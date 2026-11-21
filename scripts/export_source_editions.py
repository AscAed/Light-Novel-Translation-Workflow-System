"""Build AI-indexed and human-readable source editions from a verified archive."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from source_editions import (  # noqa: E402
    DEFAULT_EDITION_MANIFEST,
    DEFAULT_MAX_TOTAL_BYTES,
    prepare_source_editions,
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
            "Create independently cleaned AI and human editions from current "
            "manifest-verified collected source text."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default=DEFAULT_EDITION_MANIFEST,
        help="Versioned manifest path for the cleaned editions in --source-root.",
    )
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument(
        "--refresh-indexes",
        action="store_true",
        help=(
            "Refresh generated indexes when only edition-manifest provenance "
            "fields differ and all chapter files match."
        ),
    )
    parser.add_argument(
        "--max-total-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_TOTAL_BYTES,
        help="Maximum sum of source episode bytes to clean and export.",
    )
    args = parser.parse_args(argv)

    try:
        report = prepare_source_editions(
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            manifest_relative_path=args.manifest,
            human_root=args.human_root,
            ai_root=args.ai_root,
            max_total_bytes=args.max_total_bytes,
            edition_manifest_relative_path=args.edition_manifest,
            refresh_indexes=args.refresh_indexes,
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
