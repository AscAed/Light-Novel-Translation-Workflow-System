"""Record an operator's explicit approval of a reviewed translation plan."""

import argparse
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_plan_approval import (  # noqa: E402
    create_approval_receipt,
    load_translation_plan,
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
    args = parser.parse_args(argv)

    try:
        plan = load_translation_plan(args.plan)
        if plan.get("status") != "ready_for_review":
            raise ValueError("Only a ready_for_review plan can be approved.")
        receipt = create_approval_receipt(plan, args.reviewer)
    except (OSError, UnicodeError, ValueError) as exc:
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
            f"{episode['title']}\t{episode['source_version_id']}\t"
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
