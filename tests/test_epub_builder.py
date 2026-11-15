import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from epub_builder import build_epub_candidate, get_pandoc_version
from scripts.build_epub_candidate import main as build_epub_cli
from source_ingestion import source_artifact_id


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
        self.source_root = self.root / "sources"
        self.output_root = self.root / "EPUB"
        self.input_root.mkdir()
        self.source_root.mkdir()
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
        self.source_manifest = {"schema_version": 1, "artifacts": []}
        self._add_source_version(
            "episode-1", "version-001", b"Synthetic normalized source one.\n"
        )
        self._add_source_version(
            "episode-2", "version-002", b"Synthetic normalized source two.\n"
        )
        self.catalog_path = self.input_root / "epub-catalog.json"
        self._write_catalog()
        self._write_source_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_catalog(self):
        self.catalog_path.write_text(
            json.dumps(self.catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def _add_source_version(self, episode_id, version_id, content):
        relative_path = f"{episode_id}-{version_id}.md"
        (self.source_root / relative_path).write_bytes(content)
        self.source_manifest["artifacts"].append(
            {
                "artifact_id": source_artifact_id(
                    "synthetic-work",
                    "normalized_source",
                    episode_id,
                ),
                "version_id": version_id,
                "kind": "normalized_source",
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "relative_path": relative_path,
                "parent_version_ids": [],
            }
        )

    def _write_source_manifest(self):
        (self.source_root / "source_manifest.json").write_text(
            json.dumps(self.source_manifest, ensure_ascii=False),
            encoding="utf-8",
        )

    def _build(self, max_output_bytes=4 * 1024 * 1024):
        return build_epub_candidate(
            input_root=self.input_root,
            catalog_relative_path="epub-catalog.json",
            source_root=self.source_root,
            source_manifest_relative_path="source_manifest.json",
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
            build_manifest["source_manifest"]["relative_path"],
            "source_manifest.json",
        )
        self.assertEqual(
            len(build_manifest["source_manifest"]["content_sha256"]),
            64,
        )
        self.assertTrue(build_manifest["pandoc"]["file_scope"])
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
        self.assertEqual(
            sorted(path.name for path in output_dir.iterdir()),
            ["build.json", "candidate.epub"],
        )

    def test_build_uses_validated_snapshots_and_terminates_pandoc_options(self):
        original_chapter = self.input_root / "chapter-1.md"
        option_named_chapter = self.input_root / "--lua-filter=payload.md"
        option_named_chapter.write_bytes(original_chapter.read_bytes())
        original_chapter.unlink()
        self.catalog["chapters"][0]["translation_path"] = option_named_chapter.name
        self._write_catalog()
        original_bytes = option_named_chapter.read_bytes()
        original_run = subprocess.run
        observed = {}

        def mutate_source_after_snapshot(command, **kwargs):
            if "--from=markdown" in command:
                separator = command.index("--")
                staged_inputs = command[separator + 1 :]
                self.assertEqual(len(staged_inputs), 2)
                self.assertEqual(
                    Path(staged_inputs[0]).name,
                    "--lua-filter=payload.md",
                )
                self.assertNotEqual(
                    Path(staged_inputs[0]).parent,
                    self.input_root,
                )
                self.assertTrue(
                    all(not value.startswith("--") for value in staged_inputs)
                )
                observed["option_separator"] = separator
                option_named_chapter.write_bytes(
                    b"# Chapter One\n\nChanged after validation.\n"
                )
            return original_run(command, **kwargs)

        with patch(
            "epub_builder.subprocess.run",
            side_effect=mutate_source_after_snapshot,
        ):
            self._build()

        output_dir = self.output_root / "synthetic-work" / "edition-001"
        build_manifest = json.loads(
            (output_dir / "build.json").read_text(encoding="utf-8")
        )
        self.assertIn("option_separator", observed)
        self.assertEqual(
            build_manifest["chapters"][0]["content_sha256"],
            hashlib.sha256(original_bytes).hexdigest(),
        )
        with zipfile.ZipFile(output_dir / "candidate.epub") as archive:
            xhtml = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xhtml")
            )
        self.assertIn("Synthetic translation one.", xhtml)
        self.assertNotIn("Changed after validation.", xhtml)

    def test_independent_chapters_scope_duplicate_footnotes_locally(self):
        (self.input_root / "chapter-1.md").write_text(
            "# Chapter One\n\nFirst note[^note].\n\n[^note]: First footnote.\n",
            encoding="utf-8",
        )
        (self.input_root / "chapter-2.md").write_text(
            "# Chapter Two\n\nSecond note[^note].\n\n[^note]: Second footnote.\n",
            encoding="utf-8",
        )

        self._build()

        output_dir = self.output_root / "synthetic-work" / "edition-001"
        manifest = json.loads((output_dir / "build.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["pandoc"]["file_scope"])
        with zipfile.ZipFile(output_dir / "candidate.epub") as archive:
            chapters = {
                name: archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xhtml")
            }
        first_chapter = next(
            content for content in chapters.values() if "First note" in content
        )
        second_chapter = next(
            content for content in chapters.values() if "Second note" in content
        )
        self.assertIn("First footnote.", first_chapter)
        self.assertNotIn("Second footnote.", first_chapter)
        self.assertIn("Second footnote.", second_chapter)
        self.assertNotIn("First footnote.", second_chapter)

    def test_cross_chapter_links_and_footnotes_keep_global_scope(self):
        (self.input_root / "chapter-1.md").write_text(
            "# Chapter One\n\n"
            "[Next chapter](chapter-2.md#part-two).\n\n"
            "Shared note[^shared].\n",
            encoding="utf-8",
        )
        (self.input_root / "chapter-2.md").write_text(
            "# Chapter Two\n\n"
            "## Part Two\n\n"
            "[^shared]: Shared cross-chapter footnote.\n",
            encoding="utf-8",
        )

        self._build()

        output_dir = self.output_root / "synthetic-work" / "edition-001"
        manifest = json.loads((output_dir / "build.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["pandoc"]["file_scope"])
        with zipfile.ZipFile(output_dir / "candidate.epub") as archive:
            xhtml = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xhtml")
            )
        self.assertIn("Shared cross-chapter footnote.", xhtml)
        self.assertIn("ch002.xhtml#part-two", xhtml)

    def test_cli_builds_candidate_without_echoing_chapter_text(self):
        output = StringIO()
        with redirect_stdout(output):
            status = build_epub_cli(
                [
                    "--input-root",
                    str(self.input_root),
                    "--catalog",
                    "epub-catalog.json",
                    "--source-root",
                    str(self.source_root),
                    "--source-manifest",
                    "source_manifest.json",
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

    def test_rejects_source_version_from_another_episode(self):
        self.catalog["chapters"][0]["source_version_id"] = "version-002"
        self._write_catalog()

        with self.assertRaisesRegex(ValueError, "does not match"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_stale_source_version(self):
        self._add_source_version(
            "episode-1",
            "version-003",
            b"Updated normalized source one.\n",
        )
        self._write_source_manifest()

        with self.assertRaisesRegex(ValueError, "stale"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_modified_source_artifact(self):
        (self.source_root / "episode-1-version-001.md").write_bytes(
            b"Changed after manifest.\n"
        )

        with self.assertRaisesRegex(ValueError, "hash does not match"):
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

    def test_rejects_reference_style_markdown_images(self):
        (self.input_root / "chapter-1.md").write_text(
            "# Chapter One\n\n![cover][cover]\n\n[cover]: cover.png\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Image markup"):
            self._build()

        self.assertFalse(self.output_root.exists())

    def test_rejects_embedded_media_and_html_resource_references(self):
        resource_markup = (
            '<audio src="https://example.invalid/audio.mp3"></audio>',
            '<video><source src="https://example.invalid/video.mp4"></video>',
            '<iframe src="https://example.invalid/frame"></iframe>',
            '<div style="background: url(https://example.invalid/image.png)"></div>',
        )
        for markup in resource_markup:
            with self.subTest(markup=markup):
                (self.input_root / "chapter-1.md").write_text(
                    f"# Chapter One\n\n{markup}\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "resource references"):
                    self._build()
                self.assertFalse(self.output_root.exists())

    def test_epub_cli_handles_pandoc_timeout(self):
        stdout = StringIO()
        stderr = StringIO()
        arguments = [
            "--input-root",
            str(self.input_root),
            "--catalog",
            "epub-catalog.json",
            "--source-root",
            str(self.source_root),
            "--output-root",
            str(self.output_root),
            "--pandoc",
            self.pandoc,
            "--max-chapter-bytes",
            "1024",
            "--max-total-bytes",
            "2048",
            "--max-output-bytes",
            "4096",
        ]
        with (
            patch(
                "scripts.build_epub_candidate.build_epub_candidate",
                side_effect=subprocess.TimeoutExpired(self.pandoc, 1),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = build_epub_cli(arguments)

        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "ERROR: TimeoutExpired\n")

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
