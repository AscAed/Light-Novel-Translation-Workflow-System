"""Publish one approved translation draft without overwriting existing work."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import publish_reviewed_translation  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Publish one translation only when its independent review receipt "
            "matches the current source and draft."
        )
    )
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--review", required=True)
    args = parser.parse_args(argv)
    try:
        report = publish_reviewed_translation(
            args.run_directory,
            args.episode_id,
            args.review,
        )
    except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
        print(
            f"ERROR: translation publication refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
