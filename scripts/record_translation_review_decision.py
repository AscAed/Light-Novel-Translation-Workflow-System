"""Append a hash-bound, content-free final-review decision for one run."""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_review import record_translation_review_decision  # noqa: E402


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Review JSON contains a duplicate field.")
        result[key] = value
    return result


def _reject_non_finite_json_constant(_value):
    raise ValueError("Review JSON contains a non-finite numeric value.")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Review JSON contains a non-finite numeric value.")
    return parsed


def _parse_json_object(value: str, label: str) -> dict:
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return parsed


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
    parser.add_argument(
        "--policy-sha256",
        help=(
            "Opaque policy digest for a legacy-compatible decision. When "
            "--review-policy-file is supplied, its digest is computed and "
            "checked against this value if also provided."
        ),
    )
    parser.add_argument(
        "--review-policy-file",
        help=(
            "Optional schema v1 issue registry. It is copied into the run by "
            "content hash and each issue code is checked against its stages."
        ),
    )
    parser.add_argument(
        "--max-rework-attempts",
        type=int,
        help=(
            "Maximum rework attempts (default: 2 for a new chain; after an "
            "explicit budget extension, defaults to the extended value)."
        ),
    )
    parser.add_argument("--reviewed-candidate-sha256", required=True)
    parser.add_argument(
        "--stage-verdicts",
        required=True,
        help='JSON object, for example {"fidelity":["pass"],"fluency":["pass"],"style":["pass"]}.',
    )
    parser.add_argument(
        "--stage-issue-codes",
        help=(
            "JSON object mapping each stage to policy-defined, content-free "
            "issue codes; every failed stage must have at least one code."
        ),
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
        stage_verdicts = _parse_json_object(
            args.stage_verdicts,
            "Stage verdicts",
        )
        issue_codes_by_stage = (
            None
            if args.stage_issue_codes is None
            else _parse_json_object(
                args.stage_issue_codes,
                "Stage issue codes",
            )
        )
        report = record_translation_review_decision(
            args.run_directory,
            args.episode_id,
            stage_verdicts=stage_verdicts,
            issue_codes_by_stage=issue_codes_by_stage,
            reviewer_id=args.reviewer,
            reviewed_at_utc=args.reviewed_at_utc,
            policy_sha256=args.policy_sha256,
            review_policy_file=args.review_policy_file,
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
