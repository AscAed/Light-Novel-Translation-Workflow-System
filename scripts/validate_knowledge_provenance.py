"""Read-only validation of knowledge-draft source freshness."""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from source_manifest import (
    StaleSourceVersionError,
    latest_artifacts_by_kind,
    latest_raw_parent_for_normalized,
    load_manifest,
    verify_manifest_artifact,
    verify_current_normalized_source_metadata,
)
from utils import open_regular_file, resolve_relative_path


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _finding(status: str, source: str, detail: str) -> dict[str, str]:
    return {"status": status, "source": source, "detail": detail}


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


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Knowledge provenance contains a duplicate JSON field.")
        result[key] = value
    return result


def _sha256_relative_text(root: str, relative_path: str) -> str:
    source_path = resolve_relative_path(root, relative_path)
    digest = hashlib.sha256()
    with open_regular_file(source_path) as source_file:
        for chunk in iter(lambda: source_file.read(64 * 1024), ""):
            digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def _validate_provenance(provenance: dict) -> list[dict]:
    if (
        not isinstance(provenance, dict)
        or isinstance(provenance.get("schema_version"), bool)
        or provenance.get("schema_version") != 1
        or provenance.get("artifact_status") != "complete"
    ):
        raise ValueError(
            "Knowledge provenance must be a complete schema_version 1 artifact."
        )

    source_files = provenance.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ValueError("Knowledge provenance must contain source_files.")

    seen_filenames = set()
    for index, source in enumerate(source_files, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Knowledge source entry {index} must be an object.")
        filename = source.get("filename")
        digest = source.get("source_sha256")
        if (
            not isinstance(filename, str)
            or not filename
            or filename.strip() != filename
            or not isinstance(digest, str)
            or not _SHA256_PATTERN.fullmatch(digest)
        ):
            raise ValueError(f"Knowledge source entry {index} is malformed.")
        filename_key = filename.casefold()
        if filename_key in seen_filenames:
            raise ValueError(f"Knowledge provenance repeats source entry {index}.")
        seen_filenames.add(filename_key)

        if "source_version_id" in source:
            version_id = source["source_version_id"]
            if (
                not isinstance(version_id, str)
                or not version_id
                or version_id.strip() != version_id
                or any(ord(character) < 32 for character in version_id)
            ):
                raise ValueError(
                    f"Knowledge source entry {index} has an invalid source_version_id."
                )
    return source_files


def audit_knowledge_provenance(
    provenance: dict,
    raw_dir: str,
    source_manifest_path: str,
    *,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    """Check each knowledge source against its recorded and latest versions."""
    source_files = _validate_provenance(provenance)
    manifest_path = resolve_relative_path(raw_dir, source_manifest_path)
    manifest = load_manifest(manifest_path)
    latest_normalized = latest_artifacts_by_kind(manifest, "normalized_source")
    findings = []

    for index, source in enumerate(source_files, start=1):
        filename = source["filename"]
        label = f"source[{index}] {filename}"
        source_input = None
        try:
            if source_input_root is None:
                text_digest = _sha256_relative_text(raw_dir, filename)
            else:
                source_input = (source_input_map or {}).get(filename)
                if (
                    not isinstance(source_input, dict)
                    or source_input.get("source_version_id")
                    != source.get("source_version_id")
                    or not isinstance(source_input.get("source_input_file"), str)
                    or (
                        source.get("source_input_file") is not None
                        and source_input.get("source_input_file")
                        != source.get("source_input_file")
                    )
                ):
                    findings.append(
                        _finding(
                            "mismatch",
                            label,
                            "Source entry does not match the current AI edition map.",
                        )
                    )
                    continue
                from source_editions import read_verified_ai_edition_bytes

                source_bytes = read_verified_ai_edition_bytes(
                    source_input_root,
                    source_input["source_input_file"],
                    source_input["source_sha256"],
                )
                source_text = source_bytes.decode("utf-8")
                normalized_text = source_text.replace(
                    "\r\n", "\n"
                ).replace("\r", "\n")
                text_digest = hashlib.sha256(
                    normalized_text.encode("utf-8")
                ).hexdigest()
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append(
                _finding(
                    "unverified",
                    label,
                    f"Could not safely read source text ({type(exc).__name__}).",
                )
            )
            continue

        source_version_id = source.get("source_version_id")
        if source_version_id is None:
            if text_digest != source["source_sha256"]:
                findings.append(
                    _finding(
                        "stale",
                        label,
                        "Source text hash differs from the draft.",
                    )
                )
                continue
            findings.append(
                _finding(
                    "unverified",
                    label,
                    "No source_version_id is recorded.",
                )
            )
            continue

        try:
            recorded = (
                verify_current_normalized_source_metadata(
                    manifest, source_version_id
                )
                if source_input_root is not None
                else verify_manifest_artifact(
                    raw_dir, manifest, source_version_id
                )
            )
        except StaleSourceVersionError:
            findings.append(
                _finding(
                    "stale",
                    label,
                    "Recorded normalized source version is no longer current.",
                )
            )
            continue
        except ValueError:
            findings.append(
                _finding(
                    "invalid",
                    label,
                    "Recorded source version is missing or its byte hash does not verify.",
                )
            )
            continue

        if (
            recorded["kind"] != "normalized_source"
            or recorded["relative_path"] != filename
        ):
            findings.append(
                _finding(
                    "mismatch",
                    label,
                    "Recorded version does not match the normalized source path.",
                )
            )
            continue
        if text_digest != source["source_sha256"]:
            findings.append(
                _finding(
                    "mismatch",
                    label,
                    "Recorded source text hash does not match the verified version.",
                )
            )
            continue

        latest = latest_normalized.get(recorded["artifact_id"])
        if latest is None:
            findings.append(
                _finding(
                    "invalid",
                    label,
                    "Manifest has no current normalized source version.",
                )
            )
            continue
        if latest["version_id"] != recorded["version_id"]:
            findings.append(
                _finding(
                    "stale",
                    label,
                    "A newer normalized source version exists than the one recorded.",
                )
            )
            continue

        try:
            latest_raw = latest_raw_parent_for_normalized(manifest, latest)
            if source_input_root is None:
                verify_manifest_artifact(
                    raw_dir, manifest, latest_raw["version_id"]
                )
        except ValueError:
            findings.append(
                _finding(
                    "invalid",
                    label,
                    "Latest normalized source raw parent does not verify.",
                )
            )
            continue
        if latest_raw["version_id"] not in latest["parent_version_ids"]:
            findings.append(
                _finding(
                    "stale",
                    label,
                    "Latest normalized source was derived from an older raw source version.",
                )
            )
            continue

        findings.append(
            _finding("verified", label, "Source version matches the latest artifact.")
        )
    return findings


def _load_json_regular(path: str) -> dict:
    provenance_path = Path(path)
    if provenance_path.is_symlink():
        raise ValueError("Symbolic links are not allowed for knowledge provenance.")
    with open_regular_file(provenance_path) as stream:
        return json.load(stream, object_pairs_hook=_reject_duplicate_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only validation of knowledge-draft source freshness."
    )
    parser.add_argument("--root", required=True, help="Root containing source files.")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Source manifest path relative to --root.",
    )
    parser.add_argument(
        "--provenance",
        required=True,
        help="Path to KNOWLEDGE_PROVENANCE_draft.json.",
    )
    args = parser.parse_args(argv)

    try:
        provenance = _load_json_regular(args.provenance)
        findings = audit_knowledge_provenance(
            provenance,
            args.root,
            args.manifest,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"ERROR: {_escape_nonprintable(str(exc))}",
            file=sys.stderr,
        )
        return 1

    for item in findings:
        print(
            f"{_escape_nonprintable(item['status'].upper())} "
            f"{_escape_nonprintable(item['source'])}: "
            f"{_escape_nonprintable(item['detail'])}"
        )

    counts = {
        status: sum(item["status"] == status for item in findings)
        for status in ("verified", "stale", "mismatch", "invalid", "unverified")
    }
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if counts["stale"] or counts["mismatch"] or counts["invalid"]:
        return 1
    if counts["unverified"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
