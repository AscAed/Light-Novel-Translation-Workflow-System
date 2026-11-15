"""Build a scoped EPUB candidate from a version-bound Markdown catalog."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epub_builder import build_epub_candidate  # noqa: E402


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive integer.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Build a non-publishable EPUB candidate from an explicit ordered "
            "chapter catalog."
        )
    )
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--max-chapter-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-total-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-output-bytes", type=_positive_int, required=True)
    parser.add_argument("--timeout-seconds", type=_positive_int, default=120)
    args = parser.parse_args(argv)

    try:
        result = build_epub_candidate(
            input_root=args.input_root,
            catalog_relative_path=args.catalog,
            output_root=args.output_root,
            max_chapter_bytes=args.max_chapter_bytes,
            max_total_bytes=args.max_total_bytes,
            max_output_bytes=args.max_output_bytes,
            pandoc_executable=args.pandoc,
            timeout_seconds=args.timeout_seconds,
        )
    except (FileExistsError, OSError, UnicodeError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
