"""Create and validate reviewed story-summary bundles."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from source_manifest import (
    latest_artifacts_by_kind,
    latest_raw_parent_for_normalized,
    load_manifest,
    verify_manifest_artifact,
)
from utils import (
    open_regular_file,
    resolve_child_path,
    resolve_relative_path,
    write_new_child_text,
)


_MAX_INPUT_BYTES = 16 * 1024 * 1024
_MAX_BUNDLE_BYTES = 32 * 1024 * 1024
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_COUNT = 3
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"approved", "rejected", "escalated"})


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Summary review input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_bounded_file(path: Path, limit: int) -> bytes:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Summary review input exceeds the configured size limit.")
    return content


def _read_child_bytes(root: str, filename: str) -> bytes:
    return _read_bounded_file(
        resolve_child_path(root, filename),
        _MAX_INPUT_BYTES,
    )


def _read_json(content: bytes) -> dict:
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Summary review input must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Summary review input must contain a JSON object.")
    return value


def _require_text(value, field: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\r\n\t" for character in value)
    ):
        raise ValueError(f"Summary review input has an invalid {field}.")
    return value


def _require_sha256(value, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"Summary review input has an invalid {field}.")
    return value


def _validate_timestamp(value) -> str:
    value = _require_text(value, "reviewed_at_utc", maximum=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Summary review input has an invalid reviewed_at_utc.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Summary review timestamp must be explicitly UTC.")
    return value


def _validate_reviewer(value) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "provider_id",
        "model_id",
        "review_id",
    }:
        raise ValueError("Summary review input has an invalid reviewer record.")
    provider_id = _require_text(
        value.get("provider_id"), "reviewer provider_id", maximum=128
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider_id):
        raise ValueError("Summary review input has an invalid reviewer provider_id.")
    return {
        "provider_id": provider_id.lower(),
        "model_id": _require_text(
            value.get("model_id"), "reviewer model_id", maximum=256
        ),
        "review_id": _require_text(
            value.get("review_id"), "reviewer review_id", maximum=256
        ),
    }


def _validate_summary_provenance(provenance: dict) -> dict:
    if not isinstance(provenance, dict):
        raise ValueError("Summary provenance must be a JSON object.")
    if (
        isinstance(provenance.get("schema_version"), bool)
        or provenance.get("schema_version") != 1
        or provenance.get("artifact_status") != "complete"
    ):
        raise ValueError("Summary provenance must be a complete schema v1 artifact.")

    source_files = provenance.get("source_files")
    summary_chapters = provenance.get("summary_source_chapters")
    if (
        not isinstance(source_files, list)
        or not source_files
        or len(source_files) > _MAX_SOURCE_COUNT
        or not isinstance(summary_chapters, list)
        or not summary_chapters
    ):
        raise ValueError(
            "Summary provenance must identify one to three source chapters."
        )

    normalized_sources = []
    filenames = []
    for item in source_files:
        if not isinstance(item, dict):
            raise ValueError("Summary provenance contains a malformed source entry.")
        filename = _require_text(item.get("filename"), "source filename", maximum=4096)
        source_digest = _require_sha256(
            item.get("source_sha256"), "source_sha256"
        )
        version_id = _require_text(
            item.get("source_version_id"), "source_version_id", maximum=256
        )
        if filename.casefold() in {name.casefold() for name in filenames}:
            raise ValueError("Summary provenance repeats a source filename.")
        filenames.append(filename)
        normalized_sources.append(
            {
                "filename": filename,
                "source_sha256": source_digest,
                "source_version_id": version_id,
            }
        )

    if (
        any(not isinstance(name, str) for name in summary_chapters)
        or summary_chapters != filenames
    ):
        raise ValueError(
            "Summary source chapters must match the provenance source-file order."
        )
    return {
        "summary_source_chapters": list(summary_chapters),
        "source_files": normalized_sources,
    }


def _validate_summary_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > _MAX_INPUT_BYTES
        or any(
            ord(character) < 32 and character not in "\r\n\t"
            for character in value
        )
    ):
        raise ValueError("Summary candidate must be non-empty and within the size limit.")
    return value


def verify_summary_sources(
    source_root: str,
    manifest_relative_path: str,
    source_provenance: dict,
) -> None:
    """Require every summary source to be the current verified normalized version."""
    normalized = _validate_summary_provenance(
        {
            "schema_version": 1,
            "artifact_status": "complete",
            **source_provenance,
        }
    )
    manifest_path = resolve_relative_path(source_root, manifest_relative_path)
    manifest = load_manifest(manifest_path)
    latest = latest_artifacts_by_kind(manifest, "normalized_source")

    for source in normalized["source_files"]:
        filename = source["filename"]
        version_id = source["source_version_id"]
        artifact = next(
            (
                item
                for item in manifest["artifacts"]
                if item["version_id"] == version_id
            ),
            None,
        )
        if artifact is None or artifact["relative_path"] is None:
            raise ValueError("Summary source version is missing from the manifest.")
        if artifact["kind"] != "normalized_source" or artifact["relative_path"] != filename:
            raise ValueError("Summary source version does not match its path.")
        current = latest.get(artifact["artifact_id"])
        if current is None or current["version_id"] != version_id:
            raise ValueError("Summary source versions are not current.")
        latest_raw = latest_raw_parent_for_normalized(manifest, current)
        verify_manifest_artifact(
            source_root, manifest, latest_raw["version_id"]
        )
        if latest_raw["version_id"] not in current["parent_version_ids"]:
            raise ValueError("Summary source versions are not current.")

        source_path = resolve_relative_path(source_root, filename)
        source_bytes = _read_bounded_file(source_path, _MAX_SOURCE_BYTES)
        if hashlib.sha256(source_bytes).hexdigest() != artifact["content_sha256"]:
            raise ValueError("Summary source bytes do not match the manifest.")
        try:
            source_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Summary source is not valid UTF-8.") from exc
        normalized_text = source_text.replace("\r\n", "\n").replace("\r", "\n")
        if hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() != source[
            "source_sha256"
        ]:
            raise ValueError("Summary source text does not match its provenance.")


def _candidate_inputs(knowledge_root: str) -> tuple[bytes, str, bytes, dict, dict]:
    summary_bytes = _read_child_bytes(knowledge_root, "STORY_SUMMARY_draft.md")
    try:
        summary = summary_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Summary candidate must be valid UTF-8.") from exc
    _validate_summary_text(summary)

    provenance_bytes = _read_child_bytes(
        knowledge_root, "KNOWLEDGE_PROVENANCE_draft.json"
    )
    provenance = _read_json(provenance_bytes)
    source_provenance = _validate_summary_provenance(provenance)
    return summary_bytes, summary, provenance_bytes, provenance, source_provenance


def create_summary_review_template(
    knowledge_root: str,
    output_filename: str,
) -> dict:
    """Create a pending receipt bound to the summary and provenance candidates."""
    summary_bytes, _, provenance_bytes, _, source_provenance = _candidate_inputs(
        knowledge_root
    )
    template = {
        "schema_version": 1,
        "candidate_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "candidate_provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
        "reviewer": {"provider_id": "", "model_id": "", "review_id": ""},
        "reviewed_at_utc": "",
        "decision": "pending",
        "rationale": "",
        "summary_source_chapters": source_provenance["summary_source_chapters"],
    }
    output_text = json.dumps(template, ensure_ascii=False, indent=2)
    write_new_child_text(knowledge_root, output_filename, output_text)
    output_path = resolve_child_path(knowledge_root, output_filename)
    with open_regular_file(output_path, binary=True) as stream:
        output_digest = hashlib.sha256(stream.read()).hexdigest()
    return {
        "output": output_filename,
        "source_count": len(source_provenance["source_files"]),
        "output_sha256": output_digest,
    }


def _validate_review_receipt(
    receipt: dict,
    summary_digest: str,
    provenance_digest: str,
    summary_chapters: list[str],
) -> dict:
    expected_fields = {
        "schema_version",
        "candidate_summary_sha256",
        "candidate_provenance_sha256",
        "reviewer",
        "reviewed_at_utc",
        "decision",
        "rationale",
        "summary_source_chapters",
    }
    if set(receipt) != expected_fields:
        raise ValueError("Summary review receipt has an invalid field set.")
    if (
        isinstance(receipt.get("schema_version"), bool)
        or receipt.get("schema_version") != 1
        or receipt.get("candidate_summary_sha256") != summary_digest
        or receipt.get("candidate_provenance_sha256") != provenance_digest
        or receipt.get("summary_source_chapters") != summary_chapters
    ):
        raise ValueError("Summary review receipt does not match current candidates.")

    decision = receipt.get("decision")
    if not isinstance(decision, str) or decision not in _DECISIONS:
        raise ValueError("Summary review receipt has an invalid decision.")
    return {
        "reviewer": _validate_reviewer(receipt.get("reviewer")),
        "reviewed_at_utc": _validate_timestamp(receipt.get("reviewed_at_utc")),
        "decision": decision,
        "rationale": _require_text(
            receipt.get("rationale"), "decision rationale", maximum=4096
        ),
    }


def publish_reviewed_summary(
    knowledge_root: str,
    source_root: str,
    manifest_relative_path: str,
    receipt_filename: str,
    output_filename: str,
) -> dict:
    """Publish one approved summary bound to current source versions."""
    if (
        not isinstance(output_filename, str)
        or not output_filename.lower().endswith(".json")
    ):
        raise ValueError("Reviewed summary output filename must end with .json.")

    summary_bytes, summary, provenance_bytes, _, source_provenance = _candidate_inputs(
        knowledge_root
    )
    receipt_bytes = _read_child_bytes(knowledge_root, receipt_filename)
    receipt = _read_json(receipt_bytes)
    review = _validate_review_receipt(
        receipt,
        hashlib.sha256(summary_bytes).hexdigest(),
        hashlib.sha256(provenance_bytes).hexdigest(),
        source_provenance["summary_source_chapters"],
    )
    if review["decision"] != "approved":
        raise ValueError("Only an explicitly approved summary can be published.")
    verify_summary_sources(
        source_root,
        manifest_relative_path,
        source_provenance,
    )

    summary_digest = hashlib.sha256(summary_bytes).hexdigest()
    source_provenance_digest = hashlib.sha256(
        json.dumps(
            source_provenance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    bundle = {
        "_story_summary_review_schema": 1,
        "artifact_status": "complete",
        "approval_status": "approved",
        "summary": summary,
        "summary_sha256": summary_digest,
        "source_provenance": source_provenance,
        "source_provenance_sha256": source_provenance_digest,
        "review": {
            **review,
            "candidate_summary_sha256": summary_digest,
            "candidate_provenance_sha256": hashlib.sha256(
                provenance_bytes
            ).hexdigest(),
            "review_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        },
    }
    output_text = json.dumps(bundle, ensure_ascii=False, indent=2)
    write_new_child_text(knowledge_root, output_filename, output_text)
    output_path = resolve_child_path(knowledge_root, output_filename)
    with open_regular_file(output_path, binary=True) as stream:
        output_digest = hashlib.sha256(stream.read()).hexdigest()
    return {
        "output": output_filename,
        "source_count": len(source_provenance["source_files"]),
        "output_sha256": output_digest,
    }


def load_reviewed_story_summary(
    path: str,
    source_root: str,
    manifest_relative_path: str | None,
) -> str:
    """Validate an approved bundle and return its summary text."""
    bundle_path = Path(path)
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise ValueError("Reviewed summary path must be a regular file.")
    bundle_bytes = _read_bounded_file(bundle_path, _MAX_BUNDLE_BYTES)
    bundle = _read_json(bundle_bytes)
    expected_fields = {
        "_story_summary_review_schema",
        "artifact_status",
        "approval_status",
        "summary",
        "summary_sha256",
        "source_provenance",
        "source_provenance_sha256",
        "review",
    }
    if set(bundle) != expected_fields:
        raise ValueError("Reviewed summary bundle has an invalid field set.")
    if (
        isinstance(bundle.get("_story_summary_review_schema"), bool)
        or bundle.get("_story_summary_review_schema") != 1
        or bundle.get("artifact_status") != "complete"
        or bundle.get("approval_status") != "approved"
    ):
        raise ValueError("Reviewed summary bundle is not approved and complete.")

    summary = _validate_summary_text(bundle.get("summary"))
    summary_digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    if bundle.get("summary_sha256") != summary_digest:
        raise ValueError("Reviewed summary content hash does not match.")

    source_provenance = _validate_summary_provenance(
        {
            "schema_version": 1,
            "artifact_status": "complete",
            **bundle.get("source_provenance", {}),
        }
        if isinstance(bundle.get("source_provenance"), dict)
        else {}
    )
    expected_source_provenance_digest = hashlib.sha256(
        json.dumps(
            source_provenance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if bundle.get("source_provenance_sha256") != expected_source_provenance_digest:
        raise ValueError("Reviewed summary source provenance hash does not match.")
    review = bundle.get("review")
    if not isinstance(review, dict) or set(review) != {
        "reviewer",
        "reviewed_at_utc",
        "decision",
        "rationale",
        "candidate_summary_sha256",
        "candidate_provenance_sha256",
        "review_receipt_sha256",
    }:
        raise ValueError("Reviewed summary bundle has an invalid review record.")
    _validate_reviewer(review.get("reviewer"))
    _validate_timestamp(review.get("reviewed_at_utc"))
    if review.get("decision") != "approved":
        raise ValueError("Reviewed summary bundle has no approval decision.")
    _require_text(review.get("rationale"), "decision rationale", maximum=4096)
    if review.get("candidate_summary_sha256") != summary_digest:
        raise ValueError("Reviewed summary candidate hash does not match.")
    _require_sha256(
        review.get("candidate_provenance_sha256"),
        "candidate_provenance_sha256",
    )
    _require_sha256(
        review.get("review_receipt_sha256"),
        "review_receipt_sha256",
    )
    if not manifest_relative_path:
        raise ValueError("Reviewed summary requires a source manifest.")
    verify_summary_sources(
        source_root,
        manifest_relative_path,
        source_provenance,
    )
    return summary
