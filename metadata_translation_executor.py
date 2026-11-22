"""Execute explicit, bounded metadata translation runs with local recovery."""

import errno
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from metadata_translation import (
    create_metadata_translation_candidate,
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)
from metadata_translation_generation import _SYSTEM_PROMPT, _USER_PREFIX
from metadata_translation_freshness import verify_metadata_translation_plan_freshness
from utils import open_regular_file, resolve_child_path, write_new_child_bytes_atomically


_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_DATA_CATEGORIES = ("source_text",)


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


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Metadata provider response contains duplicate JSON keys.")
        result[key] = value
    return result


def _reject_non_finite(value: str):
    raise ValueError("Metadata provider response contains a non-finite JSON value.")


def _strict_object(raw: object) -> dict:
    if not isinstance(raw, str):
        raise ValueError("Metadata provider response must be JSON text.")
    encoded = raw.encode("utf-8")
    if not encoded or len(encoded) > _MAX_RESPONSE_BYTES:
        raise ValueError("Metadata provider response exceeds the size limit.")
    try:
        result = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeEncodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Metadata provider response is invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("Metadata provider response must be a JSON object.")
    return result


def _validate_translation(value: object) -> str:
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
        raise ValueError("Metadata provider returned an invalid translation value.")
    return value


def _parse_batch_translations(response_text: object, expected_ids: list[str]) -> dict:
    response = _strict_object(response_text)
    if set(response) != {"translations"} or not isinstance(
        response["translations"], list
    ):
        raise ValueError("Metadata provider response schema does not match.")
    translations = {}
    for item in response["translations"]:
        if not isinstance(item, dict) or set(item) != {
            "field_id",
            "translation_value",
        }:
            raise ValueError("Metadata provider returned an invalid translation item.")
        field_id = item["field_id"]
        if not isinstance(field_id, str) or field_id in translations:
            raise ValueError("Metadata provider returned a duplicate or invalid field ID.")
        translations[field_id] = _validate_translation(item["translation_value"])
    if set(translations) != set(expected_ids):
        raise ValueError("Metadata provider response does not cover this batch exactly.")
    return {field_id: translations[field_id] for field_id in expected_ids}


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


@contextmanager
def _lock_generation_run(plans_root: Path, run_id: str):
    lock_path = plans_root / f".metadata-translation-{run_id}.lock"
    if _is_reparse_point(lock_path):
        raise ValueError("Metadata generation lock must not be a reparse point.")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Metadata generation lock must be a regular file.")
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno == errno.EACCES or getattr(exc, "winerror", None) == 33:
                    raise ValueError("An identical metadata generation run is active.") from exc
                raise
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {
                    errno.EACCES,
                    errno.EAGAIN,
                    getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
                }:
                    raise ValueError("An identical metadata generation run is active.") from exc
                raise
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_child_bytes(
    plans_root: Path,
    filename: str,
    *,
    maximum_bytes: int,
) -> bytes | None:
    path = resolve_child_path(str(plans_root), filename, allow_missing=True)
    if not path.exists() and not path.is_symlink():
        return None
    if _is_reparse_point(path) or not path.is_file():
        raise ValueError("Metadata generation artifact must be a regular file.")
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ValueError("Metadata generation artifact exceeds the size limit.")
    return content


def _load_child_object(
    plans_root: Path,
    filename: str,
    *,
    maximum_bytes: int,
) -> dict | None:
    content = _load_child_bytes(
        plans_root,
        filename,
        maximum_bytes=maximum_bytes,
    )
    if content is None:
        return None
    try:
        result = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Metadata generation artifact is invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("Metadata generation artifact must be a JSON object.")
    return result


def _write_or_reuse(
    plans_root: Path,
    filename: str,
    content: bytes,
    *,
    maximum_bytes: int,
) -> bool:
    if len(content) > maximum_bytes:
        raise ValueError("Metadata generation output exceeds the size limit.")
    existing = _load_child_bytes(
        plans_root,
        filename,
        maximum_bytes=maximum_bytes,
    )
    if existing is not None:
        if existing != content:
            raise ValueError("Metadata generation output exists with different content.")
        return True
    try:
        write_new_child_bytes_atomically(str(plans_root), filename, content)
        return False
    except FileExistsError:
        existing = _load_child_bytes(
            plans_root,
            filename,
            maximum_bytes=maximum_bytes,
        )
        if existing != content:
            raise ValueError("Metadata generation output exists with different content.")
        return True


def _run_identity(
    generation_plan: dict,
    *,
    model_id: str,
    request_model: str,
    provider_id: str,
    provider_fingerprint: str,
) -> dict:
    summary = generation_plan["summary"]
    identity = {
        "schema_version": 1,
        "plan_sha256": summary["plan_sha256"],
        "source_snapshot": summary["source_snapshot"],
        "operator_model_id": model_id,
        "request_model": request_model,
        "provider_id": provider_id,
        "provider_fingerprint": provider_fingerprint,
        "tokenizer_sha256": summary["tokenizer_sha256"],
        "prompt_sha256": summary["prompt_sha256"],
        "context_window_tokens": summary["context_window_tokens"],
        "max_input_tokens_per_request": summary["max_input_tokens_per_request"],
        "max_output_tokens_per_request": summary["max_output_tokens_per_request"],
        "max_provider_calls": summary["max_provider_calls"],
        "estimated_cost_upper_bound": summary["estimated_cost_upper_bound"],
        "max_estimated_cost": summary["max_estimated_cost"],
        "data_categories": list(_DATA_CATEGORIES),
    }
    identity["run_id"] = hashlib.sha256(_canonical_json(identity)).hexdigest()
    return identity


def _ensure_fresh_snapshot(
    plan: dict,
    generation_plan: dict,
    *,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str,
) -> None:
    current = verify_metadata_translation_plan_freshness(
        plan,
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
    )
    expected = generation_plan["summary"]["source_snapshot"]
    if (
        current["catalog_sha256"] != expected["catalog_sha256"]
        or current["manifest_sha256"] != expected["manifest_sha256"]
    ):
        raise ValueError("Metadata sources changed after the generation preflight.")


def _ensure_run_manifest(plans_root: Path, identity: dict) -> str:
    filename = f".metadata-translation-{identity['run_id']}.run.json"
    existing = _load_child_object(
        plans_root,
        filename,
        maximum_bytes=64 * 1024,
    )
    if existing is not None:
        if (
            set(existing) != {"schema_version", "identity", "recorded_at_utc"}
            or type(existing.get("schema_version")) is not int
            or existing["schema_version"] != 1
            or existing.get("identity") != identity
            or not isinstance(existing.get("recorded_at_utc"), str)
        ):
            raise ValueError("Metadata generation run manifest identity does not match.")
        recorded_at = existing["recorded_at_utc"]
        _validate_recorded_at(recorded_at)
        return recorded_at

    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
    payload = _canonical_json(
        {
            "schema_version": 1,
            "identity": identity,
            "recorded_at_utc": recorded_at,
        }
    )
    try:
        write_new_child_bytes_atomically(str(plans_root), filename, payload)
        return recorded_at
    except FileExistsError:
        existing = _load_child_object(
            plans_root,
            filename,
            maximum_bytes=64 * 1024,
        )
        if (
            existing is None
            or type(existing.get("schema_version")) is not int
            or existing["schema_version"] != 1
            or existing.get("identity") != identity
            or not isinstance(existing.get("recorded_at_utc"), str)
        ):
            raise ValueError("Metadata generation run manifest identity does not match.")
        recorded_at = existing["recorded_at_utc"]
        _validate_recorded_at(recorded_at)
        return recorded_at


def _validate_recorded_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ValueError("Metadata generation run timestamp is invalid.") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Metadata generation run timestamp must be UTC.")


def _intent_filename(run_id: str, batch_index: int) -> str:
    return (
        f".metadata-translation-{run_id}-batch-{batch_index:04d}.intent.json"
    )


def _checkpoint_filename(run_id: str, batch_index: int) -> str:
    return (
        f".metadata-translation-{run_id}-batch-{batch_index:04d}.checkpoint.json"
    )


def _expected_batch_ids(batch: dict) -> list[str]:
    records = [json.loads(paragraph.text) for paragraph in batch["paragraphs"]]
    return [record["field_id"] for record in records]


def _batch_input_sha256(batch: dict) -> str:
    return hashlib.sha256(batch["user_text"].encode("utf-8")).hexdigest()


def _load_intent(
    plans_root: Path,
    *,
    run_id: str,
    batch_index: int,
    batch_input_sha256: str,
    provider_id: str,
    request_model: str,
    prompt_sha256: str,
    tokenizer_sha256: str,
) -> dict | None:
    filename = _intent_filename(run_id, batch_index)
    intent = _load_child_object(
        plans_root,
        filename,
        maximum_bytes=64 * 1024,
    )
    if intent is None:
        return None
    if (
        set(intent)
        != {
            "schema_version",
            "run_id",
            "batch_index",
            "batch_input_sha256",
            "provider_id",
            "request_model",
            "prompt_sha256",
            "tokenizer_sha256",
            "state",
        }
        or type(intent.get("schema_version")) is not int
        or intent["schema_version"] != 1
        or intent.get("run_id") != run_id
        or type(intent.get("batch_index")) is not int
        or intent.get("batch_index") != batch_index
        or intent.get("batch_input_sha256") != batch_input_sha256
        or intent.get("provider_id") != provider_id
        or intent.get("request_model") != request_model
        or intent.get("prompt_sha256") != prompt_sha256
        or intent.get("tokenizer_sha256") != tokenizer_sha256
        or intent.get("state") != "request_may_have_been_sent"
    ):
        raise ValueError("Metadata generation intent identity does not match.")
    return intent


def _load_checkpoint(
    plans_root: Path,
    *,
    run_id: str,
    batch_index: int,
    batch_input_sha256: str,
    provider_id: str,
    request_model: str,
    prompt_sha256: str,
    tokenizer_sha256: str,
    expected_input_tokens: int,
    max_input_tokens: int,
    max_output_tokens: int,
    expected_ids: list[str],
) -> dict | None:
    checkpoint = _load_child_object(
        plans_root,
        _checkpoint_filename(run_id, batch_index),
        maximum_bytes=_MAX_CHECKPOINT_BYTES,
    )
    if checkpoint is None:
        return None
    if (
        set(checkpoint)
        != {
            "schema_version",
            "run_id",
            "batch_index",
            "batch_input_sha256",
            "provider_id",
            "request_model",
            "prompt_sha256",
            "tokenizer_sha256",
            "estimated_input_tokens",
            "reported_prompt_tokens",
            "reported_completion_tokens",
            "response_sha256",
            "translations",
        }
        or type(checkpoint.get("schema_version")) is not int
        or checkpoint["schema_version"] != 1
        or checkpoint.get("run_id") != run_id
        or type(checkpoint.get("batch_index")) is not int
        or checkpoint.get("batch_index") != batch_index
        or checkpoint.get("batch_input_sha256") != batch_input_sha256
        or checkpoint.get("provider_id") != provider_id
        or checkpoint.get("request_model") != request_model
        or checkpoint.get("prompt_sha256") != prompt_sha256
        or checkpoint.get("tokenizer_sha256") != tokenizer_sha256
        or type(checkpoint.get("estimated_input_tokens")) is not int
        or checkpoint.get("estimated_input_tokens") != expected_input_tokens
        or checkpoint.get("reported_prompt_tokens") is not None
        and (
            isinstance(checkpoint["reported_prompt_tokens"], bool)
            or not isinstance(checkpoint["reported_prompt_tokens"], int)
            or not 0
            <= checkpoint["reported_prompt_tokens"]
            <= max_input_tokens
        )
        or checkpoint.get("reported_completion_tokens") is not None
        and (
            isinstance(checkpoint["reported_completion_tokens"], bool)
            or not isinstance(checkpoint["reported_completion_tokens"], int)
            or not 0
            <= checkpoint["reported_completion_tokens"]
            <= max_output_tokens
        )
        or not isinstance(checkpoint.get("response_sha256"), str)
        or not _SHA256.fullmatch(checkpoint["response_sha256"])
        or not isinstance(checkpoint.get("translations"), dict)
        or set(checkpoint["translations"]) != set(expected_ids)
    ):
        raise ValueError("Metadata generation checkpoint identity does not match.")
    checkpoint["translations"] = {
        field_id: _validate_translation(checkpoint["translations"][field_id])
        for field_id in expected_ids
    }
    return checkpoint


def _provider_response_text(response: object, *, max_input_tokens: int, max_output_tokens: int):
    choices = getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        raise ValueError("Metadata provider returned an invalid response.")
    choice = choices[0]
    if getattr(choice, "finish_reason", None) != "stop":
        raise ValueError("Metadata provider response did not finish normally.")
    response_text = getattr(getattr(choice, "message", None), "content", None)
    _strict_object(response_text)
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    for value, limit, label in (
        (prompt_tokens, max_input_tokens, "prompt"),
        (completion_tokens, max_output_tokens, "completion"),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= limit
        ):
            raise ValueError(f"Provider-reported metadata {label} tokens exceed the budget.")
    return response_text, prompt_tokens, completion_tokens


async def execute_metadata_translation_generation(
    plan: dict,
    generation_plan: dict,
    *,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str,
    plans_root: str | Path,
    candidate_name: str,
    model_id: str,
    request_model: str,
    provider_id: str,
    provider_fingerprint: str,
    client,
) -> dict:
    """Run one explicitly authorized model route and persist recoverable results."""
    plan_sha256 = verify_metadata_translation_plan(plan)
    if not isinstance(generation_plan, dict) or set(generation_plan) != {
        "summary",
        "source_snapshot",
        "system_text",
        "batches",
    }:
        raise ValueError("Metadata generation plan has an invalid schema.")
    summary = generation_plan["summary"]
    if not isinstance(summary, dict):
        raise ValueError("Metadata generation summary is invalid.")
    expected_ids = [
        field["field_id"]
        for field in plan["fields"]
        if field["source_value"] is not None
    ]
    batches = generation_plan["batches"]
    planned_ids = [
        field_id
        for batch in batches
        for field_id in _expected_batch_ids(batch)
    ] if isinstance(batches, list) else []
    if (
        summary.get("status") != "ready_for_operator_review"
        or summary.get("model_id") != model_id
        or summary.get("plan_sha256") != plan_sha256
        or summary.get("field_count") != len(expected_ids)
        or summary.get("source_snapshot") != generation_plan["source_snapshot"]
        or summary.get("planned_batch_count") != len(batches)
        or not isinstance(summary.get("prompt_sha256"), str)
        or summary["prompt_sha256"]
        != hashlib.sha256(
            (_SYSTEM_PROMPT + "\n" + _USER_PREFIX).encode("utf-8")
        ).hexdigest()
        or summary.get("tokenizer_sha256") is None
        or generation_plan.get("system_text") != _SYSTEM_PROMPT
        or planned_ids != expected_ids
        or isinstance(summary.get("max_input_tokens_per_request"), bool)
        or not isinstance(summary.get("max_input_tokens_per_request"), int)
        or isinstance(summary.get("max_output_tokens_per_request"), bool)
        or not isinstance(summary.get("max_output_tokens_per_request"), int)
        or not isinstance(request_model, str)
        or not request_model.strip()
        or request_model != request_model.strip()
        or len(request_model) > 256
        or any(ord(character) < 32 for character in request_model)
        or not isinstance(provider_id, str)
        or not provider_id.strip()
        or provider_id != provider_id.strip()
        or any(ord(character) < 32 for character in provider_id)
        or not isinstance(provider_fingerprint, str)
        or not _SHA256.fullmatch(provider_fingerprint)
        or not isinstance(batches, list)
        or not batches
    ):
        raise ValueError("Metadata generation execution identity is invalid.")
    if not isinstance(candidate_name, str) or not _FILENAME.fullmatch(candidate_name):
        raise ValueError("Candidate name must be a simple JSON filename.")

    plans_root = Path(plans_root).resolve(strict=True)
    workflow_root = plans_root.parent
    if (
        plans_root.name != "Plans"
        or workflow_root.name != "Workflow"
        or not plans_root.is_dir()
        or _is_reparse_point(plans_root)
        or _is_reparse_point(workflow_root)
        or plans_root.resolve(strict=True) != plans_root
        or workflow_root.resolve(strict=True) != workflow_root
    ):
        raise ValueError("Metadata outputs require an existing Workflow/Plans directory.")

    identity = _run_identity(
        generation_plan,
        model_id=model_id,
        request_model=request_model,
        provider_id=provider_id,
        provider_fingerprint=provider_fingerprint,
    )
    run_id = identity["run_id"]
    prompt_sha256 = summary["prompt_sha256"]
    tokenizer_sha256 = summary["tokenizer_sha256"]
    max_input_tokens = summary["max_input_tokens_per_request"]
    max_output_tokens = summary["max_output_tokens_per_request"]
    _ensure_fresh_snapshot(
        plan,
        generation_plan,
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
    )

    with _lock_generation_run(plans_root, run_id):
        recorded_at = _ensure_run_manifest(plans_root, identity)
        translations = {}
        batch_receipts = []
        calls_made = 0
        calls_reused = 0
        for batch_index, batch in enumerate(batches, start=1):
            _ensure_fresh_snapshot(
                plan,
                generation_plan,
                source_root=source_root,
                catalog_relative_path=catalog_relative_path,
                manifest_relative_path=manifest_relative_path,
            )
            expected_ids = _expected_batch_ids(batch)
            input_sha256 = _batch_input_sha256(batch)
            checkpoint_arguments = {
                "run_id": run_id,
                "batch_index": batch_index,
                "batch_input_sha256": input_sha256,
                "provider_id": provider_id,
                "request_model": request_model,
                "prompt_sha256": prompt_sha256,
                "tokenizer_sha256": tokenizer_sha256,
                "expected_input_tokens": batch["input_tokens"],
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "expected_ids": expected_ids,
            }
            checkpoint = _load_checkpoint(plans_root, **checkpoint_arguments)
            intent = _load_intent(
                plans_root,
                run_id=run_id,
                batch_index=batch_index,
                batch_input_sha256=input_sha256,
                provider_id=provider_id,
                request_model=request_model,
                prompt_sha256=prompt_sha256,
                tokenizer_sha256=tokenizer_sha256,
            )
            if checkpoint is not None:
                if intent is None:
                    raise ValueError("Metadata checkpoint has no matching request intent.")
                translations.update(checkpoint["translations"])
                calls_reused += 1
                batch_receipts.append(
                    {
                        "batch_index": batch_index,
                        "batch_input_sha256": input_sha256,
                        "response_sha256": checkpoint["response_sha256"],
                        "estimated_input_tokens": checkpoint["estimated_input_tokens"],
                        "reported_prompt_tokens": checkpoint["reported_prompt_tokens"],
                        "reported_completion_tokens": checkpoint[
                            "reported_completion_tokens"
                        ],
                    }
                )
                continue
            if intent is not None:
                raise ValueError(
                    "A metadata request may have been sent without a checkpoint; "
                    "operator resolution is required before another request."
                )

            intent_record = {
                "schema_version": 1,
                "run_id": run_id,
                "batch_index": batch_index,
                "batch_input_sha256": input_sha256,
                "provider_id": provider_id,
                "request_model": request_model,
                "prompt_sha256": prompt_sha256,
                "tokenizer_sha256": tokenizer_sha256,
                "state": "request_may_have_been_sent",
            }
            intent_filename = _intent_filename(run_id, batch_index)
            if _load_child_bytes(
                plans_root,
                intent_filename,
                maximum_bytes=64 * 1024,
            ) is not None:
                raise ValueError("Metadata request intent already exists without a checkpoint.")
            try:
                write_new_child_bytes_atomically(
                    str(plans_root),
                    intent_filename,
                    _canonical_json(intent_record),
                )
            except FileExistsError as exc:
                raise ValueError(
                    "Metadata request intent already exists without a checkpoint."
                ) from exc

            calls_made += 1
            response = await client.chat.completions.create(
                model=request_model,
                messages=[
                {"role": "system", "content": generation_plan["system_text"]},
                    {"role": "user", "content": batch["user_text"]},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_output_tokens,
            )
            response_text, reported_prompt_tokens, reported_completion_tokens = (
                _provider_response_text(
                    response,
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=max_output_tokens,
                )
            )
            batch_translations = _parse_batch_translations(
                response_text,
                expected_ids,
            )
            checkpoint = {
                "schema_version": 1,
                "run_id": run_id,
                "batch_index": batch_index,
                "batch_input_sha256": input_sha256,
                "provider_id": provider_id,
                "request_model": request_model,
                "prompt_sha256": prompt_sha256,
                "tokenizer_sha256": tokenizer_sha256,
                "estimated_input_tokens": batch["input_tokens"],
                "reported_prompt_tokens": reported_prompt_tokens,
                "reported_completion_tokens": reported_completion_tokens,
                "response_sha256": hashlib.sha256(
                    response_text.encode("utf-8")
                ).hexdigest(),
                "translations": batch_translations,
            }
            checkpoint_bytes = _canonical_json(checkpoint)
            if len(checkpoint_bytes) > _MAX_CHECKPOINT_BYTES:
                raise ValueError("Metadata generation checkpoint exceeds the size limit.")
            _write_or_reuse(
                plans_root,
                _checkpoint_filename(run_id, batch_index),
                checkpoint_bytes,
                maximum_bytes=_MAX_CHECKPOINT_BYTES,
            )
            translations.update(batch_translations)
            batch_receipts.append(
                {
                    "batch_index": batch_index,
                    "batch_input_sha256": input_sha256,
                    "response_sha256": checkpoint["response_sha256"],
                    "estimated_input_tokens": checkpoint["estimated_input_tokens"],
                    "reported_prompt_tokens": checkpoint["reported_prompt_tokens"],
                    "reported_completion_tokens": checkpoint[
                        "reported_completion_tokens"
                    ],
                }
            )

        _ensure_fresh_snapshot(
            plan,
            generation_plan,
            source_root=source_root,
            catalog_relative_path=catalog_relative_path,
            manifest_relative_path=manifest_relative_path,
        )
        candidate = create_metadata_translation_candidate(
            plan,
            translations,
            {
                "declared_origin": "provider_export",
                "provider_id": provider_id,
                "model_id": request_model,
                "prompt_sha256": prompt_sha256,
                "recorded_at_utc": recorded_at,
            },
        )
        verify_metadata_translation_candidate(candidate, plan)
        candidate_bytes = _canonical_json(candidate)
        reused_candidate = _write_or_reuse(
            plans_root,
            candidate_name,
            candidate_bytes,
            maximum_bytes=_MAX_CANDIDATE_BYTES,
        )
        receipt = {
            "schema_version": 1,
            "status": "completed",
            "run_id": run_id,
            "plan_sha256": summary["plan_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "source_snapshot": summary["source_snapshot"],
            "provider_id": provider_id,
            "provider_fingerprint": provider_fingerprint,
            "operator_model_id": model_id,
            "request_model": request_model,
            "tokenizer_sha256": tokenizer_sha256,
            "prompt_sha256": prompt_sha256,
            "data_categories": list(_DATA_CATEGORIES),
            "batch_count": len(batch_receipts),
            "provider_calls_for_run": len(batch_receipts),
            "estimated_cost_upper_bound": summary["estimated_cost_upper_bound"],
            "max_estimated_cost": summary["max_estimated_cost"],
            "provider_cost_cap_enforced": False,
            "recorded_at_utc": recorded_at,
            "batches": batch_receipts,
        }
        receipt_bytes = _canonical_json(receipt)
        receipt_name = f".metadata-translation-{run_id}.receipt.json"
        _write_or_reuse(
            plans_root,
            receipt_name,
            receipt_bytes,
            maximum_bytes=2 * 1024 * 1024,
        )

    return {
        "status": "metadata_translation_candidate_reused"
        if reused_candidate
        else "metadata_translation_candidate_created",
        "run_id": run_id,
        "plan_sha256": summary["plan_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "candidate_name": candidate_name,
        "receipt_name": receipt_name,
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "field_count": candidate["field_count"],
        "review_status": candidate["status"],
        "provider_id": provider_id,
        "model_id": request_model,
        "provider_calls_made": calls_made,
        "provider_calls_reused": calls_reused,
        "provider_cost_cap_enforced": False,
        "source_values_in_report": False,
    }
