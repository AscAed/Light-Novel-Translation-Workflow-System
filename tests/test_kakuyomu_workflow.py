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
    _roots_are_disjoint,
    _resolve_roots,
    _translation_targets,
    run_workflow,
)
from source_ingestion import EpisodeMetadata


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
                    "tm_key": "kakuyomu:987654321:123456789",
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
                    "tm_key": "kakuyomu:987654321:123456789",
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
            raw_text = "source paragraph"
            translation_text = "translated paragraph"
            raw_path.write_text(raw_text, encoding="utf-8")
            output_path.write_text(translation_text, encoding="utf-8")
            target = {
                "translation_file": output_path.name,
                "tm_key": "kakuyomu:987654321:123456789",
            }
            chapter = {
                "raw_file": "normalized/chapter.md",
                "source_version_id": "normalized-version-1",
            }
            tm_data = {
                "chapters": {
                    target["tm_key"]: [
                        {
                            "raw": raw_text,
                            "translated": translation_text,
                            "embedding": [0.1],
                        }
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
                                "pair_index": 1,
                                "raw_paragraph_indices": [1],
                                "translation_paragraph_indices": [1],
                                "trace_status": "matched",
                            }
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

    def test_workflow_retry_allows_verified_completed_episode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            translation_root = root / "translation"
            source_root.mkdir()
            translation_root.mkdir()
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
            raw_text = {
                "123456789": "first source",
                "123456790": "second source",
            }
            for episode_id, relative_path in raw_files.items():
                raw_path = source_root / relative_path
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(raw_text[episode_id], encoding="utf-8")

            first_target = {
                "translation_file": "episode-0001-123456789.md",
                "tm_key": "kakuyomu:987654321:123456789",
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
                        "raw_file": raw_files["123456789"],
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
            pipeline = Mock()
            pipeline.rag.tm_data = tm_data
            pipeline.run_all = AsyncMock()
            captured_chapter_maps = []

            def make_pipeline():
                captured_chapter_maps.append(Config.CHAPTER_MAP)
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
                ),
                patch(
                    "scripts.run_kakuyomu_workflow.validate_provider_configuration"
                ),
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
                    "scripts.run_kakuyomu_workflow.TranslationPipeline",
                    side_effect=make_pipeline,
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
                        config_loader=lambda **_: None,
                        adapter_factory=lambda *_args: object(),
                    )
                self.assertEqual(
                    completed_output.read_text(encoding="utf-8"),
                    "edited conflicting output",
                )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            [
                item["chapter_position"]
                for item in captured_chapter_maps[0]
            ],
            [1, 2],
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
