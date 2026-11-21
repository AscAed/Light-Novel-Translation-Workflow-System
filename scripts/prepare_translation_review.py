"""Create local review templates for a completed translation run."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import (  # noqa: E402
    _load_run,
    prepare_translation_review,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create version-bound review templates for translation drafts."
    )
    parser.add_argument("--run-directory", required=True)
    parser.add_argument(
        "--episode-id",
        help="Prepare one episode; omit to prepare every episode in the run.",
    )
    args = parser.parse_args(argv)
    try:
        _, run, _ = _load_run(args.run_directory)
        episode_ids = (
            [args.episode_id]
            if args.episode_id
            else [episode["episode_id"] for episode in run["episodes"]]
        )
        reports = [
            prepare_translation_review(args.run_directory, episode_id)
            for episode_id in episode_ids
        ]
    except (OSError, UnicodeError, ValueError, KeyError, RuntimeError) as exc:
        print(
            f"ERROR: review template creation refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "ready", "reviews": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
