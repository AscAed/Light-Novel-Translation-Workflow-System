import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.ingest_local_sources import main
from source_manifest import load_manifest, verify_manifest_files


class LocalSourceIngestionCLITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.output_root = self.root / "archive"
        self.source_root.mkdir()
        self.output_root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_catalog(self, episodes):
        catalog = {
            "schema_version": 1,
            "work_id": "synthetic-work",
            "episodes": episodes,
        }
        (self.source_root / "catalog.json").write_text(
            json.dumps(catalog),
            encoding="utf-8",
        )

    def _run_cli(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(self.output_root),
                    "--page-size",
                    "1",
                ]
            )
        return result, stdout.getvalue(), stderr.getvalue()

    def test_cli_archives_only_explicit_files_without_modifying_or_echoing_them(self):
        first = self.source_root / "volume-2" / "chapter-10.md"
        second = self.source_root / "chapter-2.md"
        first.parent.mkdir()
        first.write_bytes(b"synthetic source text ten")
        second.write_bytes(b"synthetic source text two")
        source_bytes = (first.read_bytes(), second.read_bytes())
        self._write_catalog(
            [
                {
                    "episode_id": "episode-10",
                    "title": "Chapter Ten",
                    "position": 10,
                    "relative_path": "volume-2/chapter-10.md",
                    "source_ref": "https://example.invalid/works/test/episodes/10",
                },
                {
                    "episode_id": "episode-2",
                    "title": "Chapter Two",
                    "position": 2,
                    "relative_path": "chapter-2.md",
                },
            ]
        )

        result, stdout, stderr = self._run_cli()

        self.assertEqual(result, 0)
        report = json.loads(stdout)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_count"], 2)
        self.assertEqual(stderr, "")
        self.assertNotIn("synthetic source text", stdout)
        self.assertEqual((first.read_bytes(), second.read_bytes()), source_bytes)
        manifest = load_manifest(self.output_root / "source_manifest.json")
        self.assertEqual(verify_manifest_files(self.output_root, manifest), 4)
        metadata_artifact = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "episode"
            and json.loads(
                (self.output_root / artifact["relative_path"]).read_text(
                    encoding="utf-8"
                )
            )["episode_id"]
            == "episode-10"
        )
        metadata = json.loads(
            (self.output_root / metadata_artifact["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            metadata["source_ref"],
            "https://example.invalid/works/test/episodes/10",
        )

    def test_cli_rejects_catalog_paths_that_escape_the_source_root(self):
        outside = self.root / "outside.md"
        outside.write_bytes(b"synthetic private text")
        self._write_catalog(
            [
                {
                    "episode_id": "episode-1",
                    "title": "Chapter One",
                    "position": 1,
                    "relative_path": "../outside.md",
                }
            ]
        )

        result, stdout, stderr = self._run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "ERROR: ValueError\n")
        self.assertFalse((self.output_root / "source_manifest.json").exists())
        self.assertEqual(outside.read_bytes(), b"synthetic private text")

    def test_cli_rejects_duplicate_catalog_json_fields(self):
        (self.source_root / "catalog.json").write_text(
            '{"schema_version":1,"schema_version":1,"work_id":"synthetic-work","episodes":[]}',
            encoding="utf-8",
        )

        result, stdout, stderr = self._run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "ERROR: ValueError\n")


if __name__ == "__main__":
    unittest.main()
