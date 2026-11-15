import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_kakuyomu_workflow import (
    main,
    preview_translation_plan,
)
from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    collect_source,
    materialize_episode_markdown,
)
from source_manifest import load_manifest


WORK_ID = "987654321"
EPISODE_ID = "123456789"
SOURCE_TEXT = "synthetic source body that must not appear in the plan"


class SyntheticAdapter:
    def __init__(self, source_text=SOURCE_TEXT):
        self.source_text = source_text.encode("utf-8")
        self.source_fingerprint = hashlib.sha256(self.source_text).hexdigest()

    def list_episodes(self, cursor):
        if cursor is not None:
            raise AssertionError("The synthetic catalog has one page.")
        return CatalogPage(
            (EpisodeMetadata(EPISODE_ID, "Synthetic Episode", 1),),
            None,
        )

    def fetch_episode(self, episode_id):
        if episode_id != EPISODE_ID:
            raise AssertionError("Unexpected synthetic episode.")
        return self.source_text


class KakuyomuTranslationPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.translation_root = self.root / "translation"
        self.source_root.mkdir()
        self.translation_root.mkdir()
        self.catalog_path = self.source_root / "catalog.json"
        self._write_catalog("Synthetic Episode")
        self._archive_and_materialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_catalog(self, title):
        self.catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "work_id": WORK_ID,
                    "episodes": [
                        {
                            "episode_id": EPISODE_ID,
                            "position": 1,
                            "title": title,
                            "page_url": (
                                "https://kakuyomu.jp/works/"
                                f"{WORK_ID}/episodes/{EPISODE_ID}"
                            ),
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _archive_and_materialize(self, source_text=SOURCE_TEXT):
        report = collect_source(
            SyntheticAdapter(source_text),
            root=self.source_root,
            work_id=WORK_ID,
        )
        self.assertEqual(report["status"], "complete")
        materialize_episode_markdown(
            self.source_root,
            work_id=WORK_ID,
            episode_id=EPISODE_ID,
        )

    def _preview(self):
        return preview_translation_plan(
            source_root=str(self.source_root),
            catalog="catalog.json",
            translation_root=str(self.translation_root),
        )

    def test_preview_is_read_only_and_does_not_include_source_text(self):
        before = {
            "source": sorted(
                str(path.relative_to(self.source_root))
                for path in self.source_root.rglob("*")
            ),
            "translation": sorted(
                str(path.relative_to(self.translation_root))
                for path in self.translation_root.rglob("*")
            ),
        }

        plan = self._preview()

        after = {
            "source": sorted(
                str(path.relative_to(self.source_root))
                for path in self.source_root.rglob("*")
            ),
            "translation": sorted(
                str(path.relative_to(self.translation_root))
                for path in self.translation_root.rglob("*")
            ),
        }
        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertEqual(before, after)
        self.assertEqual(plan["status"], "ready_for_review")
        self.assertEqual(plan["episode_count"], 1)
        self.assertEqual(plan["verified_source_count"], 1)
        self.assertEqual(plan["network_requests"], 0)
        self.assertEqual(plan["provider_calls"], 0)
        self.assertEqual(plan["filesystem_writes"], 0)
        self.assertFalse(plan["source_text_included"])
        self.assertEqual(plan["episodes"][0]["episode_id"], EPISODE_ID)
        self.assertTrue(plan["episodes"][0]["source_version_id"])
        self.assertNotIn(SOURCE_TEXT, serialized)
        self.assertRegex(plan["plan_sha256"], r"^[0-9a-f]{64}$")

    def test_cli_runs_plan_only_without_config_and_prints_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--translation-root",
                    str(self.translation_root),
                    "--plan-only",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "ready_for_review")
        self.assertEqual(report["provider_calls"], 0)
        self.assertNotIn(SOURCE_TEXT, output.getvalue())

    def test_existing_translation_target_blocks_plan_without_reading_it(self):
        sentinel = "private existing translation"
        target = self.translation_root / "episode-0001-123456789.md"
        target.write_text(sentinel, encoding="utf-8")

        plan = self._preview()

        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(plan["episodes"][0]["translation_target_exists"])
        self.assertIn(
            {"episode_id": EPISODE_ID, "code": "translation_target_exists"},
            plan["issues"],
        )
        self.assertNotIn(sentinel, json.dumps(plan, ensure_ascii=False))

    def test_changed_raw_source_blocks_stale_normalized_mapping(self):
        report = collect_source(
            SyntheticAdapter("changed synthetic source"),
            root=self.source_root,
            work_id=WORK_ID,
            checkpoint_relative_path="source_checkpoint.changed.json",
        )
        self.assertEqual(report["status"], "complete")

        plan = self._preview()

        self.assertEqual(plan["status"], "blocked")
        self.assertIn(
            {"episode_id": EPISODE_ID, "code": "stale_normalized_source"},
            plan["issues"],
        )

    def test_catalog_metadata_must_match_archived_episode(self):
        self._write_catalog("Changed title")

        plan = self._preview()

        self.assertEqual(plan["status"], "blocked")
        self.assertIn(
            {"episode_id": EPISODE_ID, "code": "catalog_metadata_mismatch"},
            plan["issues"],
        )

    def test_missing_normalized_source_blocks_plan(self):
        manifest = load_manifest(self.source_root / "source_manifest.json")
        normalized = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "normalized_source"
        )
        (self.source_root / normalized["relative_path"]).unlink()

        plan = self._preview()

        self.assertEqual(plan["status"], "blocked")
        self.assertIn(
            {"episode_id": EPISODE_ID, "code": "invalid_normalized_source"},
            plan["issues"],
        )

    def test_missing_normalized_artifact_blocks_plan(self):
        normalized_file = next(self.source_root.rglob("*.md"))
        normalized_file.unlink()
        manifest_path = self.source_root / "source_manifest.json"
        manifest = load_manifest(manifest_path)
        manifest["artifacts"] = [
            item
            for item in manifest["artifacts"]
            if item["kind"] != "normalized_source"
        ]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )

        plan = self._preview()

        self.assertEqual(plan["status"], "blocked")
        self.assertIn(
            {"episode_id": EPISODE_ID, "code": "missing_normalized_source"},
            plan["issues"],
        )


if __name__ == "__main__":
    unittest.main()
