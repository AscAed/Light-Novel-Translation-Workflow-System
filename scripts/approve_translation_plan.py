"""Record an operator's explicit approval of a reviewed translation plan."""

import argparse
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_plan_approval import (  # noqa: E402
    create_approval_receipt,
    load_translation_plan,
    verify_plan_review_template,
    write_new_json,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Review a translation mapping and create a local approval receipt "
            "after exact-digest confirmation."
        )
    )
    parser.add_argument("--plan", required=True, help="JSON plan file to review.")
    parser.add_argument("--receipt", required=True, help="New receipt path.")
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Reviewer label; it is recorded as a caller-provided claim.",
    )
    parser.add_argument(
        "--review",
        help="Completed mapping/edition review template to verify before approval.",
    )
    parser.add_argument(
        "--human-index",
        help="Current human-reading SOURCE_MAP.json used by --review.",
    )
    args = parser.parse_args(argv)

    try:
        plan = load_translation_plan(args.plan)
        if plan.get("status") != "ready_for_review":
            raise ValueError("Only a ready_for_review plan can be approved.")
        source_root = Path(plan["source_root"]).resolve()
        receipt_path = Path(args.receipt).resolve()
        try:
            receipt_path.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                "Approval receipts must be stored outside the plan source root."
            )
        if bool(args.review) != bool(args.human_index):
            raise ValueError("--review and --human-index must be supplied together.")
        if plan.get("source_edition") is not None and not args.review:
            raise ValueError(
                "AI edition plans require --review and --human-index."
            )
        review_sha256 = None
        if args.review:
            _, review_sha256 = verify_plan_review_template(
                args.review,
                plan,
                args.human_index,
            )
        receipt = create_approval_receipt(
            plan,
            args.reviewer,
            review_sha256=review_sha256,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        safe_messages = {
            "--review and --human-index must be supplied together.",
            "AI edition plans require --review and --human-index.",
        }
        if str(exc) in safe_messages:
            print(str(exc), file=sys.stderr)
            return 1
        print(
            f"Translation plan approval refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Work {plan['work_id']}: {plan['episode_count']} episodes; "
        f"plan SHA-256 {receipt['plan_sha256']}"
    )
    for episode in plan["episodes"]:
        print(
            f"{episode['position']}\t{episode['episode_id']}\t"
            f"{episode['title']}\t"
            f"archive={episode['source_file']}\t"
            f"input={episode['source_input_file'] or episode['source_file']}\t"
            f"{episode['source_version_id']}\t"
            f"{episode['translation_file']}\t{episode['tm_key']}"
        )

    try:
        confirmation = input(
            "After reviewing the mappings above, enter the exact SHA-256 "
            "to approve: "
        ).strip()
    except EOFError:
        print("Approval was not recorded.", file=sys.stderr)
        return 2
    if not hmac.compare_digest(confirmation, receipt["plan_sha256"]):
        print("Approval digest did not match; no receipt was written.", file=sys.stderr)
        return 2

    try:
        write_new_json(args.receipt, receipt)
    except (OSError, UnicodeError, ValueError) as exc:
        print(
            f"Translation plan approval refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Approval receipt created: {args.receipt}. "
        "The reviewer label is not authenticated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
