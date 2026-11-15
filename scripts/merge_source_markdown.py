"""Merge explicitly selected normalized episodes into one Markdown export."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_ingestion import (  # noqa: E402
    materialize_complete_checkpoint_catalog_markdown,
    materialize_episode_collection_markdown,
)


def _positive_byte_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive byte count.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive byte count.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge explicitly ordered, manifest-verified Markdown episodes. "
            "Use --complete-checkpoint to require every episode recorded by a "
            "complete source checkpoint; that does not prove platform enumeration "
            "was exhaustive."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--work-id", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--episode-id",
        action="append",
        help="Episode ID in source order; repeat once per episode.",
    )
    selection.add_argument(
        "--complete-checkpoint",
        nargs="?",
        const="source_checkpoint.json",
        metavar="PATH",
        help=(
            "Export every episode in a complete checkpoint, optionally naming "
            "the checkpoint path."
        ),
    )
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--max-bytes",
        type=_positive_byte_limit,
        required=True,
        help="Required maximum output size, including separators.",
    )
    args = parser.parse_args(argv)

    try:
        if args.complete_checkpoint is not None:
            result = materialize_complete_checkpoint_catalog_markdown(
                args.root,
                work_id=args.work_id,
                max_bytes=args.max_bytes,
                manifest_relative_path=args.manifest,
                checkpoint_relative_path=args.complete_checkpoint,
            )
            artifact = result["artifact"]
            episode_ids = result["episode_ids"]
            coverage_scope = "complete_checkpoint_catalog"
            source_fingerprint = result["source_fingerprint"]
        else:
            episode_ids = args.episode_id
            artifact = materialize_episode_collection_markdown(
                args.root,
                work_id=args.work_id,
                episode_ids=episode_ids,
                max_bytes=args.max_bytes,
                manifest_relative_path=args.manifest,
            )
            coverage_scope = "explicit_episode_selection"
            source_fingerprint = None
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    report = {
        "status": "materialized",
        "coverage_scope": coverage_scope,
        "artifact_id": artifact["artifact_id"],
        "version_id": artifact["version_id"],
        "content_sha256": artifact["content_sha256"],
        "relative_path": artifact["relative_path"],
        "episode_count": len(episode_ids),
    }
    if source_fingerprint is not None:
        report["source_fingerprint"] = source_fingerprint
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
