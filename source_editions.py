"""Create independently cleaned AI and human-readable source editions."""

import copy
import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any

from scripts.ingest_kakuyomu_pages import _load_catalog_snapshot
from source_ingestion import (
    DEFAULT_MAX_EPISODE_BYTES,
    _load_episode_metadata,
    _read_manifested_artifact_bytes,
    _source_artifact_id,
)
from source_manifest import (
    latest_raw_parent_for_normalized,
    latest_artifacts_by_kind,
    load_manifest,
    parse_manifest_bytes,
    validate_manifest,
    verify_current_normalized_source,
    verify_current_normalized_source_metadata,
)
from utils import (
    open_regular_file,
    resolve_relative_path,
    write_bytes_atomically,
    write_new_relative_bytes,
)


DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024
DEFAULT_EDITION_MANIFEST = "source_editions_manifest.json"
_MAX_INDEX_BYTES = 16 * 1024 * 1024
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
    re.IGNORECASE,
)
_MAX_COMPONENT_UTF16_UNITS = 100
_SOURCE_ANNOTATION = re.compile(
    r"｜(?P<base>[^《\n]+)《(?P<reading>[^》\n]*)》"
)
_AI_CLEANING_PROFILE = {
    "id": "ai-efficient-v1",
    "rules": [
        "Normalize line endings to LF.",
        "Remove one leading U+3000 at the beginning of each paragraph.",
        "Render ruby as base followed by 《reading》, without the range marker.",
        "Render emphasis dots as Markdown strong emphasis.",
        "Preserve paragraph and line boundaries.",
    ],
}
_HUMAN_CLEANING_PROFILE = {
    "id": "human-reading-v1",
    "rules": [
        "Normalize line endings to LF.",
        "Preserve source paragraph indentation and line boundaries.",
        "Render ruby with native HTML ruby elements.",
        "Render emphasis dots with CSS text-emphasis.",
        "Escape source text before embedding inline HTML.",
    ],
}


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open_regular_file(path, binary=True) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reject_duplicate_index_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("AI edition index contains a duplicate JSON field.")
        result[key] = value
    return result


def _reject_duplicate_source_edition_index_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Source-edition index contains a duplicate JSON field.")
        result[key] = value
    return result


def _load_source_edition_index(
    root: Path,
    relative_path: str,
    *,
    edition: str,
) -> tuple[dict[str, Any], str]:
    index_path = resolve_relative_path(str(root), relative_path)
    with open_regular_file(index_path, binary=True) as stream:
        index_bytes = stream.read(_MAX_INDEX_BYTES + 1)
    if len(index_bytes) > _MAX_INDEX_BYTES:
        raise ValueError("Source-edition index exceeds the configured size limit.")
    try:
        index = json.loads(
            index_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_source_edition_index_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "Source-edition index is invalid UTF-8 JSON or has duplicate fields."
        ) from exc
    if not isinstance(index, dict) or index.get("edition") != edition:
        raise ValueError("Source-edition index has an unsupported edition.")
    return index, _sha256_bytes(index_bytes)


def _edition_artifact(
    *,
    work_id: str,
    profile_id: str,
    episode_id: str,
    kind: str,
    parent_version_id: str,
    content: bytes,
) -> dict:
    artifact_id = _source_artifact_id(work_id, profile_id, episode_id)
    content_sha256 = _sha256_bytes(content)
    identity = json.dumps(
        [artifact_id, parent_version_id, content_sha256],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    version_id = f"v-{hashlib.sha256(identity).hexdigest()}"
    return {
        "artifact_id": artifact_id,
        "version_id": version_id,
        "kind": kind,
        "content_sha256": content_sha256,
        "relative_path": (
            f"editions/{profile_id}/{episode_id}/{version_id}.md"
        ),
        "parent_version_ids": [parent_version_id],
    }


def _merge_edition_manifest(
    source_manifest: dict,
    existing_edition_manifest: dict | None,
    edition_artifacts: list[dict],
) -> dict:
    source_by_version = {
        item["version_id"]: item for item in source_manifest["artifacts"]
    }
    preserved_editions = []
    if existing_edition_manifest is not None:
        for artifact in existing_edition_manifest["artifacts"]:
            source_artifact = source_by_version.get(artifact["version_id"])
            if source_artifact is not None:
                if artifact != source_artifact:
                    raise ValueError(
                        "Edition manifest conflicts with a source manifest version."
                    )
            else:
                preserved_editions.append(copy.deepcopy(artifact))

    combined = {
        "schema_version": source_manifest["schema_version"],
        "artifacts": [
            *copy.deepcopy(source_manifest["artifacts"]),
            *preserved_editions,
        ],
    }
    by_version = {
        artifact["version_id"]: artifact
        for artifact in combined["artifacts"]
    }
    for artifact in edition_artifacts:
        current = by_version.get(artifact["version_id"])
        if current is not None:
            if current != artifact:
                raise ValueError("Edition artifact version identity conflicts.")
            continue
        combined["artifacts"].append(copy.deepcopy(artifact))
        by_version[artifact["version_id"]] = artifact
    validate_manifest(combined)
    return combined


def synchronize_edition_manifest_with_source_history(
    *,
    source_root: str,
    source_manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = DEFAULT_EDITION_MANIFEST,
) -> dict[str, Any]:
    """Add newly collected source history while preserving edition artifacts."""
    source_path = Path(source_root).resolve(strict=True)
    if not source_path.is_dir():
        raise ValueError("Source root must be a directory.")
    source_manifest_path = resolve_relative_path(
        str(source_path),
        source_manifest_relative_path,
    )
    edition_manifest_path = resolve_relative_path(
        str(source_path),
        edition_manifest_relative_path,
        allow_missing=True,
    )
    if source_manifest_path == edition_manifest_path:
        raise ValueError("Source and edition manifests must be different files.")

    source_manifest_sha256 = _sha256_file(source_manifest_path)
    source_manifest = load_manifest(source_manifest_path)
    existing_bytes = _load_output_file(edition_manifest_path)
    existing_manifest = (
        parse_manifest_bytes(existing_bytes)
        if existing_bytes is not None
        else None
    )
    merged_manifest = _merge_edition_manifest(
        source_manifest,
        existing_manifest,
        [],
    )
    merged_bytes = _json_bytes(merged_manifest)
    updated = existing_bytes != merged_bytes
    if _sha256_file(source_manifest_path) != source_manifest_sha256:
        raise RuntimeError(
            "Source manifest changed while edition history was synchronized."
        )
    if _load_output_file(edition_manifest_path) != existing_bytes:
        raise RuntimeError(
            "Edition manifest changed while source history was synchronized."
        )
    if updated:
        write_bytes_atomically(str(edition_manifest_path), merged_bytes)

    return {
        "status": "updated" if updated else "unchanged",
        "source_manifest_sha256": source_manifest_sha256,
        "edition_manifest_sha256": _sha256_bytes(merged_bytes),
        "artifact_count": len(merged_manifest["artifacts"]),
    }


def _index_refresh_is_safe(existing: bytes, expected: bytes) -> bool:
    try:
        previous = json.loads(existing.decode("utf-8"))
        current = json.loads(expected.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False

    previous = copy.deepcopy(previous)
    current = copy.deepcopy(current)

    for reference_name in (
        "source_manifest",
        "edition_manifest",
        "catalog",
    ):
        previous_reference = previous.pop(reference_name, None)
        current_reference = current.pop(reference_name, None)
        if (
            reference_name == "edition_manifest"
            and previous_reference is None
        ):
            previous_reference = current_reference
        if not isinstance(previous_reference, dict) or not isinstance(
            current_reference, dict
        ):
            return False
        if (
            (
                reference_name != "catalog"
                and previous_reference.get("relative_path")
                != current_reference.get("relative_path")
            )
            or not isinstance(previous_reference.get("relative_path"), str)
            or not isinstance(current_reference.get("relative_path"), str)
            or not isinstance(previous_reference.get("sha256"), str)
            or not isinstance(current_reference.get("sha256"), str)
        ):
            return False

    previous_work_metadata = previous.pop("work_metadata", None)
    current_work_metadata = current.pop("work_metadata", None)
    previous_work_count = None
    current_work_count = None
    if previous_work_metadata is not None or current_work_metadata is not None:
        if not isinstance(previous_work_metadata, dict) or not isinstance(
            current_work_metadata, dict
        ):
            return False
        previous_count = previous_work_metadata.pop(
            "public_episode_count", None
        )
        current_count = current_work_metadata.pop(
            "public_episode_count", None
        )
        previous_published = previous_work_metadata.pop(
            "last_episode_published_at", None
        )
        current_published = current_work_metadata.pop(
            "last_episode_published_at", None
        )
        if (
            previous_work_metadata != current_work_metadata
            or isinstance(previous_count, bool)
            or not isinstance(previous_count, int)
            or isinstance(current_count, bool)
            or not isinstance(current_count, int)
            or current_count < previous_count
            or not isinstance(previous_published, (str, type(None)))
            or not isinstance(current_published, (str, type(None)))
            or (
                current_count == previous_count
                and current_published != previous_published
            )
        ):
            return False
        previous_work_count = previous_count
        current_work_count = current_count

    previous_chapters = previous.pop("chapters", None)
    current_chapters = current.pop("chapters", None)
    if (
        not isinstance(previous_chapters, list)
        or not isinstance(current_chapters, list)
        or len(current_chapters) < len(previous_chapters)
    ):
        return False
    for index, previous_chapter in enumerate(previous_chapters):
        current_chapter = current_chapters[index]
        if not isinstance(previous_chapter, dict) or not isinstance(
            current_chapter, dict
        ):
            return False
        previous_chapter = copy.deepcopy(previous_chapter)
        current_chapter = copy.deepcopy(current_chapter)
        if index == len(previous_chapters) - 1:
            previous_episode_ids = previous_chapter.pop("episode_ids", None)
            current_episode_ids = current_chapter.pop("episode_ids", None)
            previous_end = previous_chapter.pop("position_end", None)
            current_end = current_chapter.pop("position_end", None)
            if (
                (
                    previous_episode_ids is None
                    and current_episode_ids is not None
                )
                or (
                    previous_episode_ids is not None
                    and (
                        not isinstance(previous_episode_ids, list)
                        or not isinstance(current_episode_ids, list)
                        or current_episode_ids[: len(previous_episode_ids)]
                        != previous_episode_ids
                    )
                )
                or isinstance(previous_end, bool)
                or not isinstance(previous_end, int)
                or isinstance(current_end, bool)
                or not isinstance(current_end, int)
                or current_end < previous_end
            ):
                return False
        if previous_chapter != current_chapter:
            return False

    edition_fields = {
        "ai_edition_artifact_id",
        "ai_edition_version_id",
        "ai_archive_relative_path",
        "human_edition_artifact_id",
        "human_edition_version_id",
        "human_archive_relative_path",
    }
    previous_episodes = previous.pop("episodes", None)
    current_episodes = current.pop("episodes", None)
    if (
        not isinstance(previous_episodes, list)
        or not isinstance(current_episodes, list)
        or len(current_episodes) < len(previous_episodes)
        or (
            previous_work_count is not None
            and previous_work_count != len(previous_episodes)
        )
        or (
            current_work_count is not None
            and current_work_count != len(current_episodes)
        )
    ):
        return False
    for index, previous_episode in enumerate(previous_episodes):
        current_episode = current_episodes[index]
        if not isinstance(previous_episode, dict) or not isinstance(
            current_episode,
            dict,
        ):
            return False
        for field in edition_fields:
            if (
                field in previous_episode
                and previous_episode[field] != current_episode.get(field)
            ):
                return False
            previous_episode.pop(field, None)
            current_episode.pop(field, None)
        if previous_episode != current_episode:
            return False
    return previous == current


def verify_ai_edition_index(
    *,
    source_root: str,
    ai_root: str,
    source_manifest_relative_path: str,
    edition_manifest_relative_path: str,
    index_relative_path: str = "catalog.json",
) -> dict[str, Any]:
    """Verify RAWs_AI files and their archive lineage metadata.

    Archived source and edition bodies are checked by the explicit archive
    validators; translation setup reads only their manifests and catalog.
    """
    source_path = Path(source_root).resolve(strict=True)
    ai_path = Path(ai_root).resolve(strict=True)
    if not source_path.is_dir() or not ai_path.is_dir():
        raise ValueError("Source and AI edition roots must be directories.")
    try:
        common_root = Path(os.path.commonpath((source_path, ai_path)))
    except ValueError:
        common_root = None
    if common_root in (source_path, ai_path):
        raise ValueError(
            "Source archive and AI edition roots must be disjoint."
        )
    source_manifest_path = resolve_relative_path(
        str(source_path),
        source_manifest_relative_path,
    )
    edition_manifest_path = resolve_relative_path(
        str(source_path),
        edition_manifest_relative_path,
    )
    index_path = resolve_relative_path(str(ai_path), index_relative_path)
    with open_regular_file(index_path, binary=True) as stream:
        index_bytes = stream.read(_MAX_INDEX_BYTES + 1)
    if len(index_bytes) > _MAX_INDEX_BYTES:
        raise ValueError("AI edition index exceeds the configured size limit.")
    try:
        index = json.loads(
            index_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_index_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "AI edition index is invalid UTF-8 JSON or has duplicate fields."
        ) from exc
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != 2
        or index.get("edition") != "ai"
        or not isinstance(index.get("work_id"), str)
        or not isinstance(index.get("cleaning_profile"), dict)
        or index["cleaning_profile"].get("id")
        != _AI_CLEANING_PROFILE["id"]
    ):
        raise ValueError("AI edition index has an unsupported profile or schema.")
    source_record = index.get("source_manifest")
    edition_record = index.get("edition_manifest")
    if (
        not isinstance(source_record, dict)
        or source_record.get("relative_path")
        != source_manifest_relative_path.replace("\\", "/")
        or source_record.get("sha256") != _sha256_file(source_manifest_path)
    ):
        raise ValueError("AI edition index is stale for the source manifest.")
    if (
        not isinstance(edition_record, dict)
        or edition_record.get("relative_path")
        != edition_manifest_relative_path.replace("\\", "/")
        or edition_record.get("sha256") != _sha256_file(edition_manifest_path)
    ):
        raise ValueError("AI edition index is stale for the edition manifest.")

    source_manifest = load_manifest(source_manifest_path)
    edition_manifest = load_manifest(edition_manifest_path)
    edition_by_version = {
        item["version_id"]: item for item in edition_manifest["artifacts"]
    }
    for source_artifact in source_manifest["artifacts"]:
        if edition_by_version.get(source_artifact["version_id"]) != source_artifact:
            raise ValueError("Edition manifest does not contain the current source history.")

    episodes = index.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("AI edition index episodes must be an array.")
    by_episode_id = {}
    normalized_by_id = latest_artifacts_by_kind(
        source_manifest,
        "normalized_source",
    )
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("AI edition index contains an invalid episode.")
        episode_id = episode.get("episode_id")
        if not isinstance(episode_id, str) or episode_id in by_episode_id:
            raise ValueError("AI edition index contains a duplicate episode.")
        normalized_id = _source_artifact_id(
            index["work_id"],
            "normalized_source",
            episode_id,
        )
        normalized = normalized_by_id.get(normalized_id)
        if (
            normalized is None
            or episode.get("source_version_id") != normalized["version_id"]
            or episode.get("source_sha256") != normalized["content_sha256"]
        ):
            raise ValueError("AI edition input normalized source is stale.")
        verified_normalized = verify_current_normalized_source_metadata(
            source_manifest,
            normalized["version_id"],
        )
        raw_parent = latest_raw_parent_for_normalized(
            source_manifest,
            verified_normalized,
        )
        if (
            episode.get("raw_source_version_id") != raw_parent["version_id"]
            or episode.get("raw_source_sha256") != raw_parent["content_sha256"]
            or episode.get("edition_input_version_id") != raw_parent["version_id"]
            or episode.get("edition_input_sha256") != raw_parent["content_sha256"]
        ):
            raise ValueError("AI edition input raw source is stale.")
        artifact_id = _source_artifact_id(
            index["work_id"],
            _AI_CLEANING_PROFILE["id"],
            episode_id,
        )
        edition_version_id = episode.get("ai_edition_version_id")
        edition_artifact = verify_current_normalized_source_metadata(
            edition_manifest,
            edition_version_id,
        )
        if (
            episode.get("ai_edition_artifact_id") != artifact_id
            or edition_artifact["artifact_id"] != artifact_id
            or edition_artifact["relative_path"]
            != episode.get("ai_archive_relative_path")
            or raw_parent["version_id"]
            not in edition_artifact["parent_version_ids"]
            or edition_artifact["content_sha256"]
            != episode.get("output_sha256")
        ):
            raise ValueError("AI edition artifact metadata does not match its index.")
        ai_relative_path = episode.get("ai_relative_path")
        if not isinstance(ai_relative_path, str):
            raise ValueError("AI edition output path is missing.")
        ai_file = resolve_relative_path(str(ai_path), ai_relative_path)
        if _sha256_file(ai_file) != episode["output_sha256"]:
            raise ValueError("AI edition output hash does not match its index.")
        by_episode_id[episode_id] = episode

    return {
        "index": index,
        "episodes_by_id": by_episode_id,
        "source_manifest": source_manifest,
        "edition_manifest": edition_manifest,
        "index_sha256": _sha256_bytes(index_bytes),
    }


def read_verified_ai_edition_bytes(
    ai_root: str,
    relative_path: str,
    expected_sha256: str,
    *,
    max_bytes: int = DEFAULT_MAX_EPISODE_BYTES,
) -> bytes:
    """Read a RAWs_AI file and verify it against its edition-index digest."""
    if (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
    ):
        raise ValueError("AI edition source has an invalid expected SHA-256.")
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
    ):
        raise ValueError("AI edition source size limit must be positive.")
    path = resolve_relative_path(ai_root, relative_path)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("AI edition source exceeds the configured size limit.")
    if _sha256_bytes(content) != expected_sha256:
        raise ValueError("AI edition source does not match its verified index.")
    return content


def validate_source_editions(
    *,
    source_root: str,
    catalog_relative_path: str,
    human_root: str,
    ai_root: str,
    source_manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = DEFAULT_EDITION_MANIFEST,
    human_index_relative_path: str = "SOURCE_MAP.json",
    ai_index_relative_path: str = "catalog.json",
    max_total_source_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Read-only verification of both editions against current raw source bytes."""
    if (
        isinstance(max_total_source_bytes, bool)
        or not isinstance(max_total_source_bytes, int)
        or max_total_source_bytes < 1
    ):
        raise ValueError("Maximum total source bytes must be positive.")

    source_path = Path(source_root).resolve(strict=True)
    human_path = Path(human_root).resolve(strict=True)
    ai_path = Path(ai_root).resolve(strict=True)
    if not all(path.is_dir() for path in (source_path, human_path, ai_path)):
        raise ValueError("Source and edition roots must be directories.")
    roots = (source_path, human_path, ai_path)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            try:
                common = Path(os.path.commonpath((left, right)))
            except ValueError:
                continue
            if common in (left, right):
                raise ValueError(
                    "Source archive and source-edition roots must be disjoint."
                )

    ai_result = verify_ai_edition_index(
        source_root=str(source_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=source_manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
        index_relative_path=ai_index_relative_path,
    )
    ai_index = ai_result["index"]
    human_index, human_index_sha256 = _load_source_edition_index(
        human_path,
        human_index_relative_path,
        edition="human_reading",
    )
    catalog = _load_catalog_snapshot(
        str(source_path),
        catalog_relative_path,
    )
    normalized_catalog_path = catalog_relative_path.replace("\\", "/")
    expected_catalog_record = {
        "relative_path": normalized_catalog_path,
        "sha256": catalog["sha256"],
    }
    if (
        ai_index.get("work_id") != catalog["work_id"]
        or ai_index.get("catalog") != expected_catalog_record
    ):
        raise ValueError("AI edition index is stale for the current catalog.")

    expected_human_profile = _HUMAN_CLEANING_PROFILE
    if (
        human_index.get("schema_version") != 2
        or human_index.get("work_id") != ai_index["work_id"]
        or human_index.get("lookup_key") != "human_relative_path"
        or human_index.get("cleaning_profile") != expected_human_profile
    ):
        raise ValueError("Human edition index has an unsupported schema or profile.")

    shared_fields = (
        "schema_version",
        "work_id",
        "source_manifest",
        "edition_manifest",
        "catalog",
        "source_basis",
        "chapters",
        "work_metadata",
    )
    if any(
        human_index.get(field) != ai_index.get(field)
        for field in shared_fields
    ):
        raise ValueError("AI and human edition indexes do not share one source basis.")

    chapters = catalog["chapters"]
    chapter_names = _build_chapter_names(chapters)
    chapter_order = _chapter_index(chapters)
    expected_chapters = [
        {
            "group_id": chapter["group_id"],
            "chapter_id": chapter["chapter_id"],
            "title": chapter["title"],
            "level": chapter["level"],
            "position_start": chapter["position_start"],
            "position_end": chapter["position_end"],
            "human_directory": chapter_names[chapter["group_id"]],
            "ai_directory": (
                f"chapters/{chapter_order[chapter['group_id']]:03d}_"
                f"{safe_path_component(chapter['chapter_id'] or chapter['group_id'], fallback=chapter['group_id'])}"
            ),
        }
        for chapter in chapters
    ]
    if ai_index.get("chapters") != expected_chapters:
        raise ValueError("Edition chapter directories do not match the catalog.")

    ai_entries = ai_index.get("episodes")
    human_entries = human_index.get("episodes")
    catalog_episodes = catalog["episodes"]
    if (
        not isinstance(ai_entries, list)
        or not isinstance(human_entries, list)
        or len(ai_entries) != len(catalog_episodes)
        or len(human_entries) != len(catalog_episodes)
    ):
        raise ValueError("Edition indexes do not cover the complete catalog.")

    def episodes_by_id(entries, edition_name):
        result = {}
        for episode in entries:
            if not isinstance(episode, dict):
                raise ValueError(
                    f"{edition_name} edition index contains an invalid episode."
                )
            episode_id = episode.get("episode_id")
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError(
                    f"{edition_name} edition index contains an invalid episode ID."
                )
            if episode_id in result:
                raise ValueError(
                    f"{edition_name} edition index contains a duplicate episode."
                )
            result[episode_id] = episode
        return result

    ai_by_id = episodes_by_id(ai_entries, "AI")
    human_by_id = episodes_by_id(human_entries, "Human")
    catalog_ids = [episode.metadata.episode_id for episode in catalog_episodes]
    if (
        set(ai_by_id) != set(catalog_ids)
        or set(human_by_id) != set(catalog_ids)
    ):
        raise ValueError("Edition indexes contain duplicate or missing episodes.")

    group_by_episode = {
        episode_id: chapter
        for chapter in chapters
        for episode_id in chapter["episode_ids"]
    }
    used_human_names: dict[str, set[str]] = {
        chapter["group_id"]: set() for chapter in chapters
    }
    source_manifest = ai_result["source_manifest"]
    edition_manifest = ai_result["edition_manifest"]
    source_by_version = {
        artifact["version_id"]: artifact
        for artifact in source_manifest["artifacts"]
    }
    edition_by_version = {
        artifact["version_id"]: artifact
        for artifact in edition_manifest["artifacts"]
    }
    total_source_bytes = 0
    total_ai_output_bytes = 0
    total_human_output_bytes = 0

    for catalog_episode in catalog_episodes:
        metadata = catalog_episode.metadata
        episode_id = metadata.episode_id
        chapter = group_by_episode.get(episode_id)
        if chapter is None:
            raise ValueError("Catalog episode has no chapter assignment.")
        ai_episode = ai_by_id[episode_id]
        human_episode = human_by_id[episode_id]

        human_base = safe_path_component(
            metadata.title or "",
            fallback=f"未命名话目_{episode_id}",
        )
        used_names = used_human_names[chapter["group_id"]]
        human_name = human_base
        if human_name.casefold() in used_names:
            human_name = safe_path_component(
                f"{human_base}_{metadata.position:04d}",
                fallback=f"话目_{metadata.position:04d}_{episode_id}",
            )
        if human_name.casefold() in used_names:
            human_name = safe_path_component(
                f"{human_name}_{episode_id}",
                fallback=f"话目_{metadata.position:04d}_{episode_id}",
            )
        if human_name.casefold() in used_names:
            raise ValueError("Catalog episode titles map to duplicate files.")
        used_names.add(human_name.casefold())

        ai_relative_path = (
            f"chapters/{chapter_order[chapter['group_id']]:03d}_"
            f"{safe_path_component(chapter['chapter_id'] or chapter['group_id'], fallback=chapter['group_id'])}"
            f"/episodes/{metadata.position:04d}_{episode_id}.md"
        )
        human_relative_path = (
            f"{chapter_names[chapter['group_id']]}/{human_name}.md"
        )
        normalized_id = _source_artifact_id(
            catalog["work_id"],
            "normalized_source",
            episode_id,
        )
        normalized = latest_artifacts_by_kind(
            source_manifest,
            "normalized_source",
        ).get(normalized_id)
        if normalized is None:
            raise ValueError("Catalog episode has no current normalized source.")
        raw_parent = latest_raw_parent_for_normalized(
            source_manifest,
            normalized,
        )
        raw_artifact = source_by_version[raw_parent["version_id"]]
        raw_content = _read_manifested_artifact_bytes(
            source_path,
            raw_artifact,
            max_bytes=DEFAULT_MAX_EPISODE_BYTES,
        )
        total_source_bytes += len(raw_content)
        if total_source_bytes > max_total_source_bytes:
            raise ValueError("Source-edition validation exceeds the total byte limit.")
        try:
            source_text = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Current raw source is not valid UTF-8.") from exc
        if source_text.encode("utf-8") != raw_content:
            raise ValueError("Current raw source is not byte-preserving UTF-8.")

        ai_content = _prepare_ai_text(source_text).encode("utf-8")
        human_content = _prepare_human_text(source_text).encode("utf-8")
        ai_artifact = _edition_artifact(
            work_id=catalog["work_id"],
            profile_id=_AI_CLEANING_PROFILE["id"],
            episode_id=episode_id,
            kind="normalized_source",
            parent_version_id=raw_parent["version_id"],
            content=ai_content,
        )
        human_artifact = _edition_artifact(
            work_id=catalog["work_id"],
            profile_id=_HUMAN_CLEANING_PROFILE["id"],
            episode_id=episode_id,
            kind="export",
            parent_version_id=raw_parent["version_id"],
            content=human_content,
        )
        expected_episode = {
            "episode_id": episode_id,
            "title": metadata.title,
            "position": metadata.position,
            "chapter_id": chapter["chapter_id"],
            "chapter_group_id": chapter["group_id"],
            "chapter_title": chapter["title"],
            "source_version_id": normalized["version_id"],
            "source_sha256": normalized["content_sha256"],
            "edition_input_version_id": raw_parent["version_id"],
            "edition_input_sha256": raw_parent["content_sha256"],
            "raw_source_version_id": raw_parent["version_id"],
            "raw_source_sha256": raw_parent["content_sha256"],
            "human_relative_path": human_relative_path,
            "ai_relative_path": ai_relative_path,
            "human_edition_artifact_id": human_artifact["artifact_id"],
            "human_edition_version_id": human_artifact["version_id"],
            "human_archive_relative_path": human_artifact["relative_path"],
            "ai_edition_artifact_id": ai_artifact["artifact_id"],
            "ai_edition_version_id": ai_artifact["version_id"],
            "ai_archive_relative_path": ai_artifact["relative_path"],
        }
        if any(
            episode.get(key) != value
            for episode in (ai_episode, human_episode)
            for key, value in expected_episode.items()
        ):
            raise ValueError(
                f"Edition index metadata does not match catalog episode {episode_id}."
            )
        if (
            ai_episode.get("output_sha256") != ai_artifact["content_sha256"]
            or human_episode.get("output_sha256")
            != human_artifact["content_sha256"]
        ):
            raise ValueError(
                f"Edition output hashes do not match profile for episode {episode_id}."
            )
        if (
            edition_by_version.get(ai_artifact["version_id"]) != ai_artifact
            or edition_by_version.get(human_artifact["version_id"])
            != human_artifact
        ):
            raise ValueError(
                f"Edition archive metadata is invalid for episode {episode_id}."
            )

        ai_archive = _read_manifested_artifact_bytes(
            source_path,
            ai_artifact,
            max_bytes=DEFAULT_MAX_TOTAL_BYTES,
        )
        human_archive = _read_manifested_artifact_bytes(
            source_path,
            human_artifact,
            max_bytes=DEFAULT_MAX_TOTAL_BYTES,
        )
        ai_mirror = _read_source_edition_output(
            ai_path,
            ai_relative_path,
        )
        human_mirror = _read_source_edition_output(
            human_path,
            human_relative_path,
        )
        if not (ai_archive == ai_mirror == ai_content):
            raise ValueError(
                f"AI edition does not match current profile for episode {episode_id}."
            )
        if not (human_archive == human_mirror == human_content):
            raise ValueError(
                f"Human edition does not match current profile for episode {episode_id}."
            )
        total_ai_output_bytes += len(ai_content)
        total_human_output_bytes += len(human_content)

    return {
        "status": "verified",
        "episode_count": len(catalog_episodes),
        "source_bytes": total_source_bytes,
        "ai_output_bytes": total_ai_output_bytes,
        "human_output_bytes": total_human_output_bytes,
        "ai_index_sha256": ai_result["index_sha256"],
        "human_index_sha256": human_index_sha256,
        "catalog_sha256": catalog["sha256"],
    }


def _read_source_edition_output(root: Path, relative_path: str) -> bytes:
    path = resolve_relative_path(str(root), relative_path)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(DEFAULT_MAX_TOTAL_BYTES + 1)
    if len(content) > DEFAULT_MAX_TOTAL_BYTES:
        raise ValueError("Source-edition output exceeds the configured byte limit.")
    return content


def _component_utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def safe_path_component(value: str, *, fallback: str) -> str:
    """Keep readable Unicode names while removing Windows path hazards."""
    if not isinstance(value, str):
        value = ""
    component = _INVALID_FILENAME_CHARACTERS.sub("_", value)
    component = "".join(
        "_" if ord(character) < 32 else character for character in component
    ).rstrip(" .")
    if component in {"", ".", ".."}:
        component = fallback
    if _RESERVED_WINDOWS_NAME.fullmatch(component):
        component = f"_{component}"

    if _component_utf16_units(component) > _MAX_COMPONENT_UTF16_UNITS:
        suffix = hashlib.sha256(component.encode("utf-8")).hexdigest()[:10]
        while _component_utf16_units(component) > _MAX_COMPONENT_UTF16_UNITS - 11:
            component = component[:-1]
        component = f"{component}_{suffix}"
    return component


def _replace_source_annotations(text: str, *, edition: str) -> str:
    """Render the Kakuyomu parser's ruby and emphasis-dot notation."""
    pieces = []
    offset = 0
    for match in _SOURCE_ANNOTATION.finditer(text):
        base = match.group("base")
        reading = match.group("reading")
        prefix = text[offset : match.start()]
        pieces.append(
            html.escape(prefix, quote=False) if edition == "human" else prefix
        )
        if edition == "ai":
            if reading == "・・・":
                pieces.append(f"**{base}**")
            else:
                pieces.append(f"{base}《{reading}》")
        else:
            escaped_base = html.escape(base, quote=False)
            if reading == "・・・":
                pieces.append(
                    '<span class="emphasisDots" '
                    'style="text-emphasis: filled sesame;">'
                    f"{escaped_base}</span>"
                )
            else:
                escaped_reading = html.escape(reading, quote=False)
                pieces.append(
                    f"<ruby><rb>{escaped_base}</rb><rp>(</rp>"
                    f"<rt>{escaped_reading}</rt><rp>)</rp></ruby>"
                )
        offset = match.end()

    remainder = text[offset:]
    if edition == "human":
        pieces.append(html.escape(remainder, quote=False))
    else:
        pieces.append(remainder)
    return "".join(pieces)


def _prepare_ai_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _replace_source_annotations(text, edition="ai")
    return re.sub(r"(^|\n\n)　", r"\1", text)


def _prepare_human_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    rendered = _replace_source_annotations(text, edition="human")
    return (
        '<div style="white-space: pre-wrap;">\n'
        f"{rendered}"
        "\n</div>\n"
    )


def _load_output_file(path: Path) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise ValueError("Symbolic links are not allowed in source-edition outputs.")
    with open_regular_file(path, binary=True) as stream:
        return stream.read()


def _ensure_directory_chain(root: Path, relative_directory: str) -> None:
    current = root
    prefix = []
    if current.is_symlink():
        raise ValueError("Symbolic links are not allowed for output roots.")
    for component in relative_directory.split("/") if relative_directory else ():
        prefix.append(component)
        current = current / component
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in output paths.")
        try:
            current.mkdir()
        except FileExistsError:
            if not current.is_dir():
                raise ValueError("Source-edition output parent is not a directory.")
        resolve_relative_path(str(root), "/".join(prefix), allow_missing=True)


def _preflight_output(
    root: Path,
    relative_path: str,
    expected: bytes,
) -> bool:
    """Return True for a reusable exact file, False for a new file."""
    path = root.joinpath(*relative_path.split("/"))
    current = root
    for component in relative_path.split("/")[:-1]:
        current = current / component
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in output paths.")
        if current.exists() and not current.is_dir():
            raise ValueError("Source-edition output parent is not a directory.")
    existing = _load_output_file(path)
    if existing is None:
        return False
    if hashlib.sha256(existing).digest() != hashlib.sha256(expected).digest():
        raise ValueError(
            f"Existing source-edition output differs: {relative_path}"
        )
    return True


def _create_output(
    root: Path,
    relative_path: str,
    content: bytes,
) -> bool:
    parent = "/".join(relative_path.split("/")[:-1])
    _ensure_directory_chain(root, parent)
    try:
        write_new_relative_bytes(
            str(root),
            relative_path,
            content,
        )
        return True
    except FileExistsError:
        existing = _load_output_file(root.joinpath(*relative_path.split("/")))
        if existing != content:
            raise ValueError(
                f"Source-edition output changed during generation: {relative_path}"
            )
        return False


def _resolve_roots(source_root: str, human_root: str, ai_root: str):
    source_path = Path(source_root).resolve(strict=True)
    if not source_path.is_dir():
        raise ValueError("Source archive root must be a directory.")

    human_input_path = Path(human_root)
    ai_input_path = Path(ai_root)
    if human_input_path.is_symlink() or ai_input_path.is_symlink():
        raise ValueError("Source-edition roots cannot be symbolic links.")
    human_path = human_input_path.resolve(strict=False)
    ai_path = ai_input_path.resolve(strict=False)
    roots = (source_path, human_path, ai_path)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            try:
                common = Path(os.path.commonpath((left, right)))
            except ValueError:
                continue
            if common in (left, right):
                raise ValueError(
                    "Source archive and source-edition output roots must be disjoint."
                )
    if not human_path.exists():
        human_path.mkdir(parents=True)
    if not ai_path.exists():
        ai_path.mkdir(parents=True)
    if not human_path.is_dir() or not ai_path.is_dir():
        raise ValueError("Source-edition roots must be directories.")
    if os.path.normcase(str(human_path)) == os.path.normcase(str(ai_path)):
        raise ValueError("AI and human source-edition roots must differ.")
    return source_path, human_path, ai_path


def _build_chapter_names(chapters: tuple[dict, ...]) -> dict[str, str]:
    names = {}
    seen = set()
    for index, chapter in enumerate(chapters, start=1):
        group_id = chapter["group_id"]
        title = chapter["title"]
        fallback_id = chapter["chapter_id"] or group_id
        name = safe_path_component(
            title or "",
            fallback=f"未命名章节_{fallback_id}",
        )
        key = name.casefold()
        if key in seen:
            name = safe_path_component(
                f"{name}_{fallback_id}",
                fallback=f"章节_{index:03d}_{fallback_id}",
            )
            key = name.casefold()
        if key in seen:
            raise ValueError("Catalog chapter names map to a duplicate directory.")
        seen.add(key)
        names[group_id] = name
    return names


def _chapter_index(chapters: tuple[dict, ...]) -> dict[str, int]:
    return {
        chapter["group_id"]: index
        for index, chapter in enumerate(chapters, start=1)
    }


def prepare_source_editions(
    *,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str,
    human_root: str,
    ai_root: str,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    edition_manifest_relative_path: str = DEFAULT_EDITION_MANIFEST,
    refresh_indexes: bool = False,
) -> dict[str, Any]:
    """Create independently cleaned editions from verified collected sources."""
    if (
        isinstance(max_total_bytes, bool)
        or not isinstance(max_total_bytes, int)
        or max_total_bytes < 1
    ):
        raise ValueError("Maximum total output bytes must be a positive integer.")

    source_path, human_path, ai_path = _resolve_roots(
        source_root,
        human_root,
        ai_root,
    )
    catalog = _load_catalog_snapshot(
        str(source_path),
        catalog_relative_path,
    )
    if catalog["schema_version"] < 2 or not catalog["chapters"]:
        raise ValueError(
            "Source-edition export requires a catalog with chapter groups."
        )
    manifest_path = resolve_relative_path(
        str(source_path),
        manifest_relative_path,
    )
    manifest = load_manifest(manifest_path)
    manifest_sha256_before = _sha256_file(manifest_path)
    edition_manifest_path = resolve_relative_path(
        str(source_path),
        edition_manifest_relative_path,
        allow_missing=True,
    )
    if edition_manifest_path.is_symlink():
        raise ValueError("Symbolic links are not allowed for edition manifests.")
    existing_edition_bytes = _load_output_file(edition_manifest_path)
    existing_edition_manifest = (
        load_manifest(edition_manifest_path)
        if existing_edition_bytes is not None
        else None
    )
    latest_normalized = latest_artifacts_by_kind(
        manifest,
        "normalized_source",
    )
    chapters = catalog["chapters"]
    chapter_names = _build_chapter_names(chapters)
    chapter_order = _chapter_index(chapters)
    used_human_names: dict[str, set[str]] = {
        chapter["group_id"]: set() for chapter in chapters
    }

    group_by_episode = {
        episode_id: chapter
        for chapter in chapters
        for episode_id in chapter["episode_ids"]
    }
    planned_episodes = []
    contents_by_id = {}
    total_bytes = 0
    for episode in catalog["episodes"]:
        metadata = episode.metadata
        episode_id = metadata.episode_id
        chapter = group_by_episode.get(episode_id)
        if chapter is None:
            raise ValueError("Catalog episode is missing a chapter assignment.")

        _metadata_artifact, recorded_metadata = _load_episode_metadata(
            source_path,
            manifest,
            work_id=catalog["work_id"],
            episode_id=episode_id,
        )
        if (
            recorded_metadata["title"] != metadata.title
            or recorded_metadata["position"] != metadata.position
        ):
            raise ValueError(
                "Catalog and manifest episode metadata do not match."
            )

        normalized_id = _source_artifact_id(
            catalog["work_id"],
            "normalized_source",
            episode_id,
        )
        normalized = latest_normalized.get(normalized_id)
        if normalized is None:
            raise ValueError("Episode has no normalized source version.")
        verified_normalized = verify_current_normalized_source(
            source_path,
            manifest,
            normalized["version_id"],
        )
        raw_parent = latest_raw_parent_for_normalized(
            manifest,
            verified_normalized,
        )
        raw_content = _read_manifested_artifact_bytes(
            source_path,
            raw_parent,
            max_bytes=DEFAULT_MAX_EPISODE_BYTES,
        )
        content = _read_manifested_artifact_bytes(
            source_path,
            normalized,
            max_bytes=DEFAULT_MAX_EPISODE_BYTES,
        )
        if raw_content != content:
            raise ValueError(
                "Edition cleaning requires byte-identical current raw and "
                "normalized source artifacts."
            )
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Collected raw source is not valid UTF-8.") from exc
        if text.encode("utf-8") != raw_content:
            raise ValueError("Collected raw source is not byte-preserving UTF-8.")
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise ValueError("Source-edition export exceeds the total byte limit.")
        human_content = _prepare_human_text(text).encode("utf-8")
        ai_content = _prepare_ai_text(text).encode("utf-8")
        human_artifact = _edition_artifact(
            work_id=catalog["work_id"],
            profile_id=_HUMAN_CLEANING_PROFILE["id"],
            episode_id=episode_id,
            kind="export",
            parent_version_id=raw_parent["version_id"],
            content=human_content,
        )
        ai_artifact = _edition_artifact(
            work_id=catalog["work_id"],
            profile_id=_AI_CLEANING_PROFILE["id"],
            episode_id=episode_id,
            kind="normalized_source",
            parent_version_id=raw_parent["version_id"],
            content=ai_content,
        )

        human_chapter = chapter_names[chapter["group_id"]]
        human_episode_base = safe_path_component(
            metadata.title or "",
            fallback=f"未命名话目_{episode_id}",
        )
        chapter_names_used = used_human_names[chapter["group_id"]]
        human_episode = human_episode_base
        if human_episode.casefold() in chapter_names_used:
            human_episode = safe_path_component(
                f"{human_episode_base}_{metadata.position:04d}",
                fallback=f"话目_{metadata.position:04d}_{episode_id}",
            )
        if human_episode.casefold() in chapter_names_used:
            human_episode = safe_path_component(
                f"{human_episode}_{episode_id}",
                fallback=f"话目_{metadata.position:04d}_{episode_id}",
            )
        if human_episode.casefold() in chapter_names_used:
            raise ValueError("Catalog episode titles map to a duplicate file.")
        chapter_names_used.add(human_episode.casefold())
        human_relative_path = f"{human_chapter}/{human_episode}.md"
        ai_chapter = (
            f"chapters/{chapter_order[chapter['group_id']]:03d}_"
            f"{safe_path_component(chapter['chapter_id'] or chapter['group_id'], fallback=chapter['group_id'])}"
        )
        ai_relative_path = (
            f"{ai_chapter}/episodes/{metadata.position:04d}_{episode_id}.md"
        )
        planned_episodes.append(
            {
                "episode_id": episode_id,
                "title": metadata.title,
                "position": metadata.position,
                "chapter_id": chapter["chapter_id"],
                "chapter_group_id": chapter["group_id"],
                "chapter_title": chapter["title"],
                "source_version_id": normalized["version_id"],
                "source_sha256": normalized["content_sha256"],
                "edition_input_version_id": raw_parent["version_id"],
                "edition_input_sha256": raw_parent["content_sha256"],
                "raw_source_version_id": raw_parent["version_id"],
                "raw_source_sha256": raw_parent["content_sha256"],
                "human_relative_path": human_relative_path,
                "ai_relative_path": ai_relative_path,
                "human_edition_artifact_id": human_artifact["artifact_id"],
                "human_edition_version_id": human_artifact["version_id"],
                "human_archive_relative_path": human_artifact["relative_path"],
                "ai_edition_artifact_id": ai_artifact["artifact_id"],
                "ai_edition_version_id": ai_artifact["version_id"],
                "ai_archive_relative_path": ai_artifact["relative_path"],
            }
        )
        contents_by_id[episode_id] = {
            "source": content,
            "human": human_content,
            "ai": ai_content,
            "human_artifact": human_artifact,
            "ai_artifact": ai_artifact,
        }

    manifest_sha256_after_read = _sha256_file(manifest_path)
    if manifest_sha256_after_read != manifest_sha256_before:
        raise RuntimeError(
            "Source manifest changed while source editions were being prepared."
        )

    edition_artifacts = []
    for episode in planned_episodes:
        contents = contents_by_id[episode["episode_id"]]
        edition_artifacts.extend(
            (contents["human_artifact"], contents["ai_artifact"])
        )
    edition_manifest = _merge_edition_manifest(
        manifest,
        existing_edition_manifest,
        edition_artifacts,
    )
    edition_manifest_bytes = _json_bytes(edition_manifest)
    edition_manifest_sha256 = _sha256_bytes(edition_manifest_bytes)

    common_metadata = {
        "schema_version": 2,
        "work_id": catalog["work_id"],
        "source_manifest": {
            "relative_path": manifest_relative_path,
            "sha256": manifest_sha256_before,
        },
        "edition_manifest": {
            "relative_path": edition_manifest_relative_path,
            "sha256": edition_manifest_sha256,
        },
        "catalog": {
            "relative_path": catalog_relative_path,
            "sha256": catalog["sha256"],
        },
        "source_basis": (
            "Both editions derive directly from the same current raw_source "
            "bytes, verified byte-for-byte against its current normalized_source."
        ),
        "chapters": [
            {
                "group_id": chapter["group_id"],
                "chapter_id": chapter["chapter_id"],
                "title": chapter["title"],
                "level": chapter["level"],
                "position_start": chapter["position_start"],
                "position_end": chapter["position_end"],
                "human_directory": chapter_names[chapter["group_id"]],
                "ai_directory": (
                    f"chapters/{chapter_order[chapter['group_id']]:03d}_"
                    f"{safe_path_component(chapter['chapter_id'] or chapter['group_id'], fallback=chapter['group_id'])}"
                ),
            }
            for chapter in chapters
        ],
    }
    work_metadata = catalog.get("work_metadata")
    if work_metadata is not None:
        common_metadata["work_metadata"] = work_metadata

    ai_index = {
        **common_metadata,
        "edition": "ai",
        "lookup_key": "episode_id",
        "cleaning_profile": _AI_CLEANING_PROFILE,
        "content_representation": (
            "UTF-8 Markdown with compact ruby notation, Markdown emphasis, "
            "LF line endings, and paragraph-leading U+3000 removed."
        ),
        "episodes": [
            {
                **episode,
                "output_sha256": hashlib.sha256(
                    contents_by_id[episode["episode_id"]]["ai"]
                ).hexdigest(),
            }
            for episode in planned_episodes
        ],
    }
    human_index = {
        **common_metadata,
        "edition": "human_reading",
        "lookup_key": "human_relative_path",
        "cleaning_profile": _HUMAN_CLEANING_PROFILE,
        "content_representation": (
            "UTF-8 Markdown containing escaped source text and rendered "
            "HTML ruby/emphasis markup with LF line endings."
        ),
        "episodes": [
            {
                **episode,
                "output_sha256": hashlib.sha256(
                    contents_by_id[episode["episode_id"]]["human"]
                ).hexdigest(),
            }
            for episode in planned_episodes
        ],
    }
    ai_index_bytes = _json_bytes(ai_index)
    human_index_bytes = _json_bytes(human_index)

    archive_outputs = []
    mirror_outputs = []
    for episode in planned_episodes:
        contents = contents_by_id[episode["episode_id"]]
        archive_outputs.append(
            (
                episode["human_archive_relative_path"],
                contents["human"],
            )
        )
        archive_outputs.append(
            (
                episode["ai_archive_relative_path"],
                contents["ai"],
            )
        )
        mirror_outputs.append(
            (human_path, episode["human_relative_path"], contents["human"])
        )
        mirror_outputs.append(
            (ai_path, episode["ai_relative_path"], contents["ai"])
        )
    index_outputs = (
        (human_path, "SOURCE_MAP.json", human_index_bytes),
        (ai_path, "catalog.json", ai_index_bytes),
    )

    seen_targets = set()
    reusable_before_write = 0
    for relative_path, content in archive_outputs:
        target_key = (
            os.path.normcase(str(source_path)),
            relative_path.casefold(),
        )
        if target_key in seen_targets:
            raise ValueError("Source-edition output paths collide.")
        seen_targets.add(target_key)
        if _preflight_output(source_path, relative_path, content):
            reusable_before_write += 1
    for root, relative_path, content in mirror_outputs:
        target_key = (
            os.path.normcase(str(root)),
            relative_path.casefold(),
        )
        if target_key in seen_targets:
            raise ValueError("Source-edition output paths collide.")
        seen_targets.add(target_key)
        if _preflight_output(root, relative_path, content):
            reusable_before_write += 1
    if existing_edition_bytes == edition_manifest_bytes:
        reusable_before_write += 1
    for root, relative_path, content in index_outputs:
        target_path = root.joinpath(*relative_path.split("/"))
        existing = _load_output_file(target_path)
        if existing == content:
            reusable_before_write += 1
        elif existing is not None and (
            not refresh_indexes
            or not _index_refresh_is_safe(existing, content)
        ):
            raise ValueError(
                f"Existing source-edition index differs: {relative_path}"
            )

    if _sha256_file(manifest_path) != manifest_sha256_before:
        raise RuntimeError(
            "Source manifest changed while source editions were being prepared."
        )

    created = 0
    reused = 0
    updated = 0
    for relative_path, content in archive_outputs:
        if _create_output(source_path, relative_path, content):
            created += 1
        else:
            reused += 1

    current_edition_bytes = _load_output_file(edition_manifest_path)
    if current_edition_bytes != existing_edition_bytes:
        raise RuntimeError(
            "Edition manifest changed while source editions were being prepared."
        )
    if current_edition_bytes != edition_manifest_bytes:
        if _sha256_file(manifest_path) != manifest_sha256_before:
            raise RuntimeError(
                "Source manifest changed before edition manifest update."
            )
        write_bytes_atomically(
            str(edition_manifest_path),
            edition_manifest_bytes,
        )
        if current_edition_bytes is None:
            created += 1
        else:
            updated += 1
    else:
        reused += 1

    for root, relative_path, content in mirror_outputs:
        if _create_output(root, relative_path, content):
            created += 1
        else:
            reused += 1
    for root, relative_path, content in index_outputs:
        target_path = root.joinpath(*relative_path.split("/"))
        existing = _load_output_file(target_path)
        if existing == content:
            reused += 1
            continue
        if existing is None:
            if _create_output(root, relative_path, content):
                created += 1
            else:
                reused += 1
            continue
        if (
            not refresh_indexes
            or not _index_refresh_is_safe(existing, content)
        ):
            raise RuntimeError(
                f"Source-edition index changed during generation: {relative_path}"
            )
        write_bytes_atomically(str(target_path), content)
        updated += 1

    return {
        "status": "materialized",
        "work_id": catalog["work_id"],
        "chapter_count": len(chapters),
        "episode_count": len(planned_episodes),
        "total_source_bytes": total_bytes,
        "total_human_bytes": sum(
            len(item["human"]) for item in contents_by_id.values()
        ),
        "total_ai_bytes": sum(
            len(item["ai"]) for item in contents_by_id.values()
        ),
        "created_files": created,
        "reused_files": reused,
        "updated_files": updated,
        "preexisting_identical_files": reusable_before_write,
        "source_manifest_sha256": manifest_sha256_before,
        "edition_manifest_sha256": edition_manifest_sha256,
        "catalog_sha256": catalog["sha256"],
    }
