import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.apply_story_summary_review import main
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from story_summary_review import (
    create_summary_review_template,
    load_reviewed_story_summary,
    publish_reviewed_summary,
)
from utils import read_relative_text


class StorySummaryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.knowledge_root = self.root / "Knowledge"
        self.source_root = self.root / "source"
        self.archive_root = self.root / "archive"
        self.knowledge_root.mkdir()
        self.source_root.mkdir()
        self.archive_root.mkdir()
        self.source_file = self.source_root / "chapter.txt"
        self.source_file.write_text(
            "Synthetic source text.\r\nSecond paragraph.\r\n",
            encoding="utf-8",
            newline="",
        )
        self.artifact = self._collect_and_materialize()
        self.summary_bytes = (
            "# Story Summary (Draft)\n\nSynthetic plot summary.\n"
        ).encode("utf-8")
        self.provenance = {
            "schema_version": 1,
            "artifact_status": "complete",
            "source_files": [
                {
                    "filename": self.artifact["relative_path"],
                    "source_sha256": hashlib.sha256(
                        read_relative_text(
                            str(self.archive_root),
                            self.artifact["relative_path"],
                        ).encode("utf-8")
                    ).hexdigest(),
                    "source_version_id": self.artifact["version_id"],
                }
            ],
            "summary_source_chapters": [self.artifact["relative_path"]],
        }
        self.provenance_bytes = json.dumps(
            self.provenance, ensure_ascii=False, indent=2
        ).encode("utf-8")
        (self.knowledge_root / "STORY_SUMMARY_draft.md").write_bytes(
            self.summary_bytes
        )
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_bytes(
            self.provenance_bytes
        )
        self.template_path = self.knowledge_root / "summary-review.json"
        self.output_path = self.knowledge_root / "STORY_SUMMARY_reviewed.json"

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

    def _create_template(self):
        return create_summary_review_template(
            str(self.knowledge_root),
            self.template_path.name,
        )

    def _complete_receipt(self, decision="approved"):
        template = json.loads(self.template_path.read_text(encoding="utf-8"))
        template["reviewer"] = {
            "provider_id": "synthetic-reviewer",
            "model_id": "fixture-v1",
            "review_id": "summary-review-001",
        }
        template["reviewed_at_utc"] = "2026-11-15T00:00:00Z"
        template["decision"] = decision
        template["rationale"] = f"Synthetic review decision: {decision}."
        self.template_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _publish(self, output_filename=None):
        return publish_reviewed_summary(
            str(self.knowledge_root),
            str(self.archive_root),
            "source_manifest.json",
            self.template_path.name,
            output_filename or self.output_path.name,
        )

    def _load(self):
        return load_reviewed_story_summary(
            str(self.output_path),
            str(self.archive_root),
            "source_manifest.json",
        )

    def test_template_binds_candidates_and_starts_pending(self):
        result = self._create_template()
        template = json.loads(self.template_path.read_text(encoding="utf-8"))

        self.assertEqual(result["source_count"], 1)
        self.assertEqual(
            template["candidate_summary_sha256"],
            hashlib.sha256(self.summary_bytes).hexdigest(),
        )
        self.assertEqual(
            template["candidate_provenance_sha256"],
            hashlib.sha256(self.provenance_bytes).hexdigest(),
        )
        self.assertEqual(
            result["output_sha256"],
            hashlib.sha256(self.template_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(template["decision"], "pending")
        self.assertNotIn(
            "Synthetic source text.",
            json.dumps(template, ensure_ascii=False),
        )

    def test_template_mode_does_not_require_current_source_files(self):
        self.source_file.unlink()

        self._create_template()

        self.assertTrue(self.template_path.is_file())

    def test_template_accepts_full_book_source_coverage(self):
        provenance = dict(self.provenance)
        provenance["source_files"] = [
            {
                **self.provenance["source_files"][0],
                "filename": f"chapter-{index}.md",
                "source_version_id": f"version-{index}",
            }
            for index in range(1, 89)
        ]
        provenance["summary_source_chapters"] = [
            item["filename"] for item in provenance["source_files"]
        ]
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 88,
            "included_chapter_count": 88,
            "input_characters": 100,
            "input_character_limit": 500,
        }
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False),
            encoding="utf-8",
        )

        result = self._create_template()

        self.assertEqual(result["source_count"], 88)

    def test_template_rejects_incomplete_full_book_coverage(self):
        provenance = dict(self.provenance)
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 2,
            "included_chapter_count": 1,
            "input_characters": 100,
            "input_character_limit": 500,
        }
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "incomplete full-book coverage"):
            self._create_template()

    def test_token_batch_claim_evidence_survives_summary_approval(self):
        provenance = json.loads(
            (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        source_filename = self.artifact["relative_path"]
        provenance["source_files"][0]["source_index"] = 1
        provenance["source_files"][0]["included_paragraph_count"] = 2
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 1,
            "included_chapter_count": 1,
            "input_characters": 100,
            "input_character_limit": 500,
        }
        provenance["token_budget"] = {
            "tokenizer_sha256": "a" * 64,
            "context_window_tokens": 4096,
            "max_output_tokens_per_request": 512,
            "safety_margin_tokens": 256,
            "message_overhead_tokens": 32,
            "max_input_tokens_per_request": 3328,
            "max_provider_calls": 10,
            "provider_call_count": 1,
            "total_estimated_input_tokens": 100,
            "batches": [
                {
                    "batch_id": "B0001",
                    "source_ids": ["C0001P00001", "C0001P00002"],
                    "estimated_input_tokens": 100,
                    "reported_prompt_tokens": None,
                    "user_message_characters": 100,
                    "user_message_sha256": "b" * 64,
                    "response_sha256": "c" * 64,
                }
            ],
        }
        provenance["claim_evidence"] = [
            {
                "claim_id": "B0001-summary-0001",
                "category": "summary",
                "batch_id": "B0001",
                "claim_text": "Synthetic plot summary.",
                "claim_sha256": hashlib.sha256(
                    b"Synthetic plot summary."
                ).hexdigest(),
                "evidence": [
                    {
                        "source_id": "C0001P00001",
                        "filename": source_filename,
                        "paragraph_index": 1,
                    }
                ],
            }
        ]
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._create_template()
        self._complete_receipt()
        self._publish()

        loaded = load_reviewed_story_summary(
            str(self.output_path),
            str(self.archive_root),
            "source_manifest.json",
            require_full_book_coverage=True,
            expected_sources=[
                {
                    "filename": source_filename,
                    "source_version_id": self.artifact["version_id"],
                }
            ],
        )
        self.assertIn("Synthetic plot summary.", loaded)
        bundle = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(
            bundle["source_provenance"]["claim_evidence"][0]["evidence"][0][
                "source_id"
            ],
            "C0001P00001",
        )

    def test_token_batch_claim_cannot_cite_a_paragraph_outside_its_location(self):
        provenance = json.loads(
            (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        source_filename = self.artifact["relative_path"]
        provenance["source_files"][0]["source_index"] = 1
        provenance["source_files"][0]["included_paragraph_count"] = 2
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 1,
            "included_chapter_count": 1,
            "input_characters": 100,
            "input_character_limit": 500,
        }
        provenance["token_budget"] = {
            "tokenizer_sha256": "a" * 64,
            "context_window_tokens": 4096,
            "max_output_tokens_per_request": 512,
            "safety_margin_tokens": 256,
            "message_overhead_tokens": 32,
            "max_input_tokens_per_request": 3328,
            "max_provider_calls": 10,
            "provider_call_count": 1,
            "total_estimated_input_tokens": 100,
            "batches": [
                {
                    "batch_id": "B0001",
                    "source_ids": ["C0001P00001", "C0001P00002"],
                    "estimated_input_tokens": 100,
                    "reported_prompt_tokens": None,
                    "user_message_characters": 100,
                    "user_message_sha256": "b" * 64,
                    "response_sha256": "c" * 64,
                }
            ],
        }
        provenance["claim_evidence"] = [
            {
                "claim_id": "B0001-summary-0001",
                "category": "summary",
                "batch_id": "B0001",
                "claim_text": "Synthetic plot summary.",
                "claim_sha256": hashlib.sha256(
                    b"Synthetic plot summary."
                ).hexdigest(),
                "evidence": [
                    {
                        "source_id": "C0001P00002",
                        "filename": source_filename,
                        "paragraph_index": 1,
                    }
                ],
            }
        ]
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "invalid claim locations"):
            self._create_template()

    def test_summary_source_size_limit_is_cumulative(self):
        self._create_template()
        self._complete_receipt()

        with patch("story_summary_review._MAX_TOTAL_SOURCE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "total size limit"):
                self._publish()

        self.assertFalse(self.output_path.exists())

    def test_full_book_bundle_must_match_current_chapter_map(self):
        provenance = json.loads(
            (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 1,
            "included_chapter_count": 1,
            "input_characters": 100,
            "input_character_limit": 500,
        }
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._create_template()
        self._complete_receipt()
        self._publish()

        expected = [
            {
                "filename": self.artifact["relative_path"],
                "source_version_id": self.artifact["version_id"],
            }
        ]
        loaded = load_reviewed_story_summary(
            str(self.output_path),
            str(self.archive_root),
            "source_manifest.json",
            require_full_book_coverage=True,
            expected_sources=expected,
        )
        self.assertIn("Synthetic plot summary.", loaded)

        with self.assertRaisesRegex(ValueError, "do not match"):
            load_reviewed_story_summary(
                str(self.output_path),
                str(self.archive_root),
                "source_manifest.json",
                require_full_book_coverage=True,
                expected_sources=[
                    {
                        "filename": self.artifact["relative_path"],
                        "source_version_id": "stale-version",
                    }
                ],
            )

    def test_publishes_approved_bundle_and_runtime_rechecks_sources(self):
        self._create_template()
        self._complete_receipt()

        result = self._publish()
        bundle = json.loads(self.output_path.read_text(encoding="utf-8"))

        self.assertEqual(result["source_count"], 1)
        self.assertEqual(
            result["output_sha256"],
            hashlib.sha256(self.output_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(bundle["approval_status"], "approved")
        self.assertEqual(bundle["summary"], self.summary_bytes.decode("utf-8"))
        self.assertEqual(self._load(), self.summary_bytes.decode("utf-8"))

    def test_project_summary_verification_reads_ai_mirror_not_archive_body(self):
        provenance = json.loads(
            (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 1,
            "included_chapter_count": 1,
            "input_characters": 1,
            "input_character_limit": 100,
        }
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_text(
            json.dumps(provenance, ensure_ascii=False),
            encoding="utf-8",
        )
        self._create_template()
        self._complete_receipt()
        self._publish()
        ai_root = self.root / "RAWs_AI"
        ai_root.mkdir()
        ai_input = ai_root / "episode.md"
        ai_input.write_bytes(
            (self.archive_root / self.artifact["relative_path"]).read_bytes()
        )
        source_sha256 = hashlib.sha256(ai_input.read_bytes()).hexdigest()

        with (
            patch(
                "source_manifest._verify_artifact_file",
                side_effect=AssertionError("archive body read during translation"),
            ),
            patch(
                "story_summary_review.verify_manifest_artifact",
                side_effect=AssertionError("archive body read during translation"),
            ),
        ):
            summary = load_reviewed_story_summary(
                str(self.output_path),
                str(self.archive_root),
                "source_manifest.json",
                require_full_book_coverage=True,
                expected_sources=[
                    {
                        "filename": self.artifact["relative_path"],
                        "source_version_id": self.artifact["version_id"],
                        "source_input_file": "episode.md",
                        "source_sha256": source_sha256,
                    }
                ],
                source_input_root=str(ai_root),
                source_input_map={
                    self.artifact["relative_path"]: {
                        "source_version_id": self.artifact["version_id"],
                        "source_input_file": "episode.md",
                        "source_sha256": source_sha256,
                    }
                },
            )

        self.assertEqual(summary, self.summary_bytes.decode("utf-8"))

    def test_reviewed_summary_requires_json_output_name(self):
        self._create_template()
        self._complete_receipt()

        with self.assertRaisesRegex(ValueError, "must end with .json"):
            self._publish("reviewed-summary.md")

        self.assertFalse(
            (self.knowledge_root / "reviewed-summary.md").exists()
        )

    def test_pending_or_rejected_receipt_cannot_publish(self):
        self._create_template()

        with self.assertRaisesRegex(ValueError, "invalid decision"):
            self._publish()
        self.assertFalse(self.output_path.exists())

        self._complete_receipt("rejected")
        with self.assertRaisesRegex(ValueError, "Only an explicitly approved"):
            self._publish()
        self.assertFalse(self.output_path.exists())

    def test_changed_candidate_is_rejected_before_publication(self):
        self._create_template()
        self._complete_receipt()
        (self.knowledge_root / "STORY_SUMMARY_draft.md").write_bytes(
            self.summary_bytes + b"changed"
        )

        with self.assertRaisesRegex(ValueError, "does not match current candidates"):
            self._publish()
        self.assertFalse(self.output_path.exists())

    def test_stale_source_is_rejected_during_publication(self):
        self._create_template()
        self._complete_receipt()
        self.source_file.write_text("Changed source.\n", encoding="utf-8")
        self._collect_and_materialize("updated-checkpoint.json")

        with self.assertRaisesRegex(ValueError, "not current"):
            self._publish()
        self.assertFalse(self.output_path.exists())

    def test_raw_update_before_materialization_is_rejected_during_publication(self):
        self._create_template()
        self._complete_receipt()
        self.source_file.write_text(
            "Changed raw source before normalization.\n",
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

        with self.assertRaisesRegex(ValueError, "not current"):
            self._publish()
        self.assertFalse(self.output_path.exists())

    def test_stale_source_is_rejected_when_runtime_loads_bundle(self):
        self._create_template()
        self._complete_receipt()
        self._publish()
        self.source_file.write_text("Changed source.\n", encoding="utf-8")
        self._collect_and_materialize("updated-checkpoint.json")

        with self.assertRaisesRegex(ValueError, "not current"):
            self._load()

    def test_tampered_bundle_summary_is_rejected(self):
        self._create_template()
        self._complete_receipt()
        self._publish()
        bundle = json.loads(self.output_path.read_text(encoding="utf-8"))
        bundle["summary"] += "tampered"
        self.output_path.write_text(
            json.dumps(bundle, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "content hash does not match"):
            self._load()

    def test_tampered_bundle_source_provenance_is_rejected(self):
        self._create_template()
        self._complete_receipt()
        self._publish()
        bundle = json.loads(self.output_path.read_text(encoding="utf-8"))
        bundle["source_provenance"]["source_files"][0]["source_sha256"] = "0" * 64
        self.output_path.write_text(
            json.dumps(bundle, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "source provenance hash"):
            self._load()

    def test_reviewed_bundle_requires_source_manifest(self):
        self._create_template()
        self._complete_receipt()
        self._publish()

        with self.assertRaisesRegex(ValueError, "requires a source manifest"):
            load_reviewed_story_summary(
                str(self.output_path),
                str(self.archive_root),
                None,
            )

    def test_existing_output_is_never_overwritten(self):
        self._create_template()
        self._complete_receipt()
        self.output_path.write_text("preserve", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self._publish()
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "preserve")

    def test_cli_creates_template_without_source_arguments(self):
        result = main(
            [
                "--knowledge-root",
                str(self.knowledge_root),
                "--create-template",
                self.template_path.name,
            ]
        )

        self.assertEqual(result, 0)
        self.assertTrue(self.template_path.is_file())

    def test_cli_publishes_approved_review(self):
        self._create_template()
        self._complete_receipt()

        result = main(
            [
                "--knowledge-root",
                str(self.knowledge_root),
                "--source-root",
                str(self.archive_root),
                "--manifest",
                "source_manifest.json",
                "--review",
                self.template_path.name,
                "--output",
                self.output_path.name,
            ]
        )

        self.assertEqual(result, 0)
        self.assertTrue(self.output_path.is_file())


if __name__ == "__main__":
    unittest.main()
