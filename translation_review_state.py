"""Policy-neutral transitions for synthetic final-review workflows."""

import asyncio
import errno
import hashlib
import hmac
import json
import os
import re
import stat
import time
from contextlib import asynccontextmanager, contextmanager
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath

from utils import (
    open_regular_file,
    resolve_relative_path,
    write_new_child_bytes_atomically,
)


REVIEW_STAGES = ("fidelity", "fluency", "style")
REVIEW_VERDICTS = frozenset({"pass", "fail", "inconclusive"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_ISSUE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+){0,7}\Z")
_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "work_id",
        "episode_id",
        "source_version_id",
        "source_sha256",
        "candidate_revision",
        "candidate_relative_path",
        "parent_candidate_sha256",
        "candidate_sha256",
        "policy_sha256",
        "reviewer_id",
        "reviewed_at_utc",
        "stage_verdicts",
        "max_rework_attempts",
        "transition",
        "decision_sha256",
    }
)
_DECISION_FIELDS_V1 = _DECISION_FIELDS
_DECISION_FIELDS_V2 = _DECISION_FIELDS | {"issue_codes_by_stage"}
_DECISION_FIELDS_V3 = _DECISION_FIELDS_V2 | {"policy_relative_path"}
_DECISION_FIELDS_V4 = _DECISION_FIELDS_V3 | {"final_review_gate"}
_RESOLUTION_FIELDS = frozenset(
    {
        "schema_version",
        "resolution_revision",
        "run_id",
        "work_id",
        "episode_id",
        "source_version_id",
        "source_sha256",
        "candidate_revision",
        "candidate_relative_path",
        "candidate_sha256",
        "policy_sha256",
        "decision_sha256",
        "action",
        "reviewer_id",
        "reviewed_at_utc",
        "rationale",
        "blocking_stages",
        "previous_max_rework_attempts",
        "new_max_rework_attempts",
        "parent_resolution_sha256",
        "resolution_sha256",
    }
)
_MAX_DECISION_BYTES = 256 * 1024
_MAX_REVIEW_POLICY_BYTES = 128 * 1024
_REVIEW_POLICY_FIELDS = frozenset(
    {"schema_version", "policy_id", "revision", "issue_codes"}
)
_REVIEW_POLICY_ENTRY_FIELDS = frozenset({"code", "stages", "definition"})
_POLICY_ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+){0,15}\Z")


def decide_review_transition(
    stage_verdicts: Mapping[str, Sequence[str]],
    *,
    rework_attempts_used: int,
    max_rework_attempts: int,
    final_review_gate: Mapping[str, str] | None = None,
) -> dict:
    """Return a fail-closed transition without choosing quality thresholds."""
    for name, value in (
        ("rework_attempts_used", rework_attempts_used),
        ("max_rework_attempts", max_rework_attempts),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")
    if rework_attempts_used > max_rework_attempts:
        raise ValueError("Rework attempts used exceed the configured maximum.")
    if not isinstance(stage_verdicts, Mapping):
        raise ValueError("Stage verdicts must be a mapping.")
    if set(stage_verdicts) != set(REVIEW_STAGES):
        raise ValueError("Stage verdicts must cover fidelity, fluency, and style.")
    if final_review_gate is None:
        final_review_gate = {
            "convergence": "pass",
            "publication_checks": "pass",
        }
    if (
        not isinstance(final_review_gate, Mapping)
        or set(final_review_gate) != {"convergence", "publication_checks"}
        or any(
            not isinstance(value, str)
            or value not in {"pass", "inconclusive"}
            for value in final_review_gate.values()
        )
    ):
        raise ValueError("Final review gates must be pass or inconclusive.")

    normalized: dict[str, list[str]] = {}
    for stage in REVIEW_STAGES:
        values = stage_verdicts[stage]
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError(f"{stage} verdicts must be a sequence.")
        if any(
            not isinstance(value, str) or value not in REVIEW_VERDICTS
            for value in values
        ):
            raise ValueError(f"{stage} contains an unsupported verdict.")
        normalized[stage] = list(values)

    conflicts = [
        stage
        for stage, values in normalized.items()
        if len(set(values)) > 1
    ]
    missing = [
        stage for stage, values in normalized.items() if not values
    ]
    inconclusive = [
        stage
        for stage, values in normalized.items()
        if values and values[0] == "inconclusive"
    ]
    failures = [
        stage
        for stage, values in normalized.items()
        if values and values[0] == "fail"
    ]

    status = "passed"
    reason = "all_stages_passed"
    next_rework_attempt = None
    blocking_stages: list[str] = []

    if conflicts:
        status = "needs_human"
        reason = "conflicting_verdicts"
        blocking_stages = conflicts
    elif missing:
        status = "needs_human"
        reason = "missing_verdicts"
        blocking_stages = missing
    elif inconclusive:
        status = "needs_human"
        reason = "inconclusive_verdict"
        blocking_stages = inconclusive
    elif failures and rework_attempts_used < max_rework_attempts:
        status = "rework"
        reason = "quality_failure"
        next_rework_attempt = rework_attempts_used + 1
        blocking_stages = failures
    elif failures:
        status = "needs_human"
        reason = "rework_limit_reached"
        blocking_stages = failures
    elif any(value == "inconclusive" for value in final_review_gate.values()):
        status = "needs_human"
        reason = "final_review_gate_inconclusive"
        blocking_stages = list(REVIEW_STAGES)

    return {
        "status": status,
        "reason": reason,
        "publishable": status == "passed",
        "rework_attempts_used": rework_attempts_used,
        "max_rework_attempts": max_rework_attempts,
        "next_rework_attempt": next_rework_attempt,
        "blocking_stages": blocking_stages,
    }


def _require_text(value, field: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Review decision has an invalid {field}.")
    return value


def _require_sha256(value, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"Review decision has an invalid {field}.")
    return value


def _require_candidate_relative_path(value, *, episode_id: str, revision: int) -> str:
    path = _require_text(value, "candidate_relative_path")
    parts = path.split("/")
    if (
        "\\" in path
        or path.startswith("/")
        or PureWindowsPath(path).drive
        or any(part in {"", ".", ".."} or ":" in part for part in parts)
    ):
        raise ValueError("Review decision candidate path must be run-relative.")
    if revision == 0:
        if len(parts) < 2 or parts[0] != "Drafts":
            raise ValueError("Initial review candidate must be in Drafts.")
    elif (
        len(parts) < 3
        or parts[0] != "ReviewCandidates"
        or parts[1] != episode_id
    ):
        raise ValueError(
            "Rework candidates must be in the episode ReviewCandidates directory."
        )
    return path


def _validate_reviewed_at_utc(value) -> str:
    timestamp = _require_text(value, "reviewed_at_utc", maximum=64)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Review decision timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Review decision timestamp must be UTC.")
    return timestamp


def _decision_sha256(record: dict) -> str:
    identity = {
        key: value
        for key, value in record.items()
        if key != "decision_sha256"
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _normalize_issue_codes_by_stage(
    stage_verdicts: Mapping[str, Sequence[str]],
    issue_codes_by_stage: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    if issue_codes_by_stage is None:
        issue_codes_by_stage = {stage: [] for stage in REVIEW_STAGES}
    if not isinstance(issue_codes_by_stage, Mapping) or set(
        issue_codes_by_stage
    ) != set(REVIEW_STAGES):
        raise ValueError("Issue codes must cover fidelity, fluency, and style.")

    normalized = {}
    for stage in REVIEW_STAGES:
        codes = issue_codes_by_stage[stage]
        if not isinstance(codes, Sequence) or isinstance(codes, (str, bytes)):
            raise ValueError(f"{stage} issue codes must be a sequence.")
        if len(codes) > 64 or any(
            not isinstance(code, str)
            or len(code) > 64
            or not _ISSUE_CODE_PATTERN.fullmatch(code)
            for code in codes
        ):
            raise ValueError(f"{stage} contains an invalid issue code.")
        if len(set(codes)) != len(codes):
            raise ValueError(f"{stage} contains duplicate issue codes.")

        verdicts = stage_verdicts[stage]
        if "fail" in verdicts and not codes:
            raise ValueError(
                f"{stage} failed verdicts require at least one issue code."
            )
        if verdicts and set(verdicts) == {"pass"} and codes:
            raise ValueError(
                f"{stage} passing verdicts must not include issue codes."
            )
        normalized[stage] = sorted(codes)
    return normalized


def _reject_duplicate_json_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Review policy contains a duplicate JSON field.")
        value[key] = item
    return value


def _reject_non_finite_json_constant(_value):
    raise ValueError("Review policy contains a non-finite JSON value.")


def _parse_review_policy_bytes(content: bytes) -> tuple[dict, str]:
    if not isinstance(content, bytes) or not content:
        raise ValueError("Review policy must be non-empty UTF-8 JSON.")
    if len(content) > _MAX_REVIEW_POLICY_BYTES:
        raise ValueError("Review policy exceeds the configured size limit.")
    try:
        policy = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Review policy must be valid UTF-8 JSON.") from exc
    _validate_review_policy(policy)
    return policy, hashlib.sha256(content).hexdigest()


def _validate_review_policy(policy: dict) -> dict:
    if not isinstance(policy, dict) or set(policy) != _REVIEW_POLICY_FIELDS:
        raise ValueError("Review policy fields do not match schema v1.")
    if isinstance(policy["schema_version"], bool) or policy["schema_version"] != 1:
        raise ValueError("Review policy schema version is unsupported.")
    policy_id = policy["policy_id"]
    if not isinstance(policy_id, str) or not _POLICY_ID_PATTERN.fullmatch(policy_id):
        raise ValueError("Review policy has an invalid policy_id.")
    revision = policy["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Review policy revision must be a positive integer.")
    entries = policy["issue_codes"]
    if not isinstance(entries, list) or not entries or len(entries) > 512:
        raise ValueError("Review policy must define 1 to 512 issue codes.")

    seen_codes = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _REVIEW_POLICY_ENTRY_FIELDS:
            raise ValueError("Review policy issue entry fields are invalid.")
        code = entry["code"]
        if (
            not isinstance(code, str)
            or len(code) > 64
            or not _ISSUE_CODE_PATTERN.fullmatch(code)
            or code in seen_codes
        ):
            raise ValueError("Review policy contains an invalid or duplicate code.")
        seen_codes.add(code)
        stages = entry["stages"]
        if (
            not isinstance(stages, list)
            or not stages
            or any(
                not isinstance(stage, str) or stage not in REVIEW_STAGES
                for stage in stages
            )
            or len(set(stages)) != len(stages)
            or stages
            != [stage for stage in REVIEW_STAGES if stage in stages]
        ):
            raise ValueError("Review policy issue stages are invalid.")
        definition = entry["definition"]
        if (
            not isinstance(definition, str)
            or not definition
            or definition.strip() != definition
            or len(definition) > 2000
            or any(
                ord(character) < 32 and character not in "\t\n\r"
                for character in definition
            )
        ):
            raise ValueError("Review policy issue definition is invalid.")
    return policy


def _validate_policy_issue_codes(
    policy: dict,
    issue_codes_by_stage: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    definitions = {
        entry["code"]: set(entry["stages"])
        for entry in policy["issue_codes"]
    }
    if issue_codes_by_stage is None:
        normalized = {stage: [] for stage in REVIEW_STAGES}
    else:
        if (
            not isinstance(issue_codes_by_stage, Mapping)
            or set(issue_codes_by_stage) != set(REVIEW_STAGES)
        ):
            raise ValueError(
                "Issue codes must cover fidelity, fluency, and style."
            )
        normalized = issue_codes_by_stage
    normalized = _normalize_issue_codes_by_stage(
        {
            stage: ["fail"] if normalized[stage] else ["pass"]
            for stage in REVIEW_STAGES
        },
        normalized,
    )
    for stage, codes in normalized.items():
        for code in codes:
            if code not in definitions or stage not in definitions[code]:
                raise ValueError(
                    f"{stage} issue code is not declared for this review policy."
                )
    return normalized


def _verify_policy_bound_decision(run_root: Path, record: dict) -> dict:
    if record["schema_version"] not in {3, 4}:
        return record
    policy = _load_review_policy_artifact(
        run_root,
        policy_sha256=record["policy_sha256"],
        policy_relative_path=record["policy_relative_path"],
    )
    _validate_policy_issue_codes(policy, record["issue_codes_by_stage"])
    return record


def _review_policy_relative_path(policy_sha256: str) -> str:
    return f"ReviewPolicies/{policy_sha256}.json"


def _load_review_policy_artifact(
    run_root: Path,
    *,
    policy_sha256: str,
    policy_relative_path: str,
) -> dict:
    expected_path = _review_policy_relative_path(policy_sha256)
    if policy_relative_path != expected_path:
        raise ValueError("Review decision policy path does not match its digest.")
    path = resolve_relative_path(str(run_root), policy_relative_path)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_REVIEW_POLICY_BYTES + 1)
    policy, actual_sha256 = _parse_review_policy_bytes(content)
    if not hmac.compare_digest(actual_sha256, policy_sha256):
        raise ValueError("Review policy artifact digest is invalid.")
    return policy


def read_review_policy_file(path: str | Path) -> tuple[bytes, str, dict]:
    """Read and validate a reviewer-supplied policy without following links."""
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_REVIEW_POLICY_BYTES + 1)
    policy, policy_sha256 = _parse_review_policy_bytes(content)
    return content, policy_sha256, policy


def store_review_policy_artifact(
    run_directory: str | Path,
    content: bytes,
    *,
    issue_codes_by_stage: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, str, dict]:
    """Validate and create an immutable, content-addressed run policy artifact."""
    policy, policy_sha256 = _parse_review_policy_bytes(content)
    _validate_policy_issue_codes(policy, issue_codes_by_stage)
    relative_path = _review_policy_relative_path(policy_sha256)
    run_root = Path(run_directory).resolve(strict=True)
    policy_root = run_root / "ReviewPolicies"
    if policy_root.is_symlink():
        raise ValueError("Review policy root must not be a symbolic link.")
    policy_root.mkdir(exist_ok=True)
    target = resolve_relative_path(
        str(run_root),
        relative_path,
        allow_missing=True,
    )
    if target.exists():
        with open_regular_file(target, binary=True) as stream:
            existing = stream.read(_MAX_REVIEW_POLICY_BYTES + 1)
        if existing != content:
            raise ValueError("Existing review policy artifact does not match.")
    else:
        try:
            write_new_child_bytes_atomically(
                str(policy_root),
                f"{policy_sha256}.json",
                content,
            )
        except FileExistsError:
            with open_regular_file(target, binary=True) as stream:
                existing = stream.read(_MAX_REVIEW_POLICY_BYTES + 1)
            if existing != content:
                raise ValueError("Existing review policy artifact does not match.")
    return relative_path, policy_sha256, policy


def _build_review_decision_record(
    *,
    schema_version: int,
    run_id: str,
    work_id: str,
    episode_id: str,
    source_version_id: str,
    source_sha256: str,
    candidate_revision: int,
    candidate_relative_path: str,
    parent_candidate_sha256: str | None,
    candidate_sha256: str,
    policy_sha256: str,
    reviewer_id: str,
    reviewed_at_utc: str,
    stage_verdicts: Mapping[str, Sequence[str]],
    issue_codes_by_stage: Mapping[str, Sequence[str]] | None,
    policy_relative_path: str | None = None,
    final_review_gate: Mapping[str, str] | None = None,
    max_rework_attempts: int = 2,
) -> dict:
    """Build a content-free decision receipt bound to one candidate version."""
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Review decision has an invalid run_id.")
    for field, value in (
        ("work_id", work_id),
        ("episode_id", episode_id),
        ("source_version_id", source_version_id),
    ):
        _require_text(value, field)
    for field, value in (
        ("source_sha256", source_sha256),
        ("candidate_sha256", candidate_sha256),
        ("policy_sha256", policy_sha256),
    ):
        _require_sha256(value, field)
    _require_text(reviewer_id, "reviewer_id", maximum=200)
    _validate_reviewed_at_utc(reviewed_at_utc)
    if (
        isinstance(candidate_revision, bool)
        or not isinstance(candidate_revision, int)
        or candidate_revision < 0
    ):
        raise ValueError("Review decision has an invalid candidate_revision.")
    _require_candidate_relative_path(
        candidate_relative_path,
        episode_id=episode_id,
        revision=candidate_revision,
    )
    if candidate_revision == 0:
        if parent_candidate_sha256 is not None:
            raise ValueError("Initial candidate must not have a parent digest.")
    else:
        _require_sha256(parent_candidate_sha256, "parent_candidate_sha256")
        if parent_candidate_sha256 == candidate_sha256:
            raise ValueError("A rework candidate must differ from its parent.")

    transition = decide_review_transition(
        stage_verdicts,
        rework_attempts_used=candidate_revision,
        max_rework_attempts=max_rework_attempts,
        final_review_gate=final_review_gate,
    )
    normalized_verdicts = {
        stage: list(stage_verdicts[stage]) for stage in REVIEW_STAGES
    }
    normalized_issue_codes = (
        _normalize_issue_codes_by_stage(stage_verdicts, issue_codes_by_stage)
        if schema_version in {2, 3, 4}
        else None
    )
    record = {
        "schema_version": schema_version,
        "run_id": run_id,
        "work_id": work_id,
        "episode_id": episode_id,
        "source_version_id": source_version_id,
        "source_sha256": source_sha256,
        "candidate_revision": candidate_revision,
        "candidate_relative_path": candidate_relative_path,
        "parent_candidate_sha256": parent_candidate_sha256,
        "candidate_sha256": candidate_sha256,
        "policy_sha256": policy_sha256,
        "reviewer_id": reviewer_id,
        "reviewed_at_utc": reviewed_at_utc,
        "stage_verdicts": normalized_verdicts,
        "max_rework_attempts": max_rework_attempts,
        "transition": transition,
    }
    if schema_version in {2, 3, 4}:
        record["issue_codes_by_stage"] = normalized_issue_codes
    if schema_version in {3, 4}:
        if policy_relative_path != _review_policy_relative_path(policy_sha256):
            raise ValueError("Review decision policy artifact path is invalid.")
        record["policy_relative_path"] = policy_relative_path
    if schema_version == 4:
        if (
            not isinstance(final_review_gate, Mapping)
            or set(final_review_gate) != {"convergence", "publication_checks"}
        ):
            raise ValueError("AI final-review gates are required for schema v4.")
        record["final_review_gate"] = dict(final_review_gate)
    record["decision_sha256"] = _decision_sha256(record)
    return record


def create_review_decision_record(
    *,
    run_id: str,
    work_id: str,
    episode_id: str,
    source_version_id: str,
    source_sha256: str,
    candidate_revision: int,
    candidate_relative_path: str,
    parent_candidate_sha256: str | None,
    candidate_sha256: str,
    policy_sha256: str,
    reviewer_id: str,
    reviewed_at_utc: str,
    stage_verdicts: Mapping[str, Sequence[str]],
    issue_codes_by_stage: Mapping[str, Sequence[str]] | None = None,
    policy_relative_path: str | None = None,
    final_review_gate: Mapping[str, str] | None = None,
    max_rework_attempts: int = 2,
) -> dict:
    """Build a hash-bound receipt with an optional immutable policy artifact."""
    if final_review_gate is not None and policy_relative_path is None:
        raise ValueError("AI final-review decisions require a bound policy file.")
    return _build_review_decision_record(
        schema_version=(
            4
            if final_review_gate is not None
            else 3 if policy_relative_path is not None else 2
        ),
        run_id=run_id,
        work_id=work_id,
        episode_id=episode_id,
        source_version_id=source_version_id,
        source_sha256=source_sha256,
        candidate_revision=candidate_revision,
        candidate_relative_path=candidate_relative_path,
        parent_candidate_sha256=parent_candidate_sha256,
        candidate_sha256=candidate_sha256,
        policy_sha256=policy_sha256,
        reviewer_id=reviewer_id,
        reviewed_at_utc=reviewed_at_utc,
        stage_verdicts=stage_verdicts,
        issue_codes_by_stage=issue_codes_by_stage,
        policy_relative_path=policy_relative_path,
        final_review_gate=final_review_gate,
        max_rework_attempts=max_rework_attempts,
    )


def verify_review_decision_record(record: dict) -> dict:
    """Recompute a decision receipt and reject edits or invalid lineage."""
    if not isinstance(record, dict):
        raise ValueError("Review decision must be an object.")
    schema_version = record.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("Review decision schema version is unsupported.")
    expected_fields = {
        1: _DECISION_FIELDS_V1,
        2: _DECISION_FIELDS_V2,
        3: _DECISION_FIELDS_V3,
        4: _DECISION_FIELDS_V4,
    }.get(schema_version)
    if expected_fields is None or set(record) != expected_fields:
        raise ValueError("Review decision schema version is unsupported.")
    expected = _build_review_decision_record(
        schema_version=schema_version,
        run_id=record["run_id"],
        work_id=record["work_id"],
        episode_id=record["episode_id"],
        source_version_id=record["source_version_id"],
        source_sha256=record["source_sha256"],
        candidate_revision=record["candidate_revision"],
        candidate_relative_path=record["candidate_relative_path"],
        parent_candidate_sha256=record["parent_candidate_sha256"],
        candidate_sha256=record["candidate_sha256"],
        policy_sha256=record["policy_sha256"],
        reviewer_id=record["reviewer_id"],
        reviewed_at_utc=record["reviewed_at_utc"],
        stage_verdicts=record["stage_verdicts"],
        issue_codes_by_stage=(
            record["issue_codes_by_stage"]
            if schema_version in {2, 3, 4}
            else None
        ),
        policy_relative_path=(
            record["policy_relative_path"]
            if schema_version in {3, 4}
            else None
        ),
        final_review_gate=(
            record["final_review_gate"] if schema_version == 4 else None
        ),
        max_rework_attempts=record["max_rework_attempts"],
    )
    if expected != record:
        raise ValueError("Review decision digest or transition is invalid.")
    return expected


def _resolution_sha256(record: dict) -> str:
    identity = {
        key: value
        for key, value in record.items()
        if key != "resolution_sha256"
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_review_resolution_record(
    decision: dict,
    *,
    resolution_revision: int,
    action: str,
    reviewer_id: str,
    reviewed_at_utc: str,
    rationale: str,
    parent_resolution_sha256: str | None,
    new_max_rework_attempts: int | None = None,
) -> dict:
    """Create an explicit human resolution without rewriting review verdicts."""
    decision = verify_review_decision_record(decision)
    transition = decision["transition"]
    if transition["status"] != "needs_human":
        raise ValueError("Only a needs_human decision can be resolved.")
    if (
        isinstance(resolution_revision, bool)
        or not isinstance(resolution_revision, int)
        or resolution_revision < 0
    ):
        raise ValueError("Review resolution revision must be non-negative.")
    if (
        not isinstance(action, str)
        or action not in {"approve_current", "increase_budget"}
    ):
        raise ValueError("Review resolution action is unsupported.")
    _require_text(reviewer_id, "reviewer_id", maximum=200)
    _validate_reviewed_at_utc(reviewed_at_utc)
    _require_text(rationale, "rationale", maximum=4000)
    blocking_stages = list(transition["blocking_stages"])
    if not blocking_stages:
        raise ValueError("A human resolution requires blocking review stages.")
    if parent_resolution_sha256 is not None:
        _require_sha256(parent_resolution_sha256, "parent_resolution_sha256")
    if action == "approve_current":
        if new_max_rework_attempts is not None:
            raise ValueError("approve_current must not change the retry budget.")
    else:
        if transition["reason"] != "rework_limit_reached":
            raise ValueError(
                "The retry budget can only be increased after it is exhausted."
            )
        if (
            isinstance(new_max_rework_attempts, bool)
            or not isinstance(new_max_rework_attempts, int)
            or new_max_rework_attempts <= decision["max_rework_attempts"]
        ):
            raise ValueError("The new retry budget must be a larger integer.")
    record = {
        "schema_version": 1,
        "resolution_revision": resolution_revision,
        "run_id": decision["run_id"],
        "work_id": decision["work_id"],
        "episode_id": decision["episode_id"],
        "source_version_id": decision["source_version_id"],
        "source_sha256": decision["source_sha256"],
        "candidate_revision": decision["candidate_revision"],
        "candidate_relative_path": decision["candidate_relative_path"],
        "candidate_sha256": decision["candidate_sha256"],
        "policy_sha256": decision["policy_sha256"],
        "decision_sha256": decision["decision_sha256"],
        "action": action,
        "reviewer_id": reviewer_id,
        "reviewed_at_utc": reviewed_at_utc,
        "rationale": rationale,
        "blocking_stages": blocking_stages,
        "previous_max_rework_attempts": decision["max_rework_attempts"],
        "new_max_rework_attempts": new_max_rework_attempts,
        "parent_resolution_sha256": parent_resolution_sha256,
    }
    record["resolution_sha256"] = _resolution_sha256(record)
    return record


def verify_review_resolution_record(record: dict) -> dict:
    if not isinstance(record, dict) or set(record) != _RESOLUTION_FIELDS:
        raise ValueError("Review resolution fields do not match schema v1.")
    if isinstance(record.get("schema_version"), bool) or record.get(
        "schema_version"
    ) != 1:
        raise ValueError("Review resolution schema version is unsupported.")
    record_identity = {
        key: record[key]
        for key in (
            "run_id",
            "work_id",
            "episode_id",
            "source_version_id",
            "source_sha256",
            "candidate_revision",
            "candidate_relative_path",
            "candidate_sha256",
            "policy_sha256",
            "decision_sha256",
            "previous_max_rework_attempts",
        )
    }
    if not isinstance(record_identity["run_id"], str) or not _RUN_ID_PATTERN.fullmatch(
        record_identity["run_id"]
    ):
        raise ValueError("Review resolution has an invalid run_id.")
    for field in ("work_id", "episode_id", "source_version_id"):
        _require_text(record_identity[field], field)
    for field in (
        "source_sha256",
        "candidate_sha256",
        "policy_sha256",
        "decision_sha256",
    ):
        _require_sha256(record_identity[field], field)
    if (
        isinstance(record_identity["candidate_revision"], bool)
        or not isinstance(record_identity["candidate_revision"], int)
        or record_identity["candidate_revision"] < 0
    ):
        raise ValueError("Review resolution candidate revision is invalid.")
    _require_candidate_relative_path(
        record_identity["candidate_relative_path"],
        episode_id=record_identity["episode_id"],
        revision=record_identity["candidate_revision"],
    )
    if (
        isinstance(record_identity["previous_max_rework_attempts"], bool)
        or not isinstance(record_identity["previous_max_rework_attempts"], int)
        or record_identity["previous_max_rework_attempts"] < 0
    ):
        raise ValueError("Review resolution retry budget is invalid.")
    if (
        not isinstance(record.get("resolution_revision"), int)
        or isinstance(record.get("resolution_revision"), bool)
        or record["resolution_revision"] < 0
    ):
        raise ValueError("Review resolution revision is invalid.")
    if (
        not isinstance(record["action"], str)
        or record["action"] not in {"approve_current", "increase_budget"}
    ):
        raise ValueError("Review resolution action is unsupported.")
    _require_text(record.get("reviewer_id"), "reviewer_id", maximum=200)
    _validate_reviewed_at_utc(record.get("reviewed_at_utc"))
    _require_text(record.get("rationale"), "rationale", maximum=4000)
    blocking_stages = record.get("blocking_stages")
    if (
        not isinstance(blocking_stages, list)
        or any(
            not isinstance(stage, str) or stage not in REVIEW_STAGES
            for stage in blocking_stages
        )
        or blocking_stages != [
            stage
            for stage in REVIEW_STAGES
            if stage in blocking_stages
        ]
        or not blocking_stages
    ):
        raise ValueError("Review resolution blocking stages are invalid.")
    if record["parent_resolution_sha256"] is not None:
        _require_sha256(
            record["parent_resolution_sha256"],
            "parent_resolution_sha256",
        )
    new_budget = record["new_max_rework_attempts"]
    if record["action"] == "approve_current":
        if new_budget is not None:
            raise ValueError("approve_current must not change the retry budget.")
    elif (
        isinstance(new_budget, bool)
        or not isinstance(new_budget, int)
        or new_budget <= record_identity["previous_max_rework_attempts"]
    ):
        raise ValueError("The new retry budget must be a larger integer.")
    if _resolution_sha256(record) != record.get("resolution_sha256"):
        raise ValueError("Review resolution digest is invalid.")
    return record


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _read_decision(path: Path) -> dict:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_DECISION_BYTES + 1)
    if len(content) > _MAX_DECISION_BYTES:
        raise ValueError("Review decision exceeds the configured size limit.")
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Review decision must be valid UTF-8 JSON.") from exc
    return verify_review_decision_record(value)


def _resolution_directory(
    run_directory: str | Path,
    episode_id: str,
) -> Path:
    _require_text(episode_id, "episode_id")
    if "/" in episode_id or "\\" in episode_id:
        raise ValueError("Review resolution episode ID must be one path component.")
    run_root = Path(run_directory).resolve(strict=True)
    if not run_root.is_dir() or run_root.is_symlink():
        raise ValueError("Review resolution run path must be a regular directory.")
    resolution_root = run_root / "ReviewResolutions"
    if resolution_root.is_symlink():
        raise ValueError("Review resolution root must not be a symbolic link.")
    if not resolution_root.exists():
        return resolution_root / episode_id
    if not resolution_root.is_dir():
        raise ValueError("Review resolution root must be a directory.")
    episode_root = resolve_relative_path(
        str(run_root),
        f"ReviewResolutions/{episode_id}",
        allow_missing=True,
    )
    if episode_root.is_symlink():
        raise ValueError("Review resolution directory must not be a symbolic link.")
    if episode_root.exists() and not episode_root.is_dir():
        raise ValueError("Review resolution path must be a directory.")
    return episode_root


def _read_resolution(path: Path) -> dict:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_DECISION_BYTES + 1)
    if len(content) > _MAX_DECISION_BYTES:
        raise ValueError("Review resolution exceeds the configured size limit.")
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Review resolution must be valid UTF-8 JSON.") from exc
    return verify_review_resolution_record(value)


def _load_review_resolution_chain(
    run_root: Path,
    episode_id: str,
    decisions: list[dict],
) -> list[dict]:
    episode_root = _resolution_directory(run_root, episode_id)
    if not episode_root.exists():
        return []
    records = []
    for path in sorted(episode_root.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError("Review resolution directory contains an invalid entry.")
        records.append(_read_resolution(path))
    return _validate_review_resolution_records(
        run_root,
        episode_id,
        decisions,
        records,
    )


def _validate_review_resolution_records(
    run_root: Path,
    episode_id: str,
    decisions: list[dict],
    records: list[dict],
) -> list[dict]:
    if not records:
        return []

    decisions_by_digest = {
        record["decision_sha256"]: (index, record)
        for index, record in enumerate(decisions)
    }
    previous = None
    previous_decision_index = -1
    approved = False
    for expected_revision, record in enumerate(records):
        if record["resolution_revision"] != expected_revision:
            raise ValueError("Review resolution revisions must be contiguous.")
        if approved:
            raise ValueError("No resolution can follow a human approval.")
        if (
            record["episode_id"] != episode_id
            or record["parent_resolution_sha256"]
            != (
                None
                if previous is None
                else previous["resolution_sha256"]
            )
        ):
            raise ValueError("Review resolution chain identity does not match.")
        match = decisions_by_digest.get(record["decision_sha256"])
        if match is None:
            raise ValueError("Review resolution references an unknown decision.")
        decision_index, decision = match
        if decision_index <= previous_decision_index:
            raise ValueError("Review resolution decisions must advance.")
        if (
            decision["transition"]["status"] != "needs_human"
            or record["run_id"] != decision["run_id"]
            or record["work_id"] != decision["work_id"]
            or record["source_version_id"] != decision["source_version_id"]
            or record["source_sha256"] != decision["source_sha256"]
            or record["candidate_revision"] != decision["candidate_revision"]
            or record["candidate_relative_path"]
            != decision["candidate_relative_path"]
            or record["candidate_sha256"] != decision["candidate_sha256"]
            or record["policy_sha256"] != decision["policy_sha256"]
            or record["previous_max_rework_attempts"]
            != decision["max_rework_attempts"]
            or record["blocking_stages"]
            != decision["transition"]["blocking_stages"]
        ):
            raise ValueError("Review resolution does not match its decision.")
        if record["action"] == "increase_budget":
            if decision["transition"]["reason"] != "rework_limit_reached":
                raise ValueError(
                    "Retry budget extension does not match an exhausted decision."
                )
        elif record["action"] == "approve_current":
            approved = True
        previous = record
        previous_decision_index = decision_index
    return records


def load_review_resolution_chain(
    run_directory: str | Path,
    *,
    episode_id: str,
) -> list[dict]:
    """Load and verify human resolutions attached to one decision chain."""
    run_root = Path(run_directory).resolve(strict=True)
    decision_root = _decision_directory(run_root, episode_id, create=False)
    if not decision_root.exists():
        return _load_review_resolution_chain(run_root, episode_id, [])
    with _lock_episode_decisions(decision_root):
        decisions = _load_review_decision_chain_unlocked(
            run_root,
            episode_id=episode_id,
        )
        return _load_review_resolution_chain(run_root, episode_id, decisions)


def write_review_resolution(
    run_directory: str | Path,
    record: dict,
) -> dict:
    """Append one explicit, create-only human resolution."""
    verified = verify_review_resolution_record(record)
    run_root = Path(run_directory).resolve(strict=True)
    decision_root = _decision_directory(
        run_root,
        verified["episode_id"],
        create=False,
    )
    if not decision_root.is_dir():
        raise ValueError("Review resolution requires an existing decision chain.")
    with _lock_episode_decisions(decision_root):
        decisions = _load_review_decision_chain_unlocked(
            run_root,
            episode_id=verified["episode_id"],
            expected_run_id=verified["run_id"],
            expected_work_id=verified["work_id"],
            expected_source_version_id=verified["source_version_id"],
            expected_source_sha256=verified["source_sha256"],
        )
        if (
            not decisions
            or decisions[-1]["decision_sha256"]
            != verified["decision_sha256"]
        ):
            raise ValueError("Review resolution must bind the latest decision.")
        existing = _load_review_resolution_chain(
            run_root,
            verified["episode_id"],
            decisions,
        )
        previous = existing[-1] if existing else None
        if (
            verified["resolution_revision"] != len(existing)
            or verified["parent_resolution_sha256"]
            != (None if previous is None else previous["resolution_sha256"])
            or (previous is not None and previous["action"] == "approve_current")
            or any(
                item["decision_sha256"] == verified["decision_sha256"]
                for item in existing
            )
        ):
            raise ValueError("Review resolution does not continue its chain.")
        _validate_review_resolution_records(
            run_root,
            verified["episode_id"],
            decisions,
            [*existing, verified],
        )
        filename = (
            f"resolution-{verified['resolution_revision']:04d}-"
            f"{verified['resolution_sha256']}.json"
        )
        episode_root = _resolution_directory(run_root, verified["episode_id"])
        episode_root.mkdir(parents=True, exist_ok=True)
        write_new_child_bytes_atomically(
            str(episode_root),
            filename,
            _canonical_json(verified).encode("utf-8"),
        )
        _load_review_resolution_chain(
            run_root,
            verified["episode_id"],
            decisions,
        )
    return {
        "status": "created",
        "path": str(episode_root / filename),
        "resolution_sha256": verified["resolution_sha256"],
        "resolution_revision": verified["resolution_revision"],
        "action": verified["action"],
        "new_max_rework_attempts": verified["new_max_rework_attempts"],
    }


def _decision_directory(
    run_directory: str | Path,
    episode_id: str,
    *,
    create: bool,
) -> Path:
    _require_text(episode_id, "episode_id")
    if "/" in episode_id or "\\" in episode_id:
        raise ValueError("Review decision episode ID must be one path component.")
    run_root = Path(run_directory).resolve(strict=True)
    if not run_root.is_dir() or run_root.is_symlink():
        raise ValueError("Review decision run path must be a regular directory.")
    decisions_root = run_root / "ReviewDecisions"
    if decisions_root.is_symlink():
        raise ValueError("Review decision root must not be a symbolic link.")
    if not decisions_root.exists():
        if not create:
            return decisions_root / episode_id
        decisions_root.mkdir(exist_ok=True)
    if not decisions_root.is_dir():
        raise ValueError("Review decision root must be a directory.")
    episode_root = resolve_relative_path(
        str(run_root),
        f"ReviewDecisions/{episode_id}",
        allow_missing=True,
    )
    if episode_root.is_symlink():
        raise ValueError("Review decision directory must not be a symbolic link.")
    if create:
        episode_root.mkdir(exist_ok=True)
    elif not episode_root.exists():
        return episode_root
    if not episode_root.is_dir():
        raise ValueError("Review decision path must be a directory.")
    return episode_root


@contextmanager
def _lock_episode_decisions(episode_root: Path):
    lock_path = episode_root / ".append.lock"
    if lock_path.is_symlink():
        raise ValueError("Review decision lock must not be a symbolic link.")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Review decision lock must be a regular file.")
        if os.name == "nt":
            import msvcrt

            while True:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if (
                        exc.errno != errno.EACCES
                        and getattr(exc, "winerror", None) != 33
                    ):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@asynccontextmanager
async def _lock_episode_workflow(run_root: Path, episode_id: str):
    """Serialize asynchronous review/rework work without blocking its event loop."""
    workflow_root = run_root / "AIWorkflowLocks"
    if workflow_root.is_symlink():
        raise ValueError("Review workflow lock root must not be a symbolic link.")
    workflow_root.mkdir(exist_ok=True)
    if not workflow_root.is_dir():
        raise ValueError("Review workflow lock root must be a directory.")
    lock_name = hashlib.sha256(episode_id.encode("utf-8")).hexdigest()
    lock_path = workflow_root / f"{lock_name}.lock"
    if lock_path.is_symlink():
        raise ValueError("Review workflow lock must not be a symbolic link.")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Review workflow lock must be a regular file.")

        while not locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                locked = True
            except OSError as exc:
                if os.name == "nt":
                    conflict = (
                        exc.errno == errno.EACCES
                        or getattr(exc, "winerror", None) == 33
                    )
                else:
                    conflict = exc.errno in {
                        errno.EACCES,
                        errno.EAGAIN,
                        getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
                    }
                if not conflict:
                    raise
                await asyncio.sleep(0.05)
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_review_decision_chain_unlocked(
    run_directory: str | Path,
    *,
    episode_id: str,
    expected_run_id: str | None = None,
    expected_work_id: str | None = None,
    expected_source_version_id: str | None = None,
    expected_source_sha256: str | None = None,
) -> list[dict]:
    """Load and verify one episode's content-free decision chain."""
    episode_root = _decision_directory(run_directory, episode_id, create=False)
    if not episode_root.exists():
        return []
    records = []
    for path in sorted(episode_root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise ValueError("Review decision files must not be symbolic links.")
        if path.name == ".append.lock":
            if not path.is_file():
                raise ValueError("Review decision lock must be a regular file.")
            continue
        if path.name.startswith(".") and path.name.endswith(".tmp"):
            if not path.is_file():
                raise ValueError(
                    "Review decision staging entries must be regular files."
                )
            continue
        if not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError("Review decision directory contains an invalid entry.")
        records.append(_read_decision(path))
    if not records:
        return []

    run_root = Path(run_directory).resolve(strict=True)
    policy_bound_records = [
        record for record in records if record["schema_version"] in {3, 4}
    ]
    if policy_bound_records:
        policy_record = policy_bound_records[0]
        policy = _load_review_policy_artifact(
            run_root,
            policy_sha256=policy_record["policy_sha256"],
            policy_relative_path=policy_record["policy_relative_path"],
        )
        for record in records:
            if record["schema_version"] in {3, 4} and (
                record["policy_relative_path"]
                != policy_record["policy_relative_path"]
            ):
                raise ValueError("Review decision chain changed policy artifact.")
            if record["schema_version"] in {2, 3, 4}:
                _validate_policy_issue_codes(
                    policy,
                    record["issue_codes_by_stage"],
                )

    first = records[0]
    stable_fields = {
        "run_id": first["run_id"],
        "work_id": first["work_id"],
        "episode_id": first["episode_id"],
        "source_version_id": first["source_version_id"],
        "source_sha256": first["source_sha256"],
        "policy_sha256": first["policy_sha256"],
    }
    if first["candidate_revision"] != 0 or first["parent_candidate_sha256"] is not None:
        raise ValueError("Review decision chain must begin at revision zero.")
    if first["episode_id"] != episode_id:
        raise ValueError("Review decision chain episode does not match its path.")
    for field, expected in (
        ("run_id", expected_run_id),
        ("work_id", expected_work_id),
        ("source_version_id", expected_source_version_id),
        ("source_sha256", expected_source_sha256),
    ):
        if expected is not None and stable_fields[field] != expected:
            raise ValueError("Review decision chain identity does not match.")

    resolutions = _load_review_resolution_chain(
        run_root,
        episode_id,
        records,
    )
    resolutions_by_decision = {
        record["decision_sha256"]: record for record in resolutions
    }
    seen_candidates = set()
    seen_candidate_paths = set()
    previous = None
    for expected_revision, record in enumerate(records):
        if record["candidate_revision"] != expected_revision:
            raise ValueError("Review decision revisions must be contiguous.")
        if any(record[field] != value for field, value in stable_fields.items()):
            raise ValueError("Review decision chain contains conflicting identity.")
        if record["candidate_sha256"] in seen_candidates:
            raise ValueError("Review decision chain reuses a candidate digest.")
        seen_candidates.add(record["candidate_sha256"])
        if record["candidate_relative_path"] in seen_candidate_paths:
            raise ValueError("Review decision chain reuses a candidate path.")
        seen_candidate_paths.add(record["candidate_relative_path"])
        if expected_revision == 0:
            if record["parent_candidate_sha256"] is not None:
                raise ValueError("Initial review decision has a parent digest.")
        else:
            if previous is None:
                raise ValueError("Review decision chain has no prior decision.")
            previous_status = previous["transition"]["status"]
            if previous_status == "rework":
                expected_budget = previous["max_rework_attempts"]
            elif previous_status == "needs_human":
                resolution = resolutions_by_decision.get(
                    previous["decision_sha256"]
                )
                if resolution is None or resolution["action"] != "increase_budget":
                    raise ValueError(
                        "A new review decision requires an explicit budget extension."
                    )
                expected_budget = resolution["new_max_rework_attempts"]
            else:
                raise ValueError(
                    "A new review decision requires a rework transition."
                )
            if record["max_rework_attempts"] != expected_budget:
                raise ValueError("Review decision retry budget does not match policy.")
            if record["parent_candidate_sha256"] != previous["candidate_sha256"]:
                raise ValueError("Review decision parent digest does not match.")
        previous = record
    return records


def load_review_decision_chain(
    run_directory: str | Path,
    *,
    episode_id: str,
    expected_run_id: str | None = None,
    expected_work_id: str | None = None,
    expected_source_version_id: str | None = None,
    expected_source_sha256: str | None = None,
) -> list[dict]:
    """Load a decision chain and its resolutions from one locked snapshot."""
    episode_root = _decision_directory(
        run_directory,
        episode_id,
        create=False,
    )
    if not episode_root.exists():
        return []
    with _lock_episode_decisions(episode_root):
        return _load_review_decision_chain_unlocked(
            run_directory,
            episode_id=episode_id,
            expected_run_id=expected_run_id,
            expected_work_id=expected_work_id,
            expected_source_version_id=expected_source_version_id,
            expected_source_sha256=expected_source_sha256,
        )


def write_review_decision(
    run_directory: str | Path,
    record: dict,
) -> dict:
    """Create one verified decision file without overwriting an existing record."""
    verified = verify_review_decision_record(record)
    run_root = Path(run_directory).resolve(strict=True)
    _verify_policy_bound_decision(run_root, verified)
    filename = (
        f"revision-{verified['candidate_revision']:04d}-"
        f"{verified['decision_sha256']}.json"
    )
    episode_root = _decision_directory(
        run_directory,
        verified["episode_id"],
        create=True,
    )
    with _lock_episode_decisions(episode_root):
        existing_path = episode_root / filename
        if existing_path.is_symlink():
            raise ValueError("Review decision files must not be symbolic links.")
        if existing_path.exists():
            raise FileExistsError("Review decision already exists.")
        existing = _load_review_decision_chain_unlocked(
            run_directory,
            episode_id=verified["episode_id"],
            expected_run_id=verified["run_id"],
            expected_work_id=verified["work_id"],
            expected_source_version_id=verified["source_version_id"],
            expected_source_sha256=verified["source_sha256"],
        )
        if existing:
            if verified["schema_version"] in {3, 4}:
                if verified["policy_sha256"] != existing[-1]["policy_sha256"]:
                    raise ValueError(
                        "Review decision policy changed within one chain."
                    )
                policy = _load_review_policy_artifact(
                    Path(run_directory).resolve(strict=True),
                    policy_sha256=verified["policy_sha256"],
                    policy_relative_path=verified["policy_relative_path"],
                )
                for item in existing:
                    if item["schema_version"] in {2, 3, 4}:
                        _validate_policy_issue_codes(
                            policy,
                            item["issue_codes_by_stage"],
                        )
            previous = existing[-1]
            if (
                any(item["schema_version"] in {3, 4} for item in existing)
                and verified["schema_version"] not in {3, 4}
            ):
                raise ValueError(
                    "A policy-bound decision chain must remain policy-bound."
                )
            if verified["candidate_sha256"] in {
                decision["candidate_sha256"] for decision in existing
            }:
                raise ValueError("Review decision chain reuses a candidate digest.")
            previous_status = previous["transition"]["status"]
            if previous_status == "rework":
                expected_budget = previous["max_rework_attempts"]
            elif previous_status == "needs_human":
                resolutions = _load_review_resolution_chain(
                    run_root,
                    verified["episode_id"],
                    existing,
                )
                resolution = next(
                    (
                        item
                        for item in reversed(resolutions)
                        if item["decision_sha256"]
                        == previous["decision_sha256"]
                    ),
                    None,
                )
                if resolution is None or resolution["action"] != "increase_budget":
                    raise ValueError(
                        "A new review decision requires an explicit budget extension."
                    )
                expected_budget = resolution["new_max_rework_attempts"]
            else:
                raise ValueError(
                    "A new review decision requires a rework transition."
                )
            if (
                verified["candidate_revision"]
                != previous["candidate_revision"] + 1
                or verified["parent_candidate_sha256"]
                != previous["candidate_sha256"]
                or verified["policy_sha256"] != previous["policy_sha256"]
                or verified["max_rework_attempts"]
                != expected_budget
                or verified["candidate_relative_path"]
                in {item["candidate_relative_path"] for item in existing}
            ):
                raise ValueError("Review decision does not continue its chain.")
        elif (
            verified["candidate_revision"] != 0
            or verified["parent_candidate_sha256"] is not None
        ):
            raise ValueError("Review decision chain must begin at revision zero.")
        write_new_child_bytes_atomically(
            str(episode_root),
            filename,
            _canonical_json(verified).encode("utf-8"),
        )
    return {
        "status": "created",
        "path": str(episode_root / filename),
        "decision_sha256": verified["decision_sha256"],
        "candidate_revision": verified["candidate_revision"],
    }
