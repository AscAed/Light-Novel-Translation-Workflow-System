import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tm_review import create_tm_review_template, publish_reviewed_tm


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a TM review receipt or publish an approved retrieval snapshot."
    )
    parser.add_argument("--tm", required=True, help="Path to translation_memory.json")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--translation-root", required=True)
    parser.add_argument("--manifest", required=True, help="Manifest path relative to source root")
    parser.add_argument("--chapter", action="append", dest="chapters")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create-template", metavar="FILENAME")
    mode.add_argument("--review", metavar="RECEIPT")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        if args.create_template:
            if args.output:
                parser.error("--output is only valid with --review.")
            result = create_tm_review_template(
                args.tm,
                args.create_template,
                args.source_root,
                args.translation_root,
                args.manifest,
                args.chapters,
            )
            label = "Incomplete TM review template created"
        else:
            if args.chapters:
                parser.error("--chapter is only valid with --create-template.")
            if not args.output:
                parser.error("--output is required with --review.")
            result = publish_reviewed_tm(
                args.tm,
                args.review,
                args.output,
                args.source_root,
                args.translation_root,
                args.manifest,
            )
            label = "Reviewed TM snapshot created"
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"TM review operation refused ({type(exc).__name__}).", file=sys.stderr)
        return 1

    approved = (
        f", approved_pairs={result['approved_pair_count']}"
        if "approved_pair_count" in result
        else ""
    )
    print(
        f"{label}: {result['output']} "
        f"(decisions={result['decision_count']}{approved}, "
        f"sha256={result['output_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
