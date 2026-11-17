"""Persist a read-only snapshot of downstream source freshness findings."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.validate_knowledge_provenance import audit_knowledge_provenance
from scripts.validate_tm_provenance import audit_translation_memory
from source_manifest import load_manifest
from story_summary_review import load_reviewed_story_summary
from utils import open_regular_file, resolve_relative_path, write_new_child_text


FRESHNESS_STATUSES = (
    "verified",
    "stale",
    "mismatch",
    "invalid",
    "unverified",
    "unindexed",
)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Input JSON contains a duplicate field.")
        result[key] = value
    return result


def _load_json_regular(path: str, label: str) -> dict:
    input_path = Path(path)
    if input_path.is_symlink():
        raise ValueError(f"Symbolic links are not allowed for {label}.")
    with open_regular_file(input_path) as stream:
        return json.load(stream, object_pairs_hook=_reject_duplicate_keys)


def _sha256_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open_regular_file(path, binary=True) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _consumer_snapshot(findings: list[dict[str, str]], identity_field: str) -> dict:
    items = [
        {
            "identity": finding[identity_field],
            "status": finding["status"],
            "detail": finding["detail"],
        }
        for finding in findings
    ]
    return {
        "summary": {
            status: sum(item["status"] == status for item in items)
            for status in FRESHNESS_STATUSES
        },
        "findings": items,
    }


def _json_sha256(value: dict) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _audit_reviewed_story_summary(
    *,
    path: str,
    source_root: str,
    manifest_relative_path: str,
    expected_sources: list[dict],
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> tuple[dict[str, str], str]:
    summary_path = Path(path)
    if summary_path.is_symlink():
        return (
            {
                "identity": "reviewed_story_summary",
                "status": "invalid",
                "detail": "Reviewed summary path is a symbolic link.",
            },
            "",
        )
    try:
        digest_before = _sha256_regular_file(summary_path)
    except (OSError, ValueError):
        return (
            {
                "identity": "reviewed_story_summary",
                "status": "unverified",
                "detail": "Reviewed summary could not be safely read.",
            },
            "",
        )

    status = "verified"
    detail = "Approved summary matches the current chapter map and sources."
    try:
        load_reviewed_story_summary(
            str(summary_path),
            source_root,
            manifest_relative_path,
            require_full_book_coverage=True,
            expected_sources=expected_sources,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        message = str(exc)
        lowered = message.casefold()
        status = (
            "stale"
            if (
                "stale" in lowered
                or "not current" in lowered
                or "current chapter map" in lowered
            )
            else "invalid"
        )
        detail = message

    try:
        digest_after = _sha256_regular_file(summary_path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Reviewed summary changed or became unavailable during freshness audit."
        ) from exc
    if digest_after != digest_before:
        raise RuntimeError(
            "Reviewed summary changed while freshness findings were being collected."
        )
    return (
        {
            "identity": "reviewed_story_summary",
            "status": status,
            "detail": detail,
        },
        digest_before,
    )


def _current_expected_sources(
    *,
    project: str | None,
    config_file: str | None,
    source_root: str,
    manifest_relative_path: str,
) -> list[dict]:
    from pipeline import Config, get_chapter_specs

    Config.load_config(project=project, config_file=config_file)
    configured_source_root = Path(Config.RAW_DIR).resolve(strict=True)
    if configured_source_root != Path(source_root).resolve(strict=True):
        raise ValueError("Configured RAW_DIR does not match --source-root.")
    if not Config.SOURCE_MANIFEST_PATH:
        raise ValueError("The current chapter map requires a source manifest.")
    configured_manifest = resolve_relative_path(
        Config.RAW_DIR, Config.SOURCE_MANIFEST_PATH
    )
    requested_manifest = resolve_relative_path(source_root, manifest_relative_path)
    if configured_manifest != requested_manifest:
        raise ValueError("Configured source manifest does not match --manifest.")

    chapters = get_chapter_specs(
        Config.RAW_DIR,
        Config.OUTPUT_DIR,
        Config.CHAPTER_MAP,
        Config.SOURCE_MANIFEST_PATH,
        source_input_root=Config.AI_EDITION_ROOT,
    )
    expected_sources = [
        {
            "filename": chapter.raw_file,
            "source_version_id": chapter.source_version_id,
            "source_input_file": chapter.source_input_file,
            "source_sha256": chapter.source_sha256,
        }
        for chapter in chapters
    ]
    if not expected_sources or any(
        not item["source_version_id"] for item in expected_sources
    ):
        raise ValueError(
            "The current chapter map must bind every source version "
            "to audit a full-book summary."
        )
    return expected_sources


def build_downstream_freshness_snapshot(
    *,
    tm_data: dict | None,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
    tm_label: str | None,
    knowledge_provenance: dict | None = None,
    knowledge_label: str | None = None,
    story_summary_path: str | None = None,
    expected_sources: list[dict] | None = None,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> dict:
    """Audit configured consumers and bind results to one manifest byte hash."""
    manifest_path = resolve_relative_path(source_root, manifest_relative_path)
    load_manifest(manifest_path)
    manifest_sha256_before = _sha256_regular_file(manifest_path)

    consumers = {}
    if tm_data is None:
        tm_findings = [
            {
                "chapter": "translation_memory",
                "status": "unverified",
                "detail": "Configured translation memory is unavailable.",
            }
        ]
        tm_sha256 = None
    else:
        tm_findings = audit_translation_memory(
            tm_data,
            source_root,
            translation_root,
            manifest_relative_path,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
        tm_sha256 = _json_sha256(tm_data)
    translation_memory = {
        "input": tm_label,
        **_consumer_snapshot(tm_findings, "chapter"),
    }
    if tm_sha256 is not None:
        translation_memory["sha256"] = tm_sha256
    consumers["translation_memory"] = translation_memory
    if knowledge_provenance is not None:
        knowledge_findings = audit_knowledge_provenance(
            knowledge_provenance,
            source_root,
            manifest_relative_path,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
        consumers["knowledge_provenance"] = {
            "input": knowledge_label,
            **_consumer_snapshot(knowledge_findings, "source"),
            "sha256": _json_sha256(knowledge_provenance),
        }
    if story_summary_path is not None:
        if expected_sources is None:
            raise ValueError(
                "Current versioned chapter sources are required to audit "
                "a reviewed story summary."
            )
        summary_finding, summary_digest = _audit_reviewed_story_summary(
            path=story_summary_path,
            source_root=source_root,
            manifest_relative_path=manifest_relative_path,
            expected_sources=expected_sources,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
        summary_consumer = {
            "input": Path(story_summary_path).name,
            **_consumer_snapshot([summary_finding], "identity"),
        }
        if summary_digest:
            summary_consumer["sha256"] = summary_digest
        consumers["reviewed_story_summary"] = summary_consumer

    manifest_sha256_after = _sha256_regular_file(manifest_path)
    if manifest_sha256_after != manifest_sha256_before:
        raise RuntimeError(
            "Source manifest changed while freshness findings were being collected."
        )

    return {
        "schema_version": 2,
        "snapshot_kind": "downstream_freshness",
        "generated_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "source_manifest": {
            "relative_path": manifest_relative_path,
            "sha256": manifest_sha256_before,
        },
        "consumers": consumers,
    }


def persist_downstream_freshness_snapshot(
    snapshot: dict,
    source_root: str,
) -> dict[str, str | bool]:
    """Persist an immutable, content-addressed snapshot under the source root."""
    stable_snapshot = {
        key: value
        for key, value in snapshot.items()
        if key not in {"generated_at_utc", "snapshot_id"}
    }
    identity_bytes = json.dumps(
        stable_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    snapshot_id = hashlib.sha256(identity_bytes).hexdigest()
    filename = f"downstream_freshness_{snapshot_id}.json"
    persisted = {
        **snapshot,
        "snapshot_id": snapshot_id,
    }
    serialized = json.dumps(
        persisted,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    created = True
    try:
        write_new_child_text(source_root, filename, serialized)
    except FileExistsError:
        existing = _load_json_regular(
            str(Path(source_root) / filename),
            "existing freshness snapshot",
        )
        if not isinstance(existing, dict):
            raise RuntimeError(
                "Existing freshness snapshot does not match its content address."
            )
        existing_stable = {
            key: value
            for key, value in existing.items()
            if key not in {"generated_at_utc", "snapshot_id"}
        }
        if existing_stable != stable_snapshot or existing.get("snapshot_id") != snapshot_id:
            raise RuntimeError(
                "Existing freshness snapshot does not match its content address."
            )
        created = False
    return {
        "snapshot_id": snapshot_id,
        "path": filename,
        "created": created,
    }


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


def _print_summary(snapshot: dict, output_path: Path) -> None:
    print(f"Snapshot created: {_escape_nonprintable(str(output_path))}")
    print(f"Source manifest SHA-256: {snapshot['source_manifest']['sha256']}")
    for consumer, result in snapshot["consumers"].items():
        counts = result["summary"]
        print(
            f"{consumer}: "
            + ", ".join(f"{status}={count}" for status, count in counts.items())
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of downstream freshness, persisted as a "
            "manifest-bound JSON snapshot."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--translation-root", required=True)
    parser.add_argument(
        "--manifest",
        default="source_manifest.json",
        help="Source manifest path relative to --source-root.",
    )
    parser.add_argument("--tm", required=True, help="Translation memory JSON path.")
    parser.add_argument(
        "--knowledge-provenance",
        help="Optional KNOWLEDGE_PROVENANCE JSON path.",
    )
    parser.add_argument(
        "--story-summary",
        help="Optional approved full-book STORY_SUMMARY JSON bundle.",
    )
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--project",
        help="Project name used to load the current versioned chapter map.",
    )
    config_group.add_argument(
        "--config",
        help="JSON configuration used to load the current versioned chapter map.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="New JSON output path. Existing files are never overwritten.",
    )
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    if not output_path.name or output_path.name in {".", ".."}:
        print("ERROR: --output must name a file.", file=sys.stderr)
        return 1

    try:
        tm_data = _load_json_regular(args.tm, "translation memory")
        knowledge_provenance = (
            _load_json_regular(args.knowledge_provenance, "knowledge provenance")
            if args.knowledge_provenance
            else None
        )
        if args.story_summary:
            if not args.project and not args.config:
                raise ValueError(
                    "--story-summary requires --project or --config so its "
                    "source coverage can be checked against the current chapter map."
                )
            expected_sources = _current_expected_sources(
                project=args.project,
                config_file=args.config,
                source_root=args.source_root,
                manifest_relative_path=args.manifest,
            )
            from pipeline import Config

            source_input_root = Config.AI_EDITION_ROOT
            source_input_map = {
                item["filename"]: {
                    "source_version_id": item["source_version_id"],
                    "source_input_file": item["source_input_file"],
                    "source_sha256": item["source_sha256"],
                }
                for item in expected_sources
                if isinstance(item.get("source_input_file"), str)
            }
        else:
            if args.project or args.config:
                raise ValueError(
                    "--project/--config are only accepted with --story-summary."
                )
            expected_sources = None
            source_input_root = None
            source_input_map = None
        snapshot = build_downstream_freshness_snapshot(
            tm_data=tm_data,
            source_root=args.source_root,
            translation_root=args.translation_root,
            manifest_relative_path=args.manifest,
            tm_label=Path(args.tm).name,
            knowledge_provenance=knowledge_provenance,
            knowledge_label=(
                Path(args.knowledge_provenance).name
                if args.knowledge_provenance
                else None
            ),
            story_summary_path=args.story_summary,
            expected_sources=expected_sources,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
        serialized = json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        write_new_child_text(
            str(output_path.parent),
            output_path.name,
            serialized + "\n",
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {_escape_nonprintable(str(exc))}", file=sys.stderr)
        return 1

    _print_summary(snapshot, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
