"""Materialize one archived UTF-8 episode as an immutable Markdown artifact."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_ingestion import (  # noqa: E402
    DEFAULT_MAX_EPISODE_BYTES,
    materialize_episode_markdown,
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
            "Create a byte-preserving UTF-8 Markdown artifact for one archived "
            "episode. This command does not clean or transform source text."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--max-bytes",
        type=_positive_byte_limit,
        default=DEFAULT_MAX_EPISODE_BYTES,
        help="Maximum bytes accepted for the archived episode.",
    )
    args = parser.parse_args(argv)

    try:
        artifact = materialize_episode_markdown(
            args.root,
            work_id=args.work_id,
            episode_id=args.episode_id,
            manifest_relative_path=args.manifest,
            max_bytes=args.max_bytes,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "materialized",
                "artifact_id": artifact["artifact_id"],
                "version_id": artifact["version_id"],
                "content_sha256": artifact["content_sha256"],
                "relative_path": artifact["relative_path"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
