"""Adapter-independent source collection and resumable local persistence."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from source_manifest import (
    append_artifact,
    load_manifest,
    new_manifest,
    verify_manifest_artifact,
    verified_manifest_content_bytes,
)
from utils import open_regular_file, resolve_relative_path, write_text_atomically


CHECKPOINT_SCHEMA_VERSION = 5
DEFAULT_MAX_EPISODE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CATALOG_BYTES = 1024 * 1024 * 1024
_MAX_EPISODE_METADATA_BYTES = 1024 * 1024
_LEGACY_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "work_id",
        "cursor",
        "page_next_cursor",
        "page_loaded",
        "pending_episodes",
        "discovered_episode_ids",
        "completed_episode_ids",
        "seen_cursors",
        "status",
        "pause_reason",
    }
)
_CHECKPOINT_V3_FIELDS = _LEGACY_CHECKPOINT_FIELDS | {"source_fingerprint"}
_CHECKPOINT_V4_FIELDS = _CHECKPOINT_V3_FIELDS | {"manifest_relative_path"}
_CHECKPOINT_FIELDS = _CHECKPOINT_V4_FIELDS | {"completed_raw_versions"}
_EPISODE_FIELDS_V1 = frozenset({"episode_id", "title", "position"})
_EPISODE_FIELDS = _EPISODE_FIELDS_V1 | {"source_ref"}
_PAUSE_REASONS = frozenset(
    {
        "access_denied",
        "archive_limit",
        "rate_limited",
        "unavailable",
        "pagination_cycle",
    }
)


class ArchiveLimitExceeded(ValueError):
    """The next episode would exceed the configured manifest content budget."""


@dataclass(frozen=True)
class EpisodeMetadata:
    episode_id: str
    title: str
    position: int
    source_ref: str | None = None


@dataclass(frozen=True)
class CatalogPage:
    episodes: tuple[EpisodeMetadata, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class FetchedEpisode:
    metadata: EpisodeMetadata
    content: bytes


@dataclass(frozen=True)
class LocalEpisodeFile:
    metadata: EpisodeMetadata
    relative_path: str


class SourceAdapter(Protocol):
    @property
    def source_fingerprint(self) -> str: ...

    def list_episodes(self, cursor: str | None) -> CatalogPage: ...

    def fetch_episode(self, episode_id: str) -> bytes | FetchedEpisode: ...


class LocalFileAdapter:
    """Read explicitly mapped local source files without modifying them."""

    def __init__(
        self,
        root,
        episodes,
        *,
        page_size: int = 50,
        max_episode_bytes: int = DEFAULT_MAX_EPISODE_BYTES,
        max_catalog_bytes: int = DEFAULT_MAX_CATALOG_BYTES,
    ):
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size < 1
        ):
            raise ValueError("Local source page_size must be a positive integer.")
        for limit_name, limit in (
            ("max_episode_bytes", max_episode_bytes),
            ("max_catalog_bytes", max_catalog_bytes),
        ):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError(f"Local source {limit_name} must be a positive integer.")
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Local source root must be a directory.")
        if not isinstance(episodes, (list, tuple)):
            raise ValueError("Local source episodes must be an explicit list.")

        self.page_size = page_size
        self.max_episode_bytes = max_episode_bytes
        self.max_catalog_bytes = max_catalog_bytes
        input_episodes = tuple(episodes)
        self._files = {}
        self._source_hashes = {}
        seen_ids = set()
        seen_paths = set()
        normalized_episodes = []
        fingerprint_records = []
        catalog_bytes = 0
        for item in input_episodes:
            if not isinstance(item, LocalEpisodeFile):
                raise ValueError("Local source catalog contains an invalid entry.")
            _validate_episode_metadata(item.metadata)
            if not isinstance(item.relative_path, str):
                raise ValueError("Local source path must be a relative string.")
            metadata = item.metadata
            if metadata.source_ref is None:
                metadata = EpisodeMetadata(
                    episode_id=metadata.episode_id,
                    title=metadata.title,
                    position=metadata.position,
                    source_ref=f"local:{item.relative_path}",
                )
                _validate_episode_metadata(metadata)
                item = LocalEpisodeFile(metadata, item.relative_path)
            episode_id = item.metadata.episode_id
            path_key = item.relative_path.casefold()
            if episode_id in seen_ids:
                raise ValueError("Local source catalog repeats an episode_id.")
            if path_key in seen_paths:
                raise ValueError("Local source catalog repeats a file path.")
            source_path = resolve_relative_path(str(self.root), item.relative_path)
            if not source_path.is_file():
                raise ValueError("Local source path must be a regular file.")
            remaining_catalog_bytes = max_catalog_bytes - catalog_bytes
            source_hash, source_bytes = _hash_file_with_size(
                self.root,
                item.relative_path,
                max_bytes=min(max_episode_bytes, remaining_catalog_bytes),
            )
            catalog_bytes += source_bytes
            seen_ids.add(episode_id)
            seen_paths.add(path_key)
            self._files[episode_id] = item.relative_path
            self._source_hashes[episode_id] = source_hash
            normalized_episodes.append(item)
            fingerprint_records.append(
                {
                    "episode_id": episode_id,
                    "title": metadata.title,
                    "position": metadata.position,
                    "source_ref": metadata.source_ref,
                    "relative_path": item.relative_path,
                    "content_sha256": source_hash,
                }
            )
        self.episodes = tuple(normalized_episodes)
        fingerprint_data = json.dumps(
            {
                "episodes": fingerprint_records,
                "limits": {
                    "max_episode_bytes": max_episode_bytes,
                    "max_catalog_bytes": max_catalog_bytes,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.source_fingerprint = hashlib.sha256(fingerprint_data).hexdigest()

    def list_episodes(self, cursor: str | None) -> CatalogPage:
        if cursor is None:
            offset = 0
        elif (
            not isinstance(cursor, str)
            or not cursor.isascii()
            or not cursor.isdecimal()
            or cursor.startswith("0")
        ):
            raise ValueError("Local source cursor must be a canonical positive offset.")
        else:
            offset = int(cursor)
        if offset < 0 or (offset >= len(self.episodes) and offset != 0):
            raise ValueError("Local source cursor is out of range.")

        end = min(offset + self.page_size, len(self.episodes))
        next_cursor = str(end) if end < len(self.episodes) else None
        return CatalogPage(
            tuple(item.metadata for item in self.episodes[offset:end]),
            next_cursor,
        )

    def fetch_episode(self, episode_id: str) -> bytes:
        try:
            relative_path = self._files[episode_id]
        except KeyError as exc:
            raise ValueError(
                "Episode is not present in the explicit local catalog."
            ) from exc
        path = resolve_relative_path(str(self.root), relative_path)
        if not path.is_file():
            raise ValueError("Local source path must be a regular file.")
        content = bytearray()
        with open_regular_file(path, binary=True) as source_file:
            while True:
                remaining = self.max_episode_bytes - len(content)
                chunk = source_file.read(min(1024 * 1024, remaining + 1))
                if not chunk:
                    break
                if len(content) + len(chunk) > self.max_episode_bytes:
                    raise ValueError(
                        "Local source file exceeds the configured byte limit."
                    )
                content.extend(chunk)
        content = bytes(content)
        if hashlib.sha256(content).hexdigest() != self._source_hashes[episode_id]:
            raise ValueError("Local source file changed after snapshot creation.")
        return content


class SourceAccessDenied(Exception):
    """The source refused access; callers must not try an alternate route."""


class SourceRateLimited(Exception):
    """The source requested that collection pause."""


class SourceUnavailable(Exception):
    """The source could not be reached or returned a transient failure."""


def _valid_identifier(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and not any(ord(character) < 32 for character in value)
    )


def _valid_source_ref(value) -> bool:
    return value is None or (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and not any(ord(character) < 32 for character in value)
    )


def _validate_cursor(value) -> None:
    if value is not None and not _valid_identifier(value):
        raise ValueError("Source cursor must be null or a non-empty string.")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Source checkpoint contains a duplicate JSON field.")
        result[key] = value
    return result


def new_checkpoint(
    work_id: str,
    source_fingerprint: str,
    manifest_relative_path: str = "source_manifest.json",
) -> dict:
    if not _valid_identifier(work_id):
        raise ValueError("Source checkpoint requires a valid work_id.")
    if not _valid_identifier(source_fingerprint):
        raise ValueError("Source checkpoint requires a valid source_fingerprint.")
    if not _valid_identifier(manifest_relative_path):
        raise ValueError("Source checkpoint requires a valid manifest path.")
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "work_id": work_id,
        "source_fingerprint": source_fingerprint,
        "manifest_relative_path": manifest_relative_path,
        "cursor": None,
        "page_next_cursor": None,
        "page_loaded": False,
        "pending_episodes": [],
        "discovered_episode_ids": [],
        "completed_episode_ids": [],
        "completed_raw_versions": {},
        "seen_cursors": [],
        "status": "in_progress",
        "pause_reason": None,
    }


def validate_checkpoint(checkpoint: dict) -> None:
    if not isinstance(checkpoint, dict):
        raise ValueError("Source checkpoint has an invalid field set.")
    version = checkpoint.get("schema_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {1, 2, 3, 4, CHECKPOINT_SCHEMA_VERSION}
    ):
        raise ValueError("Unsupported source checkpoint schema_version.")
    expected_fields = (
        _CHECKPOINT_FIELDS if version == CHECKPOINT_SCHEMA_VERSION
        else _CHECKPOINT_V4_FIELDS if version == 4
        else _CHECKPOINT_V3_FIELDS if version == 3
        else _LEGACY_CHECKPOINT_FIELDS
    )
    if set(checkpoint) != expected_fields:
        raise ValueError("Source checkpoint has an invalid field set.")
    if not _valid_identifier(checkpoint["work_id"]):
        raise ValueError("Source checkpoint has an invalid work_id.")
    if version in {3, CHECKPOINT_SCHEMA_VERSION} and not _valid_identifier(
        checkpoint["source_fingerprint"]
    ):
        raise ValueError("Source checkpoint has an invalid source_fingerprint.")
    if version == CHECKPOINT_SCHEMA_VERSION and not _valid_identifier(
        checkpoint["manifest_relative_path"]
    ):
        raise ValueError("Source checkpoint has an invalid manifest path.")

    _validate_cursor(checkpoint["cursor"])
    _validate_cursor(checkpoint["page_next_cursor"])
    if not isinstance(checkpoint["page_loaded"], bool):
        raise ValueError("Source checkpoint page_loaded must be a boolean.")
    status = checkpoint["status"]
    if not isinstance(status, str) or status not in {
        "in_progress",
        "paused",
        "complete",
    }:
        raise ValueError("Source checkpoint has an unsupported status.")
    pause_reason = checkpoint["pause_reason"]
    if checkpoint["status"] == "paused":
        if not isinstance(pause_reason, str) or pause_reason not in _PAUSE_REASONS:
            raise ValueError("Paused source checkpoint requires a known pause_reason.")
    elif pause_reason is not None:
        raise ValueError("Only paused source checkpoints may have a pause_reason.")
    if checkpoint["status"] == "complete" and (
        checkpoint["cursor"] is not None or checkpoint["page_loaded"]
    ):
        raise ValueError("Completed source checkpoint has unfinished pagination.")

    for field in ("discovered_episode_ids", "completed_episode_ids", "seen_cursors"):
        values = checkpoint[field]
        if not isinstance(values, list) or any(
            not _valid_identifier(value) for value in values
        ):
            raise ValueError(f"Source checkpoint has invalid {field}.")
        if len(values) != len(set(values)):
            raise ValueError(f"Source checkpoint repeats a value in {field}.")

    discovered = set(checkpoint["discovered_episode_ids"])
    completed = set(checkpoint["completed_episode_ids"])
    if status == "complete" and not discovered:
        raise ValueError("Completed source checkpoint contains no episodes.")
    if status == "complete" and completed != discovered:
        raise ValueError("Completed source checkpoint has an incomplete episode set.")
    if not completed <= discovered:
        raise ValueError("Completed episodes must have been discovered.")
    if version == CHECKPOINT_SCHEMA_VERSION:
        completed_raw_versions = checkpoint["completed_raw_versions"]
        if (
            not isinstance(completed_raw_versions, dict)
            or any(
                not _valid_identifier(episode_id)
                or not _valid_identifier(version_id)
                for episode_id, version_id in completed_raw_versions.items()
            )
            or set(completed_raw_versions) != completed
            or len(set(completed_raw_versions.values()))
            != len(completed_raw_versions)
        ):
            raise ValueError(
                "Source checkpoint completed raw versions are inconsistent."
            )

    pending = checkpoint["pending_episodes"]
    if not isinstance(pending, list):
        raise ValueError("Source checkpoint pending_episodes must be an array.")
    pending_ids = []
    for episode in pending:
        expected_fields = (
            _EPISODE_FIELDS if version in {2, 3, 4, 5} else _EPISODE_FIELDS_V1
        )
        if not isinstance(episode, dict) or set(episode) != expected_fields:
            raise ValueError("Source checkpoint has invalid episode metadata.")
        if not _valid_identifier(episode["episode_id"]):
            raise ValueError("Source checkpoint has an invalid episode_id.")
        if not isinstance(episode["title"], str):
            raise ValueError("Source checkpoint has an invalid episode title.")
        if version == 2 and not _valid_source_ref(episode["source_ref"]):
            raise ValueError("Source checkpoint has an invalid source_ref.")
        position = episode["position"]
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            raise ValueError("Source checkpoint has an invalid episode position.")
        pending_ids.append(episode["episode_id"])
    if len(pending_ids) != len(set(pending_ids)):
        raise ValueError("Source checkpoint repeats a pending episode.")
    if not set(pending_ids) <= discovered or set(pending_ids) & completed:
        raise ValueError("Source checkpoint pending episodes are inconsistent.")
    if checkpoint["page_loaded"]:
        if checkpoint["cursor"] is not None and checkpoint["cursor"] not in set(
            checkpoint["seen_cursors"]
        ):
            raise ValueError("Loaded page cursor is missing from seen_cursors.")
    elif pending or checkpoint["page_next_cursor"] is not None:
        raise ValueError("Unloaded source checkpoint contains pending page state.")


def _write_json(root: Path, relative_path: str, value: dict) -> Path:
    path = resolve_relative_path(str(root), relative_path, allow_missing=True)
    content = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    write_text_atomically(str(path), content + "\n")
    return path


def _report(checkpoint: dict) -> dict:
    discovered = set(checkpoint["discovered_episode_ids"])
    completed = set(checkpoint["completed_episode_ids"])
    return {
        "status": checkpoint["status"],
        "reason": checkpoint["pause_reason"],
        "discovered_count": len(discovered),
        "completed_count": len(completed),
        "pending_count": len(discovered - completed),
    }


def _completed_raw_content_bytes(
    root_path: Path,
    manifest_path: Path,
    work_id: str,
    checkpoint: dict,
) -> int:
    if not checkpoint["completed_episode_ids"]:
        return 0
    if not manifest_path.exists():
        raise ValueError("Completed source checkpoint has no manifest.")
    manifest = load_manifest(manifest_path)
    total = 0
    for episode_id in checkpoint["completed_episode_ids"]:
        version_id = checkpoint["completed_raw_versions"][episode_id]
        artifact = verify_manifest_artifact(root_path, manifest, version_id)
        if (
            artifact["kind"] != "raw_source"
            or artifact["artifact_id"]
            != _source_artifact_id(work_id, "raw_source", episode_id)
        ):
            raise ValueError(
                "Completed source checkpoint points to an unrelated raw artifact."
            )
        path = resolve_relative_path(str(root_path), artifact["relative_path"])
        total += path.stat().st_size
    return total


def _pause(checkpoint: dict, reason: str, root: Path, checkpoint_path: str) -> dict:
    checkpoint["status"] = "paused"
    checkpoint["pause_reason"] = reason
    validate_checkpoint(checkpoint)
    _write_json(root, checkpoint_path, checkpoint)
    return _report(checkpoint)


def _validate_page(page: CatalogPage) -> None:
    if not isinstance(page, CatalogPage) or not isinstance(page.episodes, tuple):
        raise ValueError("Source adapter must return a CatalogPage with a tuple.")
    _validate_cursor(page.next_cursor)
    episode_ids = []
    for episode in page.episodes:
        _validate_episode_metadata(episode)
        episode_ids.append(episode.episode_id)
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("Catalog page repeats an episode_id.")


def _validate_episode_metadata(episode: EpisodeMetadata) -> None:
    if not isinstance(episode, EpisodeMetadata):
        raise ValueError("Source catalog contains invalid episode metadata.")
    if not _valid_identifier(episode.episode_id):
        raise ValueError("Source catalog contains an invalid episode_id.")
    if not isinstance(episode.title, str):
        raise ValueError("Source catalog contains an invalid episode title.")
    position = episode.position
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise ValueError("Source catalog contains an invalid episode position.")
    if not _valid_source_ref(episode.source_ref):
        raise ValueError("Source catalog contains an invalid source_ref.")


def _record_page(checkpoint: dict, page: CatalogPage) -> None:
    _validate_page(page)
    if checkpoint["page_loaded"] or checkpoint["status"] != "in_progress":
        raise ValueError("Source checkpoint is not ready to load a catalog page.")
    if (
        not page.episodes
        and page.next_cursor is None
        and not checkpoint["discovered_episode_ids"]
    ):
        raise ValueError("Source adapter returned an empty catalog.")

    cursor = checkpoint["cursor"]
    if cursor is not None and cursor in checkpoint["seen_cursors"]:
        raise ValueError("Source catalog repeated a cursor.")
    if cursor is not None:
        checkpoint["seen_cursors"].append(cursor)

    discovered = set(checkpoint["discovered_episode_ids"])
    completed = set(checkpoint["completed_episode_ids"])
    pending = []
    for episode in page.episodes:
        if episode.episode_id not in discovered:
            checkpoint["discovered_episode_ids"].append(episode.episode_id)
            discovered.add(episode.episode_id)
        if episode.episode_id not in completed:
            pending.append(
                {
                    "episode_id": episode.episode_id,
                    "title": episode.title,
                    "position": episode.position,
                    "source_ref": episode.source_ref,
                }
            )

    checkpoint["page_next_cursor"] = page.next_cursor
    checkpoint["pending_episodes"] = pending
    checkpoint["page_loaded"] = True
    validate_checkpoint(checkpoint)


def _ensure_parent_directories(root: Path, relative_path: str) -> None:
    parts = relative_path.split("/")[:-1]
    current = root
    prefix = []
    for part in parts:
        prefix.append(part)
        current = current / part
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in source paths.")
        try:
            current.mkdir()
        except FileExistsError:
            if not current.is_dir():
                raise ValueError("Source path parent is not a directory.")
        resolve_relative_path(str(root), "/".join(prefix), allow_missing=True)


def _hash_file(root: Path, relative_path: str) -> str:
    digest, _ = _hash_file_with_size(root, relative_path)
    return digest


def _hash_file_with_size(
    root: Path,
    relative_path: str,
    *,
    max_bytes: int | None = None,
) -> tuple[str, int]:
    path = resolve_relative_path(str(root), relative_path)
    digest = hashlib.sha256()
    size = 0
    with open_regular_file(path, binary=True) as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ValueError(
                    "Local source file exceeds the configured byte limit."
                )
            digest.update(chunk)
    return digest.hexdigest(), size


def _store_immutable_bytes(
    root: Path, relative_path: str, content: bytes, expected_hash: str
) -> None:
    _ensure_parent_directories(root, relative_path)
    path = resolve_relative_path(str(root), relative_path, allow_missing=True)
    if path.exists():
        if _hash_file(root, relative_path) != expected_hash:
            raise ValueError("Existing source artifact has an unexpected hash.")
        return

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            descriptor = -1
            target.write(content)
            target.flush()
            os.fsync(target.fileno())

        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if _hash_file(root, relative_path) != expected_hash:
                raise ValueError("Existing source artifact has an unexpected hash.")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except OSError:
            pass


def _artifact_version_id(
    artifact_id: str, content_hash: str, parent_version_ids: list[str]
) -> str:
    version_data = json.dumps(
        {
            "artifact_id": artifact_id,
            "content_sha256": content_hash,
            "parent_version_ids": parent_version_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"v-{hashlib.sha256(version_data).hexdigest()}"


def _checkpoint_fingerprint(
    source_fingerprint: str,
    max_archive_bytes: int | None,
) -> str:
    if max_archive_bytes is None:
        return source_fingerprint
    fingerprint_data = json.dumps(
        {
            "source_fingerprint": source_fingerprint,
            "max_archive_bytes": max_archive_bytes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(fingerprint_data).hexdigest()


def source_artifact_id(work_id: str, kind: str, episode_id: str) -> str:
    if not all(_valid_identifier(value) for value in (work_id, kind, episode_id)):
        raise ValueError("Source artifact identity fields must be valid identifiers.")
    identity = json.dumps(
        [work_id, kind, episode_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"source-ingestion:v1:{hashlib.sha256(identity).hexdigest()}"


_source_artifact_id = source_artifact_id


def _latest_artifact(manifest: dict, artifact_id: str) -> dict | None:
    return next(
        (
            artifact
            for artifact in reversed(manifest["artifacts"])
            if artifact["artifact_id"] == artifact_id
        ),
        None,
    )


def _append_immutable_artifact(
    root: Path,
    manifest_path: Path,
    manifest: dict,
    artifact: dict,
    content: bytes,
) -> dict:
    existing_version = next(
        (
            item
            for item in manifest["artifacts"]
            if item["version_id"] == artifact["version_id"]
        ),
        None,
    )
    if existing_version is not None:
        if existing_version != artifact:
            raise ValueError("Existing source manifest version has conflicting data.")
        if artifact["relative_path"] is not None and _hash_file(
            root, artifact["relative_path"]
        ) != artifact["content_sha256"]:
            raise ValueError("Existing source manifest file has an unexpected hash.")
        return manifest

    if artifact["relative_path"] is not None:
        _store_immutable_bytes(
            root,
            artifact["relative_path"],
            content,
            artifact["content_sha256"],
        )
    return append_artifact(str(manifest_path), artifact)


def _persist_episode(
    root: Path,
    manifest_path: Path,
    work_id: str,
    episode: EpisodeMetadata,
    content: bytes,
    *,
    max_archive_bytes: int | None = None,
    current_archive_bytes: int | None = None,
) -> int | None:
    manifest = (
        load_manifest(manifest_path)
        if manifest_path.exists()
        else new_manifest()
    )
    episode_key = hashlib.sha256(
        f"{work_id}\0{episode.episode_id}".encode("utf-8")
    ).hexdigest()
    metadata = json.dumps(
        {
            "schema_version": 1,
            "work_id": work_id,
            "episode_id": episode.episode_id,
            "title": episode.title,
            "position": episode.position,
            "source_ref": episode.source_ref,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(metadata) > _MAX_EPISODE_METADATA_BYTES:
        raise ValueError("Serialized episode metadata exceeds the size limit.")
    metadata_hash = hashlib.sha256(metadata).hexdigest()
    metadata_artifact_id = _source_artifact_id(
        work_id, "episode", episode.episode_id
    )
    latest_metadata = _latest_artifact(manifest, metadata_artifact_id)

    metadata_to_append = None
    if latest_metadata and latest_metadata["content_sha256"] == metadata_hash:
        metadata_version_id = latest_metadata["version_id"]
        if (
            latest_metadata["relative_path"] is None
            or _hash_file(root, latest_metadata["relative_path"]) != metadata_hash
        ):
            raise ValueError("Existing episode metadata has an unexpected hash.")
    else:
        metadata_parents = (
            [latest_metadata["version_id"]] if latest_metadata else []
        )
        metadata_version_id = _artifact_version_id(
            metadata_artifact_id,
            metadata_hash,
            metadata_parents,
        )
        metadata_artifact = {
            "artifact_id": metadata_artifact_id,
            "version_id": metadata_version_id,
            "kind": "episode",
            "content_sha256": metadata_hash,
            "relative_path": (
                f"metadata/{episode_key}/{metadata_version_id[2:]}.json"
            ),
            "parent_version_ids": metadata_parents,
        }
        metadata_to_append = (metadata_artifact, metadata)

    raw_artifact_id = _source_artifact_id(
        work_id, "raw_source", episode.episode_id
    )
    raw_hash = hashlib.sha256(content).hexdigest()
    latest_raw = _latest_artifact(manifest, raw_artifact_id)
    if (
        latest_raw
        and latest_raw["content_sha256"] == raw_hash
        and metadata_version_id in latest_raw["parent_version_ids"]
    ):
        if (
            latest_raw["relative_path"] is None
            or _hash_file(root, latest_raw["relative_path"]) != raw_hash
        ):
            raise ValueError("Existing raw episode has an unexpected hash.")
        return current_archive_bytes

    raw_parents = [metadata_version_id]
    if latest_raw:
        raw_parents.append(latest_raw["version_id"])
    raw_version_id = _artifact_version_id(raw_artifact_id, raw_hash, raw_parents)
    raw_artifact = {
        "artifact_id": raw_artifact_id,
        "version_id": raw_version_id,
        "kind": "raw_source",
        "content_sha256": raw_hash,
        "relative_path": f"raw/{episode_key}/{raw_version_id[2:]}.bin",
        "parent_version_ids": raw_parents,
    }
    if max_archive_bytes is not None:
        if (
            isinstance(current_archive_bytes, bool)
            or not isinstance(current_archive_bytes, int)
            or current_archive_bytes < 0
        ):
            raise ValueError("Current archive byte count is required for a byte limit.")
        candidates = [(raw_artifact, content)]
        if metadata_to_append is not None:
            candidates.append(metadata_to_append)
        additions = sum(
            len(candidate_content)
            for candidate, candidate_content in candidates
            if not any(
                item["version_id"] == candidate["version_id"]
                for item in manifest["artifacts"]
            )
        )
        if current_archive_bytes + additions > max_archive_bytes:
            raise ArchiveLimitExceeded(
                "Episode would exceed the configured manifest content byte limit."
            )

    if metadata_to_append is not None:
        metadata_artifact, metadata = metadata_to_append
        manifest = _append_immutable_artifact(
            root,
            manifest_path,
            manifest,
            metadata_artifact,
            metadata,
        )
    _append_immutable_artifact(
        root,
        manifest_path,
        manifest,
        raw_artifact,
        content,
    )
    if current_archive_bytes is not None:
        return current_archive_bytes + additions
    return None


def _read_manifested_artifact_bytes(
    root: Path, artifact: dict, *, max_bytes: int
) -> bytes:
    relative_path = artifact["relative_path"]
    if relative_path is None:
        raise ValueError("Source artifact has no content file.")
    path = resolve_relative_path(str(root), relative_path)
    content = bytearray()
    with open_regular_file(path, binary=True) as source_file:
        while True:
            remaining = max_bytes - len(content)
            chunk = source_file.read(min(1024 * 1024, remaining + 1))
            if not chunk:
                break
            if len(content) + len(chunk) > max_bytes:
                raise ValueError("Source artifact exceeds the configured byte limit.")
            content.extend(chunk)
    content = bytes(content)
    if hashlib.sha256(content).hexdigest() != artifact["content_sha256"]:
        raise ValueError("Source artifact content does not match its manifest hash.")
    return content


def _reject_duplicate_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Episode metadata contains a duplicate JSON field.")
        result[key] = value
    return result


def _load_episode_metadata(
    root_path: Path,
    manifest: dict,
    *,
    work_id: str,
    episode_id: str,
) -> tuple[dict, dict]:
    metadata_artifact_id = _source_artifact_id(work_id, "episode", episode_id)
    metadata_artifact = _latest_artifact(manifest, metadata_artifact_id)
    if metadata_artifact is None or metadata_artifact["kind"] != "episode":
        raise ValueError("Episode metadata is not present in the source manifest.")
    metadata_bytes = _read_manifested_artifact_bytes(
        root_path,
        metadata_artifact,
        max_bytes=_MAX_EPISODE_METADATA_BYTES,
    )
    try:
        metadata = json.loads(
            metadata_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_fields,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Episode metadata is not valid UTF-8 JSON.") from exc
    if (
        not isinstance(metadata, dict)
        or set(metadata)
        != {
            "schema_version",
            "work_id",
            "episode_id",
            "title",
            "position",
            "source_ref",
        }
        or isinstance(metadata["schema_version"], bool)
        or metadata["schema_version"] != 1
        or metadata["work_id"] != work_id
        or metadata["episode_id"] != episode_id
        or not isinstance(metadata["title"], str)
        or isinstance(metadata["position"], bool)
        or not isinstance(metadata["position"], int)
        or metadata["position"] < 1
        or not _valid_source_ref(metadata["source_ref"])
    ):
        raise ValueError("Episode metadata does not match the requested identity.")
    return metadata_artifact, metadata


def _latest_raw_for_metadata(
    manifest: dict, *, work_id: str, episode_id: str, metadata_artifact: dict
) -> dict:
    raw_artifact_id = _source_artifact_id(work_id, "raw_source", episode_id)
    raw_artifact = next(
        (
            item
            for item in reversed(manifest["artifacts"])
            if item["artifact_id"] == raw_artifact_id
            and item["kind"] == "raw_source"
            and metadata_artifact["version_id"] in item["parent_version_ids"]
        ),
        None,
    )
    if raw_artifact is None:
        raise ValueError("No raw source version is linked to the latest episode metadata.")
    return raw_artifact


def materialize_episode_markdown(
    root,
    *,
    work_id: str,
    episode_id: str,
    manifest_relative_path: str = "source_manifest.json",
    max_bytes: int = DEFAULT_MAX_EPISODE_BYTES,
) -> dict:
    """Create a byte-preserving UTF-8 Markdown artifact from one archived episode."""
    if not _valid_identifier(work_id) or not _valid_identifier(episode_id):
        raise ValueError("Markdown materialization requires valid work and episode IDs.")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("Markdown materialization byte limit must be positive.")

    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("Markdown materialization root must be a directory.")
    manifest_path = resolve_relative_path(
        str(root_path), manifest_relative_path
    )
    manifest = load_manifest(manifest_path)

    metadata_artifact, _ = _load_episode_metadata(
        root_path, manifest, work_id=work_id, episode_id=episode_id
    )
    raw_artifact = _latest_raw_for_metadata(
        manifest,
        work_id=work_id,
        episode_id=episode_id,
        metadata_artifact=metadata_artifact,
    )
    raw_bytes = _read_manifested_artifact_bytes(
        root_path, raw_artifact, max_bytes=max_bytes
    )
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Raw episode is not valid UTF-8.") from exc
    markdown_bytes = raw_text.encode("utf-8")
    if markdown_bytes != raw_bytes:
        raise ValueError("UTF-8 Markdown materialization must preserve source bytes.")

    markdown_hash = hashlib.sha256(markdown_bytes).hexdigest()
    normalized_artifact_id = _source_artifact_id(
        work_id, "normalized_source", episode_id
    )
    latest_normalized = _latest_artifact(manifest, normalized_artifact_id)
    if latest_normalized is not None and latest_normalized["kind"] != "normalized_source":
        raise ValueError("Markdown artifact identity has an unexpected kind.")
    if (
        latest_normalized
        and latest_normalized["content_sha256"] == markdown_hash
        and raw_artifact["version_id"] in latest_normalized["parent_version_ids"]
    ):
        _read_manifested_artifact_bytes(
            root_path, latest_normalized, max_bytes=max_bytes
        )
        return latest_normalized

    parents = [raw_artifact["version_id"]]
    if latest_normalized is not None:
        parents.append(latest_normalized["version_id"])
    version_id = _artifact_version_id(
        normalized_artifact_id, markdown_hash, parents
    )
    episode_key = hashlib.sha256(
        f"{work_id}\0{episode_id}".encode("utf-8")
    ).hexdigest()
    relative_path = f"normalized/{episode_key}/{version_id[2:]}.md"
    if (
        manifest_path.relative_to(root_path).as_posix().casefold()
        == relative_path.casefold()
    ):
        raise ValueError("Markdown output path conflicts with the source manifest.")
    if any(
        item["relative_path"] is not None
        and item["relative_path"].casefold() == relative_path.casefold()
        for item in manifest["artifacts"]
    ):
        raise ValueError("Markdown output path is already owned by another artifact.")
    _ensure_parent_directories(root_path, relative_path)
    artifact = {
        "artifact_id": normalized_artifact_id,
        "version_id": version_id,
        "kind": "normalized_source",
        "content_sha256": markdown_hash,
        "relative_path": relative_path,
        "parent_version_ids": parents,
    }
    _append_immutable_artifact(
        root_path,
        manifest_path,
        manifest,
        artifact,
        markdown_bytes,
    )
    return artifact


def materialize_episode_collection_markdown(
    root,
    *,
    work_id: str,
    episode_ids: list[str],
    max_bytes: int,
    manifest_relative_path: str = "source_manifest.json",
    expected_raw_versions: dict[str, str] | None = None,
) -> dict:
    """Merge explicitly ordered current episodes into an immutable Markdown export."""
    if not _valid_identifier(work_id):
        raise ValueError("Episode collection requires a valid work_id.")
    if (
        not isinstance(episode_ids, list)
        or not episode_ids
        or any(not _valid_identifier(episode_id) for episode_id in episode_ids)
    ):
        raise ValueError("Episode collection requires episode IDs.")
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("Episode collection IDs must be unique.")
    if expected_raw_versions is not None and (
        not isinstance(expected_raw_versions, dict)
        or set(expected_raw_versions) != set(episode_ids)
        or any(
            not _valid_identifier(episode_id)
            or not _valid_identifier(version_id)
            for episode_id, version_id in expected_raw_versions.items()
        )
    ):
        raise ValueError("Episode collection raw version bindings are invalid.")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("Episode collection byte limit must be positive.")

    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("Episode collection root must be a directory.")
    manifest_path = resolve_relative_path(str(root_path), manifest_relative_path)
    manifest = load_manifest(manifest_path)

    separator = b"\n\n"
    position = 0
    normalized_artifacts = []
    contents = []
    size = 0
    for episode_id in episode_ids:
        metadata_artifact, metadata = _load_episode_metadata(
            root_path, manifest, work_id=work_id, episode_id=episode_id
        )
        if metadata["position"] <= position:
            raise ValueError(
                "Episode collection IDs must follow increasing source positions."
            )
        position = metadata["position"]

        raw_artifact = _latest_raw_for_metadata(
            manifest,
            work_id=work_id,
            episode_id=episode_id,
            metadata_artifact=metadata_artifact,
        )
        if (
            expected_raw_versions is not None
            and raw_artifact["version_id"] != expected_raw_versions[episode_id]
        ):
            raise ValueError(
                "Complete source checkpoint is stale for the current raw source."
            )
        verify_manifest_artifact(
            root_path, manifest, raw_artifact["version_id"]
        )
        normalized_artifact_id = _source_artifact_id(
            work_id, "normalized_source", episode_id
        )
        normalized_artifact = _latest_artifact(manifest, normalized_artifact_id)
        if (
            normalized_artifact is None
            or normalized_artifact["kind"] != "normalized_source"
        ):
            raise ValueError("Episode has no normalized Markdown artifact.")
        if raw_artifact["version_id"] not in normalized_artifact["parent_version_ids"]:
            raise ValueError("Episode normalized Markdown is stale for its latest raw source.")

        remaining = max_bytes - size - (len(separator) if contents else 0)
        if remaining < 0:
            raise ValueError("Episode collection exceeds the configured byte limit.")
        content = _read_manifested_artifact_bytes(
            root_path, normalized_artifact, max_bytes=remaining
        )
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Normalized episode is not valid UTF-8.") from exc
        if contents:
            size += len(separator)
        size += len(content)
        contents.append(content)
        normalized_artifacts.append(normalized_artifact)

    markdown_bytes = separator.join(contents)
    content_hash = hashlib.sha256(markdown_bytes).hexdigest()
    artifact_id = "source-ingestion:v1:episode-collection-export:" + hashlib.sha256(
        json.dumps(
            [work_id, "episode-collection-markdown"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    source_versions = [
        artifact["version_id"] for artifact in normalized_artifacts
    ]
    latest_export = _latest_artifact(manifest, artifact_id)
    if latest_export is not None and latest_export["kind"] != "export":
        raise ValueError("Episode collection export identity has an unexpected kind.")
    version_by_id = {
        item["version_id"]: item for item in manifest["artifacts"]
    }
    previous_export_parent = (
        latest_export is not None
        and len(latest_export["parent_version_ids"]) == len(source_versions) + 1
        and latest_export["parent_version_ids"][: len(source_versions)]
        == source_versions
        and version_by_id[latest_export["parent_version_ids"][-1]]["artifact_id"]
        == artifact_id
        and version_by_id[latest_export["parent_version_ids"][-1]]["kind"]
        == "export"
    )
    if (
        latest_export is not None
        and latest_export["content_sha256"] == content_hash
        and (
            latest_export["parent_version_ids"] == source_versions
            or previous_export_parent
        )
    ):
        _read_manifested_artifact_bytes(
            root_path, latest_export, max_bytes=max_bytes
        )
        return latest_export

    parents = list(source_versions)
    if latest_export is not None:
        parents.append(latest_export["version_id"])
    version_id = _artifact_version_id(artifact_id, content_hash, parents)
    work_key = hashlib.sha256(work_id.encode("utf-8")).hexdigest()
    relative_path = f"exports/{work_key}/{version_id[2:]}.md"
    if (
        manifest_path.relative_to(root_path).as_posix().casefold()
        == relative_path.casefold()
    ):
        raise ValueError("Episode collection output path conflicts with the source manifest.")
    if any(
        item["relative_path"] is not None
        and item["relative_path"].casefold() == relative_path.casefold()
        for item in manifest["artifacts"]
    ):
        raise ValueError("Episode collection output path is already owned by another artifact.")

    artifact = {
        "artifact_id": artifact_id,
        "version_id": version_id,
        "kind": "export",
        "content_sha256": content_hash,
        "relative_path": relative_path,
        "parent_version_ids": parents,
    }
    _append_immutable_artifact(
        root_path,
        manifest_path,
        manifest,
        artifact,
        markdown_bytes,
    )
    return artifact


def materialize_complete_checkpoint_catalog_markdown(
    root,
    *,
    work_id: str,
    max_bytes: int,
    manifest_relative_path: str = "source_manifest.json",
    checkpoint_relative_path: str = "source_checkpoint.json",
) -> dict:
    """Export every current episode bound to a complete source checkpoint."""
    if not _valid_identifier(work_id):
        raise ValueError("Complete catalog export requires a valid work_id.")

    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("Complete catalog export root must be a directory.")
    manifest_path = resolve_relative_path(
        str(root_path), manifest_relative_path
    )
    checkpoint_path = resolve_relative_path(
        str(root_path), checkpoint_relative_path
    )
    manifest_identity = manifest_path.relative_to(root_path).as_posix()
    checkpoint_identity = checkpoint_path.relative_to(root_path).as_posix()
    if manifest_identity.casefold() == checkpoint_identity.casefold():
        raise ValueError("Manifest and checkpoint paths must be different.")

    checkpoint = _read_checkpoint(checkpoint_path)
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(
            "Complete catalog export requires a checkpoint with raw version bindings."
        )
    if checkpoint["work_id"] != work_id:
        raise ValueError("Source checkpoint belongs to a different work_id.")
    if checkpoint["manifest_relative_path"] != manifest_identity:
        raise ValueError("Source checkpoint does not match the source manifest.")
    if checkpoint["status"] != "complete":
        raise ValueError("Complete catalog export requires a complete checkpoint.")

    episode_ids = checkpoint["discovered_episode_ids"]
    if checkpoint["completed_episode_ids"] != episode_ids:
        raise ValueError("Complete source checkpoint episode order is inconsistent.")
    manifest = load_manifest(manifest_path)
    source_positions = []
    for episode_id in episode_ids:
        _, metadata = _load_episode_metadata(
            root_path,
            manifest,
            work_id=work_id,
            episode_id=episode_id,
        )
        source_positions.append((metadata["position"], episode_id))
    episode_ids = [
        episode_id for _, episode_id in sorted(source_positions)
    ]

    artifact = materialize_episode_collection_markdown(
        root_path,
        work_id=work_id,
        episode_ids=episode_ids,
        max_bytes=max_bytes,
        manifest_relative_path=manifest_identity,
        expected_raw_versions=checkpoint["completed_raw_versions"],
    )
    return {
        "artifact": artifact,
        "episode_ids": list(episode_ids),
        "source_fingerprint": checkpoint["source_fingerprint"],
    }


def collect_source(
    adapter: SourceAdapter,
    *,
    root,
    work_id: str,
    manifest_relative_path: str = "source_manifest.json",
    checkpoint_relative_path: str = "source_checkpoint.json",
    max_archive_bytes: int | None = None,
) -> dict:
    """Persist adapter catalog entries and fetched raw bytes with resumable state."""
    if not _valid_identifier(work_id):
        raise ValueError("Source collection requires a valid work_id.")
    source_fingerprint = getattr(adapter, "source_fingerprint", None)
    if not _valid_identifier(source_fingerprint):
        raise ValueError("Source adapter must provide a stable source_fingerprint.")
    if max_archive_bytes is not None and (
        isinstance(max_archive_bytes, bool)
        or not isinstance(max_archive_bytes, int)
        or max_archive_bytes < 1
    ):
        raise ValueError("Archive byte limit must be a positive integer.")
    checkpoint_fingerprint = _checkpoint_fingerprint(
        source_fingerprint,
        max_archive_bytes,
    )
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("Source collection root must be a directory.")
    manifest_path = resolve_relative_path(
        str(root_path),
        manifest_relative_path,
        allow_missing=True,
    )
    checkpoint_path = resolve_relative_path(
        str(root_path),
        checkpoint_relative_path,
        allow_missing=True,
    )
    manifest_identity = manifest_path.relative_to(root_path).as_posix()
    checkpoint_identity = checkpoint_path.relative_to(root_path).as_posix()
    if manifest_identity.casefold() == checkpoint_identity.casefold():
        raise ValueError("Manifest and checkpoint paths must be different.")
    checkpoint = (
        _read_checkpoint(checkpoint_path)
        if checkpoint_path.exists()
        else new_checkpoint(work_id, checkpoint_fingerprint, manifest_identity)
    )
    if checkpoint["work_id"] != work_id:
        raise ValueError("Source checkpoint belongs to a different work_id.")
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        checkpoint_version = checkpoint["schema_version"]
        if checkpoint["completed_episode_ids"] or checkpoint["status"] == "complete":
            raise ValueError(
                "Legacy source checkpoint has no completed raw version bindings; "
                "use a new checkpoint path after verifying existing output."
            )
        if (
            checkpoint_version == 4
            and checkpoint["manifest_relative_path"] != manifest_identity
        ):
            raise ValueError(
                "Legacy source checkpoint does not match the destination manifest."
            )
        if checkpoint_version < 3:
            raise ValueError(
                "Legacy source checkpoint has no source_fingerprint; use a new "
                "checkpoint path after verifying the source catalog."
            )
        if checkpoint_version in {3, 4} and (
            checkpoint["source_fingerprint"] != checkpoint_fingerprint
        ):
            raise ValueError(
                "Source checkpoint does not match the current source snapshot "
                "or archive limit."
            )
        checkpoint["schema_version"] = CHECKPOINT_SCHEMA_VERSION
        if checkpoint_version < 3:
            checkpoint["source_fingerprint"] = checkpoint_fingerprint
        checkpoint["manifest_relative_path"] = manifest_identity
        checkpoint["completed_raw_versions"] = {}
        validate_checkpoint(checkpoint)
        _write_json(root_path, checkpoint_relative_path, checkpoint)
    else:
        if checkpoint["source_fingerprint"] != checkpoint_fingerprint:
            raise ValueError(
                "Source checkpoint does not match the current source snapshot "
                "or archive limit."
            )
        if checkpoint["manifest_relative_path"] != manifest_identity:
            raise ValueError(
                "Source checkpoint does not match the destination manifest."
            )
    if checkpoint["status"] == "complete":
        return _report(checkpoint)
    if (
        checkpoint["status"] == "paused"
        and checkpoint["pause_reason"] in {"archive_limit", "pagination_cycle"}
    ):
        return _report(checkpoint)
    set_completed_catalog_bytes = getattr(
        adapter, "set_completed_catalog_bytes", None
    )
    if callable(set_completed_catalog_bytes):
        set_completed_catalog_bytes(
            _completed_raw_content_bytes(
                root_path,
                manifest_path,
                work_id,
                checkpoint,
            )
        )
    archive_bytes = None
    if max_archive_bytes is not None:
        existing_manifest = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else new_manifest()
        )
        archive_bytes = verified_manifest_content_bytes(
            root_path,
            existing_manifest,
        )
    if checkpoint["status"] == "paused":
        checkpoint["status"] = "in_progress"
        checkpoint["pause_reason"] = None
        _write_json(root_path, checkpoint_relative_path, checkpoint)
    elif not checkpoint_path.exists():
        _write_json(root_path, checkpoint_relative_path, checkpoint)

    while checkpoint["status"] == "in_progress":
        if not checkpoint["page_loaded"]:
            try:
                page = adapter.list_episodes(checkpoint["cursor"])
            except SourceAccessDenied:
                return _pause(
                    checkpoint, "access_denied", root_path, checkpoint_relative_path
                )
            except SourceRateLimited:
                return _pause(
                    checkpoint, "rate_limited", root_path, checkpoint_relative_path
                )
            except SourceUnavailable:
                return _pause(
                    checkpoint, "unavailable", root_path, checkpoint_relative_path
                )
            _record_page(checkpoint, page)
            _write_json(root_path, checkpoint_relative_path, checkpoint)

        while checkpoint["pending_episodes"]:
            record = checkpoint["pending_episodes"][0]
            episode = EpisodeMetadata(**record)
            try:
                fetched = adapter.fetch_episode(episode.episode_id)
            except ArchiveLimitExceeded:
                return _pause(
                    checkpoint, "archive_limit", root_path, checkpoint_relative_path
                )
            except SourceAccessDenied:
                return _pause(
                    checkpoint, "access_denied", root_path, checkpoint_relative_path
                )
            except SourceRateLimited:
                return _pause(
                    checkpoint, "rate_limited", root_path, checkpoint_relative_path
                )
            except SourceUnavailable:
                return _pause(
                    checkpoint, "unavailable", root_path, checkpoint_relative_path
                )
            if isinstance(fetched, FetchedEpisode):
                _validate_episode_metadata(fetched.metadata)
                if (
                    fetched.metadata.episode_id != episode.episode_id
                    or fetched.metadata.position != episode.position
                    or fetched.metadata.source_ref != episode.source_ref
                ):
                    raise ValueError(
                        "Fetched episode metadata does not match its catalog entry."
                    )
                episode = fetched.metadata
                content = fetched.content
            else:
                content = fetched
            if not isinstance(content, bytes):
                raise ValueError("Source adapter must return episode content as bytes.")

            try:
                archive_bytes = _persist_episode(
                    root_path,
                    manifest_path,
                    work_id,
                    episode,
                    content,
                    max_archive_bytes=max_archive_bytes,
                    current_archive_bytes=archive_bytes,
                )
            except ArchiveLimitExceeded:
                return _pause(
                    checkpoint, "archive_limit", root_path, checkpoint_relative_path
                )
            manifest = load_manifest(manifest_path)
            metadata_artifact, _ = _load_episode_metadata(
                root_path,
                manifest,
                work_id=work_id,
                episode_id=episode.episode_id,
            )
            raw_artifact = _latest_raw_for_metadata(
                manifest,
                work_id=work_id,
                episode_id=episode.episode_id,
                metadata_artifact=metadata_artifact,
            )
            verify_manifest_artifact(root_path, manifest, raw_artifact["version_id"])
            checkpoint["completed_episode_ids"].append(episode.episode_id)
            checkpoint["completed_raw_versions"][episode.episode_id] = (
                raw_artifact["version_id"]
            )
            checkpoint["pending_episodes"].pop(0)
            validate_checkpoint(checkpoint)
            _write_json(root_path, checkpoint_relative_path, checkpoint)

        next_cursor = checkpoint["page_next_cursor"]
        checkpoint["cursor"] = next_cursor
        checkpoint["page_next_cursor"] = None
        checkpoint["page_loaded"] = False
        if next_cursor is None:
            if not checkpoint["discovered_episode_ids"]:
                raise ValueError("Source adapter returned an empty catalog.")
            checkpoint["status"] = "complete"
        elif next_cursor in checkpoint["seen_cursors"]:
            checkpoint["status"] = "paused"
            checkpoint["pause_reason"] = "pagination_cycle"
        _write_json(root_path, checkpoint_relative_path, checkpoint)

    return _report(checkpoint)


def _read_checkpoint(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Source checkpoint path must be a regular file.")
    try:
        with open_regular_file(path) as checkpoint_file:
            checkpoint = json.load(
                checkpoint_file,
                object_pairs_hook=_reject_duplicate_keys,
            )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source checkpoint could not be read as valid JSON.") from exc
    validate_checkpoint(checkpoint)
    return checkpoint
