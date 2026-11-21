import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import translation_review_state
from translation_review_state import (
    REVIEW_STAGES,
    create_review_decision_record,
    create_review_resolution_record,
    decide_review_transition,
    load_review_decision_chain,
    load_review_resolution_chain,
    store_review_policy_artifact,
    verify_review_decision_record,
    _resolution_sha256,
    write_review_decision,
    write_review_resolution,
)


def verdicts(*, fidelity="pass", fluency="pass", style="pass"):
    return {
        "fidelity": [fidelity],
        "fluency": [fluency],
        "style": [style],
    }


def decision_values(**overrides):
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
    return values


def decision_record(**overrides):
    values = decision_values(**overrides)
    if "issue_codes_by_stage" not in overrides:
        values["issue_codes_by_stage"] = {
            stage: (
                ["synthetic_failure"]
                if "fail" in values["stage_verdicts"][stage]
                else []
            )
            for stage in REVIEW_STAGES
        }
    return create_review_decision_record(**values)


def legacy_decision_record(**overrides):
    record = decision_record(**overrides)
    record.pop("issue_codes_by_stage")
    record["schema_version"] = 1
    identity = {
        key: value for key, value in record.items() if key != "decision_sha256"
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    record["decision_sha256"] = hashlib.sha256(canonical).hexdigest()
    return record


def failed_exhausted_record():
    return decision_record(
        max_rework_attempts=0,
        stage_verdicts=verdicts(fidelity="fail"),
    )


def review_policy_bytes():
    return json.dumps(
        {
            "schema_version": 1,
            "policy_id": "synthetic-review",
            "revision": 1,
            "issue_codes": [
                {
                    "code": "omission",
                    "stages": ["fidelity"],
                    "definition": "Synthetic definition for a fidelity issue.",
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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

    def test_inconclusive_final_review_gate_requires_human_resolution(self):
        result = decide_review_transition(
            verdicts(),
            rework_attempts_used=0,
            max_rework_attempts=2,
            final_review_gate={
                "convergence": "pass",
                "publication_checks": "inconclusive",
            },
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["reason"], "final_review_gate_inconclusive")
        self.assertFalse(result["publishable"])
        self.assertEqual(result["blocking_stages"], list(REVIEW_STAGES))

    def test_ai_final_review_decision_binds_gate_and_policy(self):
        relative_path, policy_sha256, _ = store_review_policy_artifact(
            self.root,
            review_policy_bytes(),
            issue_codes_by_stage={stage: [] for stage in REVIEW_STAGES},
        )
        record = create_review_decision_record(
            **decision_values(policy_sha256=policy_sha256),
            issue_codes_by_stage={stage: [] for stage in REVIEW_STAGES},
            policy_relative_path=relative_path,
            final_review_gate={
                "convergence": "pass",
                "publication_checks": "pass",
            },
        )

        self.assertEqual(record["schema_version"], 4)
        self.assertEqual(verify_review_decision_record(record), record)

        with self.assertRaisesRegex(ValueError, "bound policy"):
            create_review_decision_record(
                **decision_values(),
                issue_codes_by_stage={stage: [] for stage in REVIEW_STAGES},
                final_review_gate={
                    "convergence": "pass",
                    "publication_checks": "pass",
                },
            )

        tampered = dict(record)
        tampered["final_review_gate"] = {
            "convergence": "inconclusive",
            "publication_checks": "pass",
        }
        with self.assertRaisesRegex(ValueError, "digest or transition"):
            verify_review_decision_record(tampered)

    def test_decision_record_defaults_to_two_rework_attempts(self):
        values = decision_values()
        values.pop("max_rework_attempts")
        self.assertEqual(
            create_review_decision_record(**values)[
                "max_rework_attempts"
            ],
            2,
        )

    def test_failed_stage_requires_explicit_issue_code(self):
        with self.assertRaisesRegex(ValueError, "require at least one issue code"):
            create_review_decision_record(
                **decision_values(stage_verdicts=verdicts(fidelity="fail"))
            )

    def test_issue_code_mapping_and_identifiers_are_validated(self):
        invalid_values = (
            (
                {
                    "fidelity": ["Missing_Translation"],
                    "fluency": [],
                    "style": [],
                },
                "fidelity contains an invalid issue code",
            ),
            (
                {
                    "fidelity": ["omission", "omission"],
                    "fluency": [],
                    "style": [],
                },
                "fidelity contains duplicate issue codes",
            ),
            (
                {
                    "fidelity": [],
                    "fluency": [],
                    "style": [],
                    "other": [],
                },
                "Issue codes must cover fidelity, fluency, and style",
            ),
        )
        for issue_codes, expected_error in invalid_values:
            with self.subTest(issue_codes=issue_codes):
                with self.assertRaisesRegex(ValueError, expected_error):
                    decision_record(
                        stage_verdicts=verdicts(fidelity="fail"),
                        issue_codes_by_stage=issue_codes,
                    )

        with self.assertRaisesRegex(ValueError, "must not include issue codes"):
            decision_record(
                issue_codes_by_stage={
                    "fidelity": ["omission"],
                    "fluency": [],
                    "style": [],
                }
            )

    def test_issue_codes_are_canonical_and_hash_bound(self):
        record = decision_record(
            stage_verdicts=verdicts(fidelity="fail"),
            issue_codes_by_stage={
                "fidelity": ["omission", "meaning_shift"],
                "fluency": [],
                "style": [],
            },
        )
        self.assertEqual(
            record["issue_codes_by_stage"]["fidelity"],
            ["meaning_shift", "omission"],
        )
        record["issue_codes_by_stage"]["fidelity"][0] = "unsupported_addition"
        with self.assertRaisesRegex(ValueError, "digest or transition"):
            verify_review_decision_record(record)

    def test_schema_v1_decision_remains_readable(self):
        legacy = legacy_decision_record(
            stage_verdicts=verdicts(fidelity="fail"),
        )
        self.assertEqual(verify_review_decision_record(legacy), legacy)

    def test_policy_bound_decision_validates_and_loads_its_artifact(self):
        issue_codes = {
            "fidelity": ["omission"],
            "fluency": [],
            "style": [],
        }
        policy_path, policy_sha256, _ = store_review_policy_artifact(
            self.root,
            review_policy_bytes(),
            issue_codes_by_stage=issue_codes,
        )
        record = decision_record(
            policy_sha256=policy_sha256,
            policy_relative_path=policy_path,
            stage_verdicts=verdicts(fidelity="fail"),
            issue_codes_by_stage=issue_codes,
        )
        write_review_decision(self.root, record)

        chain = load_review_decision_chain(
            self.root,
            episode_id=record["episode_id"],
            expected_run_id=record["run_id"],
        )

        self.assertEqual(chain, [record])
        self.assertEqual(record["schema_version"], 3)
        self.assertEqual(record["policy_relative_path"], policy_path)
        self.assertTrue((self.root / policy_path).is_file())

    def test_policy_rejects_issue_code_outside_declared_stage(self):
        with self.assertRaisesRegex(ValueError, "not declared for this review policy"):
            store_review_policy_artifact(
                self.root,
                review_policy_bytes(),
                issue_codes_by_stage={
                    "fidelity": [],
                    "fluency": ["omission"],
                    "style": [],
                },
            )
        self.assertFalse((self.root / "ReviewPolicies").exists())

    def test_v2_chain_can_continue_into_matching_policy_bound_v3(self):
        issue_codes = {
            "fidelity": ["omission"],
            "fluency": [],
            "style": [],
        }
        policy_path, policy_sha256, _ = store_review_policy_artifact(
            self.root,
            review_policy_bytes(),
            issue_codes_by_stage=issue_codes,
        )
        first = decision_record(
            policy_sha256=policy_sha256,
            candidate_revision=0,
            candidate_relative_path="Drafts/episode-1.md",
            parent_candidate_sha256=None,
            candidate_sha256="c" * 64,
            max_rework_attempts=1,
            stage_verdicts=verdicts(fidelity="fail"),
            issue_codes_by_stage=issue_codes,
        )
        write_review_decision(self.root, first)

        second = decision_record(
            policy_sha256=policy_sha256,
            policy_relative_path=policy_path,
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-0001.md"
            ),
            parent_candidate_sha256="c" * 64,
            candidate_sha256="e" * 64,
            max_rework_attempts=1,
            stage_verdicts=verdicts(),
            issue_codes_by_stage={
                "fidelity": [],
                "fluency": [],
                "style": [],
            },
        )
        write_review_decision(self.root, second)

        chain = load_review_decision_chain(
            self.root,
            episode_id=first["episode_id"],
        )
        self.assertEqual([record["schema_version"] for record in chain], [2, 3])

    def test_v2_chain_with_unregistered_code_cannot_enter_policy_bound_v3(self):
        policy_path, policy_sha256, _ = store_review_policy_artifact(
            self.root,
            review_policy_bytes(),
        )
        first = decision_record(
            policy_sha256=policy_sha256,
            candidate_revision=0,
            candidate_relative_path="Drafts/episode-1.md",
            parent_candidate_sha256=None,
            candidate_sha256="c" * 64,
            max_rework_attempts=1,
            stage_verdicts=verdicts(fidelity="fail"),
        )
        write_review_decision(self.root, first)
        second = decision_record(
            policy_sha256=policy_sha256,
            policy_relative_path=policy_path,
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-0001.md"
            ),
            parent_candidate_sha256="c" * 64,
            candidate_sha256="e" * 64,
            max_rework_attempts=1,
            stage_verdicts=verdicts(),
            issue_codes_by_stage={
                "fidelity": [],
                "fluency": [],
                "style": [],
            },
        )

        with self.assertRaisesRegex(ValueError, "not declared for this review policy"):
            write_review_decision(self.root, second)

    def test_policy_artifact_tampering_rejects_decision_chain(self):
        issue_codes = {
            "fidelity": ["omission"],
            "fluency": [],
            "style": [],
        }
        policy_path, policy_sha256, _ = store_review_policy_artifact(
            self.root,
            review_policy_bytes(),
            issue_codes_by_stage=issue_codes,
        )
        record = decision_record(
            policy_sha256=policy_sha256,
            policy_relative_path=policy_path,
            stage_verdicts=verdicts(fidelity="fail"),
            issue_codes_by_stage=issue_codes,
        )
        write_review_decision(self.root, record)
        (self.root / policy_path).write_bytes(review_policy_bytes() + b" ")

        with self.assertRaisesRegex(ValueError, "artifact digest is invalid"):
            load_review_decision_chain(
                self.root,
                episode_id=record["episode_id"],
            )

    def test_policy_rejects_duplicate_json_fields(self):
        content = (
            b'{"schema_version":1,"policy_id":"first","policy_id":"second",'
            b'"revision":1,"issue_codes":[]}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
            store_review_policy_artifact(self.root, content)

    def test_malformed_schema_version_is_rejected(self):
        record = decision_record()
        record["schema_version"] = {}
        with self.assertRaisesRegex(ValueError, "schema version"):
            verify_review_decision_record(record)

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
        record["stage_verdicts"]["style"] = ["inconclusive"]

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

    def test_decision_chain_can_continue_from_schema_v1_to_v2(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = legacy_decision_record(
            stage_verdicts=verdicts(fidelity="fail"),
        )
        write_review_decision(run_root, first)
        second = decision_record(
            candidate_revision=1,
            candidate_relative_path="ReviewCandidates/episode-1/revision-1.md",
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(),
        )
        write_review_decision(run_root, second)

        chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
        )
        self.assertEqual(
            [record["schema_version"] for record in chain],
            [1, 2],
        )
        self.assertEqual(chain[-1]["transition"]["status"], "passed")

    def test_decision_chain_rejects_reusing_an_earlier_candidate_digest(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = decision_record(
            stage_verdicts=verdicts(fidelity="fail"),
        )
        write_review_decision(run_root, first)
        second = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(fidelity="fail"),
        )
        write_review_decision(run_root, second)
        third = decision_record(
            candidate_revision=2,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-2.md"
            ),
            parent_candidate_sha256=second["candidate_sha256"],
            candidate_sha256=first["candidate_sha256"],
        )

        with self.assertRaisesRegex(ValueError, "reuses a candidate digest"):
            write_review_decision(run_root, third)

        chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
        )
        self.assertEqual(
            [record["decision_sha256"] for record in chain],
            [first["decision_sha256"], second["decision_sha256"]],
        )
        self.assertFalse(
            (
                run_root
                / "ReviewDecisions"
                / first["episode_id"]
                / (
                    f"revision-0002-{third['decision_sha256']}.json"
                )
            ).exists()
        )

    def test_decision_chain_ignores_interrupted_staging_file(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = decision_record(stage_verdicts=verdicts(style="fail"))
        write_review_decision(run_root, first)
        decision_root = run_root / "ReviewDecisions" / first["episode_id"]
        (decision_root / ".revision-0001-interrupted.tmp").write_bytes(
            b'{"incomplete":'
        )

        chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
            expected_run_id=first["run_id"],
            expected_work_id=first["work_id"],
            expected_source_version_id=first["source_version_id"],
            expected_source_sha256=first["source_sha256"],
        )

        self.assertEqual(chain, [first])

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

    def test_human_approval_resolution_preserves_failed_verdict(self):
        run_root = self.root / "run"
        run_root.mkdir()
        decision = failed_exhausted_record()
        write_review_decision(run_root, decision)
        resolution = create_review_resolution_record(
            decision,
            resolution_revision=0,
            action="approve_current",
            reviewer_id="synthetic-operator",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            rationale="Synthetic operator explicitly accepts this candidate.",
            parent_resolution_sha256=None,
        )

        write_review_resolution(run_root, resolution)
        chain = load_review_decision_chain(
            run_root,
            episode_id=decision["episode_id"],
        )
        resolutions = load_review_resolution_chain(
            run_root,
            episode_id=decision["episode_id"],
        )

        self.assertEqual(chain[-1]["transition"]["status"], "needs_human")
        self.assertEqual(chain[-1]["stage_verdicts"]["fidelity"], ["fail"])
        self.assertEqual(resolutions[-1]["action"], "approve_current")
        self.assertEqual(
            resolutions[-1]["decision_sha256"],
            decision["decision_sha256"],
        )

    def test_resolution_write_rejects_decision_mismatch_before_create(self):
        run_root = self.root / "run"
        run_root.mkdir()
        decision = failed_exhausted_record()
        write_review_decision(run_root, decision)
        resolution = create_review_resolution_record(
            decision,
            resolution_revision=0,
            action="approve_current",
            reviewer_id="synthetic-operator",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            rationale="Synthetic operator explicitly accepts this candidate.",
            parent_resolution_sha256=None,
        )
        resolution["blocking_stages"] = ["style"]
        resolution["resolution_sha256"] = _resolution_sha256(resolution)

        with self.assertRaisesRegex(
            ValueError,
            "Review resolution does not match its decision",
        ):
            write_review_resolution(run_root, resolution)

        resolution_root = run_root / "ReviewResolutions" / decision["episode_id"]
        self.assertFalse(
            resolution_root.exists()
            and any(resolution_root.glob("resolution-*.json"))
        )

    def test_decision_and_resolution_reads_share_append_snapshot(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = failed_exhausted_record()
        write_review_decision(run_root, first)
        first_resolution = create_review_resolution_record(
            first,
            resolution_revision=0,
            action="increase_budget",
            reviewer_id="synthetic-operator",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            rationale="One more attempt is authorized for this candidate.",
            parent_resolution_sha256=None,
            new_max_rework_attempts=1,
        )
        write_review_resolution(run_root, first_resolution)
        second = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(fidelity="fail"),
            max_rework_attempts=1,
        )
        second_resolution = create_review_resolution_record(
            second,
            resolution_revision=1,
            action="approve_current",
            reviewer_id="synthetic-operator",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            rationale="Synthetic operator approves the current candidate.",
            parent_resolution_sha256=first_resolution[
                "resolution_sha256"
            ],
        )

        writer_started = threading.Event()
        writer_finished = threading.Event()
        writer_errors = []
        writer = None
        original_loader = translation_review_state._load_review_resolution_chain

        def append_after_decision_snapshot(root, episode_id, decisions):
            nonlocal writer
            if writer is None:
                def append_resolution():
                    writer_started.set()
                    try:
                        write_review_decision(run_root, second)
                        write_review_resolution(run_root, second_resolution)
                    except BaseException as exc:
                        writer_errors.append(exc)
                    finally:
                        writer_finished.set()

                writer = threading.Thread(target=append_resolution)
                writer.start()
                self.assertTrue(writer_started.wait(timeout=2))
                self.assertFalse(writer_finished.wait(timeout=0.1))
            return original_loader(root, episode_id, decisions)

        with patch.object(
            translation_review_state,
            "_load_review_resolution_chain",
            side_effect=append_after_decision_snapshot,
        ):
            snapshot = load_review_decision_chain(
                run_root,
                episode_id=first["episode_id"],
            )

        self.assertEqual(
            [item["decision_sha256"] for item in snapshot],
            [first["decision_sha256"]],
        )
        writer.join(timeout=5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(writer_errors, [])
        final_chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
        )
        self.assertEqual(
            [item["decision_sha256"] for item in final_chain],
            [first["decision_sha256"], second["decision_sha256"]],
        )

    def test_budget_extension_allows_next_bound_revision(self):
        run_root = self.root / "run"
        run_root.mkdir()
        first = failed_exhausted_record()
        write_review_decision(run_root, first)
        extension = create_review_resolution_record(
            first,
            resolution_revision=0,
            action="increase_budget",
            reviewer_id="synthetic-operator",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            rationale="One more attempt is authorized for this candidate.",
            parent_resolution_sha256=None,
            new_max_rework_attempts=1,
        )
        write_review_resolution(run_root, extension)
        second = decision_record(
            candidate_revision=1,
            candidate_relative_path=(
                "ReviewCandidates/episode-1/revision-1.md"
            ),
            parent_candidate_sha256=first["candidate_sha256"],
            candidate_sha256="e" * 64,
            stage_verdicts=verdicts(),
            max_rework_attempts=1,
        )

        write_review_decision(run_root, second)
        chain = load_review_decision_chain(
            run_root,
            episode_id=first["episode_id"],
        )

        self.assertEqual(chain[-1]["transition"]["status"], "passed")
        self.assertEqual(chain[-1]["max_rework_attempts"], 1)

    def test_budget_extension_must_strictly_increase(self):
        decision = failed_exhausted_record()
        with self.assertRaisesRegex(ValueError, "larger integer"):
            create_review_resolution_record(
                decision,
                resolution_revision=0,
                action="increase_budget",
                reviewer_id="synthetic-operator",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                rationale="Invalid budget reduction.",
                parent_resolution_sha256=None,
                new_max_rework_attempts=0,
            )
        with self.assertRaisesRegex(ValueError, "action is unsupported"):
            create_review_resolution_record(
                decision,
                resolution_revision=0,
                action=[],
                reviewer_id="synthetic-operator",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                rationale="Invalid action type.",
                parent_resolution_sha256=None,
            )


if __name__ == "__main__":
    unittest.main()
