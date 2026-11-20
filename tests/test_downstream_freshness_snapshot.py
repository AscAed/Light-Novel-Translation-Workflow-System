import hashlib
import io
import json
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import snapshot_downstream_freshness
from scripts.snapshot_downstream_freshness import (
    main,
    persist_downstream_freshness_snapshot,
)
from source_manifest import append_artifact
from story_summary_review import (
    create_summary_review_template,
    publish_reviewed_summary,
)


class DownstreamFreshnessSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "raw"
        self.translation_root = self.root / "translated"
        self.source_root.mkdir()
        self.translation_root.mkdir()
        self.raw_text = "原文段落。"
        self.translation_text = "译文段落。"
        (self.source_root / "chapter.md").write_text(
            self.raw_text, encoding="utf-8"
        )
        (self.translation_root / "chapter.md").write_text(
            self.translation_text, encoding="utf-8"
        )
        self.manifest_path = self.source_root / "source_manifest.json"
        self._write_manifest_lineage()
        self.tm_path = self.root / "translation_memory.json"
        self.knowledge_path = self.root / "KNOWLEDGE_PROVENANCE_draft.json"
        self.tm_data = self._tm_data()
        self.knowledge_data = self._knowledge_data()
        self.tm_path.write_text(
            json.dumps(self.tm_data, ensure_ascii=False), encoding="utf-8"
        )
        self.knowledge_path.write_text(
            json.dumps(self.knowledge_data, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_manifest_lineage(self):
        raw_source_path = self.source_root / "original.txt"
        raw_source_path.write_text("Raw source.", encoding="utf-8")
        raw_digest = hashlib.sha256(raw_source_path.read_bytes()).hexdigest()
        normalized_digest = hashlib.sha256(
            self.raw_text.encode("utf-8")
        ).hexdigest()
        append_artifact(
            self.manifest_path,
            {
                "artifact_id": "episode-1-raw",
                "version_id": "raw-v1",
                "kind": "raw_source",
                "content_sha256": raw_digest,
                "relative_path": "original.txt",
                "parent_version_ids": [],
            },
        )
        append_artifact(
            self.manifest_path,
            {
                "artifact_id": "episode-1-normalized",
                "version_id": "normalized-v1",
                "kind": "normalized_source",
                "content_sha256": normalized_digest,
                "relative_path": "chapter.md",
                "parent_version_ids": ["raw-v1"],
            },
        )

    def _tm_data(self):
        return {
            "chapters": {
                "episode-1": [
                    {"raw": self.raw_text, "translated": self.translation_text}
                ]
            },
            "source_provenance": {
                "episode-1": {
                    "schema_version": 1,
                    "producer": "synthetic-test",
                    "raw_file": "chapter.md",
                    "raw_sha256": hashlib.sha256(
                        self.raw_text.encode("utf-8")
                    ).hexdigest(),
                    "translation_file": "chapter.md",
                    "translation_sha256": hashlib.sha256(
                        self.translation_text.encode("utf-8")
                    ).hexdigest(),
                    "source_version_id": "normalized-v1",
                    "pair_mappings": [
                        {
                            "pair_index": 1,
                            "raw_paragraph_indices": [1],
                            "translation_paragraph_indices": [1],
                            "trace_status": "matched",
                        }
                    ],
                }
            },
        }

    def _knowledge_data(self):
        return {
            "schema_version": 1,
            "artifact_status": "complete",
            "source_files": [
                {
                    "filename": "chapter.md",
                    "source_sha256": hashlib.sha256(
                        self.raw_text.encode("utf-8")
                    ).hexdigest(),
                    "source_version_id": "normalized-v1",
                }
            ],
        }

    def _create_reviewed_summary(self) -> Path:
        knowledge_root = self.root / "summary-knowledge"
        knowledge_root.mkdir()
        summary_path = knowledge_root / "STORY_SUMMARY_draft.md"
        provenance_path = knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json"
        receipt_path = knowledge_root / "summary-review.json"
        reviewed_path = knowledge_root / "STORY_SUMMARY_reviewed.json"
        summary_path.write_text(
            "# Synthetic full-book summary.\n",
            encoding="utf-8",
        )
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_status": "complete",
                    "source_files": [
                        {
                            "filename": "chapter.md",
                            "source_sha256": hashlib.sha256(
                                self.raw_text.encode("utf-8")
                            ).hexdigest(),
                            "source_version_id": "normalized-v1",
                        }
                    ],
                    "summary_source_chapters": ["chapter.md"],
                    "input_coverage": {
                        "scope": "all_configured_chapters",
                        "complete_for_configured_chapters": True,
                        "configured_chapter_count": 1,
                        "included_chapter_count": 1,
                        "input_characters": len(self.raw_text),
                        "input_character_limit": 1000,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        create_summary_review_template(str(knowledge_root), receipt_path.name)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(
            {
                "reviewer": {
                    "provider_id": "synthetic-reviewer",
                    "model_id": "fixture-v1",
                    "review_id": "summary-review-001",
                },
                "reviewed_at_utc": "2026-11-15T00:00:00Z",
                "decision": "approved",
                "rationale": "Synthetic full-book summary approval.",
            }
        )
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False),
            encoding="utf-8",
        )
        publish_reviewed_summary(
            str(knowledge_root),
            str(self.source_root),
            "source_manifest.json",
            receipt_path.name,
            reviewed_path.name,
        )
        return reviewed_path

    def _run_cli(
        self,
        output_path: Path,
        *,
        knowledge: bool = True,
        story_summary: Path | None = None,
        expected_sources: list[dict] | None = None,
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = [
            "--source-root",
            str(self.source_root),
            "--translation-root",
            str(self.translation_root),
            "--manifest",
            "source_manifest.json",
            "--tm",
            str(self.tm_path),
        ]
        if knowledge:
            args.extend(["--knowledge-provenance", str(self.knowledge_path)])
        if story_summary is not None:
            args.extend(
                [
                    "--story-summary",
                    str(story_summary),
                    "--project",
                    "synthetic-project",
                ]
            )
        args.extend(["--output", str(output_path)])
        source_map_patch = (
            patch(
                "scripts.snapshot_downstream_freshness._current_expected_sources",
                return_value=expected_sources,
            )
            if story_summary is not None
            else nullcontext()
        )
        source_input_config_patch = (
            patch("pipeline.Config.AI_EDITION_ROOT", None)
            if story_summary is not None
            else nullcontext()
        )
        with (
            source_map_patch,
            source_input_config_patch,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(args)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_writes_manifest_bound_snapshot_for_verified_consumers(self):
        output_path = self.root / "freshness.json"
        original_tm = self.tm_path.read_bytes()
        original_knowledge = self.knowledge_path.read_bytes()

        result, stdout, stderr = self._run_cli(output_path)

        snapshot = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("translation_memory: verified=1", stdout)
        self.assertIn("knowledge_provenance: verified=1", stdout)
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(
            snapshot["source_manifest"]["sha256"],
            hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            snapshot["consumers"]["translation_memory"]["findings"][0]["status"],
            "verified",
        )
        self.assertEqual(
            snapshot["consumers"]["knowledge_provenance"]["findings"][0]["status"],
            "verified",
        )
        self.assertNotIn(self.raw_text, output_path.read_text(encoding="utf-8"))
        self.assertNotIn(self.translation_text, output_path.read_text(encoding="utf-8"))
        self.assertEqual(self.tm_path.read_bytes(), original_tm)
        self.assertEqual(self.knowledge_path.read_bytes(), original_knowledge)

    def test_manifest_bound_tm_without_source_version_is_persisted_unverified(self):
        provenance = self.tm_data["source_provenance"]["episode-1"]
        del provenance["source_version_id"]
        self.tm_path.write_text(
            json.dumps(self.tm_data, ensure_ascii=False),
            encoding="utf-8",
        )
        original_tm = self.tm_path.read_bytes()
        output_path = self.root / "freshness.json"

        result, stdout, stderr = self._run_cli(
            output_path,
            knowledge=False,
        )

        snapshot = json.loads(output_path.read_text(encoding="utf-8"))
        finding = snapshot["consumers"]["translation_memory"]["findings"][0]
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("unverified=1", stdout)
        self.assertEqual(finding["status"], "unverified")
        self.assertIn("No source_version_id", finding["detail"])
        self.assertEqual(self.tm_path.read_bytes(), original_tm)

    def test_persists_stale_findings_without_overwriting_snapshot(self):
        output_path = self.root / "freshness.json"
        output_path.write_text("preserve this", encoding="utf-8")
        (self.source_root / "chapter.md").write_text("更新后的原文。", encoding="utf-8")

        result, _, stderr = self._run_cli(output_path)

        self.assertEqual(result, 1)
        self.assertIn("File exists", stderr)
        self.assertEqual(output_path.read_text(encoding="utf-8"), "preserve this")

    def test_snapshot_records_stale_tm_and_knowledge_statuses(self):
        (self.source_root / "chapter.md").write_text("更新后的原文。", encoding="utf-8")
        output_path = self.root / "freshness.json"

        result, stdout, stderr = self._run_cli(output_path)

        snapshot_text = output_path.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("stale=1", stdout)
        tm_statuses = {
            item["status"]
            for item in snapshot["consumers"]["translation_memory"]["findings"]
        }
        knowledge_statuses = {
            item["status"]
            for item in snapshot["consumers"]["knowledge_provenance"]["findings"]
        }
        self.assertIn("stale", tm_statuses)
        self.assertIn("mismatch", tm_statuses)
        self.assertIn("invalid", knowledge_statuses)
        self.assertNotIn(self.raw_text, snapshot_text)
        self.assertNotIn(self.translation_text, snapshot_text)

    def test_can_snapshot_tm_without_knowledge_provenance(self):
        output_path = self.root / "freshness.json"

        result, stdout, stderr = self._run_cli(output_path, knowledge=False)

        snapshot = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("translation_memory: verified=1", stdout)
        self.assertEqual(
            list(snapshot["consumers"]),
            ["translation_memory"],
        )

    def test_content_addressed_persistence_is_idempotent_and_append_only(self):
        first = {
            "schema_version": 2,
            "snapshot_kind": "downstream_freshness",
            "generated_at_utc": "2026-11-17T00:00:00Z",
            "source_manifest": {"relative_path": "source_manifest.json"},
            "consumers": {
                "translation_memory": {
                    "summary": {"verified": 1},
                    "findings": [],
                }
            },
        }

        first_result = persist_downstream_freshness_snapshot(
            first, str(self.source_root)
        )
        first_path = self.source_root / first_result["path"]
        first_bytes = first_path.read_bytes()
        retry = {
            **first,
            "generated_at_utc": "2026-11-17T00:01:00Z",
        }
        retry_result = persist_downstream_freshness_snapshot(
            retry, str(self.source_root)
        )

        self.assertTrue(first_result["created"])
        self.assertFalse(retry_result["created"])
        self.assertEqual(retry_result["snapshot_id"], first_result["snapshot_id"])
        self.assertEqual(first_path.read_bytes(), first_bytes)

        changed = {
            **retry,
            "consumers": {
                "translation_memory": {
                    "summary": {"stale": 1},
                    "findings": [],
                }
            },
        }
        changed_result = persist_downstream_freshness_snapshot(
            changed, str(self.source_root)
        )
        self.assertTrue(changed_result["created"])
        self.assertNotEqual(changed_result["snapshot_id"], first_result["snapshot_id"])

    def test_corrupt_content_addressed_snapshot_is_preserved_and_rejected(self):
        snapshot = {
            "schema_version": 2,
            "snapshot_kind": "downstream_freshness",
            "generated_at_utc": "2026-11-17T00:00:00Z",
            "source_manifest": {"relative_path": "source_manifest.json"},
            "consumers": {},
        }
        persisted = persist_downstream_freshness_snapshot(
            snapshot, str(self.source_root)
        )
        path = self.source_root / persisted["path"]
        path.write_text("[]", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "content address"):
            persist_downstream_freshness_snapshot(
                snapshot, str(self.source_root)
            )

        self.assertEqual(path.read_text(encoding="utf-8"), "[]")

    def test_snapshots_verified_full_book_summary_without_its_content(self):
        output_path = self.root / "freshness.json"
        summary_path = self._create_reviewed_summary()

        result, stdout, stderr = self._run_cli(
            output_path,
            knowledge=False,
            story_summary=summary_path,
            expected_sources=[
                {
                    "filename": "chapter.md",
                    "source_version_id": "normalized-v1",
                }
            ],
        )

        snapshot_text = output_path.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)
        summary_consumer = snapshot["consumers"]["reviewed_story_summary"]
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("reviewed_story_summary: verified=1", stdout)
        self.assertEqual(summary_consumer["findings"][0]["status"], "verified")
        self.assertEqual(
            summary_consumer["sha256"],
            hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        )
        self.assertNotIn("Synthetic full-book summary.", snapshot_text)

    def test_snapshots_stale_full_book_summary_after_raw_source_advances(self):
        output_path = self.root / "freshness.json"
        summary_path = self._create_reviewed_summary()
        updated_raw_path = self.source_root / "original-v2.txt"
        updated_raw_path.write_text("Updated raw source.", encoding="utf-8")
        append_artifact(
            self.manifest_path,
            {
                "artifact_id": "episode-1-raw",
                "version_id": "raw-v2",
                "kind": "raw_source",
                "content_sha256": hashlib.sha256(
                    updated_raw_path.read_bytes()
                ).hexdigest(),
                "relative_path": "original-v2.txt",
                "parent_version_ids": [],
            },
        )

        result, stdout, stderr = self._run_cli(
            output_path,
            knowledge=False,
            story_summary=summary_path,
            expected_sources=[
                {
                    "filename": "chapter.md",
                    "source_version_id": "normalized-v1",
                }
            ],
        )

        snapshot_text = output_path.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("reviewed_story_summary: verified=0, stale=1", stdout)
        self.assertEqual(
            snapshot["consumers"]["reviewed_story_summary"]["findings"][0][
                "status"
            ],
            "stale",
        )
        self.assertNotIn("Synthetic full-book summary.", snapshot_text)

    def test_refuses_snapshot_if_manifest_changes_during_audit(self):
        output_path = self.root / "freshness.json"
        original_audit = snapshot_downstream_freshness.audit_translation_memory

        def audit_then_change_manifest(*args, **kwargs):
            findings = original_audit(*args, **kwargs)
            with self.manifest_path.open("ab") as stream:
                stream.write(b" ")
            return findings

        stdout = io.StringIO()
        stderr = io.StringIO()
        args = [
            "--source-root",
            str(self.source_root),
            "--translation-root",
            str(self.translation_root),
            "--manifest",
            "source_manifest.json",
            "--tm",
            str(self.tm_path),
            "--output",
            str(output_path),
        ]
        with (
            patch(
                "scripts.snapshot_downstream_freshness.audit_translation_memory",
                side_effect=audit_then_change_manifest,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(args)

        self.assertEqual(result, 1)
        self.assertIn("manifest changed", stderr.getvalue())
        self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
