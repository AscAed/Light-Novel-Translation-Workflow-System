"""Source-bound, human-declared review records for metadata candidates."""

import hashlib
import json
import re
from datetime import datetime, timedelta

from metadata_translation import (
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TEMPLATE_FIELDS = {
    "schema_version",
    "template_type",
    "quality_rules_version",
    "quality_rules_sha256",
    "quality_criteria",
    "status",
    "work_id",
    "plan_sha256",
    "candidate_sha256",
    "field_count",
    "reviewer_id",
    "reviewed_at_utc",
    "decisions",
}
_TEMPLATE_DECISION_FIELDS = {
    "field_id",
    "source_version_id",
    "source_sha256",
    "source_value",
    "translation_sha256",
    "translation_value",
    "quality_checks",
}
_REPORT_DECISION_FIELDS = _TEMPLATE_DECISION_FIELDS | {"decision"}
_QUALITY_RULES_VERSION = "metadata-translation-semantic-v1"
_QUALITY_GUIDANCE = {
    "source_fidelity": (
        "Preserve source meaning, facts, tone, author voice, and Japanese work "
        "characteristics; add no unsupported facts."
    ),
    "completeness": (
        "Represent all reader-relevant information in this source field without "
        "omission or inference."
    ),
    "terminology": (
        "Follow applicable approved project terminology. Use not_applicable only "
        "when no approved term or reference applies."
    ),
    "naturalness": (
        "Use clear, idiomatic Chinese for this field while preserving its source "
        "register and voice."
    ),
    "localization": (
        "Convey applicable Japan-specific references or wordplay naturally "
        "without changing meaning. Choose annotation_required if a separate note "
        "is needed because this candidate schema has no note field."
    ),
}
_QUALITY_CHECKS = {
    "source_fidelity": {"pass", "fail", "uncertain"},
    "completeness": {"pass", "fail", "uncertain"},
    "terminology": {"pass", "not_applicable", "conflict", "uncertain"},
    "naturalness": {"pass", "fail", "uncertain"},
    "localization": {
        "pass",
        "not_applicable",
        "annotation_required",
        "uncertain",
    },
}
_QUALITY_FAILURES = {
    "source_fidelity": {"fail"},
    "completeness": {"fail"},
    "terminology": {"conflict"},
    "naturalness": {"fail"},
    "localization": set(),
}
_QUALITY_ESCALATIONS = {
    "source_fidelity": {"uncertain"},
    "completeness": {"uncertain"},
    "terminology": {"uncertain"},
    "naturalness": {"uncertain"},
    "localization": {"annotation_required", "uncertain"},
}
_REVIEW_FIELDS = {
    "schema_version",
    "review_type",
    "quality_rules_version",
    "quality_rules_sha256",
    "status",
    "work_id",
    "plan_sha256",
    "candidate_sha256",
    "decision_count",
    "decision_counts",
    "source_snapshot",
    "reviewer_id",
    "reviewed_at_utc",
    "decisions",
    "review_sha256",
}
_DECISIONS = {"approved", "rejected", "escalated"}


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _quality_rules_sha256() -> str:
    payload = {
        "version": _QUALITY_RULES_VERSION,
        "criteria": _QUALITY_GUIDANCE,
        "statuses": {
            name: sorted(statuses) for name, statuses in _QUALITY_CHECKS.items()
        },
        "failures": {
            name: sorted(statuses) for name, statuses in _QUALITY_FAILURES.items()
        },
        "escalations": {
            name: sorted(statuses)
            for name, statuses in _QUALITY_ESCALATIONS.items()
        },
        "decision_precedence": ["rejected", "escalated", "approved"],
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _timestamp(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("Metadata review timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ValueError("Metadata review timestamp is invalid.") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Metadata review timestamp must be UTC.")
    return value


def _reviewer_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("Metadata reviewer declaration is invalid.")
    return value


def _rationale(value: object, *, required: bool) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 5000
        or any(
            ord(character) < 32 and character not in "\n\t"
            or ord(character) == 127
            for character in value
        )
        or required and not value.strip()
    ):
        raise ValueError("Metadata review rationale is empty or invalid.")
    return value


def _verified_context(plan: dict, candidate: dict) -> tuple[str, str]:
    plan_sha256 = verify_metadata_translation_plan(plan)
    candidate_sha256 = verify_metadata_translation_candidate(candidate, plan)
    return plan_sha256, candidate_sha256


def create_metadata_translation_review_template(
    plan: dict,
    candidate: dict,
) -> dict:
    """Create a pending field-by-field human review template."""
    plan_sha256, candidate_sha256 = _verified_context(plan, candidate)
    decisions = [
        {
            "field_id": item["field_id"],
            "source_version_id": item["source_version_id"],
            "source_sha256": item["source_sha256"],
            "source_value": item["source_value"],
            "translation_sha256": item["translation_sha256"],
            "translation_value": item["translation_value"],
            "quality_checks": {
                check: {"status": "pending", "rationale": ""}
                for check in _QUALITY_CHECKS
            },
        }
        for item in candidate["fields"]
    ]
    template = {
        "schema_version": 2,
        "template_type": "metadata_translation_review_template",
        "quality_rules_version": _QUALITY_RULES_VERSION,
        "quality_rules_sha256": _quality_rules_sha256(),
        "quality_criteria": dict(_QUALITY_GUIDANCE),
        "status": "pending_review",
        "work_id": plan["work_id"],
        "plan_sha256": plan_sha256,
        "candidate_sha256": candidate_sha256,
        "field_count": len(decisions),
        "reviewer_id": None,
        "reviewed_at_utc": None,
        "decisions": decisions,
    }
    verify_metadata_translation_review_template(template, plan, candidate)
    return template


def _review_decision(quality_checks: dict) -> str:
    if any(
        quality_checks[name]["status"] in failures
        for name, failures in _QUALITY_FAILURES.items()
    ):
        return "rejected"
    if any(
        quality_checks[name]["status"] in escalations
        for name, escalations in _QUALITY_ESCALATIONS.items()
    ):
        return "escalated"
    return "approved"


def _verify_quality_checks(value: object, *, allow_pending: bool) -> dict:
    if not isinstance(value, dict) or set(value) != set(_QUALITY_CHECKS):
        raise ValueError("Metadata semantic review checks do not match the rubric.")
    verified = {}
    for check, allowed_statuses in _QUALITY_CHECKS.items():
        item = value.get(check)
        if not isinstance(item, dict) or set(item) != {"status", "rationale"}:
            raise ValueError("Metadata semantic review check has an invalid schema.")
        status = item.get("status")
        valid_statuses = allowed_statuses | ({"pending"} if allow_pending else set())
        if not isinstance(status, str) or status not in valid_statuses:
            raise ValueError("Metadata semantic review check has an invalid status.")
        rationale = _rationale(
            item.get("rationale"),
            required=status != "pending",
        )
        verified[check] = {"status": status, "rationale": rationale}
    return verified


def _verify_decisions(
    decisions: object,
    candidate: dict,
    *,
    allow_pending: bool,
    include_decision: bool,
) -> list[dict]:
    if not isinstance(decisions, list) or len(decisions) != len(candidate["fields"]):
        raise ValueError("Metadata review decisions must cover every candidate field.")
    verified = []
    for decision, candidate_field in zip(decisions, candidate["fields"]):
        expected_fields = (
            _REPORT_DECISION_FIELDS if include_decision else _TEMPLATE_DECISION_FIELDS
        )
        if not isinstance(decision, dict) or set(decision) != expected_fields:
            raise ValueError("Metadata review decision has an invalid schema.")
        if (
            decision.get("field_id") != candidate_field["field_id"]
            or decision.get("source_version_id")
            != candidate_field["source_version_id"]
            or decision.get("source_sha256") != candidate_field["source_sha256"]
            or decision.get("source_value") != candidate_field["source_value"]
            or decision.get("translation_sha256")
            != candidate_field["translation_sha256"]
            or decision.get("translation_value")
            != candidate_field["translation_value"]
        ):
            raise ValueError("Metadata review decision is not bound to its candidate.")
        quality_checks = _verify_quality_checks(
            decision.get("quality_checks"),
            allow_pending=allow_pending,
        )
        item = {
            "field_id": decision["field_id"],
            "source_version_id": decision["source_version_id"],
            "source_sha256": decision["source_sha256"],
            "source_value": decision["source_value"],
            "translation_sha256": decision["translation_sha256"],
            "translation_value": decision["translation_value"],
            "quality_checks": quality_checks,
        }
        if include_decision:
            expected_decision = _review_decision(quality_checks)
            if decision.get("decision") != expected_decision:
                raise ValueError(
                    "Metadata review decision does not match its semantic checks."
                )
            item["decision"] = expected_decision
        verified.append(item)
    return verified


def verify_metadata_translation_review_template(
    template: dict,
    plan: dict,
    candidate: dict,
) -> None:
    """Verify an editable template against its exact plan and candidate."""
    plan_sha256, candidate_sha256 = _verified_context(plan, candidate)
    if not isinstance(template, dict) or set(template) != _TEMPLATE_FIELDS:
        raise ValueError("Metadata review template fields do not match schema.")
    if (
        isinstance(template.get("schema_version"), bool)
        or not isinstance(template.get("schema_version"), int)
        or template.get("schema_version") != 2
        or template.get("template_type") != "metadata_translation_review_template"
        or template.get("quality_rules_version") != _QUALITY_RULES_VERSION
        or template.get("quality_rules_sha256") != _quality_rules_sha256()
        or template.get("quality_criteria") != _QUALITY_GUIDANCE
        or template.get("status") != "pending_review"
        or template.get("work_id") != plan["work_id"]
        or template.get("plan_sha256") != plan_sha256
        or template.get("candidate_sha256") != candidate_sha256
        or isinstance(template.get("field_count"), bool)
        or not isinstance(template.get("field_count"), int)
        or template.get("field_count") != len(candidate["fields"])
    ):
        raise ValueError("Metadata review template header is invalid.")
    _verify_decisions(
        template.get("decisions"),
        candidate,
        allow_pending=True,
        include_decision=False,
    )

    reviewer = template.get("reviewer_id")
    reviewed_at = template.get("reviewed_at_utc")
    if (reviewer is None) != (reviewed_at is None):
        raise ValueError("Reviewer and review timestamp must be provided together.")
    if reviewer is not None:
        _reviewer_id(reviewer)
        _timestamp(reviewed_at)


def finalize_metadata_translation_review(
    template: dict,
    plan: dict,
    candidate: dict,
    source_snapshot: dict,
) -> dict:
    """Validate human-declared decisions and produce an immutable review report."""
    verify_metadata_translation_review_template(template, plan, candidate)
    reviewer = _reviewer_id(template.get("reviewer_id"))
    reviewed_at = _timestamp(template.get("reviewed_at_utc"))
    decisions = _verify_decisions(
        template["decisions"],
        candidate,
        allow_pending=False,
        include_decision=False,
    )
    decisions = [
        {**item, "decision": _review_decision(item["quality_checks"])}
        for item in decisions
    ]
    if (
        not isinstance(source_snapshot, dict)
        or set(source_snapshot) != {"catalog_sha256", "manifest_sha256"}
        or any(
            not isinstance(source_snapshot.get(key), str)
            or not _SHA256.fullmatch(source_snapshot[key])
            for key in ("catalog_sha256", "manifest_sha256")
        )
    ):
        raise ValueError("Metadata review source snapshot is invalid.")
    decision_counts = {
        decision: sum(item["decision"] == decision for item in decisions)
        for decision in sorted(_DECISIONS)
    }
    status = (
        "approved"
        if decision_counts["approved"] == len(decisions)
        else "needs_resolution"
    )
    report = {
        "schema_version": 2,
        "review_type": "metadata_translation_review",
        "quality_rules_version": _QUALITY_RULES_VERSION,
        "quality_rules_sha256": _quality_rules_sha256(),
        "status": status,
        "work_id": plan["work_id"],
        "plan_sha256": template["plan_sha256"],
        "candidate_sha256": template["candidate_sha256"],
        "decision_count": len(decisions),
        "decision_counts": decision_counts,
        "source_snapshot": dict(source_snapshot),
        "reviewer_id": reviewer,
        "reviewed_at_utc": reviewed_at,
        "decisions": decisions,
    }
    report["review_sha256"] = hashlib.sha256(
        _canonical_json_bytes(report)
    ).hexdigest()
    verify_metadata_translation_review(report, plan, candidate)
    return report


def verify_metadata_translation_review(
    report: dict,
    plan: dict,
    candidate: dict,
) -> str:
    """Verify report coverage, source binding, outcome, and canonical digest."""
    plan_sha256, candidate_sha256 = _verified_context(plan, candidate)
    if not isinstance(report, dict) or set(report) != _REVIEW_FIELDS:
        raise ValueError("Metadata review report fields do not match schema.")
    if (
        isinstance(report.get("schema_version"), bool)
        or not isinstance(report.get("schema_version"), int)
        or report.get("schema_version") != 2
        or report.get("review_type") != "metadata_translation_review"
        or report.get("quality_rules_version") != _QUALITY_RULES_VERSION
        or report.get("quality_rules_sha256") != _quality_rules_sha256()
        or report.get("work_id") != plan["work_id"]
        or report.get("plan_sha256") != plan_sha256
        or report.get("candidate_sha256") != candidate_sha256
        or isinstance(report.get("decision_count"), bool)
        or not isinstance(report.get("decision_count"), int)
        or report.get("decision_count") != len(candidate["fields"])
    ):
        raise ValueError("Metadata review report header is invalid.")
    _reviewer_id(report.get("reviewer_id"))
    _timestamp(report.get("reviewed_at_utc"))
    source_snapshot = report.get("source_snapshot")
    if (
        not isinstance(source_snapshot, dict)
        or set(source_snapshot) != {"catalog_sha256", "manifest_sha256"}
        or any(
            not isinstance(source_snapshot.get(key), str)
            or not _SHA256.fullmatch(source_snapshot[key])
            for key in ("catalog_sha256", "manifest_sha256")
        )
    ):
        raise ValueError("Metadata review source snapshot is invalid.")
    decisions = _verify_decisions(
        report.get("decisions"),
        candidate,
        allow_pending=False,
        include_decision=True,
    )
    counts = {
        decision: sum(item["decision"] == decision for item in decisions)
        for decision in sorted(_DECISIONS)
    }
    expected_status = (
        "approved"
        if counts["approved"] == len(decisions)
        else "needs_resolution"
    )
    reported_counts = report.get("decision_counts")
    if (
        not isinstance(reported_counts, dict)
        or set(reported_counts) != _DECISIONS
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in reported_counts.values()
        )
        or reported_counts != counts
        or not isinstance(report.get("status"), str)
        or report.get("status") != expected_status
    ):
        raise ValueError("Metadata review outcome does not match its decisions.")
    digest = hashlib.sha256(
        _canonical_json_bytes(
            {key: value for key, value in report.items() if key != "review_sha256"}
        )
    ).hexdigest()
    if (
        not isinstance(report.get("review_sha256"), str)
        or not _SHA256.fullmatch(report["review_sha256"])
        or report["review_sha256"] != digest
    ):
        raise ValueError("Metadata review report digest is invalid.")
    return digest
