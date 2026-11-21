"""Run bounded AI translation review, rework, and publication for one episode."""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_translation_workflow import run_ai_translation_workflow  # noqa: E402
from pipeline import (  # noqa: E402
    Config,
    validate_final_review_provider_configuration,
    validate_translation_rework_provider_configuration,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run or resume one hash-bound AI review/rework chain. Only a passing "
            "candidate is published through the existing create-only gate."
        )
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--config")
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--review-policy-file", required=True)
    parser.add_argument(
        "--max-review-text-chars",
        type=int,
        default=64_000,
        help="Maximum combined source and candidate characters per review.",
    )
    parser.add_argument(
        "--max-rework-text-chars",
        type=int,
        default=64_000,
        help="Maximum combined source and candidate characters per rework request.",
    )
    parser.add_argument(
        "--max-rework-attempts",
        type=int,
        help=(
            "Initial review-chain rework budget; defaults to 2. When resuming "
            "a chain, it must match the recorded or human-extended budget."
        ),
    )
    args = parser.parse_args(argv)

    try:
        Config.load_config(project=args.project, config_file=args.config)
        validate_final_review_provider_configuration()
        validate_translation_rework_provider_configuration()
        report = asyncio.run(
            run_ai_translation_workflow(
                args.run_directory,
                args.episode_id,
                review_policy_file=args.review_policy_file,
                max_review_text_chars=args.max_review_text_chars,
                max_rework_text_chars=args.max_rework_text_chars,
                max_rework_attempts=args.max_rework_attempts,
            )
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, KeyError) as exc:
        print(
            f"ERROR: AI translation workflow refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
