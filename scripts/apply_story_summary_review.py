"""Create a summary review template or publish an approved summary bundle."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from story_summary_review import (
    create_summary_review_template,
    publish_reviewed_summary,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a pending summary review receipt or publish an approved summary."
    )
    parser.add_argument("--knowledge-root", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--manifest")
    parser.add_argument("--source-input-root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create-template", metavar="FILENAME")
    mode.add_argument("--review", metavar="RECEIPT")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        if args.create_template:
            if (
                args.source_root
                or args.manifest
                or args.source_input_root
                or args.output
            ):
                parser.error(
                    "--source-root, --manifest, --source-input-root, and "
                    "--output are only valid with --review."
                )
            result = create_summary_review_template(
                args.knowledge_root,
                args.create_template,
            )
            label = "Pending summary review template created"
        else:
            if not args.source_root or not args.manifest or not args.output:
                parser.error(
                    "--source-root, --manifest, and --output are required with --review."
                )
            result = publish_reviewed_summary(
                args.knowledge_root,
                args.source_root,
                args.manifest,
                args.review,
                args.output,
                source_input_root=args.source_input_root,
            )
            label = "Approved summary bundle created"
    except (OSError, UnicodeError, ValueError) as exc:
        print(
            f"Summary review operation refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"{label}: {result['output']} "
        f"(source_count={result['source_count']}, "
        f"sha256={result['output_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
