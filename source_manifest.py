"""Local version-manifest contract; this module does not ingest source content."""

import copy
import hashlib
import json
import re
from pathlib import Path, PureWindowsPath

from utils import open_regular_file, resolve_relative_path, write_text_atomically


SCHEMA_VERSION = 1
ARTIFACT_KINDS = frozenset(
    {
        "work",
        "episode",
        "raw_source",
        "normalized_source",
        "translation",
        "knowledge",
        "export",
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = frozenset({"schema_version", "artifacts"})
_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "version_id",
        "kind",
        "content_sha256",
        "relative_path",
        "parent_version_ids",
    }
)


def new_manifest() -> dict:
    return {"schema_version": SCHEMA_VERSION, "artifacts": []}


def _is_identifier(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and not any(ord(character) < 32 for character in value)
    )


def _validate_relative_path(value, index: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Artifact {index} has an invalid relative_path.")
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        value.startswith("/")
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Artifact {index} has an invalid relative_path.")


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("Source manifest must contain only schema_version and artifacts.")
    version = manifest["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ValueError("Unsupported source manifest schema_version.")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("Source manifest artifacts must be an array.")

    versions = {}
    artifact_kinds = {}
    paths = set()
    parents_by_version = {}

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_FIELDS:
            raise ValueError(f"Artifact {index} has an invalid field set.")
        artifact_id = artifact["artifact_id"]
        version_id = artifact["version_id"]
        kind = artifact["kind"]
        digest = artifact["content_sha256"]
        parents = artifact["parent_version_ids"]

        if not _is_identifier(artifact_id) or not _is_identifier(version_id):
            raise ValueError(f"Artifact {index} has an invalid identifier.")
        if not isinstance(kind, str) or kind not in ARTIFACT_KINDS:
            raise ValueError(f"Artifact {index} has an unsupported kind.")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError(f"Artifact {index} has an invalid content_sha256.")
        if not isinstance(parents, list) or any(
            not _is_identifier(parent) for parent in parents
        ):
            raise ValueError(f"Artifact {index} has invalid parent_version_ids.")
        if len(parents) != len(set(parents)):
            raise ValueError(f"Artifact {index} repeats a parent version.")

        if version_id in versions:
            raise ValueError(f"Artifact {index} repeats a version_id.")
        if artifact_id in artifact_kinds and artifact_kinds[artifact_id] != kind:
            raise ValueError(f"Artifact {index} changes the kind of an artifact_id.")

        _validate_relative_path(artifact["relative_path"], index)
        relative_path = artifact["relative_path"]
        if relative_path is not None:
            path_key = relative_path.casefold()
            if path_key in paths:
                raise ValueError(f"Artifact {index} repeats a relative_path.")
            paths.add(path_key)

        versions[version_id] = artifact
        artifact_kinds[artifact_id] = kind
        parents_by_version[version_id] = parents

    for version_id, parents in parents_by_version.items():
        if version_id in parents:
            raise ValueError("An artifact version cannot parent itself.")
        if any(parent not in versions for parent in parents):
            raise ValueError("Source manifest references a missing parent version.")

    pending_parent_counts = {
        version_id: len(parents)
        for version_id, parents in parents_by_version.items()
    }
    children_by_parent = {version_id: [] for version_id in parents_by_version}
    for version_id, parents in parents_by_version.items():
        for parent in parents:
            children_by_parent[parent].append(version_id)

    ready = [
        version_id
        for version_id, parent_count in pending_parent_counts.items()
        if parent_count == 0
    ]
    visited_count = 0
    while ready:
        parent = ready.pop()
        visited_count += 1
        for child in children_by_parent[parent]:
            pending_parent_counts[child] -= 1
            if pending_parent_counts[child] == 0:
                ready.append(child)

    if visited_count != len(parents_by_version):
        raise ValueError("Source manifest parent relationships contain a cycle.")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Source manifest contains a duplicate JSON field.")
        result[key] = value
    return result


def load_manifest(path) -> dict:
    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Source manifest path must be a regular file.")
    try:
        with open_regular_file(manifest_path) as manifest_file:
            manifest = json.load(
                manifest_file,
                object_pairs_hook=_reject_duplicate_keys,
            )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source manifest could not be read as valid JSON.") from exc
    validate_manifest(manifest)
    return manifest


def verify_manifest_files(root, manifest: dict) -> int:
    """Verify recorded hashes against files beneath an explicit root."""
    validate_manifest(manifest)
    verified_files = 0
    for artifact in manifest["artifacts"]:
        relative_path = artifact["relative_path"]
        if relative_path is None:
            continue

        version_id = artifact["version_id"]
        try:
            source_path = resolve_relative_path(str(root), relative_path)
            digest = hashlib.sha256()
            with open_regular_file(source_path, binary=True) as source_file:
                for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"Artifact version {version_id!r} could not be verified."
            ) from exc

        if digest.hexdigest() != artifact["content_sha256"]:
            raise ValueError(
                f"Artifact version {version_id!r} content hash does not match."
            )
        verified_files += 1
    return verified_files


def append_artifact(path, artifact: dict) -> dict:
    manifest_path = Path(path)
    if manifest_path.is_symlink():
        raise ValueError("Symbolic links are not allowed for source manifests.")
    manifest = load_manifest(manifest_path) if manifest_path.exists() else new_manifest()
    updated = copy.deepcopy(manifest)
    updated["artifacts"].append(copy.deepcopy(artifact))
    validate_manifest(updated)
    serialized = json.dumps(
        updated,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    write_text_atomically(str(manifest_path), serialized + "\n")
    return updated
