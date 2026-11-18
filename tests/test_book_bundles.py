import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import book_bundles
from book_bundles import export_book_bundles, load_verified_ai_book_bundle
from scripts.export_book_bundles import main as export_main
from source_editions import prepare_source_editions
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)


class BookBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.input_root = self.root / "input"
        self.source_root = self.root / "archive"
        self.human_root = self.root / "human"
        self.ai_root = self.root / "ai"
        for path in (self.input_root, self.source_root, self.human_root, self.ai_root):
            path.mkdir()

        self.work_id = "12345"
        self.work_metadata = {
            "source_url": "https://kakuyomu.jp/works/12345",
            "title": "Synthetic work",
            "author_name": "Synthetic author",
            "author_screen_name": "synthetic",
            "catchphrase": "A test work",
            "introduction": "Synthetic introduction",
            "genre": "fantasy",
            "tags": ["synthetic"],
            "serial_status": "ongoing",
            "published_at": None,
            "last_episode_published_at": None,
            "public_episode_count": 2,
        }
        self.source_text = {
            "101": "Synthetic first episode.\n",
            "102": "Synthetic second episode.\n",
        }
        episodes = []
        for episode_id, title, position in (
            ("101", "First episode", 1),
            ("102", "Second episode", 2),
        ):
            page_url = (
                "https://kakuyomu.jp/works/12345/episodes/" + episode_id
            )
            filename = episode_id + ".txt"
            (self.input_root / filename).write_bytes(
                self.source_text[episode_id].encode("utf-8")
            )
            episodes.append(
                LocalEpisodeFile(
                    EpisodeMetadata(
                        episode_id,
                        title,
                        position,
                        page_url,
                    ),
                    filename,
                )
            )
        collect_source(
            LocalFileAdapter(self.input_root, episodes),
            root=self.source_root,
            work_id=self.work_id,
            work_metadata=self.work_metadata,
        )
        self.catalog_path = self.source_root / "catalog.json"
        catalog = {
            "schema_version": 3,
            "work_id": self.work_id,
            "work_metadata": self.work_metadata,
            "episodes": [
                {
                    "episode_id": item.metadata.episode_id,
                    "title": item.metadata.title,
                    "position": item.metadata.position,
                    "page_url": item.metadata.source_ref,
                }
                for item in episodes
            ],
            "chapters": [
                {
                    "group_id": "chapter-1",
                    "chapter_id": "chapter-1",
                    "title": "Chapter One",
                    "level": 1,
                    "position_start": 1,
                    "position_end": 2,
                    "episode_ids": ["101", "102"],
                }
            ],
        }
        self.catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )
        for item in episodes:
            materialize_episode_markdown(
                self.source_root,
                work_id=self.work_id,
                episode_id=item.metadata.episode_id,
            )
        prepare_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            manifest_relative_path="source_manifest.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _export(self, **overrides):
        arguments = {
            "source_root": str(self.source_root),
            "catalog_relative_path": "catalog.json",
            "human_root": str(self.human_root),
            "ai_root": str(self.ai_root),
            "checkpoint_relative_path": "source_checkpoint.json",
        }
        arguments.update(overrides)
        return export_book_bundles(**arguments)

    def test_exports_complete_self_contained_bundles_and_manifest(self):
        report = self._export()
        bundle_set = json.loads(
            (self.source_root / report["bundle_set_relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        paths = {
            name: Path(root) / record["relative_path"]
            for name, root in (
                ("raw", self.source_root),
                ("ai", self.ai_root),
                ("human", self.human_root),
            )
            for record in [bundle_set["bundles"][name]]
        }
        raw_bundle = json.loads(paths["raw"].read_text(encoding="utf-8"))
        ai_bundle = json.loads(paths["ai"].read_text(encoding="utf-8"))
        human_bundle = paths["human"].read_text(encoding="utf-8")

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(bundle_set["status"], "complete")
        self.assertEqual(
            bundle_set["completeness"]["status"],
            "complete_for_declared_public_catalog",
        )
        self.assertEqual(
            bundle_set["completeness"]["platform_enumeration_exhaustiveness"],
            "not_independently_proven",
        )
        self.assertEqual(
            [item["source_text"] for item in raw_bundle["episodes"]],
            list(self.source_text.values()),
        )
        self.assertEqual(
            [item["source_text"] for item in ai_bundle["episodes"]],
            list(self.source_text.values()),
        )
        self.assertIn(_HUMAN_MARKER, human_bundle)
        self.assertIn("episode:start:1", human_bundle)
        self.assertIn("episode:end:2", human_bundle)
        self.assertNotIn("Synthetic first episode.", json.dumps(report))
        for edition, path in paths.items():
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                bundle_set["bundles"][edition]["sha256"],
            )

    def test_repeated_export_is_idempotent(self):
        first = self._export()
        second = self._export()

        self.assertEqual(first["source_snapshot_id"], second["source_snapshot_id"])
        self.assertTrue(all(first["created"].values()))
        self.assertFalse(any(second["created"].values()))
        self.assertEqual(
            first["bundles"],
            second["bundles"],
        )

    def test_ai_bundle_loader_verifies_complete_current_snapshot(self):
        report = self._export()
        verified = load_verified_ai_book_bundle(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            checkpoint_relative_path="source_checkpoint.json",
            bundle_set_relative_path=report["bundle_set_relative_path"],
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["episode_count"], 2)
        self.assertEqual(
            verified["source_snapshot_id"],
            report["source_snapshot_id"],
        )
        self.assertEqual(
            [
                episode["source_text"]
                for episode in verified["bundle"]["episodes"]
            ],
            list(self.source_text.values()),
        )
        for episode in verified["episodes_by_source_input_file"].values():
            self.assertTrue(episode["source_file"])

    def test_ai_bundle_loader_rejects_changed_bundle_content(self):
        report = self._export()
        ai_bundle_path = (
            self.ai_root / report["bundles"]["ai"]["relative_path"]
        )
        ai_bundle_path.write_bytes(b"changed after completion")

        with self.assertRaisesRegex(ValueError, "completion set"):
            load_verified_ai_book_bundle(
                source_root=str(self.source_root),
                catalog_relative_path="catalog.json",
                checkpoint_relative_path="source_checkpoint.json",
                bundle_set_relative_path=report["bundle_set_relative_path"],
                human_root=str(self.human_root),
                ai_root=str(self.ai_root),
            )

    def test_failed_partial_export_can_resume_before_completion_marker(self):
        original = book_bundles._write_immutable
        failed = [False]

        def fail_once(root, relative_path, content):
            if relative_path.endswith("/book-ai.json") and not failed[0]:
                failed[0] = True
                raise OSError("synthetic write interruption")
            return original(root, relative_path, content)

        with patch("book_bundles._write_immutable", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "write interruption"):
                self._export()

        collection_root = self.source_root / "collections"
        self.assertTrue(collection_root.exists())
        self.assertEqual(list(collection_root.rglob("bundle-set.*.json")), [])

        resumed = self._export()
        self.assertFalse(resumed["created"]["raw"])
        self.assertTrue(resumed["created"]["ai"])
        self.assertTrue(resumed["created"]["human"])
        self.assertTrue(resumed["created"]["bundle_set"])

    def test_incomplete_checkpoint_fails_before_writing(self):
        checkpoint_path = self.source_root / "source_checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["status"] = "paused"
        checkpoint["pause_reason"] = "unavailable"
        checkpoint_path.write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "complete current checkpoint"):
            self._export()
        self.assertFalse((self.source_root / "collections").exists())

    def test_output_limit_fails_before_writing(self):
        with self.assertRaisesRegex(ValueError, "output byte limit"):
            self._export(max_total_output_bytes=1)
        self.assertFalse((self.source_root / "collections").exists())
        self.assertFalse((self.ai_root / "collections").exists())
        self.assertFalse((self.human_root / "collections").exists())

    def test_cli_reports_metadata_without_chapter_text(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = export_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--human-root",
                    str(self.human_root),
                    "--ai-root",
                    str(self.ai_root),
                    "--checkpoint",
                    "source_checkpoint.json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn('"status": "complete"', stdout.getvalue())
        for source_text in self.source_text.values():
            self.assertNotIn(source_text.strip(), stdout.getvalue())
        self.assertIn("source_snapshot_id", stdout.getvalue())


_HUMAN_MARKER = "<!-- translation-workflow-human-bundle:v1"


if __name__ == "__main__":
    unittest.main()
