"""Recoverable per-chapter publication for translation output and TM."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from utils import (
    open_regular_file,
    read_relative_text,
    require_aligned_paragraphs,
    resolve_child_path,
    resolve_relative_path,
    split_paragraphs,
    write_new_child_text,
    write_new_relative_text,
    write_text_atomically,
)

_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Chapter transaction contains a duplicate JSON field.")
        result[key] = value
    return result


def _journal_name(translation_file: str, tm_key: str) -> str:
    identity = json.dumps(
        [translation_file, tm_key],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f".codex-chapter-transaction-{_sha256(identity)}.json"


def _journal_location(output_root: str, translation_file: str, tm_key: str):
    output_path = resolve_relative_path(
        output_root, translation_file, allow_missing=True
    )
    filename = _journal_name(translation_file, tm_key)
    journal_path = resolve_child_path(
        str(output_path.parent), filename, allow_missing=True
    )
    return output_path, str(output_path.parent), filename, journal_path


def has_pending_chapter_transaction(
    output_root: str, translation_file: str, tm_key: str
) -> bool:
    _, _, _, journal_path = _journal_location(
        output_root, translation_file, tm_key
    )
    return journal_path.exists()


def _read_journal(root: str, filename: str) -> dict:
    path = resolve_child_path(root, filename)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_JOURNAL_BYTES + 1)
    if len(content) > _MAX_JOURNAL_BYTES:
        raise ValueError("Chapter transaction journal exceeds the size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Chapter transaction journal is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Chapter transaction journal must be an object.")
    return value


def _write_new_journal(root: str, filename: str, content: str) -> None:
    target = resolve_child_path(root, filename, allow_missing=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{filename}.",
        suffix=".tmp",
        dir=root,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, target)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _build_tm_update(raw_text: str, translation_text: str, spec) -> tuple[list, dict]:
    raw_paragraphs = split_paragraphs(raw_text)
    translated_paragraphs = split_paragraphs(translation_text)
    require_aligned_paragraphs(
        raw_paragraphs, translated_paragraphs, "Recovered translation"
    )
    if "\n\n".join(translated_paragraphs) != translation_text:
        raise ValueError("Chapter transaction translation is not normalized.")

    pairs = [
        {"raw": raw, "translated": translated}
        for raw, translated in zip(raw_paragraphs, translated_paragraphs)
    ]
    provenance = {
        "schema_version": 1,
        "producer": "pipeline",
        "raw_file": spec.raw_file,
        "raw_sha256": _sha256(raw_text.encode("utf-8")),
        "translation_file": spec.translation_file,
        "translation_sha256": _sha256(translation_text.encode("utf-8")),
        "pair_mappings": [
            {
                "pair_index": index,
                "raw_paragraph_indices": [index],
                "translation_paragraph_indices": [index],
                "trace_status": "matched",
            }
            for index in range(1, len(pairs) + 1)
        ],
    }
    if spec.source_version_id is not None:
        provenance["source_version_id"] = spec.source_version_id
    return pairs, provenance


def _validate_journal(record: dict, raw_text: str, spec) -> str:
    expected_fields = {
        "schema_version",
        "raw_file",
        "translation_file",
        "tm_key",
        "source_version_id",
        "raw_sha256",
        "translation_sha256",
        "tm_base_sha256",
        "translation_text",
    }
    if (
        set(record) != expected_fields
        or isinstance(record.get("schema_version"), bool)
        or record.get("schema_version") != 1
        or record.get("raw_file") != spec.raw_file
        or record.get("translation_file") != spec.translation_file
        or record.get("tm_key") != spec.tm_key
        or record.get("source_version_id") != spec.source_version_id
    ):
        raise ValueError("Chapter transaction does not match the current chapter map.")

    raw_digest = record.get("raw_sha256")
    translation_digest = record.get("translation_sha256")
    tm_base_digest = record.get("tm_base_sha256")
    translation_text = record.get("translation_text")
    if (
        not isinstance(raw_digest, str)
        or not _SHA256_PATTERN.fullmatch(raw_digest)
        or raw_digest != _sha256(raw_text.encode("utf-8"))
        or not isinstance(translation_digest, str)
        or not _SHA256_PATTERN.fullmatch(translation_digest)
        or not isinstance(translation_text, str)
        or translation_digest != _sha256(translation_text.encode("utf-8"))
        or (
            tm_base_digest is not None
            and (
                not isinstance(tm_base_digest, str)
                or not _SHA256_PATTERN.fullmatch(tm_base_digest)
            )
        )
    ):
        raise ValueError("Chapter transaction hashes do not match current inputs.")
    _build_tm_update(raw_text, translation_text, spec)
    return translation_text


def _ensure_output(output_path: Path, output_root: str, spec, text: str) -> None:
    expected_bytes = text.replace("\n", os.linesep).encode("utf-8")
    if not output_path.exists():
        if "/" in spec.translation_file:
            write_new_relative_text(
                output_root, spec.translation_file, text
            )
        else:
            write_new_child_text(output_root, spec.translation_file, text)
        return

    with open_regular_file(output_path, binary=True) as stream:
        current_bytes = stream.read()
    if current_bytes == expected_bytes:
        return
    if (
        current_bytes
        and len(current_bytes) < len(expected_bytes)
        and expected_bytes.startswith(current_bytes)
    ):
        write_text_atomically(str(output_path), text)
        return
    raise ValueError(
        "Chapter transaction found an output that differs from its recorded result."
    )


def _tm_chapter_matches(rag, tm_key: str, pairs: list, provenance: dict) -> bool:
    tm_data = getattr(rag, "tm_data", None)
    if not isinstance(tm_data, dict):
        return False
    chapters = tm_data.get("chapters")
    source_provenance = tm_data.get("source_provenance")
    if not isinstance(chapters, dict) or not isinstance(source_provenance, dict):
        return False
    saved_pairs = chapters.get(tm_key)
    if not isinstance(saved_pairs, list) or len(saved_pairs) != len(pairs):
        return False
    if source_provenance.get(tm_key) != provenance:
        return False
    return all(
        isinstance(saved, dict)
        and saved.get("raw") == expected["raw"]
        and saved.get("translated") == expected["translated"]
        for saved, expected in zip(saved_pairs, pairs)
    )


def _apply_record(
    record: dict,
    raw_text: str,
    spec,
    output_root: str,
    output_path: Path,
    rag,
    validate_translation,
    *,
    recovering: bool,
) -> None:
    translation_text = _validate_journal(record, raw_text, spec)
    validate_translation(raw_text, translation_text)
    _ensure_output(output_path, output_root, spec, translation_text)
    pairs, provenance = _build_tm_update(raw_text, translation_text, spec)

    has_disk_fingerprint = hasattr(rag, "current_tm_disk_sha256") and hasattr(
        rag, "tm_disk_sha256"
    )
    already_committed = _tm_chapter_matches(rag, spec.tm_key, pairs, provenance)
    if has_disk_fingerprint and (
        recovering or already_committed
    ):
        if (
            rag.current_tm_disk_sha256() != rag.tm_disk_sha256
            and hasattr(rag, "reload_translation_memory")
        ):
            rag.reload_translation_memory()
            already_committed = _tm_chapter_matches(
                rag, spec.tm_key, pairs, provenance
            )
    current_tm_digest = getattr(rag, "tm_disk_sha256", None)
    base_digest = record["tm_base_sha256"]
    if already_committed:
        pass
    else:
        if hasattr(rag, "tm_disk_sha256") and current_tm_digest != base_digest:
            raise ValueError(
                "Translation memory changed after the chapter transaction began."
            )
        rag.update_translation_memory(
            spec.tm_key,
            pairs,
            source_provenance=provenance,
            expected_tm_sha256=base_digest,
        )
        if hasattr(rag, "tm_disk_sha256") and not _tm_chapter_matches(
            rag, spec.tm_key, pairs, provenance
        ):
            raise ValueError("Translation memory did not match the committed chapter.")


def _remove_journal(root: str, filename: str) -> None:
    path = resolve_child_path(root, filename)
    os.unlink(path)


def commit_chapter_translation(
    output_root: str,
    raw_text: str,
    spec,
    translation_text: str,
    rag,
    validate_translation,
) -> None:
    output_path, journal_root, journal_filename, journal_path = _journal_location(
        output_root, spec.translation_file, spec.tm_key
    )
    if journal_path.exists():
        raise ValueError(
            "A chapter transaction is already pending; retry the chapter to recover it."
        )

    record = {
        "schema_version": 1,
        "raw_file": spec.raw_file,
        "translation_file": spec.translation_file,
        "tm_key": spec.tm_key,
        "source_version_id": spec.source_version_id,
        "raw_sha256": _sha256(raw_text.encode("utf-8")),
        "translation_sha256": _sha256(translation_text.encode("utf-8")),
        "tm_base_sha256": getattr(rag, "tm_disk_sha256", None),
        "translation_text": translation_text,
    }
    _validate_journal(record, raw_text, spec)
    validate_translation(raw_text, translation_text)
    journal_text = json.dumps(record, ensure_ascii=False, indent=2)
    if len(journal_text.encode("utf-8")) > _MAX_JOURNAL_BYTES:
        raise ValueError("Chapter transaction journal exceeds the size limit.")
    _write_new_journal(journal_root, journal_filename, journal_text)
    _apply_record(
        record,
        raw_text,
        spec,
        output_root,
        output_path,
        rag,
        validate_translation,
        recovering=False,
    )
    _remove_journal(journal_root, journal_filename)


def recover_chapter_translation(
    output_root: str,
    raw_text: str,
    spec,
    rag,
    validate_translation,
) -> bool:
    output_path, journal_root, journal_filename, journal_path = _journal_location(
        output_root, spec.translation_file, spec.tm_key
    )
    if not journal_path.exists():
        return False
    record = _read_journal(journal_root, journal_filename)
    _apply_record(
        record,
        raw_text,
        spec,
        output_root,
        output_path,
        rag,
        validate_translation,
        recovering=True,
    )
    _remove_journal(journal_root, journal_filename)
    return True
