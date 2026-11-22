"""Review full-book knowledge candidates against their cited AI-edition passages."""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from book_bundles import load_verified_ai_book_bundle  # noqa: E402
from knowledge_ai_review import (  # noqa: E402
    KNOWLEDGE_REVIEW_SYSTEM_PROMPT,
    build_knowledge_review_candidates,
    candidate_paragraphs,
    render_knowledge_review_prompt,
    validate_knowledge_review_decisions,
)
from knowledge_batching import (  # noqa: E402
    BatchBudgetError,
    BatchCountError,
    SourceParagraph,
    count_message_tokens,
    load_tokenizer_json,
    plan_paragraph_batches,
    validate_batch_budget,
)
from scripts.apply_knowledge_review import (  # noqa: E402
    _MAX_INPUT_BYTES,
    _read_json_child,
    _validate_evidence,
    _validate_glossary,
    _verify_source_evidence,
)
from source_manifest import load_manifest  # noqa: E402
from source_editions import read_verified_ai_edition_bytes  # noqa: E402
from story_summary_review import (  # noqa: E402
    _candidate_inputs,
    _validate_summary_provenance,
    verify_summary_sources,
)
from utils import (  # noqa: E402
    open_regular_file,
    resolve_child_path,
    split_paragraphs,
    write_new_child_bytes_atomically,
)


_MAX_REVIEW_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REVIEW_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_PROVIDER_CALLS = 100
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_IDENTITY_FIELDS = (
    "source_snapshot_id",
    "ai_bundle_id",
    "bundle_set_relative_path",
    "bundle_set_sha256",
    "ai_bundle_relative_path",
    "ai_bundle_sha256",
    "episode_count",
)


def _canonical_json(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Knowledge review response has duplicate JSON fields.")
        result[key] = value
    return result


def _reject_non_finite(value):
    raise ValueError("Knowledge review response has a non-finite JSON value.")


def _parse_response(raw: str) -> dict:
    if not isinstance(raw, str):
        raise ValueError("Knowledge review response must be JSON text.")
    encoded = raw.encode("utf-8")
    if not encoded or len(encoded) > _MAX_REVIEW_RESPONSE_BYTES:
        raise ValueError("Knowledge review response exceeds the size limit.")
    try:
        response = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeEncodeError, json.JSONDecodeError) as exc:
        raise ValueError("Knowledge review response is invalid JSON.") from exc
    if not isinstance(response, dict):
        raise ValueError("Knowledge review response must be a JSON object.")
    return response


def _bundle_identity(bundle: dict) -> dict:
    identity = {}
    for field in _BUNDLE_IDENTITY_FIELDS:
        value = bundle.get(field)
        if field == "episode_count":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Verified book bundle has an invalid chapter count.")
        elif not isinstance(value, str) or not value:
            raise ValueError("Verified book bundle identity is incomplete.")
        identity[field] = value
    return identity


def _load_current_review_inputs(
    *,
    knowledge_root: str,
    source_root: str,
    manifest_relative_path: str,
    edition_manifest_relative_path: str,
    catalog_relative_path: str,
    checkpoint_relative_path: str,
    bundle_set_relative_path: str,
    human_root: str,
    ai_root: str,
) -> tuple[dict, dict, dict, bytes, bytes, bytes, list]:
    bundle = load_verified_ai_book_bundle(
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        checkpoint_relative_path=checkpoint_relative_path,
        bundle_set_relative_path=bundle_set_relative_path,
        human_root=human_root,
        ai_root=ai_root,
        manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
    )
    if bundle.get("status") != "verified":
        raise ValueError("Current AI book bundle is not verified.")
    bundle_identity = _bundle_identity(bundle)

    glossary_bytes, glossary = _read_json_child(
        knowledge_root,
        "Glossary_draft.json",
    )
    if not isinstance(glossary, dict):
        raise ValueError("Knowledge glossary candidate must be an object.")
    if glossary:
        glossary = _validate_glossary(glossary)
    summary_bytes, summary, provenance_bytes, provenance, source_provenance = (
        _candidate_inputs(knowledge_root)
    )
    if len(provenance_bytes) > _MAX_INPUT_BYTES:
        raise ValueError("Knowledge provenance exceeds the review size limit.")
    if source_provenance.get("book_bundle") != bundle_identity:
        raise ValueError("Knowledge candidates belong to a different AI book bundle.")

    coverage = provenance.get("input_coverage")
    if (
        not isinstance(coverage, dict)
        or coverage.get("scope") != "all_configured_chapters"
        or coverage.get("complete_for_configured_chapters") is not True
        or coverage.get("configured_chapter_count") != bundle_identity["episode_count"]
        or coverage.get("included_chapter_count") != bundle_identity["episode_count"]
        or len(source_provenance["source_files"])
        != bundle_identity["episode_count"]
    ):
        raise ValueError("Knowledge candidates do not cover the current full book.")

    episodes_by_input = bundle.get("episodes_by_source_input_file")
    if (
        not isinstance(episodes_by_input, dict)
        or len(episodes_by_input) != bundle_identity["episode_count"]
    ):
        raise ValueError("Verified AI book bundle has an invalid chapter map.")
    source_input_map = {}
    episodes_by_position = {}
    for source_input_file, episode in episodes_by_input.items():
        if (
            not isinstance(source_input_file, str)
            or not isinstance(episode, dict)
            or episode.get("source_input_file") != source_input_file
            or not isinstance(episode.get("source_file"), str)
            or not isinstance(episode.get("source_text"), str)
            or isinstance(episode.get("position"), bool)
            or not isinstance(episode.get("position"), int)
            or episode["position"] in episodes_by_position
        ):
            raise ValueError("Verified AI book bundle has a malformed chapter.")
        episodes_by_position[episode["position"]] = (
            source_input_file,
            episode,
        )
        source_input_map[episode["source_file"]] = {
            "source_version_id": episode.get("source_version_id"),
            "source_input_file": source_input_file,
            "source_sha256": episode.get("source_sha256"),
        }
    if set(episodes_by_position) != set(
        range(1, bundle_identity["episode_count"] + 1)
    ):
        raise ValueError("Verified AI book bundle chapter positions are incomplete.")

    paragraphs_by_id = {}
    for source in source_provenance["source_files"]:
        source_index = source.get("source_index")
        if (
            isinstance(source_index, bool)
            or not isinstance(source_index, int)
            or source_index not in episodes_by_position
        ):
            raise ValueError("Knowledge provenance has an invalid full-book order.")
        source_input_file, episode = episodes_by_position[source_index]
        if (
            source.get("filename") != episode["source_file"]
            or source.get("source_input_file") != source_input_file
            or source.get("source_version_id") != episode.get("source_version_id")
        ):
            raise ValueError("Knowledge provenance does not match the current chapter map.")
        source_bytes = read_verified_ai_edition_bytes(
            ai_root,
            source_input_file,
            episode["source_sha256"],
        )
        source_text = source_bytes.decode("utf-8").replace(
            "\r\n", "\n"
        ).replace("\r", "\n")
        if (
            hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            != source["source_sha256"]
        ):
            raise ValueError("Knowledge provenance source digest is stale.")
        paragraphs = split_paragraphs(source_text)
        if len(paragraphs) != source.get("included_paragraph_count"):
            raise ValueError("Knowledge provenance paragraph coverage is incomplete.")
        for paragraph_index, text in enumerate(paragraphs, start=1):
            source_id = f"C{source_index:04d}P{paragraph_index:05d}"
            paragraphs_by_id[source_id] = SourceParagraph(
                source_id=source_id,
                filename=source["filename"],
                paragraph_index=paragraph_index,
                text=text,
            )

    if glossary:
        evidence_by_source = _validate_evidence(provenance, glossary)
        _verify_source_evidence(
            source_root,
            load_manifest(resolve_child_path(source_root, manifest_relative_path)),
            provenance,
            evidence_by_source,
            source_input_root=ai_root,
            source_input_map=source_input_map,
        )
    verify_summary_sources(
        source_root,
        manifest_relative_path,
        source_provenance,
        source_input_root=ai_root,
        source_input_map=source_input_map,
    )

    token_budget = provenance.get("token_budget")
    if not isinstance(token_budget, dict):
        raise ValueError("Knowledge candidates have no bounded extraction record.")
    claims_by_category = {
        category: []
        for category in ("summary", "worldbuilding", "narrative_voice")
    }
    for claim in provenance.get("claim_evidence", []):
        claims_by_category[claim["category"]].append(claim)
    synthesized = token_budget.get("synthesis_status") == "completed"
    from scripts.auto_extract_knowledge import _render_full_book_summary

    expected_summary = (
        "# Story Summary (Draft)\n\n"
        + _render_full_book_summary(claims_by_category, synthesized=synthesized)
    )
    normalized_summary = summary.replace("\r\n", "\n").replace("\r", "\n")
    normalized_expected_summary = expected_summary.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")
    if normalized_summary != normalized_expected_summary:
        raise ValueError(
            "Summary draft does not match the evidenced claim rendering "
            f"(actual_sha256={hashlib.sha256(normalized_summary.encode('utf-8')).hexdigest()}, "
            f"expected_sha256={hashlib.sha256(normalized_expected_summary.encode('utf-8')).hexdigest()}, "
            f"claim_count={sum(map(len, claims_by_category.values()))}, "
            f"synthesis_applied={synthesized}, "
            f"actual_prefix={normalized_summary[:160]!r}, "
            f"expected_prefix={normalized_expected_summary[:160]!r})."
        )

    candidate_provenance = {
        **source_provenance,
        "glossary_evidence": provenance.get("glossary_evidence"),
    }
    candidates = build_knowledge_review_candidates(
        glossary,
        candidate_provenance,
        paragraphs_by_id,
    )
    return (
        bundle_identity,
        glossary,
        source_provenance,
        glossary_bytes,
        summary_bytes,
        provenance_bytes,
        candidates,
    )


def _review_plan(
    candidates: list[dict],
    *,
    model_id: str,
    tokenizer,
    tokenizer_sha256: str,
    context_window_tokens: int,
    max_output_tokens: int,
    safety_margin_tokens: int,
    message_overhead_tokens: int,
    max_provider_calls: int,
) -> dict:
    input_token_limit = validate_batch_budget(
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        message_overhead_tokens=message_overhead_tokens,
    )
    paragraphs = candidate_paragraphs(candidates)
    batches = plan_paragraph_batches(
        paragraphs,
        tokenizer=tokenizer,
        system_text=KNOWLEDGE_REVIEW_SYSTEM_PROMPT,
        render_user_text=render_knowledge_review_prompt,
        input_token_limit=input_token_limit,
        message_overhead_tokens=message_overhead_tokens,
        max_provider_calls=max_provider_calls,
    )
    batch_tokens = [
        count_message_tokens(
            tokenizer,
            KNOWLEDGE_REVIEW_SYSTEM_PROMPT,
            batch["user_text"],
        )
        + message_overhead_tokens
        for batch in batches
    ]
    return {
        "model_id": model_id,
        "tokenizer_sha256": tokenizer_sha256,
        "context_window_tokens": context_window_tokens,
        "max_output_tokens_per_request": max_output_tokens,
        "safety_margin_tokens": safety_margin_tokens,
        "message_overhead_tokens": message_overhead_tokens,
        "max_input_tokens_per_request": input_token_limit,
        "review_candidate_count": len(candidates),
        "review_batch_count": len(batches),
        "minimum_provider_calls": len(batches),
        "estimated_review_input_tokens": sum(batch_tokens),
        "largest_estimated_batch_input_tokens": max(batch_tokens),
        "max_provider_calls": max_provider_calls,
        "batches": batches,
    }


def _run_identity(
    *,
    glossary_bytes: bytes,
    summary_bytes: bytes,
    provenance_bytes: bytes,
    bundle_identity: dict,
    plan: dict,
    provider_id: str,
    provider_fingerprint: str,
) -> str:
    identity = {
        "candidate_glossary_sha256": hashlib.sha256(glossary_bytes).hexdigest(),
        "candidate_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "candidate_provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
        "book_bundle": bundle_identity,
        "model_id": plan["model_id"],
        "provider_id": provider_id,
        "provider_fingerprint": provider_fingerprint,
        "tokenizer_sha256": plan["tokenizer_sha256"],
        "context_window_tokens": plan["context_window_tokens"],
        "max_output_tokens_per_request": plan["max_output_tokens_per_request"],
        "safety_margin_tokens": plan["safety_margin_tokens"],
        "message_overhead_tokens": plan["message_overhead_tokens"],
        "max_provider_calls": plan["max_provider_calls"],
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _checkpoint_filename(run_id: str, batch_index: int) -> str:
    return f".knowledge-ai-review-{run_id}-batch-{batch_index:04d}.json"


def _review_budget(plan: dict) -> dict:
    return {
        key: plan[key]
        for key in (
            "tokenizer_sha256",
            "context_window_tokens",
            "max_output_tokens_per_request",
            "safety_margin_tokens",
            "message_overhead_tokens",
            "max_input_tokens_per_request",
            "minimum_provider_calls",
            "estimated_review_input_tokens",
            "largest_estimated_batch_input_tokens",
        )
    }


def _load_checkpoint(
    knowledge_root: str,
    filename: str,
    *,
    run_id: str,
    batch_index: int,
    batch_input_sha256: str,
    provider_id: str,
    model_id: str,
    tokenizer_sha256: str,
    expected_input_tokens: int,
    max_input_tokens: int,
    candidates: list[dict],
) -> dict | None:
    path = resolve_child_path(knowledge_root, filename, allow_missing=True)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("Knowledge review checkpoint must be a regular file.")
    _, checkpoint = _read_json_child(knowledge_root, filename)
    expected_fields = {
        "schema_version",
        "run_id",
        "batch_index",
        "batch_input_sha256",
        "provider_id",
        "model_id",
        "tokenizer_sha256",
        "estimated_input_tokens",
        "reported_prompt_tokens",
        "response_sha256",
        "decisions",
    }
    if (
        set(checkpoint) != expected_fields
        or type(checkpoint.get("schema_version")) is not int
        or checkpoint["schema_version"] != 1
        or checkpoint.get("run_id") != run_id
        or isinstance(checkpoint.get("batch_index"), bool)
        or not isinstance(checkpoint.get("batch_index"), int)
        or checkpoint.get("batch_index") != batch_index
        or checkpoint.get("batch_input_sha256") != batch_input_sha256
        or checkpoint.get("provider_id") != provider_id
        or checkpoint.get("model_id") != model_id
        or checkpoint.get("tokenizer_sha256") != tokenizer_sha256
        or isinstance(checkpoint.get("estimated_input_tokens"), bool)
        or not isinstance(checkpoint.get("estimated_input_tokens"), int)
        or checkpoint.get("estimated_input_tokens") != expected_input_tokens
        or (
            checkpoint.get("reported_prompt_tokens") is not None
            and (
                isinstance(checkpoint.get("reported_prompt_tokens"), bool)
                or not isinstance(checkpoint.get("reported_prompt_tokens"), int)
                or checkpoint["reported_prompt_tokens"] < 0
                or checkpoint["reported_prompt_tokens"] > max_input_tokens
            )
        )
        or not isinstance(checkpoint.get("response_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(checkpoint["response_sha256"])
    ):
        raise ValueError("Knowledge review checkpoint identity does not match.")
    decisions = validate_knowledge_review_decisions(
        {"decisions": checkpoint["decisions"]},
        candidates,
    )
    checkpoint["decisions"] = decisions
    return checkpoint


def _validate_existing_report(
    knowledge_root: str,
    filename: str,
    existing: dict,
    *,
    run_id: str,
    plan: dict,
    candidates: list[dict],
    bundle_identity: dict,
    glossary_bytes: bytes,
    summary_bytes: bytes,
    provenance_bytes: bytes,
    provider_id: str,
    provider_fingerprint: str,
) -> dict:
    expected_fields = {
        "schema_version",
        "artifact_status",
        "run_id",
        "status",
        "automatic_publication",
        "review_scope",
        "candidate_completeness_assessed",
        "independent_reviewer_established",
        "candidate_count",
        "decision_counts",
        "reviewer",
        "provider_fingerprint",
        "candidate_artifacts",
        "book_bundle",
        "budget",
        "provider_call_count",
        "provider_calls_made_this_run",
        "provider_calls_reused_from_checkpoints",
        "batches",
        "decisions",
        "reviewed_at_utc",
    }
    if (
        not isinstance(existing, dict)
        or set(existing) != expected_fields
        or type(existing.get("schema_version")) is not int
        or existing["schema_version"] != 1
    ):
        raise ValueError("Existing knowledge review output does not match.")

    checkpoint_decisions = []
    expected_batches = []
    for batch_index, batch in enumerate(plan["batches"], start=1):
        batch_candidates = [
            json.loads(paragraph.text) for paragraph in batch["paragraphs"]
        ]
        batch_input_sha256 = hashlib.sha256(
            batch["user_text"].encode("utf-8")
        ).hexdigest()
        checkpoint = _load_checkpoint(
            knowledge_root,
            _checkpoint_filename(run_id, batch_index),
            run_id=run_id,
            batch_index=batch_index,
            batch_input_sha256=batch_input_sha256,
            provider_id=provider_id,
            model_id=plan["model_id"],
            tokenizer_sha256=plan["tokenizer_sha256"],
            expected_input_tokens=batch["input_tokens"],
            max_input_tokens=plan["max_input_tokens_per_request"],
            candidates=batch_candidates,
        )
        if checkpoint is None:
            raise ValueError(
                "Existing knowledge review output has no matching checkpoint."
            )
        checkpoint_decisions.extend(checkpoint["decisions"])
        expected_batches.append(
            {
                "batch_index": batch_index,
                "candidate_count": len(batch_candidates),
                "input_sha256": batch_input_sha256,
                "response_sha256": checkpoint["response_sha256"],
                "estimated_input_tokens": batch["input_tokens"],
                "reported_prompt_tokens": checkpoint["reported_prompt_tokens"],
            }
        )

    checkpoint_decisions = validate_knowledge_review_decisions(
        {"decisions": checkpoint_decisions},
        candidates,
    )
    report_decisions = validate_knowledge_review_decisions(
        {"decisions": existing.get("decisions")},
        candidates,
    )
    if report_decisions != checkpoint_decisions:
        raise ValueError(
            "Existing knowledge review decisions do not match their checkpoints."
        )

    decision_counts = {
        decision: sum(item["decision"] == decision for item in report_decisions)
        for decision in ("approved", "rejected", "escalated")
    }
    expected_status = (
        "all_candidates_approved"
        if decision_counts["approved"] == len(candidates)
        else "resolution_required"
    )
    batch_count = len(plan["batches"])
    made = existing.get("provider_calls_made_this_run")
    reused = existing.get("provider_calls_reused_from_checkpoints")
    timestamp = existing.get("reviewed_at_utc")
    try:
        parsed_timestamp = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as exc:
        raise ValueError(
            "Existing knowledge review output has an invalid timestamp."
        ) from exc
    if (
        parsed_timestamp.tzinfo is None
        or parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp)
        or isinstance(existing.get("candidate_count"), bool)
        or not isinstance(existing.get("candidate_count"), int)
        or existing.get("status") != expected_status
        or existing.get("automatic_publication") != "not_performed"
        or existing.get("review_scope") != "candidate_evidence_only"
        or existing.get("candidate_completeness_assessed") is not False
        or existing.get("independent_reviewer_established") is not False
        or existing.get("candidate_count") != len(candidates)
        or _canonical_json(existing.get("decision_counts"))
        != _canonical_json(decision_counts)
        or any(
            type(existing["decision_counts"].get(key)) is not int
            for key in decision_counts
        )
        or _canonical_json(existing.get("reviewer"))
        != _canonical_json(
            {
                "provider_id": provider_id,
                "model_id": plan["model_id"],
                "review_id": run_id[:24],
            }
        )
        or existing.get("provider_fingerprint") != provider_fingerprint
        or _canonical_json(existing.get("candidate_artifacts"))
        != _canonical_json(
            {
                "glossary_sha256": hashlib.sha256(glossary_bytes).hexdigest(),
                "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
            }
        )
        or _canonical_json(existing.get("book_bundle"))
        != _canonical_json(bundle_identity)
        or _canonical_json(existing.get("budget"))
        != _canonical_json(_review_budget(plan))
        or isinstance(existing.get("provider_call_count"), bool)
        or not isinstance(existing.get("provider_call_count"), int)
        or existing.get("provider_call_count") != batch_count
        or _canonical_json(existing.get("batches"))
        != _canonical_json(expected_batches)
        or type(made) is not int
        or type(reused) is not int
        or made < 0
        or reused < 0
        or made + reused != batch_count
    ):
        raise ValueError(
            "Existing knowledge review output does not match its checkpoints."
        )
    return {
        "status": "already_reviewed",
        "output": filename,
        "candidate_count": len(candidates),
        "decision_counts": decision_counts,
        "provider_calls_made": 0,
        "provider_calls_reused": batch_count,
    }


async def _execute_review(
    *,
    knowledge_root: str,
    plan: dict,
    candidates: list[dict],
    bundle_identity: dict,
    glossary_bytes: bytes,
    summary_bytes: bytes,
    provenance_bytes: bytes,
    provider_id: str,
    provider_fingerprint: str,
    client,
) -> dict:
    run_id = _run_identity(
        glossary_bytes=glossary_bytes,
        summary_bytes=summary_bytes,
        provenance_bytes=provenance_bytes,
        bundle_identity=bundle_identity,
        plan=plan,
        provider_id=provider_id,
        provider_fingerprint=provider_fingerprint,
    )
    output_filename = f"KNOWLEDGE_AI_REVIEW_{run_id[:24]}.json"
    output_path = resolve_child_path(
        knowledge_root,
        output_filename,
        allow_missing=True,
    )
    if output_path.exists() or output_path.is_symlink():
        if output_path.is_symlink() or not output_path.is_file():
            raise ValueError("Existing knowledge review output is not a regular file.")
        with open_regular_file(output_path, binary=True) as stream:
            existing_bytes = stream.read(_MAX_REVIEW_ARTIFACT_BYTES + 1)
        if len(existing_bytes) > _MAX_REVIEW_ARTIFACT_BYTES:
            raise ValueError("Existing knowledge review output exceeds the size limit.")
        existing = json.loads(
            existing_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        return _validate_existing_report(
            knowledge_root,
            output_filename,
            existing,
            run_id=run_id,
            plan=plan,
            candidates=candidates,
            bundle_identity=bundle_identity,
            glossary_bytes=glossary_bytes,
            summary_bytes=summary_bytes,
            provenance_bytes=provenance_bytes,
            provider_id=provider_id,
            provider_fingerprint=provider_fingerprint,
        )

    all_decisions = []
    batch_records = []
    calls_made = 0
    calls_reused = 0
    for batch_index, batch in enumerate(plan["batches"], start=1):
        batch_candidates = [
            json.loads(paragraph.text) for paragraph in batch["paragraphs"]
        ]
        batch_input_sha256 = hashlib.sha256(
            batch["user_text"].encode("utf-8")
        ).hexdigest()
        checkpoint_filename = _checkpoint_filename(run_id, batch_index)
        checkpoint = _load_checkpoint(
            knowledge_root,
            checkpoint_filename,
            run_id=run_id,
            batch_index=batch_index,
            batch_input_sha256=batch_input_sha256,
            provider_id=provider_id,
            model_id=plan["model_id"],
            tokenizer_sha256=plan["tokenizer_sha256"],
            expected_input_tokens=batch["input_tokens"],
            max_input_tokens=plan["max_input_tokens_per_request"],
            candidates=batch_candidates,
        )
        if checkpoint is None:
            response = await client.chat.completions.create(
                model=plan["model_id"],
                messages=[
                    {
                        "role": "system",
                        "content": KNOWLEDGE_REVIEW_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": batch["user_text"]},
                ],
                response_format={"type": "json_object"},
                max_tokens=plan["max_output_tokens_per_request"],
            )
            choices = getattr(response, "choices", None)
            if not isinstance(choices, (list, tuple)) or len(choices) != 1:
                raise ValueError("Knowledge review provider returned an invalid response.")
            choice = choices[0]
            if getattr(choice, "finish_reason", None) in {"length", "content_filter"}:
                raise ValueError(
                    "Knowledge review response was truncated or content-filtered."
                )
            response_text = getattr(
                getattr(choice, "message", None),
                "content",
                None,
            )
            response_json = _parse_response(response_text)
            decisions = validate_knowledge_review_decisions(
                response_json,
                batch_candidates,
            )
            usage = getattr(response, "usage", None)
            reported_prompt_tokens = getattr(usage, "prompt_tokens", None)
            if reported_prompt_tokens is not None and (
                isinstance(reported_prompt_tokens, bool)
                or not isinstance(reported_prompt_tokens, int)
                or reported_prompt_tokens < 0
                or reported_prompt_tokens > plan["max_input_tokens_per_request"]
            ):
                raise BatchBudgetError(
                    "Provider-reported review input exceeds the configured context budget."
                )
            checkpoint = {
                "schema_version": 1,
                "run_id": run_id,
                "batch_index": batch_index,
                "batch_input_sha256": batch_input_sha256,
                "provider_id": provider_id,
                "model_id": plan["model_id"],
                "tokenizer_sha256": plan["tokenizer_sha256"],
                "estimated_input_tokens": batch["input_tokens"],
                "reported_prompt_tokens": reported_prompt_tokens,
                "response_sha256": hashlib.sha256(
                    response_text.encode("utf-8")
                ).hexdigest(),
                "decisions": decisions,
            }
            checkpoint_bytes = _canonical_json(checkpoint)
            if len(checkpoint_bytes) > _MAX_REVIEW_ARTIFACT_BYTES:
                raise ValueError("Knowledge review checkpoint exceeds the size limit.")
            try:
                write_new_child_bytes_atomically(
                    knowledge_root,
                    checkpoint_filename,
                    checkpoint_bytes,
                )
            except FileExistsError:
                checkpoint = _load_checkpoint(
                    knowledge_root,
                    checkpoint_filename,
                    run_id=run_id,
                    batch_index=batch_index,
                    batch_input_sha256=batch_input_sha256,
                    provider_id=provider_id,
                    model_id=plan["model_id"],
                    tokenizer_sha256=plan["tokenizer_sha256"],
                    expected_input_tokens=batch["input_tokens"],
                    max_input_tokens=plan["max_input_tokens_per_request"],
                    candidates=batch_candidates,
                )
                if checkpoint is None:
                    raise
                calls_reused += 1
            else:
                calls_made += 1
        else:
            calls_reused += 1

        all_decisions.extend(checkpoint["decisions"])
        batch_records.append(
            {
                "batch_index": batch_index,
                "candidate_count": len(batch_candidates),
                "input_sha256": batch_input_sha256,
                "response_sha256": checkpoint["response_sha256"],
                "estimated_input_tokens": batch["input_tokens"],
                "reported_prompt_tokens": checkpoint["reported_prompt_tokens"],
            }
        )

    all_decisions = validate_knowledge_review_decisions(
        {"decisions": all_decisions},
        candidates,
    )
    counts = {
        decision: sum(
            item["decision"] == decision
            for item in all_decisions
        )
        for decision in ("approved", "rejected", "escalated")
    }
    report = {
        "schema_version": 1,
        "artifact_status": "complete",
        "run_id": run_id,
        "status": (
            "all_candidates_approved"
            if counts["approved"] == len(candidates)
            else "resolution_required"
        ),
        "automatic_publication": "not_performed",
        "review_scope": "candidate_evidence_only",
        "candidate_completeness_assessed": False,
        "independent_reviewer_established": False,
        "candidate_count": len(candidates),
        "decision_counts": counts,
        "reviewer": {
            "provider_id": provider_id,
            "model_id": plan["model_id"],
            "review_id": run_id[:24],
        },
        "provider_fingerprint": provider_fingerprint,
        "candidate_artifacts": {
            "glossary_sha256": hashlib.sha256(glossary_bytes).hexdigest(),
            "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
        },
        "book_bundle": bundle_identity,
        "budget": _review_budget(plan),
        "provider_call_count": len(batch_records),
        "provider_calls_made_this_run": calls_made,
        "provider_calls_reused_from_checkpoints": calls_reused,
        "batches": batch_records,
        "decisions": all_decisions,
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    report_bytes = _canonical_json(report)
    if len(report_bytes) > _MAX_REVIEW_ARTIFACT_BYTES:
        raise ValueError("Knowledge AI review report exceeds the size limit.")
    write_new_child_bytes_atomically(
        knowledge_root,
        output_filename,
        report_bytes,
    )
    return {
        "status": report["status"],
        "output": output_filename,
        "candidate_count": len(candidates),
        "decision_counts": counts,
        "provider_calls_made": calls_made,
        "provider_calls_reused": calls_reused,
    }


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight or explicitly run evidence-bound semantic review for "
            "full-book knowledge candidates."
        )
    )
    parser.add_argument("--knowledge-root", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default="source_editions_manifest.json",
    )
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--bundle-set", required=True)
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument("--tokenizer-json", required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--context-window-tokens", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--safety-margin-tokens", type=int, required=True)
    parser.add_argument("--message-overhead-tokens", type=int, required=True)
    parser.add_argument("--max-provider-calls", type=int, default=_MAX_PROVIDER_CALLS)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Load configured credentials and call the authorized review provider.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    try:
        tokenizer, tokenizer_sha256 = load_tokenizer_json(args.tokenizer_json)
        model_id = args.model_id
        provider_id = "caller-declared"
        provider_fingerprint = "not-resolved"
        client = None
        if args.execute:
            from pipeline import (
                Config,
                get_api_key,
                get_openai_client,
                get_primary_provider_route,
                resolve_openai_client_settings,
            )

            Config.load_config()
            configured_model = Config.PROOFREAD_MODEL
            if (
                not isinstance(configured_model, str)
                or not configured_model.strip()
                or (
                    model_id is not None
                    and model_id != configured_model
                )
            ):
                raise ValueError(
                    "Execution model must match the configured PROOFREAD_MODEL."
                )
            model_id = configured_model
            route = get_primary_provider_route(model_id)
            api_key = get_api_key(route.api_key_env)
            categories = {"source_text", "book_knowledge"}
            resolve_openai_client_settings(
                route.base_url,
                api_key,
                provider_id=route.provider_id,
                data_categories=categories,
            )
            client = get_openai_client(
                route.base_url,
                api_key,
                provider_id=route.provider_id,
                data_categories=categories,
            )
            from ai_translation_review import _provider_fingerprint

            provider_id = route.provider_id
            provider_fingerprint = _provider_fingerprint(model_id)
            model_id = route.request_model or configured_model
        elif not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("--model-id is required unless --execute is used.")

        (
            bundle_identity,
            _,
            _,
            glossary_bytes,
            summary_bytes,
            provenance_bytes,
            candidates,
        ) = _load_current_review_inputs(
            knowledge_root=args.knowledge_root,
            source_root=args.source_root,
            manifest_relative_path=args.manifest,
            edition_manifest_relative_path=args.edition_manifest,
            catalog_relative_path=args.catalog,
            checkpoint_relative_path=args.checkpoint,
            bundle_set_relative_path=args.bundle_set,
            human_root=args.human_root,
            ai_root=args.ai_root,
        )
        plan = _review_plan(
            candidates,
            model_id=model_id,
            tokenizer=tokenizer,
            tokenizer_sha256=tokenizer_sha256,
            context_window_tokens=args.context_window_tokens,
            max_output_tokens=args.max_output_tokens,
            safety_margin_tokens=args.safety_margin_tokens,
            message_overhead_tokens=args.message_overhead_tokens,
            max_provider_calls=args.max_provider_calls,
        )
        if not args.execute:
            output = {
                "status": "plan_ready",
                "model_id": model_id,
                "model_id_source": "caller_declared_not_verified",
                "book_bundle": bundle_identity,
                "review_candidate_count": plan["review_candidate_count"],
                "review_batch_count": plan["review_batch_count"],
                "minimum_provider_calls": plan["minimum_provider_calls"],
                "estimated_review_input_tokens": plan[
                    "estimated_review_input_tokens"
                ],
                "largest_estimated_batch_input_tokens": plan[
                    "largest_estimated_batch_input_tokens"
                ],
                "provider_calls_made": 0,
                "files_written": 0,
                "source_passages_included": False,
            }
        else:
            result = asyncio.run(
                _execute_review(
                    knowledge_root=args.knowledge_root,
                    plan=plan,
                    candidates=candidates,
                    bundle_identity=bundle_identity,
                    glossary_bytes=glossary_bytes,
                    summary_bytes=summary_bytes,
                    provenance_bytes=provenance_bytes,
                    provider_id=provider_id,
                    provider_fingerprint=provider_fingerprint,
                    client=client,
                )
            )
            output = {
                **result,
                "book_bundle": bundle_identity,
                "automatic_publication": "not_performed",
            }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        BatchBudgetError,
        BatchCountError,
        OSError,
        UnicodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
