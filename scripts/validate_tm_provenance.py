"""Read-only checks for translation-memory source provenance."""

import argparse
import hashlib
import json
import os
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
from utils import (
    open_regular_file,
    read_relative_text,
    resolve_relative_path,
    split_paragraphs,
    validate_tm_source_provenance,
)


def _finding(status: str, chapter: str, detail: str) -> dict[str, str]:
    return {"status": status, "chapter": chapter, "detail": detail}


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


def _audit_chapter(
    chapter: str,
    pairs: list,
    provenance: dict,
    raw_dir: str,
    translation_dir: str,
    source_manifest: dict | None = None,
    latest_normalized_by_artifact_id: dict | None = None,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    findings = []
    try:
        validate_tm_source_provenance(provenance, len(pairs))
    except (TypeError, ValueError) as exc:
        return [_finding("invalid", chapter, str(exc))]

    try:
        if source_input_root is None:
            raw_text = read_relative_text(raw_dir, provenance["raw_file"])
        else:
            source_input = (source_input_map or {}).get(provenance["raw_file"])
            if (
                not isinstance(source_input, dict)
                or source_input.get("source_version_id")
                != provenance.get("source_version_id")
                or not isinstance(source_input.get("source_input_file"), str)
                or source_input.get("source_sha256")
                != provenance.get("raw_sha256")
            ):
                return [
                    _finding(
                        "mismatch",
                        chapter,
                        "TM source does not match the current AI edition map.",
                    )
                ]
            from source_editions import read_verified_ai_edition_bytes

            raw_text = read_verified_ai_edition_bytes(
                source_input_root,
                source_input["source_input_file"],
                source_input["source_sha256"],
            ).decode("utf-8")
        translation_text = read_relative_text(
            translation_dir, provenance["translation_file"]
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return [
            _finding(
                "unverified",
                chapter,
                f"Could not safely read source files ({type(exc).__name__}).",
            )
        ]

    if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != provenance["raw_sha256"]:
        findings.append(_finding("stale", chapter, "Raw source hash differs."))
    if (
        hashlib.sha256(translation_text.encode("utf-8")).hexdigest()
        != provenance["translation_sha256"]
    ):
        findings.append(
            _finding("stale", chapter, "Translation source hash differs.")
        )
    if "source_version_id" in provenance:
        if source_manifest is None:
            findings.append(
                _finding(
                    "unverified",
                    chapter,
                    "Source version is recorded but SOURCE_MANIFEST_PATH is not configured.",
                )
            )
        else:
            try:
                source_artifact = (
                    verify_current_normalized_source_metadata(
                        source_manifest, provenance["source_version_id"]
                    )
                    if source_input_root is not None
                    else verify_manifest_artifact(
                        raw_dir,
                        source_manifest,
                        provenance["source_version_id"],
                    )
                )
            except StaleSourceVersionError:
                findings.append(
                    _finding(
                        "stale",
                        chapter,
                        "Recorded normalized source version is no longer current.",
                    )
                )
            except ValueError:
                findings.append(
                    _finding(
                        "invalid",
                        chapter,
                        "Recorded source version is missing or its file hash does not verify.",
                    )
                )
            else:
                if (
                    source_artifact["kind"] != "normalized_source"
                    or source_artifact["relative_path"] != provenance["raw_file"]
                    or (
                        source_input_root is not None
                        and source_artifact["content_sha256"]
                        != source_input["source_sha256"]
                    )
                ):
                    findings.append(
                        _finding(
                            "mismatch",
                            chapter,
                            "Recorded source version does not match the raw file provenance.",
                        )
                    )
                else:
                    latest_source = (latest_normalized_by_artifact_id or {}).get(
                        source_artifact["artifact_id"]
                    )
                    if latest_source is None:
                        findings.append(
                            _finding(
                                "invalid",
                                chapter,
                                "Manifest has no current normalized source version.",
                            )
                        )
                    else:
                        try:
                            latest_raw = latest_raw_parent_for_normalized(
                                source_manifest, latest_source
                            )
                            if source_input_root is None:
                                verify_manifest_artifact(
                                    raw_dir,
                                    source_manifest,
                                    latest_source["version_id"],
                                )
                                verify_manifest_artifact(
                                    raw_dir,
                                    source_manifest,
                                    latest_raw["version_id"],
                                )
                        except ValueError:
                            findings.append(
                                _finding(
                                    "invalid",
                                    chapter,
                                    "Latest normalized source raw parent does not verify.",
                                )
                            )
                        else:
                            if (
                                latest_raw["version_id"]
                                not in latest_source["parent_version_ids"]
                            ):
                                findings.append(
                                    _finding(
                                        "stale",
                                        chapter,
                                        "Latest normalized source was derived from an older raw source version.",
                                    )
                                )
                            elif latest_source["version_id"] != source_artifact["version_id"]:
                                findings.append(
                                    _finding(
                                        "stale",
                                        chapter,
                                        "A newer normalized source version exists than the one recorded.",
                                    )
                                )
    elif source_manifest is not None:
        findings.append(
            _finding(
                "unverified",
                chapter,
                "No source_version_id is recorded for manifest-bound TM provenance.",
            )
        )

    source_paragraphs = {
        "raw": split_paragraphs(raw_text),
        "translated": split_paragraphs(translation_text),
    }
    previous_index = {"raw": 0, "translated": 0}
    mappings = provenance["pair_mappings"]

    for pair, mapping in zip(pairs, mappings):
        pair_index = mapping["pair_index"]
        if not isinstance(pair, dict) or not isinstance(pair.get("raw"), str) or not isinstance(
            pair.get("translated"), str
        ):
            findings.append(
                _finding(
                    "invalid",
                    chapter,
                    f"TM pair {pair_index} has invalid raw/translated text.",
                )
            )
            continue

        for side, field in (
            ("raw", "raw_paragraph_indices"),
            ("translated", "translation_paragraph_indices"),
        ):
            indices = mapping[field]
            paragraphs = source_paragraphs[side]
            if not indices:
                continue
            if indices[-1] > len(paragraphs):
                findings.append(
                    _finding(
                        "mismatch",
                        chapter,
                        f"TM pair {pair_index} references a missing {side} paragraph.",
                    )
                )
                continue
            if indices[0] <= previous_index[side]:
                findings.append(
                    _finding(
                        "invalid",
                        chapter,
                        f"TM pair {pair_index} reuses or reorders {side} paragraph indices.",
                    )
                )
                continue
            previous_index[side] = indices[-1]
            referenced_text = "\n\n".join(paragraphs[index - 1] for index in indices)
            if pair[side] != referenced_text:
                findings.append(
                    _finding(
                        "mismatch",
                        chapter,
                        f"TM pair {pair_index} {side} text differs from referenced paragraphs.",
                    )
                )

        if mapping["trace_status"] != "matched":
            findings.append(
                _finding(
                    "unverified",
                    chapter,
                    f"TM pair {pair_index} has {mapping['trace_status']} provenance.",
                )
            )

    if not findings:
        findings.append(
            _finding("verified", chapter, f"Verified {len(pairs)} TM pairs.")
        )
    return findings


def audit_translation_memory(
    tm_data: dict,
    raw_dir: str,
    translation_dir: str,
    source_manifest_path: str | None = None,
    *,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    """Compare indexed TM pairs with their local source files without writing."""
    if not isinstance(tm_data, dict) or not isinstance(tm_data.get("chapters"), dict):
        raise ValueError("Translation memory must contain a chapters object.")

    chapters = tm_data["chapters"]
    provenance_by_chapter = tm_data.get("source_provenance", {})
    if not isinstance(provenance_by_chapter, dict):
        raise ValueError("TM source_provenance must be an object.")

    if not chapters and not provenance_by_chapter:
        return [
            _finding("unverified", "-", "Translation memory contains no chapters.")
        ]

    source_manifest = None
    if source_manifest_path is not None:
        source_manifest_file = resolve_relative_path(
            raw_dir, source_manifest_path
        )
        source_manifest = load_manifest(source_manifest_file)
    latest_normalized_by_artifact_id = (
        latest_artifacts_by_kind(source_manifest, "normalized_source")
        if source_manifest is not None
        else {}
    )

    findings = []
    for chapter in provenance_by_chapter.keys() - chapters.keys():
        findings.append(
            _finding("invalid", chapter, "Provenance references a missing TM chapter.")
        )

    for chapter, pairs in chapters.items():
        if not isinstance(pairs, list):
            findings.append(
                _finding("invalid", chapter, "TM chapter entries must be an array.")
            )
            continue
        if chapter not in provenance_by_chapter:
            findings.append(
                _finding("unindexed", chapter, "No source provenance is recorded.")
            )
            continue
        provenance = provenance_by_chapter[chapter]
        findings.extend(
            _audit_chapter(
                chapter,
                pairs,
                provenance,
                raw_dir,
                translation_dir,
                source_manifest,
                latest_normalized_by_artifact_id,
                source_input_root,
                source_input_map,
            )
        )
    return findings


def _load_tm(path: str) -> dict:
    tm_path = Path(path)
    if tm_path.is_symlink():
        raise ValueError("Symbolic links are not allowed for translation memory.")
    with open_regular_file(tm_path) as stream:
        return json.load(stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only validation of translation-memory source provenance."
    )
    parser.add_argument("--project", "-p", type=str)
    parser.add_argument("--config", "-c", type=str)
    args, _ = parser.parse_known_args(argv)

    try:
        from pipeline import Config

        if (
            "TEST_WORKSPACE_DIR" in os.environ
            and not os.environ["TEST_WORKSPACE_DIR"].strip()
        ):
            raise ValueError("TEST_WORKSPACE_DIR must be a non-empty path.")
        Config.load_config(project=args.project, config_file=args.config)
        tm_data = _load_tm(Config.TM_PATH)
        source_input_map = {
            item["raw_file"]: {
                "source_version_id": item.get("source_version_id"),
                "source_input_file": item.get("source_input_file"),
                "source_sha256": item.get("source_sha256"),
            }
            for item in (Config.CHAPTER_MAP or [])
            if isinstance(item, dict)
            and isinstance(item.get("raw_file"), str)
            and isinstance(item.get("source_input_file"), str)
        }
        findings = audit_translation_memory(
            tm_data,
            Config.RAW_DIR,
            Config.OUTPUT_DIR,
            Config.SOURCE_MANIFEST_PATH,
            source_input_root=Config.AI_EDITION_ROOT if source_input_map else None,
            source_input_map=source_input_map,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {_escape_nonprintable(str(exc))}", file=sys.stderr)
        return 1

    for item in findings:
        print(
            f"{_escape_nonprintable(item['status'].upper())} "
            f"{_escape_nonprintable(item['chapter'])}: "
            f"{_escape_nonprintable(item['detail'])}"
        )

    counts = {
        status: sum(item["status"] == status for item in findings)
        for status in ("verified", "stale", "mismatch", "invalid", "unverified", "unindexed")
    }
    print(
        "Summary: "
        + ", ".join(f"{status}={count}" for status, count in counts.items())
    )

    if counts["stale"] or counts["mismatch"] or counts["invalid"]:
        return 1
    if counts["unverified"] or counts["unindexed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
