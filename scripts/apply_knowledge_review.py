"""Publish only explicitly approved glossary candidates from a review receipt."""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.validate_knowledge_provenance import audit_knowledge_provenance
from utils import (
    open_regular_file,
    resolve_child_path,
    resolve_relative_path,
    split_paragraphs,
    write_new_child_text,
)
from source_manifest import load_manifest, verify_manifest_artifact


_MAX_INPUT_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"approved", "rejected", "escalated"})


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Review input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_json_child(root: str, filename: str) -> tuple[bytes, dict]:
    path = resolve_child_path(root, filename)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_INPUT_BYTES + 1)
    if len(content) > _MAX_INPUT_BYTES:
        raise ValueError("Review input exceeds the configured size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Review input must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Review input must contain a JSON object.")
    return content, value


def _require_sha256(value, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"Review input has an invalid {field}.")
    return value


def _require_text(value, field: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\r\n\t" for character in value)
    ):
        raise ValueError(f"Review input has an invalid {field}.")
    return value


def _validate_timestamp(value) -> str:
    value = _require_text(value, "reviewed_at_utc", maximum=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Review input has an invalid reviewed_at_utc.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Review timestamp must be an explicit UTC timestamp.")
    return value


def _validate_glossary(glossary: dict) -> dict[str, str]:
    if not glossary:
        raise ValueError("Candidate glossary must contain at least one term.")
    for source, translation in glossary.items():
        _require_text(source, "glossary source term", maximum=1000)
        _require_text(translation, "glossary translation", maximum=4000)
    return glossary


def _validate_evidence(provenance: dict, glossary: dict[str, str]) -> dict:
    if (
        isinstance(provenance.get("schema_version"), bool)
        or provenance.get("schema_version") != 1
        or provenance.get("artifact_status") != "complete"
    ):
        raise ValueError("Knowledge provenance is not a complete schema v1 artifact.")

    source_files = provenance.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ValueError("Knowledge provenance has no source files.")
    paragraphs_by_filename = {}
    for source in source_files:
        if not isinstance(source, dict):
            raise ValueError("Knowledge provenance has a malformed source file.")
        filename = source.get("filename")
        paragraph_count = source.get("included_paragraph_count")
        included_characters = source.get("included_characters")
        included_digest = source.get("included_sha256")
        if (
            not isinstance(filename, str)
            or not filename
            or filename in paragraphs_by_filename
            or isinstance(paragraph_count, bool)
            or not isinstance(paragraph_count, int)
            or paragraph_count < 1
            or isinstance(included_characters, bool)
            or not isinstance(included_characters, int)
            or included_characters < 1
            or not isinstance(included_digest, str)
            or not _SHA256_PATTERN.fullmatch(included_digest)
        ):
            raise ValueError("Knowledge provenance has a malformed source file.")
        paragraphs_by_filename[filename] = {
            "paragraph_count": paragraph_count,
            "included_characters": included_characters,
            "included_sha256": included_digest,
        }

    evidence = provenance.get("glossary_evidence")
    if not isinstance(evidence, list):
        raise ValueError("Knowledge provenance has no glossary evidence.")
    evidence_by_source = {}
    for item in evidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"src", "occurrences"}
            or not isinstance(item.get("src"), str)
            or item["src"] in evidence_by_source
            or not isinstance(item.get("occurrences"), list)
        ):
            raise ValueError("Knowledge provenance has malformed glossary evidence.")
        normalized_occurrences = []
        for occurrence in item["occurrences"]:
            if (
                not isinstance(occurrence, dict)
                or set(occurrence) != {"chapter", "paragraph_indices"}
                or occurrence.get("chapter") not in paragraphs_by_filename
                or not isinstance(occurrence.get("paragraph_indices"), list)
                or not occurrence["paragraph_indices"]
            ):
                raise ValueError("Knowledge provenance has malformed term locations.")
            indices = occurrence["paragraph_indices"]
            paragraph_count = paragraphs_by_filename[
                occurrence["chapter"]
            ]["paragraph_count"]
            if (
                any(
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or index < 1
                    or index > paragraph_count
                    for index in indices
                )
                or indices != sorted(set(indices))
            ):
                raise ValueError("Knowledge provenance has invalid term locations.")
            normalized_occurrences.append(
                {
                    "chapter": occurrence["chapter"],
                    "paragraph_indices": list(indices),
                }
            )
        evidence_by_source[item["src"]] = normalized_occurrences

    if set(evidence_by_source) != set(glossary):
        raise ValueError("Knowledge provenance does not match candidate glossary terms.")
    return evidence_by_source


def _verify_source_evidence(
    source_root: str,
    manifest: dict,
    provenance: dict,
    evidence_by_source: dict,
) -> None:
    paragraphs_by_filename = {}
    for source in provenance["source_files"]:
        filename = source["filename"]
        version = verify_manifest_artifact(
            source_root,
            manifest,
            source["source_version_id"],
        )
        if (
            version["kind"] != "normalized_source"
            or version["relative_path"] != filename
        ):
            raise ValueError("Knowledge source version does not match its path.")
        source_path = resolve_relative_path(source_root, filename)
        with open_regular_file(source_path, binary=True) as stream:
            source_bytes = stream.read(_MAX_SOURCE_BYTES + 1)
        if len(source_bytes) > _MAX_SOURCE_BYTES:
            raise ValueError("Source chapter exceeds the review size limit.")
        if hashlib.sha256(source_bytes).hexdigest() != version["content_sha256"]:
            raise ValueError("Source chapter changed during review publication.")
        try:
            text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Source chapter is not valid UTF-8.") from exc
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if (
            hashlib.sha256(text.encode("utf-8")).hexdigest()
            != source["source_sha256"]
        ):
            raise ValueError("Source text changed during review publication.")
        included_text = text[: source["included_characters"]]
        if (
            hashlib.sha256(included_text.encode("utf-8")).hexdigest()
            != source["included_sha256"]
        ):
            raise ValueError("Knowledge sample does not match current source text.")
        paragraphs = split_paragraphs(included_text)
        if len(paragraphs) != source["included_paragraph_count"]:
            raise ValueError("Knowledge sample paragraph count does not match.")
        paragraphs_by_filename[filename] = paragraphs

    for source_term, occurrences in evidence_by_source.items():
        actual_occurrences = []
        for filename, paragraphs in paragraphs_by_filename.items():
            paragraph_indices = [
                index
                for index, paragraph in enumerate(paragraphs, start=1)
                if source_term in paragraph
            ]
            if paragraph_indices:
                actual_occurrences.append(
                    {"chapter": filename, "paragraph_indices": paragraph_indices}
                )
        if actual_occurrences != occurrences:
            raise ValueError("Glossary source locations do not match source text.")


def _validate_review_receipt(
    receipt: dict,
    glossary: dict[str, str],
    glossary_digest: str,
    provenance_digest: str,
) -> tuple[dict, list[dict]]:
    expected_fields = {
        "schema_version",
        "candidate_glossary_sha256",
        "candidate_provenance_sha256",
        "reviewer",
        "reviewed_at_utc",
        "decisions",
    }
    if set(receipt) != expected_fields or receipt.get("schema_version") != 1:
        raise ValueError("Review receipt must match schema version 1.")
    if (
        isinstance(receipt.get("schema_version"), bool)
        or receipt["candidate_glossary_sha256"] != glossary_digest
        or receipt["candidate_provenance_sha256"] != provenance_digest
    ):
        raise ValueError("Review receipt does not match the current candidate files.")

    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {
        "provider_id",
        "model_id",
        "review_id",
    }:
        raise ValueError("Review receipt has an invalid reviewer record.")
    provider_id = _require_text(
        reviewer.get("provider_id"), "reviewer provider_id", maximum=128
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider_id):
        raise ValueError("Review receipt has an invalid reviewer provider_id.")
    reviewer_record = {
        "provider_id": provider_id.lower(),
        "model_id": _require_text(
            reviewer.get("model_id"), "reviewer model_id", maximum=256
        ),
        "review_id": _require_text(
            reviewer.get("review_id"), "reviewer review_id", maximum=256
        ),
    }
    reviewed_at = _validate_timestamp(receipt.get("reviewed_at_utc"))

    decisions = receipt.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(glossary):
        raise ValueError("Review receipt must decide every glossary candidate once.")
    decisions_by_source = {}
    for item in decisions:
        if (
            not isinstance(item, dict)
            or set(item) != {"src", "decision", "rationale"}
        ):
            raise ValueError("Review receipt contains a malformed term decision.")
        source = item.get("src")
        if (
            not isinstance(source, str)
            or source not in glossary
            or source in decisions_by_source
        ):
            raise ValueError("Review receipt has a missing or duplicate term decision.")
        decision = item.get("decision")
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise ValueError("Review receipt contains an unknown term decision.")
        rationale = _require_text(
            item.get("rationale"), "decision rationale", maximum=4096
        )
        decisions_by_source[source] = {
            "src": source,
            "decision": decision,
            "rationale": rationale,
        }
    if set(decisions_by_source) != set(glossary):
        raise ValueError("Review receipt does not cover every glossary candidate.")
    return {"reviewer": reviewer_record, "reviewed_at_utc": reviewed_at}, [
        decisions_by_source[source] for source in glossary
    ]


def _terms_sha256(terms: dict[str, str]) -> str:
    canonical = json.dumps(
        terms,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_knowledge_review_template(
    knowledge_root: str,
    output_filename: str,
) -> dict:
    """Create an incomplete, candidate-hash-bound receipt for a local reviewer."""
    glossary_bytes, glossary = _read_json_child(
        knowledge_root, "Glossary_draft.json"
    )
    provenance_bytes, provenance = _read_json_child(
        knowledge_root, "KNOWLEDGE_PROVENANCE_draft.json"
    )
    glossary = _validate_glossary(glossary)
    _validate_evidence(provenance, glossary)

    template = {
        "schema_version": 1,
        "candidate_glossary_sha256": hashlib.sha256(glossary_bytes).hexdigest(),
        "candidate_provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
        "reviewer": {
            "provider_id": "",
            "model_id": "",
            "review_id": "",
        },
        "reviewed_at_utc": "",
        "decisions": [
            {
                "src": source,
                "decision": "pending",
                "rationale": "",
            }
            for source in glossary
        ],
    }
    output_text = json.dumps(template, ensure_ascii=False, indent=2)
    write_new_child_text(knowledge_root, output_filename, output_text)
    return {
        "output": output_filename,
        "decision_count": len(glossary),
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
    }


def apply_knowledge_review(
    knowledge_root: str,
    source_root: str,
    manifest_relative_path: str,
    review_filename: str,
    output_filename: str,
) -> dict:
    """Create a new reviewed glossary bundle from fresh candidates and a receipt."""
    glossary_bytes, glossary = _read_json_child(
        knowledge_root, "Glossary_draft.json"
    )
    provenance_bytes, provenance = _read_json_child(
        knowledge_root, "KNOWLEDGE_PROVENANCE_draft.json"
    )
    receipt_bytes, receipt = _read_json_child(knowledge_root, review_filename)
    glossary = _validate_glossary(glossary)
    evidence_by_source = _validate_evidence(provenance, glossary)

    findings = audit_knowledge_provenance(
        provenance,
        source_root,
        manifest_relative_path,
    )
    if not findings or any(item["status"] != "verified" for item in findings):
        raise ValueError("Candidate source provenance is not fully verified.")
    manifest = load_manifest(
        resolve_relative_path(source_root, manifest_relative_path)
    )
    _verify_source_evidence(
        source_root,
        manifest,
        provenance,
        evidence_by_source,
    )

    glossary_digest = hashlib.sha256(glossary_bytes).hexdigest()
    provenance_digest = hashlib.sha256(provenance_bytes).hexdigest()
    review, decisions = _validate_review_receipt(
        receipt,
        glossary,
        glossary_digest,
        provenance_digest,
    )
    if any(
        decision["decision"] == "approved"
        and not evidence_by_source[decision["src"]]
        for decision in decisions
    ):
        raise ValueError("Review receipt approved a term without source evidence.")
    published_terms = {
        decision["src"]: glossary[decision["src"]]
        for decision in decisions
        if decision["decision"] == "approved"
    }
    if not published_terms:
        raise ValueError("Review receipt approved no glossary terms.")

    reviewed_decisions = [
        {
            **decision,
            "evidence": evidence_by_source[decision["src"]],
        }
        for decision in decisions
    ]
    bundle = {
        "_knowledge_review_schema": 1,
        "artifact_status": "complete",
        "approval_status": "approved_terms_only",
        "terms": published_terms,
        "review": {
            **review,
            "candidate_glossary_sha256": glossary_digest,
            "candidate_provenance_sha256": provenance_digest,
            "review_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "terms_sha256": _terms_sha256(published_terms),
            "source_files": provenance["source_files"],
            "decisions": reviewed_decisions,
        },
    }
    output_text = json.dumps(bundle, ensure_ascii=False, indent=2)
    write_new_child_text(knowledge_root, output_filename, output_text)
    return {
        "output": output_filename,
        "approved_term_count": len(published_terms),
        "decision_count": len(decisions),
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an incomplete review template or publish approved glossary candidates."
    )
    parser.add_argument("--knowledge-root", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--manifest")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--review")
    mode.add_argument("--create-template", metavar="FILENAME")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.create_template:
            if args.output is not None:
                parser.error("--output is only valid with --review.")
            result = create_knowledge_review_template(
                args.knowledge_root,
                args.create_template,
            )
            label = "Incomplete review template created"
        else:
            if not args.source_root or not args.manifest or not args.output:
                parser.error(
                    "--source-root, --manifest, and --output are required with --review."
                )
            result = apply_knowledge_review(
                args.knowledge_root,
                args.source_root,
                args.manifest,
                args.review,
                args.output,
            )
            label = "Reviewed glossary artifact created"
    except (OSError, UnicodeError, ValueError) as exc:
        print(
            f"Knowledge review operation refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    detail = (
        f"approved_terms={result['approved_term_count']}, "
        if "approved_term_count" in result
        else ""
    )
    print(
        f"{label}: "
        f"{result['output']} "
        f"({detail}decisions={result['decision_count']}, "
        f"sha256={result['output_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
