import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import ChapterSpec, Config, TranslationPipeline, get_chapter_specs
from scripts.validate_tm_provenance import audit_translation_memory
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from utils import read_relative_text, split_paragraphs


class SourcePipelineLinkageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.archive_root = self.root / "archive"
        self.translation_root = self.root / "translations"
        self.source_root.mkdir()
        self.archive_root.mkdir()
        self.translation_root.mkdir()
        self.raw_text = "Synthetic normalized source."
        (self.source_root / "chapter.txt").write_text(
            self.raw_text,
            encoding="utf-8",
        )
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "Synthetic episode", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id="synthetic-work",
            checkpoint_relative_path="updated_checkpoint.json",
        )
        self.artifact = materialize_episode_markdown(
            self.archive_root,
            work_id="synthetic-work",
            episode_id="episode-1",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _chapter_map(self, **overrides):
        entry = {
            "raw_file": self.artifact["relative_path"],
            "translation_file": "第1話.md",
            "tm_key": "Volume1/第1話.md",
            "source_version_id": self.artifact["version_id"],
        }
        entry.update(overrides)
        return [entry]

    def _translation_memory(self):
        translated_text = "Synthetic translation."
        (self.translation_root / "第1話.md").write_text(
            translated_text,
            encoding="utf-8",
        )
        provenance = {
            "schema_version": 1,
            "producer": "pipeline",
            "raw_file": self.artifact["relative_path"],
            "raw_sha256": hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest(),
            "translation_file": "第1話.md",
            "translation_sha256": hashlib.sha256(
                translated_text.encode("utf-8")
            ).hexdigest(),
            "source_version_id": self.artifact["version_id"],
            "pair_mappings": [
                {
                    "pair_index": 1,
                    "raw_paragraph_indices": [1],
                    "translation_paragraph_indices": [1],
                    "trace_status": "matched",
                }
            ],
        }
        return {
            "chapters": {
                "Volume1/第1話.md": [
                    {"raw": self.raw_text, "translated": translated_text}
                ]
            },
            "source_provenance": {
                "Volume1/第1話.md": provenance,
            },
        }

    def test_chapter_map_resolves_and_verifies_a_manifest_version(self):
        specs = get_chapter_specs(
            str(self.archive_root),
            str(self.translation_root),
            self._chapter_map(),
            "source_manifest.json",
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].raw_file, self.artifact["relative_path"])
        self.assertEqual(specs[0].source_version_id, self.artifact["version_id"])

    def test_versioned_map_requires_manifest_and_matching_source_path(self):
        with self.assertRaisesRegex(ValueError, "requires SOURCE_MANIFEST_PATH"):
            get_chapter_specs(
                str(self.archive_root),
                str(self.translation_root),
                self._chapter_map(),
            )

        other_source = self.archive_root / "other.md"
        other_source.write_text("different synthetic source", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            get_chapter_specs(
                str(self.archive_root),
                str(self.translation_root),
                self._chapter_map(raw_file="other.md"),
                "source_manifest.json",
            )

    def test_versioned_map_rejects_changed_manifest_artifact(self):
        source_path = self.archive_root / self.artifact["relative_path"]
        source_path.write_text("changed source", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "hash does not match"):
            get_chapter_specs(
                str(self.archive_root),
                str(self.translation_root),
                self._chapter_map(),
                "source_manifest.json",
            )

    def test_tm_audit_verifies_source_version_and_reports_missing_manifest(self):
        tm_data = self._translation_memory()

        verified = audit_translation_memory(
            tm_data,
            str(self.archive_root),
            str(self.translation_root),
            "source_manifest.json",
        )
        unverified = audit_translation_memory(
            tm_data,
            str(self.archive_root),
            str(self.translation_root),
        )

        self.assertEqual([item["status"] for item in verified], ["verified"])
        self.assertIn(
            "unverified",
            [item["status"] for item in unverified],
        )

    def test_tm_audit_marks_older_manifest_version_stale(self):
        tm_data = self._translation_memory()
        updated_text = "Synthetic updated source."
        (self.source_root / "chapter.txt").write_text(
            updated_text,
            encoding="utf-8",
        )
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "Synthetic episode", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(adapter, root=self.archive_root, work_id="synthetic-work")
        latest_artifact = materialize_episode_markdown(
            self.archive_root,
            work_id="synthetic-work",
            episode_id="episode-1",
        )

        self.assertEqual(latest_artifact["artifact_id"], self.artifact["artifact_id"])
        self.assertNotEqual(latest_artifact["version_id"], self.artifact["version_id"])
        stale = audit_translation_memory(
            tm_data,
            str(self.archive_root),
            str(self.translation_root),
            "source_manifest.json",
        )
        self.assertEqual([item["status"] for item in stale], ["stale"])

        (self.archive_root / latest_artifact["relative_path"]).write_text(
            "tampered latest source",
            encoding="utf-8",
        )
        invalid = audit_translation_memory(
            tm_data,
            str(self.archive_root),
            str(self.translation_root),
            "source_manifest.json",
        )
        self.assertEqual([item["status"] for item in invalid], ["invalid"])

    def test_tm_audit_marks_raw_update_before_materialization_stale(self):
        tm_data = self._translation_memory()
        (self.source_root / "chapter.txt").write_text(
            "Updated raw source before normalization.",
            encoding="utf-8",
        )
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "Synthetic episode", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id="synthetic-work",
            checkpoint_relative_path="raw-only-checkpoint.json",
        )

        with self.assertRaisesRegex(ValueError, "Normalized source is stale"):
            get_chapter_specs(
                str(self.archive_root),
                str(self.translation_root),
                self._chapter_map(),
                "source_manifest.json",
            )

        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        with (
            patch.object(Config, "RAW_DIR", str(self.archive_root)),
            patch.object(Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"),
        ):
            with self.assertRaisesRegex(ValueError, "Normalized source is stale"):
                pipeline._verify_chapter_source_snapshot(
                    ChapterSpec(
                        self.artifact["relative_path"],
                        "第1話.md",
                        "Volume1/第1話.md",
                        self.artifact["version_id"],
                    ),
                    self.raw_text,
                    mapped_paths=True,
                )

        findings = audit_translation_memory(
            tm_data,
            str(self.archive_root),
            str(self.translation_root),
            "source_manifest.json",
        )

        self.assertEqual([item["status"] for item in findings], ["stale"])
        self.assertIn("older raw source", findings[0]["detail"])

    def test_tm_audit_verifies_byte_preserving_crlf_source_version(self):
        source_root = self.root / "crlf-source"
        archive_root = self.root / "crlf-archive"
        translation_root = self.root / "crlf-translations"
        source_root.mkdir()
        archive_root.mkdir()
        translation_root.mkdir()
        source_bytes = b"Source paragraph one.\r\n\r\nSource paragraph two.\r\n"
        (source_root / "chapter.txt").write_bytes(source_bytes)
        adapter = LocalFileAdapter(
            source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("crlf-episode", "CRLF fixture", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(adapter, root=archive_root, work_id="crlf-work")
        artifact = materialize_episode_markdown(
            archive_root,
            work_id="crlf-work",
            episode_id="crlf-episode",
        )
        self.assertEqual(
            (archive_root / artifact["relative_path"]).read_bytes(),
            source_bytes,
        )

        raw_text = read_relative_text(
            str(archive_root), artifact["relative_path"]
        )
        translated_text = "Translation paragraph one.\n\nTranslation paragraph two."
        (translation_root / "chapter.md").write_text(
            translated_text,
            encoding="utf-8",
        )
        raw_paragraphs = split_paragraphs(raw_text)
        translated_paragraphs = split_paragraphs(translated_text)
        chapter_key = "Volume1/chapter.md"
        pairs = [
            {"raw": raw, "translated": translated}
            for raw, translated in zip(raw_paragraphs, translated_paragraphs)
        ]
        provenance = {
            "schema_version": 1,
            "producer": "pipeline",
            "raw_file": artifact["relative_path"],
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "translation_file": "chapter.md",
            "translation_sha256": hashlib.sha256(
                translated_text.encode("utf-8")
            ).hexdigest(),
            "source_version_id": artifact["version_id"],
            "pair_mappings": [
                {
                    "pair_index": index,
                    "raw_paragraph_indices": [index],
                    "translation_paragraph_indices": [index],
                    "trace_status": "matched",
                }
                for index in range(1, len(pairs) + 1)
            ],
        }
        findings = audit_translation_memory(
            {
                "chapters": {chapter_key: pairs},
                "source_provenance": {chapter_key: provenance},
            },
            str(archive_root),
            str(translation_root),
            "source_manifest.json",
        )

        self.assertNotIn("\r", raw_text)
        self.assertEqual([item["status"] for item in findings], ["verified"])

    def test_config_loads_relative_source_manifest_setting(self):
        config_path = self.root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "WORKSPACE_DIR": str(self.root),
                    "RAW_DIR": str(self.archive_root),
                    "OUTPUT_DIR": str(self.translation_root),
                    "SOURCE_MANIFEST_PATH": "source_manifest.json",
                    "CHAPTER_MAP": self._chapter_map(),
                }
            ),
            encoding="utf-8",
        )

        config_state = {
            name: value
            for name, value in vars(Config).items()
            if name.isupper()
        }
        with patch.multiple(Config, **config_state):
            with patch.dict("os.environ", {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))

            specs = get_chapter_specs(
                Config.RAW_DIR,
                Config.OUTPUT_DIR,
                Config.CHAPTER_MAP,
                Config.SOURCE_MANIFEST_PATH,
            )

            self.assertEqual(
                Config.SOURCE_MANIFEST_PATH,
                "source_manifest.json",
            )
            self.assertEqual(
                specs[0].source_version_id,
                self.artifact["version_id"],
            )


if __name__ == "__main__":
    unittest.main()
