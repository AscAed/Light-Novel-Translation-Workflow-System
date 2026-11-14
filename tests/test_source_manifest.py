import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from source_manifest import (
    append_artifact,
    load_manifest,
    new_manifest,
    validate_manifest,
    verify_manifest_files,
)
from scripts.validate_source_manifest import main as validate_source_manifest_main


class SourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manifest_path = Path(self.temp_dir.name) / "source_manifest.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _artifact(
        self,
        *,
        artifact_id="work-1/episode-1",
        version_id="version-1",
        kind="raw_source",
        content=b"synthetic fixture",
        relative_path="raw/episode-1.md",
        parent_version_ids=None,
    ):
        return {
            "artifact_id": artifact_id,
            "version_id": version_id,
            "kind": kind,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "relative_path": relative_path,
            "parent_version_ids": parent_version_ids or [],
        }

    def test_append_round_trips_versions_and_lineage(self):
        first = self._artifact()
        append_artifact(self.manifest_path, first)
        second = self._artifact(
            artifact_id="work-1/episode-1/normalized",
            version_id="version-2",
            kind="normalized_source",
            content=b"normalized synthetic fixture",
            relative_path="normalized/episode-1.md",
            parent_version_ids=["version-1"],
        )

        actual = append_artifact(self.manifest_path, second)

        self.assertEqual(actual["schema_version"], 1)
        self.assertEqual(len(actual["artifacts"]), 2)
        self.assertEqual(load_manifest(self.manifest_path), actual)

    def test_append_rejects_duplicate_version_without_changing_file(self):
        artifact = self._artifact()
        append_artifact(self.manifest_path, artifact)
        before = self.manifest_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "repeats a version_id"):
            append_artifact(self.manifest_path, artifact)

        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_verifies_file_hash_under_explicit_root(self):
        root = Path(self.temp_dir.name) / "project"
        source_dir = root / "raw"
        source_dir.mkdir(parents=True)
        content = b"synthetic source bytes\n"
        (source_dir / "episode-1.md").write_bytes(content)
        manifest = new_manifest()
        manifest["artifacts"] = [
            self._artifact(content=content, relative_path="raw/episode-1.md")
        ]

        self.assertEqual(verify_manifest_files(root, manifest), 1)

    def test_rejects_file_hash_mismatch(self):
        root = Path(self.temp_dir.name) / "project"
        source_dir = root / "raw"
        source_dir.mkdir(parents=True)
        (source_dir / "episode-1.md").write_bytes(b"different synthetic bytes")
        manifest = new_manifest()
        manifest["artifacts"] = [
            self._artifact(relative_path="raw/episode-1.md")
        ]

        with self.assertRaisesRegex(ValueError, "hash does not match"):
            verify_manifest_files(root, manifest)

    def test_skips_metadata_without_a_file_path(self):
        artifact = self._artifact(
            artifact_id="work-1",
            kind="work",
            relative_path=None,
        )

        self.assertEqual(
            verify_manifest_files(
                self.temp_dir.name,
                {"schema_version": 1, "artifacts": [artifact]},
            ),
            0,
        )

    def test_rejects_unavailable_or_unsafe_manifest_file(self):
        root = Path(self.temp_dir.name) / "project"
        root.mkdir()
        manifest = new_manifest()
        manifest["artifacts"] = [
            self._artifact(relative_path="../outside.md")
        ]

        with self.assertRaisesRegex(ValueError, "invalid relative_path"):
            verify_manifest_files(root, manifest)

        manifest["artifacts"] = [
            self._artifact(relative_path="missing.md")
        ]
        with self.assertRaisesRegex(ValueError, "could not be verified"):
            verify_manifest_files(root, manifest)

    def test_read_only_cli_reports_verified_file_count(self):
        root = Path(self.temp_dir.name) / "project"
        source_dir = root / "raw"
        source_dir.mkdir(parents=True)
        content = b"synthetic source"
        source_path = source_dir / "episode-1.md"
        source_path.write_bytes(content)
        manifest = {"schema_version": 1, "artifacts": [self._artifact(content=content)]}
        manifest_path = root / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        source_before = source_path.read_bytes()
        manifest_before = manifest_path.read_bytes()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = validate_source_manifest_main(
                ["--root", str(root), "--manifest", "source_manifest.json"]
            )

        self.assertEqual(result, 0)
        self.assertIn("files_verified=1", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(source_path.read_bytes(), source_before)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)

    def test_read_only_cli_fails_on_hash_mismatch_without_printing_content(self):
        root = Path(self.temp_dir.name) / "project"
        source_dir = root / "raw"
        source_dir.mkdir(parents=True)
        (source_dir / "episode-1.md").write_bytes(b"synthetic private text")
        manifest = {
            "schema_version": 1,
            "artifacts": [self._artifact(content=b"expected synthetic text")],
        }
        (root / "source_manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = validate_source_manifest_main(
                ["--root", str(root), "--manifest", "source_manifest.json"]
            )

        self.assertEqual(result, 1)
        self.assertIn("hash does not match", stderr.getvalue())
        self.assertNotIn("synthetic private text", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_rejects_missing_parent(self):
        manifest = new_manifest()
        manifest["artifacts"] = [
            self._artifact(parent_version_ids=["missing-version"])
        ]

        with self.assertRaisesRegex(ValueError, "missing parent"):
            validate_manifest(manifest)

    def test_rejects_parent_cycle(self):
        first = self._artifact(
            version_id="version-1",
            relative_path="raw/1.md",
            parent_version_ids=["version-2"],
        )
        second = self._artifact(
            version_id="version-2",
            relative_path="raw/2.md",
            parent_version_ids=["version-1"],
        )
        manifest = {"schema_version": 1, "artifacts": [first, second]}

        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_manifest(manifest)

    def test_validates_deep_acyclic_parent_chain_without_recursion(self):
        artifacts = [
            self._artifact(
                artifact_id=f"work-1/episode-{index}",
                version_id=f"version-{index}",
                relative_path=None,
                parent_version_ids=[f"version-{index - 1}"] if index else [],
            )
            for index in range(1200)
        ]

        validate_manifest({"schema_version": 1, "artifacts": artifacts})

    def test_rejects_unsupported_or_boolean_schema_version(self):
        for version in (0, True, "1"):
            with self.subTest(version=version):
                manifest = new_manifest()
                manifest["schema_version"] = version
                with self.assertRaisesRegex(ValueError, "schema_version"):
                    validate_manifest(manifest)

    def test_rejects_unknown_fields(self):
        manifest = new_manifest()
        manifest["unreviewed"] = True

        with self.assertRaisesRegex(ValueError, "only schema_version"):
            validate_manifest(manifest)

    def test_rejects_invalid_hash_kind_and_case_insensitive_duplicate_path(self):
        artifact = self._artifact()
        artifact["content_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            validate_manifest({"schema_version": 1, "artifacts": [artifact]})

        artifact = self._artifact()
        artifact["kind"] = []
        with self.assertRaisesRegex(ValueError, "unsupported kind"):
            validate_manifest({"schema_version": 1, "artifacts": [artifact]})

        first = self._artifact(
            version_id="version-1",
            relative_path="raw/Chapter.md",
        )
        second = self._artifact(
            version_id="version-2",
            relative_path="raw/chapter.md",
        )
        with self.assertRaisesRegex(ValueError, "repeats a relative_path"):
            validate_manifest({"schema_version": 1, "artifacts": [first, second]})

    def test_rejects_unsafe_relative_paths(self):
        for path in ("../outside.md", "/absolute.md", "C:/absolute.md", "raw\\chapter.md"):
            with self.subTest(path=path):
                manifest = new_manifest()
                manifest["artifacts"] = [self._artifact(relative_path=path)]
                with self.assertRaisesRegex(ValueError, "relative_path"):
                    validate_manifest(manifest)

    def test_rejects_mixed_kinds_for_same_artifact_id(self):
        first = self._artifact(version_id="version-1", relative_path="raw/1.md")
        second = self._artifact(
            version_id="version-2",
            kind="translation",
            relative_path="translated/1.md",
        )

        with self.assertRaisesRegex(ValueError, "changes the kind"):
            validate_manifest({"schema_version": 1, "artifacts": [first, second]})

    def test_rejects_duplicate_json_fields(self):
        self.manifest_path.write_text(
            '{"schema_version":1,"schema_version":1,"artifacts":[]}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
            load_manifest(self.manifest_path)

    def test_rejects_invalid_json(self):
        self.manifest_path.write_text("{not-json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "valid JSON"):
            load_manifest(self.manifest_path)


if __name__ == "__main__":
    unittest.main()
