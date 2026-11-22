"""Create versioned, self-contained source-book bundles."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from book_bundles import (  # noqa: E402
    DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    DEFAULT_MAX_TOTAL_SOURCE_BYTES,
    export_book_bundles,
)


def _positive_byte_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive byte count.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive byte count.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create raw, AI, and human book bundles from a complete, "
            "manifest-verified catalog snapshot."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument(
        "--checkpoint",
        default="source_checkpoint.json",
        help="Complete schema v5 source checkpoint for --catalog.",
    )
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default="source_editions_manifest.json",
    )
    parser.add_argument("--ai-index", default="catalog.json")
    parser.add_argument("--human-index", default="SOURCE_MAP.json")
    parser.add_argument(
        "--max-source-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_TOTAL_SOURCE_BYTES,
    )
    parser.add_argument(
        "--max-output-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    )
    args = parser.parse_args(argv)

    try:
        report = export_book_bundles(
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            human_root=args.human_root,
            ai_root=args.ai_root,
            checkpoint_relative_path=args.checkpoint,
            manifest_relative_path=args.manifest,
            edition_manifest_relative_path=args.edition_manifest,
            ai_index_relative_path=args.ai_index,
            human_index_relative_path=args.human_index,
            max_total_source_bytes=args.max_source_bytes,
            max_total_output_bytes=args.max_output_bytes,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: book bundle export refused ({type(exc).__name__}).", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
