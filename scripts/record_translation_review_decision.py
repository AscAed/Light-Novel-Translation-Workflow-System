"""Append a hash-bound, content-free final-review decision for one run."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import record_translation_review_decision  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record one explicit fidelity/fluency/style decision without "
            "copying translation text."
        )
    )
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at-utc", required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--max-rework-attempts", required=True, type=int)
    parser.add_argument("--reviewed-candidate-sha256", required=True)
    parser.add_argument(
        "--stage-verdicts",
        required=True,
        help='JSON object, for example {"fidelity":["pass"],"fluency":["pass"],"style":["pass"]}.',
    )
    parser.add_argument(
        "--candidate-file",
        help=(
            "Candidate file inside the run; omit for the initial Drafts "
            "candidate. Rework candidates belong under "
            "ReviewCandidates/<episode_id>/."
        ),
    )
    args = parser.parse_args(argv)

    try:
        stage_verdicts = json.loads(args.stage_verdicts)
        if not isinstance(stage_verdicts, dict):
            raise ValueError("stage verdicts must be a JSON object")
        report = record_translation_review_decision(
            args.run_directory,
            args.episode_id,
            stage_verdicts=stage_verdicts,
            reviewer_id=args.reviewer,
            reviewed_at_utc=args.reviewed_at_utc,
            policy_sha256=args.policy_sha256,
            max_rework_attempts=args.max_rework_attempts,
            candidate_file=args.candidate_file,
            reviewed_candidate_sha256=args.reviewed_candidate_sha256,
        )
    except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
        print(
            f"ERROR: review decision refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
