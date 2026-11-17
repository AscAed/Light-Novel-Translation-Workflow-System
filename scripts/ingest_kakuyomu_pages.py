"""Discover or archive a catalog of public Kakuyomu episode pages."""

import argparse
import hashlib
import json
import os
import sys
import math
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kakuyomu_page_source import (  # noqa: E402
    DEFAULT_MAX_CATALOG_BYTES,
    DEFAULT_MAX_EPISODE_BYTES,
    DEFAULT_MAX_EPISODES,
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    MAX_REQUEST_DELAY_SECONDS,
    MIN_REQUEST_DELAY_SECONDS,
    DEFAULT_REQUEST_DELAY_SECONDS,
    KakuyomuEpisodePage,
    KakuyomuPageAdapter,
    discover_kakuyomu_work_catalog,
    save_discovered_work_catalog,
)
from source_ingestion import (  # noqa: E402
    EpisodeMetadata,
    SourceAccessDenied,
    SourceRateLimited,
    SourceUnavailable,
    compare_full_refresh_versions,
    collect_source,
    prepare_append_only_checkpoint,
    prepare_full_refresh_checkpoint,
)
from kakuyomu_catalog_diff import (  # noqa: E402
    append_only_catalog_status,
    exact_refresh_catalog_status,
)
from utils import open_regular_file, resolve_relative_path  # noqa: E402


_CATALOG_V1_FIELDS = frozenset({"schema_version", "work_id", "episodes"})
_CATALOG_V2_FIELDS = _CATALOG_V1_FIELDS | {"chapters"}
_CATALOG_V3_FIELDS = _CATALOG_V2_FIELDS | {"work_metadata"}
_WORK_METADATA_FIELDS = frozenset(
    {
        "source_url",
        "title",
        "author_name",
        "author_screen_name",
        "catchphrase",
        "introduction",
        "genre",
        "tags",
        "serial_status",
        "published_at",
        "last_episode_published_at",
        "public_episode_count",
    }
)
_ENTRY_REQUIRED_FIELDS = frozenset(
    {"episode_id", "position", "page_url"}
)
_ENTRY_FIELDS = _ENTRY_REQUIRED_FIELDS | {"title"}
_CHAPTER_FIELDS = frozenset(
    {
        "group_id",
        "chapter_id",
        "title",
        "level",
        "position_start",
        "position_end",
        "episode_ids",
    }
)
DEFAULT_MAX_CATALOG_FILE_BYTES = 16 * 1024 * 1024
_PROJECTS_ROOT = Path(__file__).resolve().parent.parent / "projects"


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Kakuyomu catalog contains a duplicate JSON field.")
        result[key] = value
    return result


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive integer.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive finite number.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("Must be a positive finite number.")
    return parsed


def _minimum_delay(value: str) -> float:
    parsed = _positive_float(value)
    if not MIN_REQUEST_DELAY_SECONDS <= parsed <= MAX_REQUEST_DELAY_SECONDS:
        raise argparse.ArgumentTypeError(
            "Request delay must be between 1.5 and 3 seconds."
        )
    return parsed


def _load_catalog(
    source_root: str,
    catalog_relative_path: str,
    *,
    max_catalog_file_bytes: int = DEFAULT_MAX_CATALOG_FILE_BYTES,
):
    snapshot = _load_catalog_snapshot(
        source_root,
        catalog_relative_path,
        max_catalog_file_bytes=max_catalog_file_bytes,
    )
    return snapshot["work_id"], snapshot["episodes"], snapshot["path"]


def _load_catalog_snapshot(
    source_root: str,
    catalog_relative_path: str,
    *,
    max_catalog_file_bytes: int = DEFAULT_MAX_CATALOG_FILE_BYTES,
):
    if (
        isinstance(max_catalog_file_bytes, bool)
        or not isinstance(max_catalog_file_bytes, int)
        or max_catalog_file_bytes < 1
    ):
        raise ValueError("Kakuyomu catalog byte limit must be positive.")
    source_root_path = Path(source_root).resolve(strict=True)
    if not source_root_path.is_dir():
        raise ValueError("Kakuyomu source root must be a directory.")
    catalog_path = resolve_relative_path(
        str(source_root_path),
        catalog_relative_path,
    )
    if not catalog_path.is_file():
        raise ValueError("Kakuyomu catalog must be a regular file.")
    with open_regular_file(catalog_path, binary=True) as catalog_file:
        catalog_bytes = catalog_file.read(max_catalog_file_bytes + 1)
    if len(catalog_bytes) > max_catalog_file_bytes:
        raise ValueError("Kakuyomu catalog exceeds the configured byte limit.")
    try:
        catalog = json.loads(
            catalog_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Kakuyomu catalog is not valid UTF-8 JSON.") from exc

    if not isinstance(catalog, dict) or "schema_version" not in catalog:
        raise ValueError("Kakuyomu catalog has an invalid field set.")
    version = catalog["schema_version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {1, 2, 3}
    ):
        raise ValueError("Unsupported Kakuyomu catalog schema_version.")
    expected_fields = {
        1: _CATALOG_V1_FIELDS,
        2: _CATALOG_V2_FIELDS,
        3: _CATALOG_V3_FIELDS,
    }[version]
    if set(catalog) != expected_fields:
        raise ValueError("Kakuyomu catalog has an invalid field set.")
    work_id = catalog["work_id"]
    if (
        not isinstance(work_id, str)
        or not work_id.isascii()
        or not work_id.isdecimal()
    ):
        raise ValueError("Kakuyomu catalog has an invalid work_id.")
    records = catalog["episodes"]
    if not isinstance(records, list) or not records:
        raise ValueError("Kakuyomu catalog must contain episodes.")
    episodes = []
    for record in records:
        if (
            not isinstance(record, dict)
            or not _ENTRY_REQUIRED_FIELDS <= set(record)
            or not set(record) <= _ENTRY_FIELDS
        ):
            raise ValueError("Kakuyomu catalog has an invalid episode entry.")
        episodes.append(
            KakuyomuEpisodePage(
                EpisodeMetadata(
                    episode_id=record["episode_id"],
                    title=record.get("title", ""),
                    position=record["position"],
                ),
                page_url=record["page_url"],
            )
        )
    if version >= 2:
        chapter_records = catalog["chapters"]
        if not isinstance(chapter_records, list):
            raise ValueError("Kakuyomu catalog has invalid chapter groups.")
        catalog_episode_ids = [episode.metadata.episode_id for episode in episodes]
        catalog_positions = [episode.metadata.position for episode in episodes]
        if (
            len(catalog_episode_ids) != len(set(catalog_episode_ids))
            or catalog_positions != list(range(1, len(episodes) + 1))
        ):
            raise ValueError(
                "Kakuyomu catalog episodes must have unique IDs and ordered positions."
            )
        seen_group_ids = set()
        grouped_episode_ids = []
        episode_positions = {
            episode_id: position
            for episode_id, position in zip(catalog_episode_ids, catalog_positions)
        }
        for chapter in chapter_records:
            if not isinstance(chapter, dict) or set(chapter) != _CHAPTER_FIELDS:
                raise ValueError("Kakuyomu catalog has an invalid chapter group.")
            group_id = chapter["group_id"]
            chapter_id = chapter["chapter_id"]
            title = chapter["title"]
            level = chapter["level"]
            position_start = chapter["position_start"]
            position_end = chapter["position_end"]
            episode_ids = chapter["episode_ids"]
            if (
                not isinstance(group_id, str)
                or not group_id
                or any(ord(character) < 32 for character in group_id)
                or group_id in seen_group_ids
                or (
                    chapter_id is not None
                    and (
                        not isinstance(chapter_id, str)
                        or not chapter_id
                        or any(ord(character) < 32 for character in chapter_id)
                    )
                )
                or (title is not None and not isinstance(title, str))
                or (
                    title is not None
                    and any(ord(character) < 32 for character in title)
                )
                or (
                    level is not None
                    and (
                        isinstance(level, bool)
                        or not isinstance(level, int)
                        or level < 0
                    )
                )
                or not isinstance(episode_ids, list)
                or any(
                    not isinstance(episode_id, str) for episode_id in episode_ids
                )
                or len(episode_ids) != len(set(episode_ids))
            ):
                raise ValueError("Kakuyomu catalog has invalid chapter metadata.")
            seen_group_ids.add(group_id)
            if episode_ids:
                if (
                    isinstance(position_start, bool)
                    or not isinstance(position_start, int)
                    or isinstance(position_end, bool)
                    or not isinstance(position_end, int)
                    or position_start < 1
                    or position_end < position_start
                    or position_end - position_start + 1 != len(episode_ids)
                    or any(
                        episode_id not in episode_positions
                        or episode_positions[episode_id]
                        != position_start + index
                        for index, episode_id in enumerate(episode_ids)
                    )
                ):
                    raise ValueError(
                        "Kakuyomu catalog chapter positions are inconsistent."
                    )
            elif position_start is not None or position_end is not None:
                raise ValueError(
                    "Empty Kakuyomu chapter groups must not declare positions."
                )
            grouped_episode_ids.extend(episode_ids)
        if grouped_episode_ids != [
            episode.metadata.episode_id for episode in episodes
        ]:
            raise ValueError(
                "Kakuyomu catalog chapter groups do not match episode order."
            )
    work_metadata = catalog.get("work_metadata")
    if version == 3:
        if (
            not isinstance(work_metadata, dict)
            or set(work_metadata) != _WORK_METADATA_FIELDS
        ):
            raise ValueError("Kakuyomu catalog has invalid work metadata.")
        source_url = work_metadata["source_url"]
        title = work_metadata["title"]
        author_name = work_metadata["author_name"]
        author_screen_name = work_metadata["author_screen_name"]
        tags = work_metadata["tags"]
        optional_text_fields = (
            "catchphrase",
            "introduction",
            "genre",
            "serial_status",
            "published_at",
            "last_episode_published_at",
        )
        if (
            source_url != f"https://kakuyomu.jp/works/{work_id}"
            or not isinstance(title, str)
            or not title.strip()
            or any(ord(character) < 32 for character in title)
            or (
                author_name is None
                and author_screen_name is not None
            )
            or (
                author_screen_name is None
                and author_name is not None
            )
            or (
                author_name is not None
                and (
                    not isinstance(author_name, str)
                    or not author_name.strip()
                    or any(ord(character) < 32 for character in author_name)
                )
            )
            or (
                author_screen_name is not None
                and (
                    not isinstance(author_screen_name, str)
                    or not author_screen_name.strip()
                    or any(
                        ord(character) < 32 for character in author_screen_name
                    )
                )
            )
            or not isinstance(tags, list)
            or any(
                not isinstance(tag, str)
                or not tag.strip()
                or any(ord(character) < 32 for character in tag)
                for tag in tags
            )
            or any(
                work_metadata[field] is not None
                and (
                    not isinstance(work_metadata[field], str)
                    or any(
                        ord(character) < 32
                        and character not in "\t\n\r"
                        for character in work_metadata[field]
                    )
                )
                for field in optional_text_fields
            )
            or isinstance(work_metadata["public_episode_count"], bool)
            or not isinstance(work_metadata["public_episode_count"], int)
            or work_metadata["public_episode_count"] != len(episodes)
        ):
            raise ValueError("Kakuyomu catalog has invalid work metadata.")
    return {
        "schema_version": version,
        "work_id": work_id,
        "work_metadata": work_metadata,
        "episodes": tuple(episodes),
        "chapters": tuple(catalog.get("chapters", ())),
        "path": catalog_path,
        "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
    }


def _paths_alias(first: Path, second: Path) -> bool:
    if os.path.normcase(str(first)) == os.path.normcase(str(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError("Could not verify source/output path identity.") from exc


def _validate_output_paths(
    source_root: str,
    output_root: str,
    catalog_path: Path,
    manifest_relative_path: str,
    checkpoint_relative_path: str,
) -> None:
    source_root_path = Path(source_root).resolve(strict=True)
    output_root_path = Path(output_root).resolve(strict=True)
    if not source_root_path.is_dir() or not output_root_path.is_dir():
        raise ValueError("Source and output roots must be directories.")
    outputs = (
        resolve_relative_path(
            str(output_root_path), manifest_relative_path, allow_missing=True
        ),
        resolve_relative_path(
            str(output_root_path), checkpoint_relative_path, allow_missing=True
        ),
    )
    if _paths_alias(*outputs):
        raise ValueError("Manifest and checkpoint paths must be different.")
    if any(_paths_alias(output, catalog_path) for output in outputs):
        raise ValueError("Source outputs must not overwrite the catalog.")


def _resolve_project_ingestion_context(
    project: str,
    source_root: str,
    output_root: str,
) -> dict:
    if (
        not isinstance(project, str)
        or not project
        or project.strip() != project
        or project in {".", ".."}
        or "/" in project
        or "\\" in project
    ):
        raise ValueError("Invalid project name.")
    projects_root = _PROJECTS_ROOT.resolve(strict=True)
    project_path = projects_root / project
    if project_path.is_symlink():
        raise ValueError("Project directory must not be a symbolic link.")
    project_path = project_path.resolve(strict=True)
    try:
        common = Path(os.path.commonpath((projects_root, project_path)))
    except ValueError as exc:
        raise ValueError("Invalid project name.") from exc
    if common != projects_root or project_path == projects_root:
        raise ValueError("Invalid project name.")

    source_path = (project_path / "SourceArchive").resolve(strict=True)
    if (
        not source_path.is_dir()
        or (project_path / "SourceArchive").is_symlink()
        or Path(source_root).resolve(strict=True) != source_path
        or Path(output_root).resolve(strict=True) != source_path
    ):
        raise ValueError(
            "--project requires --source-root and --output-root to be "
            "that project's SourceArchive directory."
        )

    from pipeline import _resolve_project_content_dir, _resolve_project_output_override

    translation_root = _resolve_project_output_override(
        str(project_path)
    ) or _resolve_project_content_dir(
        str(project_path),
        "熟肉",
        "OUTPUT_DIR",
    )
    return {
        "project_root": project_path,
        "source_root": source_path,
        "translation_root": Path(translation_root),
        "ai_root": project_path / "RAWs_AI",
        "tm_path": project_path / "Knowledge" / "translation_memory.json",
        "knowledge_path": (
            project_path / "Knowledge" / "KNOWLEDGE_PROVENANCE_draft.json"
        ),
        "story_summary_path": (
            project_path / "Knowledge" / "STORY_SUMMARY_reviewed.json"
        ),
    }


def _load_json_regular(path: Path, label: str):
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link.")
    with open_regular_file(path) as stream:
        return json.load(stream, object_pairs_hook=_reject_duplicate_keys)


def _sha256_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open_regular_file(path, binary=True) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ai_edition_index_freshness(
    *,
    source_root: Path,
    ai_root: Path,
    catalog_relative_path: str,
    manifest_relative_path: str,
    edition_manifest_relative_path: str,
) -> tuple[dict[str, str], list[dict[str, str]] | None]:
    index_path = ai_root / "catalog.json"
    if not ai_root.is_dir() or not index_path.exists():
        return (
            {
                "identity": "ai_edition_index",
                "status": "unverified",
                "detail": "No AI edition index is available for this project.",
            },
            None,
        )
    try:
        index = _load_json_regular(index_path, "AI edition index")
        current_catalog = _load_catalog_snapshot(
            str(source_root),
            catalog_relative_path,
        )
        source_manifest_path = resolve_relative_path(
            str(source_root),
            manifest_relative_path,
        )
        edition_manifest_path = resolve_relative_path(
            str(source_root),
            edition_manifest_relative_path,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return (
            {
                "identity": "ai_edition_index",
                "status": "invalid",
                "detail": "AI edition index or current catalog could not be verified.",
            },
            None,
        )

    if (
        not isinstance(index, dict)
        or index.get("schema_version") != 2
        or index.get("edition") != "ai"
        or not isinstance(index.get("work_id"), str)
        or not isinstance(index.get("episodes"), list)
    ):
        return (
            {
                "identity": "ai_edition_index",
                "status": "invalid",
                "detail": "AI edition index has an unsupported schema.",
            },
            None,
        )

    expected_sources = []
    valid_episode_records = True
    for episode in index["episodes"]:
        if (
            not isinstance(episode, dict)
            or not isinstance(episode.get("ai_archive_relative_path"), str)
            or not isinstance(episode.get("ai_edition_version_id"), str)
        ):
            valid_episode_records = False
            break
        expected_sources.append(
            {
                "filename": episode["ai_archive_relative_path"],
                "source_version_id": episode["ai_edition_version_id"],
            }
        )
    if not valid_episode_records:
        expected_sources = None

    source_record = index.get("source_manifest")
    edition_record = index.get("edition_manifest")
    catalog_record = index.get("catalog")
    if not all(
        isinstance(record, dict)
        and isinstance(record.get("relative_path"), str)
        and isinstance(record.get("sha256"), str)
        for record in (source_record, edition_record, catalog_record)
    ):
        return (
            {
                "identity": "ai_edition_index",
                "status": "invalid",
                "detail": "AI edition index is missing lineage identities.",
            },
            expected_sources,
        )

    references_match = (
        source_record["relative_path"].replace("\\", "/")
        == manifest_relative_path.replace("\\", "/")
        and source_record["sha256"] == _sha256_regular_file(source_manifest_path)
        and edition_record["relative_path"].replace("\\", "/")
        == edition_manifest_relative_path.replace("\\", "/")
        and edition_record["sha256"] == _sha256_regular_file(edition_manifest_path)
        and catalog_record["relative_path"].replace("\\", "/")
        == catalog_relative_path.replace("\\", "/")
        and catalog_record["sha256"] == current_catalog["sha256"]
    )
    catalog_episode_map = {
        episode.metadata.episode_id: (
            episode.metadata.position,
            episode.metadata.title,
        )
        for episode in current_catalog["episodes"]
    }
    index_episode_map = {}
    for episode in index["episodes"]:
        if not isinstance(episode, dict):
            index_episode_map = {}
            break
        episode_id = episode.get("episode_id")
        position = episode.get("position")
        title = episode.get("title")
        if (
            not isinstance(episode_id, str)
            or isinstance(position, bool)
            or not isinstance(position, int)
            or not isinstance(title, str)
            or episode_id in index_episode_map
        ):
            index_episode_map = {}
            break
        index_episode_map[episode_id] = (position, title)
    if index.get("work_id") != current_catalog["work_id"] or (
        index_episode_map != catalog_episode_map
    ):
        references_match = False

    if not references_match:
        return (
            {
                "identity": "ai_edition_index",
                "status": "stale",
                "detail": (
                    "AI edition index does not match the current source, "
                    "edition manifest, or catalog."
                ),
            },
            expected_sources,
        )

    try:
        from source_editions import verify_ai_edition_index

        verify_ai_edition_index(
            source_root=str(source_root),
            ai_root=str(ai_root),
            source_manifest_relative_path=manifest_relative_path,
            edition_manifest_relative_path=edition_manifest_relative_path,
        )
    except (OSError, UnicodeError, ValueError):
        return (
            {
                "identity": "ai_edition_index",
                "status": "invalid",
                "detail": "AI edition files or source lineage failed verification.",
            },
            expected_sources,
        )
    return (
        {
            "identity": "ai_edition_index",
            "status": "verified",
            "detail": "AI edition index matches the current source and catalog.",
        },
        expected_sources,
    )


def _record_project_ingestion_freshness(
    *,
    context: dict,
    catalog_relative_path: str,
    manifest_relative_path: str,
) -> dict:
    from scripts.snapshot_downstream_freshness import (
        FRESHNESS_STATUSES,
        build_downstream_freshness_snapshot,
        persist_downstream_freshness_snapshot,
    )
    from source_editions import synchronize_edition_manifest_with_source_history

    edition_manifest_relative_path = "source_editions_manifest.json"
    edition_manifest = synchronize_edition_manifest_with_source_history(
        source_root=str(context["source_root"]),
        source_manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
    )
    ai_finding, expected_sources = _ai_edition_index_freshness(
        source_root=context["source_root"],
        ai_root=context["ai_root"],
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
    )

    tm_path = context["tm_path"]
    knowledge_path = context["knowledge_path"]
    summary_path = context["story_summary_path"]
    tm_data = (
        _load_json_regular(tm_path, "Translation memory")
        if tm_path.exists() or tm_path.is_symlink()
        else None
    )
    knowledge = (
        _load_json_regular(knowledge_path, "Knowledge provenance")
        if knowledge_path.exists() or knowledge_path.is_symlink()
        else None
    )
    summary_present = summary_path.exists() or summary_path.is_symlink()
    can_audit_summary = summary_present and expected_sources is not None
    snapshot = build_downstream_freshness_snapshot(
        tm_data=tm_data,
        source_root=str(context["source_root"]),
        translation_root=str(context["translation_root"]),
        manifest_relative_path=edition_manifest_relative_path,
        tm_label=tm_path.name if tm_data is not None else None,
        knowledge_provenance=knowledge,
        knowledge_label=knowledge_path.name if knowledge is not None else None,
        story_summary_path=(
            str(summary_path) if can_audit_summary else None
        ),
        expected_sources=expected_sources if can_audit_summary else None,
    )
    ai_status = ai_finding["status"]
    snapshot["consumers"]["ai_edition_index"] = {
        "input": "RAWs_AI/catalog.json",
        "summary": {
            status: int(status == ai_status)
            for status in FRESHNESS_STATUSES
        },
        "findings": [ai_finding],
    }
    if summary_present and not can_audit_summary:
        summary_finding = {
            "identity": "reviewed_story_summary",
            "status": "unverified",
            "detail": (
                "The current AI edition chapter map is unavailable for "
                "full-book summary verification."
            ),
        }
        snapshot["consumers"]["reviewed_story_summary"] = {
            "input": summary_path.name,
            "summary": {
                status: int(status == "unverified")
                for status in FRESHNESS_STATUSES
            },
            "findings": [summary_finding],
        }
    elif (
        ai_status != "verified"
        and "reviewed_story_summary" in snapshot["consumers"]
    ):
        summary_consumer = snapshot["consumers"]["reviewed_story_summary"]
        summary_consumer["summary"] = {
            status: int(status == "stale")
            for status in FRESHNESS_STATUSES
        }
        summary_consumer["findings"] = [
            {
                "identity": "reviewed_story_summary",
                "status": "stale",
                "detail": (
                    "AI edition index is stale for the current source catalog; "
                    "the full-book summary must be reviewed against the refreshed edition."
                ),
            }
        ]

    persisted = persist_downstream_freshness_snapshot(
        snapshot,
        str(context["source_root"]),
    )
    return {
        "status": "persisted",
        "path": persisted["path"],
        "snapshot_id": persisted["snapshot_id"],
        "created": persisted["created"],
        "edition_manifest": edition_manifest,
        "consumers": {
            name: consumer["summary"]
            for name, consumer in snapshot["consumers"].items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch an explicit Kakuyomu episode catalog or discover all public "
            "episodes from a work page. The command checks robots.txt."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument(
        "--project",
        help=(
            "Optional project name. Requires --source-root and --output-root "
            "to be that project's SourceArchive and records downstream freshness."
        ),
    )
    parser.add_argument(
        "--catalog",
        help="Existing catalog path relative to --source-root.",
    )
    parser.add_argument(
        "--work-url",
        help="Discover the public episode catalog from this Kakuyomu work URL.",
    )
    parser.add_argument(
        "--discovered-catalog",
        default="source_catalog.discovered.json",
        help="New relative catalog path used with --work-url.",
    )
    parser.add_argument(
        "--incremental-from-catalog",
        help="Baseline full catalog for an append-only update.",
    )
    parser.add_argument(
        "--incremental-from-checkpoint",
        help="Complete baseline checkpoint for an append-only update.",
    )
    parser.add_argument(
        "--refresh-from-catalog",
        help="Baseline full catalog for an explicit full body refresh.",
    )
    parser.add_argument(
        "--refresh-from-checkpoint",
        help="Complete baseline checkpoint for an explicit full body refresh.",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--page-size", type=_positive_int, default=50)
    parser.add_argument(
        "--max-page-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_PAGE_BYTES,
    )
    parser.add_argument(
        "--max-episode-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_EPISODE_BYTES,
    )
    parser.add_argument(
        "--max-catalog-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_CATALOG_BYTES,
    )
    parser.add_argument(
        "--max-catalog-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_CATALOG_FILE_BYTES,
    )
    parser.add_argument(
        "--max-episodes",
        type=_positive_int,
        default=DEFAULT_MAX_EPISODES,
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=_minimum_delay,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_float,
        default=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-archive-bytes",
        type=_positive_int,
        help=(
            "Optional ceiling checked before new manifest content is appended; "
            "not a physical disk quota."
        ),
    )
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--checkpoint")
    args = parser.parse_args(argv)

    try:
        if (args.catalog is None) == (args.work_url is None):
            parser.error("Specify exactly one of --catalog or --work-url.")
        project_context = None
        if args.project is not None:
            if args.manifest != "source_manifest.json":
                raise ValueError(
                    "--project requires the default source_manifest.json."
                )
            project_context = _resolve_project_ingestion_context(
                args.project,
                args.source_root,
                args.output_root,
            )
        incremental_requested = (
            args.incremental_from_catalog is not None
            or args.incremental_from_checkpoint is not None
        )
        refresh_requested = (
            args.refresh_from_catalog is not None
            or args.refresh_from_checkpoint is not None
        )
        if incremental_requested and refresh_requested:
            parser.error("Append-only update and full refresh modes are exclusive.")
        if (args.incremental_from_catalog is None) != (
            args.incremental_from_checkpoint is None
        ):
            parser.error(
                "--incremental-from-catalog and "
                "--incremental-from-checkpoint must be used together."
            )
        if (args.refresh_from_catalog is None) != (
            args.refresh_from_checkpoint is None
        ):
            parser.error(
                "--refresh-from-catalog and --refresh-from-checkpoint "
                "must be used together."
            )
        if (incremental_requested or refresh_requested) and (
            not args.work_url or not args.checkpoint
        ):
            parser.error(
                "Catalog updates require --work-url and a new --checkpoint."
            )
        checkpoint = args.checkpoint or (
            "source_checkpoint.discovered.json"
            if args.work_url
            else "source_checkpoint.json"
        )
        discovery = None
        if args.work_url:
            discovery = discover_kakuyomu_work_catalog(
                args.work_url,
                max_work_page_bytes=args.max_page_bytes,
                max_episodes=args.max_episodes,
                request_delay_seconds=args.request_delay_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            work_id = discovery.work_id
            episodes = discovery.episodes
            source_root_path = Path(args.source_root).resolve(strict=True)
            catalog_path = resolve_relative_path(
                str(source_root_path),
                args.discovered_catalog,
                allow_missing=True,
            )
            if incremental_requested or refresh_requested:
                baseline_catalog_argument = (
                    args.incremental_from_catalog
                    if incremental_requested
                    else args.refresh_from_catalog
                )
                baseline_checkpoint_argument = (
                    args.incremental_from_checkpoint
                    if incremental_requested
                    else args.refresh_from_checkpoint
                )
                previous_catalog_path = resolve_relative_path(
                    str(source_root_path),
                    baseline_catalog_argument,
                )
                output_root_path = Path(args.output_root).resolve(strict=True)
                baseline_checkpoint_path = resolve_relative_path(
                    str(output_root_path),
                    baseline_checkpoint_argument,
                )
                new_checkpoint_path = resolve_relative_path(
                    str(output_root_path),
                    checkpoint,
                    allow_missing=True,
                )
                if _paths_alias(catalog_path, previous_catalog_path):
                    raise ValueError(
                        "Catalog update requires a new discovered catalog path."
                    )
                if _paths_alias(new_checkpoint_path, baseline_checkpoint_path):
                    raise ValueError(
                        "Catalog update requires a new checkpoint path."
                    )
        else:
            work_id, episodes, catalog_path = _load_catalog(
                args.source_root,
                args.catalog,
                max_catalog_file_bytes=args.max_catalog_file_bytes,
            )
        _validate_output_paths(
            args.source_root,
            args.output_root,
            catalog_path,
            args.manifest,
            checkpoint,
        )
        if discovery is not None:
            catalog_path = save_discovered_work_catalog(
                args.source_root,
                args.discovered_catalog,
                work_id,
                episodes,
                chapters=discovery.chapters,
                work_metadata=discovery.work_metadata,
            )
            adapter = discovery.create_page_adapter(
                page_size=args.page_size,
                max_page_bytes=args.max_page_bytes,
                max_episode_bytes=args.max_episode_bytes,
                max_catalog_bytes=args.max_catalog_bytes,
                max_episodes=args.max_episodes,
            )
            if incremental_requested:
                previous_snapshot = _load_catalog_snapshot(
                    args.source_root,
                    args.incremental_from_catalog,
                    max_catalog_file_bytes=args.max_catalog_file_bytes,
                )
                current_snapshot = _load_catalog_snapshot(
                    args.source_root,
                    args.discovered_catalog,
                    max_catalog_file_bytes=args.max_catalog_file_bytes,
                )
                compatibility = append_only_catalog_status(
                    previous_snapshot, current_snapshot
                )
                if not compatibility["append_only"]:
                    raise ValueError(
                        "Catalog changes are not append-only: "
                        + ", ".join(compatibility["issues"])
                    )
                baseline_ids = [
                    episode.metadata.episode_id
                    for episode in previous_snapshot["episodes"]
                ]
                checkpoint_data = prepare_append_only_checkpoint(
                    adapter,
                    root=args.output_root,
                    work_id=work_id,
                    current_episodes=tuple(
                        episode.metadata for episode in discovery.episodes
                    ),
                    baseline_episode_ids=baseline_ids,
                    baseline_checkpoint_relative_path=(
                        args.incremental_from_checkpoint
                    ),
                    checkpoint_relative_path=checkpoint,
                    manifest_relative_path=args.manifest,
                    max_archive_bytes=args.max_archive_bytes,
                )
                report = collect_source(
                    adapter,
                    root=args.output_root,
                    work_id=work_id,
                    manifest_relative_path=args.manifest,
                    checkpoint_relative_path=checkpoint,
                    max_archive_bytes=args.max_archive_bytes,
                    work_metadata=discovery.work_metadata.to_catalog_record(),
                )
                report["incremental_update"] = {
                    **compatibility,
                    "reused_count": len(baseline_ids),
                    "checkpoint_status": checkpoint_data["status"],
                }
            elif refresh_requested:
                previous_snapshot = _load_catalog_snapshot(
                    args.source_root,
                    args.refresh_from_catalog,
                    max_catalog_file_bytes=args.max_catalog_file_bytes,
                )
                current_snapshot = _load_catalog_snapshot(
                    args.source_root,
                    args.discovered_catalog,
                    max_catalog_file_bytes=args.max_catalog_file_bytes,
                )
                compatibility = exact_refresh_catalog_status(
                    previous_snapshot, current_snapshot
                )
                if not compatibility["same_catalog"]:
                    raise ValueError(
                        "Full refresh requires an unchanged episode catalog: "
                        + ", ".join(compatibility["issues"])
                    )
                episode_ids = [
                    episode.metadata.episode_id
                    for episode in current_snapshot["episodes"]
                ]
                refresh = prepare_full_refresh_checkpoint(
                    adapter,
                    root=args.output_root,
                    work_id=work_id,
                    current_episodes=tuple(
                        episode.metadata for episode in discovery.episodes
                    ),
                    baseline_episode_ids=episode_ids,
                    baseline_catalog_sha256=previous_snapshot["sha256"],
                    baseline_checkpoint_relative_path=args.refresh_from_checkpoint,
                    checkpoint_relative_path=checkpoint,
                    manifest_relative_path=args.manifest,
                    max_archive_bytes=args.max_archive_bytes,
                )
                report = collect_source(
                    refresh["adapter"],
                    root=args.output_root,
                    work_id=work_id,
                    manifest_relative_path=args.manifest,
                    checkpoint_relative_path=checkpoint,
                    max_archive_bytes=args.max_archive_bytes,
                    work_metadata=discovery.work_metadata.to_catalog_record(),
                )
                if report["status"] == "complete":
                    report["content_refresh"] = compare_full_refresh_versions(
                        root=args.output_root,
                        work_id=work_id,
                        episode_ids=episode_ids,
                        baseline_checkpoint_relative_path=(
                            args.refresh_from_checkpoint
                        ),
                        checkpoint_relative_path=checkpoint,
                        manifest_relative_path=args.manifest,
                    )
                else:
                    report["content_refresh"] = {
                        "status": "pending",
                        "episode_count": len(episode_ids),
                        "changed_count": None,
                        "downstream_review_required": None,
                    }
            else:
                report = collect_source(
                    adapter,
                    root=args.output_root,
                    work_id=work_id,
                    manifest_relative_path=args.manifest,
                    checkpoint_relative_path=checkpoint,
                    max_archive_bytes=args.max_archive_bytes,
                    work_metadata=discovery.work_metadata.to_catalog_record(),
                )
        else:
            adapter = KakuyomuPageAdapter(
                work_id,
                episodes,
                page_size=args.page_size,
                max_page_bytes=args.max_page_bytes,
                max_episode_bytes=args.max_episode_bytes,
                max_catalog_bytes=args.max_catalog_bytes,
                max_episodes=args.max_episodes,
                request_delay_seconds=args.request_delay_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            report = collect_source(
                adapter,
                root=args.output_root,
                work_id=work_id,
                manifest_relative_path=args.manifest,
                checkpoint_relative_path=checkpoint,
                max_archive_bytes=args.max_archive_bytes,
            )
        if discovery is not None:
            report["discovered_catalog"] = str(
                catalog_path.relative_to(Path(args.source_root).resolve(strict=True))
            )
            report["discovery_fingerprint"] = discovery.source_fingerprint
        if project_context is not None:
            catalog_relative_path = catalog_path.relative_to(
                project_context["source_root"]
            ).as_posix()
            try:
                report["project_freshness_snapshot"] = (
                    _record_project_ingestion_freshness(
                        context=project_context,
                        catalog_relative_path=catalog_relative_path,
                        manifest_relative_path=args.manifest,
                    )
                )
            except (
                OSError,
                UnicodeError,
                ValueError,
                RuntimeError,
                json.JSONDecodeError,
            ) as exc:
                report["project_freshness_snapshot"] = {
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                }
    except (
        OSError,
        UnicodeError,
        ValueError,
        SourceAccessDenied,
        SourceRateLimited,
        SourceUnavailable,
    ) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
