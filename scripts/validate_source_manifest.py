"""Read-only validation for a source version manifest and its listed files."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_manifest import load_manifest, verify_manifest_files
from utils import resolve_relative_path


def _escape_nonprintable(value: str) -> str:
    visible = []
    for character in value:
        if character.isprintable():
            visible.append(character)
            continue
        codepoint = ord(character)
        if codepoint <= 0xFFFF:
            visible.append(f"\\u{codepoint:04x}")
        else:
            visible.append(f"\\U{codepoint:08x}")
    return "".join(visible)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only validation of a source manifest and listed file hashes."
    )
    parser.add_argument("--root", required=True, help="Explicit project data root.")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Manifest path relative to --root, using forward slashes.",
    )
    args = parser.parse_args(argv)

    try:
        manifest_path = resolve_relative_path(args.root, args.manifest)
        manifest = load_manifest(manifest_path)
        verified_files = verify_manifest_files(args.root, manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {_escape_nonprintable(str(exc))}", file=sys.stderr)
        return 1

    print(
        "OK: "
        f"schema_version={manifest['schema_version']} "
        f"artifacts={len(manifest['artifacts'])} "
        f"files_verified={verified_files}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
