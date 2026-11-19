import json
import tempfile
import unittest
from pathlib import Path

from translation_review_state import (
    REVIEW_STAGES,
    create_review_decision_record,
    decide_review_transition,
    load_review_decision_chain,
    verify_review_decision_record,
    write_review_decision,
)


def verdicts(*, fidelity="pass", fluency="pass", style="pass"):
    return {
        "fidelity": [fidelity],
        "fluency": [fluency],
        "style": [style],
    }


def decision_record(**overrides):
    values = {
        "run_id": "a" * 32,
        "work_id": "synthetic-work",
        "episode_id": "episode-1",
        "source_version_id": "source-version-1",
        "source_sha256": "b" * 64,
        "candidate_revision": 0,
        "candidate_relative_path": "Drafts/episode-1.md",
        "parent_candidate_sha256": None,
        "candidate_sha256": "c" * 64,
        "policy_sha256": "d" * 64,
        "reviewer_id": "synthetic-reviewer",
        "reviewed_at_utc": "2026-11-19T00:00:00Z",
        "stage_verdicts": verdicts(),
        "max_rework_attempts": 2,
    }
    values.update(overrides)
    return create_review_decision_record(**values)


class TranslationReviewStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_all_stages_must_pass_before_publication(self):
        result = decide_review_transition(
            verdicts(),
            rework_attempts_used=0,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["publishable"])
        self.assertIsNone(result["next_rework_attempt"])

    def test_failure_requests_rework_while_explicit_budget_remains(self):
        result = decide_review_transition(
            verdicts(fidelity="fail"),
            rework_attempts_used=0,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "rework")
        self.assertFalse(result["publishable"])
        self.assertEqual(result["blocking_stages"], ["fidelity"])
        self.assertEqual(result["next_rework_attempt"], 1)

    def test_failure_at_configured_limit_escalates_to_human(self):
        result = decide_review_transition(
            verdicts(style="fail"),
            rework_attempts_used=2,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["reason"], "rework_limit_reached")
        self.assertFalse(result["publishable"])

    def test_zero_rework_budget_escalates_first_failure(self):
        result = decide_review_transition(
            verdicts(fluency="fail"),
            rework_attempts_used=0,
            max_rework_attempts=0,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["next_rework_attempt"], None)

    def test_missing_stage_verdict_escalates_without_publication(self):
        report = verdicts()
        report["fluency"] = []

        result = decide_review_transition(
            report,
            rework_attempts_used=0,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["reason"], "missing_verdicts")
        self.assertEqual(result["blocking_stages"], ["fluency"])

    def test_inconclusive_verdict_escalates_without_rework(self):
        result = decide_review_transition(
            verdicts(fidelity="inconclusive"),
            rework_attempts_used=0,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["reason"], "inconclusive_verdict")

    def test_conflicting_stage_verdicts_escalate_without_publication(self):
        report = verdicts()
        report["style"] = ["pass", "fail"]

        result = decide_review_transition(
            report,
            rework_attempts_used=0,
            max_rework_attempts=2,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["reason"], "conflicting_verdicts")
        self.assertEqual(result["blocking_stages"], ["style"])

    def test_all_three_stage_names_are_required(self):
        for stage in REVIEW_STAGES:
            report = verdicts()
            del report[stage]
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(ValueError, "cover"):
                    decide_review_transition(
                        report,
                        rework_attempts_used=0,
                        max_rework_attempts=2,
                    )

    def test_boolean_or_negative_retry_limits_are_rejected(self):
        for used, maximum in ((True, 2), (0, False), (-1, 2), (0, -1)):
            with self.subTest(used=used, maximum=maximum):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    decide_review_transition(
                        verdicts(),
                        rework_attempts_used=used,
                        max_rework_attempts=maximum,
                    )

    def test_retry_count_above_policy_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceed"):
            decide_review_transition(
                verdicts(),
                rework_attempts_used=3,
                max_rework_attempts=2,
            )

    def test_unknown_verdict_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported verdict"):
            decide_review_transition(
                verdicts(style="approve"),
                rework_attempts_used=0,
                max_rework_attempts=2,
            )

    def test_decision_record_is_bound_to_source_candidate_and_policy(self):
        original = decision_record()
        changed_candidate = decision_record(candidate_sha256="e" * 64)
        changed_source = decision_record(source_sha256="f" * 64)
        changed_policy = decision_record(policy_sha256="1" * 64)

        verified = verify_review_decision_record(original)
        self.assertTrue(verified["transition"]["publishable"])
        self.assertNotEqual(
            original["decision_sha256"],
            changed_candidate["decision_sha256"],
        )
        self.assertNotEqual(
            original["decision_sha256"],
            changed_source["decision_sha256"],
        )
        self.assertNotEqual(
            original["decision_sha256"],
            changed_policy["decision_sha256"],
        )

    def test_rework_record_requires_parent_and_binds_revision(self):
        record = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256="c" * 64,
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(fluency="fail"),
        )

        verified = verify_review_decision_record(record)
        self.assertEqual(verified["transition"]["status"], "rework")
        self.assertEqual(verified["transition"]["next_rework_attempt"], 2)

    def test_tampered_transition_or_verdict_is_rejected(self):
        record = decision_record()
        record["stage_verdicts"]["style"] = ["fail"]

        with self.assertRaisesRegex(ValueError, "digest or transition"):
            verify_review_decision_record(record)

        record = decision_record()
        record["transition"]["publishable"] = False
        with self.assertRaisesRegex(ValueError, "digest or transition"):
            verify_review_decision_record(record)

    def test_candidate_revision_must_match_rework_attempt_count(self):
        with self.assertRaisesRegex(ValueError, "exceed"):
            decision_record(
                candidate_revision=1,
                candidate_relative_path=(
                    "ReviewCandidates/episode-1/revision-1.md"
                ),
                parent_candidate_sha256="c" * 64,
                candidate_sha256="e" * 64,
                max_rework_attempts=0,
            )

    def test_rework_revision_requires_distinct_parent_digest(self):
        with self.assertRaisesRegex(ValueError, "must differ"):
            decision_record(
                candidate_revision=1,
                candidate_relative_path=(
                    "ReviewCandidates/episode-1/revision-1.md"
                ),
                parent_candidate_sha256="c" * 64,
                candidate_sha256="c" * 64,
            )

    def test_candidate_path_is_bound_to_revision_area(self):
        with self.assertRaisesRegex(ValueError, "ReviewCandidates directory"):
            decision_record(
                candidate_revision=1,
                candidate_relative_path="ReviewCandidates/other/revision-1.md",
                parent_candidate_sha256="c" * 64,
                candidate_sha256="e" * 64,
            )
        with self.assertRaisesRegex(ValueError, "Initial review candidate"):
            decision_record(candidate_relative_path="ReviewCandidates/episode-1.md")

    def test_naive_review_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be UTC"):
            decision_record(reviewed_at_utc="2026-11-19T00:00:00")

    def test_decision_chain_is_create_only_and_recoverable(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = decision_record(
            stage_verdicts=verdicts(style="fail"),
        )
        created = write_review_decision(run_root, first)
        self.assertEqual(created["candidate_revision"], 0)

        second = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(),
        )
        write_review_decision(run_root, second)
        chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
            expected_run_id=first["run_id"],
            expected_work_id=first["work_id"],
            expected_source_version_id=first["source_version_id"],
            expected_source_sha256=first["source_sha256"],
        )

        self.assertEqual(
            [record["candidate_revision"] for record in chain],
            [0, 1],
        )
        self.assertEqual(chain[-1]["transition"]["status"], "passed")
        with self.assertRaises(FileExistsError):
            write_review_decision(run_root, first)

    def test_decision_chain_rejects_tampered_file(self):
        run_root = self.root / "run"
        run_root.mkdir()
        record = decision_record(stage_verdicts=verdicts(style="fail"))
        result = write_review_decision(run_root, record)
        path = Path(result["path"])
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["reviewer_id"] = "changed"
        path.write_text(json.dumps(tampered), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "digest or transition"):
            load_review_decision_chain(
                run_root,
                episode_id=record["episode_id"],
            )

    def test_decision_chain_rejects_non_rework_parent(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = decision_record()
        write_review_decision(run_root, first)
        second = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
        )
        with self.assertRaisesRegex(ValueError, "requires a rework"):
            write_review_decision(run_root, second)

    def test_missing_decision_chain_does_not_create_directories(self):
        run_root = self.root / "run"
        run_root.mkdir()

        chain = load_review_decision_chain(
            run_root,
            episode_id="missing-episode",
        )

        self.assertEqual(chain, [])
        self.assertFalse((run_root / "ReviewDecisions").exists())


if __name__ == "__main__":
    unittest.main()
