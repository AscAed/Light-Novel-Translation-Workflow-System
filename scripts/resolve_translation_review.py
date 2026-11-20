"""Record an explicit human resolution for an exhausted review decision."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import resolve_translation_review  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Approve the current candidate for human review or explicitly "
            "increase its rework budget."
        )
    )
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument(
        "--action",
        required=True,
        choices=("approve_current", "increase_budget"),
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at-utc", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--reviewed-decision-sha256", required=True)
    parser.add_argument("--new-max-rework-attempts", type=int)
    args = parser.parse_args(argv)

    try:
        report = resolve_translation_review(
            args.run_directory,
            args.episode_id,
            action=args.action,
            reviewer_id=args.reviewer,
            reviewed_at_utc=args.reviewed_at_utc,
            rationale=args.rationale,
            reviewed_decision_sha256=args.reviewed_decision_sha256,
            new_max_rework_attempts=args.new_max_rework_attempts,
        )
    except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
        print(
            f"ERROR: review resolution refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
