import json
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from epub_builder import build_epub_candidate, get_pandoc_version
from scripts.build_epub_candidate import main as build_epub_cli


class EpubCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pandoc = shutil.which("pandoc")
        if not cls.pandoc:
            raise unittest.SkipTest("Pandoc is not installed.")
        cls.pandoc_version = get_pandoc_version(cls.pandoc)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input_root = self.root / "translations"
        self.output_root = self.root / "EPUB"
        self.input_root.mkdir()
        (self.input_root / "chapter-1.md").write_bytes(
            b"# Chapter One\n\nSynthetic translation one.\n"
        )
        (self.input_root / "chapter-2.md").write_bytes(
            b"# Chapter Two\n\nSynthetic translation two.\n"
        )
        self.catalog = {
            "schema_version": 1,
            "work_id": "synthetic-work",
            "build_id": "edition-001",
            "expected_pandoc_version": self.pandoc_version,
            "title": "Synthetic Novel",
            "author": "Synthetic Author",
            "language": "zh-CN",
            "identifier": "urn:synthetic:novel",
            "chapters": [
                {
                    "episode_id": "episode-1",
                    "position": 1,
                    "title": "Chapter One",
                    "translation_path": "chapter-1.md",
                    "source_version_id": "version-001",
                },
                {
                    "episode_id": "episode-2",
                    "position": 2,
                    "title": "Chapter Two",
                    "translation_path": "chapter-2.md",
                    "source_version_id": "version-002",
                },
            ],
        }
        self.catalog_path = self.input_root / "epub-catalog.json"
        self._write_catalog()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_catalog(self):
        self.catalog_path.write_text(
            json.dumps(self.catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def _build(self, max_output_bytes=4 * 1024 * 1024):
        return build_epub_candidate(
            input_root=self.input_root,
            catalog_relative_path="epub-catalog.json",
            output_root=self.output_root,
            max_chapter_bytes=1024 * 1024,
            max_total_bytes=2 * 1024 * 1024,
            max_output_bytes=max_output_bytes,
            pandoc_executable=self.pandoc,
        )

    def test_builds_candidate_with_source_hashes_and_preserves_markdown(self):
        before = {
            path.name: path.read_bytes()
            for path in (self.input_root / "chapter-1.md", self.input_root / "chapter-2.md")
        }

        result = self._build()

        output_dir = self.output_root / "synthetic-work" / "edition-001"
        artifact = output_dir / "candidate.epub"
        build_manifest = json.loads((output_dir / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["chapter_count"], 2)
        self.assertEqual(build_manifest["artifact_status"], "candidate")
        self.assertEqual(build_manifest["quality_gate_status"], "not_evaluated")
        self.assertEqual(build_manifest["coverage_scope"], "explicit_episode_selection")
        self.assertEqual(
            [chapter["episode_id"] for chapter in build_manifest["chapters"]],
            ["episode-1", "episode-2"],
        )
        self.assertEqual(
            build_manifest["chapters"][0]["source_version_id"],
            "version-001",
        )
        self.assertEqual(len(build_manifest["chapters"][0]["content_sha256"]), 64)
        self.assertEqual(
            {
                name: (self.input_root / name).read_bytes()
                for name in before
            },
            before,
        )
        with zipfile.ZipFile(artifact) as archive:
            self.assertIsNone(archive.testzip())
            content = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xhtml")
            )
        self.assertIn("Synthetic translation one.", content)
        self.assertIn("Synthetic translation two.", content)
        self.assertLess(
            content.index("Synthetic translation one."),
            content.index("Synthetic translation two."),
        )

    def test_cli_builds_candidate_without_echoing_chapter_text(self):
        output = StringIO()
        with redirect_stdout(output):
            status = build_epub_cli(
                [
                    "--input-root",
                    str(self.input_root),
                    "--catalog",
                    "epub-catalog.json",
                    "--output-root",
                    str(self.output_root),
                    "--pandoc",
                    self.pandoc,
                    "--max-chapter-bytes",
                    str(1024 * 1024),
                    "--max-total-bytes",
                    str(2 * 1024 * 1024),
                    "--max-output-bytes",
                    str(4 * 1024 * 1024),
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "candidate")
        self.assertNotIn("Synthetic translation", output.getvalue())

    def test_rejects_existing_output_without_overwriting_it(self):
        self._build()
        output_dir = self.output_root / "synthetic-work" / "edition-001"
        original = (output_dir / "build.json").read_bytes()

        with self.assertRaises(FileExistsError):
            self._build()

        self.assertEqual((output_dir / "build.json").read_bytes(), original)

    def test_rejects_pandoc_version_mismatch_before_creating_output(self):
        self.catalog["expected_pandoc_version"] = "0.0.0"
        self._write_catalog()

        with self.assertRaisesRegex(ValueError, "does not match"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_chapter_title_and_catalog_disagreement(self):
        self.catalog["chapters"][0]["title"] = "Wrong Title"
        self._write_catalog()

        with self.assertRaisesRegex(ValueError, "H1 title"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_image_markup_without_copying_unbounded_assets(self):
        chapter = self.input_root / "chapter-1.md"
        chapter.write_text(
            "# Chapter One\n\n![cover](large-image.png)\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Image markup"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_oversized_generated_epub_without_publishing_it(self):
        with self.assertRaisesRegex(ValueError, "output byte limit"):
            self._build(max_output_bytes=1)

        self.assertFalse(
            (self.output_root / "synthetic-work" / "edition-001").exists()
        )

    def test_rejects_duplicate_catalog_fields(self):
        self.catalog_path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self._build()


if __name__ == "__main__":
    unittest.main()
