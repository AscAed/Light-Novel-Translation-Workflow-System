"""Compare two saved Kakuyomu catalogs and optionally export a selection."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kakuyomu_catalog_diff import (  # noqa: E402
    compare_catalog_snapshots,
    create_selection_catalog,
)
from scripts.ingest_kakuyomu_pages import (  # noqa: E402
    DEFAULT_MAX_CATALOG_FILE_BYTES,
    _load_catalog_snapshot,
)
from utils import resolve_relative_path, write_new_relative_text  # noqa: E402


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive integer.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare saved Kakuyomu catalog snapshots without contacting the site "
            "or reading episode bodies."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--previous-catalog", required=True)
    parser.add_argument("--current-catalog", required=True)
    parser.add_argument(
        "--max-catalog-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_CATALOG_FILE_BYTES,
    )
    parser.add_argument(
        "--export",
        choices=("added", "updated"),
        help="Optionally create a new v1 catalog containing only this selection.",
    )
    parser.add_argument(
        "--catalog-output",
        help="New relative path under --source-root; existing files are never replaced.",
    )
    args = parser.parse_args(argv)

    if (args.export is None) != (args.catalog_output is None):
        parser.error("--export and --catalog-output must be used together.")

    try:
        previous = _load_catalog_snapshot(
            args.source_root,
            args.previous_catalog,
            max_catalog_file_bytes=args.max_catalog_file_bytes,
        )
        current = _load_catalog_snapshot(
            args.source_root,
            args.current_catalog,
            max_catalog_file_bytes=args.max_catalog_file_bytes,
        )
        report = compare_catalog_snapshots(previous, current)
        if args.export is not None:
            selection = create_selection_catalog(current, report, args.export)
            output_path = resolve_relative_path(
                args.source_root,
                args.catalog_output,
                allow_missing=True,
            )
            catalog_text = (
                json.dumps(
                    selection,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
            write_new_relative_text(
                args.source_root,
                args.catalog_output,
                catalog_text,
            )
            report["exported_catalog"] = output_path.relative_to(
                Path(args.source_root).resolve(strict=True)
            ).as_posix()
            report["exported_catalog_sha256"] = hashlib.sha256(
                catalog_text.replace("\n", os.linesep).encode("utf-8")
            ).hexdigest()
            report["exported_selection"] = args.export
            report["exported_episode_count"] = len(selection["episodes"])
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
