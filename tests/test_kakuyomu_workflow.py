import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kakuyomu_page_source import KakuyomuEpisodePage
from pipeline import Config
from scripts.run_kakuyomu_workflow import (
    _check_translation_targets,
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

    def test_existing_translation_target_is_not_overwritten(self):
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

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                _check_translation_targets(root, targets)

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
