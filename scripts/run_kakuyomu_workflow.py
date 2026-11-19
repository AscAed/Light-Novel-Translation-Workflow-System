"""Discover or load a Kakuyomu catalog and run the production translation pipeline."""

import argparse
import asyncio
import functools
import hashlib
import io
import json
import math
import os
import re
import sys
import uuid
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
    TranslationQualityGateError,
    _resolve_project_human_edition_root,
    validate_provider_configuration,
)
from book_bundles import (  # noqa: E402
    export_book_bundles,
    load_verified_ai_book_bundle,
)
from scripts.ingest_kakuyomu_pages import (  # noqa: E402
    _load_catalog,
    _load_catalog_snapshot,
    _validate_output_paths,
)
from scripts.snapshot_downstream_freshness import (  # noqa: E402
    _load_json_regular,
    build_downstream_freshness_snapshot,
    persist_downstream_freshness_snapshot,
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
    verify_current_normalized_source_metadata,
)
from source_editions import (  # noqa: E402
    StaleAIEditionCatalogError,
    prepare_source_editions,
    read_verified_ai_edition_bytes,
    verify_ai_edition_index,
)
from story_summary_review import load_reviewed_story_summary  # noqa: E402
from translation_plan_approval import (  # noqa: E402
    translation_plan_sha256,
    verify_approval_receipt,
    write_new_json,
)
from translation_review import (  # noqa: E402
    _load_run,
    build_translation_run_manifest,
)
from utils import (  # noqa: E402
    open_regular_file,
    read_relative_text,
    resolve_relative_path,
    split_paragraphs,
    validate_tm_source_provenance,
    write_text_atomically,
)


def _preserve_workflow_config(function):
    """Restore explicit workflow overrides for embedded callers and retries."""

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        previous = {
            field: value
            for field, value in vars(Config).items()
            if field.isupper()
        }
        try:
            return function(*args, **kwargs)
        finally:
            for field in tuple(vars(Config)):
                if field.isupper() and field not in previous:
                    delattr(Config, field)
            for field, value in previous.items():
                setattr(Config, field, value)

    return wrapped


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


def _validate_workflow_root_boundaries(
    source_path: Path,
    translation_path: Path,
    human_edition_root: str,
    ai_edition_root: str,
) -> None:
    roots = (
        source_path.resolve(strict=False),
        Path(human_edition_root).resolve(strict=False),
        Path(ai_edition_root).resolve(strict=False),
        translation_path.resolve(strict=False),
    )
    if any(
        not _roots_are_disjoint(roots[left], roots[right])
        for left in range(len(roots))
        for right in range(left + 1, len(roots))
    ):
        raise ValueError(
            "SourceArchive, human edition, RAWs_AI, and translation roots "
            "must be pairwise disjoint."
        )


def _resolve_roots(source_root: str, translation_root: str) -> tuple[Path, Path]:
    source_path = Path(source_root).resolve(strict=True)
    translation_path = Path(translation_root).resolve(strict=True)
    if not source_path.is_dir() or not translation_path.is_dir():
        raise ValueError("Source and translation roots must be directories.")
    if not _roots_are_disjoint(source_path, translation_path):
        raise ValueError("Source and translation roots must be disjoint.")
    return source_path, translation_path


def _prepare_translation_run_directory(
    workspace_dir: str,
    run_id: str | None,
    plan: dict,
) -> tuple[str, Path, Path, bool]:
    if run_id is None:
        run_id = uuid.uuid4().hex
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Run ID must be 32 lowercase hexadecimal characters.")

    workspace_path = Path(workspace_dir).resolve(strict=True)
    workflow_path = workspace_path / "Workflow"
    runs_path = workflow_path / "Runs"
    run_path = runs_path / run_id
    for directory in (workflow_path, runs_path, run_path):
        if directory.is_symlink():
            raise ValueError("Translation run directories cannot be symbolic links.")
        directory.mkdir(exist_ok=True)
        if not directory.is_dir():
            raise ValueError("Translation run path is not a directory.")
    try:
        run_path.resolve(strict=True).relative_to(workspace_path)
    except ValueError as exc:
        raise ValueError("Translation run path must remain inside its project.") from exc

    manifest_path = run_path / "run.json"
    if manifest_path.exists():
        _, existing_run, _ = _load_run(run_path)
        if existing_run["plan_sha256"] != plan["plan_sha256"]:
            raise ValueError("Run ID is already bound to a different translation plan.")
        draft_path = run_path / existing_run["draft_root"]
        if draft_path.is_symlink() or not draft_path.is_dir():
            raise ValueError("Existing translation run has an invalid draft directory.")
        _mark_translation_run_review_pending(
            run_path,
            run_id=run_id,
            plan=plan,
        )
        return run_id, run_path, draft_path, True

    state_path = run_path / "run_state.json"
    expected_state = {
        "schema_version": 1,
        "status": "running",
        "run_id": run_id,
        "work_id": plan["work_id"],
        "plan_sha256": plan["plan_sha256"],
    }
    if state_path.exists():
        state = _load_json_regular(str(state_path), "translation run state")
        if state != expected_state:
            raise ValueError("Run ID is already bound to another task.")
    elif any(run_path.iterdir()):
        raise ValueError("Run directory contains files without a valid run state.")
    else:
        write_new_json(state_path, expected_state)

    draft_path = run_path / "Drafts"
    if draft_path.is_symlink():
        raise ValueError("Translation draft directory cannot be a symbolic link.")
    draft_path.mkdir(exist_ok=True)
    return run_id, run_path, draft_path, False


def _mark_translation_run_review_pending(
    run_path: Path,
    *,
    run_id: str,
    plan: dict,
) -> None:
    """Advance a successfully materialized run from execution to review."""

    state_path = run_path / "run_state.json"
    if state_path.is_symlink():
        raise ValueError("Translation run state cannot be a symbolic link.")
    with open_regular_file(state_path, binary=True) as stream:
        state_bytes = stream.read(64 * 1024 + 1)
    try:
        state = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Translation run state is invalid.") from exc
    expected_common = {
        "schema_version": 1,
        "run_id": run_id,
        "work_id": plan["work_id"],
        "plan_sha256": plan["plan_sha256"],
    }
    if (
        not isinstance(state, dict)
        or set(state) != set(expected_common) | {"status"}
        or any(state.get(key) != value for key, value in expected_common.items())
        or state.get("status") not in {"running", "review_pending", "published"}
    ):
        raise ValueError("Translation run state changed before completion.")
    if state["status"] != "running":
        return
    completed_state = dict(expected_common)
    completed_state["status"] = "review_pending"
    write_text_atomically(
        str(state_path),
        json.dumps(completed_state, ensure_ascii=False, indent=2) + "\n",
    )


def _validate_plan_output_location(source_root: str, plan_output: str) -> None:
    archive_root = Path(source_root).resolve(strict=True)
    output_path = Path(plan_output).resolve(strict=False)
    try:
        output_path.relative_to(archive_root)
    except ValueError:
        return
    raise ValueError(
        "Translation plan reports must be stored outside SourceArchive; "
        "use the project's Workflow/Plans directory."
    )


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
                "tm_key": f"source-edition:{work_id}:{metadata.episode_id}",
            }
        )
    return targets


def _select_source_edition(
    source_root: Path,
    source_edition: str,
    ai_edition_root: str | None,
) -> str | None:
    if source_edition not in {"ai", "normalized_source"}:
        raise ValueError("Source edition must be 'ai' or 'normalized_source'.")
    if source_edition == "normalized_source":
        if ai_edition_root is not None:
            raise ValueError(
                "--ai-edition-root cannot be combined with "
                "--source-edition normalized_source."
            )
        return None
    if ai_edition_root is not None:
        if not ai_edition_root.strip():
            raise ValueError("AI edition root must not be empty.")
        return ai_edition_root
    return str(source_root.parent / "RAWs_AI")


def preview_translation_plan(
    *,
    source_root: str,
    catalog: str,
    translation_root: str,
    manifest: str = "source_manifest.json",
    source_edition: str = "ai",
    ai_edition_root: str | None = None,
    edition_manifest: str = "source_editions_manifest.json",
) -> dict:
    """Build a read-only, source-verified chapter map without network or providers."""
    source_path, translation_path = _resolve_roots(
        source_root, translation_root
    )
    selected_ai_edition_root = _select_source_edition(
        source_path,
        source_edition,
        ai_edition_root,
    )
    work_id, episodes, catalog_path = _load_catalog(
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

    ai_edition = None
    ai_edition_issue = None
    if selected_ai_edition_root is not None:
        try:
            ai_path = Path(selected_ai_edition_root).resolve(strict=True)
            if not ai_path.is_dir():
                raise ValueError("AI edition root must be a directory.")
            if not _roots_are_disjoint(source_path, ai_path) or not (
                _roots_are_disjoint(translation_path, ai_path)
            ):
                raise ValueError(
                    "Source, translation, and AI edition roots must be disjoint."
                )
            ai_edition = verify_ai_edition_index(
                source_root=str(source_path),
                ai_root=str(ai_path),
                source_manifest_relative_path=manifest,
                edition_manifest_relative_path=edition_manifest,
            )
            index = ai_edition["index"]
            index_catalog = index.get("catalog")
            with open_regular_file(catalog_path, binary=True) as stream:
                catalog_sha256 = hashlib.sha256(stream.read()).hexdigest()
            indexed_episodes = ai_edition["episodes_by_id"]
            expected_ids = {target["episode_id"] for target in targets}
            if (
                not isinstance(index_catalog, dict)
                or index_catalog.get("sha256") != catalog_sha256
                or set(indexed_episodes) != expected_ids
            ):
                ai_edition_issue = "stale_ai_edition_catalog"
            else:
                for episode in episodes:
                    indexed = indexed_episodes[episode.metadata.episode_id]
                    if (
                        indexed.get("title") != episode.metadata.title
                        or indexed.get("position") != episode.metadata.position
                    ):
                        ai_edition_issue = "stale_ai_edition_catalog"
                        break
        except StaleAIEditionCatalogError:
            ai_edition_issue = "stale_ai_edition_catalog"
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            ai_edition_issue = "invalid_ai_edition"

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
            "source_input_file": None,
            "source_sha256": None,
            "translation_file": target["translation_file"],
            "translation_target_exists": target_path.exists(),
            "tm_key": target["tm_key"],
        }

        def add_issue(code: str) -> None:
            issues.append({"episode_id": episode_id, "code": code})

        if planned["translation_target_exists"]:
            add_issue("translation_target_exists")
        if ai_edition_issue is not None:
            add_issue(ai_edition_issue)
            planned_episodes.append(planned)
            continue

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
        if ai_edition is None:
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
        if raw_artifact["version_id"] not in normalized["parent_version_ids"]:
            add_issue("stale_normalized_source")
            planned_episodes.append(planned)
            continue
        try:
            if ai_edition is None:
                verify_manifest_artifact(
                    source_path, source_manifest, normalized["version_id"]
                )
            else:
                verify_current_normalized_source_metadata(
                    source_manifest, normalized["version_id"]
                )
        except (OSError, UnicodeError, ValueError):
            add_issue("invalid_normalized_source")
            planned_episodes.append(planned)
            continue
        if ai_edition is None:
            planned["source_file"] = normalized["relative_path"]
            planned["source_version_id"] = normalized["version_id"]
            planned["source_sha256"] = normalized["content_sha256"]
        else:
            ai_episode = ai_edition["episodes_by_id"].get(episode_id)
            if ai_episode is None:
                add_issue("missing_ai_edition_episode")
            else:
                planned["source_file"] = ai_episode[
                    "ai_archive_relative_path"
                ]
                planned["source_version_id"] = ai_episode[
                    "ai_edition_version_id"
                ]
                planned["source_input_file"] = ai_episode["ai_relative_path"]
                planned["source_sha256"] = ai_episode["output_sha256"]
                planned["source_profile"] = index["cleaning_profile"]["id"]
                planned["source_input_version_id"] = ai_episode[
                    "raw_source_version_id"
                ]
        planned_episodes.append(planned)

    source_edition_record = None
    if ai_edition is not None and ai_edition_issue is None:
        index = ai_edition["index"]
        source_edition_record = {
            "profile_id": index["cleaning_profile"]["id"],
            "index_root": str(
                Path(selected_ai_edition_root).resolve(strict=True)
            ),
            "index_relative_path": "catalog.json",
            "index_sha256": ai_edition["index_sha256"],
            "manifest": edition_manifest.replace("\\", "/"),
            "manifest_sha256": index["edition_manifest"]["sha256"],
        }
    plan = {
        "schema_version": 2,
        "status": "ready_for_review" if not issues else "blocked",
        "work_id": work_id,
        "source_root": str(source_path),
        "catalog": catalog.replace("\\", "/"),
        "manifest": manifest.replace("\\", "/"),
        "source_edition": source_edition_record,
        "translation_root": str(translation_path),
        "episode_count": len(planned_episodes),
        "verified_source_count": sum(
            episode["source_version_id"] is not None
            for episode in planned_episodes
        ),
        "network_requests": 0,
        "provider_calls": 0,
        "filesystem_writes": 0,
        "source_text_included": False,
        "episodes": planned_episodes,
        "issues": issues,
    }
    plan["plan_sha256"] = translation_plan_sha256(plan)
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
    ai_edition_root: str | None = None,
) -> bool:
    try:
        if source_artifact.get("source_input_file") is not None:
            if not ai_edition_root:
                return False
            raw_text = read_verified_ai_edition_bytes(
                ai_edition_root,
                source_artifact["source_input_file"],
                source_artifact["source_sha256"],
            ).decode("utf-8")
        else:
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


def _refresh_downstream_freshness_snapshot(
    *,
    source_root: Path,
    translation_root: Path,
    manifest_relative_path: str,
    workspace_dir: str,
    plan: dict,
) -> dict:
    tm_path = Path(Config.TM_PATH)
    knowledge_path = (
        Path(workspace_dir) / "Knowledge" / "KNOWLEDGE_PROVENANCE_draft.json"
    )
    summary_value = getattr(Config, "STORY_SUMMARY_PATH", None)
    summary_path = (
        Path(summary_value)
        if isinstance(summary_value, str)
        and summary_value
        and Path(summary_value).suffix.casefold() == ".json"
        else None
    )
    configured_paths = (tm_path, knowledge_path, summary_path)
    present_paths = [
        path
        for path in configured_paths
        if path is not None and (path.exists() or path.is_symlink())
    ]
    if not present_paths:
        return {"status": "not_needed"}

    try:
        tm_data = (
            _load_json_regular(str(tm_path), "translation memory")
            if tm_path.exists() or tm_path.is_symlink()
            else None
        )
        knowledge = (
            _load_json_regular(
                str(knowledge_path),
                "knowledge provenance",
            )
            if knowledge_path.exists() or knowledge_path.is_symlink()
            else None
        )
        summary_file = (
            str(summary_path)
            if summary_path is not None
            and (summary_path.exists() or summary_path.is_symlink())
            else None
        )
        expected_sources = [
            {
                "filename": episode.get("source_file"),
                "source_version_id": episode.get("source_version_id"),
                "source_input_file": episode.get("source_input_file"),
                "source_sha256": episode.get("source_sha256"),
            }
            for episode in plan.get("episodes", [])
        ]
        source_input_map = {
            item["filename"]: {
                "source_version_id": item["source_version_id"],
                "source_input_file": item["source_input_file"],
                "source_sha256": item["source_sha256"],
            }
            for item in expected_sources
            if isinstance(item.get("filename"), str)
            and isinstance(item.get("source_input_file"), str)
        }
        source_input_root = (
            plan.get("source_edition", {}).get("index_root")
            if source_input_map and isinstance(plan.get("source_edition"), dict)
            else None
        )
        snapshot = build_downstream_freshness_snapshot(
            tm_data=tm_data,
            source_root=str(source_root),
            translation_root=str(translation_root),
            manifest_relative_path=manifest_relative_path,
            tm_label=tm_path.name,
            knowledge_provenance=knowledge,
            knowledge_label=knowledge_path.name if knowledge is not None else None,
            story_summary_path=summary_file,
            expected_sources=expected_sources if summary_file else None,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )
        persisted = persist_downstream_freshness_snapshot(
            snapshot,
            str(source_root),
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        return {
            "status": "unavailable",
            "error_type": type(exc).__name__,
        }

    return {
        "status": "created" if persisted["created"] else "reused",
        "snapshot_id": persisted["snapshot_id"],
        "path": persisted["path"],
        "consumer_statuses": {
            name: result["summary"]
            for name, result in snapshot["consumers"].items()
        },
    }


@_preserve_workflow_config
def run_workflow(
    *,
    source_root: str,
    catalog: str | None = None,
    work_url: str | None = None,
    translation_root: str,
    config_file: str,
    approval_receipt: str | None = None,
    discovered_catalog: str = "source_catalog.discovered.json",
    manifest: str = "source_manifest.json",
    source_edition: str = "ai",
    ai_edition_root: str | None = None,
    edition_manifest: str = "source_editions_manifest.json",
    checkpoint: str | None = None,
    max_archive_bytes: int | None = None,
    max_episodes: int = DEFAULT_MAX_EPISODES,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    run_id: str | None = None,
    config_loader=None,
    discovery_factory=None,
    adapter_factory=None,
) -> dict:
    if (catalog is None) == (work_url is None):
        raise ValueError("Specify exactly one of catalog or work_url.")
    source_path, translation_path = _resolve_roots(
        source_root, translation_root
    )
    selected_ai_edition_root = _select_source_edition(
        source_path,
        source_edition,
        ai_edition_root,
    )
    discovered_catalog_path = resolve_relative_path(
        str(source_path),
        discovered_catalog,
        allow_missing=True,
    )
    config_path = Path(config_file).resolve(strict=True)
    if not config_path.is_file():
        raise ValueError("Configuration path must be a regular file.")

    loader = config_loader or Config.load_config
    loader(config_file=str(config_path))
    _validate_project_config()
    Config.RAW_DIR = str(source_path)
    Config.AI_EDITION_ROOT = selected_ai_edition_root
    Config.OUTPUT_DIR = str(translation_path)
    Config.CHAPTER_MAP = None
    Config.SOURCE_MANIFEST_PATH = (
        edition_manifest if selected_ai_edition_root is not None else manifest
    )
    workspace_dir = getattr(Config, "WORKSPACE_DIR", None)
    if not isinstance(workspace_dir, str) or not workspace_dir:
        workspace_dir = str(source_path.parent)
    human_edition_root = _resolve_project_human_edition_root(workspace_dir)
    ai_edition_root = selected_ai_edition_root or str(
        source_path.parent / "RAWs_AI"
    )
    _validate_workflow_root_boundaries(
        source_path,
        translation_path,
        human_edition_root,
        ai_edition_root,
    )
    validate_provider_configuration()

    if checkpoint is None:
        checkpoint = (
            "source_checkpoint.discovered.json"
            if work_url
            else "source_checkpoint.json"
        )

    discovery = None
    catalog_work_metadata = None
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
        catalog_snapshot = _load_catalog_snapshot(str(source_path), catalog)
        work_id = catalog_snapshot["work_id"]
        episodes = catalog_snapshot["episodes"]
        catalog_path = catalog_snapshot["path"]
        catalog_work_metadata = catalog_snapshot["work_metadata"]
    uses_discovered_catalog = catalog_path == discovered_catalog_path
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
            chapters=discovery.chapters,
            work_metadata=discovery.work_metadata,
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
        work_metadata=(
            discovery.work_metadata.to_catalog_record()
            if discovery is not None
            else catalog_work_metadata
        ),
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
                if uses_discovered_catalog
                else None
            ),
        }

    for target in targets:
        materialize_episode_markdown(
            str(source_path),
            work_id=work_id,
            episode_id=target["episode_id"],
            manifest_relative_path=manifest,
        )
    plan_catalog = (
        catalog.replace("\\", "/")
        if catalog is not None
        else str(catalog_path.relative_to(source_path)).replace("\\", "/")
    )
    if selected_ai_edition_root is not None:
        edition_report = prepare_source_editions(
            source_root=str(source_path),
            catalog_relative_path=plan_catalog,
            manifest_relative_path=manifest,
            human_root=human_edition_root,
            ai_root=ai_edition_root,
            edition_manifest_relative_path=edition_manifest,
            refresh_indexes=True,
        )
    else:
        edition_report = {
            "status": "not_needed",
            "reason": "normalized_source_selected",
        }
    book_bundle_report = None
    verified_book_bundle = None
    if selected_ai_edition_root is not None:
        book_bundle_report = export_book_bundles(
            source_root=str(source_path),
            catalog_relative_path=plan_catalog,
            human_root=human_edition_root,
            ai_root=ai_edition_root,
            checkpoint_relative_path=checkpoint,
            manifest_relative_path=manifest,
            edition_manifest_relative_path=edition_manifest,
        )
        verified_book_bundle = load_verified_ai_book_bundle(
            source_root=str(source_path),
            catalog_relative_path=plan_catalog,
            checkpoint_relative_path=checkpoint,
            bundle_set_relative_path=book_bundle_report[
                "bundle_set_relative_path"
            ],
            human_root=human_edition_root,
            ai_root=ai_edition_root,
            manifest_relative_path=manifest,
            edition_manifest_relative_path=edition_manifest,
        )
    plan = preview_translation_plan(
        source_root=str(source_path),
        catalog=plan_catalog,
        translation_root=str(translation_path),
        manifest=manifest,
        source_edition=source_edition,
        ai_edition_root=selected_ai_edition_root,
        edition_manifest=edition_manifest,
    )
    active_manifest = (
        edition_manifest if selected_ai_edition_root is not None else manifest
    )
    pre_translation_freshness = _refresh_downstream_freshness_snapshot(
        source_root=source_path,
        translation_root=translation_path,
        manifest_relative_path=active_manifest,
        workspace_dir=workspace_dir,
        plan=plan,
    )
    if approval_receipt is None:
        status = (
            "approval_required"
            if plan["status"] == "ready_for_review"
            else "translation_plan_blocked"
        )
        return {
            "status": status,
            "work_id": work_id,
            "discovered_catalog": (
                str(catalog_path.relative_to(source_path))
                if uses_discovered_catalog
                else None
            ),
            "source_editions": edition_report,
            "pre_translation_freshness": pre_translation_freshness,
            "plan": plan,
        }
    issues = plan.get("issues")
    target_issue_ids = {
        issue.get("episode_id")
        for issue in issues
        if isinstance(issue, dict)
        and issue.get("code") == "translation_target_exists"
    } if isinstance(issues, list) else set()
    existing_target_ids = {
        episode.get("episode_id")
        for episode in plan.get("episodes", [])
        if isinstance(episode, dict)
        and episode.get("translation_target_exists")
    }
    resumable_plan = (
        plan.get("status") == "blocked"
        and isinstance(issues, list)
        and bool(issues)
        and target_issue_ids == existing_target_ids
        and any(
            isinstance(episode, dict)
            and not episode.get("translation_target_exists")
            for episode in plan.get("episodes", [])
        )
        and all(
            isinstance(issue, dict)
            and issue.get("code") == "translation_target_exists"
            for issue in issues
        )
    )
    if plan.get("status") != "ready_for_review" and not resumable_plan:
        return {
            "status": "translation_plan_blocked",
            "work_id": work_id,
            "translation_plan_sha256": plan["plan_sha256"],
            "pre_translation_freshness": pre_translation_freshness,
            "plan": plan,
        }
    approval = verify_approval_receipt(approval_receipt, plan)
    if selected_ai_edition_root is None:
        return {
            "status": "reviewed_publication_requires_ai_edition",
            "reason": (
                "The reviewed publication workflow requires a verified AI "
                "edition and full-book bundle."
            ),
            "work_id": work_id,
            "translation_plan_sha256": plan["plan_sha256"],
            "pre_translation_freshness": pre_translation_freshness,
        }
    expected_book_bundle = {
        field: verified_book_bundle[field]
        for field in (
            "source_snapshot_id",
            "ai_bundle_id",
            "bundle_set_relative_path",
            "bundle_set_sha256",
            "ai_bundle_relative_path",
            "ai_bundle_sha256",
            "episode_count",
        )
    }
    chapter_map = [
        {
            "raw_file": episode["source_file"],
            "source_input_file": episode["source_input_file"],
            "source_sha256": episode["source_sha256"],
            "translation_file": episode["translation_file"],
            "tm_key": episode["tm_key"],
            "source_version_id": episode["source_version_id"],
            "chapter_position": episode["position"],
        }
        for episode in plan["episodes"]
    ]
    Config.CHAPTER_MAP = chapter_map

    summary_path = getattr(Config, "STORY_SUMMARY_PATH", None)
    try:
        if not isinstance(summary_path, str) or not summary_path:
            raise ValueError("A reviewed full-book summary is required.")
        load_reviewed_story_summary(
            summary_path,
            str(source_path),
            Config.SOURCE_MANIFEST_PATH,
            require_full_book_coverage=True,
            expected_sources=[
                {
                    "filename": chapter["raw_file"],
                    "source_version_id": chapter["source_version_id"],
                    "source_input_file": chapter["source_input_file"],
                    "source_sha256": chapter["source_sha256"],
                }
                for chapter in chapter_map
            ],
            source_input_root=selected_ai_edition_root,
            source_input_map={
                chapter["raw_file"]: {
                    "source_version_id": chapter["source_version_id"],
                    "source_input_file": chapter["source_input_file"],
                    "source_sha256": chapter["source_sha256"],
                }
                for chapter in chapter_map
                if isinstance(chapter.get("source_input_file"), str)
            },
            require_book_bundle=True,
            expected_book_bundle=expected_book_bundle,
        )
    except (OSError, ValueError):
        return {
            "status": "full_book_knowledge_required",
            "reason": "missing_or_invalid_reviewed_summary",
            "work_id": work_id,
            "translation_plan_sha256": plan["plan_sha256"],
            "book_bundles": book_bundle_report,
            "pre_translation_freshness": pre_translation_freshness,
        }

    resolved_run_id, run_path, draft_path, run_already_completed = (
        _prepare_translation_run_directory(
            workspace_dir,
            run_id,
            plan,
        )
    )
    if run_already_completed:
        return {
            "status": "review_pending",
            "work_id": work_id,
            "run_id": resolved_run_id,
            "run_manifest": str(run_path / "run.json"),
            "draft_root": str(draft_path),
            "translation_plan_sha256": plan["plan_sha256"],
            "book_bundles": book_bundle_report,
        }
    _validate_workflow_root_boundaries(
        source_path,
        translation_path,
        human_edition_root,
        ai_edition_root,
    )
    if not _roots_are_disjoint(source_path.resolve(), draft_path.resolve()):
        raise ValueError("Translation drafts must be outside SourceArchive.")
    for protected_root in (human_edition_root, ai_edition_root, translation_path):
        if not _roots_are_disjoint(
            Path(protected_root).resolve(strict=False),
            draft_path.resolve(strict=True),
        ):
            raise ValueError(
                "Translation drafts must be disjoint from source editions and publication."
            )
    Config.OUTPUT_DIR = str(draft_path)
    Config.TRANSLATION_OUTPUT_MODE = "reviewed_run_draft"
    Config.REQUIRE_REVIEWED_PUBLICATION = True
    Config.TRANSLATION_RUN_ID = resolved_run_id
    Config.EXPECTED_BOOK_BUNDLE = expected_book_bundle
    previous_chapter_knowledge_requirement = (
        Config.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE
    )
    Config.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE = True
    try:
        pipeline = TranslationPipeline(
            reviewed_tm_translation_root=str(translation_path)
        )
        tm_data = pipeline.rag.tm_data
        tm_chapters = tm_data.get("chapters", {})
        completed_publication_ids = set()
        for target, chapter in zip(targets, chapter_map):
            publication_path = resolve_relative_path(
                str(translation_path),
                target["translation_file"],
                allow_missing=True,
            )
            if plan.get("status") == "blocked" and publication_path.exists():
                if not _is_committed_translation(
                    str(source_path),
                    str(translation_path),
                    target,
                    chapter,
                    tm_data,
                    ai_edition_root=selected_ai_edition_root,
                ):
                    return {
                        "status": "translation_plan_blocked",
                        "work_id": work_id,
                        "translation_plan_sha256": plan["plan_sha256"],
                        "pre_translation_freshness": pre_translation_freshness,
                        "plan": plan,
                    }
                completed_publication_ids.add(target["episode_id"])
                continue
            pending = has_pending_chapter_transaction(
                str(draft_path),
                target["translation_file"],
                target["tm_key"],
            )
            output_path = resolve_relative_path(
                str(draft_path),
                target["translation_file"],
                allow_missing=True,
            )
            committed = _is_committed_translation(
                str(source_path),
                str(draft_path),
                target,
                chapter,
                tm_data,
                ai_edition_root=selected_ai_edition_root,
            )
            if (
                (output_path.exists() or target["tm_key"] in tm_chapters)
                and not pending
                and not committed
            ):
                raise FileExistsError(
                    "Existing translation output or memory does not match the current source."
                )

        pending_episodes = [
            episode
            for episode in plan["episodes"]
            if episode["episode_id"] not in completed_publication_ids
        ]
        if not pending_episodes:
            raise ValueError("Translation run has no pending episodes.")
        pending_episode_ids = [
            episode["episode_id"] for episode in pending_episodes
        ]
        Config.CHAPTER_MAP = [
            chapter
            for chapter, episode in zip(chapter_map, plan["episodes"])
            if episode["episode_id"] not in completed_publication_ids
        ]
        asyncio.run(pipeline.run_all())
    finally:
        Config.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE = (
            previous_chapter_knowledge_requirement
        )
    run_manifest = build_translation_run_manifest(
        run_id=resolved_run_id,
        plan=plan,
        source_root=str(source_path),
        source_manifest=manifest,
        edition_manifest=edition_manifest,
        catalog=plan_catalog,
        ai_root=ai_edition_root,
        draft_root=str(draft_path),
        translation_root=str(translation_path),
        book_bundle={
            field: expected_book_bundle[field]
            for field in (
                "source_snapshot_id",
                "ai_bundle_id",
                "bundle_set_relative_path",
                "bundle_set_sha256",
                "ai_bundle_relative_path",
                "ai_bundle_sha256",
            )
        },
        episode_ids=pending_episode_ids,
    )
    write_new_json(run_path / "run.json", run_manifest)
    _mark_translation_run_review_pending(
        run_path,
        run_id=resolved_run_id,
        plan=plan,
    )
    post_translation_freshness = _refresh_downstream_freshness_snapshot(
        source_root=source_path,
        translation_root=translation_path,
        manifest_relative_path=active_manifest,
        workspace_dir=workspace_dir,
        plan=plan,
    )
    return {
        "status": "review_pending",
        "run_id": resolved_run_id,
        "run_manifest": str(run_path / "run.json"),
        "draft_root": str(draft_path),
        "work_id": work_id,
        "translation_plan_sha256": plan["plan_sha256"],
        "approval_reviewer": approval["approved_by"],
        "approval_at_utc": approval["approved_at_utc"],
        "discovered_catalog": (
            str(catalog_path.relative_to(source_path))
            if uses_discovered_catalog
            else None
        ),
        "discovery_fingerprint": (
            discovery.source_fingerprint if discovery is not None else None
        ),
        "source_editions": edition_report,
        "book_bundles": book_bundle_report,
        "pre_translation_freshness": pre_translation_freshness,
        "post_translation_freshness": post_translation_freshness,
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
        "--source-edition",
        choices=("ai", "normalized_source"),
        default="ai",
        help=(
            "Translation input edition. Defaults to the AI-cleaned edition; "
            "normalized_source is an explicit compatibility override."
        ),
    )
    parser.add_argument(
        "--ai-edition-root",
        help=(
            "Override the default sibling RAWs_AI directory for the AI "
            "translation input edition."
        ),
    )
    parser.add_argument(
        "--edition-manifest",
        default="source_editions_manifest.json",
        help=(
            "Edition provenance manifest relative to --source-root; used "
            "by the default AI translation input edition."
        ),
    )
    parser.add_argument(
        "--config",
        help="Existing project JSON configuration; provider settings stay local.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help=(
            "Read an existing --catalog and source manifest, then print a "
            "provider-free chapter mapping preview. The AI edition is "
            "verified and selected by default."
        ),
    )
    parser.add_argument(
        "--plan-output",
        help=(
            "Write the --plan-only JSON report to a new file; existing files "
            "are never overwritten."
        ),
    )
    parser.add_argument(
        "--approval-receipt",
        help="Required local human-approval receipt for translation execution.",
    )
    parser.add_argument(
        "--run-id",
        help=(
            "Resume an interrupted translation run using its 32-character "
            "hexadecimal ID."
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
        if args.approval_receipt:
            parser.error("--approval-receipt is only used for translation.")
        if args.run_id:
            parser.error("--run-id is only used for translation execution.")
        if args.work_url:
            parser.error("--plan-only requires an existing --catalog; it does not access the network.")
        if not args.catalog:
            parser.error("--plan-only requires --catalog.")
        if args.plan_output is not None and not args.plan_output.strip():
            parser.error("--plan-output must be a non-empty path.")
        if args.plan_output:
            try:
                _validate_plan_output_location(
                    args.source_root,
                    args.plan_output,
                )
            except (OSError, ValueError) as exc:
                parser.error(str(exc))
    elif not args.config:
        parser.error("--config is required unless --plan-only is set.")
    elif not args.approval_receipt:
        parser.error("--approval-receipt is required for translation execution.")
    elif args.plan_output:
        parser.error("--plan-output can only be used with --plan-only.")
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
                source_edition=args.source_edition,
                ai_edition_root=args.ai_edition_root,
                edition_manifest=args.edition_manifest,
            )
            if args.plan_output:
                report["filesystem_writes"] = 1
                write_new_json(args.plan_output, report)
        else:
            report = run_workflow(
                source_root=args.source_root,
                catalog=args.catalog,
                work_url=args.work_url,
                translation_root=args.translation_root,
                config_file=args.config,
                approval_receipt=args.approval_receipt,
                run_id=args.run_id,
                discovered_catalog=args.discovered_catalog,
                manifest=args.manifest,
                source_edition=args.source_edition,
                ai_edition_root=args.ai_edition_root,
                edition_manifest=args.edition_manifest,
                checkpoint=args.checkpoint,
                max_archive_bytes=args.max_archive_bytes,
                max_episodes=args.max_episodes,
                request_delay_seconds=args.request_delay_seconds,
            )
    except TranslationQualityGateError as exc:
        position = exc.chapter_position
        position_context = (
            f" at chapter position {position}"
            if isinstance(position, int) and not isinstance(position, bool)
            else ""
        )
        print(
            f"ERROR: {type(exc).__name__}{position_context}: {exc}",
            file=sys.stderr,
        )
        return 1
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
    return 0 if report["status"] in {"complete", "review_pending"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
