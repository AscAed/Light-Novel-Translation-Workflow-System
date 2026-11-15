"""Create source-verified TM review receipts and approved retrieval snapshots."""

import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from scripts.validate_tm_provenance import audit_translation_memory
from utils import (
    open_regular_file,
    resolve_relative_path,
    validate_tm_source_provenance,
    write_new_child_text,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"approved", "rejected", "escalated"})
_REVIEWED_TM_FIELDS = {
    "_tm_review_schema",
    "artifact_status",
    "approval_status",
    "chapters",
    "source_provenance",
    "review",
}


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("TM review input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_json(path: str) -> tuple[bytes, dict]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("Symbolic links are not allowed for TM review inputs.")
    with open_regular_file(candidate, binary=True) as stream:
        content = stream.read()
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("TM review input must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("TM review input must contain a JSON object.")
    return content, value


def _canonical_sha256(value: dict) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pair_id(chapter: str, pair: dict) -> str:
    raw = pair.get("raw")
    translated = pair.get("translated")
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or not isinstance(translated, str)
        or not translated.strip()
    ):
        raise ValueError("TM review candidate has invalid pair text.")
    return _canonical_sha256(
        {"chapter": chapter, "raw": raw, "translated": translated}
    )


def _validate_pairs(chapter: str, pairs: list) -> list[str]:
    if not isinstance(pairs, list) or not pairs:
        raise ValueError(f"TM review chapter has no pairs: {chapter}")
    pair_ids = []
    embedding_size = None
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("TM review candidate pair must be an object.")
        pair_ids.append(_pair_id(chapter, pair))
        embedding = pair.get("embedding")
        if (
            not isinstance(embedding, list)
            or not embedding
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in embedding
            )
        ):
            raise ValueError("TM review candidate requires a finite embedding.")
        if embedding_size is None:
            embedding_size = len(embedding)
        elif len(embedding) != embedding_size:
            raise ValueError("TM review chapter has inconsistent embedding sizes.")
    if len(pair_ids) != len(set(pair_ids)):
        raise ValueError(f"TM review chapter contains duplicate pairs: {chapter}")
    return pair_ids


def _selected_chapters(tm: dict, chapter_names: list[str] | None) -> dict:
    chapters = tm.get("chapters")
    provenance = tm.get("source_provenance", {})
    if not isinstance(chapters, dict) or not chapters:
        raise ValueError("Translation memory contains no chapters.")
    if not isinstance(provenance, dict):
        raise ValueError("Translation memory source_provenance must be an object.")
    selected_names = list(dict.fromkeys(chapter_names or chapters.keys()))
    if not selected_names or any(name not in chapters for name in selected_names):
        raise ValueError("TM review selected a missing chapter.")
    if any(not isinstance(name, str) or not name for name in selected_names):
        raise ValueError("TM review chapter names must be non-empty strings.")
    selected = {
        "chapters": {name: chapters[name] for name in selected_names},
        "source_provenance": {
            name: provenance[name]
            for name in selected_names
            if name in provenance
        },
    }
    embedding_size = None
    for name, pairs in selected["chapters"].items():
        _validate_pairs(name, pairs)
        for pair in pairs:
            pair_embedding_size = len(pair["embedding"])
            if embedding_size is None:
                embedding_size = pair_embedding_size
            elif pair_embedding_size != embedding_size:
                raise ValueError(
                    "TM review selection contains incompatible embedding sizes."
                )
        chapter_provenance = selected["source_provenance"].get(name)
        if not isinstance(chapter_provenance, dict) or not chapter_provenance.get(
            "source_version_id"
        ):
            raise ValueError(
                f"TM review requires a manifest source version for {name}."
            )
    return selected


def _manifest_digest(source_root: str, manifest_relative_path: str) -> str:
    manifest_path = resolve_relative_path(source_root, manifest_relative_path)
    with open_regular_file(manifest_path, binary=True) as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def _require_verified_sources(
    selected: dict,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
) -> None:
    findings = audit_translation_memory(
        selected,
        source_root,
        translation_root,
        manifest_relative_path,
    )
    if (
        not findings
        or len(findings) != len(selected["chapters"])
        or any(item["status"] != "verified" for item in findings)
    ):
        raise ValueError("Selected TM source provenance is not fully verified.")


def _write_output(output_root: str, output_filename: str, value: dict) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    write_new_child_text(output_root, output_filename, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_tm_review_template(
    tm_path: str,
    output_filename: str,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
    chapter_names: list[str] | None = None,
) -> dict:
    """Create a pending receipt for explicitly selected, source-verified chapters."""
    tm_bytes, tm = _read_json(tm_path)
    selected = _selected_chapters(tm, chapter_names)
    manifest_digest = _manifest_digest(source_root, manifest_relative_path)
    _require_verified_sources(
        selected, source_root, translation_root, manifest_relative_path
    )
    if hashlib.sha256(_read_json(tm_path)[0]).hexdigest() != hashlib.sha256(
        tm_bytes
    ).hexdigest():
        raise ValueError("Translation memory changed during review preparation.")
    if _manifest_digest(source_root, manifest_relative_path) != manifest_digest:
        raise ValueError("Source manifest changed during review preparation.")

    decisions = []
    for chapter, pairs in selected["chapters"].items():
        for pair_id in _validate_pairs(chapter, pairs):
            decisions.append(
                {
                    "chapter": chapter,
                    "pair_sha256": pair_id,
                    "decision": "pending",
                    "rationale": "",
                }
            )
    template = {
        "schema_version": 1,
        "candidate_tm_sha256": hashlib.sha256(tm_bytes).hexdigest(),
        "candidate_manifest_sha256": manifest_digest,
        "chapters": list(selected["chapters"]),
        "reviewer": {"provider_id": "", "model_id": "", "review_id": ""},
        "reviewed_at_utc": "",
        "decisions": decisions,
    }
    digest = _write_output(str(Path(tm_path).parent), output_filename, template)
    return {
        "output": output_filename,
        "decision_count": len(decisions),
        "output_sha256": digest,
    }


def _require_text(value, field: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\r\n\t" for character in value)
    ):
        raise ValueError(f"TM review receipt has an invalid {field}.")
    return value


def _reviewer_record(reviewer) -> dict[str, str]:
    fields = {"provider_id", "model_id", "review_id"}
    if not isinstance(reviewer, dict) or set(reviewer) != fields:
        raise ValueError("TM review receipt has an invalid reviewer record.")
    return {
        key: _require_text(reviewer[key], f"reviewer {key}", 256)
        for key in sorted(fields)
    }


def _validate_timestamp(value: str) -> str:
    value = _require_text(value, "reviewed_at_utc", 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TM review timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("TM review timestamp must use UTC.")
    return value


def _validate_receipt(
    receipt: dict,
    tm: dict,
    tm_digest: str,
    manifest_digest: str,
    selected: dict,
) -> tuple[dict, list[dict]]:
    expected_fields = {
        "schema_version",
        "candidate_tm_sha256",
        "candidate_manifest_sha256",
        "chapters",
        "reviewer",
        "reviewed_at_utc",
        "decisions",
    }
    if set(receipt) != expected_fields or receipt.get("schema_version") != 1:
        raise ValueError("TM review receipt does not match schema version 1.")
    if (
        isinstance(receipt.get("schema_version"), bool)
        or receipt.get("candidate_tm_sha256") != tm_digest
        or receipt.get("candidate_manifest_sha256") != manifest_digest
        or receipt.get("chapters") != list(selected["chapters"])
    ):
        raise ValueError("TM review receipt does not match current inputs.")

    expected = {
        (chapter, pair_id)
        for chapter, pairs in selected["chapters"].items()
        for pair_id in _validate_pairs(chapter, pairs)
    }
    decisions = receipt.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(expected):
        raise ValueError("TM review receipt must decide every selected pair once.")
    normalized = []
    seen = set()
    for item in decisions:
        if not isinstance(item, dict) or set(item) != {
            "chapter",
            "pair_sha256",
            "decision",
            "rationale",
        }:
            raise ValueError("TM review receipt contains a malformed pair decision.")
        key = (item["chapter"], item["pair_sha256"])
        if key not in expected or key in seen:
            raise ValueError("TM review receipt has a missing or duplicate pair.")
        decision = item["decision"]
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise ValueError("TM review receipt contains a pending or unknown decision.")
        normalized.append(
            {
                "chapter": key[0],
                "pair_sha256": key[1],
                "decision": decision,
                "rationale": _require_text(item["rationale"], "rationale"),
            }
        )
        seen.add(key)
    if seen != expected:
        raise ValueError("TM review receipt does not cover every selected pair.")

    return (
        {
            "reviewer": _reviewer_record(receipt.get("reviewer")),
            "reviewed_at_utc": _validate_timestamp(
                receipt.get("reviewed_at_utc")
            ),
        },
        normalized,
    )


def _build_reviewed_bundle(
    tm: dict,
    selected: dict,
    review: dict,
    decisions: list[dict],
    tm_digest: str,
    manifest_digest: str,
    receipt_digest: str,
) -> dict:
    approved = {
        (item["chapter"], item["pair_sha256"])
        for item in decisions
        if item["decision"] == "approved"
    }
    if not approved:
        raise ValueError("TM review approved no pairs.")

    approved_chapters = {}
    approved_provenance = {}
    for chapter, pairs in selected["chapters"].items():
        original_provenance = selected["source_provenance"][chapter]
        original_mappings = original_provenance["pair_mappings"]
        chapter_pairs = []
        chapter_mappings = []
        for original_index, (pair, mapping) in enumerate(
            zip(pairs, original_mappings), start=1
        ):
            if (chapter, _pair_id(chapter, pair)) not in approved:
                continue
            if mapping.get("trace_status") != "matched":
                raise ValueError("Only fully matched TM pairs may be approved.")
            chapter_pairs.append(pair)
            chapter_mappings.append(
                {**mapping, "pair_index": len(chapter_mappings) + 1}
            )
        if chapter_pairs:
            approved_chapters[chapter] = chapter_pairs
            approved_provenance[chapter] = {
                **original_provenance,
                "pair_mappings": chapter_mappings,
            }

    bundle = {
        "_tm_review_schema": 1,
        "artifact_status": "complete",
        "approval_status": "approved_pairs_only",
        "chapters": approved_chapters,
        "source_provenance": approved_provenance,
        "review": {
            **review,
            "candidate_tm_sha256": tm_digest,
            "candidate_manifest_sha256": manifest_digest,
            "review_receipt_sha256": receipt_digest,
            "decisions": decisions,
            "approved_pair_count": sum(
                len(pairs) for pairs in approved_chapters.values()
            ),
        },
    }
    bundle["review"]["bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def publish_reviewed_tm(
    tm_path: str,
    review_path: str,
    output_filename: str,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
) -> dict:
    """Publish an immutable snapshot containing only explicitly approved pairs."""
    tm_bytes, tm = _read_json(tm_path)
    receipt_bytes, receipt = _read_json(review_path)
    tm_digest = hashlib.sha256(tm_bytes).hexdigest()
    manifest_digest = _manifest_digest(source_root, manifest_relative_path)
    selected = _selected_chapters(tm, receipt.get("chapters"))
    _require_verified_sources(
        selected, source_root, translation_root, manifest_relative_path
    )
    review, decisions = _validate_receipt(
        receipt, tm, tm_digest, manifest_digest, selected
    )
    bundle = _build_reviewed_bundle(
        tm,
        selected,
        review,
        decisions,
        tm_digest,
        manifest_digest,
        hashlib.sha256(receipt_bytes).hexdigest(),
    )
    _require_verified_sources(
        selected, source_root, translation_root, manifest_relative_path
    )
    if hashlib.sha256(_read_json(tm_path)[0]).hexdigest() != tm_digest:
        raise ValueError("Translation memory changed during review publication.")
    if hashlib.sha256(_read_json(review_path)[0]).hexdigest() != hashlib.sha256(
        receipt_bytes
    ).hexdigest():
        raise ValueError("TM review receipt changed during publication.")
    if _manifest_digest(source_root, manifest_relative_path) != manifest_digest:
        raise ValueError("Source manifest changed during review publication.")
    output_digest = _write_output(
        str(Path(tm_path).parent), output_filename, bundle
    )
    return {
        "output": output_filename,
        "decision_count": len(decisions),
        "approved_pair_count": bundle["review"]["approved_pair_count"],
        "output_sha256": output_digest,
    }


def load_reviewed_tm_snapshot(
    path: str,
    source_root: str | None,
    translation_root: str | None,
    source_manifest_path: str | None,
) -> dict:
    """Load only a complete, integrity-consistent, currently source-backed bundle."""
    _, bundle = _read_json(path)
    if set(bundle) != _REVIEWED_TM_FIELDS:
        raise ValueError("Reviewed TM bundle has unexpected fields.")
    if (
        isinstance(bundle.get("_tm_review_schema"), bool)
        or bundle.get("_tm_review_schema") != 1
        or bundle.get("artifact_status") != "complete"
        or bundle.get("approval_status") != "approved_pairs_only"
    ):
        raise ValueError("Reviewed TM bundle is not complete and approved.")

    chapters = bundle.get("chapters")
    provenance = bundle.get("source_provenance")
    review = bundle.get("review")
    if (
        not isinstance(chapters, dict)
        or not chapters
        or not isinstance(provenance, dict)
        or set(provenance) != set(chapters)
        or not isinstance(review, dict)
    ):
        raise ValueError("Reviewed TM bundle has invalid chapter data.")
    expected_review_fields = {
        "reviewer",
        "reviewed_at_utc",
        "candidate_tm_sha256",
        "candidate_manifest_sha256",
        "review_receipt_sha256",
        "decisions",
        "approved_pair_count",
        "bundle_sha256",
    }
    if set(review) != expected_review_fields:
        raise ValueError("Reviewed TM bundle has invalid review metadata.")
    reviewer = _reviewer_record(review.get("reviewer"))
    reviewed_at = _validate_timestamp(review.get("reviewed_at_utc"))
    for field in (
        "candidate_tm_sha256",
        "candidate_manifest_sha256",
        "review_receipt_sha256",
        "bundle_sha256",
    ):
        if not isinstance(review.get(field), str) or not _SHA256.fullmatch(
            review[field]
        ):
            raise ValueError("Reviewed TM bundle has an invalid hash binding.")

    decisions = review.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("Reviewed TM bundle has no decisions.")
    approved_decisions = set()
    decision_keys = set()
    for item in decisions:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"chapter", "pair_sha256", "decision", "rationale"}
            or item.get("decision") not in _DECISIONS
            or not isinstance(item.get("chapter"), str)
            or not isinstance(item.get("pair_sha256"), str)
            or not _SHA256.fullmatch(item["pair_sha256"])
            or not isinstance(item.get("rationale"), str)
            or not item["rationale"].strip()
        ):
            raise ValueError("Reviewed TM bundle has a malformed decision.")
        key = (item["chapter"], item["pair_sha256"])
        if key in decision_keys:
            raise ValueError("Reviewed TM bundle contains duplicate decisions.")
        decision_keys.add(key)
        if item["decision"] == "approved":
            approved_decisions.add(key)

    actual_approved = {
        (chapter, pair_id)
        for chapter, pairs in chapters.items()
        for pair_id in _validate_pairs(chapter, pairs)
    }
    if (
        actual_approved != approved_decisions
        or review.get("approved_pair_count") != len(actual_approved)
    ):
        raise ValueError("Reviewed TM pairs do not match approved decisions.")

    for chapter, pairs in chapters.items():
        chapter_provenance = provenance[chapter]
        try:
            validate_tm_source_provenance(chapter_provenance, len(pairs))
        except (TypeError, ValueError) as exc:
            raise ValueError("Reviewed TM source provenance is invalid.") from exc
        if any(
            mapping["trace_status"] != "matched"
            for mapping in chapter_provenance["pair_mappings"]
        ):
            raise ValueError("Reviewed TM contains a pair without matched provenance.")

    integrity_payload = json.loads(json.dumps(bundle, ensure_ascii=False))
    integrity_payload["review"].pop("bundle_sha256")
    if _canonical_sha256(integrity_payload) != review["bundle_sha256"]:
        raise ValueError("Reviewed TM bundle integrity hash does not match.")
    if not source_root or not translation_root or not source_manifest_path:
        raise ValueError(
            "Reviewed TM retrieval requires source, translation, and manifest paths."
        )
    _require_verified_sources(
        {"chapters": chapters, "source_provenance": provenance},
        source_root,
        translation_root,
        source_manifest_path,
    )
    return {
        "chapters": chapters,
        "source_provenance": provenance,
        "review": {
            **review,
            "reviewer": reviewer,
            "reviewed_at_utc": reviewed_at,
        },
    }
