"""Version-bound human review and create-only translation publication."""

import hashlib
import hmac
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from source_editions import read_verified_ai_edition_bytes, verify_ai_edition_index
from source_manifest import verify_current_normalized_source_metadata
from utils import (
    open_regular_file,
    require_aligned_paragraphs,
    resolve_child_path,
    resolve_relative_path,
    split_paragraphs,
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
            or episode["draft_bytes"] < 1
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


def _verify_current_inputs(run: dict, episode: dict) -> bytes:
    source_root = Path(run["source_root"]).resolve(strict=True)
    ai_root = Path(run["ai_root"]).resolve(strict=True)
    index_result = verify_ai_edition_index(
        source_root=str(source_root),
        ai_root=str(ai_root),
        source_manifest_relative_path=run["source_manifest"],
        edition_manifest_relative_path=run["edition_manifest"],
        index_relative_path=run["ai_index"],
    )
    if index_result["index_sha256"] != run["ai_index_sha256"]:
        raise ValueError("AI edition index changed after translation.")
    if (
        index_result["index"].get("catalog", {}).get("relative_path")
        != run["catalog"]
    ):
        raise ValueError("Translation run catalog differs from the AI edition.")
    book_bundle = run["book_bundle"]
    if book_bundle is not None:
        source_root_path = Path(run["source_root"]).resolve(strict=True)
        set_path = resolve_relative_path(
            str(source_root_path),
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
        with open_regular_file(ai_bundle_path, binary=True) as stream:
            ai_bundle_bytes = stream.read(_MAX_RUN_BYTES + 1)
        if (
            len(ai_bundle_bytes) > _MAX_RUN_BYTES
            or not hmac.compare_digest(
                _sha256_bytes(ai_bundle_bytes),
                book_bundle["ai_bundle_sha256"],
            )
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
    source_bytes = read_verified_ai_edition_bytes(
        str(ai_root),
        episode["source_input_file"],
        episode["source_sha256"],
    )
    return source_bytes


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
    try:
        source_text = source_bytes.decode("utf-8")
        translation_text = draft_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Translation source and draft must be UTF-8.") from exc
    source_paragraphs = split_paragraphs(source_text)
    translated_paragraphs = split_paragraphs(translation_text)
    require_aligned_paragraphs(
        source_paragraphs,
        translated_paragraphs,
        "Reviewed translation",
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
    return draft_bytes


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
    _load_draft(run_root, run, episode, source_bytes)
    reviews_root = resolve_relative_path(
        str(run_root),
        review_directory,
        allow_missing=True,
    )
    if reviews_root.is_symlink():
        raise ValueError("Review directory must not be a symbolic link.")
    reviews_root.mkdir(exist_ok=True)
    resolve_relative_path(str(run_root), review_directory)
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
        "reviewer_id": "",
        "independence_confirmed": False,
        "reviewed_at_utc": "",
        "decision": "pending",
        "checks": {name: "pending" for name in _REVIEW_CHECKS},
        "issues": [],
        "notes": "",
    }
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
    return {
        "status": "review_template_ready",
        "episode_id": episode_id,
        "review_path": str(review_path),
        "created": created,
        "draft_sha256": episode["draft_sha256"],
    }


def _validate_approved_review(
    review_path: Path,
    *,
    run_root: Path,
    run: dict,
    run_bytes: bytes,
    episode: dict,
) -> tuple[dict, bytes]:
    review, review_bytes = _read_json(
        review_path,
        _MAX_REVIEW_BYTES,
        "Translation review",
    )
    if set(review) != _REVIEW_FIELDS:
        raise ValueError("Translation review fields do not match schema v1.")
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
    if any(review.get(key) != value for key, value in expected.items()):
        raise ValueError("Translation review does not match the current run.")
    if (
        isinstance(review.get("schema_version"), bool)
        or review.get("schema_version") != 1
        or review.get("decision") != "approved"
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
    source_bytes = _verify_current_inputs(run, episode)
    draft_bytes = _load_draft(run_root, run, episode, source_bytes)
    return review, review_bytes


def _write_new_bytes_atomically(root: str, relative_path: str, content: bytes) -> bool:
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
            with open_regular_file(target, binary=True) as stream:
                existing = stream.read(len(content) + 1)
            if existing != content:
                raise ValueError("Existing publication differs from reviewed draft.")
            return False
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def publish_reviewed_translation(
    run_directory: str | Path,
    episode_id: str,
    review_file: str | Path,
) -> dict:
    run_root, run, run_bytes = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    review_path = Path(review_file).resolve(strict=True)
    review, review_bytes = _validate_approved_review(
        review_path,
        run_root=run_root,
        run=run,
        run_bytes=run_bytes,
        episode=episode,
    )
    del review
    output_root = Path(run["translation_root"]).resolve(strict=True)
    output_target = resolve_relative_path(
        str(output_root),
        episode["translation_file"],
        allow_missing=True,
    )
    if output_target.exists():
        with open_regular_file(output_target, binary=True) as stream:
            existing = stream.read(_MAX_TRANSLATION_BYTES + 1)
        if existing != _load_draft(
            run_root,
            run,
            episode,
            _verify_current_inputs(run, episode),
        ):
            raise FileExistsError(
                "Existing published translation differs from the approved draft."
            )
        created = False
    else:
        source_bytes = _verify_current_inputs(run, episode)
        draft_bytes = _load_draft(run_root, run, episode, source_bytes)
        created = _write_new_bytes_atomically(
            str(output_root),
            episode["translation_file"],
            draft_bytes,
        )

    published_root = run_root / "Published"
    if published_root.is_symlink():
        raise ValueError("Publication receipt directory must not be a symbolic link.")
    published_root.mkdir(exist_ok=True)
    receipt = {
        "schema_version": 1,
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
    receipt_name = f"{episode['episode_id']}.json"
    receipt_path = resolve_child_path(
        str(published_root),
        receipt_name,
        allow_missing=True,
    )
    serialized_receipt = _canonical_json(receipt)
    try:
        write_new_child_text(
            str(published_root),
            receipt_name,
            serialized_receipt,
        )
        receipt_created = True
    except FileExistsError:
        existing_receipt, _ = _read_json(
            receipt_path,
            _MAX_REVIEW_BYTES,
            "Publication receipt",
        )
        stable_fields = {
            key: value
            for key, value in receipt.items()
            if key != "published_at_utc"
        }
        if any(existing_receipt.get(key) != value for key, value in stable_fields.items()):
            raise ValueError("Existing publication receipt conflicts with this run.")
        receipt_created = False
    return {
        "status": "published",
        "episode_id": episode_id,
        "translation_file": episode["translation_file"],
        "created": created,
        "receipt_created": receipt_created,
        "draft_sha256": episode["draft_sha256"],
    }
