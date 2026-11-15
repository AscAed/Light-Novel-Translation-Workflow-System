"""Create and verify local approvals for translation mapping plans."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import open_regular_file, write_new_child_text


_MAX_PLAN_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_FIELDS = (
    "schema_version",
    "work_id",
    "source_root",
    "catalog",
    "manifest",
    "translation_root",
    "episode_count",
)
_EPISODE_FIELDS = (
    "episode_id",
    "position",
    "title",
    "source_file",
    "source_version_id",
    "translation_file",
    "tm_key",
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "plan_sha256",
        "work_id",
        "episode_count",
        "approved_by",
        "approved_at_utc",
    }
)


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Approval input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_json_file(path: str | Path, limit: int, label: str) -> dict:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"{label} exceeds the configured size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object.")
    return value


def _require_text(value, field: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Approval input has an invalid {field}.")
    return value


def _require_sha256(value, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"Approval input has an invalid {field}.")
    return value


def _validate_plan_shape(plan: dict) -> list[dict]:
    if (
        isinstance(plan.get("schema_version"), bool)
        or plan.get("schema_version") != 1
    ):
        raise ValueError("Translation plan schema version is unsupported.")
    for field in _PLAN_FIELDS:
        if field not in plan:
            raise ValueError(f"Translation plan is missing {field}.")
    for field in (
        "work_id",
        "source_root",
        "catalog",
        "manifest",
        "translation_root",
    ):
        _require_text(plan[field], field)

    episode_count = plan["episode_count"]
    episodes = plan.get("episodes")
    if (
        isinstance(episode_count, bool)
        or not isinstance(episode_count, int)
        or episode_count < 1
        or not isinstance(episodes, list)
        or len(episodes) != episode_count
    ):
        raise ValueError("Translation plan episode count is invalid.")

    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("Translation plan contains an invalid episode.")
        if any(field not in episode for field in _EPISODE_FIELDS):
            raise ValueError("Translation plan episode mapping is incomplete.")
        for field in (
            "episode_id",
            "title",
            "translation_file",
            "tm_key",
        ):
            _require_text(episode[field], field, maximum=4096)
        for field in ("source_file", "source_version_id"):
            if episode[field] is not None:
                _require_text(episode[field], field, maximum=4096)
        position = episode["position"]
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
        ):
            raise ValueError("Translation plan contains an invalid position.")
    return episodes


def translation_plan_sha256(plan: dict) -> str:
    """Hash only stable source-to-output mapping identity, not run state."""
    episodes = _validate_plan_shape(plan)
    identity = {field: plan[field] for field in _PLAN_FIELDS}
    identity["episodes"] = [
        {field: episode[field] for field in _EPISODE_FIELDS}
        for episode in episodes
    ]
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_translation_plan(path: str | Path) -> dict:
    plan = _read_json_file(path, _MAX_PLAN_BYTES, "Translation plan")
    expected = translation_plan_sha256(plan)
    recorded = _require_sha256(plan.get("plan_sha256"), "plan_sha256")
    if not hmac.compare_digest(recorded, expected):
        raise ValueError("Translation plan digest does not match its mapping.")
    return plan


def _require_approvable_plan(plan: dict) -> str:
    digest = translation_plan_sha256(plan)
    recorded = _require_sha256(plan.get("plan_sha256"), "plan_sha256")
    if not hmac.compare_digest(recorded, digest):
        raise ValueError("Translation plan digest does not match its mapping.")
    episodes = _validate_plan_shape(plan)
    if (
        plan.get("status") != "ready_for_review"
        or plan.get("issues") != []
        or not _all_sources_verified(plan, len(episodes))
    ):
        raise ValueError("Only a fully verified translation plan can be approved.")
    if any(
        episode["source_file"] is None
        or episode["source_version_id"] is None
        for episode in episodes
    ):
        raise ValueError("Every approved episode must have a verified source.")
    return digest


def _all_sources_verified(plan: dict, episode_count: int) -> bool:
    verified_count = plan.get("verified_source_count")
    return (
        isinstance(verified_count, int)
        and not isinstance(verified_count, bool)
        and verified_count == episode_count
    )


def create_approval_receipt(plan: dict, approved_by: str) -> dict:
    digest = _require_approvable_plan(plan)
    reviewer = _require_text(approved_by, "approved_by", maximum=200)
    return {
        "schema_version": 1,
        "plan_sha256": digest,
        "work_id": plan["work_id"],
        "episode_count": plan["episode_count"],
        "approved_by": reviewer,
        "approved_at_utc": (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        ),
    }


def verify_approval_receipt(path: str | Path, plan: dict) -> dict:
    """Verify a local receipt against a current plan, allowing safe resume state."""
    digest = translation_plan_sha256(plan)
    recorded = _require_sha256(plan.get("plan_sha256"), "plan_sha256")
    if not hmac.compare_digest(recorded, digest):
        raise ValueError("Current translation plan digest is invalid.")

    episodes = _validate_plan_shape(plan)
    issues = plan.get("issues")
    ready = (
        plan.get("status") == "ready_for_review"
        and issues == []
        and _all_sources_verified(plan, len(episodes))
    )
    resumable = (
        plan.get("status") == "blocked"
        and isinstance(issues, list)
        and bool(issues)
        and all(
            isinstance(issue, dict)
            and issue.get("code") == "translation_target_exists"
            for issue in issues
        )
        and _all_sources_verified(plan, len(episodes))
    )
    if not (ready or resumable) or any(
        episode["source_file"] is None
        or episode["source_version_id"] is None
        for episode in episodes
    ):
        raise ValueError("Current translation plan is not safe to execute.")

    receipt = _read_json_file(path, _MAX_RECEIPT_BYTES, "Approval receipt")
    if set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("Approval receipt fields do not match schema v1.")
    if (
        isinstance(receipt.get("schema_version"), bool)
        or receipt.get("schema_version") != 1
    ):
        raise ValueError("Approval receipt schema version is unsupported.")
    receipt_digest = _require_sha256(
        receipt.get("plan_sha256"), "plan_sha256"
    )
    if not hmac.compare_digest(receipt_digest, digest):
        raise ValueError("Approval receipt does not match the current plan.")
    if (
        receipt.get("work_id") != plan["work_id"]
        or isinstance(receipt.get("episode_count"), bool)
        or receipt.get("episode_count") != plan["episode_count"]
    ):
        raise ValueError("Approval receipt scope does not match the current plan.")
    _require_text(receipt.get("approved_by"), "approved_by", maximum=200)
    approved_at = _require_text(
        receipt.get("approved_at_utc"),
        "approved_at_utc",
        maximum=64,
    )
    try:
        parsed_at = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Approval timestamp is invalid.") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() != timedelta(0):
        raise ValueError("Approval timestamp must be an explicit UTC time.")
    return receipt


def write_new_json(path: str | Path, value: dict) -> None:
    target = Path(path)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    write_new_child_text(str(target.parent), target.name, content)
