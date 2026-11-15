import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pipeline import get_chapter_specs
from scripts.ingest_local_sources import main as ingest_local_main
from scripts.materialize_source_markdown import main
from scripts.merge_source_markdown import main as merge_main
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_complete_checkpoint_catalog_markdown,
    materialize_episode_collection_markdown,
    materialize_episode_markdown,
)
from source_manifest import load_manifest, verify_manifest_files


class SourceMarkdownMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.archive_root = self.root / "archive"
        self.source_root.mkdir()
        self.archive_root.mkdir()
        self.work_id = "synthetic-work"
        self.episode_id = "episode-1"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _archive(self, content):
        (self.source_root / "chapter.bin").write_bytes(content)
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata(self.episode_id, "Synthetic chapter", 1),
                    "chapter.bin",
                )
            ],
        )
        return collect_source(
            adapter,
            root=self.archive_root,
            work_id=self.work_id,
        )

    def _archive_many(self, episodes):
        catalog = []
        for episode_id, title, position, content in episodes:
            relative_path = f"{episode_id}.bin"
            (self.source_root / relative_path).write_bytes(content)
            catalog.append(
                LocalEpisodeFile(
                    EpisodeMetadata(episode_id, title, position),
                    relative_path,
                )
            )
        adapter = LocalFileAdapter(self.source_root, catalog)
        collect_source(
            adapter,
            root=self.archive_root,
            work_id=self.work_id,
            checkpoint_relative_path="source_checkpoint_many.json",
        )
        return [
            materialize_episode_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_id=episode_id,
            )
            for episode_id, _, _, _ in episodes
        ]

    def test_materializes_exact_utf8_bytes_and_is_idempotent(self):
        source_bytes = (
            "\ufeff# 第1話\r\n\r\n前書き\n本文「確認」\r\n"
        ).encode("utf-8")
        self._archive(source_bytes)

        artifact = materialize_episode_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_id=self.episode_id,
        )
        output_path = self.archive_root / artifact["relative_path"]
        manifest = load_manifest(self.archive_root / "source_manifest.json")
        raw_artifact = next(
            item for item in manifest["artifacts"] if item["kind"] == "raw_source"
        )

        self.assertEqual(artifact["kind"], "normalized_source")
        self.assertIn(raw_artifact["version_id"], artifact["parent_version_ids"])
        self.assertEqual(output_path.suffix, ".md")
        self.assertEqual(output_path.read_bytes(), source_bytes)
        self.assertEqual(
            artifact["content_sha256"],
            hashlib.sha256(source_bytes).hexdigest(),
        )
        self.assertEqual(
            (self.source_root / "chapter.bin").read_bytes(),
            source_bytes,
        )

        repeated = materialize_episode_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_id=self.episode_id,
        )
        updated_manifest = load_manifest(self.archive_root / "source_manifest.json")
        self.assertEqual(repeated, artifact)
        self.assertEqual(len(updated_manifest["artifacts"]), 3)
        self.assertEqual(verify_manifest_files(self.archive_root, updated_manifest), 3)

    def test_invalid_utf8_does_not_change_manifest_or_create_markdown(self):
        self._archive(b"invalid utf-8: \xff")
        manifest_path = self.archive_root / "source_manifest.json"
        original_manifest = manifest_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
            materialize_episode_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_id=self.episode_id,
            )

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertFalse((self.archive_root / "normalized").exists())

    def test_byte_limit_rejects_before_writing_markdown(self):
        self._archive(b"synthetic chapter")
        manifest_path = self.archive_root / "source_manifest.json"
        original_manifest = manifest_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "configured byte limit"):
            materialize_episode_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_id=self.episode_id,
                max_bytes=4,
            )

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertFalse((self.archive_root / "normalized").exists())

    def test_cli_reports_artifact_metadata_without_source_text(self):
        source_bytes = b"synthetic chapter text"
        self._archive(source_bytes)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--root",
                    str(self.archive_root),
                    "--work-id",
                    self.work_id,
                    "--episode-id",
                    self.episode_id,
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "materialized")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(source_bytes.decode("utf-8"), stdout.getvalue())
        self.assertEqual(
            (self.archive_root / report["relative_path"]).read_bytes(),
            source_bytes,
        )

    def test_merges_explicit_episode_order_with_version_provenance(self):
        normalized = self._archive_many(
            [
                ("episode-1", "First", 1, b"# First\r\nBody one"),
                ("episode-2", "Second", 2, b"# Second\nBody two"),
            ]
        )

        artifact = materialize_episode_collection_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_ids=["episode-1", "episode-2"],
            max_bytes=1024,
        )
        output_path = self.archive_root / artifact["relative_path"]
        manifest = load_manifest(self.archive_root / "source_manifest.json")

        self.assertEqual(artifact["kind"], "export")
        self.assertEqual(
            output_path.read_bytes(),
            b"# First\r\nBody one\n\n# Second\nBody two",
        )
        self.assertEqual(
            artifact["parent_version_ids"],
            [item["version_id"] for item in normalized],
        )
        repeated = materialize_episode_collection_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_ids=["episode-1", "episode-2"],
            max_bytes=1024,
        )
        updated_manifest = load_manifest(self.archive_root / "source_manifest.json")
        self.assertEqual(repeated, artifact)
        self.assertEqual(
            len(
                [
                    item
                    for item in updated_manifest["artifacts"]
                    if item["kind"] == "export"
                ]
            ),
            1,
        )
        self.assertEqual(len(manifest["artifacts"]), len(updated_manifest["artifacts"]))

    def test_exports_all_current_episodes_from_complete_checkpoint(self):
        normalized = self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )

        result = materialize_complete_checkpoint_catalog_markdown(
            self.archive_root,
            work_id=self.work_id,
            checkpoint_relative_path="source_checkpoint_many.json",
            max_bytes=1024,
        )
        checkpoint = json.loads(
            (self.archive_root / "source_checkpoint_many.json").read_text(
                encoding="utf-8"
            )
        )
        artifact = result["artifact"]

        self.assertEqual(result["episode_ids"], ["episode-1", "episode-2"])
        self.assertEqual(
            result["source_fingerprint"], checkpoint["source_fingerprint"]
        )
        self.assertEqual(
            artifact["parent_version_ids"],
            [item["version_id"] for item in normalized],
        )
        self.assertEqual(
            (self.archive_root / artifact["relative_path"]).read_bytes(),
            b"first\n\nsecond",
        )

    def test_local_catalog_flows_through_export_and_versioned_chapter_map(self):
        source_items = [
            ("episode-1", "Synthetic first", 1, "first.txt", b"synthetic one\r\nline"),
            ("episode-2", "Synthetic second", 2, "second.txt", b"synthetic two\nline"),
        ]
        catalog = {
            "schema_version": 1,
            "work_id": self.work_id,
            "episodes": [],
        }
        for episode_id, title, position, filename, content in source_items:
            (self.source_root / filename).write_bytes(content)
            catalog["episodes"].append(
                {
                    "episode_id": episode_id,
                    "title": title,
                    "position": position,
                    "relative_path": filename,
                }
            )
        (self.source_root / "catalog.json").write_text(
            json.dumps(catalog),
            encoding="utf-8",
        )

        ingest_stdout = io.StringIO()
        ingest_stderr = io.StringIO()
        with redirect_stdout(ingest_stdout), redirect_stderr(ingest_stderr):
            ingest_result = ingest_local_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(self.archive_root),
                ]
            )

        self.assertEqual(ingest_result, 0)
        self.assertEqual(ingest_stderr.getvalue(), "")
        ingest_report = json.loads(ingest_stdout.getvalue())
        self.assertEqual(ingest_report["status"], "complete")
        self.assertEqual(ingest_report["completed_count"], 2)
        for _, _, _, _, content in source_items:
            self.assertNotIn(content.decode("utf-8"), ingest_stdout.getvalue())

        normalized = {
            episode_id: materialize_episode_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_id=episode_id,
            )
            for episode_id, _, _, _, _ in source_items
        }
        merge_stdout = io.StringIO()
        merge_stderr = io.StringIO()
        with redirect_stdout(merge_stdout), redirect_stderr(merge_stderr):
            merge_result = merge_main(
                [
                    "--root",
                    str(self.archive_root),
                    "--work-id",
                    self.work_id,
                    "--complete-checkpoint",
                    "--max-bytes",
                    "1024",
                ]
            )

        self.assertEqual(merge_result, 0)
        self.assertEqual(merge_stderr.getvalue(), "")
        merge_report = json.loads(merge_stdout.getvalue())
        self.assertEqual(merge_report["coverage_scope"], "complete_checkpoint_catalog")
        self.assertEqual(merge_report["episode_count"], 2)
        export_bytes = (
            self.archive_root / merge_report["relative_path"]
        ).read_bytes()
        self.assertEqual(
            export_bytes,
            b"synthetic one\r\nline\n\nsynthetic two\nline",
        )

        translation_root = self.root / "translations"
        translation_root.mkdir()
        chapter_map = [
            {
                "raw_file": normalized[episode_id]["relative_path"],
                "translation_file": f"{episode_id}.md",
                "tm_key": episode_id,
                "source_version_id": normalized[episode_id]["version_id"],
            }
            for episode_id, _, _, _, _ in source_items
        ]
        specs = get_chapter_specs(
            str(self.archive_root),
            str(translation_root),
            chapter_map,
            "source_manifest.json",
        )

        self.assertEqual(
            [spec.source_version_id for spec in specs],
            [normalized[episode_id]["version_id"] for episode_id, *_ in source_items],
        )
        self.assertEqual(
            [spec.raw_file for spec in specs],
            [normalized[episode_id]["relative_path"] for episode_id, *_ in source_items],
        )
        manifest = load_manifest(self.archive_root / "source_manifest.json")
        self.assertEqual(verify_manifest_files(self.archive_root, manifest), 7)

    def test_complete_checkpoint_rejects_missing_episode_without_writing(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        checkpoint_path = self.archive_root / "source_checkpoint_many.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["completed_episode_ids"].pop()
        checkpoint["completed_raw_versions"].pop("episode-2")
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        manifest_path = self.archive_root / "source_manifest.json"
        original_manifest = manifest_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "incomplete episode set"):
            materialize_complete_checkpoint_catalog_markdown(
                self.archive_root,
                work_id=self.work_id,
                checkpoint_relative_path="source_checkpoint_many.json",
                max_bytes=1024,
            )

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertFalse((self.archive_root / "exports").exists())

    def test_complete_checkpoint_rejects_raw_versions_from_a_newer_run(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        (self.source_root / "episode-2.bin").write_bytes(b"updated second")
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "First", 1),
                    "episode-1.bin",
                ),
                LocalEpisodeFile(
                    EpisodeMetadata("episode-2", "Second", 2),
                    "episode-2.bin",
                ),
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id=self.work_id,
            checkpoint_relative_path="source_checkpoint_updated.json",
        )

        with self.assertRaisesRegex(ValueError, "checkpoint is stale"):
            materialize_complete_checkpoint_catalog_markdown(
                self.archive_root,
                work_id=self.work_id,
                checkpoint_relative_path="source_checkpoint_many.json",
                max_bytes=1024,
            )

        self.assertFalse((self.archive_root / "exports").exists())

    def test_merge_rejects_duplicate_or_non_source_order_without_writes(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        manifest_path = self.archive_root / "source_manifest.json"
        original_manifest = manifest_path.read_bytes()

        for episode_ids, message in (
            (["episode-1", "episode-1"], "must be unique"),
            (["episode-2", "episode-1"], "increasing source positions"),
        ):
            with self.subTest(episode_ids=episode_ids):
                with self.assertRaisesRegex(ValueError, message):
                    materialize_episode_collection_markdown(
                        self.archive_root,
                        work_id=self.work_id,
                        episode_ids=episode_ids,
                        max_bytes=1024,
                    )

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertFalse((self.archive_root / "exports").exists())

    def test_merge_rejects_stale_normalized_episode(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        (self.source_root / "episode-2.bin").write_bytes(b"updated second")
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "First", 1),
                    "episode-1.bin",
                ),
                LocalEpisodeFile(
                    EpisodeMetadata("episode-2", "Second", 2),
                    "episode-2.bin",
                ),
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id=self.work_id,
            checkpoint_relative_path="source_checkpoint_updated.json",
        )

        with self.assertRaisesRegex(ValueError, "normalized Markdown is stale"):
            materialize_episode_collection_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_ids=["episode-1", "episode-2"],
                max_bytes=1024,
            )

    def test_merge_rejects_corrupted_raw_parent(self):
        normalized = self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        manifest = load_manifest(self.archive_root / "source_manifest.json")
        raw_version_id = normalized[1]["parent_version_ids"][0]
        raw_artifact = next(
            item
            for item in manifest["artifacts"]
            if item["version_id"] == raw_version_id
        )
        (self.archive_root / raw_artifact["relative_path"]).write_bytes(b"tampered")

        with self.assertRaisesRegex(ValueError, "content hash does not match"):
            materialize_episode_collection_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_ids=["episode-1", "episode-2"],
                max_bytes=1024,
            )
        self.assertFalse((self.archive_root / "exports").exists())

    def test_merge_appends_new_export_when_normalized_source_changes(self):
        normalized = self._archive_many(
            [
                ("episode-1", "First", 1, b"first"),
                ("episode-2", "Second", 2, b"second"),
            ]
        )
        first_export = materialize_episode_collection_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_ids=["episode-1", "episode-2"],
            max_bytes=1024,
        )
        (self.source_root / "episode-2.bin").write_bytes(b"updated second")
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "First", 1),
                    "episode-1.bin",
                ),
                LocalEpisodeFile(
                    EpisodeMetadata("episode-2", "Second", 2),
                    "episode-2.bin",
                ),
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id=self.work_id,
            checkpoint_relative_path="source_checkpoint_updated.json",
        )
        updated_normalized = materialize_episode_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_id="episode-2",
        )

        second_export = materialize_episode_collection_markdown(
            self.archive_root,
            work_id=self.work_id,
            episode_ids=["episode-1", "episode-2"],
            max_bytes=1024,
        )
        updated_manifest = load_manifest(self.archive_root / "source_manifest.json")
        export_versions = [
            item
            for item in updated_manifest["artifacts"]
            if item["kind"] == "export"
        ]

        self.assertNotEqual(second_export["version_id"], first_export["version_id"])
        self.assertEqual(
            second_export["parent_version_ids"],
            [
                normalized[0]["version_id"],
                updated_normalized["version_id"],
                first_export["version_id"],
            ],
        )
        self.assertEqual(len(export_versions), 2)
        self.assertEqual(
            (self.archive_root / second_export["relative_path"]).read_bytes(),
            b"first\n\nupdated second",
        )

    def test_merge_byte_limit_includes_separators_and_is_preflighted(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"1234"),
                ("episode-2", "Second", 2, b"5678"),
            ]
        )
        manifest_path = self.archive_root / "source_manifest.json"
        original_manifest = manifest_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "configured byte limit"):
            materialize_episode_collection_markdown(
                self.archive_root,
                work_id=self.work_id,
                episode_ids=["episode-1", "episode-2"],
                max_bytes=9,
            )

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertFalse((self.archive_root / "exports").exists())

    def test_merge_cli_reports_metadata_without_episode_text(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"private chapter one"),
                ("episode-2", "Second", 2, b"private chapter two"),
            ]
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = merge_main(
                [
                    "--root",
                    str(self.archive_root),
                    "--work-id",
                    self.work_id,
                    "--episode-id",
                    "episode-1",
                    "--episode-id",
                    "episode-2",
                    "--max-bytes",
                    "1024",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "materialized")
        self.assertEqual(report["coverage_scope"], "explicit_episode_selection")
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("private chapter", stdout.getvalue())

    def test_merge_cli_complete_checkpoint_mode_reports_catalog_scope(self):
        self._archive_many(
            [
                ("episode-1", "First", 1, b"private chapter one"),
                ("episode-2", "Second", 2, b"private chapter two"),
            ]
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = merge_main(
                [
                    "--root",
                    str(self.archive_root),
                    "--work-id",
                    self.work_id,
                    "--complete-checkpoint",
                    "source_checkpoint_many.json",
                    "--max-bytes",
                    "1024",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["coverage_scope"], "complete_checkpoint_catalog")
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(
            report["source_fingerprint"],
            json.loads(
                (self.archive_root / "source_checkpoint_many.json").read_text(
                    encoding="utf-8"
                )
            )["source_fingerprint"],
        )
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("private chapter", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
