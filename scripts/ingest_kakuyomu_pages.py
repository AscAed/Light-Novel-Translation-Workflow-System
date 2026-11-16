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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch an explicit Kakuyomu episode catalog or discover all public "
            "episodes from a work page. The command checks robots.txt."
        )
    )
    parser.add_argument("--source-root", required=True)
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
