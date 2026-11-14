"""Archive explicitly listed local source files without making network requests."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_ingestion import (  # noqa: E402
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
)
from utils import open_regular_file, resolve_relative_path  # noqa: E402


_CATALOG_FIELDS = frozenset({"schema_version", "work_id", "episodes"})
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


def _load_catalog(source_root: str, catalog_relative_path: str):
    source_root_path = Path(source_root).resolve(strict=True)
    catalog_path = resolve_relative_path(
        str(source_root_path),
        catalog_relative_path,
    )
    if not catalog_path.is_file():
        raise ValueError("Local source catalog must be a regular file.")

    with open_regular_file(catalog_path, binary=True) as catalog_file:
        catalog = json.loads(
            catalog_file.read().decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )

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

    return work_id, tuple(episodes)


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
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--checkpoint", default="source_checkpoint.json")
    args = parser.parse_args(argv)

    try:
        work_id, episodes = _load_catalog(args.source_root, args.catalog)
        adapter = LocalFileAdapter(
            args.source_root,
            episodes,
            page_size=args.page_size,
        )
        report = collect_source(
            adapter,
            root=args.output_root,
            work_id=work_id,
            manifest_relative_path=args.manifest,
            checkpoint_relative_path=args.checkpoint,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
