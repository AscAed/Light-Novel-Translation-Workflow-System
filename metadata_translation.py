"""Create and verify source-bound translation inventories for book metadata."""

import hashlib
import json
import re
from datetime import datetime, timedelta


_PLAN_FIELDS = {
    "schema_version",
    "plan_type",
    "status",
    "work_id",
    "source_locale",
    "target_locale",
    "field_count",
    "pending_count",
    "missing_count",
    "fields",
    "plan_sha256",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CANDIDATE_FIELDS = {
    "schema_version",
    "candidate_type",
    "status",
    "work_id",
    "source_locale",
    "target_locale",
    "plan_sha256",
    "field_count",
    "missing_source_count",
    "fields",
    "translation_provenance",
    "candidate_sha256",
}
_CANDIDATE_ITEM_FIELDS = {
    "field_id",
    "entity_kind",
    "entity_id",
    "field_name",
    "source_version_id",
    "source_sha256",
    "source_value",
    "translation_value",
    "translation_sha256",
    "review_status",
}
_PROVENANCE_FIELDS = {
    "declared_origin",
    "provider_id",
    "model_id",
    "prompt_sha256",
    "recorded_at_utc",
}


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_field(
    *,
    field_id: str,
    entity_kind: str,
    entity_id: str,
    field_name: str,
    source_value: str | None,
    version_id: str,
) -> dict:
    if source_value is not None and not isinstance(source_value, str):
        raise ValueError("Metadata translation source values must be text or null.")
    if not isinstance(version_id, str) or not version_id:
        raise ValueError("Metadata source version identity is missing.")
    is_present = isinstance(source_value, str) and bool(source_value.strip())
    return {
        "field_id": field_id,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "field_name": field_name,
        "source_value": source_value if is_present else None,
        "source_sha256": _sha256_text(source_value) if is_present else None,
        "source_version_id": version_id,
        "translation_value": None,
        "status": "pending_translation" if is_present else "missing_source",
    }


def _require_id(value, label: str) -> str:
    if not isinstance(value, str) or not value or any(
        ord(character) < 32 for character in value
    ):
        raise ValueError(f"Verified metadata bundle has an invalid {label}.")
    return value


def create_metadata_translation_plan(verified_bundle: dict) -> dict:
    """Build a deterministic inventory from a currently verified AI bundle.

    This inventory contains source metadata values for local translation. It
    intentionally excludes episode body text and non-linguistic identifiers.
    """
    if (
        not isinstance(verified_bundle, dict)
        or verified_bundle.get("status") != "verified"
        or not isinstance(verified_bundle.get("bundle"), dict)
    ):
        raise ValueError("A verified current book bundle is required.")
    bundle = verified_bundle["bundle"]
    work_id = _require_id(bundle.get("work_id"), "work ID")
    work_metadata = bundle.get("work_metadata")
    metadata_version_id = bundle.get("work_metadata_version_id")
    catalog_sha256 = (
        bundle.get("provenance", {})
        .get("catalog", {})
        .get("sha256")
        if isinstance(bundle.get("provenance"), dict)
        else None
    )
    if (
        not isinstance(work_metadata, dict)
        or not isinstance(metadata_version_id, str)
        or not metadata_version_id
        or not isinstance(catalog_sha256, str)
        or not _SHA256.fullmatch(catalog_sha256)
    ):
        raise ValueError("Verified bundle lacks versioned work metadata.")

    fields = []
    for field_name in ("title", "catchphrase", "introduction", "genre"):
        if field_name not in work_metadata:
            raise ValueError("Work metadata is missing a supported field.")
        fields.append(
            _source_field(
                field_id=f"work.{field_name}",
                entity_kind="work",
                entity_id=work_id,
                field_name=field_name,
                source_value=work_metadata[field_name],
                version_id=metadata_version_id,
            )
        )

    tags = work_metadata.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("Work metadata tags must be an ordered text list.")
    for index, tag in enumerate(tags, start=1):
        fields.append(
            _source_field(
                field_id=f"work.tags.{index:04d}",
                entity_kind="work",
                entity_id=work_id,
                field_name="tag",
                source_value=tag,
                version_id=metadata_version_id,
            )
        )

    groups = bundle.get("groups")
    episodes = bundle.get("episodes")
    if not isinstance(groups, list) or not isinstance(episodes, list):
        raise ValueError("Verified bundle chapter metadata is invalid.")
    episode_count = verified_bundle.get("episode_count")
    if (
        isinstance(episode_count, bool)
        or not isinstance(episode_count, int)
        or len(episodes) != episode_count
    ):
        raise ValueError("Verified bundle episode metadata count is inconsistent.")

    seen_group_ids = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Verified bundle contains an invalid chapter group.")
        group_id = _require_id(group.get("group_id"), "chapter group ID")
        if group_id in seen_group_ids:
            raise ValueError("Verified bundle contains duplicate chapter groups.")
        seen_group_ids.add(group_id)
        fields.append(
            _source_field(
                field_id=f"chapter.{group_id}.title",
                entity_kind="chapter",
                entity_id=group_id,
                field_name="title",
                source_value=group.get("title"),
                version_id=catalog_sha256,
            )
        )

    seen_episode_ids = set()
    positions = set()
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("Verified bundle contains invalid episode metadata.")
        episode_id = _require_id(episode.get("episode_id"), "episode ID")
        position = episode.get("position")
        version_id = episode.get("episode_metadata_version_id")
        if (
            episode_id in seen_episode_ids
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or position in positions
            or not isinstance(version_id, str)
            or not version_id
        ):
            raise ValueError("Verified bundle episode metadata is inconsistent.")
        seen_episode_ids.add(episode_id)
        positions.add(position)
        fields.append(
            _source_field(
                field_id=f"episode.{episode_id}.title",
                entity_kind="episode",
                entity_id=episode_id,
                field_name="title",
                source_value=episode.get("title"),
                version_id=version_id,
            )
        )

    if positions != set(range(1, len(episodes) + 1)):
        raise ValueError("Verified bundle episode positions are not contiguous.")
    if len({item["field_id"] for item in fields}) != len(fields):
        raise ValueError("Metadata translation inventory contains duplicate fields.")

    pending_count = sum(
        item["status"] == "pending_translation" for item in fields
    )
    missing_count = len(fields) - pending_count
    plan = {
        "schema_version": 1,
        "plan_type": "metadata_translation_inventory",
        "status": "prepared",
        "work_id": work_id,
        "source_locale": "ja-JP",
        "target_locale": "zh-CN",
        "field_count": len(fields),
        "pending_count": pending_count,
        "missing_count": missing_count,
        "fields": fields,
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical_json_bytes(plan)).hexdigest()
    return plan


def verify_metadata_translation_plan(plan: dict) -> str:
    """Validate inventory structure and return its canonical digest."""
    if not isinstance(plan, dict) or set(plan) != _PLAN_FIELDS:
        raise ValueError("Metadata translation plan fields do not match schema.")
    if (
        isinstance(plan.get("schema_version"), bool)
        or not isinstance(plan.get("schema_version"), int)
        or plan.get("schema_version") != 1
        or plan.get("plan_type") != "metadata_translation_inventory"
        or plan.get("status") != "prepared"
        or plan.get("source_locale") != "ja-JP"
        or plan.get("target_locale") != "zh-CN"
        or not isinstance(plan.get("work_id"), str)
        or not isinstance(plan.get("fields"), list)
        or isinstance(plan.get("field_count"), bool)
        or not isinstance(plan.get("field_count"), int)
        or plan.get("field_count") != len(plan["fields"])
    ):
        raise ValueError("Metadata translation plan header is invalid.")

    field_ids = set()
    pending_count = 0
    missing_count = 0
    for item in plan["fields"]:
        expected_fields = {
            "field_id",
            "entity_kind",
            "entity_id",
            "field_name",
            "source_value",
            "source_sha256",
            "source_version_id",
            "translation_value",
            "status",
        }
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ValueError("Metadata translation field has an invalid schema.")
        field_id = item.get("field_id")
        source_value = item.get("source_value")
        source_hash = item.get("source_sha256")
        if (
            not isinstance(field_id, str)
            or not field_id
            or field_id in field_ids
            or not isinstance(item.get("entity_kind"), str)
            or not isinstance(item.get("entity_id"), str)
            or not isinstance(item.get("field_name"), str)
            or not isinstance(item.get("source_version_id"), str)
            or not item["source_version_id"]
            or item.get("translation_value") is not None
        ):
            raise ValueError("Metadata translation field identity is invalid.")
        field_ids.add(field_id)
        if source_value is None:
            if source_hash is not None or item.get("status") != "missing_source":
                raise ValueError("Missing metadata source state is inconsistent.")
            missing_count += 1
        else:
            if (
                not isinstance(source_value, str)
                or not source_value.strip()
                or not isinstance(source_hash, str)
                or not _SHA256.fullmatch(source_hash)
                or _sha256_text(source_value) != source_hash
                or item.get("status") != "pending_translation"
            ):
                raise ValueError("Metadata source value failed its digest check.")
            pending_count += 1

    if (
        isinstance(plan.get("pending_count"), bool)
        or not isinstance(plan.get("pending_count"), int)
        or plan.get("pending_count") != pending_count
        or isinstance(plan.get("missing_count"), bool)
        or not isinstance(plan.get("missing_count"), int)
        or plan.get("missing_count") != missing_count
    ):
        raise ValueError("Metadata translation plan counts are inconsistent.")
    digest = hashlib.sha256(
        _canonical_json_bytes({key: value for key, value in plan.items() if key != "plan_sha256"})
    ).hexdigest()
    if (
        not isinstance(plan.get("plan_sha256"), str)
        or not _SHA256.fullmatch(plan["plan_sha256"])
        or plan["plan_sha256"] != digest
    ):
        raise ValueError("Metadata translation plan digest is invalid.")
    return digest


def _validate_translation_provenance(provenance: dict) -> dict:
    if not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_FIELDS:
        raise ValueError("Metadata translation provenance has an invalid schema.")
    origin = provenance.get("declared_origin")
    provider_id = provenance.get("provider_id")
    model_id = provenance.get("model_id")
    prompt_sha256 = provenance.get("prompt_sha256")
    recorded_at_utc = provenance.get("recorded_at_utc")
    if not isinstance(origin, str) or origin not in {"manual", "provider_export"}:
        raise ValueError("Metadata translation origin must be declared.")
    if (
        not isinstance(recorded_at_utc, str)
        or not recorded_at_utc
        or any(ord(character) < 32 for character in recorded_at_utc)
    ):
        raise ValueError("Metadata translation timestamp is invalid.")
    try:
        parsed_timestamp = datetime.fromisoformat(
            recorded_at_utc[:-1] + "+00:00"
            if recorded_at_utc.endswith("Z")
            else recorded_at_utc
        )
    except ValueError as exc:
        raise ValueError("Metadata translation timestamp is invalid.") from exc
    if parsed_timestamp.utcoffset() != timedelta(0):
        raise ValueError("Metadata translation timestamp must be UTC.")

    if origin == "manual":
        if any(value is not None for value in (provider_id, model_id, prompt_sha256)):
            raise ValueError("Manual translation provenance cannot claim a provider.")
    elif (
        not isinstance(provider_id, str)
        or not provider_id.strip()
        or provider_id != provider_id.strip()
        or any(ord(character) < 32 for character in provider_id)
        or not isinstance(model_id, str)
        or not model_id.strip()
        or model_id != model_id.strip()
        or any(ord(character) < 32 for character in model_id)
        or not isinstance(prompt_sha256, str)
        or not _SHA256.fullmatch(prompt_sha256)
    ):
        raise ValueError("Provider export provenance is incomplete.")
    return {
        "declared_origin": origin,
        "provider_id": provider_id,
        "model_id": model_id,
        "prompt_sha256": prompt_sha256,
        "recorded_at_utc": recorded_at_utc,
    }


def _validate_translation_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 100_000
        or any(
            ord(character) < 32 and character not in "\n\t"
            or ord(character) == 127
            for character in value
        )
    ):
        raise ValueError("Metadata translation value is empty or invalid.")
    return value


def create_metadata_translation_candidate(
    plan: dict,
    translations: dict,
    provenance: dict,
) -> dict:
    """Build a complete, source-bound candidate that is still pending review."""
    plan_sha256 = verify_metadata_translation_plan(plan)
    if not isinstance(translations, dict):
        raise ValueError("Metadata translations must be keyed by field ID.")
    expected_fields = [
        field for field in plan["fields"] if field["source_value"] is not None
    ]
    if not expected_fields:
        raise ValueError("Metadata candidate requires at least one source-backed field.")
    expected_ids = [field["field_id"] for field in expected_fields]
    if set(translations) != set(expected_ids):
        raise ValueError(
            "Metadata translations must cover every source-backed field exactly once."
        )
    validated_provenance = _validate_translation_provenance(provenance)
    fields = []
    for source_field in expected_fields:
        translation_value = _validate_translation_value(
            translations[source_field["field_id"]]
        )
        fields.append(
            {
                "field_id": source_field["field_id"],
                "entity_kind": source_field["entity_kind"],
                "entity_id": source_field["entity_id"],
                "field_name": source_field["field_name"],
                "source_version_id": source_field["source_version_id"],
                "source_sha256": source_field["source_sha256"],
                "source_value": source_field["source_value"],
                "translation_value": translation_value,
                "translation_sha256": _sha256_text(translation_value),
                "review_status": "pending",
            }
        )
    candidate = {
        "schema_version": 1,
        "candidate_type": "metadata_translation_candidate",
        "status": "review_pending",
        "work_id": plan["work_id"],
        "source_locale": plan["source_locale"],
        "target_locale": plan["target_locale"],
        "plan_sha256": plan_sha256,
        "field_count": len(fields),
        "missing_source_count": plan["missing_count"],
        "fields": fields,
        "translation_provenance": validated_provenance,
    }
    candidate["candidate_sha256"] = hashlib.sha256(
        _canonical_json_bytes(candidate)
    ).hexdigest()
    verify_metadata_translation_candidate(candidate, plan)
    return candidate


def verify_metadata_translation_candidate(candidate: dict, plan: dict) -> str:
    """Verify complete field coverage and source/version binding for a candidate."""
    plan_sha256 = verify_metadata_translation_plan(plan)
    if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_FIELDS:
        raise ValueError("Metadata translation candidate fields do not match schema.")
    if (
        isinstance(candidate.get("schema_version"), bool)
        or not isinstance(candidate.get("schema_version"), int)
        or candidate.get("schema_version") != 1
        or candidate.get("candidate_type") != "metadata_translation_candidate"
        or candidate.get("status") != "review_pending"
        or candidate.get("work_id") != plan["work_id"]
        or candidate.get("source_locale") != plan["source_locale"]
        or candidate.get("target_locale") != plan["target_locale"]
        or candidate.get("plan_sha256") != plan_sha256
        or isinstance(candidate.get("field_count"), bool)
        or not isinstance(candidate.get("field_count"), int)
        or not isinstance(candidate.get("fields"), list)
    ):
        raise ValueError("Metadata translation candidate header is invalid.")

    _validate_translation_provenance(candidate.get("translation_provenance"))
    expected_fields = [
        field for field in plan["fields"] if field["source_value"] is not None
    ]
    if (
        candidate["field_count"] != len(expected_fields)
        or len(candidate["fields"]) != len(expected_fields)
        or isinstance(candidate.get("missing_source_count"), bool)
        or not isinstance(candidate.get("missing_source_count"), int)
        or candidate.get("missing_source_count") != plan["missing_count"]
    ):
        raise ValueError("Metadata translation candidate coverage is invalid.")
    for candidate_field, source_field in zip(
        candidate["fields"], expected_fields
    ):
        if (
            not isinstance(candidate_field, dict)
            or set(candidate_field) != _CANDIDATE_ITEM_FIELDS
            or candidate_field.get("field_id") != source_field["field_id"]
            or candidate_field.get("entity_kind") != source_field["entity_kind"]
            or candidate_field.get("entity_id") != source_field["entity_id"]
            or candidate_field.get("field_name") != source_field["field_name"]
            or candidate_field.get("source_version_id")
            != source_field["source_version_id"]
            or candidate_field.get("source_sha256") != source_field["source_sha256"]
            or candidate_field.get("source_value") != source_field["source_value"]
            or candidate_field.get("review_status") != "pending"
        ):
            raise ValueError("Metadata candidate field is not bound to its source.")
        translation_value = _validate_translation_value(
            candidate_field.get("translation_value")
        )
        if (
            not isinstance(candidate_field.get("translation_sha256"), str)
            or not _SHA256.fullmatch(candidate_field["translation_sha256"])
            or candidate_field["translation_sha256"]
            != _sha256_text(translation_value)
        ):
            raise ValueError("Metadata candidate translation digest is invalid.")

    digest = hashlib.sha256(
        _canonical_json_bytes(
            {
                key: value
                for key, value in candidate.items()
                if key != "candidate_sha256"
            }
        )
    ).hexdigest()
    if (
        not isinstance(candidate.get("candidate_sha256"), str)
        or not _SHA256.fullmatch(candidate["candidate_sha256"])
        or candidate["candidate_sha256"] != digest
    ):
        raise ValueError("Metadata translation candidate digest is invalid.")
    return digest
