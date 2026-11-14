import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from pipeline import Config
from scripts.validate_tm_provenance import audit_translation_memory, main
from utils import validate_tm_source_provenance


class TestTMProvenanceAudit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw_dir = self.root / "raw"
        self.translation_dir = self.root / "translated"
        self.raw_dir.mkdir()
        self.translation_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _source_provenance(
        self, raw_text: str, translation_text: str, mappings: list[dict]
    ) -> dict:
        return {
            "schema_version": 1,
            "producer": "scripts/align_chapters.py",
            "raw_file": "chapter.md",
            "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "translation_file": "chapter.md",
            "translation_sha256": hashlib.sha256(
                translation_text.encode("utf-8")
            ).hexdigest(),
            "pair_mappings": mappings,
        }

    def _mapping(
        self, index: int, raw: list[int], translated: list[int], status: str
    ) -> dict:
        return {
            "pair_index": index,
            "raw_paragraph_indices": raw,
            "translation_paragraph_indices": translated,
            "trace_status": status,
        }

    def _write_sources(self, raw_text: str, translation_text: str) -> None:
        (self.raw_dir / "chapter.md").write_text(raw_text, encoding="utf-8")
        (self.translation_dir / "chapter.md").write_text(
            translation_text, encoding="utf-8"
        )

    def _run_cli(self, tm_data: dict) -> tuple[int, str, Path, bytes]:
        tm_path = self.root / "translation_memory.json"
        tm_path.write_text(json.dumps(tm_data), encoding="utf-8")
        original_tm = tm_path.read_bytes()
        output = io.StringIO()
        env = {
            "TEST_WORKSPACE_DIR": str(self.root),
            "TEST_RAW_DIR": str(self.raw_dir),
            "TEST_OUTPUT_DIR": str(self.translation_dir),
            "TEST_TM_PATH": str(tm_path),
        }

        with patch.dict(os.environ, env, clear=True):
            with redirect_stdout(output):
                exit_code = main([])
        return exit_code, output.getvalue(), tm_path, original_tm

    def test_verifies_hashes_and_merged_paragraph_mapping(self):
        raw_text = "第一段\n\n第二段"
        translation_text = "译文一\n\n译文二"
        self._write_sources(raw_text, translation_text)
        tm_data = {
            "chapters": {
                "chapter.md": [
                    {
                        "raw": raw_text,
                        "translated": translation_text,
                        "embedding": [],
                    }
                ]
            },
            "source_provenance": {
                "chapter.md": self._source_provenance(
                    raw_text,
                    translation_text,
                    [self._mapping(1, [1, 2], [1, 2], "matched")],
                )
            },
        }

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual([finding["status"] for finding in findings], ["verified"])

    def test_verifies_mapped_nested_source_and_translation_paths(self):
        raw_text = "合成原文"
        translation_text = "合成译文"
        raw_subdir = self.raw_dir / "Volume 1"
        translation_subdir = self.translation_dir / "Ntera"
        raw_subdir.mkdir()
        translation_subdir.mkdir()
        (raw_subdir / "第1話.md").write_text(raw_text, encoding="utf-8")
        (translation_subdir / "第一話.md").write_text(
            translation_text, encoding="utf-8"
        )
        provenance = self._source_provenance(
            raw_text,
            translation_text,
            [self._mapping(1, [1], [1], "matched")],
        )
        provenance["raw_file"] = "Volume 1/第1話.md"
        provenance["translation_file"] = "Ntera/第一話.md"
        tm_data = {
            "chapters": {
                "Volume1/第1話.md": [
                    {"raw": raw_text, "translated": translation_text}
                ]
            },
            "source_provenance": {
                "Volume1/第1話.md": provenance,
            },
        }

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual([finding["status"] for finding in findings], ["verified"])

    def test_reports_stale_hash_and_changed_pair_text(self):
        raw_text = "原文"
        translation_text = "译文"
        self._write_sources("新原文", translation_text)
        tm_data = {
            "chapters": {
                "chapter.md": [
                    {"raw": raw_text, "translated": translation_text}
                ]
            },
            "source_provenance": {
                "chapter.md": self._source_provenance(
                    raw_text,
                    translation_text,
                    [self._mapping(1, [1], [1], "matched")],
                )
            },
        }

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual(
            [finding["status"] for finding in findings], ["stale", "mismatch"]
        )

    def test_reports_unindexed_legacy_chapter_without_mutating_tm(self):
        tm_data = {"chapters": {"legacy.md": [{"raw": "原文", "translated": "译文"}]}}

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual(findings[0]["status"], "unindexed")
        self.assertNotIn("source_provenance", tm_data)

    def test_empty_translation_memory_is_not_reported_as_verified(self):
        findings = audit_translation_memory(
            {"chapters": {}}, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual([finding["status"] for finding in findings], ["unverified"])

    def test_cli_reports_verified_without_rewriting_tm(self):
        raw_text = "原文"
        translation_text = "译文"
        self._write_sources(raw_text, translation_text)
        tm_data = {
            "chapters": {
                "chapter.md": [{"raw": raw_text, "translated": translation_text}]
            },
            "source_provenance": {
                "chapter.md": self._source_provenance(
                    raw_text,
                    translation_text,
                    [self._mapping(1, [1], [1], "matched")],
                )
            },
        }
        exit_code, output, tm_path, original_tm = self._run_cli(tm_data)

        self.assertEqual(exit_code, 0)
        self.assertIn("VERIFIED chapter.md", output)
        self.assertEqual(tm_path.read_bytes(), original_tm)

    def test_cli_returns_one_for_stale_source_and_preserves_tm(self):
        self._write_sources("新原文", "译文")
        tm_data = {
            "chapters": {
                "chapter.md": [{"raw": "原文", "translated": "译文"}]
            },
            "source_provenance": {
                "chapter.md": self._source_provenance(
                    "原文",
                    "译文",
                    [self._mapping(1, [1], [1], "matched")],
                )
            },
        }

        exit_code, output, tm_path, original_tm = self._run_cli(tm_data)

        self.assertEqual(exit_code, 1)
        self.assertIn("STALE chapter.md", output)
        self.assertIn("MISMATCH chapter.md", output)
        self.assertEqual(tm_path.read_bytes(), original_tm)

    def test_cli_returns_two_for_unindexed_legacy_tm(self):
        tm_data = {"chapters": {"legacy.md": [{"raw": "原文", "translated": "译文"}]}}

        exit_code, output, tm_path, original_tm = self._run_cli(tm_data)

        self.assertEqual(exit_code, 2)
        self.assertIn("UNINDEXED legacy.md", output)
        self.assertEqual(tm_path.read_bytes(), original_tm)

    def test_cli_escapes_nonprintable_chapter_key_characters(self):
        chapter = (
            "synthetic"
            + chr(0x1B)
            + "]52;c;payload"
            + chr(0x07)
            + chr(0x9D)
            + "52;c;payload"
            + chr(0x9C)
            + "\r\n"
            + chr(0x202E)
            + ".md"
        )
        tm_data = {
            "chapters": {
                chapter: [{"raw": "synthetic", "translated": "synthetic"}]
            }
        }
        tm_path = self.root / "translation_memory.json"
        tm_path.write_text(json.dumps(tm_data), encoding="utf-8")
        original_tm = tm_path.read_bytes()
        expected_chapter = (
            r"synthetic\u001b]52;c;payload\u0007\u009d52;c;payload"
            r"\u009c\u000d\u000a\u202e.md"
        )
        output = io.StringIO()

        with (
            patch("pipeline.Config.load_config"),
            patch.object(Config, "TM_PATH", str(tm_path)),
            redirect_stdout(output),
        ):
            exit_code = main([])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 2)
        self.assertIn(f"UNINDEXED {expected_chapter}: No source provenance", rendered)
        self.assertEqual(len(rendered.splitlines()), 2)
        for control in (chr(0x1B), chr(0x07), chr(0x9D), chr(0x9C), "\r", chr(0x202E)):
            self.assertNotIn(control, rendered)
        self.assertEqual(tm_path.read_bytes(), original_tm)

    def test_cli_escapes_nonprintable_exception_text(self):
        error_text = "missing" + chr(0x1B) + "]52;c;payload" + chr(0x07)
        error_output = io.StringIO()

        with (
            patch(
                "pipeline.Config.load_config",
                side_effect=FileNotFoundError(error_text),
            ),
            redirect_stderr(error_output),
        ):
            exit_code = main([])

        rendered = error_output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn(r"\u001b]52;c;payload\u0007", rendered)
        self.assertNotIn(chr(0x1B), rendered)
        self.assertNotIn(chr(0x07), rendered)

    def test_cli_rejects_empty_test_workspace_without_loading_config(self):
        error_output = io.StringIO()

        with (
            patch.dict(os.environ, {"TEST_WORKSPACE_DIR": ""}, clear=True),
            patch("pipeline.Config.load_config") as load_config,
            redirect_stderr(error_output),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 1)
        load_config.assert_not_called()
        self.assertIn("TEST_WORKSPACE_DIR must be a non-empty path.", error_output.getvalue())

    def test_reports_incomplete_mapping_and_rejects_path_escape(self):
        raw_text = "原文"
        translation_text = "译文"
        (self.translation_dir / "chapter.md").write_text(
            translation_text, encoding="utf-8"
        )
        provenance = self._source_provenance(
            raw_text, translation_text, [self._mapping(1, [], [1], "partial")]
        )
        provenance["raw_file"] = "../outside.md"
        tm_data = {
            "chapters": {
                "chapter.md": [{"raw": raw_text, "translated": translation_text}]
            },
            "source_provenance": {"chapter.md": provenance},
        }

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual([finding["status"] for finding in findings], ["unverified"])
        self.assertIn("Could not safely read source files", findings[0]["detail"])

    def test_reports_reused_paragraph_mapping(self):
        raw_text = "同一段落"
        translation_text = "相同译文"
        raw_source = raw_text + "\n\n" + raw_text
        translation_source = translation_text + "\n\n" + translation_text
        self._write_sources(raw_source, translation_source)
        tm_data = {
            "chapters": {
                "chapter.md": [
                    {"raw": raw_text, "translated": translation_text},
                    {"raw": raw_text, "translated": translation_text},
                ]
            },
            "source_provenance": {
                "chapter.md": self._source_provenance(
                    raw_source,
                    translation_source,
                    [
                        self._mapping(1, [1], [1], "matched"),
                        self._mapping(2, [1], [2], "matched"),
                    ],
                )
            },
        }

        findings = audit_translation_memory(
            tm_data, str(self.raw_dir), str(self.translation_dir)
        )

        self.assertEqual(
            [finding["status"] for finding in findings], ["invalid"]
        )

    def test_source_schema_rejects_reused_paragraph_indices(self):
        provenance = self._source_provenance(
            "原文一\n\n原文二",
            "译文一\n\n译文二",
            [
                self._mapping(1, [1], [1], "matched"),
                self._mapping(2, [1], [2], "matched"),
            ],
        )

        with self.assertRaisesRegex(ValueError, "reuses or reorders raw"):
            validate_tm_source_provenance(provenance, pair_count=2)


if __name__ == "__main__":
    unittest.main()
