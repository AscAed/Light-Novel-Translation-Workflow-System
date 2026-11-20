"""Run the configured AI final reviewer for one translation candidate."""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_translation_review import review_translation_candidate  # noqa: E402
from pipeline import Config, validate_final_review_provider_configuration  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Review one hash-bound translation candidate. A passing AI review "
            "publishes through the existing create-only publication gate."
        )
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--config")
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--review-policy-file", required=True)
    parser.add_argument(
        "--candidate-file",
        help=(
            "Required for rework candidates under "
            "ReviewCandidates/<episode_id>/; omit for the initial run draft."
        ),
    )
    parser.add_argument(
        "--max-review-text-chars",
        type=int,
        default=64_000,
        help=(
            "Maximum combined source and candidate characters sent per review "
            "assessment; input is never truncated."
        ),
    )
    parser.add_argument(
        "--max-rework-attempts",
        type=int,
        help=(
            "Initial review-chain retry budget; defaults to 2 and must match "
            "the existing chain when continuing it."
        ),
    )
    args = parser.parse_args(argv)

    try:
        Config.load_config(project=args.project, config_file=args.config)
        validate_final_review_provider_configuration()
        report = asyncio.run(
            review_translation_candidate(
                args.run_directory,
                args.episode_id,
                review_policy_file=args.review_policy_file,
                candidate_file=args.candidate_file,
                max_review_text_chars=args.max_review_text_chars,
                max_rework_attempts=args.max_rework_attempts,
            )
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, KeyError) as exc:
        print(
            f"ERROR: AI translation review refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
