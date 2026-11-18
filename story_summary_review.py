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
    verify_current_normalized_source_metadata,
)
from source_editions import read_verified_ai_edition_bytes
from utils import (
    open_regular_file,
    resolve_child_path,
    resolve_relative_path,
    write_new_child_text,
)


_MAX_INPUT_BYTES = 16 * 1024 * 1024
_MAX_BUNDLE_BYTES = 32 * 1024 * 1024
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_COUNT = 1000
_MAX_TOTAL_SOURCE_BYTES = 128 * 1024 * 1024
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


def _validate_claim_evidence_records(
    records,
    *,
    paragraph_locations,
    source_ids_by_batch,
    allowed_batch_ids,
):
    if not isinstance(records, list) or len(records) > 50000:
        raise ValueError("Summary provenance has malformed claim evidence.")
    normalized_claims = []
    seen_claim_ids = set()
    summary_claim_count = 0
    for item in records:
        if not isinstance(item, dict) or set(item) != {
            "claim_id",
            "category",
            "batch_id",
            "claim_text",
            "claim_sha256",
            "evidence",
        }:
            raise ValueError("Summary provenance has malformed claim evidence.")
        claim_id = _require_text(item.get("claim_id"), "claim_id", maximum=128)
        category = item.get("category")
        batch_id = item.get("batch_id")
        claim_text = _require_text(
            item.get("claim_text"), "claim_text", maximum=4000
        )
        if (
            claim_id in seen_claim_ids
            or not isinstance(category, str)
            or category not in {"summary", "worldbuilding", "narrative_voice"}
            or not isinstance(batch_id, str)
            or batch_id not in allowed_batch_ids
            or item.get("claim_sha256")
            != hashlib.sha256(claim_text.encode("utf-8")).hexdigest()
        ):
            raise ValueError("Summary provenance has invalid claim identity.")
        seen_claim_ids.add(claim_id)
        if category == "summary":
            summary_claim_count += 1
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or len(evidence) > 50:
            raise ValueError("Summary provenance has invalid claim locations.")
        normalized_evidence = []
        seen_evidence = set()
        for reference in evidence:
            if not isinstance(reference, dict) or set(reference) != {
                "source_id",
                "filename",
                "paragraph_index",
            }:
                raise ValueError("Summary provenance has invalid claim locations.")
            source_id = reference.get("source_id")
            filename = reference.get("filename")
            paragraph_index = reference.get("paragraph_index")
            if not isinstance(source_id, str):
                raise ValueError("Summary provenance has invalid claim locations.")
            expected_location = paragraph_locations.get(source_id)
            if (
                expected_location is None
                or source_id not in source_ids_by_batch[batch_id]
                or expected_location[0] != filename
                or expected_location[1] != paragraph_index
                or source_id in seen_evidence
            ):
                raise ValueError("Summary provenance has invalid claim locations.")
            seen_evidence.add(source_id)
            normalized_evidence.append(
                {
                    "source_id": source_id,
                    "filename": filename,
                    "paragraph_index": paragraph_index,
                }
            )
        normalized_claims.append(
            {
                "claim_id": claim_id,
                "category": category,
                "batch_id": batch_id,
                "claim_text": claim_text,
                "claim_sha256": item["claim_sha256"],
                "evidence": normalized_evidence,
            }
        )
    if summary_claim_count < 1:
        raise ValueError("Summary provenance has no evidenced summary claim.")
    return normalized_claims


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
            "Summary provenance must identify one to 1000 source chapters."
        )

    normalized_sources = []
    filenames = []
    source_indexes = []
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
        source_input_file = item.get("source_input_file")
        if source_input_file is not None:
            source_input_file = _require_text(
                source_input_file, "source_input_file", maximum=4096
            )
            if "\\" in source_input_file or any(
                part in {"", ".", ".."} for part in source_input_file.split("/")
            ):
                raise ValueError("Summary provenance has an unsafe AI input path.")
            normalized_sources[-1]["source_input_file"] = source_input_file
        paragraph_count = item.get("included_paragraph_count")
        if paragraph_count is not None:
            if (
                isinstance(paragraph_count, bool)
                or not isinstance(paragraph_count, int)
                or paragraph_count < 0
            ):
                raise ValueError(
                    "Summary provenance has an invalid paragraph count."
                )
            normalized_sources[-1]["included_paragraph_count"] = paragraph_count
        source_index = item.get("source_index")
        if source_index is not None:
            if (
                isinstance(source_index, bool)
                or not isinstance(source_index, int)
                or source_index < 1
            ):
                raise ValueError("Summary provenance has an invalid source index.")
            normalized_sources[-1]["source_index"] = source_index
            source_indexes.append(source_index)
        chapter_position = item.get("chapter_position")
        if chapter_position is not None:
            if (
                isinstance(chapter_position, bool)
                or not isinstance(chapter_position, int)
                or chapter_position < 1
            ):
                raise ValueError("Summary provenance has an invalid chapter position.")
            normalized_sources[-1]["chapter_position"] = chapter_position

    if (
        any(not isinstance(name, str) for name in summary_chapters)
        or summary_chapters != filenames
    ):
        raise ValueError(
            "Summary source chapters must match the provenance source-file order."
        )
    normalized = {
        "summary_source_chapters": list(summary_chapters),
        "source_files": normalized_sources,
    }
    coverage = provenance.get("input_coverage")
    if coverage is not None:
        if not isinstance(coverage, dict):
            raise ValueError("Summary provenance has malformed input coverage.")
        if coverage.get("scope") == "all_configured_chapters":
            configured_count = coverage.get("configured_chapter_count")
            included_count = coverage.get("included_chapter_count")
            input_characters = coverage.get("input_characters")
            input_character_limit = coverage.get("input_character_limit")
            if (
                coverage.get("complete_for_configured_chapters") is not True
                or isinstance(configured_count, bool)
                or not isinstance(configured_count, int)
                or configured_count != len(source_files)
                or isinstance(included_count, bool)
                or not isinstance(included_count, int)
                or included_count != len(source_files)
                or isinstance(input_characters, bool)
                or not isinstance(input_characters, int)
                or input_characters < 0
                or isinstance(input_character_limit, bool)
                or not isinstance(input_character_limit, int)
                or input_character_limit < 1
                or input_characters > input_character_limit
            ):
                raise ValueError("Summary provenance has incomplete full-book coverage.")
            normalized["input_coverage"] = {
                "scope": "all_configured_chapters",
                "complete_for_configured_chapters": True,
                "configured_chapter_count": configured_count,
                "included_chapter_count": included_count,
                "input_characters": input_characters,
                "input_character_limit": input_character_limit,
            }
        elif coverage.get("scope") == "selected_chapter":
            configured_count = coverage.get("configured_chapter_count")
            included_count = coverage.get("included_chapter_count")
            input_characters = coverage.get("input_characters")
            input_character_limit = coverage.get("input_character_limit")
            if (
                coverage.get("complete_for_configured_chapters") is not False
                or isinstance(configured_count, bool)
                or configured_count != 1
                or isinstance(included_count, bool)
                or included_count != 1
                or len(source_files) != 1
                or isinstance(input_characters, bool)
                or not isinstance(input_characters, int)
                or input_characters < 0
                or isinstance(input_character_limit, bool)
                or not isinstance(input_character_limit, int)
                or input_character_limit < 1
                or input_characters > input_character_limit
            ):
                raise ValueError("Summary provenance has invalid chapter-local coverage.")
            normalized["input_coverage"] = {
                "scope": "selected_chapter",
                "complete_for_configured_chapters": False,
                "configured_chapter_count": configured_count,
                "included_chapter_count": included_count,
                "input_characters": input_characters,
                "input_character_limit": input_character_limit,
            }

    chapter_local = provenance.get("chapter_local")
    if chapter_local is not None:
        expected_fields = {
            "episode_id",
            "position",
            "source_file",
            "source_version_id",
            "source_input_file",
            "source_sha256",
        }
        if not isinstance(chapter_local, dict) or set(chapter_local) != expected_fields:
            raise ValueError("Summary provenance has malformed chapter-local identity.")
        episode_id = _require_text(
            chapter_local.get("episode_id"), "episode_id", maximum=128
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]+", episode_id):
            raise ValueError("Summary provenance has an invalid episode ID.")
        position = chapter_local.get("position")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
        ):
            raise ValueError("Summary provenance has an invalid chapter position.")
        source_file = _require_text(
            chapter_local.get("source_file"), "chapter-local source file", maximum=4096
        )
        source_version_id = _require_text(
            chapter_local.get("source_version_id"),
            "chapter-local source version",
            maximum=256,
        )
        source_input_file = _require_text(
            chapter_local.get("source_input_file"),
            "chapter-local AI input file",
            maximum=4096,
        )
        if "\\" in source_input_file or any(
            part in {"", ".", ".."} for part in source_input_file.split("/")
        ):
            raise ValueError("Summary provenance has an unsafe chapter-local AI path.")
        source_sha256 = _require_sha256(
            chapter_local.get("source_sha256"), "chapter-local source_sha256"
        )
        if (
            normalized.get("input_coverage", {}).get("scope")
            != "selected_chapter"
            or len(normalized_sources) != 1
            or normalized_sources[0]["filename"] != source_file
            or normalized_sources[0]["source_version_id"] != source_version_id
            or normalized_sources[0].get("source_input_file") != source_input_file
            or normalized_sources[0].get("chapter_position") != position
        ):
            raise ValueError(
                "Summary chapter-local identity does not match its source coverage."
            )
        normalized["chapter_local"] = {
            "episode_id": episode_id,
            "position": position,
            "source_file": source_file,
            "source_version_id": source_version_id,
            "source_input_file": source_input_file,
            "source_sha256": source_sha256,
        }
    elif normalized.get("input_coverage", {}).get("scope") == "selected_chapter":
        raise ValueError("Summary chapter-local coverage has no bound episode identity.")

    token_budget = provenance.get("token_budget")
    batch_ids = set()
    source_ids_by_batch = {}
    paragraph_locations = {}
    synthesis_batch_ids = set()
    if token_budget is not None:
        legacy_token_fields = {
            "tokenizer_sha256",
            "context_window_tokens",
            "max_output_tokens_per_request",
            "safety_margin_tokens",
            "message_overhead_tokens",
            "max_input_tokens_per_request",
            "max_provider_calls",
            "provider_call_count",
            "total_estimated_input_tokens",
            "batches",
        }
        synthesis_token_fields = legacy_token_fields | {
            "extraction_provider_call_count",
            "synthesis_provider_call_count",
            "extraction_estimated_input_tokens",
            "synthesis_estimated_input_tokens",
            "synthesis_status",
            "synthesis_rounds",
        }
        if not isinstance(token_budget, dict):
            raise ValueError("Summary provenance has malformed token budget data.")
        token_budget_fields = frozenset(token_budget)
        if token_budget_fields not in {
            frozenset(legacy_token_fields),
            frozenset(synthesis_token_fields),
        }:
            raise ValueError("Summary provenance has malformed token budget data.")
        has_synthesis_provenance = (
            token_budget_fields == frozenset(synthesis_token_fields)
        )
        _require_sha256(token_budget.get("tokenizer_sha256"), "tokenizer_sha256")
        integer_fields = (
            "context_window_tokens",
            "max_output_tokens_per_request",
            "safety_margin_tokens",
            "message_overhead_tokens",
            "max_input_tokens_per_request",
            "max_provider_calls",
            "provider_call_count",
            "total_estimated_input_tokens",
        )
        for field_name in integer_fields:
            value = token_budget.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(
                    f"Summary provenance has an invalid {field_name}."
                )
        extraction_call_count = (
            token_budget["extraction_provider_call_count"]
            if has_synthesis_provenance
            else token_budget["provider_call_count"]
        )
        synthesis_call_count = (
            token_budget["synthesis_provider_call_count"]
            if has_synthesis_provenance
            else 0
        )
        extraction_estimated_tokens = (
            token_budget["extraction_estimated_input_tokens"]
            if has_synthesis_provenance
            else token_budget["total_estimated_input_tokens"]
        )
        synthesis_estimated_tokens = (
            token_budget["synthesis_estimated_input_tokens"]
            if has_synthesis_provenance
            else 0
        )
        for field_name, value, minimum in (
            ("extraction_provider_call_count", extraction_call_count, 1),
            ("synthesis_provider_call_count", synthesis_call_count, 0),
            ("extraction_estimated_input_tokens", extraction_estimated_tokens, 1),
            ("synthesis_estimated_input_tokens", synthesis_estimated_tokens, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(
                    f"Summary provenance has an invalid {field_name}."
                )
        if (
            token_budget["max_input_tokens_per_request"]
            != token_budget["context_window_tokens"]
            - token_budget["max_output_tokens_per_request"]
            - token_budget["safety_margin_tokens"]
            or token_budget["max_provider_calls"] > 100
            or token_budget["provider_call_count"] > token_budget["max_provider_calls"]
            or token_budget["provider_call_count"]
            != extraction_call_count + synthesis_call_count
            or source_indexes != list(range(1, len(source_files) + 1))
        ):
            raise ValueError("Summary provenance has inconsistent token budget data.")

        expected_source_ids = []
        for source in normalized_sources:
            paragraph_count = source.get("included_paragraph_count")
            if paragraph_count is None:
                raise ValueError(
                    "Token-budgeted summary sources require paragraph counts."
                )
            source_index = source.get("source_index")
            if source_index is None:
                raise ValueError(
                    "Token-budgeted summary sources require source indexes."
                )
            for paragraph_index in range(1, paragraph_count + 1):
                source_id = f"C{source_index:04d}P{paragraph_index:05d}"
                expected_source_ids.append(source_id)
                paragraph_locations[source_id] = (
                    source["filename"],
                    paragraph_index,
                )

        batches = token_budget.get("batches")
        if (
            not isinstance(batches, list)
            or not batches
            or len(batches) != extraction_call_count
        ):
            raise ValueError("Summary provenance has malformed token batches.")
        total_estimated = 0
        all_batch_source_ids = []
        for index, batch in enumerate(batches, start=1):
            expected_batch_id = f"B{index:04d}"
            if not isinstance(batch, dict) or set(batch) != {
                "batch_id",
                "source_ids",
                "estimated_input_tokens",
                "reported_prompt_tokens",
                "user_message_characters",
                "user_message_sha256",
                "response_sha256",
            }:
                raise ValueError("Summary provenance has a malformed token batch.")
            if batch.get("batch_id") != expected_batch_id:
                raise ValueError("Summary provenance has unordered token batches.")
            source_ids = batch.get("source_ids")
            estimated_tokens = batch.get("estimated_input_tokens")
            user_characters = batch.get("user_message_characters")
            reported_tokens = batch.get("reported_prompt_tokens")
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or len(source_ids) > 500
                or any(not isinstance(source_id, str) for source_id in source_ids)
                or len(set(source_ids)) != len(source_ids)
                or isinstance(estimated_tokens, bool)
                or not isinstance(estimated_tokens, int)
                or estimated_tokens < 1
                or estimated_tokens > token_budget["max_input_tokens_per_request"]
                or isinstance(user_characters, bool)
                or not isinstance(user_characters, int)
                or user_characters < 1
                or (
                    reported_tokens is not None
                    and (
                        isinstance(reported_tokens, bool)
                        or not isinstance(reported_tokens, int)
                        or reported_tokens < 0
                        or reported_tokens
                        > token_budget["max_input_tokens_per_request"]
                    )
                )
            ):
                raise ValueError("Summary provenance has invalid token batch limits.")
            _require_sha256(batch.get("user_message_sha256"), "user_message_sha256")
            _require_sha256(batch.get("response_sha256"), "response_sha256")
            batch_ids.add(expected_batch_id)
            source_ids_by_batch[expected_batch_id] = set(source_ids)
            all_batch_source_ids.extend(source_ids)
            total_estimated += estimated_tokens
        if (
            all_batch_source_ids != expected_source_ids
            or total_estimated != extraction_estimated_tokens
        ):
            raise ValueError(
                "Summary provenance token batches do not cover source paragraphs exactly."
            )
        if has_synthesis_provenance:
            candidate_records = provenance.get("batch_candidate_evidence")
            if (
                not isinstance(candidate_records, list)
                or not candidate_records
                or len(candidate_records) > 50000
            ):
                raise ValueError(
                    "Summary provenance has malformed batch candidate evidence."
                )
            candidate_evidence = {}
            for record in candidate_records:
                if not isinstance(record, dict) or set(record) != {
                    "candidate_id",
                    "evidence_ids",
                }:
                    raise ValueError(
                        "Summary provenance has malformed batch candidate evidence."
                    )
                candidate_id = _require_text(
                    record.get("candidate_id"),
                    "candidate_id",
                    maximum=256,
                )
                evidence_ids = record.get("evidence_ids")
                if (
                    candidate_id in candidate_evidence
                    or not isinstance(evidence_ids, list)
                    or not evidence_ids
                    or len(evidence_ids) > 50
                    or any(not isinstance(value, str) for value in evidence_ids)
                    or len(set(evidence_ids)) != len(evidence_ids)
                ):
                    raise ValueError(
                        "Summary provenance has malformed batch candidate evidence."
                    )
                owners = [
                    batch_id
                    for batch_id, batch_source_ids in source_ids_by_batch.items()
                    if set(evidence_ids) <= batch_source_ids
                ]
                if len(owners) != 1:
                    raise ValueError(
                        "Summary provenance candidate evidence crosses extraction batches."
                    )
                candidate_evidence[candidate_id] = set(evidence_ids)

            synthesis_rounds = token_budget["synthesis_rounds"]
            synthesis_status = token_budget["synthesis_status"]
            if not isinstance(synthesis_rounds, list):
                raise ValueError(
                    "Summary provenance has malformed synthesis rounds."
                )
            if synthesis_status == "not_required_single_batch":
                if (
                    extraction_call_count != 1
                    or synthesis_call_count != 0
                    or synthesis_rounds
                ):
                    raise ValueError(
                        "Summary provenance has inconsistent synthesis status."
                    )
            elif synthesis_status == "completed":
                if (
                    extraction_call_count < 2
                    or synthesis_call_count < 1
                    or not synthesis_rounds
                ):
                    raise ValueError(
                        "Summary provenance has incomplete synthesis records."
                    )
            else:
                raise ValueError(
                    "Summary provenance has an invalid synthesis status."
                )

            counted_synthesis_calls = 0
            total_synthesis_estimated = 0
            current_candidate_ids = list(candidate_evidence)
            all_candidate_ids = set(candidate_evidence)
            for round_index, round_record in enumerate(synthesis_rounds, start=1):
                if not isinstance(round_record, dict) or set(round_record) != {
                    "round",
                    "input_candidate_count",
                    "output_candidate_count",
                    "provider_call_count",
                    "batches",
                }:
                    raise ValueError(
                        "Summary provenance has a malformed synthesis round."
                    )
                round_batches = round_record.get("batches")
                if (
                    round_record.get("round") != round_index
                    or isinstance(round_record.get("round"), bool)
                    or round_record.get("input_candidate_count")
                    != len(current_candidate_ids)
                    or round_record.get("provider_call_count")
                    != (
                        len(round_batches)
                        if isinstance(round_batches, list)
                        else -1
                    )
                    or not isinstance(round_batches, list)
                    or not round_batches
                ):
                    raise ValueError(
                        "Summary provenance has inconsistent synthesis round counts."
                    )
                input_candidate_ids = []
                output_candidate_ids = []
                next_candidate_evidence = {}
                for batch_index, synthesis_batch in enumerate(
                    round_batches, start=1
                ):
                    expected_batch_id = (
                        f"R{round_index:03d}B{batch_index:04d}"
                    )
                    if not isinstance(synthesis_batch, dict) or set(
                        synthesis_batch
                    ) != {
                        "batch_id",
                        "input_candidate_ids",
                        "output_candidate_ids",
                        "estimated_input_tokens",
                        "reported_prompt_tokens",
                        "user_message_characters",
                        "user_message_sha256",
                        "response_sha256",
                    }:
                        raise ValueError(
                            "Summary provenance has a malformed synthesis batch."
                        )
                    input_ids = synthesis_batch.get("input_candidate_ids")
                    output_ids = synthesis_batch.get("output_candidate_ids")
                    estimated_tokens = synthesis_batch.get(
                        "estimated_input_tokens"
                    )
                    reported_tokens = synthesis_batch.get(
                        "reported_prompt_tokens"
                    )
                    user_characters = synthesis_batch.get(
                        "user_message_characters"
                    )
                    if (
                        synthesis_batch.get("batch_id") != expected_batch_id
                        or not isinstance(input_ids, list)
                        or not input_ids
                        or len(input_ids) > 500
                        or any(not isinstance(value, str) for value in input_ids)
                        or len(set(input_ids)) != len(input_ids)
                        or any(value not in candidate_evidence for value in input_ids)
                        or not isinstance(output_ids, list)
                        or not output_ids
                        or len(output_ids) > 500
                        or any(not isinstance(value, str) for value in output_ids)
                        or len(set(output_ids)) != len(output_ids)
                        or isinstance(estimated_tokens, bool)
                        or not isinstance(estimated_tokens, int)
                        or estimated_tokens < 1
                        or estimated_tokens
                        > token_budget["max_input_tokens_per_request"]
                        or isinstance(user_characters, bool)
                        or not isinstance(user_characters, int)
                        or user_characters < 1
                        or (
                            reported_tokens is not None
                            and (
                                isinstance(reported_tokens, bool)
                                or not isinstance(reported_tokens, int)
                                or reported_tokens < 0
                                or reported_tokens
                                > token_budget["max_input_tokens_per_request"]
                            )
                        )
                        or any(
                            value in all_candidate_ids
                            for value in output_ids
                        )
                    ):
                        raise ValueError(
                            "Summary provenance has invalid synthesis batch limits."
                        )
                    _require_sha256(
                        synthesis_batch.get("user_message_sha256"),
                        "synthesis user_message_sha256",
                    )
                    _require_sha256(
                        synthesis_batch.get("response_sha256"),
                        "synthesis response_sha256",
                    )
                    input_candidate_ids.extend(input_ids)
                    output_candidate_ids.extend(output_ids)
                    allowed_sources = set().union(
                        *(candidate_evidence[value] for value in input_ids)
                    )
                    source_ids_by_batch[expected_batch_id] = allowed_sources
                    synthesis_batch_ids.add(expected_batch_id)
                    for output_id in output_ids:
                        next_candidate_evidence[output_id] = allowed_sources
                    all_candidate_ids.update(output_ids)
                    total_synthesis_estimated += estimated_tokens
                    counted_synthesis_calls += 1
                if (
                    input_candidate_ids != current_candidate_ids
                    or round_record.get("output_candidate_count")
                    != len(output_candidate_ids)
                    or len(set(output_candidate_ids)) != len(output_candidate_ids)
                ):
                    raise ValueError(
                        "Summary provenance synthesis rounds do not preserve candidate lineage."
                    )
                current_candidate_ids = output_candidate_ids
                candidate_evidence = next_candidate_evidence

            if (
                counted_synthesis_calls != synthesis_call_count
                or total_synthesis_estimated != synthesis_estimated_tokens
                or extraction_estimated_tokens + synthesis_estimated_tokens
                != token_budget["total_estimated_input_tokens"]
            ):
                raise ValueError(
                    "Summary provenance synthesis token totals are inconsistent."
                )
            normalized["batch_candidate_evidence"] = candidate_records
        normalized["token_budget"] = token_budget

    claim_evidence = provenance.get("claim_evidence")
    if claim_evidence is not None:
        if not token_budget:
            raise ValueError(
                "Claim-level summary evidence requires token-batch provenance."
            )
        normalized["claim_evidence"] = _validate_claim_evidence_records(
            claim_evidence,
            paragraph_locations=paragraph_locations,
            source_ids_by_batch=source_ids_by_batch,
            allowed_batch_ids=batch_ids | synthesis_batch_ids,
        )
    batch_claim_evidence = provenance.get("batch_claim_evidence")
    if batch_claim_evidence is not None:
        if not token_budget:
            raise ValueError(
                "Batch claim evidence requires token-batch provenance."
            )
        normalized["batch_claim_evidence"] = _validate_claim_evidence_records(
            batch_claim_evidence,
            paragraph_locations=paragraph_locations,
            source_ids_by_batch=source_ids_by_batch,
            allowed_batch_ids=batch_ids,
        )
    book_bundle = provenance.get("book_bundle")
    if book_bundle is not None:
        expected_bundle_fields = {
            "source_snapshot_id",
            "ai_bundle_id",
            "bundle_set_relative_path",
            "bundle_set_sha256",
            "ai_bundle_relative_path",
            "ai_bundle_sha256",
            "episode_count",
        }
        if (
            not isinstance(book_bundle, dict)
            or set(book_bundle) != expected_bundle_fields
        ):
            raise ValueError("Summary provenance has malformed book bundle data.")
        source_snapshot_id = _require_text(
            book_bundle.get("source_snapshot_id"),
            "source_snapshot_id",
            maximum=128,
        )
        ai_bundle_id = _require_text(
            book_bundle.get("ai_bundle_id"),
            "ai_bundle_id",
            maximum=128,
        )
        for field in (
            "bundle_set_relative_path",
            "ai_bundle_relative_path",
        ):
            value = _require_text(book_bundle.get(field), field, maximum=4096)
            if "\\" in value or any(
                part in {"", ".", ".."} for part in value.split("/")
            ):
                raise ValueError("Summary provenance has an unsafe bundle path.")
        for field in ("bundle_set_sha256", "ai_bundle_sha256"):
            _require_sha256(book_bundle.get(field), field)
        episode_count = book_bundle.get("episode_count")
        coverage_scope = normalized.get("input_coverage", {}).get("scope")
        if (
            isinstance(episode_count, bool)
            or not isinstance(episode_count, int)
            or (
                episode_count != len(source_files)
                if coverage_scope != "selected_chapter"
                else episode_count < len(source_files)
            )
            or not re.fullmatch(r"source-v1-[0-9a-f]{64}", source_snapshot_id)
            or not re.fullmatch(r"ai-v1-[0-9a-f]{64}", ai_bundle_id)
        ):
            raise ValueError("Summary provenance book bundle scope is inconsistent.")
        normalized["book_bundle"] = {
            "source_snapshot_id": source_snapshot_id,
            "ai_bundle_id": ai_bundle_id,
            "bundle_set_relative_path": book_bundle[
                "bundle_set_relative_path"
            ],
            "bundle_set_sha256": book_bundle["bundle_set_sha256"],
            "ai_bundle_relative_path": book_bundle["ai_bundle_relative_path"],
            "ai_bundle_sha256": book_bundle["ai_bundle_sha256"],
            "episode_count": episode_count,
        }
    return normalized


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


def _validate_claim_evidence_text(source_provenance: dict, summary: str) -> None:
    for item in source_provenance.get("claim_evidence", []):
        if item["claim_text"] not in summary:
            raise ValueError(
                "Summary draft is missing text bound by claim-level provenance."
            )


def verify_summary_sources(
    source_root: str,
    manifest_relative_path: str,
    source_provenance: dict,
    *,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
) -> None:
    """Require summary sources to match current versions and optional AI inputs."""
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

    total_source_bytes = 0
    for source in normalized["source_files"]:
        filename = source["filename"]
        version_id = source["source_version_id"]
        artifact = verify_current_normalized_source_metadata(
            manifest, version_id
        )
        if artifact["kind"] != "normalized_source" or artifact["relative_path"] != filename:
            raise ValueError("Summary source version does not match its path.")
        current = latest.get(artifact["artifact_id"])
        if current is None or current["version_id"] != version_id:
            raise ValueError("Summary source versions are not current.")
        latest_raw = latest_raw_parent_for_normalized(manifest, current)
        if latest_raw["version_id"] not in current["parent_version_ids"]:
            raise ValueError("Summary source versions are not current.")

        if source_input_root is not None:
            source_input = (source_input_map or {}).get(filename)
            if (
                not isinstance(source_input, dict)
                or source_input.get("source_version_id") != version_id
                or artifact["content_sha256"]
                != source_input.get("source_sha256")
                or not isinstance(source_input.get("source_input_file"), str)
            ):
                raise ValueError(
                    "Summary source does not match the current AI edition map."
                )
            source_bytes = read_verified_ai_edition_bytes(
                source_input_root,
                source_input["source_input_file"],
                source_input["source_sha256"],
                max_bytes=_MAX_SOURCE_BYTES,
            )
        else:
            verify_manifest_artifact(
                source_root, manifest, latest_raw["version_id"]
            )
            source_path = resolve_relative_path(source_root, filename)
            source_bytes = _read_bounded_file(source_path, _MAX_SOURCE_BYTES)
        total_source_bytes += len(source_bytes)
        if total_source_bytes > _MAX_TOTAL_SOURCE_BYTES:
            raise ValueError(
                "Summary review sources exceed the configured total size limit."
            )
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
    _validate_claim_evidence_text(source_provenance, summary)
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
    *,
    require_full_book_coverage: bool = False,
    expected_sources: list[dict] | None = None,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
    require_book_bundle: bool = False,
    expected_book_bundle: dict | None = None,
    expected_chapter_local: dict | None = None,
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
    _validate_claim_evidence_text(source_provenance, summary)
    if require_full_book_coverage:
        coverage = source_provenance.get("input_coverage")
        if (
            not isinstance(coverage, dict)
            or coverage.get("scope") != "all_configured_chapters"
            or coverage.get("complete_for_configured_chapters") is not True
        ):
            raise ValueError("Reviewed summary lacks complete full-book coverage.")
    if expected_sources is not None:
        expected = [
            {
                "filename": item.get("filename"),
                "source_version_id": item.get("source_version_id"),
                **(
                    {"source_input_file": item["source_input_file"]}
                    if "source_input_file" in item
                    else {}
                ),
            }
            for item in expected_sources
            if isinstance(item, dict)
        ]
        actual = [
            {
                "filename": item["filename"],
                "source_version_id": item["source_version_id"],
                **(
                    {"source_input_file": item["source_input_file"]}
                    if "source_input_file" in item
                    else {}
                ),
            }
            for item in source_provenance["source_files"]
        ]
        if len(expected) != len(expected_sources) or actual != expected:
            raise ValueError(
                "Reviewed summary sources do not match the current chapter map."
            )
    if expected_chapter_local is not None:
        actual_chapter_local = source_provenance.get("chapter_local")
        if not isinstance(actual_chapter_local, dict) or any(
            actual_chapter_local.get(key) != value
            for key, value in expected_chapter_local.items()
        ):
            raise ValueError(
                "Reviewed summary does not match the current chapter-local source."
            )
    book_bundle = source_provenance.get("book_bundle")
    if require_book_bundle and not isinstance(book_bundle, dict):
        raise ValueError("Reviewed summary is not bound to a verified AI book bundle.")
    if expected_book_bundle is not None:
        if (
            not isinstance(book_bundle, dict)
            or any(
                book_bundle.get(field) != expected_book_bundle.get(field)
                for field in (
                    "source_snapshot_id",
                    "ai_bundle_id",
                    "bundle_set_relative_path",
                    "bundle_set_sha256",
                    "ai_bundle_relative_path",
                    "ai_bundle_sha256",
                    "episode_count",
                )
            )
        ):
            raise ValueError("Reviewed summary is bound to a different AI book bundle.")
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
        source_input_root=source_input_root,
        source_input_map=source_input_map,
    )
    return summary
