"""Archive explicitly listed local source files without making network requests."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_ingestion import (  # noqa: E402
    EpisodeMetadata,
    DEFAULT_MAX_CATALOG_BYTES,
    DEFAULT_MAX_EPISODE_BYTES,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
)
from utils import open_regular_file, resolve_relative_path  # noqa: E402


_CATALOG_FIELDS = frozenset({"schema_version", "work_id", "episodes"})
DEFAULT_MAX_CATALOG_FILE_BYTES = 16 * 1024 * 1024
_ENTRY_REQUIRED_FIELDS = frozenset(
    {"episode_id", "title", "position", "relative_path"}
)
_ENTRY_FIELDS = _ENTRY_REQUIRED_FIELDS | {"source_ref"}


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Local source catalog contains a duplicate JSON field.")
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


def _positive_byte_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive byte count.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive byte count.")
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
        raise ValueError("Local source catalog byte limit must be positive.")
    source_root_path = Path(source_root).resolve(strict=True)
    catalog_path = resolve_relative_path(
        str(source_root_path),
        catalog_relative_path,
    )
    if not catalog_path.is_file():
        raise ValueError("Local source catalog must be a regular file.")

    with open_regular_file(catalog_path, binary=True) as catalog_file:
        catalog_bytes = catalog_file.read(max_catalog_file_bytes + 1)
    if len(catalog_bytes) > max_catalog_file_bytes:
        raise ValueError("Local source catalog exceeds the configured byte limit.")
    try:
        catalog = json.loads(
            catalog_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except RecursionError as exc:
        raise ValueError("Local source catalog has excessive nesting.") from exc

    if not isinstance(catalog, dict) or set(catalog) != _CATALOG_FIELDS:
        raise ValueError("Local source catalog has an invalid field set.")
    version = catalog["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("Unsupported local source catalog schema_version.")
    work_id = catalog["work_id"]
    if (
        not isinstance(work_id, str)
        or not work_id
        or work_id.strip() != work_id
        or any(ord(character) < 32 for character in work_id)
    ):
        raise ValueError("Local source catalog has an invalid work_id.")

    episode_records = catalog["episodes"]
    if not isinstance(episode_records, list):
        raise ValueError("Local source catalog episodes must be an array.")
    if not episode_records:
        raise ValueError("Local source catalog must contain at least one episode.")
    episodes = []
    for record in episode_records:
        if (
            not isinstance(record, dict)
            or not _ENTRY_REQUIRED_FIELDS <= set(record)
            or not set(record) <= _ENTRY_FIELDS
        ):
            raise ValueError("Local source catalog has an invalid episode entry.")
        metadata = EpisodeMetadata(
            episode_id=record["episode_id"],
            title=record["title"],
            position=record["position"],
            source_ref=record.get("source_ref"),
        )
        episodes.append(
            LocalEpisodeFile(
                metadata=metadata,
                relative_path=record["relative_path"],
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
    episodes: tuple[LocalEpisodeFile, ...],
    manifest_relative_path: str,
    checkpoint_relative_path: str,
) -> None:
    source_root_path = Path(source_root).resolve(strict=True)
    output_root_path = Path(output_root).resolve(strict=True)
    if not source_root_path.is_dir() or not output_root_path.is_dir():
        raise ValueError("Source and output roots must be directories.")

    output_paths = (
        resolve_relative_path(
            str(output_root_path), manifest_relative_path, allow_missing=True
        ),
        resolve_relative_path(
            str(output_root_path), checkpoint_relative_path, allow_missing=True
        ),
    )
    input_paths = [catalog_path]
    input_paths.extend(
        resolve_relative_path(str(source_root_path), episode.relative_path)
        for episode in episodes
    )
    if any(_paths_alias(output, source) for output in output_paths for source in input_paths):
        raise ValueError("Source outputs must not overwrite catalog input files.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Archive only the local files listed in an explicit JSON catalog; "
            "this command makes no network requests."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument(
        "--catalog",
        required=True,
        help="Catalog path relative to --source-root, using forward slashes.",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--page-size", type=_positive_int, default=50)
    parser.add_argument(
        "--max-episode-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_EPISODE_BYTES,
        help="Maximum bytes accepted for one source file.",
    )
    parser.add_argument(
        "--max-catalog-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_CATALOG_BYTES,
        help="Maximum combined bytes accepted from all episode source files.",
    )
    parser.add_argument(
        "--max-catalog-file-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_CATALOG_FILE_BYTES,
        help="Maximum bytes accepted for the JSON catalog file.",
    )
    parser.add_argument(
        "--max-archive-bytes",
        type=_positive_byte_limit,
        help=(
            "Optional ceiling checked before new manifest content is appended, "
            "against verified existing payload bytes; not a physical disk quota."
        ),
    )
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--checkpoint", default="source_checkpoint.json")
    args = parser.parse_args(argv)

    try:
        work_id, episodes, catalog_path = _load_catalog(
            args.source_root,
            args.catalog,
            max_catalog_file_bytes=args.max_catalog_file_bytes,
        )
        _validate_output_paths(
            args.source_root,
            args.output_root,
            catalog_path,
            episodes,
            args.manifest,
            args.checkpoint,
        )
        adapter = LocalFileAdapter(
            args.source_root,
            episodes,
            page_size=args.page_size,
            max_episode_bytes=args.max_episode_bytes,
            max_catalog_bytes=args.max_catalog_bytes,
        )
        report = collect_source(
            adapter,
            root=args.output_root,
            work_id=work_id,
            manifest_relative_path=args.manifest,
            checkpoint_relative_path=args.checkpoint,
            max_archive_bytes=args.max_archive_bytes,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
