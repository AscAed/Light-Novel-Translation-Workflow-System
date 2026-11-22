"""Create source-current, reviewed bilingual metadata release artifacts."""

import hashlib
import json

from metadata_translation import (
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)
from metadata_translation_review import verify_metadata_translation_review


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_snapshot(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "catalog_sha256",
        "manifest_sha256",
    }:
        raise ValueError("Metadata publication source snapshot is invalid.")
    result = {}
    for key, digest in value.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("Metadata publication source digest is invalid.")
        result[key] = digest
    return result


def create_metadata_translation_artifact(
    plan: dict,
    candidate: dict,
    review: dict,
    current_source_snapshot: dict,
) -> dict:
    """Build the deterministic approved artifact for the current source snapshot."""
    plan_sha256 = verify_metadata_translation_plan(plan)
    candidate_sha256 = verify_metadata_translation_candidate(candidate, plan)
    review_sha256 = verify_metadata_translation_review(review, plan, candidate)
    source_snapshot = _source_snapshot(current_source_snapshot)
    if (
        review.get("status") != "approved"
        or any(
            item.get("decision") != "approved"
            for item in review["decisions"]
        )
    ):
        raise ValueError("Metadata review is not fully approved.")
    if review["source_snapshot"] != source_snapshot:
        raise ValueError("Metadata review does not match the current source snapshot.")

    candidates_by_id = {item["field_id"]: item for item in candidate["fields"]}
    reviews_by_id = {item["field_id"]: item for item in review["decisions"]}
    fields = []
    translated_count = 0
    missing_count = 0
    for source_field in plan["fields"]:
        field_id = source_field["field_id"]
        if source_field["source_value"] is None:
            missing_count += 1
            fields.append(
                {
                    "field_id": field_id,
                    "entity_kind": source_field["entity_kind"],
                    "entity_id": source_field["entity_id"],
                    "field_name": source_field["field_name"],
                    "source_version_id": source_field["source_version_id"],
                    "source_sha256": None,
                    "source_value": None,
                    "translation_sha256": None,
                    "translation_value": None,
                    "status": "missing_source",
                }
            )
            continue

        translated_count += 1
        candidate_field = candidates_by_id[field_id]
        review_decision = reviews_by_id[field_id]
        if review_decision["decision"] != "approved":
            raise ValueError("Metadata artifact contains a non-approved field.")
        fields.append(
            {
                "field_id": field_id,
                "entity_kind": source_field["entity_kind"],
                "entity_id": source_field["entity_id"],
                "field_name": source_field["field_name"],
                "source_version_id": source_field["source_version_id"],
                "source_sha256": source_field["source_sha256"],
                "source_value": source_field["source_value"],
                "translation_sha256": candidate_field["translation_sha256"],
                "translation_value": candidate_field["translation_value"],
                "status": "approved",
            }
        )

    if (
        len(fields) != len(plan["fields"])
        or translated_count != candidate["field_count"]
        or missing_count != plan["missing_count"]
    ):
        raise ValueError("Metadata artifact coverage differs from its plan.")

    artifact = {
        "schema_version": 1,
        "artifact_type": "bilingual_metadata_release",
        "status": "approved",
        "work_id": plan["work_id"],
        "source_locale": plan["source_locale"],
        "target_locale": plan["target_locale"],
        "plan_sha256": plan_sha256,
        "candidate_sha256": candidate_sha256,
        "review_sha256": review_sha256,
        "quality_rules_version": review["quality_rules_version"],
        "quality_rules_sha256": review["quality_rules_sha256"],
        "source_snapshot": source_snapshot,
        "field_count": len(fields),
        "translated_field_count": translated_count,
        "missing_source_count": missing_count,
        "fields": fields,
        "translation_provenance": dict(candidate["translation_provenance"]),
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        _canonical_json_bytes(artifact)
    ).hexdigest()
    return artifact


def verify_metadata_translation_artifact(
    artifact: dict,
    plan: dict,
    candidate: dict,
    review: dict,
    current_source_snapshot: dict,
) -> str:
    """Verify artifact contents and lineage against current approved inputs."""
    expected = create_metadata_translation_artifact(
        plan,
        candidate,
        review,
        current_source_snapshot,
    )
    if not isinstance(artifact, dict) or artifact != expected:
        raise ValueError("Metadata release artifact differs from approved inputs.")
    return artifact["artifact_sha256"]
