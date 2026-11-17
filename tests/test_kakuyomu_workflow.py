import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from kakuyomu_page_source import KakuyomuEpisodePage
from pipeline import Config
from scripts.run_kakuyomu_workflow import (
    _check_translation_targets,
    _is_committed_translation,
    _refresh_downstream_freshness_snapshot,
    _roots_are_disjoint,
    _resolve_roots,
    _translation_targets,
    run_workflow,
)
from source_ingestion import EpisodeMetadata
from translation_plan_approval import translation_plan_sha256


class KakuyomuWorkflowTests(unittest.TestCase):
    def test_targets_use_explicit_episode_identity(self):
        episodes = (
            KakuyomuEpisodePage(
                EpisodeMetadata("123456789", "第1話", 1),
                "https://kakuyomu.jp/works/987654321/episodes/123456789",
            ),
        )

        self.assertEqual(
            _translation_targets("987654321", episodes),
            [
                {
                    "episode_id": "123456789",
                    "position": 1,
                    "translation_file": "episode-0001-123456789.md",
                    "tm_key": "source-edition:987654321:123456789",
                }
            ],
        )

    def test_source_and_translation_roots_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            nested_output = source_root / "translations"
            source_root.mkdir()
            nested_output.mkdir()

            with self.assertRaisesRegex(ValueError, "disjoint"):
                _resolve_roots(str(source_root), str(nested_output))

    def test_archive_overlapping_edition_roots_fail_before_discovery(self):
        for invalid_root in ("ai", "human"):
            with self.subTest(invalid_root=invalid_root):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source_root = root / "SourceArchive"
                    translation_root = root / "translation"
                    source_root.mkdir()
                    translation_root.mkdir()
                    config_path = root / "config.json"
                    config_path.write_text("{}", encoding="utf-8")

                    ai_edition_root = root / "RAWs_AI"
                    if invalid_root == "ai":
                        ai_edition_root = source_root / "RAWs_AI"
                    else:
                        (root / "workflow_paths.json").write_text(
                            json.dumps(
                                {
                                    "schema_version": 1,
                                    "output_dir": "translation",
                                    "human_edition_root": (
                                        "SourceArchive/human-edition"
                                    ),
                                }
                            ),
                            encoding="utf-8",
                        )

                    discovery = Mock()
                    with (
                        patch.multiple(
                            Config,
                            WORKSPACE_DIR=str(root),
                            INFO_PATH=str(config_path),
                            TM_PATH=str(root / "translation_memory.json"),
                        ),
                        patch(
                            "scripts.run_kakuyomu_workflow.validate_provider_configuration"
                        ),
                        self.assertRaisesRegex(
                            ValueError, "must be pairwise disjoint"
                        ),
                    ):
                        run_workflow(
                            source_root=str(source_root),
                            work_url=(
                                "https://kakuyomu.jp/works/987654321"
                            ),
                            translation_root=str(translation_root),
                            config_file=str(config_path),
                            config_loader=lambda **_: None,
                            discovery_factory=discovery,
                            ai_edition_root=str(ai_edition_root),
                        )

                    discovery.assert_not_called()

    def test_freshness_snapshot_uses_configured_downstream_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "SourceArchive"
            translation_root = root / "translation"
            knowledge_root = root / "Knowledge"
            source_root.mkdir()
            translation_root.mkdir()
            knowledge_root.mkdir()
            tm_path = root / "translation_memory.json"
            tm_path.write_text('{"chapters":{}}', encoding="utf-8")
            knowledge_path = knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json"
            knowledge_path.write_text('{"source_files":[]}', encoding="utf-8")
            summary_path = knowledge_root / "STORY_SUMMARY_reviewed.json"
            summary_path.write_text('{"summary":"approved"}', encoding="utf-8")
            snapshot = {
                "consumers": {
                    "translation_memory": {"summary": {"verified": 1}},
                    "knowledge_provenance": {"summary": {"verified": 1}},
                    "reviewed_story_summary": {"summary": {"verified": 1}},
                }
            }
            persisted = {
                "snapshot_id": "f" * 64,
                "path": f"downstream_freshness_{'f' * 64}.json",
                "created": True,
            }
            plan = {
                "episodes": [
                    {
                        "source_file": "editions/ai-efficient-v1/episode.md",
                        "source_version_id": "ai-edition-v1",
                    }
                ]
            }

            with (
                patch.multiple(
                    Config,
                    WORKSPACE_DIR=str(root),
                    TM_PATH=str(tm_path),
                    STORY_SUMMARY_PATH=str(summary_path),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.build_downstream_freshness_snapshot",
                    return_value=snapshot,
                ) as build_snapshot,
                patch(
                    "scripts.run_kakuyomu_workflow.persist_downstream_freshness_snapshot",
                    return_value=persisted,
                ) as persist_snapshot,
            ):
                result = _refresh_downstream_freshness_snapshot(
                    source_root=source_root,
                    translation_root=translation_root,
                    manifest_relative_path="source_editions_manifest.json",
                    workspace_dir=str(root),
                    plan=plan,
                )

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["path"], persisted["path"])
        self.assertEqual(result["snapshot_id"], persisted["snapshot_id"])
        build_kwargs = build_snapshot.call_args.kwargs
        self.assertEqual(
            build_kwargs["manifest_relative_path"],
            "source_editions_manifest.json",
        )
        self.assertEqual(
            build_kwargs["expected_sources"],
            [
                {
                    "filename": "editions/ai-efficient-v1/episode.md",
                    "source_version_id": "ai-edition-v1",
                    "source_input_file": None,
                    "source_sha256": None,
                }
            ],
        )
        self.assertEqual(
            build_kwargs["knowledge_label"],
            "KNOWLEDGE_PROVENANCE_draft.json",
        )
        self.assertEqual(
            build_kwargs["story_summary_path"],
            str(summary_path),
        )
        persist_snapshot.assert_called_once_with(snapshot, str(source_root))

    @unittest.skipUnless(os.name == "nt", "Different-drive roots are Windows-specific.")
    def test_disjoint_roots_on_different_windows_drives_are_accepted(self):
        self.assertTrue(
            _roots_are_disjoint(
                Path("D:/sources"),
                Path("C:/translations"),
            )
        )

    def test_existing_translation_target_is_deferred_for_commit_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "episode-0001-123456789.md").write_text(
                "existing output", encoding="utf-8"
            )
            targets = [
                {
                    "translation_file": "episode-0001-123456789.md",
                    "tm_key": "source-edition:987654321:123456789",
                }
            ]

            _check_translation_targets(root, targets)

    def test_committed_translation_requires_matching_source_output_and_tm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            translation_root = root / "translation"
            raw_path = source_root / "normalized" / "chapter.md"
            output_path = translation_root / "episode-0001-123456789.md"
            raw_path.parent.mkdir(parents=True)
            translation_root.mkdir()
            raw_text = "source paragraph\n\nsecond source paragraph"
            translation_text = (
                "translated paragraph\n\nsecond translated paragraph"
            )
            raw_path.write_text(raw_text, encoding="utf-8")
            output_path.write_text(translation_text, encoding="utf-8")
            target = {
                "translation_file": output_path.name,
                "tm_key": "source-edition:987654321:123456789",
            }
            chapter = {
                "raw_file": "normalized/chapter.md",
                "source_version_id": "normalized-version-1",
            }
            tm_data = {
                "chapters": {
                    target["tm_key"]: [
                        {
                            "raw": "source paragraph",
                            "translated": "translated paragraph",
                            "embedding": [0.1],
                        },
                        {
                            "raw": "second source paragraph",
                            "translated": "second translated paragraph",
                            "embedding": [0.1],
                        },
                    ]
                },
                "source_provenance": {
                    target["tm_key"]: {
                        "schema_version": 1,
                        "producer": "pipeline",
                        "raw_file": chapter["raw_file"],
                        "raw_sha256": hashlib.sha256(
                            raw_text.encode("utf-8")
                        ).hexdigest(),
                        "translation_file": target["translation_file"],
                        "translation_sha256": hashlib.sha256(
                            translation_text.encode("utf-8")
                        ).hexdigest(),
                        "source_version_id": chapter["source_version_id"],
                        "pair_mappings": [
                            {
                                "pair_index": index,
                                "raw_paragraph_indices": [index],
                                "translation_paragraph_indices": [index],
                                "trace_status": "matched",
                            }
                            for index in (1, 2)
                        ],
                    }
                },
            }

            self.assertTrue(
                _is_committed_translation(
                    str(source_root),
                    str(translation_root),
                    target,
                    chapter,
                    tm_data,
                )
            )
            original_output_bytes = output_path.read_bytes()
            alternate_newline = b"\n" if os.linesep == "\r\n" else b"\r\n"
            output_path.write_bytes(
                original_output_bytes.replace(
                    os.linesep.encode("ascii"), alternate_newline
                )
            )
            self.assertFalse(
                _is_committed_translation(
                    str(source_root),
                    str(translation_root),
                    target,
                    chapter,
                    tm_data,
                )
            )
            output_path.write_bytes(original_output_bytes)
            output_path.write_text("edited translation", encoding="utf-8")
            self.assertFalse(
                _is_committed_translation(
                    str(source_root),
                    str(translation_root),
                    target,
                    chapter,
                    tm_data,
                )
            )
            output_path.write_text(
                f"{translation_text} \n", encoding="utf-8"
            )
            provenance = tm_data["source_provenance"][target["tm_key"]]
            provenance["translation_sha256"] = hashlib.sha256(
                output_path.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
            self.assertFalse(
                _is_committed_translation(
                    str(source_root),
                    str(translation_root),
                    target,
                    chapter,
                    tm_data,
                )
            )

    def test_paused_collection_returns_collector_report_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            translation_root = root / "translation"
            source_root.mkdir()
            translation_root.mkdir()
            catalog_path = source_root / "catalog.json"
            config_path = root / "config.json"
            catalog_path.write_text("{}", encoding="utf-8")
            config_path.write_text("{}", encoding="utf-8")
            catalog = (
                KakuyomuEpisodePage(
                    EpisodeMetadata("123456789", "Episode", 1),
                    "https://kakuyomu.jp/works/987654321/episodes/123456789",
                ),
            )
            source_report = {
                "status": "paused",
                "reason": "rate_limited",
                "discovered_count": 2,
                "completed_count": 1,
                "pending_count": 1,
            }

            with (
                patch.multiple(
                    Config,
                    WORKSPACE_DIR=str(root),
                    INFO_PATH=str(config_path),
                    TM_PATH=str(root / "tm.json"),
                    RAW_DIR=str(source_root),
                    OUTPUT_DIR=str(translation_root),
                    CHAPTER_MAP=None,
                    SOURCE_MANIFEST_PATH=None,
                    STORY_SUMMARY_PATH=str(root / "STORY_SUMMARY_reviewed.json"),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.validate_provider_configuration"
                ),
                patch(
                    "scripts.run_kakuyomu_workflow._load_catalog",
                    return_value=("987654321", catalog, catalog_path),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.collect_source",
                    return_value=source_report,
                ),
            ):
                result = run_workflow(
                    source_root=str(source_root),
                    catalog="catalog.json",
                    translation_root=str(translation_root),
                    config_file=str(config_path),
                    config_loader=lambda **_: None,
                    adapter_factory=lambda *_args: object(),
                )

        self.assertEqual(result["status"], "source_incomplete")
        self.assertEqual(result["source_status"], "paused")
        self.assertEqual(result["pause_reason"], "rate_limited")
        self.assertEqual(result["discovered_count"], 2)
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["pending_count"], 1)

    def test_normalized_source_workflow_skips_ai_edition_generation_for_v1_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "SourceArchive"
            translation_root = root / "Translation"
            source_root.mkdir()
            translation_root.mkdir()
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            catalog_path = source_root / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "work_id": "987654321",
                        "episodes": [
                            {
                                "episode_id": "123456789",
                                "title": "Episode 1",
                                "position": 1,
                                "page_url": (
                                    "https://kakuyomu.jp/works/987654321/"
                                    "episodes/123456789"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.multiple(
                    Config,
                    WORKSPACE_DIR=str(root),
                    INFO_PATH=str(config_path),
                    TM_PATH=str(root / "tm.json"),
                    RAW_DIR=str(source_root),
                    OUTPUT_DIR=str(translation_root),
                    CHAPTER_MAP=None,
                    SOURCE_MANIFEST_PATH=None,
                    STORY_SUMMARY_PATH=str(root / "STORY_SUMMARY_reviewed.json"),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.validate_provider_configuration"
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.collect_source",
                    return_value={
                        "status": "complete",
                        "reason": None,
                        "discovered_count": 1,
                        "completed_count": 1,
                        "pending_count": 0,
                    },
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.materialize_episode_markdown"
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.prepare_source_editions"
                ) as prepare_editions,
                patch(
                    "scripts.run_kakuyomu_workflow.preview_translation_plan",
                    return_value={"status": "blocked"},
                ) as preview_plan,
                patch(
                    "scripts.run_kakuyomu_workflow._refresh_downstream_freshness_snapshot",
                    return_value={"status": "not_needed"},
                ),
            ):
                result = run_workflow(
                    source_root=str(source_root),
                    catalog="catalog.json",
                    translation_root=str(translation_root),
                    config_file=str(config_path),
                    source_edition="normalized_source",
                    config_loader=lambda **_: None,
                    adapter_factory=lambda *_args: object(),
                )

        self.assertEqual(result["status"], "translation_plan_blocked")
        self.assertEqual(
            result["source_editions"],
            {
                "status": "not_needed",
                "reason": "normalized_source_selected",
            },
        )
        prepare_editions.assert_not_called()
        self.assertIsNone(preview_plan.call_args.kwargs["ai_edition_root"])
        self.assertEqual(
            preview_plan.call_args.kwargs["source_edition"],
            "normalized_source",
        )

    def test_workflow_retry_allows_verified_completed_episode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            translation_root = root / "translation"
            source_root.mkdir()
            translation_root.mkdir()
            ai_edition_root = root / "RAWs_AI"
            ai_edition_root.mkdir()
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            catalog_path = source_root / "catalog.json"
            catalog_path.write_text("{}", encoding="utf-8")

            episodes = tuple(
                KakuyomuEpisodePage(
                    EpisodeMetadata(episode_id, f"Episode {position}", position),
                    (
                        "https://kakuyomu.jp/works/987654321/"
                        f"episodes/{episode_id}"
                    ),
                )
                for episode_id, position in (("123456789", 1), ("123456790", 2))
            )
            raw_files = {
                "123456789": "normalized/first.md",
                "123456790": "normalized/second.md",
            }
            ai_archive_files = {
                "123456789": "editions/ai-efficient-v1/123456789/first.md",
                "123456790": "editions/ai-efficient-v1/123456790/second.md",
            }
            ai_input_files = {
                "123456789": "episodes/0001-123456789.md",
                "123456790": "episodes/0002-123456790.md",
            }
            raw_text = {
                "123456789": "first source",
                "123456790": "second source",
            }
            for episode_id, relative_path in raw_files.items():
                raw_path = source_root / relative_path
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(raw_text[episode_id], encoding="utf-8")
                ai_path = source_root / ai_archive_files[episode_id]
                ai_path.parent.mkdir(parents=True, exist_ok=True)
                ai_path.write_text(raw_text[episode_id], encoding="utf-8")
                mirror_path = ai_edition_root / ai_input_files[episode_id]
                mirror_path.parent.mkdir(parents=True, exist_ok=True)
                mirror_path.write_text(raw_text[episode_id], encoding="utf-8")

            first_target = {
                "translation_file": "episode-0001-123456789.md",
                "tm_key": "source-edition:987654321:123456789",
            }
            translated = "first translation"
            (translation_root / first_target["translation_file"]).write_text(
                translated, encoding="utf-8"
            )
            first_version = "normalized-first-version"
            tm_data = {
                "chapters": {
                    first_target["tm_key"]: [
                        {
                            "raw": raw_text["123456789"],
                            "translated": translated,
                            "embedding": [0.1],
                        }
                    ]
                },
                "source_provenance": {
                    first_target["tm_key"]: {
                        "schema_version": 1,
                        "producer": "pipeline",
                        "raw_file": ai_archive_files["123456789"],
                        "raw_sha256": hashlib.sha256(
                            raw_text["123456789"].encode("utf-8")
                        ).hexdigest(),
                        "translation_file": first_target["translation_file"],
                        "translation_sha256": hashlib.sha256(
                            translated.encode("utf-8")
                        ).hexdigest(),
                        "source_version_id": first_version,
                        "pair_mappings": [
                            {
                                "pair_index": 1,
                                "raw_paragraph_indices": [1],
                                "translation_paragraph_indices": [1],
                                "trace_status": "matched",
                            }
                        ],
                    }
                },
            }
            plan_episodes = [
                {
                    "episode_id": episode_id,
                    "position": position,
                    "title": f"Episode {position}",
                    "source_file": ai_archive_files[episode_id],
                    "source_version_id": (
                        first_version
                        if episode_id == "123456789"
                        else "ai-version-second"
                    ),
                    "source_input_file": ai_input_files[episode_id],
                    "source_sha256": hashlib.sha256(
                        raw_text[episode_id].encode("utf-8")
                    ).hexdigest(),
                    "translation_file": (
                        f"episode-{position:04d}-{episode_id}.md"
                    ),
                    "translation_target_exists": position == 1,
                    "tm_key": f"source-edition:987654321:{episode_id}",
                }
                for position, episode_id in (
                    (1, "123456789"),
                    (2, "123456790"),
                )
            ]
            plan = {
                "schema_version": 2,
                "status": "ready_for_review",
                "work_id": "987654321",
                "source_root": str(source_root),
                "catalog": "catalog.json",
                "manifest": "source_manifest.json",
                "source_edition": {
                    "profile_id": "ai-efficient-v1",
                    "index_root": str(ai_edition_root),
                    "index_relative_path": "catalog.json",
                    "index_sha256": "a" * 64,
                    "manifest": "source_editions_manifest.json",
                    "manifest_sha256": "b" * 64,
                },
                "translation_root": str(translation_root),
                "episode_count": len(plan_episodes),
                "verified_source_count": len(plan_episodes),
                "episodes": plan_episodes,
                "issues": [],
            }
            plan["plan_sha256"] = translation_plan_sha256(plan)
            pipeline = Mock()
            pipeline.rag.tm_data = tm_data
            pipeline.run_all = AsyncMock()
            workflow_events = []
            edition_report = {
                "status": "materialized",
                "episode_count": 2,
                "created_files": 0,
                "reused_files": 1,
            }
            captured_chapter_maps = []
            captured_manifest_paths = []

            def make_pipeline():
                captured_chapter_maps.append(Config.CHAPTER_MAP)
                captured_manifest_paths.append(Config.SOURCE_MANIFEST_PATH)
                return pipeline

            with (
                patch.multiple(
                    Config,
                    WORKSPACE_DIR=str(root),
                    INFO_PATH=str(config_path),
                    TM_PATH=str(root / "tm.json"),
                    RAW_DIR=str(source_root),
                    OUTPUT_DIR=str(translation_root),
                    CHAPTER_MAP=None,
                    SOURCE_MANIFEST_PATH=None,
                    STORY_SUMMARY_PATH=str(root / "STORY_SUMMARY_reviewed.json"),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.validate_provider_configuration"
                ),
                patch(
                    "scripts.run_kakuyomu_workflow._refresh_downstream_freshness_snapshot",
                    return_value={"status": "not_needed"},
                ) as freshness_snapshot,
                patch(
                    "scripts.run_kakuyomu_workflow._load_catalog",
                    return_value=("987654321", episodes, catalog_path),
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.collect_source",
                    return_value={
                        "status": "complete",
                        "reason": None,
                        "discovered_count": 2,
                        "completed_count": 2,
                        "pending_count": 0,
                    },
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.materialize_episode_markdown",
                    side_effect=lambda _root, episode_id, **_kwargs: {
                        "relative_path": raw_files[episode_id],
                        "version_id": (
                            first_version
                            if episode_id == "123456789"
                            else "normalized-second-version"
                        ),
                    },
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.prepare_source_editions",
                    side_effect=lambda **_kwargs: (
                        workflow_events.append("editions")
                        or edition_report
                    ),
                ) as edition_export,
                patch(
                    "scripts.run_kakuyomu_workflow.TranslationPipeline",
                    side_effect=make_pipeline,
                ) as pipeline_factory,
                patch(
                    "scripts.run_kakuyomu_workflow.preview_translation_plan",
                    side_effect=lambda **_kwargs: (
                        workflow_events.append("plan")
                        or plan
                    ),
                ) as plan_preview,
                patch(
                    "scripts.run_kakuyomu_workflow.verify_approval_receipt",
                    return_value={
                        "plan_sha256": plan["plan_sha256"],
                        "approved_by": "synthetic reviewer",
                        "approved_at_utc": "2026-11-16T00:00:00Z",
                    },
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.load_reviewed_story_summary",
                    return_value="Synthetic approved whole-book context.",
                ) as load_summary,
            ):
                load_summary.side_effect = ValueError(
                    "synthetic incomplete full-book summary"
                )
                blocked = run_workflow(
                    source_root=str(source_root),
                    catalog="catalog.json",
                    translation_root=str(translation_root),
                    config_file=str(config_path),
                    approval_receipt=str(root / "approval.json"),
                    config_loader=lambda **_: None,
                    adapter_factory=lambda *_args: object(),
                )
                self.assertEqual(
                    blocked["status"], "full_book_knowledge_required"
                )
                pipeline_factory.assert_not_called()

                load_summary.side_effect = None
                result = run_workflow(
                    source_root=str(source_root),
                    catalog="catalog.json",
                    translation_root=str(translation_root),
                    config_file=str(config_path),
                    approval_receipt=str(root / "approval.json"),
                    config_loader=lambda **_: None,
                    adapter_factory=lambda *_args: object(),
                )
                completed_output = (
                    translation_root / first_target["translation_file"]
                )
                completed_output.write_text(
                    "edited conflicting output", encoding="utf-8"
                )
                with self.assertRaisesRegex(FileExistsError, "does not match"):
                    run_workflow(
                        source_root=str(source_root),
                        catalog="catalog.json",
                        translation_root=str(translation_root),
                        config_file=str(config_path),
                        approval_receipt=str(root / "approval.json"),
                        config_loader=lambda **_: None,
                        adapter_factory=lambda *_args: object(),
                    )
                self.assertEqual(
                    completed_output.read_text(encoding="utf-8"),
                    "edited conflicting output",
                )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["source_editions"], edition_report)
        self.assertEqual(
            blocked["pre_translation_freshness"],
            {"status": "not_needed"},
        )
        self.assertEqual(
            result["pre_translation_freshness"],
            {"status": "not_needed"},
        )
        self.assertEqual(
            result["post_translation_freshness"],
            {"status": "not_needed"},
        )
        self.assertEqual(freshness_snapshot.call_count, 4)
        self.assertEqual(workflow_events, ["editions", "plan"] * 3)
        self.assertEqual(
            edition_export.call_args.kwargs["catalog_relative_path"],
            "catalog.json",
        )
        self.assertEqual(
            edition_export.call_args.kwargs["human_root"],
            str((root / "生肉").resolve(strict=False)),
        )
        self.assertEqual(
            edition_export.call_args.kwargs["ai_root"],
            str((root / "RAWs_AI").resolve(strict=False)),
        )
        self.assertEqual(
            load_summary.call_args.kwargs["expected_sources"],
            [
                {
                    "filename": ai_archive_files["123456789"],
                    "source_version_id": first_version,
                    "source_input_file": ai_input_files["123456789"],
                    "source_sha256": hashlib.sha256(
                        raw_text["123456789"].encode("utf-8")
                    ).hexdigest(),
                },
                {
                    "filename": ai_archive_files["123456790"],
                    "source_version_id": "ai-version-second",
                    "source_input_file": ai_input_files["123456790"],
                    "source_sha256": hashlib.sha256(
                        raw_text["123456790"].encode("utf-8")
                    ).hexdigest(),
                },
            ],
        )
        self.assertEqual(
            [
                item["chapter_position"]
                for item in captured_chapter_maps[0]
            ],
            [1, 2],
        )
        self.assertEqual(
            captured_manifest_paths[0],
            "source_editions_manifest.json",
        )
        self.assertEqual(
            plan_preview.call_args_list[0].kwargs["ai_edition_root"],
            str(ai_edition_root),
        )
        self.assertEqual(
            plan_preview.call_args_list[0].kwargs["source_edition"],
            "ai",
        )
        self.assertEqual(
            plan_preview.call_args.kwargs["edition_manifest"],
            "source_editions_manifest.json",
        )
        self.assertEqual(
            [
                item["raw_file"]
                for item in captured_chapter_maps[0]
            ],
            list(ai_archive_files.values()),
        )
        pipeline.run_all.assert_awaited_once()

    def test_unauthorized_provider_fails_before_page_fetch_or_archive_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            translation_root = root / "translation"
            source_root.mkdir()
            translation_root.mkdir()
            catalog_path = source_root / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "work_id": "987654321",
                        "episodes": [
                            {
                                "episode_id": "123456789",
                                "position": 1,
                                "page_url": (
                                    "https://kakuyomu.jp/works/987654321/"
                                    "episodes/123456789"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            with (
                patch.dict(os.environ, {"MOCK_SERVER_PORT": ""}),
                patch.multiple(
                    Config,
                    WORKSPACE_DIR=str(root),
                    INFO_PATH=str(config_path),
                    TM_PATH=str(root / "translation_memory.json"),
                    INITIAL_MODEL="sakura",
                    PROOFREAD_MODEL="sakura",
                    STYLE_MODEL="sakura",
                    SAKURA_BASE_URL="https://provider.example/v1",
                    PROVIDER_DATA_POLICY={},
                    GEMINI_FALLBACK_ENABLED=False,
                    STRICT_REFLECTION_MODE=False,
                ),
                self.assertRaises(PermissionError),
            ):
                run_workflow(
                    source_root=str(source_root),
                    catalog="catalog.json",
                    translation_root=str(translation_root),
                    config_file=str(config_path),
                    config_loader=lambda **_: None,
                    adapter_factory=lambda *_args, **_kwargs: self.fail(
                        "Adapter must not run before provider authorization."
                    ),
                )

            self.assertFalse((source_root / "source_manifest.json").exists())
            self.assertFalse((source_root / "source_checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
