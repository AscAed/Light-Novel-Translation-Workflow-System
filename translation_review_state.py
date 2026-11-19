"""Policy-neutral transitions for synthetic final-review workflows."""

import errno
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
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
_MAX_DECISION_BYTES = 256 * 1024


def decide_review_transition(
    stage_verdicts: Mapping[str, Sequence[str]],
    *,
    rework_attempts_used: int,
    max_rework_attempts: int,
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
    max_rework_attempts: int,
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
    )
    normalized_verdicts = {
        stage: list(stage_verdicts[stage]) for stage in REVIEW_STAGES
    }
    record = {
        "schema_version": 1,
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
    record["decision_sha256"] = _decision_sha256(record)
    return record


def verify_review_decision_record(record: dict) -> dict:
    """Recompute a decision receipt and reject edits or invalid lineage."""
    if not isinstance(record, dict) or set(record) != _DECISION_FIELDS:
        raise ValueError("Review decision fields do not match schema v1.")
    if isinstance(record.get("schema_version"), bool) or record.get(
        "schema_version"
    ) != 1:
        raise ValueError("Review decision schema version is unsupported.")
    expected = create_review_decision_record(
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
        max_rework_attempts=record["max_rework_attempts"],
    )
    if expected != record:
        raise ValueError("Review decision digest or transition is invalid.")
    return expected


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

            if os.fstat(descriptor).st_size == 0:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
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


def load_review_decision_chain(
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

    first = records[0]
    stable_fields = {
        "run_id": first["run_id"],
        "work_id": first["work_id"],
        "episode_id": first["episode_id"],
        "source_version_id": first["source_version_id"],
        "source_sha256": first["source_sha256"],
        "policy_sha256": first["policy_sha256"],
        "max_rework_attempts": first["max_rework_attempts"],
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
            if previous is None or previous["transition"]["status"] != "rework":
                raise ValueError(
                    "A new review decision requires a rework transition."
                )
            if record["parent_candidate_sha256"] != previous["candidate_sha256"]:
                raise ValueError("Review decision parent digest does not match.")
        previous = record
    return records


def write_review_decision(
    run_directory: str | Path,
    record: dict,
) -> dict:
    """Create one verified decision file without overwriting an existing record."""
    verified = verify_review_decision_record(record)
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
        existing = load_review_decision_chain(
            run_directory,
            episode_id=verified["episode_id"],
            expected_run_id=verified["run_id"],
            expected_work_id=verified["work_id"],
            expected_source_version_id=verified["source_version_id"],
            expected_source_sha256=verified["source_sha256"],
        )
        if existing:
            previous = existing[-1]
            if verified["candidate_sha256"] in {
                decision["candidate_sha256"] for decision in existing
            }:
                raise ValueError("Review decision chain reuses a candidate digest.")
            if previous["transition"]["status"] != "rework":
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
                != previous["max_rework_attempts"]
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
