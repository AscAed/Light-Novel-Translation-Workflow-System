"""Read-only checks for translation-memory source provenance."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import (
    read_relative_text,
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
) -> list[dict[str, str]]:
    findings = []
    try:
        validate_tm_source_provenance(provenance, len(pairs))
    except (TypeError, ValueError) as exc:
        return [_finding("invalid", chapter, str(exc))]

    try:
        raw_text = read_relative_text(raw_dir, provenance["raw_file"])
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
    tm_data: dict, raw_dir: str, translation_dir: str
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

    findings = []
    for chapter in provenance_by_chapter.keys() - chapters.keys():
        findings.append(
            _finding("invalid", chapter, "Provenance references a missing TM chapter.")
        )

    for chapter, pairs in chapters.items():
        if chapter not in provenance_by_chapter:
            findings.append(
                _finding("unindexed", chapter, "No source provenance is recorded.")
            )
            continue
        provenance = provenance_by_chapter[chapter]
        if not isinstance(pairs, list):
            findings.append(
                _finding("invalid", chapter, "TM chapter entries must be an array.")
            )
            continue
        findings.extend(
            _audit_chapter(chapter, pairs, provenance, raw_dir, translation_dir)
        )
    return findings


def _load_tm(path: str) -> dict:
    tm_path = Path(path)
    if tm_path.is_symlink():
        raise ValueError("Symbolic links are not allowed for translation memory.")
    with tm_path.open("r", encoding="utf-8") as stream:
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
        findings = audit_translation_memory(
            tm_data, Config.RAW_DIR, Config.OUTPUT_DIR
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
