"""Discover or load a Kakuyomu catalog and run the production translation pipeline."""

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chapter_transaction import has_pending_chapter_transaction  # noqa: E402
from kakuyomu_page_source import (  # noqa: E402
    DEFAULT_MAX_EPISODES,
    DEFAULT_REQUEST_DELAY_SECONDS,
    MAX_REQUEST_DELAY_SECONDS,
    MIN_REQUEST_DELAY_SECONDS,
    KakuyomuPageAdapter,
    discover_kakuyomu_work_catalog,
    save_discovered_work_catalog,
)
from pipeline import (  # noqa: E402
    Config,
    TranslationPipeline,
    validate_provider_configuration,
)
from scripts.ingest_kakuyomu_pages import (  # noqa: E402
    _load_catalog,
    _validate_output_paths,
)
from source_ingestion import (  # noqa: E402
    ArchiveLimitExceeded,
    SourceAccessDenied,
    SourceRateLimited,
    SourceUnavailable,
    _latest_raw_for_metadata,
    _load_episode_metadata,
    collect_source,
    materialize_episode_markdown,
    source_artifact_id,
)
from source_manifest import (  # noqa: E402
    latest_artifacts_by_kind,
    load_manifest,
    verify_manifest_artifact,
)
from utils import (  # noqa: E402
    open_regular_file,
    read_relative_text,
    resolve_relative_path,
    split_paragraphs,
    validate_tm_source_provenance,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive integer.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return parsed


def _minimum_delay(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Request delay must be a positive finite number."
        ) from exc
    if (
        not math.isfinite(parsed)
        or not MIN_REQUEST_DELAY_SECONDS
        <= parsed
        <= MAX_REQUEST_DELAY_SECONDS
    ):
        raise argparse.ArgumentTypeError(
            "Request delay must be between 1.5 and 3 seconds."
        )
    return parsed


def _roots_are_disjoint(source_path: Path, translation_path: Path) -> bool:
    try:
        common = Path(os.path.commonpath((source_path, translation_path)))
    except ValueError as exc:
        source_drive = os.path.splitdrive(str(source_path))[0].casefold()
        translation_drive = os.path.splitdrive(str(translation_path))[0].casefold()
        if source_drive and translation_drive and source_drive != translation_drive:
            return True
        raise ValueError("Source and translation roots must be disjoint.") from exc
    return common not in (source_path, translation_path)


def _resolve_roots(source_root: str, translation_root: str) -> tuple[Path, Path]:
    source_path = Path(source_root).resolve(strict=True)
    translation_path = Path(translation_root).resolve(strict=True)
    if not source_path.is_dir() or not translation_path.is_dir():
        raise ValueError("Source and translation roots must be directories.")
    if not _roots_are_disjoint(source_path, translation_path):
        raise ValueError("Source and translation roots must be disjoint.")
    return source_path, translation_path


def _translation_targets(work_id: str, episodes) -> list[dict]:
    targets = []
    episode_ids = set()
    positions = set()
    for episode in episodes:
        if not hasattr(episode, "metadata"):
            raise ValueError("Catalog contains an invalid episode entry.")
        metadata = episode.metadata
        if (
            not isinstance(metadata.episode_id, str)
            or not metadata.episode_id.isascii()
            or not metadata.episode_id.isdecimal()
            or isinstance(metadata.position, bool)
            or not isinstance(metadata.position, int)
            or metadata.position < 1
            or not isinstance(metadata.title, str)
        ):
            raise ValueError("Catalog contains invalid episode metadata.")
        if metadata.episode_id in episode_ids or metadata.position in positions:
            raise ValueError("Catalog episode IDs and positions must be unique.")
        episode_ids.add(metadata.episode_id)
        positions.add(metadata.position)
        targets.append(
            {
                "episode_id": metadata.episode_id,
                "position": metadata.position,
                "translation_file": (
                    f"episode-{metadata.position:04d}-{metadata.episode_id}.md"
                ),
                "tm_key": f"kakuyomu:{work_id}:{metadata.episode_id}",
            }
        )
    return targets


def preview_translation_plan(
    *,
    source_root: str,
    catalog: str,
    translation_root: str,
    manifest: str = "source_manifest.json",
) -> dict:
    """Build a read-only, source-verified chapter map without network or providers."""
    source_path, translation_path = _resolve_roots(
        source_root, translation_root
    )
    work_id, episodes, _catalog_path = _load_catalog(
        str(source_path), catalog
    )
    targets = _translation_targets(work_id, episodes)
    _check_translation_targets(translation_path, targets)

    manifest_path = resolve_relative_path(str(source_path), manifest)
    source_manifest = load_manifest(manifest_path)
    metadata_by_id = latest_artifacts_by_kind(source_manifest, "episode")
    raw_by_id = latest_artifacts_by_kind(source_manifest, "raw_source")
    normalized_by_id = latest_artifacts_by_kind(
        source_manifest, "normalized_source"
    )

    planned_episodes = []
    issues = []
    for episode, target in zip(episodes, targets):
        episode_id = target["episode_id"]
        target_path = resolve_relative_path(
            str(translation_path),
            target["translation_file"],
            allow_missing=True,
        )
        planned = {
            "episode_id": episode_id,
            "position": target["position"],
            "title": episode.metadata.title,
            "source_file": None,
            "source_version_id": None,
            "translation_file": target["translation_file"],
            "translation_target_exists": target_path.exists(),
            "tm_key": target["tm_key"],
        }

        def add_issue(code: str) -> None:
            issues.append({"episode_id": episode_id, "code": code})

        if planned["translation_target_exists"]:
            add_issue("translation_target_exists")

        metadata_id = source_artifact_id(work_id, "episode", episode_id)
        if metadata_id not in metadata_by_id:
            add_issue("missing_episode_metadata")
            planned_episodes.append(planned)
            continue
        try:
            metadata_artifact, source_metadata = _load_episode_metadata(
                source_path,
                source_manifest,
                work_id=work_id,
                episode_id=episode_id,
            )
        except (OSError, UnicodeError, ValueError):
            add_issue("invalid_episode_metadata")
            planned_episodes.append(planned)
            continue
        if (
            source_metadata["title"] != episode.metadata.title
            or source_metadata["position"] != episode.metadata.position
        ):
            add_issue("catalog_metadata_mismatch")
            planned_episodes.append(planned)
            continue

        try:
            raw_artifact = _latest_raw_for_metadata(
                source_manifest,
                work_id=work_id,
                episode_id=episode_id,
                metadata_artifact=metadata_artifact,
            )
        except ValueError:
            add_issue("missing_raw_source")
            planned_episodes.append(planned)
            continue

        raw_id = source_artifact_id(work_id, "raw_source", episode_id)
        latest_raw = raw_by_id.get(raw_id)
        if latest_raw is None or latest_raw["version_id"] != raw_artifact["version_id"]:
            add_issue("stale_raw_source")
            planned_episodes.append(planned)
            continue
        try:
            verify_manifest_artifact(
                source_path, source_manifest, raw_artifact["version_id"]
            )
        except (OSError, UnicodeError, ValueError):
            add_issue("invalid_raw_source")
            planned_episodes.append(planned)
            continue

        normalized_id = source_artifact_id(
            work_id, "normalized_source", episode_id
        )
        normalized = normalized_by_id.get(normalized_id)
        if normalized is None:
            add_issue("missing_normalized_source")
            planned_episodes.append(planned)
            continue
        planned["source_file"] = normalized["relative_path"]
        planned["source_version_id"] = normalized["version_id"]
        if raw_artifact["version_id"] not in normalized["parent_version_ids"]:
            add_issue("stale_normalized_source")
            planned_episodes.append(planned)
            continue
        try:
            verify_manifest_artifact(
                source_path, source_manifest, normalized["version_id"]
            )
        except (OSError, UnicodeError, ValueError):
            add_issue("invalid_normalized_source")
        planned_episodes.append(planned)

    plan = {
        "schema_version": 1,
        "status": "ready_for_review" if not issues else "blocked",
        "work_id": work_id,
        "catalog": catalog.replace("\\", "/"),
        "manifest": manifest.replace("\\", "/"),
        "episode_count": len(planned_episodes),
        "verified_source_count": sum(
            episode["source_version_id"] is not None
            and not any(
                issue["episode_id"] == episode["episode_id"]
                and issue["code"]
                in {
                    "stale_normalized_source",
                    "invalid_normalized_source",
                }
                for issue in issues
            )
            for episode in planned_episodes
        ),
        "network_requests": 0,
        "provider_calls": 0,
        "filesystem_writes": 0,
        "source_text_included": False,
        "episodes": planned_episodes,
        "issues": issues,
    }
    canonical_plan = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan["plan_sha256"] = hashlib.sha256(canonical_plan).hexdigest()
    return plan


def _check_translation_targets(translation_root: Path, targets) -> None:
    for target in targets:
        output_path = resolve_relative_path(
            str(translation_root),
            target["translation_file"],
            allow_missing=True,
        )
        if output_path.exists() and not output_path.is_file():
            raise ValueError("A translation target is not a regular file.")


def _is_committed_translation(
    source_root: str,
    translation_root: str,
    target: dict,
    source_artifact: dict,
    tm_data: dict,
) -> bool:
    try:
        raw_text = read_relative_text(source_root, source_artifact["raw_file"])
        translation_path = resolve_relative_path(
            translation_root, target["translation_file"]
        )
        with open_regular_file(translation_path, binary=True) as stream:
            translation_bytes = stream.read()
        with io.TextIOWrapper(
            io.BytesIO(translation_bytes), encoding="utf-8"
        ) as text_stream:
            translation_text = text_stream.read()
    except (OSError, UnicodeError, ValueError, KeyError):
        return False
    expected_translation_bytes = translation_text.replace(
        "\n", os.linesep
    ).encode("utf-8")
    if translation_bytes != expected_translation_bytes:
        return False

    chapters = tm_data.get("chapters")
    provenance_by_chapter = tm_data.get("source_provenance")
    pairs = chapters.get(target["tm_key"]) if isinstance(chapters, dict) else None
    provenance = (
        provenance_by_chapter.get(target["tm_key"])
        if isinstance(provenance_by_chapter, dict)
        else None
    )
    if not isinstance(pairs, list) or not isinstance(provenance, dict):
        return False
    try:
        validate_tm_source_provenance(provenance, len(pairs))
    except (TypeError, ValueError):
        return False

    raw_paragraphs = split_paragraphs(raw_text)
    translated_paragraphs = split_paragraphs(translation_text)
    if (
        provenance.get("raw_file") != source_artifact["raw_file"]
        or provenance.get("translation_file") != target["translation_file"]
        or provenance.get("raw_sha256")
        != hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        or provenance.get("translation_sha256")
        != hashlib.sha256(translation_text.encode("utf-8")).hexdigest()
        or provenance.get("source_version_id")
        != source_artifact["source_version_id"]
        or len(raw_paragraphs) != len(translated_paragraphs)
        or len(pairs) != len(raw_paragraphs)
        or "\n\n".join(translated_paragraphs) != translation_text
    ):
        return False
    expected_mappings = [
        {
            "pair_index": index,
            "raw_paragraph_indices": [index],
            "translation_paragraph_indices": [index],
            "trace_status": "matched",
        }
        for index in range(1, len(raw_paragraphs) + 1)
    ]
    if provenance.get("pair_mappings") != expected_mappings:
        return False
    return all(
        isinstance(pair, dict)
        and pair.get("raw") == raw
        and pair.get("translated") == translated
        for pair, raw, translated in zip(
            pairs, raw_paragraphs, translated_paragraphs
        )
    )


def _validate_project_config() -> None:
    workspace = getattr(Config, "WORKSPACE_DIR", None)
    if not isinstance(workspace, str) or not workspace:
        raise ValueError("Project configuration must define WORKSPACE_DIR.")
    workspace_path = Path(workspace).resolve(strict=True)
    if not workspace_path.is_dir():
        raise ValueError("WORKSPACE_DIR must be an existing directory.")
    info_path = getattr(Config, "INFO_PATH", None)
    if not isinstance(info_path, str) or not Path(info_path).is_file():
        raise ValueError("Project configuration must define an existing INFO_PATH.")
    tm_path = getattr(Config, "TM_PATH", None)
    if not isinstance(tm_path, str) or not tm_path:
        raise ValueError("Project configuration must define TM_PATH.")


def run_workflow(
    *,
    source_root: str,
    catalog: str | None = None,
    work_url: str | None = None,
    translation_root: str,
    config_file: str,
    discovered_catalog: str = "source_catalog.discovered.json",
    manifest: str = "source_manifest.json",
    checkpoint: str | None = None,
    max_archive_bytes: int | None = None,
    max_episodes: int = DEFAULT_MAX_EPISODES,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    config_loader=None,
    discovery_factory=None,
    adapter_factory=None,
) -> dict:
    if (catalog is None) == (work_url is None):
        raise ValueError("Specify exactly one of catalog or work_url.")
    source_path, translation_path = _resolve_roots(
        source_root, translation_root
    )
    config_path = Path(config_file).resolve(strict=True)
    if not config_path.is_file():
        raise ValueError("Configuration path must be a regular file.")

    loader = config_loader or Config.load_config
    loader(config_file=str(config_path))
    _validate_project_config()
    Config.RAW_DIR = str(source_path)
    Config.OUTPUT_DIR = str(translation_path)
    Config.CHAPTER_MAP = None
    Config.SOURCE_MANIFEST_PATH = manifest
    validate_provider_configuration()

    if checkpoint is None:
        checkpoint = (
            "source_checkpoint.discovered.json"
            if work_url
            else "source_checkpoint.json"
        )

    discovery = None
    if work_url:
        discover = discovery_factory or discover_kakuyomu_work_catalog
        discovery = discover(
            work_url,
            max_episodes=max_episodes,
            request_delay_seconds=request_delay_seconds,
        )
        work_id = discovery.work_id
        episodes = discovery.episodes
        catalog_path = resolve_relative_path(
            str(source_path),
            discovered_catalog,
            allow_missing=True,
        )
    else:
        work_id, episodes, catalog_path = _load_catalog(
            str(source_path), catalog
        )
    _validate_output_paths(
        str(source_path),
        str(source_path),
        catalog_path,
        manifest,
        checkpoint,
    )
    targets = _translation_targets(work_id, episodes)
    _check_translation_targets(translation_path, targets)
    if discovery is not None:
        catalog_path = save_discovered_work_catalog(
            source_path,
            discovered_catalog,
            work_id,
            episodes,
        )

    if adapter_factory is not None:
        adapter = adapter_factory(work_id, episodes)
    elif discovery is not None:
        adapter = discovery.create_page_adapter(max_episodes=max_episodes)
    else:
        adapter = KakuyomuPageAdapter(
            work_id,
            episodes,
            max_episodes=max_episodes,
            request_delay_seconds=request_delay_seconds,
        )
    source_report = collect_source(
        adapter,
        root=str(source_path),
        work_id=work_id,
        manifest_relative_path=manifest,
        checkpoint_relative_path=checkpoint,
        max_archive_bytes=max_archive_bytes,
    )
    if source_report["status"] != "complete":
        return {
            "status": "source_incomplete",
            "source_status": source_report["status"],
            "pause_reason": source_report["reason"],
            "work_id": work_id,
            "discovered_count": source_report["discovered_count"],
            "completed_count": source_report["completed_count"],
            "pending_count": source_report["pending_count"],
            "discovered_catalog": (
                str(catalog_path.relative_to(source_path))
                if discovery is not None
                else None
            ),
        }

    chapter_map = []
    for target in targets:
        artifact = materialize_episode_markdown(
            str(source_path),
            work_id=work_id,
            episode_id=target["episode_id"],
            manifest_relative_path=manifest,
        )
        chapter_map.append(
            {
                "raw_file": artifact["relative_path"],
                "translation_file": target["translation_file"],
                "tm_key": target["tm_key"],
                "source_version_id": artifact["version_id"],
                "chapter_position": target["position"],
            }
        )

    Config.CHAPTER_MAP = chapter_map
    pipeline = TranslationPipeline()
    tm_data = pipeline.rag.tm_data
    tm_chapters = tm_data.get("chapters", {})
    for target, chapter in zip(targets, chapter_map):
        pending = has_pending_chapter_transaction(
            str(translation_path),
            target["translation_file"],
            target["tm_key"],
        )
        output_path = resolve_relative_path(
            str(translation_path),
            target["translation_file"],
            allow_missing=True,
        )
        committed = _is_committed_translation(
            str(source_path),
            str(translation_path),
            target,
            chapter,
            tm_data,
        )
        if (
            (output_path.exists() or target["tm_key"] in tm_chapters)
            and not pending
            and not committed
        ):
            raise FileExistsError(
                "Existing translation output or memory does not match the current source."
            )

    asyncio.run(pipeline.run_all())
    return {
        "status": "complete",
        "work_id": work_id,
        "discovered_catalog": (
            str(catalog_path.relative_to(source_path))
            if discovery is not None
            else None
        ),
        "discovery_fingerprint": (
            discovery.source_fingerprint if discovery is not None else None
        ),
        "episodes": [
            {
                "episode_id": target["episode_id"],
                "position": target["position"],
                "source_version_id": chapter["source_version_id"],
                "translation_file": target["translation_file"],
                "tm_key": target["tm_key"],
            }
            for target, chapter in zip(targets, chapter_map)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover public episodes from a Kakuyomu work page or use an "
            "explicit catalog, archive versioned source, and run translation."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument(
        "--catalog",
        help="Existing JSON catalog path relative to --source-root.",
    )
    parser.add_argument(
        "--work-url",
        help="Discover the public episode catalog from this Kakuyomu work URL.",
    )
    parser.add_argument(
        "--discovered-catalog",
        default="source_catalog.discovered.json",
        help="New relative catalog path used with --work-url.",
    )
    parser.add_argument("--translation-root", required=True)
    parser.add_argument(
        "--config",
        help="Existing project JSON configuration; provider settings stay local.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help=(
            "Read an existing --catalog and source manifest, then print a "
            "provider-free chapter mapping preview."
        ),
    )
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--checkpoint")
    parser.add_argument(
        "--max-episodes",
        type=_positive_int,
        default=DEFAULT_MAX_EPISODES,
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=_minimum_delay,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
    )
    parser.add_argument(
        "--max-archive-bytes",
        type=_positive_int,
        help=(
            "Optional ceiling for newly archived manifest content; "
            "not a physical disk quota."
        ),
    )
    args = parser.parse_args(argv)
    if args.plan_only:
        if args.config:
            parser.error("--config is not used with --plan-only.")
        if args.work_url:
            parser.error("--plan-only requires an existing --catalog; it does not access the network.")
        if not args.catalog:
            parser.error("--plan-only requires --catalog.")
    elif not args.config:
        parser.error("--config is required unless --plan-only is set.")
    if (args.catalog is None) == (args.work_url is None):
        if not args.plan_only:
            parser.error("Specify exactly one of --catalog or --work-url.")

    try:
        if args.plan_only:
            report = preview_translation_plan(
                source_root=args.source_root,
                catalog=args.catalog,
                translation_root=args.translation_root,
                manifest=args.manifest,
            )
        else:
            report = run_workflow(
                source_root=args.source_root,
                catalog=args.catalog,
                work_url=args.work_url,
                translation_root=args.translation_root,
                config_file=args.config,
                discovered_catalog=args.discovered_catalog,
                manifest=args.manifest,
                checkpoint=args.checkpoint,
                max_archive_bytes=args.max_archive_bytes,
                max_episodes=args.max_episodes,
                request_delay_seconds=args.request_delay_seconds,
            )
    except (
        OSError,
        UnicodeError,
        ValueError,
        PermissionError,
        RuntimeError,
        ArchiveLimitExceeded,
        SourceAccessDenied,
        SourceRateLimited,
        SourceUnavailable,
    ) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    if args.plan_only:
        return 0 if report["status"] == "ready_for_review" else 2
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
