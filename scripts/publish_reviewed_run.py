"""Publish all available approved translation reviews for one run."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import publish_reviewed_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Publish every available approved translation review for a run; "
            "missing or failed episodes remain resumable."
        )
    )
    parser.add_argument("--run-directory", required=True)
    parser.add_argument(
        "--review-directory",
        default="Reviews",
        help="Review directory relative to the run (default: Reviews).",
    )
    args = parser.parse_args(argv)
    try:
        report = publish_reviewed_run(
            args.run_directory,
            review_directory=args.review_directory,
        )
    except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
        print(
            f"ERROR: translation run publication refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "published" else 2


if __name__ == "__main__":
    raise SystemExit(main())
