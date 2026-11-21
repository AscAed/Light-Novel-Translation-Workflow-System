"""Read-only validation for AI and human-readable source editions."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_editions import (  # noqa: E402
    DEFAULT_EDITION_MANIFEST,
    DEFAULT_MAX_TOTAL_BYTES,
    validate_source_editions,
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
            "Read-only verification of current raw source and both cleaned "
            "source editions."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default=DEFAULT_EDITION_MANIFEST,
    )
    parser.add_argument("--human-index", default="SOURCE_MAP.json")
    parser.add_argument("--ai-index", default="catalog.json")
    parser.add_argument(
        "--max-total-source-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_TOTAL_BYTES,
        help="Maximum sum of raw source bytes to read and verify.",
    )
    args = parser.parse_args(argv)

    try:
        report = validate_source_editions(
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            human_root=args.human_root,
            ai_root=args.ai_root,
            source_manifest_relative_path=args.manifest,
            edition_manifest_relative_path=args.edition_manifest,
            human_index_relative_path=args.human_index,
            ai_index_relative_path=args.ai_index,
            max_total_source_bytes=args.max_total_source_bytes,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
