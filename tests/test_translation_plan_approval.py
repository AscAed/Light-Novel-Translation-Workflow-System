import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.approve_translation_plan import main
from source_ingestion import source_artifact_id
from translation_plan_approval import (
    create_plan_review_template,
    create_approval_receipt,
    translation_plan_sha256,
    verify_approval_receipt,
    verify_plan_review_template,
    write_new_json,
)


class TranslationPlanApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.plan_path = self.root / "translation-plan.json"
        self.receipt_path = self.root / "translation-approval.json"
        self.plan = {
            "schema_version": 2,
            "status": "ready_for_review",
            "work_id": "synthetic-work",
            "source_root": str(self.root / "source"),
            "catalog": "catalog.json",
            "manifest": "source_manifest.json",
            "translation_root": str(self.root / "translation"),
            "episode_count": 1,
            "verified_source_count": 1,
            "network_requests": 0,
            "provider_calls": 0,
            "filesystem_writes": 0,
            "source_text_included": False,
            "episodes": [
                {
                    "episode_id": "123456789",
                    "position": 1,
                    "title": "Synthetic episode",
                    "source_file": "normalized/episode.md",
                    "source_version_id": "normalized-version-1",
                    "source_input_file": None,
                    "source_sha256": hashlib.sha256(
                        b"synthetic source"
                    ).hexdigest(),
                    "translation_file": "episode-0001-123456789.md",
                    "translation_target_exists": False,
                    "tm_key": "kakuyomu:synthetic-work:123456789",
                }
            ],
            "issues": [],
        }
        self.plan["plan_sha256"] = translation_plan_sha256(self.plan)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_requires_exact_digest_and_creates_new_receipt(self):
        write_new_json(self.plan_path, self.plan)
        output = io.StringIO()

        with patch("builtins.input", return_value=self.plan["plan_sha256"]):
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "--plan",
                        str(self.plan_path),
                        "--receipt",
                        str(self.receipt_path),
                        "--reviewer",
                        "synthetic reviewer",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(self.receipt_path.is_file())
        self.assertIn("Synthetic episode", output.getvalue())
        self.assertIn("not authenticated", output.getvalue())
        receipt = verify_approval_receipt(self.receipt_path, self.plan)
        self.assertEqual(receipt["approved_by"], "synthetic reviewer")

    def test_cli_rejects_receipt_inside_source_archive_before_confirmation(self):
        write_new_json(self.plan_path, self.plan)
        archive_root = Path(self.plan["source_root"])
        archive_root.mkdir()
        receipt_path = archive_root / "approval.json"
        error = io.StringIO()

        with (
            patch("builtins.input") as confirmation,
            contextlib.redirect_stderr(error),
        ):
            result = main(
                [
                    "--plan",
                    str(self.plan_path),
                    "--receipt",
                    str(receipt_path),
                    "--reviewer",
                    "synthetic reviewer",
                ]
            )

        self.assertEqual(result, 1)
        self.assertFalse(receipt_path.exists())
        confirmation.assert_not_called()
        self.assertIn("ValueError", error.getvalue())

    def test_wrong_digest_does_not_write_receipt(self):
        write_new_json(self.plan_path, self.plan)
        error = io.StringIO()

        with patch("builtins.input", return_value="0" * 64):
            with contextlib.redirect_stderr(error):
                result = main(
                    [
                        "--plan",
                        str(self.plan_path),
                        "--receipt",
                        str(self.receipt_path),
                        "--reviewer",
                        "synthetic reviewer",
                    ]
                )

        self.assertEqual(result, 2)
        self.assertFalse(self.receipt_path.exists())
        self.assertIn("did not match", error.getvalue())

    def test_stale_mapping_cannot_use_an_existing_receipt(self):
        receipt = create_approval_receipt(self.plan, "synthetic reviewer")
        write_new_json(self.receipt_path, receipt)
        changed_plan = dict(self.plan)
        changed_plan["episodes"] = [dict(self.plan["episodes"][0])]
        changed_plan["episodes"][0]["source_version_id"] = "new-version"
        changed_plan["plan_sha256"] = translation_plan_sha256(changed_plan)

        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_approval_receipt(self.receipt_path, changed_plan)

    def test_approval_digest_binds_ai_edition_index_and_manifest(self):
        ai_plan = dict(self.plan)
        ai_plan["source_edition"] = {
            "profile_id": "ai-efficient-v1",
            "index_root": str(self.root / "ai"),
            "index_relative_path": "catalog.json",
            "index_sha256": "a" * 64,
            "manifest": "source_editions_manifest.json",
            "manifest_sha256": "b" * 64,
        }
        ai_plan["episodes"] = [dict(self.plan["episodes"][0])]
        ai_plan["episodes"][0]["source_input_file"] = "episodes/0001.md"
        ai_plan["plan_sha256"] = translation_plan_sha256(ai_plan)
        receipt = create_approval_receipt(
            ai_plan,
            "synthetic reviewer",
            review_sha256="e" * 64,
        )
        write_new_json(self.receipt_path, receipt)

        changed_plan = dict(ai_plan)
        changed_plan["source_edition"] = dict(ai_plan["source_edition"])
        changed_plan["source_edition"]["index_sha256"] = "c" * 64
        changed_plan["plan_sha256"] = translation_plan_sha256(changed_plan)

        self.assertNotEqual(
            ai_plan["plan_sha256"],
            changed_plan["plan_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_approval_receipt(self.receipt_path, changed_plan)

        changed_input = dict(ai_plan)
        changed_input["episodes"] = [dict(ai_plan["episodes"][0])]
        changed_input["episodes"][0]["source_input_file"] = "episodes/changed.md"
        changed_input["plan_sha256"] = translation_plan_sha256(changed_input)
        self.assertNotEqual(
            ai_plan["plan_sha256"],
            changed_input["plan_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_approval_receipt(self.receipt_path, changed_input)

    def test_existing_targets_can_resume_only_from_matching_approval(self):
        receipt = create_approval_receipt(self.plan, "synthetic reviewer")
        write_new_json(self.receipt_path, receipt)
        resumed_plan = dict(self.plan)
        resumed_plan["status"] = "blocked"
        resumed_plan["episodes"] = [dict(self.plan["episodes"][0])]
        resumed_plan["episodes"][0]["translation_target_exists"] = True
        resumed_plan["issues"] = [
            {
                "episode_id": "123456789",
                "code": "translation_target_exists",
            }
        ]

        verified = verify_approval_receipt(self.receipt_path, resumed_plan)

        self.assertEqual(verified["plan_sha256"], self.plan["plan_sha256"])

    def test_non_target_plan_issue_invalidates_execution(self):
        receipt = create_approval_receipt(self.plan, "synthetic reviewer")
        write_new_json(self.receipt_path, receipt)
        blocked_plan = dict(self.plan)
        blocked_plan["status"] = "blocked"
        blocked_plan["issues"] = [
            {"episode_id": "123456789", "code": "invalid_normalized_source"}
        ]

        with self.assertRaisesRegex(ValueError, "not safe to execute"):
            verify_approval_receipt(self.receipt_path, blocked_plan)

    def test_blocked_or_tampered_plan_cannot_create_receipt(self):
        blocked_plan = dict(self.plan)
        blocked_plan["status"] = "blocked"
        blocked_plan["issues"] = [
            {"episode_id": "123456789", "code": "missing_raw_source"}
        ]
        with self.assertRaisesRegex(ValueError, "fully verified"):
            create_approval_receipt(blocked_plan, "synthetic reviewer")

        self.plan["episodes"][0]["tm_key"] = "changed-key"
        with self.assertRaisesRegex(ValueError, "digest does not match"):
            create_approval_receipt(self.plan, "synthetic reviewer")

    def test_boolean_verified_source_count_is_not_accepted(self):
        receipt = create_approval_receipt(self.plan, "synthetic reviewer")
        write_new_json(self.receipt_path, receipt)
        invalid_plan = dict(self.plan)
        invalid_plan["verified_source_count"] = True

        with self.assertRaisesRegex(ValueError, "fully verified"):
            create_approval_receipt(invalid_plan, "synthetic reviewer")
        with self.assertRaisesRegex(ValueError, "not safe to execute"):
            verify_approval_receipt(self.receipt_path, invalid_plan)

    def test_receipt_path_is_never_overwritten(self):
        receipt = create_approval_receipt(self.plan, "synthetic reviewer")
        write_new_json(self.receipt_path, receipt)

        with self.assertRaises(FileExistsError):
            write_new_json(
                self.receipt_path,
                create_approval_receipt(self.plan, "another reviewer"),
            )

    def _ai_plan_with_human_index(self):
        plan = dict(self.plan)
        shared_lineage = {
            "source_manifest": {
                "relative_path": "source_manifest.json",
                "sha256": "c" * 64,
            },
            "edition_manifest": {
                "relative_path": "source_editions_manifest.json",
                "sha256": "b" * 64,
            },
            "catalog": {
                "relative_path": "catalog.json",
                "sha256": "d" * 64,
            },
            "work_metadata": None,
        }
        plan["source_edition"] = {
            "profile_id": "ai-efficient-v1",
            "index_root": str(self.root / "ai"),
            "index_relative_path": "catalog.json",
            "index_sha256": "a" * 64,
            "manifest": "source_editions_manifest.json",
            "manifest_sha256": "b" * 64,
        }
        plan["episodes"] = [dict(self.plan["episodes"][0])]
        plan["episodes"][0]["source_input_file"] = "episodes/0001.md"
        ai_episode = {
            "episode_id": "123456789",
            "position": 1,
            "title": "Synthetic episode",
            "source_version_id": plan["episodes"][0]["source_version_id"],
            "source_sha256": plan["episodes"][0]["source_sha256"],
            "ai_edition_version_id": plan["episodes"][0]["source_version_id"],
            "ai_relative_path": plan["episodes"][0]["source_input_file"],
            "output_sha256": plan["episodes"][0]["source_sha256"],
            "raw_source_version_id": "raw-source-version-1",
            "raw_source_sha256": "e" * 64,
            "edition_input_version_id": "raw-source-version-1",
            "edition_input_sha256": "e" * 64,
        }
        ai_index = {
            "schema_version": 2,
            "edition": "ai",
            "work_id": plan["work_id"],
            **shared_lineage,
            "episodes": [ai_episode],
        }
        ai_index_result = {
            "index": ai_index,
            "index_sha256": plan["source_edition"]["index_sha256"],
            "episodes_by_id": {ai_episode["episode_id"]: ai_episode},
        }
        human_output_sha256 = hashlib.sha256(
            b"synthetic human edition"
        ).hexdigest()
        human_artifact_id = source_artifact_id(
            plan["work_id"],
            "human-reading-v1",
            ai_episode["episode_id"],
        )
        human_artifact = {
            "artifact_id": human_artifact_id,
            "version_id": "human-edition-version-1",
            "kind": "export",
            "content_sha256": human_output_sha256,
            "relative_path": (
                "editions/human-reading-v1/123456789/"
                "human-edition-version-1.md"
            ),
            "parent_version_ids": ["raw-source-version-1"],
        }
        ai_index_result["edition_manifest"] = {
            "schema_version": 1,
            "artifacts": [human_artifact],
        }
        self.enterContext(
            patch(
                "translation_plan_approval.verify_ai_edition_index",
                return_value=ai_index_result,
            )
        )
        plan["plan_sha256"] = translation_plan_sha256(plan)
        human_index = {
            "schema_version": 2,
            "edition": "human_reading",
            "work_id": plan["work_id"],
            **shared_lineage,
            "episodes": [
                {
                    "episode_id": "123456789",
                    "position": 1,
                    "title": "Synthetic episode",
                    "source_version_id": ai_episode["source_version_id"],
                    "source_sha256": ai_episode["source_sha256"],
                    "raw_source_version_id": ai_episode[
                        "raw_source_version_id"
                    ],
                    "raw_source_sha256": ai_episode["raw_source_sha256"],
                    "edition_input_version_id": ai_episode[
                        "edition_input_version_id"
                    ],
                    "edition_input_sha256": ai_episode[
                        "edition_input_sha256"
                    ],
                    "human_edition_artifact_id": human_artifact_id,
                    "human_edition_version_id": "human-edition-version-1",
                    "human_archive_relative_path": human_artifact["relative_path"],
                    "human_relative_path": "Chapter/Synthetic episode.md",
                    "output_sha256": human_output_sha256,
                }
            ],
        }
        human_index_path = self.root / "SOURCE_MAP.json"
        human_chapter_path = self.root / "Chapter" / "Synthetic episode.md"
        human_chapter_path.parent.mkdir()
        human_chapter_path.write_bytes(b"synthetic human edition")
        human_index_path.write_text(
            json.dumps(human_index, ensure_ascii=False),
            encoding="utf-8",
        )
        return plan, human_index_path

    def test_plan_review_rejects_human_output_not_bound_to_episode_artifact(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        human_index = json.loads(human_index_path.read_text(encoding="utf-8"))
        alternate_path = self.root / "Chapter" / "Other episode.md"
        alternate_bytes = b"alternate human edition"
        alternate_path.write_bytes(alternate_bytes)
        human_index["episodes"][0]["human_relative_path"] = (
            "Chapter/Other episode.md"
        )
        human_index["episodes"][0]["output_sha256"] = hashlib.sha256(
            alternate_bytes
        ).hexdigest()
        human_index_path.write_text(
            json.dumps(human_index, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "archived artifact identity"):
            create_plan_review_template(plan, human_index_path)

    def test_plan_review_template_requires_all_three_explicit_passes(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        template = create_plan_review_template(plan, human_index_path)
        self.assertEqual(template["episode_count"], 1)
        self.assertEqual(
            template["episodes"][0]["mapping_decision"],
            "pending",
        )

        review_path = self.root / "plan-review.json"
        write_new_json(review_path, template)
        with self.assertRaisesRegex(ValueError, "not fully approved"):
            verify_plan_review_template(
                review_path,
                plan,
                human_index_path,
            )

        review = json.loads(review_path.read_text(encoding="utf-8"))
        episode = review["episodes"][0]
        episode["mapping_decision"] = "pass"
        episode["ai_edition_decision"] = "pass"
        episode["human_edition_decision"] = "pass"
        review_path.write_text(
            json.dumps(review, ensure_ascii=False),
            encoding="utf-8",
        )
        _, review_sha256 = verify_plan_review_template(
            review_path,
            plan,
            human_index_path,
        )
        receipt = create_approval_receipt(
            plan,
            "synthetic reviewer",
            review_sha256=review_sha256,
        )
        self.assertEqual(receipt["schema_version"], 2)
        write_new_json(self.receipt_path, receipt)
        verified = verify_approval_receipt(self.receipt_path, plan)
        self.assertEqual(verified["review_sha256"], review_sha256)

    def test_plan_review_template_rejects_stale_human_index(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        template = create_plan_review_template(plan, human_index_path)
        review_path = self.root / "plan-review.json"
        write_new_json(review_path, template)

        human_chapter_path = human_index_path.parent / "Chapter" / "Synthetic episode.md"
        human_chapter_path.write_bytes(b"changed human edition")
        changed = json.loads(human_index_path.read_text(encoding="utf-8"))
        changed["episodes"][0]["output_sha256"] = hashlib.sha256(
            b"changed human edition"
        ).hexdigest()
        human_index_path.write_text(
            json.dumps(changed, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            verify_plan_review_template(
                review_path,
                plan,
                human_index_path,
            )

    def test_plan_review_template_rejects_index_hash_not_matching_file(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        human_chapter_path = human_index_path.parent / "Chapter" / "Synthetic episode.md"
        human_chapter_path.write_bytes(b"modified without refreshing index")

        with self.assertRaisesRegex(ValueError, "does not match its index"):
            create_plan_review_template(plan, human_index_path)

    def test_cli_accepts_completed_review_and_binds_schema_two_receipt(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        plan_path = self.root / "plan.json"
        review_path = self.root / "plan-review.json"
        write_new_json(plan_path, plan)
        review = create_plan_review_template(plan, human_index_path)
        for field in (
            "mapping_decision",
            "ai_edition_decision",
            "human_edition_decision",
        ):
            review["episodes"][0][field] = "pass"
        write_new_json(review_path, review)
        receipt_path = self.root / "approval.json"
        output = io.StringIO()

        with patch("builtins.input", return_value=plan["plan_sha256"]):
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--review",
                        str(review_path),
                        "--human-index",
                        str(human_index_path),
                        "--receipt",
                        str(receipt_path),
                        "--reviewer",
                        "synthetic reviewer",
                    ]
                )

        self.assertEqual(result, 0)
        receipt = verify_approval_receipt(receipt_path, plan)
        self.assertEqual(receipt["schema_version"], 2)
        self.assertRegex(receipt["review_sha256"], r"^[0-9a-f]{64}$")

    def test_ai_edition_plan_cannot_create_or_use_schema_one_receipt(self):
        plan, _ = self._ai_plan_with_human_index()
        with self.assertRaisesRegex(ValueError, "structured review"):
            create_approval_receipt(plan, "synthetic reviewer")

        legacy_receipt = {
            "schema_version": 1,
            "plan_sha256": plan["plan_sha256"],
            "work_id": plan["work_id"],
            "episode_count": plan["episode_count"],
            "approved_by": "legacy reviewer",
            "approved_at_utc": "2026-11-19T00:00:00Z",
        }
        write_new_json(self.receipt_path, legacy_receipt)
        with self.assertRaisesRegex(ValueError, "structured review"):
            verify_approval_receipt(self.receipt_path, plan)

    def test_ai_edition_cli_requires_structured_review_arguments(self):
        plan, _ = self._ai_plan_with_human_index()
        write_new_json(self.plan_path, plan)
        error = io.StringIO()

        with (
            patch("builtins.input") as confirmation,
            contextlib.redirect_stderr(error),
        ):
            result = main(
                [
                    "--plan",
                    str(self.plan_path),
                    "--receipt",
                    str(self.receipt_path),
                    "--reviewer",
                    "synthetic reviewer",
                ]
            )

        self.assertEqual(result, 1)
        self.assertFalse(self.receipt_path.exists())
        confirmation.assert_not_called()
        self.assertIn("--review and --human-index", error.getvalue())

    def test_plan_review_rejects_human_edition_from_another_source_revision(self):
        plan, human_index_path = self._ai_plan_with_human_index()
        human_index = json.loads(
            human_index_path.read_text(encoding="utf-8")
        )
        human_index["episodes"][0]["raw_source_version_id"] = (
            "raw-source-version-old"
        )
        human_index_path.write_text(
            json.dumps(human_index, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "lineage"):
            create_plan_review_template(plan, human_index_path)

    def test_schema_two_receipt_requires_review_digest(self):
        plan, _ = self._ai_plan_with_human_index()
        receipt = create_approval_receipt(
            plan,
            "synthetic reviewer",
            review_sha256="c" * 64,
        )
        write_new_json(self.receipt_path, receipt)
        tampered = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        del tampered["review_sha256"]
        self.receipt_path.write_text(
            json.dumps(tampered),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "fields"):
            verify_approval_receipt(self.receipt_path, plan)


if __name__ == "__main__":
    unittest.main()
