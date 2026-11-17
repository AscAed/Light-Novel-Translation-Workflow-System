"""Read-only replay validation for archived Kakuyomu episode HTML."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kakuyomu_html_archive import (  # noqa: E402
    DEFAULT_MAX_TOTAL_HTML_BYTES,
    validate_kakuyomu_html_archive,
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
            "Verify archived Kakuyomu HTML, episode lineage, title, and "
            "replayed visible-text hash without network or provider calls."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--max-total-html-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_TOTAL_HTML_BYTES,
    )
    args = parser.parse_args(argv)

    try:
        report = validate_kakuyomu_html_archive(
            source_root=args.source_root,
            manifest_relative_path=args.manifest,
            max_total_html_bytes=args.max_total_html_bytes,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
