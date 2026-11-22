"""Create a structural review from verified source-edition evidence."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_editions import validate_source_editions  # noqa: E402
from translation_plan_approval import (  # noqa: E402
    create_plan_review_template,
    load_translation_plan,
    verify_plan_review_template,
    write_new_json,
)


_REVIEW_NOTE = (
    "Codex AI structural review: current catalog mapping, source lineage, "
    "and AI/human edition bytes and profiles passed full-catalog validation. "
    "This does not establish semantic fidelity or third-party reader rendering."
)


def create_verified_review(
    plan: dict,
    human_index_path: str | Path,
) -> dict:
    """Pass only structural review fields backed by the current byte validator."""
    source_edition = plan.get("source_edition")
    if not isinstance(source_edition, dict):
        raise ValueError("A verified AI source edition is required.")

    human_index = Path(human_index_path)
    report = validate_source_editions(
        source_root=plan["source_root"],
        catalog_relative_path=plan["catalog"],
        human_root=str(human_index.parent),
        ai_root=source_edition["index_root"],
        source_manifest_relative_path=plan["manifest"],
        edition_manifest_relative_path=source_edition["manifest"],
        human_index_relative_path=human_index.name,
        ai_index_relative_path=source_edition["index_relative_path"],
    )
    review = create_plan_review_template(plan, human_index)
    episode_count = report.get("episode_count")

    if (
        report.get("status") != "verified"
        or isinstance(episode_count, bool)
        or not isinstance(episode_count, int)
        or episode_count != review["episode_count"]
        or report.get("ai_index_sha256") != review["ai_index_sha256"]
        or report.get("ai_index_sha256") != source_edition.get("index_sha256")
        or report.get("human_index_sha256") != review["human_index_sha256"]
    ):
        raise ValueError("Current full-catalog validation does not match the plan.")

    for episode in review["episodes"]:
        episode["mapping_decision"] = "pass"
        episode["ai_edition_decision"] = "pass"
        episode["human_edition_decision"] = "pass"
        episode["notes"] = _REVIEW_NOTE
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a create-only structural review after full-catalog "
            "source-edition validation."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--human-index", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        plan = load_translation_plan(args.plan)
        source_root = Path(plan["source_root"]).resolve(strict=True)
        output_path = Path(args.output).resolve(strict=False)
        try:
            output_path.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ValueError("Review files must be stored outside SourceArchive.")

        review = create_verified_review(plan, args.human_index)
        write_new_json(output_path, review)
        _, review_sha256 = verify_plan_review_template(
            output_path,
            plan,
            args.human_index,
        )
    except (KeyError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            f"ERROR: verified translation plan review refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "verified_structural_review_created",
                "output": str(output_path),
                "plan_sha256": review["plan_sha256"],
                "review_sha256": review_sha256,
                "episode_count": review["episode_count"],
                "decisions_per_category": review["episode_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
