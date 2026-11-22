"""Export version-bound raw, AI, and human book snapshots."""

import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path

from scripts.ingest_kakuyomu_pages import (
    _load_catalog_snapshot,
    _reject_duplicate_keys,
)
from source_editions import (
    DEFAULT_EDITION_MANIFEST,
    _load_source_edition_index,
    _sha256_bytes,
    read_verified_ai_edition_bytes,
    validate_source_editions,
)
from source_ingestion import (
    CHECKPOINT_SCHEMA_VERSION,
    DEFAULT_MAX_EPISODE_BYTES,
    _latest_artifact,
    _latest_raw_for_metadata,
    _load_episode_metadata,
    _read_checkpoint,
    _read_manifested_artifact_bytes,
    _source_artifact_id,
)
from source_manifest import load_manifest, verify_manifest_artifact
from utils import (
    open_regular_file,
    resolve_relative_path,
)


DEFAULT_MAX_TOTAL_SOURCE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_TOTAL_OUTPUT_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_TOTAL_BUNDLE_BYTES = 512 * 1024 * 1024
_HUMAN_BUNDLE_MARKER = "<!-- translation-workflow-human-bundle:v1\n"
_HUMAN_BUNDLE_END = "\n-->\n"


def _canonical_json_bytes(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open_regular_file(path, binary=True) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_output_directory(root: Path, relative_directory: str) -> None:
    current = root
    components = relative_directory.split("/")
    prefix = []
    for component in components:
        prefix.append(component)
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in bundle outputs.")
        current = current / component
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in bundle outputs.")
        try:
            current.mkdir()
        except FileExistsError:
            if not current.is_dir():
                raise ValueError("Bundle output parent is not a directory.")
        resolve_relative_path(
            str(root),
            "/".join(prefix),
            allow_missing=True,
        )


def _write_immutable(root: Path, relative_path: str, content: bytes) -> bool:
    """Create a file once, or accept an identical file left by a prior run."""
    target = resolve_relative_path(
        str(root),
        relative_path,
        allow_missing=True,
    )
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
            pass
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass

    existing = bytearray()
    with open_regular_file(target, binary=True) as stream:
        while True:
            chunk = stream.read(
                min(1024 * 1024, len(content) + 1 - len(existing))
            )
            if not chunk:
                break
            existing.extend(chunk)
            if len(existing) > len(content):
                break
    if bytes(existing) != content:
        raise ValueError("Existing immutable book bundle differs.")
    return False


def _load_complete_checkpoint(
    source_root: Path,
    *,
    work_id: str,
    manifest_relative_path: str,
    checkpoint_relative_path: str,
    episode_ids: list[str],
) -> dict:
    manifest_path = resolve_relative_path(
        str(source_root),
        manifest_relative_path,
    )
    checkpoint_path = resolve_relative_path(
        str(source_root),
        checkpoint_relative_path,
    )
    if (
        manifest_path.relative_to(source_root).as_posix().casefold()
        == checkpoint_path.relative_to(source_root).as_posix().casefold()
    ):
        raise ValueError("Manifest and checkpoint paths must be different.")
    checkpoint = _read_checkpoint(checkpoint_path)
    if (
        checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION
        or checkpoint["work_id"] != work_id
        or checkpoint["manifest_relative_path"]
        != manifest_path.relative_to(source_root).as_posix()
        or checkpoint["status"] != "complete"
        or checkpoint["discovered_episode_ids"] != episode_ids
        or checkpoint["completed_episode_ids"] != episode_ids
    ):
        raise ValueError(
            "Book bundle requires a complete current checkpoint for the catalog."
        )
    return checkpoint


def _metadata_provenance(work_metadata: dict) -> dict:
    source_url = work_metadata["source_url"]
    fields = {}
    for field, value in work_metadata.items():
        fields[field] = {
            "status": "observed" if value is not None else "unavailable_or_not_exposed",
            "source_url": source_url,
        }
    return {
        "scope": "fields_exposed_by_kakuyomu_catalog_schema_v3",
        "unknown_fields": "not represented by the catalog schema",
        "fields": fields,
    }


def _latest_html_reference(
    source_root: Path,
    manifest: dict,
    *,
    work_id: str,
    episode_id: str,
    metadata_version_id: str,
    raw_version_id: str,
) -> dict | None:
    artifact_id = _source_artifact_id(work_id, "raw_page_html", episode_id)
    artifact = _latest_artifact(manifest, artifact_id)
    if artifact is None or not {
        metadata_version_id,
        raw_version_id,
    } <= set(artifact["parent_version_ids"]):
        return None
    verified = verify_manifest_artifact(
        source_root,
        manifest,
        artifact["version_id"],
    )
    return {
        "version_id": verified["version_id"],
        "sha256": verified["content_sha256"],
        "relative_path": verified["relative_path"],
    }


def _build_human_bundle(
    *,
    snapshot_id: str,
    bundle_id: str,
    work_id: str,
    work_metadata: dict,
    metadata_provenance: dict,
    catalog_sha256: str,
    groups: list[dict],
    episodes: list[dict],
    body_by_episode_id: dict[str, bytes],
    profile: dict,
) -> bytes:
    index = {
        "schema_version": 1,
        "edition": "human_reading",
        "bundle_id": bundle_id,
        "source_snapshot_id": snapshot_id,
        "work_id": work_id,
        "work_metadata": work_metadata,
        "work_metadata_provenance": metadata_provenance,
        "catalog_sha256": catalog_sha256,
        "cleaning_profile": profile,
        "groups": groups,
        "episodes": [
            {
                "episode_id": episode["episode_id"],
                "position": episode["position"],
                "group_id": episode["group_id"],
                "title": episode["title"],
                "source_ref": episode["source_ref"],
                "raw_source_version_id": episode["raw_source_version_id"],
                "raw_source_sha256": episode["raw_source_sha256"],
                "edition_version_id": episode["edition_version_id"],
                "content_sha256": episode["content_sha256"],
                "body_marker_index": index,
            }
            for index, episode in enumerate(episodes, start=1)
        ],
    }
    parts = [
        _HUMAN_BUNDLE_MARKER.encode("ascii"),
        _canonical_json_bytes(index),
        _HUMAN_BUNDLE_END.encode("ascii"),
        f"# {html.escape(work_metadata['title'], quote=False)}\n\n".encode("utf-8"),
    ]
    group_by_id = {group["group_id"]: group for group in groups}
    current_group_id = None
    for index, episode in enumerate(episodes, start=1):
        group_id = episode["group_id"]
        if group_id != current_group_id:
            group = group_by_id[group_id]
            heading = group["title"] or group["chapter_id"] or group_id
            parts.append(
                f"## {html.escape(str(heading), quote=False)}\n\n".encode("utf-8")
            )
            current_group_id = group_id
        title = html.escape(episode["title"] or episode["episode_id"], quote=False)
        parts.append(
            f"### {episode['position']}. {title}\n\n"
            f"<!-- episode:start:{index} -->\n".encode("utf-8")
        )
        parts.append(body_by_episode_id[episode["episode_id"]])
        if not body_by_episode_id[episode["episode_id"]].endswith(b"\n"):
            parts.append(b"\n")
        parts.append(f"<!-- episode:end:{index} -->\n\n".encode("ascii"))
    return b"".join(parts)


def export_book_bundles(
    *,
    source_root: str,
    catalog_relative_path: str,
    human_root: str,
    ai_root: str,
    checkpoint_relative_path: str,
    manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = DEFAULT_EDITION_MANIFEST,
    ai_index_relative_path: str = "catalog.json",
    human_index_relative_path: str = "SOURCE_MAP.json",
    max_total_source_bytes: int = DEFAULT_MAX_TOTAL_SOURCE_BYTES,
    max_total_output_bytes: int = DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
) -> dict:
    """Create self-contained book editions from one fully verified catalog snapshot."""
    if (
        isinstance(max_total_source_bytes, bool)
        or not isinstance(max_total_source_bytes, int)
        or max_total_source_bytes < 1
        or isinstance(max_total_output_bytes, bool)
        or not isinstance(max_total_output_bytes, int)
        or max_total_output_bytes < 1
    ):
        raise ValueError("Book bundle byte limits must be positive integers.")

    source_path = Path(source_root).resolve(strict=True)
    human_path = Path(human_root).resolve(strict=True)
    ai_path = Path(ai_root).resolve(strict=True)
    if not all(path.is_dir() for path in (source_path, human_path, ai_path)):
        raise ValueError("Source and edition roots must be directories.")

    edition_report = validate_source_editions(
        source_root=str(source_path),
        catalog_relative_path=catalog_relative_path,
        human_root=str(human_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
        human_index_relative_path=human_index_relative_path,
        ai_index_relative_path=ai_index_relative_path,
    )
    catalog = _load_catalog_snapshot(
        str(source_path),
        catalog_relative_path,
    )
    if catalog["schema_version"] != 3 or not isinstance(
        catalog["work_metadata"], dict
    ):
        raise ValueError(
            "Book bundles require catalog schema v3 with captured work metadata."
        )
    work_metadata = catalog["work_metadata"]
    public_count = work_metadata["public_episode_count"]
    episode_ids = [
        episode.metadata.episode_id for episode in catalog["episodes"]
    ]
    if public_count != len(episode_ids) or not catalog["chapters"]:
        raise ValueError(
            "Book bundles require chapter groups covering the declared public catalog."
        )

    manifest_path = resolve_relative_path(
        str(source_path),
        manifest_relative_path,
    )
    edition_manifest_path = resolve_relative_path(
        str(source_path),
        edition_manifest_relative_path,
    )
    catalog_path = resolve_relative_path(
        str(source_path),
        catalog_relative_path,
    )
    manifest_sha256 = _sha256_file(manifest_path)
    edition_manifest_sha256 = _sha256_file(edition_manifest_path)
    catalog_sha256 = catalog["sha256"]
    source_manifest = load_manifest(manifest_path)
    checkpoint_path = resolve_relative_path(
        str(source_path),
        checkpoint_relative_path,
    )
    checkpoint_sha256 = _sha256_file(checkpoint_path)
    checkpoint = _load_complete_checkpoint(
        source_path,
        work_id=catalog["work_id"],
        manifest_relative_path=manifest_relative_path,
        checkpoint_relative_path=checkpoint_relative_path,
        episode_ids=episode_ids,
    )
    checkpoint_raw_versions = checkpoint["completed_raw_versions"]
    from source_editions import verify_ai_edition_index

    ai_result = verify_ai_edition_index(
        source_root=str(source_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
        index_relative_path=ai_index_relative_path,
    )
    ai_index = ai_result["index"]
    human_index, human_index_sha256 = _load_source_edition_index(
        human_path,
        human_index_relative_path,
        edition="human_reading",
    )
    ai_index_path = resolve_relative_path(
        str(ai_path),
        ai_index_relative_path,
    )
    human_index_path = resolve_relative_path(
        str(human_path),
        human_index_relative_path,
    )
    ai_by_id = ai_result["episodes_by_id"]
    human_by_id = {
        episode["episode_id"]: episode
        for episode in human_index["episodes"]
    }
    if len(human_by_id) != len(human_index["episodes"]):
        raise ValueError("Human edition index contains duplicate episodes.")

    work_artifact_id = _source_artifact_id(
        catalog["work_id"],
        "work",
        "metadata",
    )
    work_artifact = _latest_artifact(source_manifest, work_artifact_id)
    if work_artifact is None or work_artifact["kind"] != "work":
        raise ValueError("Book bundles require versioned work metadata.")
    verified_work_artifact = verify_manifest_artifact(
        source_path,
        source_manifest,
        work_artifact["version_id"],
    )
    work_bytes = _read_manifested_artifact_bytes(
        source_path,
        verified_work_artifact,
        max_bytes=4 * 1024 * 1024,
    )
    try:
        work_record = json.loads(
            work_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Archived work metadata is invalid.") from exc
    if (
        not isinstance(work_record, dict)
        or work_record.get("schema_version") != 1
        or work_record.get("work_id") != catalog["work_id"]
        or work_record.get("metadata") != work_metadata
    ):
        raise ValueError("Catalog work metadata does not match its archived version.")

    groups = [
        {
            "group_id": group["group_id"],
            "chapter_id": group["chapter_id"],
            "title": group["title"],
            "level": group["level"],
            "position_start": group["position_start"],
            "position_end": group["position_end"],
            "episode_ids": list(group["episode_ids"]),
        }
        for group in catalog["chapters"]
    ]
    group_by_episode = {
        episode_id: group
        for group in catalog["chapters"]
        for episode_id in group["episode_ids"]
    }
    raw_episodes = []
    ai_episodes = []
    human_episodes = []
    human_body_by_id = {}
    source_identity_episodes = []
    verified_input_files = [
        (
            source_path,
            verified_work_artifact["relative_path"],
            verified_work_artifact["content_sha256"],
        )
    ]
    total_source_bytes = 0

    for catalog_episode in catalog["episodes"]:
        metadata = catalog_episode.metadata
        episode_id = metadata.episode_id
        group = group_by_episode.get(episode_id)
        if group is None:
            raise ValueError("Catalog episode is missing its chapter group.")
        metadata_artifact, recorded_metadata = _load_episode_metadata(
            source_path,
            source_manifest,
            work_id=catalog["work_id"],
            episode_id=episode_id,
        )
        if (
            recorded_metadata["title"] != metadata.title
            or recorded_metadata["position"] != metadata.position
            or checkpoint_raw_versions.get(episode_id) is None
        ):
            raise ValueError("Catalog episode metadata is stale for the checkpoint.")
        raw_artifact = _latest_raw_for_metadata(
            source_manifest,
            work_id=catalog["work_id"],
            episode_id=episode_id,
            metadata_artifact=metadata_artifact,
        )
        if checkpoint_raw_versions[episode_id] != raw_artifact["version_id"]:
            raise ValueError("Checkpoint raw source is stale for the current catalog.")
        raw_bytes = _read_manifested_artifact_bytes(
            source_path,
            raw_artifact,
            max_bytes=DEFAULT_MAX_EPISODE_BYTES,
        )
        verified_input_files.append(
            (
                source_path,
                raw_artifact["relative_path"],
                raw_artifact["content_sha256"],
            )
        )
        total_source_bytes += len(raw_bytes)
        if total_source_bytes > max_total_source_bytes:
            raise ValueError("Book bundle source exceeds the configured byte limit.")
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Book bundle source is not valid UTF-8.") from exc
        if raw_text.encode("utf-8") != raw_bytes:
            raise ValueError("Book bundle source is not byte-preserving UTF-8.")

        ai_episode = ai_by_id.get(episode_id)
        human_episode = human_by_id.get(episode_id)
        if ai_episode is None or human_episode is None:
            raise ValueError("Edition indexes do not cover the complete catalog.")
        ai_bytes = read_verified_ai_edition_bytes(
            str(ai_path),
            ai_episode["ai_relative_path"],
            ai_episode["output_sha256"],
            max_bytes=DEFAULT_MAX_EPISODE_BYTES,
        )
        verified_input_files.append(
            (
                ai_path,
                ai_episode["ai_relative_path"],
                ai_episode["output_sha256"],
            )
        )
        human_path_for_episode = resolve_relative_path(
            str(human_path),
            human_episode["human_relative_path"],
        )
        with open_regular_file(human_path_for_episode, binary=True) as stream:
            human_bytes = stream.read(DEFAULT_MAX_EPISODE_BYTES + 1)
        if (
            len(human_bytes) > DEFAULT_MAX_EPISODE_BYTES
            or _sha256_bytes(human_bytes) != human_episode["output_sha256"]
        ):
            raise ValueError("Human edition does not match its verified index.")
        verified_input_files.append(
            (
                human_path,
                human_episode["human_relative_path"],
                human_episode["output_sha256"],
            )
        )
        try:
            ai_text = ai_bytes.decode("utf-8")
            human_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Book edition is not valid UTF-8.") from exc

        html_reference = _latest_html_reference(
            source_path,
            source_manifest,
            work_id=catalog["work_id"],
            episode_id=episode_id,
            metadata_version_id=metadata_artifact["version_id"],
            raw_version_id=raw_artifact["version_id"],
        )
        common = {
            "episode_id": episode_id,
            "position": metadata.position,
            "group_id": group["group_id"],
            "chapter_id": group["chapter_id"],
            "chapter_title": group["title"],
            "title": metadata.title,
            "page_url": catalog_episode.page_url,
            "source_ref": recorded_metadata["source_ref"],
            "episode_metadata_version_id": metadata_artifact["version_id"],
            "raw_source_version_id": raw_artifact["version_id"],
            "raw_source_sha256": raw_artifact["content_sha256"],
            "raw_page_html": html_reference,
        }
        raw_episodes.append(
            {
                **common,
                "source_text": raw_text,
            }
        )
        ai_episodes.append(
            {
                **common,
                "source_version_id": ai_episode["source_version_id"],
                "source_input_file": ai_episode["ai_relative_path"],
                "source_sha256": ai_episode["output_sha256"],
                "source_edition_version_id": ai_episode[
                    "ai_edition_version_id"
                ],
                "source_edition_sha256": ai_episode["output_sha256"],
                "source_text": ai_text,
            }
        )
        human_record = {
            **common,
            "edition_version_id": human_episode[
                "human_edition_version_id"
            ],
            "content_sha256": human_episode["output_sha256"],
        }
        human_episodes.append(human_record)
        human_body_by_id[episode_id] = human_bytes
        source_identity_episodes.append(
            {
                key: common[key]
                for key in (
                    "episode_id",
                    "position",
                    "group_id",
                    "chapter_id",
                    "title",
                    "page_url",
                    "source_ref",
                    "episode_metadata_version_id",
                    "raw_source_version_id",
                    "raw_source_sha256",
                    "raw_page_html",
                )
            }
        )

    if (
        _sha256_file(manifest_path) != manifest_sha256
        or _sha256_file(edition_manifest_path) != edition_manifest_sha256
        or _sha256_file(catalog_path) != catalog_sha256
        or _sha256_file(checkpoint_path) != checkpoint_sha256
        or ai_result["index_sha256"] != _sha256_file(ai_index_path)
        or human_index_sha256
        != _sha256_file(human_index_path)
    ):
        raise RuntimeError("Book bundle inputs changed during export.")
    for input_root, relative_path, expected_sha256 in verified_input_files:
        if _sha256_file(
            resolve_relative_path(str(input_root), relative_path)
        ) != expected_sha256:
            raise RuntimeError("Book bundle source files changed during export.")

    metadata_provenance = _metadata_provenance(work_metadata)
    source_identity = {
        "schema_version": 1,
        "work_id": catalog["work_id"],
        "catalog_sha256": catalog_sha256,
        "source_manifest_sha256": manifest_sha256,
        "checkpoint_relative_path": checkpoint_relative_path.replace("\\", "/"),
        "checkpoint_sha256": checkpoint_sha256,
        "work_metadata_version_id": verified_work_artifact["version_id"],
        "work_metadata": work_metadata,
        "groups": groups,
        "episodes": source_identity_episodes,
    }
    snapshot_digest = _sha256_bytes(_canonical_json_bytes(source_identity))
    snapshot_id = f"source-v1-{snapshot_digest}"
    completeness = {
        "status": "complete_for_declared_public_catalog",
        "declared_public_episode_count": public_count,
        "catalog_episode_count": len(episode_ids),
        "checkpoint_episode_count": len(
            checkpoint["completed_episode_ids"]
        ),
        "platform_enumeration_exhaustiveness": "not_independently_proven",
        "collection_time_window": {
            "started_at_utc": None,
            "completed_at_utc": None,
            "status": "not_recorded_by_checkpoint_schema_v5",
        },
    }
    provenance = {
        "catalog": {
            "relative_path": catalog_relative_path.replace("\\", "/"),
            "sha256": catalog_sha256,
        },
        "source_manifest": {
            "relative_path": manifest_relative_path.replace("\\", "/"),
            "sha256": manifest_sha256,
        },
        "edition_manifest": {
            "relative_path": edition_manifest_relative_path.replace("\\", "/"),
            "sha256": edition_manifest_sha256,
        },
        "source_checkpoint": {
            "relative_path": checkpoint_relative_path.replace("\\", "/"),
            "source_fingerprint": checkpoint["source_fingerprint"],
        },
        "ai_index": {
            "relative_path": ai_index_relative_path.replace("\\", "/"),
            "sha256": ai_result["index_sha256"],
        },
        "human_index": {
            "relative_path": human_index_relative_path.replace("\\", "/"),
            "sha256": human_index_sha256,
        },
    }
    raw_bundle = {
        "schema_version": 1,
        "edition": "raw_source",
        "bundle_id": snapshot_id,
        "source_snapshot_id": snapshot_id,
        "work_id": catalog["work_id"],
        "source_url": work_metadata["source_url"],
        "work_metadata": work_metadata,
        "work_metadata_provenance": metadata_provenance,
        "completeness": completeness,
        "provenance": provenance,
        "groups": groups,
        "episodes": raw_episodes,
    }
    ai_bundle_identity = {
        "bundle_contract_version": 2,
        "source_snapshot_id": snapshot_id,
        "profile": ai_index["cleaning_profile"],
        "edition_manifest_sha256": edition_manifest_sha256,
        "ai_index_sha256": ai_result["index_sha256"],
        "episodes": [
            {
                "episode_id": episode["episode_id"],
                "edition_version_id": episode["ai_edition_version_id"],
                "content_sha256": episode["output_sha256"],
            }
            for episode in ai_index["episodes"]
        ],
    }
    ai_bundle_digest = _sha256_bytes(_canonical_json_bytes(ai_bundle_identity))
    ai_bundle_id = f"ai-v1-{ai_bundle_digest}"
    ai_bundle = {
        **raw_bundle,
        "schema_version": 2,
        "edition": "ai",
        "bundle_id": ai_bundle_id,
        "cleaning_profile": ai_index["cleaning_profile"],
        "parent_source_snapshot_id": snapshot_id,
        "episodes": ai_episodes,
    }
    human_bundle_identity = {
        "source_snapshot_id": snapshot_id,
        "profile": human_index["cleaning_profile"],
        "edition_manifest_sha256": edition_manifest_sha256,
        "human_index_sha256": human_index_sha256,
        "episodes": [
            {
                "episode_id": episode["episode_id"],
                "edition_version_id": episode["edition_version_id"],
                "content_sha256": episode["content_sha256"],
            }
            for episode in human_episodes
        ],
    }
    human_bundle_digest = _sha256_bytes(
        _canonical_json_bytes(human_bundle_identity)
    )
    human_bundle_id = f"human-v1-{human_bundle_digest}"
    human_bundle_bytes = _build_human_bundle(
        snapshot_id=snapshot_id,
        bundle_id=human_bundle_id,
        work_id=catalog["work_id"],
        work_metadata=work_metadata,
        metadata_provenance=metadata_provenance,
        catalog_sha256=catalog_sha256,
        groups=groups,
        episodes=human_episodes,
        body_by_episode_id=human_body_by_id,
        profile=human_index["cleaning_profile"],
    )

    raw_bytes = _canonical_json_bytes(raw_bundle)
    ai_bytes = _canonical_json_bytes(ai_bundle)
    outputs = [
        raw_bytes,
        ai_bytes,
        human_bundle_bytes,
    ]
    if sum(map(len, outputs)) > max_total_output_bytes:
        raise ValueError("Book bundles exceed the configured total output byte limit.")

    snapshot_path_key = snapshot_digest
    raw_relative_path = (
        f"collections/{snapshot_path_key}/raw-book.json"
    )
    ai_relative_path = (
        f"collections/{snapshot_path_key}/{ai_bundle_digest}/book-ai.json"
    )
    human_relative_path = (
        f"collections/{snapshot_path_key}/{human_bundle_digest}/book-human.md"
    )
    set_identity = {
        "source_snapshot_id": snapshot_id,
        "raw_sha256": _sha256_bytes(raw_bytes),
        "ai_bundle_id": ai_bundle_id,
        "ai_sha256": _sha256_bytes(ai_bytes),
        "human_bundle_id": human_bundle_id,
        "human_sha256": _sha256_bytes(human_bundle_bytes),
    }
    set_digest = _sha256_bytes(_canonical_json_bytes(set_identity))
    set_relative_path = (
        f"collections/{snapshot_path_key}/bundle-set.{set_digest}.json"
    )
    bundle_set = {
        "schema_version": 1,
        "status": "complete",
        "source_snapshot_id": snapshot_id,
        "completeness": completeness,
        "episode_count": len(episode_ids),
        "bundles": {
            "raw": {
                "bundle_id": snapshot_id,
                "relative_path": raw_relative_path,
                "sha256": set_identity["raw_sha256"],
            },
            "ai": {
                "bundle_id": ai_bundle_id,
                "relative_path": ai_relative_path,
                "sha256": set_identity["ai_sha256"],
            },
            "human": {
                "bundle_id": human_bundle_id,
                "relative_path": human_relative_path,
                "sha256": set_identity["human_sha256"],
            },
        },
    }
    bundle_set_bytes = _canonical_json_bytes(bundle_set)
    if (
        _sha256_file(manifest_path) != manifest_sha256
        or _sha256_file(edition_manifest_path) != edition_manifest_sha256
        or _sha256_file(catalog_path) != catalog_sha256
        or _sha256_file(checkpoint_path) != checkpoint_sha256
        or ai_result["index_sha256"] != _sha256_file(ai_index_path)
        or human_index_sha256 != _sha256_file(human_index_path)
    ):
        raise RuntimeError("Source manifest changed before book bundle publication.")

    _ensure_output_directory(source_path, f"collections/{snapshot_path_key}")
    _ensure_output_directory(ai_path, f"collections/{snapshot_path_key}/{ai_bundle_digest}")
    _ensure_output_directory(
        human_path,
        f"collections/{snapshot_path_key}/{human_bundle_digest}",
    )
    created = {
        "raw": _write_immutable(source_path, raw_relative_path, raw_bytes),
        "ai": _write_immutable(ai_path, ai_relative_path, ai_bytes),
        "human": _write_immutable(
            human_path,
            human_relative_path,
            human_bundle_bytes,
        ),
    }
    output_files = (
        (source_path, raw_relative_path, _sha256_bytes(raw_bytes)),
        (ai_path, ai_relative_path, _sha256_bytes(ai_bytes)),
        (
            human_path,
            human_relative_path,
            _sha256_bytes(human_bundle_bytes),
        ),
    )
    if (
        _sha256_file(manifest_path) != manifest_sha256
        or _sha256_file(edition_manifest_path) != edition_manifest_sha256
        or _sha256_file(catalog_path) != catalog_sha256
        or _sha256_file(checkpoint_path) != checkpoint_sha256
        or ai_result["index_sha256"] != _sha256_file(ai_index_path)
        or human_index_sha256 != _sha256_file(human_index_path)
    ):
        raise RuntimeError("Book bundle inputs changed before completion was recorded.")
    for input_root, relative_path, expected_sha256 in verified_input_files:
        if _sha256_file(
            resolve_relative_path(str(input_root), relative_path)
        ) != expected_sha256:
            raise RuntimeError("Book bundle source files changed before completion.")
    for output_root, relative_path, expected_sha256 in output_files:
        output_path = resolve_relative_path(str(output_root), relative_path)
        if _sha256_file(output_path) != expected_sha256:
            raise RuntimeError("Book bundle output changed before completion.")
    created["bundle_set"] = _write_immutable(
        source_path,
        set_relative_path,
        bundle_set_bytes,
    )
    return {
        "status": "complete",
        "source_snapshot_id": snapshot_id,
        "bundle_set_relative_path": set_relative_path,
        "bundle_set_sha256": _sha256_bytes(bundle_set_bytes),
        "ai_bundle_id": ai_bundle_id,
        "ai_bundle_relative_path": ai_relative_path,
        "ai_bundle_sha256": set_identity["ai_sha256"],
        "episode_count": len(episode_ids),
        "source_bytes": total_source_bytes,
        "output_bytes": sum(map(len, outputs)),
        "source_editions_status": edition_report["status"],
        "created": created,
        "bundles": bundle_set["bundles"],
    }


def _read_json_bundle(
    root: Path,
    relative_path: str,
    *,
    max_bytes: int,
    label: str,
) -> tuple[dict, bytes]:
    path = resolve_relative_path(str(root), relative_path)
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"{label} exceeds the configured size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value, content


def load_verified_ai_book_bundle(
    *,
    source_root: str,
    catalog_relative_path: str,
    checkpoint_relative_path: str,
    bundle_set_relative_path: str,
    human_root: str,
    ai_root: str,
    manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = DEFAULT_EDITION_MANIFEST,
    max_total_bundle_bytes: int = DEFAULT_MAX_TOTAL_BUNDLE_BYTES,
) -> dict:
    """Load the AI book only when its bundle set and current edition are verified."""
    if (
        isinstance(max_total_bundle_bytes, bool)
        or not isinstance(max_total_bundle_bytes, int)
        or max_total_bundle_bytes < 1
    ):
        raise ValueError("Book bundle byte limit must be a positive integer.")
    source_path = Path(source_root).resolve(strict=True)
    human_path = Path(human_root).resolve(strict=True)
    ai_path = Path(ai_root).resolve(strict=True)
    bundle_set, bundle_set_bytes = _read_json_bundle(
        source_path,
        bundle_set_relative_path,
        max_bytes=4 * 1024 * 1024,
        label="Book bundle set",
    )
    if (
        set(bundle_set)
        != {
            "schema_version",
            "status",
            "source_snapshot_id",
            "completeness",
            "episode_count",
            "bundles",
        }
        or bundle_set.get("schema_version") != 1
        or bundle_set.get("status") != "complete"
        or not isinstance(bundle_set.get("source_snapshot_id"), str)
        or not re.fullmatch(
            r"source-v1-[0-9a-f]{64}",
            bundle_set["source_snapshot_id"],
        )
    ):
        raise ValueError("Book bundle set has an invalid schema or status.")
    episode_count = bundle_set.get("episode_count")
    if (
        isinstance(episode_count, bool)
        or not isinstance(episode_count, int)
        or episode_count < 1
        or not isinstance(bundle_set.get("completeness"), dict)
        or bundle_set["completeness"].get("status")
        != "complete_for_declared_public_catalog"
    ):
        raise ValueError("Book bundle set is not complete for its catalog.")
    bundle_records = bundle_set.get("bundles")
    if not isinstance(bundle_records, dict) or set(bundle_records) != {
        "raw",
        "ai",
        "human",
    }:
        raise ValueError("Book bundle set is missing one or more editions.")

    roots = {"raw": source_path, "ai": ai_path, "human": human_path}
    bundle_bytes = {}
    for edition, root in roots.items():
        record = bundle_records[edition]
        if (
            not isinstance(record, dict)
            or set(record) != {"bundle_id", "relative_path", "sha256"}
            or not isinstance(record.get("bundle_id"), str)
            or not isinstance(record.get("relative_path"), str)
            or not isinstance(record.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        ):
            raise ValueError("Book bundle set contains an invalid edition record.")
        path = resolve_relative_path(str(root), record["relative_path"])
        with open_regular_file(path, binary=True) as stream:
            content = stream.read(max_total_bundle_bytes + 1)
        if (
            len(content) > max_total_bundle_bytes
            or _sha256_bytes(content) != record["sha256"]
        ):
            raise ValueError("Book bundle file does not match its completion set.")
        bundle_bytes[edition] = content
    if sum(map(len, bundle_bytes.values())) > max_total_bundle_bytes:
        raise ValueError("Book bundles exceed the configured total size limit.")

    try:
        raw_bundle = json.loads(
            bundle_bytes["raw"].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        ai_bundle = json.loads(
            bundle_bytes["ai"].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Raw or AI book bundle is not valid UTF-8 JSON.") from exc
    ai_record = bundle_records["ai"]
    if (
        not isinstance(raw_bundle, dict)
        or raw_bundle.get("schema_version") != 1
        or raw_bundle.get("edition") != "raw_source"
        or not isinstance(ai_bundle, dict)
        or ai_bundle.get("schema_version") != 2
        or ai_bundle.get("edition") != "ai"
        or ai_bundle.get("bundle_id") != ai_record["bundle_id"]
        or ai_bundle.get("source_snapshot_id")
        != bundle_set["source_snapshot_id"]
        or raw_bundle.get("source_snapshot_id")
        != bundle_set["source_snapshot_id"]
        or ai_bundle.get("work_id") != raw_bundle.get("work_id")
        or ai_bundle.get("completeness")
        != bundle_set["completeness"]
    ):
        raise ValueError("AI book bundle does not match its completion set.")
    provenance = ai_bundle.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("AI book bundle is missing source provenance.")
    expected_provenance = {
        "catalog": catalog_relative_path.replace("\\", "/"),
        "source_manifest": manifest_relative_path.replace("\\", "/"),
        "edition_manifest": edition_manifest_relative_path.replace("\\", "/"),
    }
    for name, expected_path in expected_provenance.items():
        item = provenance.get(name)
        if (
            not isinstance(item, dict)
            or item.get("relative_path") != expected_path
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("AI book bundle provenance paths are inconsistent.")
    provenance_paths = {
        "catalog": (source_path, catalog_relative_path),
        "source_manifest": (source_path, manifest_relative_path),
        "edition_manifest": (source_path, edition_manifest_relative_path),
    }
    for name, (root, relative_path) in provenance_paths.items():
        if _sha256_file(resolve_relative_path(str(root), relative_path)) != (
            provenance[name]["sha256"]
        ):
            raise ValueError("Current source provenance differs from the AI bundle.")

    catalog = _load_catalog_snapshot(
        str(source_path),
        catalog_relative_path,
    )
    episode_ids = [item.metadata.episode_id for item in catalog["episodes"]]
    if (
        catalog["schema_version"] != 3
        or catalog["work_id"] != ai_bundle["work_id"]
        or catalog["work_metadata"] != ai_bundle.get("work_metadata")
        or len(episode_ids) != episode_count
        or catalog["work_metadata"]["public_episode_count"] != episode_count
    ):
        raise ValueError("AI book bundle no longer matches the current catalog.")

    from source_editions import verify_ai_edition_index

    ai_index_record = provenance.get("ai_index")
    human_index_record = provenance.get("human_index")
    checkpoint_record = provenance.get("source_checkpoint")
    if not all(
        isinstance(item, dict)
        for item in (ai_index_record, human_index_record, checkpoint_record)
    ):
        raise ValueError("AI book bundle is missing index or checkpoint provenance.")
    ai_result = verify_ai_edition_index(
        source_root=str(source_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
        index_relative_path=ai_index_record["relative_path"],
    )
    human_index_path = resolve_relative_path(
        str(human_path),
        human_index_record["relative_path"],
    )
    if (
        ai_result["index_sha256"] != ai_index_record["sha256"]
        or _sha256_file(human_index_path) != human_index_record["sha256"]
    ):
        raise ValueError("Current edition indexes differ from the AI bundle.")
    edition_report = validate_source_editions(
        source_root=str(source_path),
        catalog_relative_path=catalog_relative_path,
        human_root=str(human_path),
        ai_root=str(ai_path),
        source_manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
        human_index_relative_path=human_index_record["relative_path"],
        ai_index_relative_path=ai_index_record["relative_path"],
    )
    if edition_report["status"] != "verified":
        raise ValueError("Current source editions are not verified.")

    checkpoint = _load_complete_checkpoint(
        source_path,
        work_id=catalog["work_id"],
        manifest_relative_path=manifest_relative_path,
        checkpoint_relative_path=checkpoint_relative_path,
        episode_ids=episode_ids,
    )
    if (
        checkpoint["source_fingerprint"]
        != checkpoint_record.get("source_fingerprint")
    ):
        raise ValueError("Current checkpoint differs from the AI bundle.")

    indexed_by_id = ai_result["episodes_by_id"]
    bundled_episodes = ai_bundle.get("episodes")
    if (
        not isinstance(bundled_episodes, list)
        or len(bundled_episodes) != episode_count
    ):
        raise ValueError("AI book bundle does not cover the complete catalog.")
    bundled_by_input = {}
    bundled_episode_ids = set()
    group_by_episode = {
        episode_id: group
        for group in catalog["chapters"]
        for episode_id in group["episode_ids"]
    }
    for episode in bundled_episodes:
        if not isinstance(episode, dict):
            raise ValueError("AI book bundle contains an invalid episode.")
        episode_id = episode.get("episode_id")
        indexed = indexed_by_id.get(episode_id)
        if indexed is None or episode_id in bundled_episode_ids:
            raise ValueError("AI book bundle contains an unknown episode.")
        source_input_file = episode.get("source_input_file")
        if (
            not isinstance(source_input_file, str)
            or source_input_file in bundled_by_input
            or source_input_file != indexed.get("ai_relative_path")
            or episode.get("source_version_id")
            != indexed.get("source_version_id")
            or episode.get("source_sha256") != indexed.get("output_sha256")
            or episode.get("source_edition_version_id")
            != indexed.get("ai_edition_version_id")
            or episode.get("source_edition_sha256")
            != indexed.get("output_sha256")
            or episode.get("title") != indexed.get("title")
            or episode.get("position") != indexed.get("position")
        ):
            raise ValueError("AI book bundle episode lineage is stale.")
        source_text = episode.get("source_text")
        if (
            not isinstance(source_text, str)
            or _sha256_bytes(source_text.encode("utf-8"))
            != episode["source_sha256"]
        ):
            raise ValueError("AI book bundle episode text failed its digest check.")
        group = group_by_episode.get(episode_id)
        if group is None or (
            episode.get("group_id") != group["group_id"]
            or episode.get("chapter_id") != group["chapter_id"]
        ):
            raise ValueError("AI book bundle chapter grouping is stale.")
        source_artifact = next(
            (
                item
                for item in ai_result["source_manifest"]["artifacts"]
                if item["version_id"] == episode["source_version_id"]
            ),
            None,
        )
        if source_artifact is None or source_artifact["kind"] != "normalized_source":
            raise ValueError("AI book bundle source version is missing.")
        bundled_by_input[source_input_file] = {
            **episode,
            "source_file": source_artifact["relative_path"],
        }
        bundled_episode_ids.add(episode_id)
    if (
        len(bundled_by_input) != episode_count
        or bundled_episode_ids != set(indexed_by_id)
    ):
        raise ValueError("AI book bundle has duplicate or missing input paths.")

    return {
        "status": "verified",
        "work_id": catalog["work_id"],
        "source_snapshot_id": bundle_set["source_snapshot_id"],
        "ai_bundle_id": ai_bundle["bundle_id"],
        "bundle_set_relative_path": bundle_set_relative_path.replace("\\", "/"),
        "bundle_set_sha256": _sha256_bytes(bundle_set_bytes),
        "ai_bundle_relative_path": ai_record["relative_path"],
        "ai_bundle_sha256": ai_record["sha256"],
        "episode_count": episode_count,
        "episodes_by_source_input_file": bundled_by_input,
        "bundle": ai_bundle,
    }
