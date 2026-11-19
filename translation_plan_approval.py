"""Create and verify local approvals for translation mapping plans."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import (
    open_regular_file,
    resolve_relative_path,
    write_new_child_text,
)
from source_ingestion import source_artifact_id
from source_editions import verify_ai_edition_index


_MAX_PLAN_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024
_MAX_HUMAN_EDITION_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_HUMAN_EDITION_FILE_BYTES = 16 * 1024 * 1024
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
    "source_input_file",
    "source_sha256",
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
_RECEIPT_FIELDS_V2 = _RECEIPT_FIELDS | {"review_sha256"}
_REVIEW_DECISIONS = frozenset({"pending", "pass", "fail"})
_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "plan_sha256",
        "work_id",
        "episode_count",
        "ai_index_sha256",
        "human_index_sha256",
        "episodes",
    }
)
_REVIEW_EPISODE_FIELDS = frozenset(
    {
        "episode_id",
        "position",
        "title",
        "source_version_id",
        "source_input_file",
        "source_sha256",
        "translation_file",
        "tm_key",
        "human_relative_path",
        "human_output_sha256",
        "mapping_decision",
        "ai_edition_decision",
        "human_edition_decision",
        "issues",
        "notes",
    }
)


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Approval input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_json_file_with_bytes(
    path: str | Path,
    limit: int,
    label: str,
) -> tuple[dict, bytes]:
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
    return value, content


def _read_json_file(path: str | Path, limit: int, label: str) -> dict:
    value, _ = _read_json_file_with_bytes(path, limit, label)
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


def _require_review_notes(value) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or len(value) > 4096
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("Approval input has an invalid review notes.")
    return value


def _validate_plan_shape(plan: dict) -> list[dict]:
    if (
        isinstance(plan.get("schema_version"), bool)
        or plan.get("schema_version") != 2
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
    if "source_edition" in plan and plan["source_edition"] is not None:
        source_edition = plan["source_edition"]
        expected_source_edition_fields = {
            "profile_id",
            "index_root",
            "index_relative_path",
            "index_sha256",
            "manifest",
            "manifest_sha256",
        }
        if (
            not isinstance(source_edition, dict)
            or set(source_edition) != expected_source_edition_fields
        ):
            raise ValueError("Translation plan source edition is invalid.")
        for field in (
            "profile_id",
            "index_root",
            "index_relative_path",
            "manifest",
        ):
            _require_text(source_edition[field], field, maximum=4096)
        for field in ("index_sha256", "manifest_sha256"):
            _require_sha256(source_edition[field], field)

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
        for field in (
            "source_file",
            "source_version_id",
            "source_input_file",
        ):
            if episode[field] is not None:
                _require_text(episode[field], field, maximum=4096)
        if episode["source_sha256"] is not None:
            _require_sha256(episode["source_sha256"], "source_sha256")
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
    if "source_edition" in plan:
        identity["source_edition"] = plan["source_edition"]
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


def _load_human_edition_index(
    path: str | Path,
    *,
    work_id: str,
    episodes: list[dict],
) -> tuple[dict, str]:
    index, index_bytes = _read_json_file_with_bytes(
        path,
        _MAX_PLAN_BYTES,
        "Human edition index",
    )
    if (
        index.get("schema_version") != 2
        or index.get("edition") != "human_reading"
        or index.get("work_id") != work_id
        or not isinstance(index.get("episodes"), list)
    ):
        raise ValueError("Human edition index is not a supported edition map.")
    indexed = {}
    total_output_bytes = 0
    for item in index["episodes"]:
        if not isinstance(item, dict):
            raise ValueError("Human edition index contains an invalid episode.")
        episode_id = item.get("episode_id")
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError("Human edition index contains an invalid episode ID.")
        if episode_id in indexed:
            raise ValueError("Human edition index contains duplicate episodes.")
        for field in (
            "title",
            "human_relative_path",
            "human_edition_artifact_id",
            "human_edition_version_id",
            "human_archive_relative_path",
            "edition_input_version_id",
        ):
            _require_text(item.get(field), field, maximum=4096)
        position = item.get("position")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
        ):
            raise ValueError("Human edition index contains an invalid position.")
        output_sha256 = _require_sha256(
            item.get("output_sha256"),
            "human output_sha256",
        )
        human_path = resolve_relative_path(
            str(Path(path).parent),
            item["human_relative_path"],
        )
        with open_regular_file(human_path, binary=True) as stream:
            output_bytes = stream.read(_MAX_HUMAN_EDITION_FILE_BYTES + 1)
        if len(output_bytes) > _MAX_HUMAN_EDITION_FILE_BYTES:
            raise ValueError("Human edition output exceeds the configured byte limit.")
        total_output_bytes += len(output_bytes)
        if total_output_bytes > _MAX_HUMAN_EDITION_TOTAL_BYTES:
            raise ValueError(
                "Human edition outputs exceed the configured total byte limit."
            )
        if not hmac.compare_digest(
            hashlib.sha256(output_bytes).hexdigest(),
            output_sha256,
        ):
            raise ValueError("Human edition output hash does not match its index.")
        indexed[episode_id] = item

    if set(indexed) != {episode["episode_id"] for episode in episodes}:
        raise ValueError("Human edition index does not cover the translation plan.")
    for episode in episodes:
        item = indexed[episode["episode_id"]]
        if (
            item["position"] != episode["position"]
            or item["title"] != episode["title"]
        ):
            raise ValueError("Human edition index mapping differs from the plan.")
    return index, hashlib.sha256(index_bytes).hexdigest()


def _verify_human_edition_lineage(
    plan: dict,
    human_index: dict,
    episodes: list[dict],
) -> None:
    source_edition = plan.get("source_edition")
    if not isinstance(source_edition, dict):
        raise ValueError("A dual-edition review requires an AI source edition.")
    ai_result = verify_ai_edition_index(
        source_root=plan["source_root"],
        ai_root=source_edition["index_root"],
        source_manifest_relative_path=plan["manifest"],
        edition_manifest_relative_path=source_edition["manifest"],
        index_relative_path=source_edition["index_relative_path"],
    )
    if ai_result["index_sha256"] != source_edition["index_sha256"]:
        raise ValueError("AI edition index changed after translation planning.")
    ai_index = ai_result["index"]
    if (
        ai_index.get("work_id") != plan["work_id"]
        or ai_index.get("source_manifest", {}).get("relative_path")
        != plan["manifest"]
        or ai_index.get("catalog", {}).get("relative_path") != plan["catalog"]
        or ai_index.get("edition_manifest", {}).get("relative_path")
        != source_edition["manifest"]
        or ai_index.get("edition_manifest", {}).get("sha256")
        != source_edition["manifest_sha256"]
    ):
        raise ValueError("AI edition lineage differs from the translation plan.")
    for field in ("source_manifest", "edition_manifest", "catalog"):
        if human_index.get(field) != ai_index.get(field):
            raise ValueError("Human edition was built from a different source revision.")
    if human_index.get("work_metadata") != ai_index.get("work_metadata"):
        raise ValueError("Human edition work metadata differs from the AI edition.")

    ai_episodes = ai_result["episodes_by_id"]
    edition_manifest = ai_result.get("edition_manifest")
    if (
        not isinstance(edition_manifest, dict)
        or not isinstance(edition_manifest.get("artifacts"), list)
    ):
        raise ValueError("Verified edition manifest is missing from the AI index.")
    edition_by_version = {
        artifact["version_id"]: artifact
        for artifact in edition_manifest["artifacts"]
        if isinstance(artifact, dict) and isinstance(artifact.get("version_id"), str)
    }
    if set(ai_episodes) != {episode["episode_id"] for episode in episodes}:
        raise ValueError("AI edition episode coverage differs from the plan.")
    human_episodes = {
        episode["episode_id"]: episode for episode in human_index["episodes"]
    }
    for episode in episodes:
        ai_episode = ai_episodes[episode["episode_id"]]
        human_episode = human_episodes[episode["episode_id"]]
        human_artifact_id = source_artifact_id(
            plan["work_id"],
            "human-reading-v1",
            episode["episode_id"],
        )
        human_artifact = edition_by_version.get(
            human_episode.get("human_edition_version_id")
        )
        if (
            ai_episode.get("ai_edition_version_id")
            != episode["source_version_id"]
            or ai_episode.get("ai_relative_path")
            != episode["source_input_file"]
            or ai_episode.get("output_sha256") != episode["source_sha256"]
            or ai_episode.get("title") != episode["title"]
            or ai_episode.get("position") != episode["position"]
            or human_episode.get("source_version_id")
            != ai_episode.get("source_version_id")
            or human_episode.get("source_sha256")
            != ai_episode.get("source_sha256")
            or human_episode.get("raw_source_version_id")
            != ai_episode.get("raw_source_version_id")
            or human_episode.get("raw_source_sha256")
            != ai_episode.get("raw_source_sha256")
            or human_episode.get("edition_input_version_id")
            != ai_episode.get("edition_input_version_id")
            or human_episode.get("edition_input_sha256")
            != ai_episode.get("edition_input_sha256")
            or human_episode.get("human_edition_artifact_id")
            != human_artifact_id
            or not isinstance(human_artifact, dict)
            or human_artifact.get("artifact_id") != human_artifact_id
            or human_artifact.get("version_id")
            != human_episode.get("human_edition_version_id")
            or human_artifact.get("kind") != "export"
            or human_artifact.get("relative_path")
            != human_episode.get("human_archive_relative_path")
            or human_artifact.get("content_sha256")
            != human_episode.get("output_sha256")
            or human_episode.get("edition_input_version_id")
            not in human_artifact.get("parent_version_ids", [])
        ):
            raise ValueError(
                "Human edition episode lineage or archived artifact identity "
                "is stale or differs from the verified AI source revision."
            )


def create_plan_review_template(
    plan: dict,
    human_index_path: str | Path,
) -> dict:
    """Create a pending, content-free mapping and edition review template."""
    digest = _require_approvable_plan(plan)
    source_edition = plan.get("source_edition")
    if not isinstance(source_edition, dict):
        raise ValueError("A dual-edition review requires an AI source edition.")
    episodes = _validate_plan_shape(plan)
    human_index, human_digest = _load_human_edition_index(
        human_index_path,
        work_id=plan["work_id"],
        episodes=episodes,
    )
    _verify_human_edition_lineage(plan, human_index, episodes)
    human_by_id = {
        item["episode_id"]: item for item in human_index["episodes"]
    }
    review_episodes = []
    for episode in episodes:
        human = human_by_id[episode["episode_id"]]
        review_episodes.append(
            {
                "episode_id": episode["episode_id"],
                "position": episode["position"],
                "title": episode["title"],
                "source_version_id": episode["source_version_id"],
                "source_input_file": episode["source_input_file"],
                "source_sha256": episode["source_sha256"],
                "translation_file": episode["translation_file"],
                "tm_key": episode["tm_key"],
                "human_relative_path": human["human_relative_path"],
                "human_output_sha256": human["output_sha256"],
                "mapping_decision": "pending",
                "ai_edition_decision": "pending",
                "human_edition_decision": "pending",
                "issues": [],
                "notes": "",
            }
        )
    return {
        "schema_version": 1,
        "plan_sha256": digest,
        "work_id": plan["work_id"],
        "episode_count": len(review_episodes),
        "ai_index_sha256": source_edition["index_sha256"],
        "human_index_sha256": human_digest,
        "episodes": review_episodes,
    }


def verify_plan_review_template(
    path: str | Path,
    plan: dict,
    human_index_path: str | Path,
) -> tuple[dict, str]:
    """Verify a completed plan review and return its bytes digest."""
    review, review_bytes = _read_json_file_with_bytes(
        path,
        _MAX_PLAN_BYTES,
        "Translation plan review",
    )
    if set(review) != _REVIEW_FIELDS:
        raise ValueError("Translation plan review fields do not match schema v1.")
    expected_template = create_plan_review_template(plan, human_index_path)
    review_version = review.get("schema_version")
    if isinstance(review_version, bool) or review_version != 1:
        raise ValueError("Translation plan review schema version is unsupported.")
    for field in (
        "plan_sha256",
        "work_id",
        "episode_count",
        "ai_index_sha256",
        "human_index_sha256",
    ):
        if review.get(field) != expected_template[field]:
            raise ValueError("Translation plan review is stale.")
    review_episodes = review.get("episodes")
    if (
        not isinstance(review_episodes, list)
        or len(review_episodes) != len(expected_template["episodes"])
    ):
        raise ValueError("Translation plan review episode coverage is invalid.")
    review_episode_count = review.get("episode_count")
    if (
        isinstance(review_episode_count, bool)
        or not isinstance(review_episode_count, int)
        or review_episode_count != len(expected_template["episodes"])
    ):
        raise ValueError("Translation plan review episode count is invalid.")
    expected_by_id = {
        item["episode_id"]: item for item in expected_template["episodes"]
    }
    seen = set()
    for item in review_episodes:
        if not isinstance(item, dict) or set(item) != _REVIEW_EPISODE_FIELDS:
            raise ValueError("Translation plan review episode fields are invalid.")
        episode_id = item["episode_id"]
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError("Translation plan review contains an invalid episode.")
        if episode_id in seen or episode_id not in expected_by_id:
            raise ValueError("Translation plan review contains invalid episodes.")
        seen.add(episode_id)
        expected = expected_by_id[episode_id]
        if (
            isinstance(item["position"], bool)
            or not isinstance(item["position"], int)
        ):
            raise ValueError("Translation plan review episode position is invalid.")
        for field in (
            "episode_id",
            "position",
            "title",
            "source_version_id",
            "source_input_file",
            "source_sha256",
            "translation_file",
            "tm_key",
            "human_relative_path",
            "human_output_sha256",
        ):
            if item.get(field) != expected[field]:
                raise ValueError("Translation plan review mapping is stale.")
        for field in (
            "mapping_decision",
            "ai_edition_decision",
            "human_edition_decision",
        ):
            if item.get(field) not in _REVIEW_DECISIONS:
                raise ValueError("Translation plan review decision is invalid.")
        if (
            item["mapping_decision"] != "pass"
            or item["ai_edition_decision"] != "pass"
            or item["human_edition_decision"] != "pass"
        ):
            raise ValueError("Translation plan review is not fully approved.")
        if item.get("issues") != []:
            raise ValueError("Translation plan review contains unresolved issues.")
        _require_review_notes(item.get("notes"))
    if seen != set(expected_by_id):
        raise ValueError("Translation plan review is missing episodes.")
    return review, hashlib.sha256(review_bytes).hexdigest()


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
        or episode["source_sha256"] is None
        or (
            plan.get("source_edition") is not None
            and episode["source_input_file"] is None
        )
        or (
            plan.get("source_edition") is None
            and episode["source_input_file"] is not None
        )
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


def create_approval_receipt(
    plan: dict,
    approved_by: str,
    *,
    review_sha256: str | None = None,
) -> dict:
    digest = _require_approvable_plan(plan)
    reviewer = _require_text(approved_by, "approved_by", maximum=200)
    if plan.get("source_edition") is not None and review_sha256 is None:
        raise ValueError(
            "AI edition plans require a completed structured review."
        )
    if review_sha256 is not None:
        _require_sha256(review_sha256, "review_sha256")
    receipt = {
        "schema_version": 2 if review_sha256 is not None else 1,
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
    if review_sha256 is not None:
        receipt["review_sha256"] = review_sha256
    return receipt


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
        or episode["source_sha256"] is None
        or (
            plan.get("source_edition") is not None
            and episode["source_input_file"] is None
        )
        or (
            plan.get("source_edition") is None
            and episode["source_input_file"] is not None
        )
        for episode in episodes
    ):
        raise ValueError("Current translation plan is not safe to execute.")

    receipt = _read_json_file(path, _MAX_RECEIPT_BYTES, "Approval receipt")
    schema_version = receipt.get("schema_version")
    expected_fields = (
        _RECEIPT_FIELDS_V2 if schema_version == 2 else _RECEIPT_FIELDS
    )
    if set(receipt) != expected_fields:
        raise ValueError("Approval receipt fields do not match its schema.")
    if isinstance(schema_version, bool) or schema_version not in {1, 2}:
        raise ValueError("Approval receipt schema version is unsupported.")
    if plan.get("source_edition") is not None and schema_version != 2:
        raise ValueError(
            "AI edition plans require a structured review approval receipt."
        )
    if schema_version == 2:
        _require_sha256(receipt.get("review_sha256"), "review_sha256")
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
