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
from pipeline import get_chapter_specs
from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    collect_source,
    materialize_episode_markdown,
)
from source_editions import prepare_source_editions
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
        self.ai_root = self.root / "RAWs_AI"
        self.human_root = self.root / "human"
        self.ai_root.mkdir()
        self.human_root.mkdir()
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
            source_edition="normalized_source",
        )

    def _prepare_ai_edition(self):
        catalog_path = self.source_root / "catalog_with_chapters.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "work_id": WORK_ID,
                    "episodes": [
                        {
                            "episode_id": EPISODE_ID,
                            "title": "Synthetic Episode",
                            "position": 1,
                            "page_url": (
                                "https://kakuyomu.jp/works/"
                                f"{WORK_ID}/episodes/{EPISODE_ID}"
                            ),
                        }
                    ],
                    "chapters": [
                        {
                            "group_id": "chapter-one",
                            "chapter_id": "chapter-one",
                            "title": "Synthetic Chapter",
                            "level": 1,
                            "position_start": 1,
                            "position_end": 1,
                            "episode_ids": [EPISODE_ID],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        prepare_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="catalog_with_chapters.json",
            manifest_relative_path="source_manifest.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )
        return catalog_path

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
                    "--source-edition",
                    "normalized_source",
                    "--plan-only",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "ready_for_review")
        self.assertEqual(report["provider_calls"], 0)
        self.assertNotIn(SOURCE_TEXT, output.getvalue())

    def test_cli_can_write_plan_to_a_new_file_without_overwriting(self):
        output = io.StringIO()
        plan_dir = self.root / "Workflow" / "Plans"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "review-plan.json"
        arguments = [
            "--source-root",
            str(self.source_root),
            "--catalog",
            "catalog.json",
            "--translation-root",
            str(self.translation_root),
            "--source-edition",
            "normalized_source",
            "--plan-only",
            "--plan-output",
            str(plan_path),
        ]

        with contextlib.redirect_stdout(output):
            result = main(arguments)

        self.assertEqual(result, 0)
        written = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(written["filesystem_writes"], 1)
        self.assertEqual(written["plan_sha256"], self._preview()["plan_sha256"])

        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = main(arguments)
        self.assertEqual(result, 1)
        self.assertIn("FileExistsError", error.getvalue())
        self.assertEqual(
            written,
            json.loads(plan_path.read_text(encoding="utf-8")),
        )

    def test_plan_output_rejects_empty_path(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "--source-root",
                        str(self.source_root),
                        "--catalog",
                        "catalog.json",
                        "--translation-root",
                        str(self.translation_root),
                        "--plan-only",
                        "--plan-output",
                        "",
                    ]
                )
        self.assertEqual(raised.exception.code, 2)

    def test_plan_output_rejects_source_archive_destination(self):
        plan_path = self.source_root / "translation_plan_review.json"
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "--source-root",
                        str(self.source_root),
                        "--catalog",
                        "catalog.json",
                        "--translation-root",
                        str(self.translation_root),
                        "--plan-only",
                        "--plan-output",
                        str(plan_path),
                    ]
                )

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(plan_path.exists())

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

    def test_default_plan_blocks_when_ai_edition_is_unavailable(self):
        plan = preview_translation_plan(
            source_root=str(self.source_root),
            catalog="catalog.json",
            translation_root=str(self.translation_root),
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertIsNone(plan["source_edition"])
        self.assertEqual(
            plan["issues"],
            [{"episode_id": EPISODE_ID, "code": "invalid_ai_edition"}],
        )
        self.assertIsNone(plan["episodes"][0]["source_version_id"])

    def test_explicit_normalized_source_override_uses_collector_output(self):
        plan = preview_translation_plan(
            source_root=str(self.source_root),
            catalog="catalog.json",
            translation_root=str(self.translation_root),
            source_edition="normalized_source",
        )
        normalized = next(
            item
            for item in load_manifest(
                self.source_root / "source_manifest.json"
            )["artifacts"]
            if item["kind"] == "normalized_source"
        )

        self.assertEqual(plan["status"], "ready_for_review")
        self.assertIsNone(plan["source_edition"])
        self.assertEqual(
            plan["episodes"][0]["source_file"],
            normalized["relative_path"],
        )

    def test_normalized_source_override_rejects_ai_root(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            preview_translation_plan(
                source_root=str(self.source_root),
                catalog="catalog.json",
                translation_root=str(self.translation_root),
                source_edition="normalized_source",
                ai_edition_root=str(self.ai_root),
            )

    def test_cli_plan_only_defaults_to_ai_edition(self):
        catalog_path = self._prepare_ai_edition()
        plan_dir = self.root / "Workflow" / "Plans"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "ai-plan.json"
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    catalog_path.name,
                    "--translation-root",
                    str(self.translation_root),
                    "--plan-only",
                    "--plan-output",
                    str(plan_path),
                ]
            )

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        ai_index = json.loads(
            (self.ai_root / "catalog.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result, 0)
        self.assertEqual(plan["status"], "ready_for_review")
        self.assertEqual(plan["source_edition"]["profile_id"], "ai-efficient-v1")
        self.assertEqual(
            plan["episodes"][0]["source_version_id"],
            ai_index["episodes"][0]["ai_edition_version_id"],
        )
        self.assertNotIn(SOURCE_TEXT, plan_path.read_text(encoding="utf-8"))

    def test_ai_edition_plan_uses_raws_ai_and_tracks_archive_provenance(self):
        catalog_path = self._prepare_ai_edition()
        plan = preview_translation_plan(
            source_root=str(self.source_root),
            catalog=str(catalog_path.name),
            translation_root=str(self.translation_root),
        )

        ai_index = json.loads(
            (self.ai_root / "catalog.json").read_text(encoding="utf-8")
        )
        episode = plan["episodes"][0]
        indexed_episode = ai_index["episodes"][0]
        self.assertEqual(plan["status"], "ready_for_review")
        self.assertEqual(plan["verified_source_count"], 1)
        self.assertEqual(
            plan["source_edition"]["profile_id"],
            "ai-efficient-v1",
        )
        self.assertEqual(
            plan["source_edition"]["index_root"],
            str(self.ai_root),
        )
        self.assertEqual(
            episode["source_file"],
            indexed_episode["ai_archive_relative_path"],
        )
        self.assertEqual(
            episode["source_input_file"],
            indexed_episode["ai_relative_path"],
        )
        self.assertEqual(
            episode["source_sha256"],
            indexed_episode["output_sha256"],
        )
        self.assertEqual(
            episode["source_version_id"],
            indexed_episode["ai_edition_version_id"],
        )
        self.assertEqual(
            episode["source_input_version_id"],
            indexed_episode["raw_source_version_id"],
        )
        self.assertNotIn(SOURCE_TEXT, json.dumps(plan, ensure_ascii=False))

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
        ]
        specs = get_chapter_specs(
            str(self.source_root),
            str(self.translation_root),
            chapter_map,
            "source_editions_manifest.json",
            source_input_root=str(self.ai_root),
        )
        self.assertEqual(specs[0].raw_file, episode["source_file"])
        self.assertEqual(
            specs[0].source_input_file,
            episode["source_input_file"],
        )
        self.assertEqual(specs[0].source_sha256, episode["source_sha256"])
        self.assertEqual(
            (
                self.ai_root / indexed_episode["ai_relative_path"]
            ).read_bytes(),
            (
                self.source_root / indexed_episode["ai_archive_relative_path"]
            ).read_bytes(),
        )

    def test_ai_edition_plan_rejects_incomplete_catalog_index(self):
        catalog_path = self._prepare_ai_edition()
        index_path = self.ai_root / "catalog.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["episodes"] = []
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )

        plan = preview_translation_plan(
            source_root=str(self.source_root),
            catalog=str(catalog_path.name),
            translation_root=str(self.translation_root),
            ai_edition_root=str(self.ai_root),
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(
            plan["issues"],
            [{"episode_id": EPISODE_ID, "code": "stale_ai_edition_catalog"}],
        )
        self.assertIsNone(plan["episodes"][0]["source_version_id"])

    def test_ai_edition_plan_rejects_changed_output_bytes(self):
        catalog_path = self._prepare_ai_edition()
        ai_path = next(self.ai_root.rglob("*.md"))
        ai_path.write_bytes(ai_path.read_bytes() + b"changed")

        plan = preview_translation_plan(
            source_root=str(self.source_root),
            catalog=str(catalog_path.name),
            translation_root=str(self.translation_root),
            ai_edition_root=str(self.ai_root),
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(
            plan["issues"],
            [{"episode_id": EPISODE_ID, "code": "invalid_ai_edition"}],
        )
        self.assertEqual(plan["provider_calls"], 0)
        self.assertEqual(plan["network_requests"], 0)


if __name__ == "__main__":
    unittest.main()
