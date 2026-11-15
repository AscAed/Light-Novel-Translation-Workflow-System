import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.approve_translation_plan import main
from translation_plan_approval import (
    create_approval_receipt,
    translation_plan_sha256,
    verify_approval_receipt,
    write_new_json,
)


class TranslationPlanApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.plan_path = self.root / "translation-plan.json"
        self.receipt_path = self.root / "translation-approval.json"
        self.plan = {
            "schema_version": 1,
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


if __name__ == "__main__":
    unittest.main()
