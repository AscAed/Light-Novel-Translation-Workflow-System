"""Create a pending mapping and dual-edition review template."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translation_plan_approval import (  # noqa: E402
    create_plan_review_template,
    load_translation_plan,
    write_new_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a create-only, content-free review template for a "
            "translation plan and human-reading edition index."
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
            raise ValueError(
                "Plan review templates must be stored outside SourceArchive."
            )
        template = create_plan_review_template(plan, args.human_index)
        write_new_json(output_path, template)
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        print(
            f"ERROR: translation plan review refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "review_template_ready",
                "output": str(output_path),
                "plan_sha256": template["plan_sha256"],
                "episode_count": template["episode_count"],
                "human_index_sha256": template["human_index_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
