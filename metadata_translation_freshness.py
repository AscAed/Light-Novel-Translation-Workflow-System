"""Verify a metadata plan against current catalog and manifest versions."""

import hashlib
import json
from pathlib import Path

from scripts.ingest_kakuyomu_pages import _load_catalog_snapshot
from source_ingestion import (
    _load_episode_metadata,
    _read_manifested_artifact_bytes,
    source_artifact_id,
)
from source_manifest import latest_artifacts_by_kind, parse_manifest_bytes
from utils import open_regular_file, resolve_relative_path


_MAX_WORK_METADATA_BYTES = 4 * 1024 * 1024
_MAX_MANIFEST_BYTES = 128 * 1024 * 1024


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        if value is None:
            return None
        raise ValueError("Current metadata source field is not text or null.")
    return value if value.strip() else None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Current work metadata contains duplicate JSON keys.")
        result[key] = value
    return result


def verify_metadata_translation_plan_freshness(
    plan: dict,
    *,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str = "source_manifest.json",
    allow_field_drift: bool = False,
) -> dict:
    """Reject a plan unless all of its source fields match current local state."""
    from metadata_translation import verify_metadata_translation_plan

    if not isinstance(allow_field_drift, bool):
        raise ValueError("Metadata field drift option must be boolean.")
    verify_metadata_translation_plan(plan)
    source_path = Path(source_root).resolve(strict=True)
    catalog = _load_catalog_snapshot(source_path, catalog_relative_path)
    if catalog["schema_version"] != 3 or catalog["work_metadata"] is None:
        raise ValueError("Current source catalog must include schema v3 work metadata.")
    if catalog["work_id"] != plan["work_id"]:
        raise ValueError("Metadata plan work ID differs from the current catalog.")

    manifest_path = resolve_relative_path(
        str(source_path),
        manifest_relative_path,
    )
    with open_regular_file(manifest_path, binary=True) as stream:
        manifest_bytes = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
        raise ValueError("Current source manifest exceeds the metadata check limit.")
    manifest = parse_manifest_bytes(manifest_bytes)
    latest_work = latest_artifacts_by_kind(manifest, "work").get(
        source_artifact_id(plan["work_id"], "work", "metadata")
    )
    if latest_work is None:
        raise ValueError("Current work metadata artifact is missing.")
    work_bytes = _read_manifested_artifact_bytes(
        source_path,
        latest_work,
        max_bytes=_MAX_WORK_METADATA_BYTES,
    )
    try:
        work_record = json.loads(
            work_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Current work metadata artifact is invalid.") from exc
    if (
        not isinstance(work_record, dict)
        or work_record.get("schema_version") != 1
        or work_record.get("work_id") != plan["work_id"]
        or work_record.get("metadata") != catalog["work_metadata"]
    ):
        raise ValueError("Current work metadata differs from the catalog.")

    current_fields = {}
    work_metadata = catalog["work_metadata"]
    for field_name in ("title", "catchphrase", "introduction", "genre"):
        current_fields[f"work.{field_name}"] = (
            "work",
            plan["work_id"],
            field_name,
            _nonempty_text(work_metadata[field_name]),
            latest_work["version_id"],
        )
    for index, tag in enumerate(work_metadata["tags"], start=1):
        current_fields[f"work.tags.{index:04d}"] = (
            "work",
            plan["work_id"],
            "tag",
            _nonempty_text(tag),
            latest_work["version_id"],
        )

    catalog_episode_by_id = {
        episode.metadata.episode_id: episode.metadata
        for episode in catalog["episodes"]
    }
    for group in catalog["chapters"]:
        group_id = group["group_id"]
        current_fields[f"chapter.{group_id}.title"] = (
            "chapter",
            group_id,
            "title",
            _nonempty_text(group["title"]),
            catalog["sha256"],
        )

    latest_episodes = latest_artifacts_by_kind(manifest, "episode")
    for episode_id, catalog_episode in catalog_episode_by_id.items():
        artifact = latest_episodes.get(
            source_artifact_id(plan["work_id"], "episode", episode_id)
        )
        if artifact is None:
            raise ValueError("Current episode metadata artifact is missing.")
        metadata_artifact, metadata = _load_episode_metadata(
            source_path,
            manifest,
            work_id=plan["work_id"],
            episode_id=episode_id,
        )
        if (
            metadata_artifact["version_id"] != artifact["version_id"]
            or metadata["title"] != catalog_episode.title
            or metadata["position"] != catalog_episode.position
        ):
            raise ValueError(
                "Current episode metadata differs from the catalog snapshot."
            )
        current_fields[f"episode.{episode_id}.title"] = (
            "episode",
            episode_id,
            "title",
            _nonempty_text(metadata["title"]),
            metadata_artifact["version_id"],
        )

    planned_fields = {item["field_id"]: item for item in plan["fields"]}
    field_statuses = {}
    for field_id in planned_fields.keys() | current_fields.keys():
        item = planned_fields.get(field_id)
        expected = current_fields.get(field_id)
        if item is None:
            field_statuses[field_id] = "unplanned"
            continue
        if expected is None:
            field_statuses[field_id] = "source_removed"
            continue
        (
            entity_kind,
            entity_id,
            field_name,
            source_value,
            _source_version_id,
        ) = expected
        is_current = (
            item["entity_kind"] == entity_kind
            and item["entity_id"] == entity_id
            and item["field_name"] == field_name
            and item["source_value"] == source_value
        )
        field_statuses[field_id] = "current" if is_current else "stale"

    current_field_sources = {}
    for field_id, expected in current_fields.items():
        source_value = expected[3]
        current_field_sources[field_id] = {
            "source_version_id": expected[4],
            "source_sha256": (
                hashlib.sha256(source_value.encode("utf-8")).hexdigest()
                if source_value is not None
                else None
            ),
        }

    inventory_matches = set(planned_fields) == set(current_fields)
    all_fields_current = all(status == "current" for status in field_statuses.values())
    is_current = inventory_matches and all_fields_current
    if not is_current and not allow_field_drift:
        if not inventory_matches:
            raise ValueError("Metadata plan field inventory differs from current sources.")
        raise ValueError("Metadata plan contains a stale source field.")

    return {
        "status": "current" if is_current else "stale",
        "work_id": plan["work_id"],
        "plan_sha256": plan["plan_sha256"],
        "catalog_sha256": catalog["sha256"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "field_count": len(current_fields),
        "field_statuses": field_statuses,
        "current_field_sources": current_field_sources,
    }
