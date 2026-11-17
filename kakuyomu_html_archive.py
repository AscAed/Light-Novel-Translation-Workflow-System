"""Read-only replay validation for archived Kakuyomu episode HTML."""

import hashlib
import json
from pathlib import Path

from kakuyomu_page_source import (
    PARSER_VERSION,
    _EpisodePageParser,
    _normalize_title,
)
from source_ingestion import source_artifact_id
from source_manifest import (
    latest_artifacts_by_kind,
    load_manifest,
    verify_manifest_files,
)
from utils import open_regular_file, resolve_relative_path


DEFAULT_MAX_TOTAL_HTML_BYTES = 1024 * 1024 * 1024
_EPISODE_METADATA_FIELDS = frozenset(
    {"schema_version", "work_id", "episode_id", "title", "position", "source_ref"}
)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Episode metadata contains a duplicate JSON field.")
        result[key] = value
    return result


def _load_episode_metadata(root: Path, artifact: dict) -> dict:
    if artifact["relative_path"] is None:
        raise ValueError("Episode metadata has no content file.")
    path = resolve_relative_path(str(root), artifact["relative_path"])
    with open_regular_file(path, binary=True) as metadata_file:
        payload = metadata_file.read()
    try:
        metadata = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Episode metadata is not valid UTF-8 JSON.") from exc
    if (
        not isinstance(metadata, dict)
        or set(metadata) != _EPISODE_METADATA_FIELDS
        or isinstance(metadata["schema_version"], bool)
        or metadata["schema_version"] != 1
        or not isinstance(metadata["work_id"], str)
        or not isinstance(metadata["episode_id"], str)
        or not isinstance(metadata["title"], str)
        or not metadata["title"].strip()
        or isinstance(metadata["position"], bool)
        or not isinstance(metadata["position"], int)
        or metadata["position"] < 1
    ):
        raise ValueError("Episode metadata has an invalid identity or schema.")
    return metadata


def validate_kakuyomu_html_archive(
    *,
    source_root,
    manifest_relative_path: str = "source_manifest.json",
    max_total_html_bytes: int = DEFAULT_MAX_TOTAL_HTML_BYTES,
) -> dict:
    """Verify current archived HTML can reproduce its bound visible text."""
    if (
        isinstance(max_total_html_bytes, bool)
        or not isinstance(max_total_html_bytes, int)
        or max_total_html_bytes < 1
    ):
        raise ValueError("Maximum total HTML bytes must be a positive integer.")

    root = Path(source_root).resolve(strict=True)
    manifest_path = resolve_relative_path(str(root), manifest_relative_path)
    manifest = load_manifest(manifest_path)
    all_html = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact["kind"] == "raw_page_html"
    ]
    latest_html = latest_artifacts_by_kind(manifest, "raw_page_html")
    latest_raw = latest_artifacts_by_kind(manifest, "raw_source")
    latest_episodes = latest_artifacts_by_kind(manifest, "episode")
    if not latest_html:
        raise ValueError("Source manifest contains no archived episode HTML.")

    versions = {
        artifact["version_id"]: artifact for artifact in manifest["artifacts"]
    }
    html_sizes = {}
    total_html_bytes = 0
    for html_artifact in all_html:
        if html_artifact["relative_path"] is None:
            raise ValueError("Archived episode HTML has no content file.")
        html_path = resolve_relative_path(str(root), html_artifact["relative_path"])
        if html_path.is_symlink() or not html_path.is_file():
            raise ValueError("Archived episode HTML must be a regular file.")
        size = html_path.stat().st_size
        total_html_bytes += size
        if total_html_bytes > max_total_html_bytes:
            raise ValueError("Archived episode HTML exceeds the byte limit.")
        html_sizes[html_artifact["version_id"]] = size

    files_verified = verify_manifest_files(root, manifest)
    body_bytes = 0
    for html_artifact in latest_html.values():
        parents = [
            versions[parent_id]
            for parent_id in html_artifact["parent_version_ids"]
        ]
        raw_parents = [item for item in parents if item["kind"] == "raw_source"]
        episode_parents = [item for item in parents if item["kind"] == "episode"]
        if len(raw_parents) != 1 or len(episode_parents) != 1:
            raise ValueError(
                "Archived episode HTML must bind one raw source and one episode."
            )

        raw_parent = raw_parents[0]
        episode_parent = episode_parents[0]
        if (
            latest_raw.get(raw_parent["artifact_id"], {}).get("version_id")
            != raw_parent["version_id"]
            or latest_episodes.get(episode_parent["artifact_id"], {}).get(
                "version_id"
            )
            != episode_parent["version_id"]
        ):
            raise ValueError("Archived episode HTML has stale source lineage.")
        if raw_parent["relative_path"] is None:
            raise ValueError("Current raw source has no content file.")

        metadata = _load_episode_metadata(root, episode_parent)
        expected_ids = {
            "episode": source_artifact_id(
                metadata["work_id"], "episode", metadata["episode_id"]
            ),
            "raw_source": source_artifact_id(
                metadata["work_id"], "raw_source", metadata["episode_id"]
            ),
            "raw_page_html": source_artifact_id(
                metadata["work_id"], "raw_page_html", metadata["episode_id"]
            ),
        }
        if (
            episode_parent["artifact_id"] != expected_ids["episode"]
            or raw_parent["artifact_id"] != expected_ids["raw_source"]
            or html_artifact["artifact_id"] != expected_ids["raw_page_html"]
        ):
            raise ValueError("Archived episode HTML has mismatched episode identity.")

        html_path = resolve_relative_path(str(root), html_artifact["relative_path"])
        with open_regular_file(html_path, binary=True) as html_file:
            html_bytes = html_file.read()
        if (
            len(html_bytes) != html_sizes[html_artifact["version_id"]]
            or hashlib.sha256(html_bytes).hexdigest()
            != html_artifact["content_sha256"]
        ):
            raise ValueError("Archived episode HTML changed during validation.")
        try:
            page_text = html_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Archived episode HTML is not valid UTF-8.") from exc

        parser = _EpisodePageParser()
        parser.feed(page_text)
        parser.close()
        if (
            parser.body_count != 1
            or parser.title_count != 1
            or parser._body_stack
            or parser._title_stack
        ):
            raise ValueError(
                "Archived episode HTML has an invalid title or body region."
            )
        if parser.extracted_title() != _normalize_title(metadata["title"]):
            raise ValueError("Archived episode HTML title does not match metadata.")

        visible_bytes = parser.extracted_body().encode("utf-8")
        if not visible_bytes:
            raise ValueError("Archived episode HTML produced an empty body.")
        if hashlib.sha256(visible_bytes).hexdigest() != raw_parent["content_sha256"]:
            raise ValueError(
                "Archived episode HTML does not reproduce its raw source."
            )
        raw_path = resolve_relative_path(str(root), raw_parent["relative_path"])
        raw_digest = hashlib.sha256()
        with open_regular_file(raw_path, binary=True) as raw_file:
            for chunk in iter(lambda: raw_file.read(1024 * 1024), b""):
                raw_digest.update(chunk)
        if raw_digest.hexdigest() != raw_parent["content_sha256"]:
            raise ValueError("Current raw source changed during validation.")
        body_bytes += len(visible_bytes)

    return {
        "status": "verified",
        "parser_version": PARSER_VERSION,
        "episode_count": len(latest_html),
        "files_verified": files_verified,
        "html_bytes": total_html_bytes,
        "body_bytes": body_bytes,
    }
