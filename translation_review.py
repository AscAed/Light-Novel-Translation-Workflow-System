"""Version-bound human review and create-only translation publication."""

import hashlib
import hmac
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from book_bundles import DEFAULT_MAX_TOTAL_BUNDLE_BYTES
from source_editions import read_verified_ai_edition_bytes, verify_ai_edition_index
from source_manifest import verify_current_normalized_source_metadata
from translation_review_state import (
    create_review_decision_record,
    create_review_resolution_record,
    load_review_decision_chain,
    load_review_resolution_chain,
    read_review_policy_file,
    store_review_policy_artifact,
    write_review_decision,
    write_review_resolution,
)
from utils import (
    open_regular_file,
    require_aligned_paragraphs,
    resolve_child_path,
    resolve_relative_path,
    split_paragraphs,
    write_text_atomically,
    write_new_child_text,
)


_MAX_RUN_BYTES = 16 * 1024 * 1024
_MAX_REVIEW_BYTES = 256 * 1024
_MAX_TRANSLATION_BYTES = 16 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_REVIEW_CHECKS = (
    "fidelity",
    "completeness",
    "terminology",
    "character_voice",
    "continuity",
    "readability",
    "format",
    "sensitive_content",
)
_RUN_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "run_id",
        "created_at_utc",
        "work_id",
        "plan_sha256",
        "source_root",
        "catalog",
        "source_manifest",
        "edition_manifest",
        "ai_root",
        "ai_index",
        "ai_index_sha256",
        "book_bundle",
        "translation_root",
        "draft_root",
        "episodes",
    }
)
_EPISODE_FIELDS = frozenset(
    {
        "episode_id",
        "position",
        "title",
        "source_file",
        "source_version_id",
        "source_input_file",
        "source_sha256",
        "translation_file",
        "tm_key",
        "draft_sha256",
        "draft_bytes",
    }
)
_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "run_manifest_sha256",
        "plan_sha256",
        "work_id",
        "episode_id",
        "position",
        "source_version_id",
        "source_input_file",
        "source_sha256",
        "draft_file",
        "draft_sha256",
        "reviewer_id",
        "independence_confirmed",
        "reviewed_at_utc",
        "decision",
        "checks",
        "issues",
        "notes",
    }
)
_REVIEW_CHAIN_FIELDS = frozenset(
    {
        *(_REVIEW_FIELDS - {"draft_file", "draft_sha256"}),
        "candidate_revision",
        "candidate_relative_path",
        "candidate_sha256",
        "decision_sha256",
    }
)
_REVIEW_OVERRIDE_FIELDS = frozenset(
    {*_REVIEW_CHAIN_FIELDS, "resolution_sha256"}
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Review input contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_json(path: Path, limit: int, label: str) -> tuple[dict, bytes]:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"{label} exceeds the configured size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value, content


def _require_text(value, field: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Review input has an invalid {field}.")
    return value


def _load_run(run_directory: str | Path) -> tuple[Path, dict, bytes]:
    supplied_path = Path(run_directory)
    if supplied_path.is_symlink():
        raise ValueError("Translation run path must be a regular directory.")
    run_root = supplied_path.resolve(strict=True)
    if not run_root.is_dir():
        raise ValueError("Translation run path must be a regular directory.")
    run, run_bytes = _read_json(run_root / "run.json", _MAX_RUN_BYTES, "Run manifest")
    if (
        set(run) != _RUN_FIELDS
        or isinstance(run.get("schema_version"), bool)
        or run.get("schema_version") != 1
        or run.get("status") != "review_pending"
        or not isinstance(run.get("run_id"), str)
        or not _RUN_ID_PATTERN.fullmatch(run["run_id"])
        or run_root.name != run["run_id"]
    ):
        raise ValueError("Translation run manifest is invalid or not reviewable.")
    for field in (
        "work_id",
        "source_root",
        "catalog",
        "source_manifest",
        "edition_manifest",
        "ai_root",
        "ai_index",
        "translation_root",
        "draft_root",
    ):
        _require_text(run.get(field), field)
    if (
        not isinstance(run.get("plan_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(run["plan_sha256"])
        or not isinstance(run.get("ai_index_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(run["ai_index_sha256"])
    ):
        raise ValueError("Translation run manifest contains invalid digests.")
    book_bundle = run.get("book_bundle")
    if book_bundle is not None:
        bundle_fields = {
            "source_snapshot_id",
            "ai_bundle_id",
            "bundle_set_relative_path",
            "bundle_set_sha256",
            "ai_bundle_relative_path",
            "ai_bundle_sha256",
        }
        if (
            not isinstance(book_bundle, dict)
            or set(book_bundle) != bundle_fields
            or not isinstance(book_bundle.get("source_snapshot_id"), str)
            or not re.fullmatch(
                r"source-v1-[0-9a-f]{64}",
                book_bundle["source_snapshot_id"],
            )
            or not isinstance(book_bundle.get("ai_bundle_id"), str)
            or not re.fullmatch(
                r"ai-v1-[0-9a-f]{64}",
                book_bundle["ai_bundle_id"],
            )
            or any(
                not isinstance(book_bundle.get(field), str)
                or not _SHA256_PATTERN.fullmatch(book_bundle[field])
                for field in ("bundle_set_sha256", "ai_bundle_sha256")
            )
        ):
            raise ValueError("Translation run contains invalid book bundle data.")
        for field in ("bundle_set_relative_path", "ai_bundle_relative_path"):
            _require_text(book_bundle.get(field), field)
    episodes = run.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("Translation run must contain at least one episode.")
    seen_ids = set()
    seen_positions = set()
    for episode in episodes:
        if not isinstance(episode, dict) or set(episode) != _EPISODE_FIELDS:
            raise ValueError("Translation run contains an invalid episode.")
        episode_id = _require_text(episode["episode_id"], "episode_id")
        position = episode["position"]
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or episode_id in seen_ids
            or position in seen_positions
        ):
            raise ValueError("Translation run has duplicate or invalid episodes.")
        seen_ids.add(episode_id)
        seen_positions.add(position)
        for field in (
            "title",
            "source_file",
            "source_version_id",
            "source_input_file",
            "translation_file",
            "tm_key",
        ):
            _require_text(episode[field], field)
        if (
            not isinstance(episode["source_sha256"], str)
            or not _SHA256_PATTERN.fullmatch(episode["source_sha256"])
            or not isinstance(episode["draft_sha256"], str)
            or not _SHA256_PATTERN.fullmatch(episode["draft_sha256"])
            or isinstance(episode["draft_bytes"], bool)
            or not isinstance(episode["draft_bytes"], int)
            or episode["draft_bytes"] < 0
        ):
            raise ValueError("Translation run contains invalid episode digests.")
    if run.get("created_at_utc") is not None:
        _require_text(run["created_at_utc"], "created_at_utc", maximum=64)
    return run_root, run, run_bytes


def _run_episode(run: dict, episode_id: str) -> dict:
    _require_text(episode_id, "episode_id")
    matches = [
        episode
        for episode in run["episodes"]
        if episode["episode_id"] == episode_id
    ]
    if len(matches) != 1:
        raise ValueError("Episode is not uniquely present in the translation run.")
    return matches[0]


def _load_current_ai_index(run: dict):
    source_root = Path(run["source_root"]).resolve(strict=True)
    ai_root = Path(run["ai_root"]).resolve(strict=True)
    index_result = verify_ai_edition_index(
        source_root=str(source_root),
        ai_root=str(ai_root),
        source_manifest_relative_path=run["source_manifest"],
        edition_manifest_relative_path=run["edition_manifest"],
        index_relative_path=run["ai_index"],
    )
    if (
        index_result["index"].get("catalog", {}).get("relative_path")
        != run["catalog"]
    ):
        raise ValueError("Translation run catalog differs from the AI edition.")
    return source_root, ai_root, index_result


def _verify_index_bound_inputs(
    run: dict,
    episode: dict,
    *,
    source_root: Path,
    ai_root: Path,
    index_result: dict,
) -> bytes:
    book_bundle = run["book_bundle"]
    if book_bundle is not None:
        set_path = resolve_relative_path(
            str(source_root),
            book_bundle["bundle_set_relative_path"],
        )
        with open_regular_file(set_path, binary=True) as stream:
            set_bytes = stream.read(4 * 1024 * 1024 + 1)
        if (
            len(set_bytes) > 4 * 1024 * 1024
            or not hmac.compare_digest(
                _sha256_bytes(set_bytes),
                book_bundle["bundle_set_sha256"],
            )
        ):
            raise ValueError("Translation run book bundle set changed.")
        try:
            bundle_set = json.loads(
                set_bytes.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Translation run book bundle set is invalid.") from exc
        ai_record = (
            bundle_set.get("bundles", {}).get("ai")
            if isinstance(bundle_set, dict)
            else None
        )
        if (
            not isinstance(ai_record, dict)
            or ai_record.get("bundle_id") != book_bundle["ai_bundle_id"]
            or ai_record.get("relative_path")
            != book_bundle["ai_bundle_relative_path"]
            or ai_record.get("sha256") != book_bundle["ai_bundle_sha256"]
            or bundle_set.get("source_snapshot_id")
            != book_bundle["source_snapshot_id"]
        ):
            raise ValueError("Translation run book bundle set identity changed.")
        ai_bundle_path = resolve_relative_path(
            str(ai_root),
            book_bundle["ai_bundle_relative_path"],
        )
        ai_bundle_digest = hashlib.sha256()
        ai_bundle_size = 0
        with open_regular_file(ai_bundle_path, binary=True) as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                ai_bundle_size += len(chunk)
                if ai_bundle_size > DEFAULT_MAX_TOTAL_BUNDLE_BYTES:
                    raise ValueError("Translation run AI book bundle is too large.")
                ai_bundle_digest.update(chunk)
        if not hmac.compare_digest(
            ai_bundle_digest.hexdigest(),
            book_bundle["ai_bundle_sha256"],
        ):
            raise ValueError("Translation run AI book bundle changed.")
    indexed = index_result["episodes_by_id"].get(episode["episode_id"])
    if (
        indexed is None
        or indexed.get("ai_edition_version_id") != episode["source_version_id"]
        or indexed.get("ai_archive_relative_path") != episode["source_file"]
        or indexed.get("ai_relative_path") != episode["source_input_file"]
        or indexed.get("output_sha256") != episode["source_sha256"]
        or indexed.get("title") != episode["title"]
        or indexed.get("position") != episode["position"]
    ):
        raise ValueError("Translation run source no longer matches the AI edition.")
    return read_verified_ai_edition_bytes(
        str(ai_root),
        episode["source_input_file"],
        episode["source_sha256"],
    )


def _verify_current_inputs(run: dict, episode: dict) -> bytes:
    source_root, ai_root, index_result = _load_current_ai_index(run)
    if index_result["index_sha256"] != run["ai_index_sha256"]:
        raise ValueError("AI edition index changed after translation.")
    return _verify_index_bound_inputs(
        run,
        episode,
        source_root=source_root,
        ai_root=ai_root,
        index_result=index_result,
    )


def _verify_historical_publication_inputs(run: dict, episode: dict) -> bytes:
    """Verify an old publication against the current index without requiring it to be frozen."""
    source_root, ai_root, index_result = _load_current_ai_index(run)
    return _verify_index_bound_inputs(
        run,
        episode,
        source_root=source_root,
        ai_root=ai_root,
        index_result=index_result,
    )


def _load_draft(
    run_root: Path,
    run: dict,
    episode: dict,
    source_bytes: bytes,
) -> bytes:
    draft_root = resolve_relative_path(
        str(run_root),
        run["draft_root"],
    )
    draft_path = resolve_relative_path(
        str(draft_root),
        episode["translation_file"],
    )
    with open_regular_file(draft_path, binary=True) as stream:
        draft_bytes = stream.read(_MAX_TRANSLATION_BYTES + 1)
    if (
        len(draft_bytes) > _MAX_TRANSLATION_BYTES
        or len(draft_bytes) != episode["draft_bytes"]
        or not hmac.compare_digest(
            _sha256_bytes(draft_bytes),
            episode["draft_sha256"],
        )
    ):
        raise ValueError("Translation draft changed after the run was completed.")
    _validate_translation_bytes(source_bytes, draft_bytes, "Reviewed translation")
    return draft_bytes


def _validate_translation_bytes(
    source_bytes: bytes,
    translation_bytes: bytes,
    label: str,
) -> bytes:
    try:
        source_text = source_bytes.decode("utf-8")
        translation_text = translation_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Translation source and draft must be UTF-8.") from exc
    source_paragraphs = split_paragraphs(source_text)
    translated_paragraphs = split_paragraphs(translation_text)
    require_aligned_paragraphs(
        source_paragraphs,
        translated_paragraphs,
        label,
    )
    if any(not paragraph.strip() for paragraph in translated_paragraphs):
        raise ValueError("Translation draft contains an empty paragraph.")
    quote_marks = ("「", "」", "『", "』")
    for source, translated in zip(source_paragraphs, translated_paragraphs):
        if (
            tuple(mark for mark in source if mark in quote_marks)
            != tuple(mark for mark in translated if mark in quote_marks)
        ):
            raise ValueError("Translation draft does not preserve source quote marks.")
    return translation_bytes


def build_translation_run_manifest(
    *,
    run_id: str,
    plan: dict,
    source_root: str,
    source_manifest: str,
    edition_manifest: str,
    catalog: str,
    ai_root: str,
    ai_index: str = "catalog.json",
    draft_root: str = "Drafts",
    translation_root: str,
    book_bundle: dict | None = None,
    episode_ids: list[str] | None = None,
) -> dict:
    """Bind completed draft files to the current verified AI edition."""
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Translation run ID must be 32 lowercase hex characters.")
    plan_sha256 = plan.get("plan_sha256")
    if not isinstance(plan_sha256, str) or not _SHA256_PATTERN.fullmatch(plan_sha256):
        raise ValueError("Translation plan must contain a valid plan_sha256.")
    source_path = Path(source_root).resolve(strict=True)
    ai_path = Path(ai_root).resolve(strict=True)
    ai_result = verify_ai_edition_index(
        source_root=str(source_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=source_manifest,
        edition_manifest_relative_path=edition_manifest,
        index_relative_path=ai_index,
    )
    if (
        plan.get("work_id") != ai_result["index"]["work_id"]
        or len(plan.get("episodes", []))
        != len(ai_result["episodes_by_id"])
        or ai_result["index"].get("catalog", {}).get("relative_path")
        != catalog.replace("\\", "/")
    ):
        raise ValueError("Translation plan does not cover the current AI edition.")
    ai_index_path = resolve_relative_path(str(ai_path), ai_index)
    with open_regular_file(ai_index_path, binary=True) as stream:
        ai_index_sha256 = _sha256_bytes(stream.read(_MAX_RUN_BYTES + 1))
    plan_by_id = {
        item["episode_id"]: item
        for item in plan["episodes"]
        if isinstance(item, dict) and isinstance(item.get("episode_id"), str)
    }
    if len(plan_by_id) != len(plan["episodes"]):
        raise ValueError("Translation plan contains duplicate or invalid episodes.")
    draft_path = Path(draft_root).resolve(strict=True)
    if episode_ids is None:
        selected_episode_ids = set(plan_by_id)
    else:
        if (
            not isinstance(episode_ids, list)
            or not episode_ids
            or any(
                not isinstance(episode_id, str)
                or episode_id not in plan_by_id
                for episode_id in episode_ids
            )
            or len(set(episode_ids)) != len(episode_ids)
        ):
            raise ValueError("Translation run episode selection is invalid.")
        selected_episode_ids = set(episode_ids)
    episodes = []
    if set(plan_by_id) != set(ai_result["episodes_by_id"]):
        raise ValueError("Translation plan episode set differs from the AI edition.")
    for plan_episode in plan["episodes"]:
        episode_id = plan_episode["episode_id"]
        indexed = ai_result["episodes_by_id"][episode_id]
        if (
            plan_episode.get("source_version_id")
            != indexed.get("ai_edition_version_id")
            or plan_episode.get("source_file")
            != indexed.get("ai_archive_relative_path")
            or plan_episode.get("source_input_version_id")
            != indexed.get("raw_source_version_id")
            or plan_episode.get("source_input_file")
            != indexed.get("ai_relative_path")
            or plan_episode.get("source_sha256") != indexed.get("output_sha256")
            or plan_episode.get("title") != indexed.get("title")
            or plan_episode.get("position") != indexed.get("position")
        ):
            raise ValueError("Translation plan source mapping is stale.")
        edition_artifact = verify_current_normalized_source_metadata(
            ai_result["edition_manifest"],
            plan_episode["source_version_id"],
        )
        if (
            edition_artifact["relative_path"] != plan_episode.get("source_file")
            or edition_artifact["content_sha256"]
            != plan_episode.get("source_sha256")
            or edition_artifact["version_id"]
            != plan_episode.get("source_version_id")
        ):
            raise ValueError("Translation plan archive lineage is stale.")
        if episode_id not in selected_episode_ids:
            continue
        source_bytes = read_verified_ai_edition_bytes(
            str(ai_path),
            indexed["ai_relative_path"],
            indexed["output_sha256"],
        )
        draft_file = plan_episode["translation_file"]
        target = resolve_relative_path(str(draft_path), draft_file)
        with open_regular_file(target, binary=True) as stream:
            draft_bytes = stream.read(_MAX_TRANSLATION_BYTES + 1)
        if len(draft_bytes) > _MAX_TRANSLATION_BYTES:
            raise ValueError("Translation draft exceeds the configured size limit.")
        source_text = source_bytes.decode("utf-8")
        translated_text = draft_bytes.decode("utf-8")
        source_paragraphs = split_paragraphs(source_text)
        translated_paragraphs = split_paragraphs(translated_text)
        require_aligned_paragraphs(
            source_paragraphs,
            translated_paragraphs,
            "Translation draft",
        )
        if any(not paragraph.strip() for paragraph in translated_paragraphs):
            raise ValueError("Translation draft contains an empty paragraph.")
        quote_marks = ("「", "」", "『", "』")
        if any(
            tuple(mark for mark in source if mark in quote_marks)
            != tuple(mark for mark in translated if mark in quote_marks)
            for source, translated in zip(
                source_paragraphs,
                translated_paragraphs,
            )
        ):
            raise ValueError("Translation draft does not preserve source quote marks.")
        episodes.append(
            {
                "episode_id": episode_id,
                "position": plan_episode["position"],
                "title": plan_episode["title"],
                "source_file": plan_episode["source_file"],
                "source_version_id": plan_episode["source_version_id"],
                "source_input_file": plan_episode["source_input_file"],
                "source_sha256": plan_episode["source_sha256"],
                "translation_file": draft_file,
                "tm_key": plan_episode["tm_key"],
                "draft_sha256": _sha256_bytes(draft_bytes),
                "draft_bytes": len(draft_bytes),
            }
        )
    return {
        "schema_version": 1,
        "status": "review_pending",
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "work_id": plan["work_id"],
        "plan_sha256": plan_sha256,
        "source_root": str(source_path),
        "catalog": catalog.replace("\\", "/"),
        "source_manifest": source_manifest.replace("\\", "/"),
        "edition_manifest": edition_manifest.replace("\\", "/"),
        "ai_root": str(ai_path),
        "ai_index": ai_index.replace("\\", "/"),
        "ai_index_sha256": ai_index_sha256,
        "book_bundle": book_bundle,
        "translation_root": str(Path(translation_root).resolve(strict=True)),
        "draft_root": "Drafts",
        "episodes": episodes,
    }


def _write_new_json(root: Path, name: str, value: dict) -> None:
    write_new_child_text(str(root), name, _canonical_json(value))


def prepare_translation_review(
    run_directory: str | Path,
    episode_id: str,
    *,
    review_directory: str = "Reviews",
) -> dict:
    run_root, run, run_bytes = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    source_bytes = _verify_current_inputs(run, episode)
    chain = load_review_decision_chain(
        run_root,
        episode_id=episode_id,
        expected_run_id=run["run_id"],
        expected_work_id=run["work_id"],
        expected_source_version_id=episode["source_version_id"],
        expected_source_sha256=episode["source_sha256"],
    )
    if chain:
        final_decision = chain[-1]
        decision_status = final_decision["transition"]["status"]
        resolution_sha256 = None
        if decision_status == "needs_human":
            resolutions = load_review_resolution_chain(
                run_root,
                episode_id=episode_id,
            )
            human_resolution = next(
                (
                    item
                    for item in reversed(resolutions)
                    if item["decision_sha256"]
                    == final_decision["decision_sha256"]
                ),
                None,
            )
            if human_resolution is None or human_resolution["action"] != "approve_current":
                raise ValueError(
                    "A human approval resolution is required for this candidate."
                )
            schema_version = 3
            resolution_sha256 = human_resolution["resolution_sha256"]
        elif decision_status == "passed":
            schema_version = 2
        else:
            raise ValueError(
                "A review checklist requires a passed decision or explicit "
                "human approval."
            )
        candidate_bytes = _load_review_candidate(
            run_root,
            run,
            episode,
            source_bytes,
            final_decision,
        )
        review = {
            "schema_version": schema_version,
            "run_id": run["run_id"],
            "run_manifest_sha256": _sha256_bytes(run_bytes),
            "plan_sha256": run["plan_sha256"],
            "work_id": run["work_id"],
            "episode_id": episode["episode_id"],
            "position": episode["position"],
            "source_version_id": episode["source_version_id"],
            "source_input_file": episode["source_input_file"],
            "source_sha256": episode["source_sha256"],
            "candidate_revision": final_decision["candidate_revision"],
            "candidate_relative_path": final_decision[
                "candidate_relative_path"
            ],
            "candidate_sha256": final_decision["candidate_sha256"],
            "decision_sha256": final_decision["decision_sha256"],
        }
        if schema_version == 3:
            review["resolution_sha256"] = resolution_sha256
        review_digest = final_decision["candidate_sha256"]
    else:
        candidate_bytes = _load_draft(run_root, run, episode, source_bytes)
        review = {
            "schema_version": 1,
            "run_id": run["run_id"],
            "run_manifest_sha256": _sha256_bytes(run_bytes),
            "plan_sha256": run["plan_sha256"],
            "work_id": run["work_id"],
            "episode_id": episode["episode_id"],
            "position": episode["position"],
            "source_version_id": episode["source_version_id"],
            "source_input_file": episode["source_input_file"],
            "source_sha256": episode["source_sha256"],
            "draft_file": f"{run['draft_root']}/{episode['translation_file']}",
            "draft_sha256": episode["draft_sha256"],
        }
        review_digest = episode["draft_sha256"]
    reviews_root = resolve_relative_path(
        str(run_root),
        review_directory,
        allow_missing=True,
    )
    if reviews_root.is_symlink():
        raise ValueError("Review directory must not be a symbolic link.")
    reviews_root.mkdir(exist_ok=True)
    resolve_relative_path(str(run_root), review_directory)
    review.update(
        {
            "reviewer_id": "",
            "independence_confirmed": False,
            "reviewed_at_utc": "",
            "decision": "pending",
            "checks": {name: "pending" for name in _REVIEW_CHECKS},
            "issues": [],
            "notes": "",
        }
    )
    review_name = f"{episode['episode_id']}.json"
    review_path = resolve_child_path(
        str(reviews_root),
        review_name,
        allow_missing=True,
    )
    content = _canonical_json(review)
    try:
        write_new_child_text(str(reviews_root), review_name, content)
        created = True
    except FileExistsError:
        with open_regular_file(review_path) as stream:
            if stream.read() != content:
                raise ValueError("Existing review file differs from its template.")
        created = False
    report = {
        "status": "review_template_ready",
        "episode_id": episode_id,
        "review_path": str(review_path),
        "created": created,
    }
    if review["schema_version"] == 2:
        report.update(
            {
                "candidate_revision": review["candidate_revision"],
                "candidate_sha256": review_digest,
            }
        )
    elif review["schema_version"] == 3:
        report.update(
            {
                "candidate_revision": review["candidate_revision"],
                "candidate_sha256": review_digest,
                "resolution_sha256": review["resolution_sha256"],
            }
        )
    else:
        report["draft_sha256"] = review_digest
    return report


def _load_review_candidate(
    run_root: Path,
    run: dict,
    episode: dict,
    source_bytes: bytes,
    decision: dict,
) -> bytes:
    relative_path = decision["candidate_relative_path"]
    if decision["candidate_revision"] == 0 and relative_path != (
        f"{run['draft_root']}/{episode['translation_file']}"
    ):
        raise ValueError("Initial review candidate differs from the run draft.")
    candidate_path = resolve_relative_path(str(run_root), relative_path)
    with open_regular_file(candidate_path, binary=True) as stream:
        candidate_bytes = stream.read(_MAX_TRANSLATION_BYTES + 1)
    if (
        len(candidate_bytes) > _MAX_TRANSLATION_BYTES
        or not hmac.compare_digest(
            _sha256_bytes(candidate_bytes),
            decision["candidate_sha256"],
        )
    ):
        raise ValueError("Review candidate changed after its decision.")
    _validate_translation_bytes(source_bytes, candidate_bytes, "Review candidate")
    if decision["candidate_revision"] == 0:
        draft_bytes = _load_draft(run_root, run, episode, source_bytes)
        if candidate_bytes != draft_bytes:
            raise ValueError("Initial review candidate differs from the run draft.")
    return candidate_bytes


def _validate_approved_review(
    review_path: Path,
    *,
    run_root: Path,
    run: dict,
    run_bytes: bytes,
    episode: dict,
    input_verifier=_verify_current_inputs,
) -> tuple[dict, bytes, bytes]:
    review, review_bytes = _read_json(
        review_path,
        _MAX_REVIEW_BYTES,
        "Translation review",
    )
    schema_version = review.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("Translation review schema version is unsupported.")
    if schema_version == 1 and set(review) == _REVIEW_FIELDS:
        chain = load_review_decision_chain(
            run_root,
            episode_id=episode["episode_id"],
            expected_run_id=run["run_id"],
            expected_work_id=run["work_id"],
            expected_source_version_id=episode["source_version_id"],
            expected_source_sha256=episode["source_sha256"],
        )
        if chain:
            raise ValueError(
                "A decision chain requires a review of its final passed candidate."
            )
        expected = {
            "run_id": run["run_id"],
            "run_manifest_sha256": _sha256_bytes(run_bytes),
            "plan_sha256": run["plan_sha256"],
            "work_id": run["work_id"],
            "episode_id": episode["episode_id"],
            "position": episode["position"],
            "source_version_id": episode["source_version_id"],
            "source_input_file": episode["source_input_file"],
            "source_sha256": episode["source_sha256"],
            "draft_file": f"{run['draft_root']}/{episode['translation_file']}",
            "draft_sha256": episode["draft_sha256"],
        }
        source_bytes = input_verifier(run, episode)
        candidate_bytes = _load_draft(run_root, run, episode, source_bytes)
    elif schema_version in {2, 3} and set(review) == (
        _REVIEW_CHAIN_FIELDS if schema_version == 2 else _REVIEW_OVERRIDE_FIELDS
    ):
        chain = load_review_decision_chain(
            run_root,
            episode_id=episode["episode_id"],
            expected_run_id=run["run_id"],
            expected_work_id=run["work_id"],
            expected_source_version_id=episode["source_version_id"],
            expected_source_sha256=episode["source_sha256"],
        )
        if not chain:
            raise ValueError("Translation review has no decision chain.")
        final_decision = chain[-1]
        if schema_version == 2:
            if final_decision["transition"]["status"] != "passed":
                raise ValueError("Translation review has no final passed decision.")
        else:
            if final_decision["transition"]["status"] != "needs_human":
                raise ValueError(
                    "Human override review requires a needs_human decision."
                )
            resolutions = load_review_resolution_chain(
                run_root,
                episode_id=episode["episode_id"],
            )
            human_resolution = next(
                (
                    item
                    for item in reversed(resolutions)
                    if item["decision_sha256"]
                    == final_decision["decision_sha256"]
                ),
                None,
            )
            if (
                human_resolution is None
                or human_resolution["action"] != "approve_current"
            ):
                raise ValueError(
                    "Human override review has no matching approval resolution."
                )
        expected = {
            "run_id": run["run_id"],
            "run_manifest_sha256": _sha256_bytes(run_bytes),
            "plan_sha256": run["plan_sha256"],
            "work_id": run["work_id"],
            "episode_id": episode["episode_id"],
            "position": episode["position"],
            "source_version_id": episode["source_version_id"],
            "source_input_file": episode["source_input_file"],
            "source_sha256": episode["source_sha256"],
            "candidate_revision": final_decision["candidate_revision"],
            "candidate_relative_path": final_decision[
                "candidate_relative_path"
            ],
            "candidate_sha256": final_decision["candidate_sha256"],
            "decision_sha256": final_decision["decision_sha256"],
        }
        if schema_version == 3:
            expected["resolution_sha256"] = human_resolution[
                "resolution_sha256"
            ]
        source_bytes = input_verifier(run, episode)
        candidate_bytes = _load_review_candidate(
            run_root,
            run,
            episode,
            source_bytes,
            final_decision,
        )
    else:
        raise ValueError("Translation review fields do not match its schema.")
    if isinstance(schema_version, bool) or schema_version not in {1, 2, 3}:
        raise ValueError("Translation review schema version is unsupported.")
    if any(review.get(key) != value for key, value in expected.items()):
        raise ValueError("Translation review does not match the current run.")
    if (
        review.get("decision") != "approved"
        or review.get("independence_confirmed") is not True
        or not isinstance(review.get("checks"), dict)
        or set(review["checks"]) != set(_REVIEW_CHECKS)
        or any(value != "pass" for value in review["checks"].values())
        or review.get("issues") != []
    ):
        raise ValueError("Translation review is not fully approved.")
    _require_text(review.get("reviewer_id"), "reviewer_id", maximum=200)
    _require_text(review.get("reviewed_at_utc"), "reviewed_at_utc", maximum=64)
    try:
        reviewed_at = datetime.fromisoformat(
            review["reviewed_at_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Translation review timestamp is invalid.") from exc
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() != timezone.utc.utcoffset(
        reviewed_at
    ):
        raise ValueError("Translation review timestamp must be UTC.")
    return review, review_bytes, candidate_bytes


def record_translation_review_decision(
    run_directory: str | Path,
    episode_id: str,
    *,
    stage_verdicts,
    issue_codes_by_stage=None,
    final_review_gate=None,
    reviewer_id: str,
    reviewed_at_utc: str,
    policy_sha256: str | None = None,
    review_policy_file: str | Path | None = None,
    max_rework_attempts: int | None = None,
    candidate_file: str | Path | None = None,
    reviewed_candidate_sha256: str | None = None,
) -> dict:
    """Append a content-free, hash-bound decision for one run candidate."""
    if (
        not isinstance(reviewed_candidate_sha256, str)
        or not _SHA256_PATTERN.fullmatch(reviewed_candidate_sha256)
    ):
        raise ValueError(
            "A valid reviewed candidate SHA-256 is required to record a decision."
        )
    policy_bytes = None
    if review_policy_file is not None:
        policy_bytes, file_policy_sha256, _ = read_review_policy_file(
            review_policy_file
        )
        if policy_sha256 is not None:
            if (
                not isinstance(policy_sha256, str)
                or not _SHA256_PATTERN.fullmatch(policy_sha256)
            ):
                raise ValueError("A valid policy SHA-256 or review policy file is required.")
            if not hmac.compare_digest(policy_sha256, file_policy_sha256):
                raise ValueError("Review policy file does not match policy_sha256.")
        policy_sha256 = file_policy_sha256
    if (
        not isinstance(policy_sha256, str)
        or not _SHA256_PATTERN.fullmatch(policy_sha256)
    ):
        raise ValueError(
            "A valid policy SHA-256 or review policy file is required."
        )
    if final_review_gate is not None and policy_bytes is None:
        raise ValueError(
            "AI final-review decisions require the immutable review policy file."
        )
    run_root, run, _ = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    source_bytes = _verify_current_inputs(run, episode)

    if candidate_file is None:
        candidate_bytes = _load_draft(run_root, run, episode, source_bytes)
        candidate_relative_path = (
            f"{run['draft_root']}/{episode['translation_file']}"
        )
    else:
        candidate_supplied_path = Path(candidate_file)
        if not candidate_supplied_path.is_absolute():
            candidate_supplied_path = run_root / candidate_supplied_path
        candidate_supplied_path = candidate_supplied_path.absolute()
        try:
            supplied_relative_path = candidate_supplied_path.relative_to(run_root)
        except ValueError as exc:
            raise ValueError(
                "Review candidate must remain inside the translation run."
            ) from exc
        candidate_relative_path = supplied_relative_path.as_posix()
        candidate_path = resolve_relative_path(
            str(run_root),
            candidate_relative_path,
        )
        if not candidate_path.is_file():
            raise ValueError("Review candidate must be a regular file.")
        with open_regular_file(candidate_path, binary=True) as stream:
            candidate_bytes = stream.read(_MAX_TRANSLATION_BYTES + 1)
        if len(candidate_bytes) > _MAX_TRANSLATION_BYTES:
            raise ValueError("Review candidate exceeds the configured size limit.")
        _validate_translation_bytes(
            source_bytes,
            candidate_bytes,
            "Review candidate",
        )

    chain = load_review_decision_chain(
        run_root,
        episode_id=episode_id,
        expected_run_id=run["run_id"],
        expected_work_id=run["work_id"],
        expected_source_version_id=episode["source_version_id"],
        expected_source_sha256=episode["source_sha256"],
    )
    if chain:
        previous = chain[-1]
        previous_status = previous["transition"]["status"]
        if previous_status == "rework":
            expected_budget = previous["max_rework_attempts"]
        elif previous_status == "needs_human":
            resolutions = load_review_resolution_chain(
                run_root,
                episode_id=episode_id,
            )
            resolution = next(
                (
                    item
                    for item in reversed(resolutions)
                    if item["decision_sha256"]
                    == previous["decision_sha256"]
                ),
                None,
            )
            if resolution is None or resolution["action"] != "increase_budget":
                raise ValueError(
                    "A new review decision requires an explicit budget extension."
                )
            expected_budget = resolution["new_max_rework_attempts"]
        else:
            raise ValueError(
                "A review decision can continue only after a rework transition."
            )
        if previous["policy_sha256"] != policy_sha256:
            raise ValueError("Review decision policy changed within one chain.")
        if (
            any(item["schema_version"] in {3, 4} for item in chain)
            and policy_bytes is None
        ):
            raise ValueError(
                "A policy-bound decision chain requires its policy file "
                "for every later decision."
            )
        effective_budget = (
            expected_budget
            if max_rework_attempts is None
            else max_rework_attempts
        )
        if expected_budget != effective_budget:
            raise ValueError("Review decision retry budget changed within one chain.")
        _load_review_candidate(
            run_root,
            run,
            episode,
            source_bytes,
            previous,
        )
        candidate_revision = previous["candidate_revision"] + 1
        parent_candidate_sha256 = previous["candidate_sha256"]
        if candidate_file is None:
            raise ValueError(
                "A rework decision requires a candidate file under "
                "ReviewCandidates/<episode_id>/."
            )
    else:
        effective_budget = 2 if max_rework_attempts is None else max_rework_attempts
        candidate_revision = 0
        parent_candidate_sha256 = None
        if candidate_relative_path != (
            f"{run['draft_root']}/{episode['translation_file']}"
        ):
            raise ValueError("Initial review decision must bind the run draft.")
        verified_draft = _load_draft(run_root, run, episode, source_bytes)
        if candidate_bytes != verified_draft:
            raise ValueError("Initial review decision must bind the verified run draft.")
        candidate_bytes = verified_draft

    candidate_sha256 = _sha256_bytes(candidate_bytes)
    if not hmac.compare_digest(
        candidate_sha256,
        reviewed_candidate_sha256,
    ):
        raise ValueError(
            "Review candidate changed after its digest was recorded for review."
        )
    record = create_review_decision_record(
        run_id=run["run_id"],
        work_id=run["work_id"],
        episode_id=episode["episode_id"],
        source_version_id=episode["source_version_id"],
        source_sha256=episode["source_sha256"],
        candidate_revision=candidate_revision,
        candidate_relative_path=candidate_relative_path,
        parent_candidate_sha256=parent_candidate_sha256,
        candidate_sha256=candidate_sha256,
        policy_sha256=policy_sha256,
        reviewer_id=reviewer_id,
        reviewed_at_utc=reviewed_at_utc,
        stage_verdicts=stage_verdicts,
        issue_codes_by_stage=issue_codes_by_stage,
        final_review_gate=final_review_gate,
        policy_relative_path=(
            f"ReviewPolicies/{policy_sha256}.json"
            if policy_bytes is not None
            else None
        ),
        max_rework_attempts=effective_budget,
    )
    if policy_bytes is not None:
        relative_path, stored_policy_sha256, _ = store_review_policy_artifact(
            run_root,
            policy_bytes,
            issue_codes_by_stage=issue_codes_by_stage,
        )
        if (
            stored_policy_sha256 != policy_sha256
            or relative_path != record["policy_relative_path"]
        ):
            raise ValueError("Stored review policy identity changed.")
    report = write_review_decision(run_root, record)
    report.update(
        {
            "episode_id": episode["episode_id"],
            "transition": record["transition"],
            "candidate_sha256": record["candidate_sha256"],
        }
    )
    return report


def resolve_translation_review(
    run_directory: str | Path,
    episode_id: str,
    *,
    action: str,
    reviewer_id: str,
    reviewed_at_utc: str,
    rationale: str,
    reviewed_decision_sha256: str,
    new_max_rework_attempts: int | None = None,
) -> dict:
    """Record a human resolution for the latest exhausted review candidate."""
    run_root, run, _ = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    source_bytes = _verify_current_inputs(run, episode)
    decisions = load_review_decision_chain(
        run_root,
        episode_id=episode_id,
        expected_run_id=run["run_id"],
        expected_work_id=run["work_id"],
        expected_source_version_id=episode["source_version_id"],
        expected_source_sha256=episode["source_sha256"],
    )
    if not decisions or decisions[-1]["transition"]["status"] != "needs_human":
        raise ValueError("Only the latest needs_human decision can be resolved.")
    final_decision = decisions[-1]
    if (
        not isinstance(reviewed_decision_sha256, str)
        or not _SHA256_PATTERN.fullmatch(reviewed_decision_sha256)
    ):
        raise ValueError("A valid reviewed decision SHA-256 is required.")
    if not hmac.compare_digest(
        final_decision["decision_sha256"],
        reviewed_decision_sha256,
    ):
        raise ValueError("Latest review decision changed; review it before resolving.")
    _load_review_candidate(
        run_root,
        run,
        episode,
        source_bytes,
        final_decision,
    )
    resolutions = load_review_resolution_chain(
        run_root,
        episode_id=episode_id,
    )
    record = create_review_resolution_record(
        final_decision,
        resolution_revision=len(resolutions),
        action=action,
        reviewer_id=reviewer_id,
        reviewed_at_utc=reviewed_at_utc,
        rationale=rationale,
        parent_resolution_sha256=(
            None
            if not resolutions
            else resolutions[-1]["resolution_sha256"]
        ),
        new_max_rework_attempts=new_max_rework_attempts,
    )
    report = write_review_resolution(run_root, record)
    report.update(
        {
            "episode_id": episode["episode_id"],
            "candidate_sha256": final_decision["candidate_sha256"],
            "decision_sha256": final_decision["decision_sha256"],
            "blocking_stages": record["blocking_stages"],
        }
    )
    return report


def _create_new_bytes_atomically(
    root: str,
    relative_path: str,
    content: bytes,
) -> bool:
    target = resolve_relative_path(root, relative_path, allow_missing=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, target)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _write_new_bytes_atomically(
    root: str,
    relative_path: str,
    content: bytes,
) -> bool:
    if _create_new_bytes_atomically(root, relative_path, content):
        return True
    target = resolve_relative_path(root, relative_path, allow_missing=True)
    with open_regular_file(target, binary=True) as stream:
        existing = stream.read(len(content) + 1)
    if existing != content:
        raise ValueError("Existing publication differs from reviewed draft.")
    return False


def _load_run_state(run_root: Path, run: dict) -> tuple[Path, dict | None]:
    state_path = run_root / "run_state.json"
    if state_path.is_symlink():
        raise ValueError("Translation run state cannot be a symbolic link.")
    if not state_path.exists():
        return state_path, None
    with open_regular_file(state_path, binary=True) as stream:
        state_bytes = stream.read(64 * 1024 + 1)
    try:
        state = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Translation run state is invalid.") from exc
    expected_common = {
        "schema_version": 1,
        "run_id": run["run_id"],
        "work_id": run["work_id"],
        "plan_sha256": run["plan_sha256"],
    }
    if (
        not isinstance(state, dict)
        or set(state) != (set(expected_common) | {"status"})
        or any(state.get(key) != value for key, value in expected_common.items())
        or state.get("status") not in {"running", "review_pending", "published"}
    ):
        raise ValueError("Translation run state does not match the run manifest.")
    return state_path, state


def _demote_published_run_if_needed(run_root: Path, run: dict) -> None:
    state_path, state = _load_run_state(run_root, run)
    if state is None or state.get("status") != "published":
        return
    state["status"] = "review_pending"
    write_text_atomically(
        str(state_path),
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


def _load_verified_publication_candidate(
    run_root: Path,
    run: dict,
    run_bytes: bytes,
    episode: dict,
    *,
    input_verifier=_verify_current_inputs,
) -> bytes | None:
    published_root = run_root / "Published"
    if not published_root.is_dir() or published_root.is_symlink():
        return None
    receipt_path = resolve_child_path(
        str(published_root),
        f"{episode['episode_id']}.json",
        allow_missing=True,
    )
    if not receipt_path.exists():
        return None
    receipt, _ = _read_json(
        receipt_path,
        _MAX_REVIEW_BYTES,
        "Publication receipt",
    )

    snapshots_root = published_root / "ReviewSnapshots"
    if snapshots_root.is_symlink():
        raise ValueError(
            "Publication review snapshot directory must not be a symbolic link."
        )
    if not snapshots_root.exists():
        return None
    if not snapshots_root.is_dir():
        raise ValueError(
            "Publication review snapshot path must be a directory."
        )
    snapshot_path = resolve_child_path(
        str(snapshots_root),
        f"{episode['episode_id']}.json",
        allow_missing=True,
    )
    if not snapshot_path.exists():
        return None
    review, review_bytes, candidate_bytes = _validate_approved_review(
        snapshot_path,
        run_root=run_root,
        run=run,
        run_bytes=run_bytes,
        episode=episode,
        input_verifier=input_verifier,
    )
    expected_receipt = {
        "schema_version": review["schema_version"],
        "status": "published",
        "run_id": run["run_id"],
        "work_id": run["work_id"],
        "episode_id": episode["episode_id"],
        "position": episode["position"],
        "translation_file": episode["translation_file"],
        "source_version_id": episode["source_version_id"],
        "source_sha256": episode["source_sha256"],
        "draft_sha256": episode["draft_sha256"],
    }
    if review["schema_version"] in {2, 3}:
        expected_receipt.update(
            {
                "candidate_revision": review["candidate_revision"],
                "candidate_relative_path": review["candidate_relative_path"],
                "candidate_sha256": review["candidate_sha256"],
                "decision_sha256": review["decision_sha256"],
            }
        )
        if review["schema_version"] == 3:
            expected_receipt["resolution_sha256"] = review[
                "resolution_sha256"
            ]
    if (
        set(receipt)
        != set(expected_receipt) | {"review_sha256", "published_at_utc"}
        or any(
            receipt.get(key) != value
            for key, value in expected_receipt.items()
        )
        or not isinstance(receipt.get("review_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(receipt["review_sha256"])
    ):
        raise ValueError("Publication receipt conflicts with the run manifest.")
    if not hmac.compare_digest(
        _sha256_bytes(review_bytes),
        receipt["review_sha256"],
    ):
        raise ValueError(
            "Publication review snapshot conflicts with its receipt."
        )
    try:
        published_at = datetime.fromisoformat(
            receipt["published_at_utc"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as exc:
        raise ValueError("Publication receipt has an invalid timestamp.") from exc
    if (
        published_at.tzinfo is None
        or published_at.utcoffset() != timezone.utc.utcoffset(published_at)
    ):
        raise ValueError("Publication receipt timestamp must be UTC.")
    return candidate_bytes


def _episode_has_valid_publication(
    run_root: Path,
    run: dict,
    run_bytes: bytes,
    episode: dict,
    *,
    input_verifier=_verify_current_inputs,
) -> bool:
    candidate_bytes = _load_verified_publication_candidate(
        run_root,
        run,
        run_bytes,
        episode,
        input_verifier=input_verifier,
    )
    if candidate_bytes is None:
        return False
    output_root = Path(run["translation_root"]).resolve(strict=True)
    output_path = resolve_relative_path(
        str(output_root),
        episode["translation_file"],
        allow_missing=True,
    )
    if not output_path.exists():
        return False
    with open_regular_file(output_path, binary=True) as stream:
        published_bytes = stream.read(_MAX_TRANSLATION_BYTES + 1)
    if published_bytes != candidate_bytes:
        raise FileExistsError(
            "Published translation differs from its reviewed candidate."
        )
    return True


def has_verified_translation_publication(
    runs_root: str | Path,
    *,
    work_id: str,
    episode_id: str,
    source_version_id: str,
    source_sha256: str,
    translation_file: str,
    translation_root: str | Path,
) -> bool:
    """Find a valid prior publication for one exact source and output target."""
    supplied_runs_root = Path(runs_root)
    if supplied_runs_root.is_symlink() or not supplied_runs_root.is_dir():
        return False
    try:
        expected_translation_root = Path(translation_root).resolve(strict=True)
        run_directories = sorted(
            supplied_runs_root.iterdir(),
            key=lambda item: item.name,
        )
    except OSError:
        return False
    if not expected_translation_root.is_dir():
        return False

    for candidate_run_root in run_directories:
        if candidate_run_root.is_symlink() or not candidate_run_root.is_dir():
            continue
        try:
            run_root, run, run_bytes = _load_run(candidate_run_root)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError):
            continue
        if run["work_id"] != work_id:
            continue
        try:
            episode = _run_episode(run, episode_id)
        except ValueError:
            continue
        if (
            episode["source_version_id"] != source_version_id
            or episode["source_sha256"] != source_sha256
            or episode["translation_file"] != translation_file
        ):
            continue
        try:
            run_translation_root = Path(run["translation_root"]).resolve(
                strict=True
            )
            if run_translation_root != expected_translation_root:
                continue
            if _episode_has_valid_publication(
                run_root,
                run,
                run_bytes,
                episode,
                input_verifier=_verify_historical_publication_inputs,
            ):
                return True
        except (OSError, UnicodeError, ValueError, TypeError, KeyError):
            continue
    return False


def _mark_run_published_if_complete(
    run_root: Path, run: dict, run_bytes: bytes
) -> str | None:
    """Advance run state only while every publication artifact still matches."""

    _demote_published_run_if_needed(run_root, run)
    state_path, state = _load_run_state(run_root, run)
    if state is None:
        # Older hand-created manifests did not persist a lifecycle state file.
        return None

    if not (run_root / "Published").is_dir() or (
        run_root / "Published"
    ).is_symlink():
        target_status = "review_pending"
    else:
        complete = True
        for episode in run["episodes"]:
            if not _episode_has_valid_publication(
                run_root,
                run,
                run_bytes,
                episode,
            ):
                complete = False
                break
        target_status = "published" if complete else "review_pending"

    if state.get("status") != target_status:
        state["status"] = target_status
        write_text_atomically(
            str(state_path),
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        )
    return target_status


def publish_reviewed_translation(
    run_directory: str | Path,
    episode_id: str,
    review_file: str | Path,
    *,
    reconcile_run: bool = True,
) -> dict:
    run_root, run, run_bytes = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    review_path = Path(review_file).resolve(strict=True)
    review, review_bytes, candidate_bytes = _validate_approved_review(
        review_path,
        run_root=run_root,
        run=run,
        run_bytes=run_bytes,
        episode=episode,
    )
    _demote_published_run_if_needed(run_root, run)
    output_root = Path(run["translation_root"]).resolve(strict=True)
    output_target = resolve_relative_path(
        str(output_root),
        episode["translation_file"],
        allow_missing=True,
    )
    if output_target.exists():
        with open_regular_file(output_target, binary=True) as stream:
            existing = stream.read(_MAX_TRANSLATION_BYTES + 1)
        if existing != candidate_bytes:
            raise FileExistsError(
                "Existing published translation differs from the approved candidate."
            )
        created = False
    else:
        created = False

    published_root = run_root / "Published"
    if published_root.is_symlink():
        raise ValueError("Publication receipt directory must not be a symbolic link.")
    review_snapshots_root = published_root / "ReviewSnapshots"
    if review_snapshots_root.is_symlink():
        raise ValueError(
            "Publication review snapshot directory must not be a symbolic link."
        )
    if published_root.exists() and not published_root.is_dir():
        raise ValueError("Publication receipt path must be a directory.")
    if review_snapshots_root.exists() and not review_snapshots_root.is_dir():
        raise ValueError("Publication review snapshot path must be a directory.")

    receipt = {
        "schema_version": review["schema_version"],
        "status": "published",
        "run_id": run["run_id"],
        "work_id": run["work_id"],
        "episode_id": episode["episode_id"],
        "position": episode["position"],
        "translation_file": episode["translation_file"],
        "source_version_id": episode["source_version_id"],
        "source_sha256": episode["source_sha256"],
        "draft_sha256": episode["draft_sha256"],
        "review_sha256": _sha256_bytes(review_bytes),
        "published_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    if review["schema_version"] in {2, 3}:
        receipt.update(
            {
                "candidate_revision": review["candidate_revision"],
                "candidate_relative_path": review["candidate_relative_path"],
                "candidate_sha256": review["candidate_sha256"],
                "decision_sha256": review["decision_sha256"],
            }
        )
        if review["schema_version"] == 3:
            receipt["resolution_sha256"] = review["resolution_sha256"]
    receipt_name = f"{episode['episode_id']}.json"
    serialized_receipt = _canonical_json(receipt)
    stable_receipt_fields = {
        key: value
        for key, value in receipt.items()
        if key != "published_at_utc"
    }

    review_snapshot_created = False
    if review_snapshots_root.is_dir():
        snapshot_path = resolve_child_path(
            str(review_snapshots_root),
            f"{episode['episode_id']}.json",
            allow_missing=True,
        )
        if snapshot_path.exists():
            with open_regular_file(snapshot_path, binary=True) as stream:
                existing_review = stream.read(_MAX_REVIEW_BYTES + 1)
            if existing_review != review_bytes:
                raise ValueError("Existing publication review snapshot differs.")

    receipt_created = False
    if published_root.is_dir():
        receipt_path = resolve_child_path(
            str(published_root),
            receipt_name,
            allow_missing=True,
        )
        if receipt_path.exists():
            existing_receipt, _ = _read_json(
                receipt_path,
                _MAX_REVIEW_BYTES,
                "Publication receipt",
            )
            if any(
                existing_receipt.get(key) != value
                for key, value in stable_receipt_fields.items()
            ):
                raise ValueError("Existing publication receipt conflicts with this run.")

    created = _write_new_bytes_atomically(
        str(output_root),
        episode["translation_file"],
        candidate_bytes,
    )

    published_root.mkdir(exist_ok=True)
    review_snapshots_root.mkdir(exist_ok=True)
    review_snapshot_created = _write_new_bytes_atomically(
        str(review_snapshots_root),
        f"{episode['episode_id']}.json",
        review_bytes,
    )
    receipt_created = _create_new_bytes_atomically(
        str(published_root),
        receipt_name,
        serialized_receipt.encode("utf-8"),
    )
    if not receipt_created:
        existing_receipt, _ = _read_json(
            resolve_child_path(
                str(published_root),
                receipt_name,
                allow_missing=True,
            ),
            _MAX_REVIEW_BYTES,
            "Publication receipt",
        )
        if any(
            existing_receipt.get(key) != value
            for key, value in stable_receipt_fields.items()
        ):
            raise ValueError("Existing publication receipt conflicts with this run.")

    run_status = (
        _mark_run_published_if_complete(run_root, run, run_bytes)
        if reconcile_run
        else None
    )
    return {
        "status": "published",
        "episode_id": episode_id,
        "translation_file": episode["translation_file"],
        "created": created,
        "receipt_created": receipt_created,
        "review_snapshot_created": review_snapshot_created,
        "run_status": run_status,
        "draft_sha256": episode["draft_sha256"],
        "candidate_sha256": _sha256_bytes(candidate_bytes),
    }


def publish_reviewed_run(
    run_directory: str | Path,
    *,
    review_directory: str = "Reviews",
) -> dict:
    """Publish all available approved reviews while preserving partial progress."""

    run_root, run, run_bytes = _load_run(run_directory)
    reviews_root = resolve_relative_path(
        str(run_root),
        review_directory,
        allow_missing=True,
    )
    if reviews_root.is_symlink():
        raise ValueError("Review directory must not be a symbolic link.")
    reviews_root_exists = reviews_root.is_dir()
    _demote_published_run_if_needed(run_root, run)
    published = []
    pending = []
    failed = []
    for episode in sorted(run["episodes"], key=lambda item: item["position"]):
        if not reviews_root_exists:
            review_path = None
        else:
            review_path = resolve_child_path(
                str(reviews_root),
                f"{episode['episode_id']}.json",
                allow_missing=True,
            )
        if review_path is None or not review_path.exists():
            restored_output = False
            try:
                candidate_bytes = _load_verified_publication_candidate(
                    run_root,
                    run,
                    run_bytes,
                    episode,
                )
                if candidate_bytes is not None:
                    output_root = Path(run["translation_root"]).resolve(
                        strict=True
                    )
                    output_path = resolve_relative_path(
                        str(output_root),
                        episode["translation_file"],
                        allow_missing=True,
                    )
                    if not output_path.exists():
                        restored_output = _write_new_bytes_atomically(
                            str(output_root),
                            episode["translation_file"],
                            candidate_bytes,
                        )
                already_published = _episode_has_valid_publication(
                    run_root,
                    run,
                    run_bytes,
                    episode,
                )
            except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
                failed.append(
                    {
                        "episode_id": episode["episode_id"],
                        "position": episode["position"],
                        "error": type(exc).__name__,
                    }
                )
                continue
            if already_published:
                published.append(
                    {
                        "episode_id": episode["episode_id"],
                        "position": episode["position"],
                        "created": restored_output,
                        "receipt_created": False,
                        "review_snapshot_created": False,
                        "run_status": None,
                    }
                )
            else:
                pending.append(
                    {
                        "episode_id": episode["episode_id"],
                        "position": episode["position"],
                        "reason": "review_missing",
                    }
                )
            continue
        try:
            report = publish_reviewed_translation(
                run_root,
                episode["episode_id"],
                review_path,
                reconcile_run=False,
            )
        except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
            failed.append(
                {
                    "episode_id": episode["episode_id"],
                    "position": episode["position"],
                    "error": type(exc).__name__,
                }
            )
            continue
        published.append(
            {
                "episode_id": report["episode_id"],
                "position": episode["position"],
                "created": report["created"],
                "receipt_created": report["receipt_created"],
                "review_snapshot_created": report["review_snapshot_created"],
                "run_status": report["run_status"],
            }
        )

    run_status = None
    if failed:
        _, state = _load_run_state(run_root, run)
        run_status = state.get("status") if state is not None else None
    else:
        try:
            run_status = _mark_run_published_if_complete(
                run_root,
                run,
                run_bytes,
            )
        except (OSError, UnicodeError, ValueError, FileExistsError, KeyError) as exc:
            failed.append(
                {
                    "episode_id": None,
                    "position": None,
                    "scope": "run",
                    "error": type(exc).__name__,
                }
            )
    for item in published:
        item["run_status"] = run_status

    if failed:
        status = "blocked"
    elif pending:
        status = "review_pending"
    else:
        status = (
            "review_pending"
            if run_status == "review_pending"
            else "published"
        )
    return {
        "status": status,
        "run_id": run["run_id"],
        "published_count": len(published),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "published": published,
        "pending": pending,
        "failed": failed,
    }
