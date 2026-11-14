"""Adapter-independent source collection and resumable local persistence."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from source_manifest import append_artifact, load_manifest, new_manifest
from utils import open_regular_file, resolve_relative_path, write_text_atomically


CHECKPOINT_SCHEMA_VERSION = 4
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
_CHECKPOINT_FIELDS = _CHECKPOINT_V3_FIELDS | {"manifest_relative_path"}
_EPISODE_FIELDS_V1 = frozenset({"episode_id", "title", "position"})
_EPISODE_FIELDS = _EPISODE_FIELDS_V1 | {"source_ref"}
_PAUSE_REASONS = frozenset(
    {"access_denied", "rate_limited", "unavailable", "pagination_cycle"}
)


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
class LocalEpisodeFile:
    metadata: EpisodeMetadata
    relative_path: str


class SourceAdapter(Protocol):
    @property
    def source_fingerprint(self) -> str: ...

    def list_episodes(self, cursor: str | None) -> CatalogPage: ...

    def fetch_episode(self, episode_id: str) -> bytes: ...


class LocalFileAdapter:
    """Read explicitly mapped local source files without modifying them."""

    def __init__(self, root, episodes, *, page_size: int = 50):
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size < 1
        ):
            raise ValueError("Local source page_size must be a positive integer.")
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Local source root must be a directory.")
        if not isinstance(episodes, (list, tuple)):
            raise ValueError("Local source episodes must be an explicit list.")

        self.page_size = page_size
        input_episodes = tuple(episodes)
        self._files = {}
        self._source_hashes = {}
        seen_ids = set()
        seen_paths = set()
        normalized_episodes = []
        fingerprint_records = []
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
            source_hash = _hash_file(self.root, item.relative_path)
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
            fingerprint_records,
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
        with open_regular_file(path, binary=True) as source_file:
            content = source_file.read()
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
        or version not in {1, 2, 3, CHECKPOINT_SCHEMA_VERSION}
    ):
        raise ValueError("Unsupported source checkpoint schema_version.")
    expected_fields = (
        _CHECKPOINT_FIELDS if version == CHECKPOINT_SCHEMA_VERSION
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
    if not completed <= discovered:
        raise ValueError("Completed episodes must have been discovered.")

    pending = checkpoint["pending_episodes"]
    if not isinstance(pending, list):
        raise ValueError("Source checkpoint pending_episodes must be an array.")
    pending_ids = []
    for episode in pending:
        expected_fields = (
            _EPISODE_FIELDS if version in {2, 3, 4} else _EPISODE_FIELDS_V1
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
    path = resolve_relative_path(str(root), relative_path)
    digest = hashlib.sha256()
    with open_regular_file(path, binary=True) as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _source_artifact_id(work_id: str, kind: str, episode_id: str) -> str:
    identity = json.dumps(
        [work_id, kind, episode_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"source-ingestion:v1:{hashlib.sha256(identity).hexdigest()}"


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
) -> None:
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
    metadata_hash = hashlib.sha256(metadata).hexdigest()
    metadata_artifact_id = _source_artifact_id(
        work_id, "episode", episode.episode_id
    )
    latest_metadata = _latest_artifact(manifest, metadata_artifact_id)

    if latest_metadata and latest_metadata["content_sha256"] == metadata_hash:
        metadata_version_id = latest_metadata["version_id"]
        if _hash_file(root, latest_metadata["relative_path"]) != metadata_hash:
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
        manifest = _append_immutable_artifact(
            root,
            manifest_path,
            manifest,
            metadata_artifact,
            metadata,
        )

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
        if _hash_file(root, latest_raw["relative_path"]) != raw_hash:
            raise ValueError("Existing raw episode has an unexpected hash.")
        return

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
    _append_immutable_artifact(
        root,
        manifest_path,
        manifest,
        raw_artifact,
        content,
    )


def collect_source(
    adapter: SourceAdapter,
    *,
    root,
    work_id: str,
    manifest_relative_path: str = "source_manifest.json",
    checkpoint_relative_path: str = "source_checkpoint.json",
) -> dict:
    """Collect an adapter's catalog and raw bytes without making network requests."""
    if not _valid_identifier(work_id):
        raise ValueError("Source collection requires a valid work_id.")
    source_fingerprint = getattr(adapter, "source_fingerprint", None)
    if not _valid_identifier(source_fingerprint):
        raise ValueError("Source adapter must provide a stable source_fingerprint.")
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
        else new_checkpoint(work_id, source_fingerprint, manifest_identity)
    )
    if checkpoint["work_id"] != work_id:
        raise ValueError("Source checkpoint belongs to a different work_id.")
    if checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        checkpoint_version = checkpoint["schema_version"]
        if checkpoint["completed_episode_ids"]:
            raise ValueError(
                "Legacy source checkpoint has no destination manifest identity; "
                "use a new checkpoint path after verifying existing output."
            )
        if checkpoint_version < 3 and checkpoint["status"] != "complete":
            raise ValueError(
                "Legacy source checkpoint has no source_fingerprint; use a new "
                "checkpoint path after verifying the source catalog."
            )
        if (
            checkpoint_version == 3
            and checkpoint["source_fingerprint"] != source_fingerprint
        ):
            raise ValueError(
                "Source checkpoint does not match the current source snapshot."
            )
        checkpoint["schema_version"] = CHECKPOINT_SCHEMA_VERSION
        if checkpoint_version < 3:
            checkpoint["source_fingerprint"] = source_fingerprint
        checkpoint["manifest_relative_path"] = manifest_identity
        validate_checkpoint(checkpoint)
        _write_json(root_path, checkpoint_relative_path, checkpoint)
    else:
        if checkpoint["source_fingerprint"] != source_fingerprint:
            raise ValueError(
                "Source checkpoint does not match the current source snapshot."
            )
        if checkpoint["manifest_relative_path"] != manifest_identity:
            raise ValueError(
                "Source checkpoint does not match the destination manifest."
            )
    if checkpoint["status"] == "complete":
        return _report(checkpoint)
    if (
        checkpoint["status"] == "paused"
        and checkpoint["pause_reason"] == "pagination_cycle"
    ):
        return _report(checkpoint)
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
                content = adapter.fetch_episode(episode.episode_id)
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
            if not isinstance(content, bytes):
                raise ValueError("Source adapter must return episode content as bytes.")

            _persist_episode(
                root_path,
                manifest_path,
                work_id,
                episode,
                content,
            )
            checkpoint["completed_episode_ids"].append(episode.episode_id)
            checkpoint["pending_episodes"].pop(0)
            validate_checkpoint(checkpoint)
            _write_json(root_path, checkpoint_relative_path, checkpoint)

        next_cursor = checkpoint["page_next_cursor"]
        checkpoint["cursor"] = next_cursor
        checkpoint["page_next_cursor"] = None
        checkpoint["page_loaded"] = False
        if next_cursor is None:
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
