import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.validate_knowledge_provenance import (
    audit_knowledge_provenance,
    main,
)
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from utils import read_relative_text


class KnowledgeProvenanceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.archive_root = self.root / "archive"
        self.knowledge_root = self.root / "Knowledge"
        self.source_root.mkdir()
        self.archive_root.mkdir()
        self.knowledge_root.mkdir()
        self.source_file = self.source_root / "chapter.txt"
        self.source_bytes = (
            "Source paragraph one.\r\n\r\nSource paragraph two.\r\n"
        ).encode("utf-8")
        self.source_file.write_bytes(self.source_bytes)
        self.artifact = self._collect_and_materialize()
        self.provenance = self._provenance(self.artifact)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _collect_and_materialize(self, checkpoint="checkpoint.json"):
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
            checkpoint_relative_path=checkpoint,
        )
        return materialize_episode_markdown(
            self.archive_root,
            work_id="synthetic-work",
            episode_id="episode-1",
        )

    def _provenance(self, artifact):
        source_text = read_relative_text(
            str(self.archive_root), artifact["relative_path"]
        )
        return {
            "schema_version": 1,
            "artifact_status": "complete",
            "source_files": [
                {
                    "filename": artifact["relative_path"],
                    "source_sha256": hashlib.sha256(
                        source_text.encode("utf-8")
                    ).hexdigest(),
                    "source_version_id": artifact["version_id"],
                }
            ],
        }

    def test_verifies_latest_byte_preserving_crlf_source(self):
        findings = audit_knowledge_provenance(
            self.provenance,
            str(self.archive_root),
            "source_manifest.json",
        )

        self.assertEqual(
            [item["status"] for item in findings],
            ["verified"],
            findings,
        )
        self.assertEqual(
            (self.archive_root / self.artifact["relative_path"]).read_bytes(),
            self.source_bytes,
        )

    def test_project_audit_reads_ai_mirror_not_archive_body(self):
        ai_root = self.root / "RAWs_AI"
        ai_root.mkdir()
        ai_path = ai_root / "episode.md"
        ai_path.write_bytes(
            (self.archive_root / self.artifact["relative_path"]).read_bytes()
        )
        source_sha256 = hashlib.sha256(ai_path.read_bytes()).hexdigest()

        with patch(
            "source_manifest._verify_artifact_file",
            side_effect=AssertionError("archive body read during translation"),
        ):
            findings = audit_knowledge_provenance(
                self.provenance,
                str(self.archive_root),
                "source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map={
                    self.artifact["relative_path"]: {
                        "source_version_id": self.artifact["version_id"],
                        "source_input_file": "episode.md",
                        "source_sha256": source_sha256,
                    }
                },
            )

        self.assertEqual(
            [item["status"] for item in findings],
            ["verified"],
            findings,
        )

    def test_project_audit_binds_ai_bytes_separately_from_archive_bytes(self):
        ai_root = self.root / "RAWs_AI"
        ai_root.mkdir()
        ai_path = ai_root / "episode.md"
        ai_text = "Source paragraph one cleaned.\n\nSource paragraph two.\n"
        ai_path.write_text(ai_text, encoding="utf-8")
        ai_bytes_digest = hashlib.sha256(ai_path.read_bytes()).hexdigest()
        ai_text_digest = hashlib.sha256(
            ai_text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        ).hexdigest()
        provenance = json.loads(json.dumps(self.provenance))
        provenance["source_files"][0]["source_input_file"] = "episode.md"
        provenance["source_files"][0]["source_sha256"] = ai_text_digest

        with patch(
            "source_manifest._verify_artifact_file",
            side_effect=AssertionError("archive body read during AI edition audit"),
        ):
            findings = audit_knowledge_provenance(
                provenance,
                str(self.archive_root),
                "source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map={
                    self.artifact["relative_path"]: {
                        "source_version_id": self.artifact["version_id"],
                        "source_input_file": "episode.md",
                        "source_sha256": ai_bytes_digest,
                    }
                },
            )

        self.assertEqual(
            [item["status"] for item in findings],
            ["verified"],
            findings,
        )

    def test_reports_newer_source_version_as_stale(self):
        self.source_file.write_bytes(b"Updated source.\r\n")
        latest = self._collect_and_materialize("updated-checkpoint.json")
        self.assertEqual(latest["artifact_id"], self.artifact["artifact_id"])

        findings = audit_knowledge_provenance(
            self.provenance,
            str(self.archive_root),
            "source_manifest.json",
        )

        self.assertEqual([item["status"] for item in findings], ["stale"])

    def test_reports_raw_update_before_materialization_as_stale(self):
        self.source_file.write_bytes(b"Updated source before normalization.\r\n")
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

        findings = audit_knowledge_provenance(
            self.provenance,
            str(self.archive_root),
            "source_manifest.json",
        )

        self.assertEqual([item["status"] for item in findings], ["stale"])
        self.assertIn("older raw source", findings[0]["detail"])

    def test_reports_tampered_latest_source_as_invalid(self):
        (self.archive_root / self.artifact["relative_path"]).write_bytes(b"tampered")

        findings = audit_knowledge_provenance(
            self.provenance,
            str(self.archive_root),
            "source_manifest.json",
        )

        self.assertEqual([item["status"] for item in findings], ["invalid"])

    def test_reports_missing_source_version_as_unverified(self):
        legacy = json.loads(json.dumps(self.provenance))
        del legacy["source_files"][0]["source_version_id"]

        findings = audit_knowledge_provenance(
            legacy,
            str(self.archive_root),
            "source_manifest.json",
        )

        self.assertEqual([item["status"] for item in findings], ["unverified"])

    def test_cli_reports_status_without_source_text(self):
        provenance_path = self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json"
        provenance_path.write_text(
            json.dumps(self.provenance),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--root",
                    str(self.archive_root),
                    "--manifest",
                    "source_manifest.json",
                    "--provenance",
                    str(provenance_path),
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("VERIFIED source[1]", stdout.getvalue())
        self.assertNotIn("Source paragraph one.", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            provenance_path.read_text(encoding="utf-8"),
            json.dumps(self.provenance),
        )


if __name__ == "__main__":
    unittest.main()
