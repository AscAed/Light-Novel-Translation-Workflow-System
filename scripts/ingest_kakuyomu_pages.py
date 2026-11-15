"""Discover or archive a catalog of public Kakuyomu episode pages."""

import argparse
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
    collect_source,
)
from utils import open_regular_file, resolve_relative_path  # noqa: E402


_CATALOG_FIELDS = frozenset({"schema_version", "work_id", "episodes"})
_ENTRY_REQUIRED_FIELDS = frozenset(
    {"episode_id", "position", "page_url"}
)
_ENTRY_FIELDS = _ENTRY_REQUIRED_FIELDS | {"title"}
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

    if not isinstance(catalog, dict) or set(catalog) != _CATALOG_FIELDS:
        raise ValueError("Kakuyomu catalog has an invalid field set.")
    version = catalog["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("Unsupported Kakuyomu catalog schema_version.")
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
    return work_id, tuple(episodes), catalog_path


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
            catalog_path = resolve_relative_path(
                str(Path(args.source_root).resolve(strict=True)),
                args.discovered_catalog,
                allow_missing=True,
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
            )
            adapter = discovery.create_page_adapter(
                page_size=args.page_size,
                max_page_bytes=args.max_page_bytes,
                max_episode_bytes=args.max_episode_bytes,
                max_catalog_bytes=args.max_catalog_bytes,
                max_episodes=args.max_episodes,
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
