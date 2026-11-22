import asyncio
import hashlib
import io
import json
import multiprocessing
import os
import signal
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import translation_review
import ai_translation_review
import ai_translation_rework
import ai_translation_workflow
import scripts.record_translation_review_decision as review_decision_cli
import scripts.resolve_translation_review as review_resolution_cli
from scripts.publish_reviewed_run import main as publish_reviewed_run_main
from scripts.run_ai_translation_workflow import (
    main as run_ai_translation_workflow_main,
)
from source_editions import prepare_source_editions
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from translation_review import (
    _REVIEW_CHECKS,
    _load_run,
    _mark_run_published_if_complete,
    audit_published_translation_freshness,
    build_translation_run_manifest,
    has_verified_translation_publication,
    prepare_translation_review,
    publish_reviewed_run,
    publish_reviewed_translation,
    record_translation_review_decision as _record_translation_review_decision,
    resolve_translation_review,
)
from translation_review_state import _lock_episode_workflow


_CHECKPOINT_TIMEOUT_EXIT_CODE = 86


def _assert_checkpoint_worker_was_terminated(test_case, process) -> None:
    test_case.assertEqual(process.exitcode, -signal.SIGTERM)


def _hold_episode_workflow_lock(run_root, episode_id, ready, release):
    async def hold():
        async with _lock_episode_workflow(Path(run_root), episode_id):
            ready.set()
            await asyncio.to_thread(release.wait)

    asyncio.run(hold())


def _write_durable_checkpoint_marker(path: Path, payload: dict) -> None:
    path = Path(path)
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _review_until_publication_snapshot_checkpoint(
    run_root,
    episode_id,
    policy_path,
    marker_path,
    ready,
):
    async def assessor(_prompt, _assessment_number):
        return json.dumps(
            {
                "stage_verdicts": {
                    "fidelity": "pass",
                    "fluency": "pass",
                    "style": "pass",
                },
                "optimization_potential": "low",
                "publication_checks": {
                    name: "pass" for name in _REVIEW_CHECKS
                },
                "findings": [],
            }
        )

    snapshot_root = Path(run_root) / "Published" / "ReviewSnapshots"
    original_write = translation_review._write_new_bytes_atomically

    def checkpoint_before_snapshot(root, relative_path, content):
        if (
            Path(root).resolve() == snapshot_root.resolve()
            and relative_path == f"{episode_id}.json"
        ):
            _write_durable_checkpoint_marker(
                Path(marker_path),
                {
                    "checkpoint": "before_publication_review_snapshot",
                    "episode_id": episode_id,
                    "pid": os.getpid(),
                },
            )
            ready.set()
            threading.Event().wait(timeout=30)
            os._exit(_CHECKPOINT_TIMEOUT_EXIT_CODE)
        return original_write(root, relative_path, content)

    with (
        patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ),
        patch.object(
            translation_review,
            "_write_new_bytes_atomically",
            side_effect=checkpoint_before_snapshot,
        ),
    ):
        asyncio.run(
            ai_translation_review.review_translation_candidate(
                run_root,
                episode_id,
                review_policy_file=policy_path,
                assessor=assessor,
                reviewer_model="synthetic-reviewer",
            )
        )


def _review_until_run_state_checkpoint(
    run_root,
    episode_id,
    policy_path,
    marker_path,
    ready,
):
    async def assessor(_prompt, _assessment_number):
        return json.dumps(
            {
                "stage_verdicts": {
                    "fidelity": "pass",
                    "fluency": "pass",
                    "style": "pass",
                },
                "optimization_potential": "low",
                "publication_checks": {
                    name: "pass" for name in _REVIEW_CHECKS
                },
                "findings": [],
            }
        )

    def checkpoint_before_run_state(run_root, run, run_bytes, **_kwargs):
        _write_durable_checkpoint_marker(
            Path(marker_path),
            {
                "checkpoint": "before_run_state_published",
                "episode_id": episode_id,
                "pid": os.getpid(),
            },
        )
        ready.set()
        threading.Event().wait(timeout=30)
        os._exit(_CHECKPOINT_TIMEOUT_EXIT_CODE)

    with (
        patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ),
        patch.object(
            translation_review,
            "_mark_run_published_if_complete",
            side_effect=checkpoint_before_run_state,
        ),
    ):
        asyncio.run(
            ai_translation_review.review_translation_candidate(
                run_root,
                episode_id,
                review_policy_file=policy_path,
                assessor=assessor,
                reviewer_model="synthetic-reviewer",
            )
        )


def _publish_until_receipt_checkpoint(
    run_root,
    episode_id,
    review_path,
    marker_path,
    ready,
):
    published_root = Path(run_root) / "Published"
    original_create = translation_review._create_new_bytes_atomically

    def checkpoint_before_receipt(root, relative_path, content):
        if (
            Path(root).resolve() == published_root.resolve()
            and relative_path == f"{episode_id}.json"
        ):
            _write_durable_checkpoint_marker(
                Path(marker_path),
                {
                    "checkpoint": "before_publication_receipt",
                    "episode_id": episode_id,
                    "pid": os.getpid(),
                },
            )
            ready.set()
            threading.Event().wait(timeout=30)
            os._exit(_CHECKPOINT_TIMEOUT_EXIT_CODE)
        return original_create(root, relative_path, content)

    with patch.object(
        translation_review,
        "_create_new_bytes_atomically",
        side_effect=checkpoint_before_receipt,
    ):
        translation_review.publish_reviewed_translation(
            run_root,
            episode_id,
            review_path,
        )


def _review_until_second_assessment_checkpoint(
    run_root,
    episode_id,
    policy_path,
    marker_path,
    ready,
):
    async def assessor(_prompt, assessment_number):
        if assessment_number == 1:
            return json.dumps(
                {
                    "stage_verdicts": {
                        "fidelity": "pass",
                        "fluency": "pass",
                        "style": "pass",
                    },
                    "optimization_potential": "low",
                    "publication_checks": {
                        name: "pass" for name in _REVIEW_CHECKS
                    },
                    "findings": [],
                }
            )
        _write_durable_checkpoint_marker(
            Path(marker_path),
            {
                "checkpoint": "before_second_assessment_response",
                "episode_id": episode_id,
                "pid": os.getpid(),
            },
        )
        ready.set()
        threading.Event().wait(timeout=30)
        os._exit(_CHECKPOINT_TIMEOUT_EXIT_CODE)

    with patch.object(
        ai_translation_review,
        "_provider_fingerprint",
        return_value="e" * 64,
    ):
        asyncio.run(
            ai_translation_review.review_translation_candidate(
                run_root,
                episode_id,
                review_policy_file=policy_path,
                assessor=assessor,
                reviewer_model="synthetic-reviewer",
            )
        )


def record_translation_review_decision(run_directory, episode_id, **kwargs):
    """Keep existing fixtures concise while passing the reviewed digest explicitly."""
    if "issue_codes_by_stage" not in kwargs:
        stage_verdicts = kwargs.get("stage_verdicts", {})
        kwargs["issue_codes_by_stage"] = {
            stage: (
                ["synthetic_failure"]
                if "fail" in stage_verdicts.get(stage, [])
                else []
            )
            for stage in ("fidelity", "fluency", "style")
        }
    if "reviewed_candidate_sha256" not in kwargs:
        run_root = Path(run_directory)
        candidate = kwargs.get("candidate_file")
        candidate_path = (
            Path(candidate)
            if candidate is not None and Path(candidate).is_absolute()
            else run_root
            / (
                candidate
                if candidate is not None
                else "Drafts/"
                + next(
                    item["translation_file"]
                    for item in json.loads((run_root / "run.json").read_text())[
                        "episodes"
                    ]
                    if item["episode_id"] == episode_id
                )
            )
        )
        kwargs["reviewed_candidate_sha256"] = hashlib.sha256(
            candidate_path.read_bytes()
        ).hexdigest()
    return _record_translation_review_decision(
        run_directory,
        episode_id,
        **kwargs,
    )


class TranslationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.input_root = self.root / "input"
        self.source_root = self.root / "archive"
        self.human_root = self.root / "human"
        self.ai_root = self.root / "ai"
        self.translation_root = self.root / "published"
        self.run_root = self.root / "Workflow" / "Runs" / ("a" * 32)
        for path in (
            self.input_root,
            self.source_root,
            self.human_root,
            self.ai_root,
            self.translation_root,
            self.run_root / "Drafts",
        ):
            path.mkdir(parents=True)

        self.work_id = "12345"
        self.episode_id = "67890"
        self.source_text = "「Synthetic source paragraph.」\n"
        (self.input_root / "episode.txt").write_bytes(
            self.source_text.encode("utf-8")
        )
        episode = LocalEpisodeFile(
            EpisodeMetadata(
                self.episode_id,
                "Synthetic episode",
                1,
                f"https://kakuyomu.jp/works/{self.work_id}/episodes/{self.episode_id}",
            ),
            "episode.txt",
        )
        self.work_metadata = {
            "source_url": f"https://kakuyomu.jp/works/{self.work_id}",
            "title": "Synthetic work",
            "author_name": "Synthetic author",
            "author_screen_name": "synthetic",
            "catchphrase": "",
            "introduction": "",
            "genre": "fantasy",
            "tags": [],
            "serial_status": "ongoing",
            "published_at": None,
            "last_episode_published_at": None,
            "public_episode_count": 1,
        }
        collect_source(
            LocalFileAdapter(self.input_root, [episode]),
            root=self.source_root,
            work_id=self.work_id,
            work_metadata=self.work_metadata,
        )
        self.catalog = {
            "schema_version": 3,
            "work_id": self.work_id,
            "work_metadata": self.work_metadata,
            "episodes": [
                {
                    "episode_id": self.episode_id,
                    "title": "Synthetic episode",
                    "position": 1,
                    "page_url": episode.metadata.source_ref,
                }
            ],
            "chapters": [
                {
                    "group_id": "chapter-1",
                    "chapter_id": "chapter-1",
                    "title": "Chapter One",
                    "level": 1,
                    "position_start": 1,
                    "position_end": 1,
                    "episode_ids": [self.episode_id],
                }
            ],
        }
        (self.source_root / "catalog.json").write_text(
            json.dumps(self.catalog, ensure_ascii=False),
            encoding="utf-8",
        )
        materialize_episode_markdown(
            self.source_root,
            work_id=self.work_id,
            episode_id=self.episode_id,
        )
        prepare_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            manifest_relative_path="source_manifest.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )
        self.ai_index = json.loads(
            (self.ai_root / "catalog.json").read_text(encoding="utf-8")
        )
        indexed = self.ai_index["episodes"][0]
        self.plan = {
            "work_id": self.work_id,
            "plan_sha256": "a" * 64,
            "episodes": [
                {
                    "episode_id": self.episode_id,
                    "position": 1,
                    "title": indexed["title"],
                    "source_file": indexed["ai_archive_relative_path"],
                    "source_version_id": indexed["ai_edition_version_id"],
                    "source_input_version_id": indexed[
                        "raw_source_version_id"
                    ],
                    "source_input_file": indexed["ai_relative_path"],
                    "source_sha256": indexed["output_sha256"],
                    "translation_file": "episode-0001.md",
                    "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                }
            ],
        }
        draft_source = (self.ai_root / indexed["ai_relative_path"]).read_bytes()
        self.draft_bytes = draft_source
        (self.run_root / "Drafts" / "episode-0001.md").write_bytes(
            self.draft_bytes
        )
        self.run_manifest = build_translation_run_manifest(
            run_id="a" * 32,
            plan=self.plan,
            source_root=str(self.source_root),
            source_manifest="source_manifest.json",
            edition_manifest="source_editions_manifest.json",
            catalog="catalog.json",
            ai_root=str(self.ai_root),
            draft_root=str(self.run_root / "Drafts"),
            translation_root=str(self.translation_root),
        )
        (self.run_root / "run.json").write_text(
            json.dumps(self.run_manifest, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.run_root / "run_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "running",
                    "run_id": "a" * 32,
                    "work_id": self.work_id,
                    "plan_sha256": self.plan["plan_sha256"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _approved_review(self):
        prepare_translation_review(self.run_root, self.episode_id)
        review_path = (
            self.run_root / "Reviews" / f"{self.episode_id}.json"
        )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["reviewer_id"] = "synthetic independent reviewer"
        review["independence_confirmed"] = True
        review["reviewed_at_utc"] = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        review["decision"] = "approved"
        review["checks"] = {name: "pass" for name in _REVIEW_CHECKS}
        review["issues"] = []
        review_path.write_text(
            json.dumps(review, ensure_ascii=False),
            encoding="utf-8",
        )
        return review_path

    def test_publication_freshness_verifies_current_k4_output(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        findings = audit_published_translation_freshness(
            self.run_root.parent,
            self.translation_root,
            [
                {
                    "translation_file": "episode-0001.md",
                    "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                    "source_version_id": self.plan["episodes"][0][
                        "source_version_id"
                    ],
                    "source_sha256": self.plan["episodes"][0]["source_sha256"],
                }
            ],
        )

        self.assertEqual(
            findings,
            [
                {
                    "translation_file": "episode-0001.md",
                    "status": "verified",
                    "detail": (
                        "Published bytes match a valid K4 receipt for the current source."
                    ),
                }
            ],
        )

    def test_publication_freshness_reports_unmapped_markdown_outputs(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        stale_output = self.translation_root / "retired" / "episode-0000.md"
        stale_output.parent.mkdir()
        stale_output.write_bytes(b"stale translated output")

        findings = audit_published_translation_freshness(
            self.run_root.parent,
            self.translation_root,
            [
                {
                    "translation_file": "episode-0001.md",
                    "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                    "source_version_id": self.plan["episodes"][0][
                        "source_version_id"
                    ],
                    "source_sha256": self.plan["episodes"][0]["source_sha256"],
                }
            ],
        )

        self.assertEqual(
            findings,
            [
                {
                    "translation_file": "episode-0001.md",
                    "status": "verified",
                    "detail": (
                        "Published bytes match a valid K4 receipt for the current source."
                    ),
                },
                {
                    "translation_file": "retired/episode-0000.md",
                    "status": "unindexed",
                    "detail": (
                        "Markdown translation has no current chapter mapping."
                    ),
                },
            ],
        )

    def test_publication_freshness_bounds_unmapped_output_scan(self):
        (self.translation_root / "extra-a.md").write_bytes(b"extra output a")
        (self.translation_root / "extra-b.md").write_bytes(b"extra output b")
        expected = [
            {
                "translation_file": "episode-0001.md",
                "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                "source_version_id": self.plan["episodes"][0]["source_version_id"],
                "source_sha256": self.plan["episodes"][0]["source_sha256"],
            }
        ]

        with patch("translation_review._MAX_FRESHNESS_OUTPUT_ENTRIES", 1):
            findings = audit_published_translation_freshness(
                self.run_root.parent,
                self.translation_root,
                expected,
            )

        scan_finding = next(
            finding
            for finding in findings
            if finding["translation_file"] == "translation_root_scan"
        )
        self.assertEqual(scan_finding["status"], "unverified")

    def test_unmapped_output_scan_marks_symlink_without_following_it(self):
        entry = MagicMock()
        entry.name = "linked.md"
        entry.path = str(self.translation_root / "linked.md")
        entry.is_symlink.return_value = True
        scanner = MagicMock()
        scanner.__enter__.return_value = iter([entry])

        with patch("translation_review.os.scandir", return_value=scanner):
            findings = translation_review._audit_unmapped_translation_outputs(
                self.translation_root,
                set(),
            )

        self.assertEqual(
            findings,
            [
                {
                    "translation_file": "linked.md",
                    "status": "invalid",
                    "detail": "Translation output contains a symbolic link.",
                }
            ],
        )
        entry.is_dir.assert_not_called()
        entry.is_file.assert_not_called()

    def test_unmapped_output_scan_reports_enumeration_errors(self):
        with patch(
            "translation_review.os.scandir",
            side_effect=PermissionError("synthetic permission failure"),
        ):
            findings = translation_review._audit_unmapped_translation_outputs(
                self.translation_root,
                set(),
            )

        self.assertEqual(
            findings,
            [
                {
                    "translation_file": ".",
                    "status": "unverified",
                    "detail": (
                        "Translation output directory could not be safely "
                        "enumerated."
                    ),
                }
            ],
        )

    def test_publication_freshness_marks_verified_old_source_as_stale(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        findings = audit_published_translation_freshness(
            self.run_root.parent,
            self.translation_root,
            [
                {
                    "translation_file": "episode-0001.md",
                    "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                    "source_version_id": "newer-source-version",
                    "source_sha256": "b" * 64,
                }
            ],
        )

        self.assertEqual(findings[0]["status"], "stale")

    def test_publication_freshness_does_not_trust_unreviewed_output(self):
        (self.translation_root / "episode-0001.md").write_bytes(b"unreviewed output")

        findings = audit_published_translation_freshness(
            self.run_root.parent,
            self.translation_root,
            [
                {
                    "translation_file": "episode-0001.md",
                    "tm_key": f"source-edition:{self.work_id}:{self.episode_id}",
                    "source_version_id": self.plan["episodes"][0][
                        "source_version_id"
                    ],
                    "source_sha256": self.plan["episodes"][0]["source_sha256"],
                }
            ],
        )

        self.assertEqual(findings[0]["status"], "unverified")

    def _ai_review_policy(self):
        path = self.root / "review-policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_id": "synthetic-ai-review",
                    "revision": 1,
                    "issue_codes": [
                        {
                            "code": "omission",
                            "stages": ["fidelity"],
                            "definition": "Synthetic fidelity issue.",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_approved_review_rejects_non_integer_schema_version(self):
        review_path = self._approved_review()
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["schema_version"] = []
        review_path.write_text(
            json.dumps(review, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Translation review schema version is unsupported",
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

    def test_policy_digest_is_validated_before_comparison(self):
        policy_path = self._ai_review_policy()
        with self.assertRaisesRegex(ValueError, "valid policy SHA-256"):
            record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["pass"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                policy_sha256="é" * 64,
                review_policy_file=policy_path,
                reviewed_candidate_sha256=hashlib.sha256(
                    self.draft_bytes
                ).hexdigest(),
            )

    @staticmethod
    def _ai_assessment(
        *,
        fidelity="pass",
        optimization="low",
        findings=None,
    ):
        return json.dumps(
            {
                "stage_verdicts": {
                    "fidelity": fidelity,
                    "fluency": "pass",
                    "style": "pass",
                },
                "optimization_potential": optimization,
                "publication_checks": {
                    name: "pass" for name in _REVIEW_CHECKS
                },
                "findings": findings or [],
            },
            ensure_ascii=False,
        )

    def test_prepare_review_and_publish_only_after_all_checks_pass(self):
        review_path = self._approved_review()
        report = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        output = self.translation_root / "episode-0001.md"

        self.assertEqual(report["status"], "published")
        self.assertTrue(report["created"])
        self.assertEqual(report["run_status"], "published")
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_bytes(), self.draft_bytes)
        review_snapshot = (
            self.run_root
            / "Published"
            / "ReviewSnapshots"
            / f"{self.episode_id}.json"
        )
        self.assertTrue(review_snapshot.is_file())
        self.assertEqual(
            review_snapshot.read_bytes(),
            review_path.read_bytes(),
        )
        receipt = json.loads(
            (
                self.run_root
                / "Published"
                / f"{self.episode_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["draft_sha256"], hashlib.sha256(self.draft_bytes).hexdigest())

    def test_ai_review_publishes_only_after_two_passes_and_recovers_idempotently(self):
        policy_path = self._ai_review_policy()
        prompts = []

        async def assessor(prompt, _assessment_number):
            prompts.append(prompt)
            return self._ai_assessment()

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

            self.assertEqual(result["status"], "published")
            self.assertEqual(len(prompts), 2)
            self.assertIn("fresh adversarial review", prompts[1])
            self.assertEqual(
                (self.translation_root / "episode-0001.md").read_bytes(),
                self.draft_bytes,
            )
            chain = translation_review.load_review_decision_chain(
                self.run_root,
                episode_id=self.episode_id,
            )
            self.assertEqual(chain[-1]["schema_version"], 4)
            self.assertEqual(
                chain[-1]["final_review_gate"],
                {"convergence": "pass", "publication_checks": "pass"},
            )
            report_path = (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / (
                    f"review-{hashlib.sha256(self.draft_bytes).hexdigest()}-"
                    f"{hashlib.sha256(policy_path.read_bytes()).hexdigest()}.json"
                )
            )
            report_text = report_path.read_text(encoding="utf-8")
            self.assertNotIn("Synthetic source paragraph", report_text)

            def must_not_run(_prompt, _assessment_number):
                raise AssertionError("A recovered pass must not call the reviewer.")

            recovered = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(recovered["status"], "published")
        self.assertEqual(len(prompts), 2)

    def test_ai_pass_recovers_after_publication_snapshot_write_failure(self):
        policy_path = self._ai_review_policy()
        prompts = []

        async def assessor(prompt, assessment_number):
            prompts.append((prompt, assessment_number))
            return self._ai_assessment()

        snapshot_root = self.run_root / "Published" / "ReviewSnapshots"
        original_write = translation_review._write_new_bytes_atomically
        failure_seen = False

        def fail_snapshot_once(root, relative_path, content):
            nonlocal failure_seen
            if (
                not failure_seen
                and Path(root).resolve() == snapshot_root.resolve()
                and relative_path == f"{self.episode_id}.json"
            ):
                failure_seen = True
                raise OSError("synthetic review snapshot write failure")
            return original_write(root, relative_path, content)

        with (
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                translation_review,
                "_write_new_bytes_atomically",
                side_effect=fail_snapshot_once,
            ),
            self.assertRaisesRegex(OSError, "review snapshot write failure"),
        ):
            asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

        chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertEqual(chain[-1]["transition"]["status"], "passed")
        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            (self.translation_root / "episode-0001.md").read_bytes(),
            self.draft_bytes,
        )
        self.assertTrue(
            (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / f"publication-{chain[-1]['decision_sha256']}.json"
            ).is_file()
        )
        self.assertFalse(
            (snapshot_root / f"{self.episode_id}.json").exists()
        )
        self.assertFalse(
            (
                self.run_root
                / "Published"
                / f"{self.episode_id}.json"
            ).exists()
        )

        def must_not_run(_prompt, _assessment_number):
            raise AssertionError("Recovery must not call the reviewer.")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            recovered = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(recovered["status"], "published")
        self.assertEqual(len(prompts), 2)
        self.assertTrue(recovered["publication"]["review_snapshot_created"])
        self.assertTrue(recovered["publication"]["receipt_created"])
        self.assertEqual(recovered["publication"]["run_status"], "published")
        self.assertEqual(
            (snapshot_root / f"{self.episode_id}.json").read_bytes(),
            (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / f"publication-{chain[-1]['decision_sha256']}.json"
            ).read_bytes(),
        )

    def test_ai_pass_recovers_after_process_termination_before_publication_snapshot(
        self,
    ):
        policy_path = self._ai_review_policy()
        marker_path = self.root / "publication-crash-checkpoint.json"
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=_review_until_publication_snapshot_checkpoint,
            args=(
                str(self.run_root),
                self.episode_id,
                str(policy_path),
                str(marker_path),
                ready,
            ),
        )
        process.start()

        try:
            self.assertTrue(ready.wait(timeout=30))
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(
                marker,
                {
                    "checkpoint": "before_publication_review_snapshot",
                    "episode_id": self.episode_id,
                    "pid": process.pid,
                },
            )
            self.assertTrue(process.is_alive())

            chain = translation_review.load_review_decision_chain(
                self.run_root,
                episode_id=self.episode_id,
                expected_run_id=self.run_manifest["run_id"],
                expected_work_id=self.work_id,
                expected_source_version_id=self.plan["episodes"][0][
                    "source_version_id"
                ],
                expected_source_sha256=self.plan["episodes"][0][
                    "source_sha256"
                ],
            )
            self.assertEqual(len(chain), 1)
            decision = chain[-1]
            self.assertEqual(decision["transition"]["status"], "passed")
            self.assertEqual(
                decision["candidate_sha256"],
                hashlib.sha256(self.draft_bytes).hexdigest(),
            )

            report_path = (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / (
                    f"review-{decision['candidate_sha256']}-"
                    f"{hashlib.sha256(policy_path.read_bytes()).hexdigest()}.json"
                )
            )
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes.decode("utf-8"))
            report_sha256 = hashlib.sha256(
                ai_translation_review._canonical_json(report)
            ).hexdigest()
            self.assertEqual(
                decision["reviewer_id"],
                f"ai-final-review:{'e' * 64}:{report_sha256}",
            )

            decision_files = list(
                (
                    self.run_root
                    / "ReviewDecisions"
                    / self.episode_id
                ).glob("revision-*.json")
            )
            self.assertEqual(len(decision_files), 1)
            decision_path = decision_files[0]
            publication_review_path = (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / f"publication-{decision['decision_sha256']}.json"
            )
            publication_review = json.loads(
                publication_review_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                publication_review["decision_sha256"],
                decision["decision_sha256"],
            )
            self.assertEqual(
                publication_review["candidate_sha256"],
                decision["candidate_sha256"],
            )
            self.assertEqual(
                publication_review["reviewer_id"],
                decision["reviewer_id"],
            )
            self.assertEqual(publication_review["decision"], "approved")
            self.assertEqual(
                publication_review["checks"],
                {name: "pass" for name in _REVIEW_CHECKS},
            )
            published_path = self.translation_root / "episode-0001.md"
            snapshot_path = (
                self.run_root
                / "Published"
                / "ReviewSnapshots"
                / f"{self.episode_id}.json"
            )
            receipt_path = (
                self.run_root / "Published" / f"{self.episode_id}.json"
            )
            state_path = self.run_root / "run_state.json"

            self.assertTrue(publication_review_path.is_file())
            self.assertEqual(published_path.read_bytes(), self.draft_bytes)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "running",
            )
            self.assertFalse(snapshot_path.exists())
            self.assertFalse(receipt_path.exists())

            authenticated_bytes = {
                path: path.read_bytes()
                for path in (
                    report_path,
                    decision_path,
                    publication_review_path,
                    published_path,
                    state_path,
                )
            }
            process.terminate()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())
            _assert_checkpoint_worker_was_terminated(self, process)
            for path, expected_bytes in authenticated_bytes.items():
                self.assertEqual(path.read_bytes(), expected_bytes)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)

        def must_not_run(_prompt, _assessment_number):
            raise AssertionError("Recovery must not call the reviewer.")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            recovered = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(recovered["status"], "published")
        self.assertTrue(recovered["publication"]["review_snapshot_created"])
        self.assertTrue(recovered["publication"]["receipt_created"])
        self.assertEqual(recovered["publication"]["run_status"], "published")
        self.assertEqual(published_path.read_bytes(), self.draft_bytes)
        self.assertEqual(
            snapshot_path.read_bytes(),
            publication_review_path.read_bytes(),
        )
        self.assertEqual(
            json.loads(receipt_path.read_text(encoding="utf-8"))["status"],
            "published",
        )
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["status"],
            "published",
        )
        recovered_chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertEqual(len(recovered_chain), 1)
        self.assertEqual(
            recovered_chain[-1]["decision_sha256"],
            decision["decision_sha256"],
        )
        self.assertTrue(
            has_verified_translation_publication(
                self.run_root.parent,
                work_id=self.work_id,
                episode_id=self.episode_id,
                source_version_id=self.plan["episodes"][0][
                    "source_version_id"
                ],
                source_sha256=self.plan["episodes"][0]["source_sha256"],
                translation_file="episode-0001.md",
                translation_root=self.translation_root,
            )
        )

        def persisted_tree_bytes():
            files = {}
            for root in (self.run_root, self.translation_root):
                for path in root.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        files[str(path.relative_to(self.root))] = path.read_bytes()
            return files

        first_recovery_bytes = persisted_tree_bytes()
        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            reopened = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(reopened["status"], "published")
        self.assertEqual(persisted_tree_bytes(), first_recovery_bytes)

    def test_ai_pass_recovers_after_process_termination_before_run_state_published(
        self,
    ):
        policy_path = self._ai_review_policy()
        marker_path = self.root / "run-state-crash-checkpoint.json"
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=_review_until_run_state_checkpoint,
            args=(
                str(self.run_root),
                self.episode_id,
                str(policy_path),
                str(marker_path),
                ready,
            ),
        )
        process.start()

        try:
            self.assertTrue(ready.wait(timeout=30))
            self.assertEqual(
                json.loads(marker_path.read_text(encoding="utf-8")),
                {
                    "checkpoint": "before_run_state_published",
                    "episode_id": self.episode_id,
                    "pid": process.pid,
                },
            )
            self.assertTrue(process.is_alive())

            chain = translation_review.load_review_decision_chain(
                self.run_root,
                episode_id=self.episode_id,
                expected_run_id=self.run_manifest["run_id"],
                expected_work_id=self.work_id,
                expected_source_version_id=self.plan["episodes"][0][
                    "source_version_id"
                ],
                expected_source_sha256=self.plan["episodes"][0][
                    "source_sha256"
                ],
            )
            self.assertEqual(len(chain), 1)
            decision = chain[-1]
            self.assertEqual(decision["transition"]["status"], "passed")
            self.assertEqual(
                decision["candidate_sha256"],
                hashlib.sha256(self.draft_bytes).hexdigest(),
            )

            report_path = (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / (
                    f"review-{decision['candidate_sha256']}-"
                    f"{hashlib.sha256(policy_path.read_bytes()).hexdigest()}.json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report_sha256 = hashlib.sha256(
                ai_translation_review._canonical_json(report)
            ).hexdigest()
            self.assertEqual(
                decision["reviewer_id"],
                f"ai-final-review:{'e' * 64}:{report_sha256}",
            )

            decision_path = next(
                (
                    self.run_root
                    / "ReviewDecisions"
                    / self.episode_id
                ).glob("revision-*.json")
            )
            publication_review_path = (
                self.run_root
                / "AIReviews"
                / self.episode_id
                / f"publication-{decision['decision_sha256']}.json"
            )
            publication_review = json.loads(
                publication_review_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                publication_review["decision_sha256"],
                decision["decision_sha256"],
            )
            self.assertEqual(
                publication_review["candidate_sha256"],
                decision["candidate_sha256"],
            )

            published_path = self.translation_root / "episode-0001.md"
            snapshot_path = (
                self.run_root
                / "Published"
                / "ReviewSnapshots"
                / f"{self.episode_id}.json"
            )
            receipt_path = (
                self.run_root / "Published" / f"{self.episode_id}.json"
            )
            state_path = self.run_root / "run_state.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "published")
            self.assertEqual(
                receipt["decision_sha256"],
                decision["decision_sha256"],
            )
            self.assertEqual(
                receipt["candidate_sha256"],
                decision["candidate_sha256"],
            )
            self.assertEqual(published_path.read_bytes(), self.draft_bytes)
            self.assertEqual(
                snapshot_path.read_bytes(),
                publication_review_path.read_bytes(),
            )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "running",
            )
            self.assertTrue(
                has_verified_translation_publication(
                    self.run_root.parent,
                    work_id=self.work_id,
                    episode_id=self.episode_id,
                    source_version_id=self.plan["episodes"][0][
                        "source_version_id"
                    ],
                    source_sha256=self.plan["episodes"][0]["source_sha256"],
                    translation_file="episode-0001.md",
                    translation_root=self.translation_root,
                )
            )
            authenticated_bytes = {
                path: path.read_bytes()
                for path in (
                    report_path,
                    decision_path,
                    publication_review_path,
                    published_path,
                    snapshot_path,
                    receipt_path,
                    state_path,
                )
            }

            process.terminate()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())
            _assert_checkpoint_worker_was_terminated(self, process)
            for path, expected_bytes in authenticated_bytes.items():
                self.assertEqual(path.read_bytes(), expected_bytes)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)

        def must_not_run(_prompt, _assessment_number):
            raise AssertionError("Recovery must not call the reviewer.")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            recovered = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(recovered["status"], "published")
        self.assertFalse(recovered["publication"]["created"])
        self.assertFalse(recovered["publication"]["review_snapshot_created"])
        self.assertFalse(recovered["publication"]["receipt_created"])
        self.assertEqual(recovered["publication"]["run_status"], "published")
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["status"],
            "published",
        )
        recovered_chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertEqual(len(recovered_chain), 1)
        self.assertEqual(
            recovered_chain[-1]["decision_sha256"],
            decision["decision_sha256"],
        )

        first_recovery_bytes = {
            str(path.relative_to(self.root)): path.read_bytes()
            for root in (self.run_root, self.translation_root)
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            reopened = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(reopened["status"], "published")
        self.assertEqual(
            {
                str(path.relative_to(self.root)): path.read_bytes()
                for root in (self.run_root, self.translation_root)
                for path in root.rglob("*")
                if path.is_file() and not path.is_symlink()
            },
            first_recovery_bytes,
        )

    def test_ai_review_refuses_tampered_stored_report_on_recovery(self):
        policy_path = self._ai_review_policy()

        async def assessor(_prompt, _assessment_number):
            return self._ai_assessment()

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )
            report_path = (
                self.run_root / result["review_report_relative_path"]
            )
            tampered = json.loads(report_path.read_text(encoding="utf-8"))
            tampered["final_review_gate"]["convergence"] = "inconclusive"
            report_path.write_text(
                json.dumps(tampered, ensure_ascii=False),
                encoding="utf-8",
            )

            def must_not_run(_prompt, _assessment_number):
                raise AssertionError("Recovery must not call the reviewer.")

            with self.assertRaisesRegex(ValueError, "inconsistent evidence"):
                asyncio.run(
                    ai_translation_review.review_translation_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=must_not_run,
                        reviewer_model="synthetic-reviewer",
                    )
                )

    def test_ai_review_recovers_durable_first_assessment_after_process_termination(
        self,
    ):
        policy_path = self._ai_review_policy()
        marker_path = self.root / "assessment-crash-checkpoint.json"
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=_review_until_second_assessment_checkpoint,
            args=(
                str(self.run_root),
                self.episode_id,
                str(policy_path),
                str(marker_path),
                ready,
            ),
        )
        process.start()

        try:
            self.assertTrue(ready.wait(timeout=30))
            self.assertEqual(
                json.loads(marker_path.read_text(encoding="utf-8")),
                {
                    "checkpoint": "before_second_assessment_response",
                    "episode_id": self.episode_id,
                    "pid": process.pid,
                },
            )
            self.assertTrue(process.is_alive())

            review_context = ai_translation_review._load_review_context(
                self.run_root,
                self.episode_id,
                candidate_file=None,
                review_policy_file=policy_path,
                max_review_text_chars=64_000,
                max_rework_attempts=2,
            )
            episode_root, report_filename = ai_translation_review._report_path(
                review_context
            )
            assessment_filename = ai_translation_review._assessment_filename(
                review_context,
                "e" * 64,
                1,
            )
            assessment_path = episode_root / assessment_filename
            assessment_bytes = assessment_path.read_bytes()
            assessment_record = json.loads(assessment_bytes.decode("utf-8"))
            assessment = ai_translation_review._validate_stored_assessment(
                assessment_record,
                review_context,
                "e" * 64,
                1,
            )
            self.assertEqual(
                assessment_record,
                {
                    **ai_translation_review._assessment_identity(
                        review_context,
                        "e" * 64,
                        1,
                    ),
                    "assessment": assessment,
                },
            )
            self.assertEqual(
                assessment_bytes,
                ai_translation_review._canonical_json(assessment_record),
            )
            self.assertFalse((episode_root / report_filename).exists())
            decision_root = self.run_root / "ReviewDecisions" / self.episode_id
            self.assertFalse(
                decision_root.exists()
                and any(decision_root.glob("revision-*.json"))
            )
            self.assertFalse(
                (self.translation_root / "episode-0001.md").exists()
            )
            self.assertEqual(
                json.loads(
                    (self.run_root / "run_state.json").read_text(
                        encoding="utf-8"
                    )
                )["status"],
                "running",
            )

            process.terminate()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())
            _assert_checkpoint_worker_was_terminated(self, process)
            self.assertEqual(assessment_path.read_bytes(), assessment_bytes)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)

        assessor_calls = []

        async def assessor(_prompt, assessment_number):
            assessor_calls.append(assessment_number)
            return self._ai_assessment()

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            recovered = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(assessor_calls, [2])
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(assessment_path.read_bytes(), assessment_bytes)

        persisted_tree_bytes = {
            str(path.relative_to(self.root)): path.read_bytes()
            for root in (self.run_root, self.translation_root)
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

        def must_not_run(_prompt, _assessment_number):
            raise AssertionError("Published recovery must reuse the report.")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            reopened = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=must_not_run,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(reopened["status"], "published")
        self.assertEqual(
            {
                str(path.relative_to(self.root)): path.read_bytes()
                for root in (self.run_root, self.translation_root)
                for path in root.rglob("*")
                if path.is_file() and not path.is_symlink()
            },
            persisted_tree_bytes,
        )

    def test_ai_review_refuses_tampered_stored_assessment(self):
        policy_path = self._ai_review_policy()

        async def fail_second_assessment(_prompt, assessment_number):
            if assessment_number == 1:
                return self._ai_assessment()
            raise RuntimeError("synthetic provider interruption")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic provider interruption",
            ):
                asyncio.run(
                    ai_translation_review.review_translation_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=fail_second_assessment,
                        reviewer_model="synthetic-reviewer",
                    )
                )

            review_context = ai_translation_review._load_review_context(
                self.run_root,
                self.episode_id,
                candidate_file=None,
                review_policy_file=policy_path,
                max_review_text_chars=64_000,
                max_rework_attempts=2,
            )
            episode_root, _ = ai_translation_review._report_path(review_context)
            assessment_path = episode_root / (
                ai_translation_review._assessment_filename(
                    review_context,
                    "e" * 64,
                    1,
                )
            )
            tampered = json.loads(assessment_path.read_text(encoding="utf-8"))
            tampered["assessment_number"] = 2
            assessment_path.write_bytes(
                ai_translation_review._canonical_json(tampered)
            )

            def must_not_run(_prompt, _assessment_number):
                raise AssertionError("Invalid stored assessment must fail closed.")

            with self.assertRaisesRegex(ValueError, "identity"):
                asyncio.run(
                    ai_translation_review.review_translation_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=must_not_run,
                        reviewer_model="synthetic-reviewer",
                    )
                )

    def test_ai_review_failure_requests_rework_without_publishing(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def assessor(_prompt, _assessment_number):
            return self._ai_assessment(fidelity="fail", findings=finding)

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(result["status"], "rework")
        self.assertEqual(
            result["issue_codes_by_stage"]["fidelity"],
            ["omission"],
        )
        self.assertEqual(
            result["findings_by_assessment"][0][0]["source_paragraph"],
            0,
        )
        self.assertTrue(
            (
                self.run_root
                / result["review_report_relative_path"]
            ).is_file()
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())
        self.assertEqual(
            translation_review.load_review_decision_chain(
                self.run_root,
                episode_id=self.episode_id,
            )[-1]["transition"]["reason"],
            "quality_failure",
        )

    def test_auto_review_rework_and_publish_is_hash_bound(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]
        reviewer_calls = []
        rework_calls = []

        async def assessor(prompt, assessment_number):
            reviewer_calls.append((prompt, assessment_number))
            if "Synthetic revised paragraph." in prompt:
                return self._ai_assessment()
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        async def generator(prompt, revision):
            rework_calls.append((prompt, revision))
            return json.dumps(
                {
                    "schema_version": 1,
                    "paragraph_revisions": [
                        {
                            "paragraph_index": 0,
                            "translation": "「Synthetic revised paragraph.」",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        with (
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                ai_translation_rework,
                "_provider_fingerprint",
                return_value="f" * 64,
            ),
        ):
            result = asyncio.run(
                ai_translation_workflow.run_ai_translation_workflow(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    generator=generator,
                    reviewer_model="synthetic-reviewer",
                    rework_model="synthetic-reworker",
                    max_rework_attempts=1,
                )
            )

        candidate_path = (
            self.run_root
            / "ReviewCandidates"
            / self.episode_id
            / "revision-0001.md"
        )
        rework_report_path = (
            self.run_root
            / "AIReworks"
            / self.episode_id
            / "revision-0001.json"
        )
        self.assertEqual(result["status"], "published")
        self.assertEqual([entry["status"] for entry in result["review_history"]], [
            "rework",
            "published",
        ])
        self.assertEqual(len(reviewer_calls), 4)
        self.assertEqual(len(rework_calls), 1)
        self.assertIn('"editable":true', rework_calls[0][0])
        self.assertEqual(rework_calls[0][1], 1)
        self.assertEqual(
            candidate_path.read_bytes(),
            "「Synthetic revised paragraph.」\n".encode("utf-8"),
        )
        self.assertEqual(
            (self.translation_root / "episode-0001.md").read_bytes(),
            candidate_path.read_bytes(),
        )
        rework_report = json.loads(
            rework_report_path.read_text(encoding="utf-8")
        )
        self.assertEqual(rework_report["origin"], "generated")
        self.assertEqual(
            rework_report["candidate_sha256"],
            hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        )
        self.assertNotIn(
            "Synthetic revised paragraph.",
            rework_report_path.read_text(encoding="utf-8"),
        )
        chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertEqual(
            [record["transition"]["status"] for record in chain],
            ["rework", "passed"],
        )

    def test_workflow_cli_runs_review_rework_and_publication_end_to_end(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]
        reviewer_calls = []
        rework_calls = []

        async def assessor(prompt, assessment_number):
            reviewer_calls.append((prompt, assessment_number))
            if "Synthetic revised paragraph." in prompt:
                return self._ai_assessment()
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        async def generator(prompt, revision):
            rework_calls.append((prompt, revision))
            return json.dumps(
                {
                    "schema_version": 1,
                    "paragraph_revisions": [
                        {
                            "paragraph_index": 0,
                            "translation": "「Synthetic revised paragraph.」",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        async def run_with_synthetic_models(*args, **kwargs):
            return await ai_translation_workflow.run_ai_translation_workflow(
                *args,
                assessor=assessor,
                generator=generator,
                reviewer_model="synthetic-reviewer",
                rework_model="synthetic-reworker",
                **kwargs,
            )

        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch(
                "scripts.run_ai_translation_workflow.Config.load_config"
            ) as load_config,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_final_review_provider_configuration"
            ) as validate_reviewer,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_translation_rework_provider_configuration"
            ) as validate_reworker,
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                ai_translation_rework,
                "_provider_fingerprint",
                return_value="f" * 64,
            ),
            patch(
                "scripts.run_ai_translation_workflow.run_ai_translation_workflow",
                side_effect=run_with_synthetic_models,
            ) as run_workflow,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            exit_code = run_ai_translation_workflow_main(
                [
                    "--project",
                    "synthetic-project",
                    "--run-directory",
                    str(self.run_root),
                    "--episode-id",
                    self.episode_id,
                    "--review-policy-file",
                    str(policy_path),
                    "--max-rework-attempts",
                    "1",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(report["status"], "published")
        self.assertEqual(
            [entry["status"] for entry in report["review_history"]],
            ["rework", "published"],
        )
        self.assertEqual(len(reviewer_calls), 4)
        self.assertEqual(len(rework_calls), 1)
        load_config.assert_called_once_with(
            project="synthetic-project",
            config_file=None,
        )
        validate_reviewer.assert_called_once_with()
        validate_reworker.assert_called_once_with()
        run_workflow.assert_called_once()
        published_path = self.translation_root / "episode-0001.md"
        candidate_path = (
            self.run_root
            / "ReviewCandidates"
            / self.episode_id
            / "revision-0001.md"
        )
        self.assertEqual(published_path.read_bytes(), candidate_path.read_bytes())

    def test_auto_workflow_reuses_existing_candidate_without_regenerating(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def failing_assessor(_prompt, _assessment_number):
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            first = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=failing_assessor,
                    reviewer_model="synthetic-reviewer",
                    max_rework_attempts=1,
                )
            )
        self.assertEqual(first["status"], "rework")
        candidate_root = self.run_root / "ReviewCandidates" / self.episode_id
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_path.write_text(
            "「Synthetic revised paragraph.」\n",
            encoding="utf-8",
        )

        async def passing_assessor(_prompt, _assessment_number):
            return self._ai_assessment()

        def must_not_generate(_prompt, _revision):
            raise AssertionError("An existing candidate must be resumed.")

        with (
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                ai_translation_rework,
                "_provider_fingerprint",
                return_value="f" * 64,
            ),
        ):
            result = asyncio.run(
                ai_translation_workflow.run_ai_translation_workflow(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=passing_assessor,
                    generator=must_not_generate,
                    reviewer_model="synthetic-reviewer",
                    rework_model="synthetic-reworker",
                )
            )

        self.assertEqual(result["status"], "published")
        self.assertEqual(result["rework_history"][0]["origin"], "reused_existing")
        self.assertTrue(
            (
                self.run_root
                / "AIReworks"
                / self.episode_id
                / "revision-0001.json"
            ).is_file()
        )

    def test_auto_rework_cannot_bypass_human_budget_extension(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def failing_assessor(_prompt, _assessment_number):
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=failing_assessor,
                    reviewer_model="synthetic-reviewer",
                    max_rework_attempts=0,
                )
            )
        self.assertEqual(result["status"], "needs_human")
        with patch.object(
            ai_translation_rework,
            "_provider_fingerprint",
            return_value="f" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "Human approval"):
                asyncio.run(
                    ai_translation_rework.generate_translation_rework_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        generator=lambda _prompt, _revision: "{}",
                        rework_model="synthetic-reworker",
                    )
                )
        self.assertFalse(
            (
                self.run_root
                / "ReviewCandidates"
                / self.episode_id
                / "revision-0001.md"
            ).exists()
        )

    def test_auto_workflow_resumes_after_human_budget_extension(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]
        reviewer_calls = []
        generator_calls = []

        async def assessor(prompt, assessment_number):
            reviewer_calls.append((prompt, assessment_number))
            if "Synthetic revised paragraph." in prompt:
                return self._ai_assessment()
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        async def generator(prompt, revision):
            generator_calls.append((prompt, revision))
            return json.dumps(
                {
                    "schema_version": 1,
                    "paragraph_revisions": [
                        {
                            "paragraph_index": 0,
                            "translation": "「Synthetic revised paragraph.」",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            first = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                    max_rework_attempts=0,
                )
            )
        self.assertEqual(first["status"], "needs_human")
        self.assertEqual(first["transition"]["reason"], "rework_limit_reached")
        self.assertEqual(len(reviewer_calls), 2)

        resolution = resolve_translation_review(
            self.run_root,
            self.episode_id,
            action="increase_budget",
            reviewer_id="synthetic operator",
            reviewed_at_utc="2026-11-20T00:00:00Z",
            rationale="Approve one additional synthetic revision.",
            reviewed_decision_sha256=first["decision_sha256"],
            new_max_rework_attempts=1,
        )
        self.assertEqual(resolution["action"], "increase_budget")
        self.assertEqual(resolution["new_max_rework_attempts"], 1)

        with (
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                ai_translation_rework,
                "_provider_fingerprint",
                return_value="f" * 64,
            ),
        ):
            resumed = asyncio.run(
                ai_translation_workflow.run_ai_translation_workflow(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    generator=generator,
                    reviewer_model="synthetic-reviewer",
                    rework_model="synthetic-reworker",
                )
            )

        candidate_path = (
            self.run_root
            / "ReviewCandidates"
            / self.episode_id
            / "revision-0001.md"
        )
        published_path = self.translation_root / "episode-0001.md"
        chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertEqual(resumed["status"], "published")
        self.assertEqual(resumed["candidate_revision"], 1)
        self.assertEqual(len(generator_calls), 1)
        self.assertEqual(len(reviewer_calls), 4)
        self.assertEqual(
            [item["transition"]["status"] for item in chain],
            ["needs_human", "passed"],
        )
        self.assertEqual(
            chain[-1]["max_rework_attempts"],
            resolution["new_max_rework_attempts"],
        )
        self.assertEqual(candidate_path.read_bytes(), published_path.read_bytes())
        self.assertTrue(published_path.is_file())

    def test_concurrent_ai_reviews_reuse_one_assessment(self):
        policy_path = self._ai_review_policy()
        assessor_calls = []

        async def assessor(_prompt, assessment_number):
            assessor_calls.append(assessment_number)
            await asyncio.sleep(0.01)
            return self._ai_assessment()

        async def run_concurrent_reviews():
            return await asyncio.gather(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                ),
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                ),
            )

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            results = asyncio.run(run_concurrent_reviews())

        self.assertEqual(assessor_calls, [1, 2])
        self.assertEqual([result["status"] for result in results], ["published"] * 2)
        self.assertEqual(
            results[0]["decision_sha256"],
            results[1]["decision_sha256"],
        )

    def test_concurrent_ai_workflows_run_one_rework_and_publish(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]
        reviewer_calls = []
        generator_calls = []

        async def assessor(prompt, assessment_number):
            reviewer_calls.append(assessment_number)
            await asyncio.sleep(0.01)
            if "Synthetic revised paragraph." in prompt:
                return self._ai_assessment()
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        async def generator(prompt, revision):
            generator_calls.append(revision)
            await asyncio.sleep(0.01)
            return json.dumps(
                {
                    "schema_version": 1,
                    "paragraph_revisions": [
                        {
                            "paragraph_index": 0,
                            "translation": "「Synthetic revised paragraph.」",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        async def run_concurrent_workflows():
            return await asyncio.gather(
                *(
                    ai_translation_workflow.run_ai_translation_workflow(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=assessor,
                        generator=generator,
                        reviewer_model="synthetic-reviewer",
                        rework_model="synthetic-reworker",
                    )
                    for _ in range(2)
                )
            )

        with (
            patch.object(
                ai_translation_review,
                "_provider_fingerprint",
                return_value="e" * 64,
            ),
            patch.object(
                ai_translation_rework,
                "_provider_fingerprint",
                return_value="f" * 64,
            ),
        ):
            results = asyncio.run(run_concurrent_workflows())

        self.assertEqual([result["status"] for result in results], ["published"] * 2)
        self.assertEqual(reviewer_calls, [1, 2, 1, 2])
        self.assertEqual(generator_calls, [1])
        self.assertEqual(
            translation_review.load_review_decision_chain(
                self.run_root,
                episode_id=self.episode_id,
            )[-1]["candidate_revision"],
            1,
        )

    def test_episode_workflow_lock_serializes_across_processes(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_episode_workflow_lock,
            args=(str(self.run_root), self.episode_id, ready, release),
        )
        process.start()
        try:
            self.assertTrue(ready.wait(timeout=30))

            async def wait_for_lock():
                entered = asyncio.Event()

                async def acquire():
                    async with _lock_episode_workflow(
                        self.run_root,
                        self.episode_id,
                    ):
                        entered.set()

                task = asyncio.create_task(acquire())
                await asyncio.sleep(0.2)
                was_blocked = not entered.is_set()
                release.set()
                await asyncio.wait_for(task, timeout=10)
                return was_blocked

            self.assertTrue(asyncio.run(wait_for_lock()))
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
        finally:
            release.set()
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    def test_episode_workflow_lock_does_not_write_marker_before_locking(self):
        lock_root = self.run_root / "AIWorkflowLocks"

        async def acquire_once():
            async with _lock_episode_workflow(self.run_root, self.episode_id):
                lock_file = next(lock_root.glob("*.lock"))
                self.assertEqual(lock_file.stat().st_size, 0)

        asyncio.run(acquire_once())

    def test_episode_workflow_lock_is_released_after_process_exit(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_episode_workflow_lock,
            args=(str(self.run_root), self.episode_id, ready, release),
        )
        process.start()
        try:
            self.assertTrue(ready.wait(timeout=30))
            process.terminate()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())

            async def reacquire():
                async with _lock_episode_workflow(
                    self.run_root,
                    self.episode_id,
                ):
                    return True

            self.assertTrue(asyncio.run(asyncio.wait_for(reacquire(), timeout=5)))
        finally:
            release.set()
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    def test_invalid_rework_response_does_not_write_candidate_or_decision(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def failing_assessor(_prompt, _assessment_number):
            return self._ai_assessment(
                fidelity="fail",
                findings=finding,
            )

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            first = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=failing_assessor,
                    reviewer_model="synthetic-reviewer",
                    max_rework_attempts=1,
                )
            )
        self.assertEqual(first["status"], "rework")
        initial_chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )

        async def invalid_generator(_prompt, _revision):
            return '{"schema_version":1,"paragraph_revisions":[],"extra":true}'

        with patch.object(
            ai_translation_rework,
            "_provider_fingerprint",
            return_value="f" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "fields do not match schema"):
                asyncio.run(
                    ai_translation_rework.generate_translation_rework_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        generator=invalid_generator,
                        rework_model="synthetic-reworker",
                    )
                )

        candidate_path = (
            self.run_root
            / "ReviewCandidates"
            / self.episode_id
            / "revision-0001.md"
        )
        report_path = (
            self.run_root
            / "AIReworks"
            / self.episode_id
            / "revision-0001.json"
        )
        current_chain = translation_review.load_review_decision_chain(
            self.run_root,
            episode_id=self.episode_id,
        )
        self.assertFalse(candidate_path.exists())
        self.assertFalse(report_path.exists())
        self.assertEqual(
            [item["decision_sha256"] for item in current_chain],
            [item["decision_sha256"] for item in initial_chain],
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_rework_response_is_strict_and_paragraph_boundaries_are_preserved(self):
        context = {"target_paragraphs": [1]}
        with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
            ai_translation_rework._parse_rework_response(
                '{"schema_version":1,"schema_version":1,"paragraph_revisions":[]}',
                context,
            )
        with self.assertRaisesRegex(ValueError, "invalid target index"):
            ai_translation_rework._parse_rework_response(
                json.dumps(
                    {
                        "schema_version": 1,
                        "paragraph_revisions": [
                            {"paragraph_index": 0, "translation": "changed"}
                        ],
                    }
                ),
                context,
            )

        revised = ai_translation_rework._apply_paragraph_revisions(
            "  first\r\n\r\n  second  \n\nthird\n",
            {1: "revised"},
        )
        self.assertEqual(revised, "  first\r\n\r\n  revised  \n\nthird\n")

    def test_ai_review_disagreement_requires_human_without_publishing(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def assessor(_prompt, assessment_number):
            if assessment_number == 1:
                return self._ai_assessment()
            return self._ai_assessment(fidelity="fail", findings=finding)

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["transition"]["reason"], "conflicting_verdicts")
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_ai_review_material_optimization_potential_requires_human(self):
        policy_path = self._ai_review_policy()

        async def assessor(_prompt, _assessment_number):
            return self._ai_assessment(optimization="material")

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                )
            )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(
            result["transition"]["reason"],
            "final_review_gate_inconclusive",
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_ai_review_can_configure_zero_rework_budget(self):
        policy_path = self._ai_review_policy()
        finding = [
            {
                "stage": "fidelity",
                "code": "omission",
                "source_paragraph": 0,
                "translation_paragraph": 0,
            }
        ]

        async def assessor(_prompt, _assessment_number):
            return self._ai_assessment(fidelity="fail", findings=finding)

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            result = asyncio.run(
                ai_translation_review.review_translation_candidate(
                    self.run_root,
                    self.episode_id,
                    review_policy_file=policy_path,
                    assessor=assessor,
                    reviewer_model="synthetic-reviewer",
                    max_rework_attempts=0,
                )
            )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(
            result["transition"]["reason"],
            "rework_limit_reached",
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_ai_review_rejects_malformed_response_before_recording_decision(self):
        policy_path = self._ai_review_policy()

        async def assessor(_prompt, _assessment_number):
            return '{"stage_verdicts": {}, "stage_verdicts": {}}'

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                asyncio.run(
                    ai_translation_review.review_translation_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=assessor,
                        reviewer_model="synthetic-reviewer",
                    )
                )

        self.assertFalse(
            (self.run_root / "ReviewDecisions" / self.episode_id).exists()
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_ai_review_rejects_candidate_change_during_assessment(self):
        policy_path = self._ai_review_policy()
        calls = 0

        async def assessor(_prompt, _assessment_number):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.run_root / "Drafts" / "episode-0001.md").write_bytes(
                    "「Changed after assessment.」\n".encode("utf-8")
                )
            return self._ai_assessment()

        with patch.object(
            ai_translation_review,
            "_provider_fingerprint",
            return_value="e" * 64,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "draft changed after the run was completed|"
                "candidate changed after its digest",
            ):
                asyncio.run(
                    ai_translation_review.review_translation_candidate(
                        self.run_root,
                        self.episode_id,
                        review_policy_file=policy_path,
                        assessor=assessor,
                        reviewer_model="synthetic-reviewer",
                    )
                )

        self.assertEqual(calls, 2)
        self.assertFalse(
            (self.run_root / "ReviewDecisions" / self.episode_id).exists()
        )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_hash_bound_review_decision_chain_uses_rework_candidate(self):
        first = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        self.assertEqual(first["candidate_revision"], 0)
        self.assertEqual(first["transition"]["status"], "rework")

        candidate_root = (
            self.run_root / "ReviewCandidates" / self.episode_id
        )
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_path.write_bytes("「Synthetic revised paragraph.」\n".encode("utf-8"))
        second = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
            candidate_file=Path(
                f"ReviewCandidates/{self.episode_id}/revision-0001.md"
            ),
        )

        self.assertEqual(second["candidate_revision"], 1)
        self.assertEqual(second["transition"]["status"], "passed")
        decision_files = list(
            (self.run_root / "ReviewDecisions" / self.episode_id).glob("*.json")
        )
        self.assertEqual(len(decision_files), 2)
        first_record = json.loads(
            next(
                path
                for path in decision_files
                if "revision-0000-" in path.name
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            first_record["issue_codes_by_stage"]["fidelity"],
            ["synthetic_failure"],
        )

    def test_record_decision_requires_reviewed_candidate_digest(self):
        with self.assertRaisesRegex(ValueError, "reviewed candidate SHA-256"):
            _record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["pass"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                policy_sha256="d" * 64,
                max_rework_attempts=1,
            )

    def test_failed_decision_requires_explicit_issue_code(self):
        with self.assertRaisesRegex(ValueError, "require at least one issue code"):
            _record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["fail"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                policy_sha256="d" * 64,
                reviewed_candidate_sha256=hashlib.sha256(
                    self.draft_bytes
                ).hexdigest(),
            )

    def test_decision_cli_parses_and_forwards_stage_issue_codes(self):
        stage_verdicts = {
            "fidelity": ["fail"],
            "fluency": ["pass"],
            "style": ["pass"],
        }
        issue_codes_by_stage = {
            "fidelity": ["omission"],
            "fluency": [],
            "style": [],
        }
        with patch.object(
            review_decision_cli,
            "record_translation_review_decision",
            return_value={"status": "created"},
        ) as record, redirect_stdout(io.StringIO()):
            exit_code = review_decision_cli.main(
                [
                    "--run-directory",
                    str(self.run_root),
                    "--episode-id",
                    self.episode_id,
                    "--reviewer",
                    "synthetic reviewer",
                    "--reviewed-at-utc",
                    "2026-11-19T00:00:00Z",
                    "--policy-sha256",
                    "d" * 64,
                    "--review-policy-file",
                    str(self.root / "review-policy.json"),
                    "--reviewed-candidate-sha256",
                    "c" * 64,
                    "--stage-verdicts",
                    json.dumps(stage_verdicts),
                    "--stage-issue-codes",
                    json.dumps(issue_codes_by_stage),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            record.call_args.kwargs["issue_codes_by_stage"],
            issue_codes_by_stage,
        )
        self.assertEqual(
            record.call_args.kwargs["review_policy_file"],
            str(self.root / "review-policy.json"),
        )

    def test_resolution_cli_requires_and_forwards_reviewed_decision_digest(self):
        decision_sha256 = "d" * 64
        with (
            patch.object(
                review_resolution_cli,
                "resolve_translation_review",
                return_value={"status": "created"},
            ) as resolve,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = review_resolution_cli.main(
                [
                    "--run-directory",
                    str(self.run_root),
                    "--episode-id",
                    self.episode_id,
                    "--action",
                    "approve_current",
                    "--reviewer",
                    "synthetic operator",
                    "--reviewed-at-utc",
                    "2026-11-19T00:01:00Z",
                    "--rationale",
                    "Approve the currently reviewed candidate.",
                    "--reviewed-decision-sha256",
                    decision_sha256,
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            resolve.call_args.kwargs["reviewed_decision_sha256"],
            decision_sha256,
        )

    def test_decision_cli_rejects_ambiguous_review_json(self):
        inputs = (
            (
                '{"fidelity":["fail"],"fidelity":["pass"],'
                '"fluency":["pass"],"style":["pass"]}',
                None,
            ),
            (
                '{"fidelity":["pass"],"fluency":["pass"],"style":["pass"]}',
                '{"fidelity":["omission"],"fidelity":[],"fluency":[],"style":[]}',
            ),
            (
                '{"fidelity":NaN,"fluency":["pass"],"style":["pass"]}',
                None,
            ),
            (
                '{"fidelity":1e999,"fluency":["pass"],"style":["pass"]}',
                None,
            ),
        )
        for stage_verdicts, issue_codes_by_stage in inputs:
            argv = [
                "--run-directory",
                str(self.run_root),
                "--episode-id",
                self.episode_id,
                "--reviewer",
                "synthetic reviewer",
                "--reviewed-at-utc",
                "2026-11-19T00:00:00Z",
                "--reviewed-candidate-sha256",
                "c" * 64,
                "--stage-verdicts",
                stage_verdicts,
            ]
            if issue_codes_by_stage is not None:
                argv.extend(
                    ["--stage-issue-codes", issue_codes_by_stage]
                )

            with (
                patch.object(
                    review_decision_cli,
                    "record_translation_review_decision",
                ) as record,
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                exit_code = review_decision_cli.main(argv)

            self.assertEqual(exit_code, 1)
            record.assert_not_called()

    def test_policy_file_is_archived_and_binds_new_decision_schema(self):
        policy_bytes = json.dumps(
            {
                "schema_version": 1,
                "policy_id": "synthetic-review",
                "revision": 1,
                "issue_codes": [
                    {
                        "code": "omission",
                        "stages": ["fidelity"],
                        "definition": "Synthetic fidelity omission.",
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        policy_file = self.root / "review-policy.json"
        policy_file.write_bytes(policy_bytes)
        issue_codes = {
            "fidelity": ["omission"],
            "fluency": [],
            "style": [],
        }

        report = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            issue_codes_by_stage=issue_codes,
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-20T00:00:00Z",
            review_policy_file=policy_file,
        )

        decision_path = Path(report["path"])
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        expected_policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
        archived_policy = (
            self.run_root
            / "ReviewPolicies"
            / f"{expected_policy_sha256}.json"
        )
        self.assertEqual(decision["schema_version"], 3)
        self.assertEqual(decision["policy_sha256"], expected_policy_sha256)
        self.assertEqual(
            decision["policy_relative_path"],
            f"ReviewPolicies/{expected_policy_sha256}.json",
        )
        self.assertEqual(archived_policy.read_bytes(), policy_bytes)
        self.assertEqual(report["transition"]["status"], "rework")

    def test_policy_file_rejects_code_not_allowed_in_stage(self):
        policy_file = self.root / "review-policy.json"
        policy_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_id": "synthetic-review",
                    "revision": 1,
                    "issue_codes": [
                        {
                            "code": "omission",
                            "stages": ["fidelity"],
                            "definition": "Synthetic fidelity omission.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ValueError,
            "not declared for this review policy",
        ):
            record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["pass"],
                    "fluency": ["fail"],
                    "style": ["pass"],
                },
                issue_codes_by_stage={
                    "fidelity": [],
                    "fluency": ["omission"],
                    "style": [],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-20T00:00:00Z",
                review_policy_file=policy_file,
            )
        self.assertFalse((self.run_root / "ReviewPolicies").exists())

    def test_decision_chain_requires_final_candidate_review_before_publish(self):
        legacy_review = self._approved_review()
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )

        with self.assertRaisesRegex(ValueError, "requires a review"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                legacy_review,
            )

        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_initial_passed_decision_is_bound_to_review_and_publication(self):
        record = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        review_path = self._approved_review()
        review = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(review["schema_version"], 2)
        self.assertEqual(review["decision_sha256"], record["decision_sha256"])

        report = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        self.assertEqual(report["status"], "published")
        self.assertEqual(
            (self.translation_root / "episode-0001.md").read_bytes(),
            self.draft_bytes,
        )
        receipt = json.loads(
            (
                self.run_root
                / "Published"
                / f"{self.episode_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["candidate_revision"], 0)
        self.assertEqual(
            receipt["candidate_relative_path"],
            "Drafts/episode-0001.md",
        )

    def test_human_override_requires_and_binds_final_checklist(self):
        failed = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=0,
        )
        with self.assertRaisesRegex(ValueError, "human approval resolution"):
            prepare_translation_review(self.run_root, self.episode_id)

        with self.assertRaisesRegex(
            ValueError,
            "Latest review decision changed",
        ):
            resolve_translation_review(
                self.run_root,
                self.episode_id,
                action="approve_current",
                reviewer_id="synthetic operator",
                reviewed_at_utc="2026-11-19T00:01:00Z",
                rationale="This stale decision must not be approved.",
                reviewed_decision_sha256="0" * 64,
            )

        resolution = resolve_translation_review(
            self.run_root,
            self.episode_id,
            action="approve_current",
            reviewer_id="synthetic operator",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            rationale="Synthetic acceptance after reviewing the remaining issue.",
            reviewed_decision_sha256=failed["decision_sha256"],
        )
        review_path = self._approved_review()
        review = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(review["schema_version"], 3)
        self.assertEqual(review["resolution_sha256"], resolution["resolution_sha256"])
        self.assertEqual(review["decision_sha256"], failed["decision_sha256"])

        report = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        receipt = json.loads(
            (
                self.run_root / "Published" / f"{self.episode_id}.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(report["status"], "published")
        self.assertEqual(receipt["schema_version"], 3)
        self.assertEqual(
            receipt["resolution_sha256"],
            resolution["resolution_sha256"],
        )

    def test_budget_extension_resumes_from_exhausted_candidate(self):
        first = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=0,
        )
        resolution = resolve_translation_review(
            self.run_root,
            self.episode_id,
            action="increase_budget",
            reviewer_id="synthetic operator",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            rationale="One additional synthetic rework attempt is approved.",
            reviewed_decision_sha256=first["decision_sha256"],
            new_max_rework_attempts=1,
        )
        candidate_root = (
            self.run_root / "ReviewCandidates" / self.episode_id
        )
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_path.write_bytes(
            "「Synthetic revised paragraph.」\n".encode("utf-8")
        )

        resumed = record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:02:00Z",
            policy_sha256="d" * 64,
            candidate_file=Path(
                f"ReviewCandidates/{self.episode_id}/revision-0001.md"
            ),
        )

        self.assertEqual(resolution["action"], "increase_budget")
        self.assertEqual(resumed["candidate_revision"], 1)
        self.assertEqual(resumed["transition"]["status"], "passed")
        self.assertEqual(resumed["transition"]["max_rework_attempts"], 1)
        self.assertNotEqual(
            resumed["candidate_sha256"],
            first["candidate_sha256"],
        )

    def test_reviewed_rework_candidate_is_the_published_version(self):
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        candidate_root = (
            self.run_root / "ReviewCandidates" / self.episode_id
        )
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_bytes = "「Synthetic revised paragraph.」\n".encode("utf-8")
        candidate_path.write_bytes(candidate_bytes)
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
            candidate_file=candidate_path,
        )

        review_path = self._approved_review()
        review = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(review["schema_version"], 2)
        report = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        self.assertEqual(report["status"], "published")
        self.assertEqual(
            (self.translation_root / "episode-0001.md").read_bytes(),
            candidate_bytes,
        )
        self.assertEqual(
            (self.run_root / "Drafts" / "episode-0001.md").read_bytes(),
            self.draft_bytes,
        )
        receipt = json.loads(
            (
                self.run_root
                / "Published"
                / f"{self.episode_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["candidate_revision"], 1)
        self.assertEqual(
            receipt["candidate_relative_path"],
            f"ReviewCandidates/{self.episode_id}/revision-0001.md",
        )
        self.assertEqual(
            receipt["candidate_sha256"],
            hashlib.sha256(candidate_bytes).hexdigest(),
        )

    def test_verified_publication_lookup_binds_reworked_output_to_source(self):
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        candidate_root = (
            self.run_root / "ReviewCandidates" / self.episode_id
        )
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_path.write_bytes(
            "「Synthetic revised paragraph.」\n".encode("utf-8")
        )
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
            candidate_file=candidate_path,
        )
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        lookup = has_verified_translation_publication
        common = {
            "work_id": self.work_id,
            "episode_id": self.episode_id,
            "source_version_id": self.plan["episodes"][0][
                "source_version_id"
            ],
            "source_sha256": self.plan["episodes"][0]["source_sha256"],
            "translation_file": "episode-0001.md",
            "translation_root": self.translation_root,
        }

        self.assertTrue(lookup(self.run_root.parent, **common))
        current_episode = self.ai_index["episodes"][0]
        expanded_index = {
            "index_sha256": "f" * 64,
            "index": {"catalog": {"relative_path": "catalog.json"}},
            "episodes_by_id": {
                self.episode_id: {
                    "ai_edition_version_id": current_episode[
                        "ai_edition_version_id"
                    ],
                    "ai_archive_relative_path": current_episode[
                        "ai_archive_relative_path"
                    ],
                    "ai_relative_path": current_episode["ai_relative_path"],
                    "output_sha256": current_episode["output_sha256"],
                    "title": current_episode["title"],
                    "position": current_episode["position"],
                },
                "new-episode": {"position": 2},
            },
        }
        with patch.object(
            translation_review,
            "verify_ai_edition_index",
            return_value=expanded_index,
        ):
            self.assertTrue(lookup(self.run_root.parent, **common))
            with self.assertRaisesRegex(
                ValueError,
                "AI edition index changed after translation",
            ):
                publish_reviewed_translation(
                    self.run_root,
                    self.episode_id,
                    review_path,
                )
        changed_target_index = {
            **expanded_index,
            "episodes_by_id": {
                **expanded_index["episodes_by_id"],
                self.episode_id: {
                    **expanded_index["episodes_by_id"][self.episode_id],
                    "output_sha256": "0" * 64,
                },
            },
        }
        with patch.object(
            translation_review,
            "verify_ai_edition_index",
            return_value=changed_target_index,
        ):
            self.assertFalse(lookup(self.run_root.parent, **common))
        self.assertFalse(
            lookup(
                self.run_root.parent,
                **{**common, "source_sha256": "0" * 64},
            )
        )
        self.assertFalse(
            lookup(
                self.run_root.parent,
                **{**common, "translation_file": "episode-other.md"},
            )
        )
        self.assertFalse(
            lookup(
                self.run_root.parent,
                **{**common, "translation_root": self.root},
            )
        )
        (self.translation_root / "episode-0001.md").write_bytes(
            b"changed after publication"
        )
        self.assertFalse(lookup(self.run_root.parent, **common))

    def test_changed_final_candidate_blocks_reviewed_rework_publication(self):
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["fail"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        candidate_root = (
            self.run_root / "ReviewCandidates" / self.episode_id
        )
        candidate_root.mkdir(parents=True)
        candidate_path = candidate_root / "revision-0001.md"
        candidate_path.write_bytes(
            "「Synthetic revised paragraph.」\n".encode("utf-8")
        )
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:01:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
            candidate_file=candidate_path,
        )
        review_path = self._approved_review()
        candidate_path.write_bytes(b"tampered after review")

        with self.assertRaisesRegex(ValueError, "candidate changed"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_review_decision_chain_rejects_new_candidate_after_pass(self):
        record_translation_review_decision(
            self.run_root,
            self.episode_id,
            stage_verdicts={
                "fidelity": ["pass"],
                "fluency": ["pass"],
                "style": ["pass"],
            },
            reviewer_id="synthetic reviewer",
            reviewed_at_utc="2026-11-19T00:00:00Z",
            policy_sha256="d" * 64,
            max_rework_attempts=1,
        )
        with self.assertRaisesRegex(ValueError, "only after a rework"):
            record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["pass"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:01:00Z",
                policy_sha256="d" * 64,
                max_rework_attempts=1,
            )

    def test_review_decision_candidate_must_stay_inside_run(self):
        outside = self.root / "outside.md"
        outside.write_bytes(self.draft_bytes)

        with self.assertRaisesRegex(ValueError, "inside the translation run"):
            record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["fail"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                policy_sha256="d" * 64,
                max_rework_attempts=1,
                candidate_file=outside,
            )

    def test_review_decision_candidate_rejects_symbolic_link(self):
        candidate_root = self.run_root / "ReviewCandidates" / self.episode_id
        candidate_root.mkdir(parents=True)
        candidate_link = candidate_root / "linked.md"
        candidate_target = self.run_root / "Drafts" / "episode-0001.md"
        try:
            candidate_link.symlink_to(candidate_target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation is unavailable: {exc}")

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            record_translation_review_decision(
                self.run_root,
                self.episode_id,
                stage_verdicts={
                    "fidelity": ["fail"],
                    "fluency": ["pass"],
                    "style": ["pass"],
                },
                reviewer_id="synthetic reviewer",
                reviewed_at_utc="2026-11-19T00:00:00Z",
                policy_sha256="d" * 64,
                max_rework_attempts=1,
                candidate_file=candidate_link,
                reviewed_candidate_sha256=hashlib.sha256(
                    self.draft_bytes
                ).hexdigest(),
            )

    def test_publish_is_idempotent_and_does_not_overwrite_conflicts(self):
        review_path = self._approved_review()
        first = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        second = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        self.assertTrue(first["created"])
        self.assertTrue(first["review_snapshot_created"])
        self.assertFalse(second["created"])
        self.assertFalse(second["review_snapshot_created"])
        self.assertEqual(second["run_status"], "published")
        output = self.translation_root / "episode-0001.md"
        output.write_bytes(b"human edit")
        with self.assertRaisesRegex(FileExistsError, "differs"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )
        self.assertEqual(output.read_bytes(), b"human edit")

    def test_publish_retry_recovers_after_receipt_write_failure(self):
        review_path = self._approved_review()
        published_path = self.translation_root / "episode-0001.md"
        published_root = self.run_root / "Published"
        receipt_path = (
            published_root / f"{self.episode_id}.json"
        )
        original_create = translation_review._create_new_bytes_atomically

        def fail_receipt_once(root, relative_path, content):
            if (
                Path(root).resolve() == published_root.resolve()
                and relative_path == f"{self.episode_id}.json"
            ):
                raise OSError("synthetic receipt write failure")
            return original_create(root, relative_path, content)

        with (
            patch(
                "translation_review._create_new_bytes_atomically",
                side_effect=fail_receipt_once,
            ),
            self.assertRaisesRegex(OSError, "receipt write failure"),
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

        self.assertEqual(published_path.read_bytes(), self.draft_bytes)
        self.assertFalse(receipt_path.exists())

        retry = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        self.assertEqual(retry["status"], "published")
        self.assertFalse(retry["created"])
        self.assertTrue(retry["receipt_created"])
        self.assertEqual(retry["run_status"], "published")
        self.assertEqual(published_path.read_bytes(), self.draft_bytes)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["draft_sha256"],
            hashlib.sha256(self.draft_bytes).hexdigest(),
        )
        self.assertEqual(
            (
                self.run_root
                / "Published"
                / "ReviewSnapshots"
                / f"{self.episode_id}.json"
            ).read_bytes(),
            review_path.read_bytes(),
        )

    def test_publish_recovers_after_process_termination_before_receipt(self):
        review_path = self._approved_review()
        marker_path = self.root / "receipt-crash-checkpoint.json"
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=_publish_until_receipt_checkpoint,
            args=(
                str(self.run_root),
                self.episode_id,
                str(review_path),
                str(marker_path),
                ready,
            ),
        )
        process.start()

        published_path = self.translation_root / "episode-0001.md"
        published_root = self.run_root / "Published"
        snapshot_path = (
            published_root
            / "ReviewSnapshots"
            / f"{self.episode_id}.json"
        )
        receipt_path = published_root / f"{self.episode_id}.json"
        state_path = self.run_root / "run_state.json"

        try:
            self.assertTrue(ready.wait(timeout=30))
            self.assertEqual(
                json.loads(marker_path.read_text(encoding="utf-8")),
                {
                    "checkpoint": "before_publication_receipt",
                    "episode_id": self.episode_id,
                    "pid": process.pid,
                },
            )
            self.assertTrue(process.is_alive())
            self.assertEqual(published_path.read_bytes(), self.draft_bytes)
            self.assertEqual(snapshot_path.read_bytes(), review_path.read_bytes())
            self.assertFalse(receipt_path.exists())
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "running",
            )
            durable_bytes = {
                path: path.read_bytes()
                for path in (published_path, snapshot_path, state_path)
            }

            process.terminate()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())
            _assert_checkpoint_worker_was_terminated(self, process)
            for path, expected_bytes in durable_bytes.items():
                self.assertEqual(path.read_bytes(), expected_bytes)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)

        recovered = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )

        self.assertEqual(recovered["status"], "published")
        self.assertFalse(recovered["created"])
        self.assertFalse(recovered["review_snapshot_created"])
        self.assertTrue(recovered["receipt_created"])
        self.assertEqual(recovered["run_status"], "published")
        self.assertEqual(published_path.read_bytes(), self.draft_bytes)
        self.assertEqual(snapshot_path.read_bytes(), review_path.read_bytes())
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["status"],
            "published",
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "published")
        self.assertEqual(
            receipt["draft_sha256"],
            hashlib.sha256(self.draft_bytes).hexdigest(),
        )

        recovered_bytes = {
            path: path.read_bytes()
            for path in (published_path, snapshot_path, receipt_path, state_path)
        }
        reopened = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        self.assertFalse(reopened["created"])
        self.assertFalse(reopened["review_snapshot_created"])
        self.assertFalse(reopened["receipt_created"])
        self.assertEqual(
            {
                path: path.read_bytes()
                for path in (published_path, snapshot_path, receipt_path, state_path)
            },
            recovered_bytes,
        )

    def test_tampered_review_snapshot_blocks_republication(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        snapshot_path = (
            self.run_root
            / "Published"
            / "ReviewSnapshots"
            / f"{self.episode_id}.json"
        )
        snapshot_path.write_bytes(b"tampered review")
        with self.assertRaisesRegex(
            ValueError,
            "Existing publication review snapshot differs",
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

    def test_conflicting_review_snapshot_blocks_before_creating_translation(self):
        review_path = self._approved_review()
        snapshot_root = self.run_root / "Published" / "ReviewSnapshots"
        snapshot_root.mkdir(parents=True)
        (snapshot_root / f"{self.episode_id}.json").write_bytes(
            b"conflicting review snapshot"
        )

        with self.assertRaisesRegex(
            ValueError,
            "Existing publication review snapshot differs",
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

        self.assertFalse((self.translation_root / "episode-0001.md").exists())
        self.assertFalse(
            (self.run_root / "Published" / f"{self.episode_id}.json").exists()
        )

    def test_conflicting_receipt_blocks_before_creating_translation(self):
        review_path = self._approved_review()
        published_root = self.run_root / "Published"
        published_root.mkdir()
        (published_root / f"{self.episode_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "published",
                    "run_id": "b" * 32,
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Existing publication receipt conflicts",
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

        self.assertFalse((self.translation_root / "episode-0001.md").exists())
        self.assertFalse(
            (
                published_root
                / "ReviewSnapshots"
                / f"{self.episode_id}.json"
            ).exists()
        )

    def test_invalid_run_state_blocks_before_creating_translation(self):
        review_path = self._approved_review()
        (self.run_root / "run_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "run_id": "a" * 32,
                    "work_id": self.work_id,
                    "plan_sha256": self.plan["plan_sha256"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "run state does not match",
        ):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )

        self.assertFalse((self.translation_root / "episode-0001.md").exists())
        self.assertFalse((self.run_root / "Published").exists())

    def test_single_episode_publication_marks_run_published(self):
        review_path = self._approved_review()
        report = publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        self.assertEqual(report["run_status"], "published")
        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(
                    encoding="utf-8"
                )
            )["status"],
            "published",
        )

    def test_run_publication_state_requires_existing_output_and_recovers(self):
        self._approved_review()
        publish_reviewed_run(self.run_root)
        output_path = self.translation_root / "episode-0001.md"
        output_path.unlink()

        run_root, run, run_bytes = _load_run(self.run_root)
        status = _mark_run_published_if_complete(run_root, run, run_bytes)

        self.assertEqual(status, "review_pending")
        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(encoding="utf-8")
            )["status"],
            "review_pending",
        )

        recovered = publish_reviewed_run(self.run_root)
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(output_path.read_bytes(), self.draft_bytes)

    def test_run_publication_state_rejects_changed_review_snapshot(self):
        self._approved_review()
        publish_reviewed_run(self.run_root)
        snapshot_path = (
            self.run_root
            / "Published"
            / "ReviewSnapshots"
            / f"{self.episode_id}.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["notes"] = "changed after publication"
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False),
            encoding="utf-8",
        )

        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["failed"][0]["error"], "ValueError")

        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(encoding="utf-8")
            )["status"],
            "review_pending",
        )

    def test_run_publication_state_rejects_changed_published_translation(self):
        self._approved_review()
        publish_reviewed_run(self.run_root)
        output_path = self.translation_root / "episode-0001.md"
        output_path.write_bytes(b"changed after publication")

        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["failed"][0]["error"], "FileExistsError")

        self.assertEqual(
            output_path.read_bytes(),
            b"changed after publication",
        )
        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(encoding="utf-8")
            )["status"],
            "review_pending",
        )

    def test_batch_publication_reports_missing_review_without_leaking_details(self):
        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "review_pending")
        self.assertEqual(report["published_count"], 0)
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(
            report["pending"],
            [
                {
                    "episode_id": self.episode_id,
                    "position": 1,
                    "reason": "review_missing",
                }
            ],
        )
        self.assertFalse(
            (self.translation_root / "episode-0001.md").exists()
        )

    def test_batch_publication_publishes_approved_review(self):
        self._approved_review()
        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "published")
        self.assertEqual(report["published_count"], 1)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["failed_count"], 0)
        self.assertTrue(
            (self.translation_root / "episode-0001.md").is_file()
        )

    def test_batch_reconciles_publication_when_editable_review_is_missing(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        review_path.unlink()

        report = publish_reviewed_run(self.run_root)

        self.assertEqual(report["status"], "published")
        self.assertEqual(report["published_count"], 1)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(
                    encoding="utf-8"
                )
            )["status"],
            "published",
        )

    def test_batch_restores_missing_output_from_verified_snapshot(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        review_path.unlink()
        output_path = self.translation_root / "episode-0001.md"
        output_path.unlink()

        report = publish_reviewed_run(self.run_root)

        self.assertEqual(report["status"], "published")
        self.assertEqual(report["published_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertTrue(report["published"][0]["created"])
        self.assertEqual(output_path.read_bytes(), self.draft_bytes)

    def test_batch_does_not_overwrite_conflicting_output_without_review(self):
        review_path = self._approved_review()
        publish_reviewed_translation(
            self.run_root,
            self.episode_id,
            review_path,
        )
        review_path.unlink()
        output_path = self.translation_root / "episode-0001.md"
        output_path.write_bytes(b"preserve this translation")

        report = publish_reviewed_run(self.run_root)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["published_count"], 0)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["failed"][0]["error"], "FileExistsError")
        self.assertEqual(
            output_path.read_bytes(),
            b"preserve this translation",
        )

    def test_batch_attributes_run_reconciliation_conflict_to_run(self):
        self._approved_review()
        with patch(
            "translation_review._mark_run_published_if_complete",
            side_effect=FileExistsError("synthetic run conflict"),
        ):
            report = publish_reviewed_run(self.run_root)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["published_count"], 1)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["failed"][0]["scope"], "run")
        self.assertTrue(
            (self.translation_root / "episode-0001.md").is_file()
        )

    def test_batch_publication_keeps_partial_run_review_pending(self):
        run = json.loads(
            (self.run_root / "run.json").read_text(encoding="utf-8")
        )
        second = dict(run["episodes"][0])
        second.update(
            {
                "episode_id": "67891",
                "position": 2,
                "title": "Synthetic second episode",
                "translation_file": "episode-0002.md",
                "tm_key": f"source-edition:{self.work_id}:67891",
            }
        )
        run["episodes"].append(second)
        (self.run_root / "run.json").write_text(
            json.dumps(run, ensure_ascii=False),
            encoding="utf-8",
        )
        self._approved_review()

        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "review_pending")
        self.assertEqual(report["published_count"], 1)
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertTrue(
            (self.translation_root / "episode-0001.md").is_file()
        )
        self.assertFalse(
            (self.translation_root / "episode-0002.md").exists()
        )
        self.assertEqual(
            json.loads(
                (self.run_root / "run_state.json").read_text(
                    encoding="utf-8"
                )
            )["status"],
            "review_pending",
        )

    def test_batch_publication_reports_conflicting_output_without_overwriting(self):
        self._approved_review()
        output_path = self.translation_root / "episode-0001.md"
        output_path.write_bytes(b"preserve this translation")

        report = publish_reviewed_run(self.run_root)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["published_count"], 0)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["failed"][0]["error"], "FileExistsError")
        self.assertEqual(
            output_path.read_bytes(),
            b"preserve this translation",
        )

    def test_batch_publication_cli_returns_incomplete_exit_code(self):
        incomplete = {
            "status": "review_pending",
            "run_id": "a" * 32,
            "published_count": 1,
            "pending_count": 1,
            "failed_count": 0,
            "published": [],
            "pending": [],
            "failed": [],
        }
        output = io.StringIO()
        with (
            patch(
                "scripts.publish_reviewed_run.publish_reviewed_run",
                return_value=incomplete,
            ),
            redirect_stdout(output),
        ):
            exit_code = publish_reviewed_run_main(
                ["--run-directory", str(self.run_root)]
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue()), incomplete)

    def test_pending_or_incomplete_review_cannot_publish(self):
        prepare_translation_review(self.run_root, self.episode_id)
        review_path = self.run_root / "Reviews" / f"{self.episode_id}.json"
        with self.assertRaisesRegex(ValueError, "not fully approved"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["decision"] = "approved"
        review["reviewer_id"] = "synthetic reviewer"
        review["independence_confirmed"] = True
        review["reviewed_at_utc"] = "2026-11-18T00:00:00Z"
        review["checks"] = {name: "pass" for name in _REVIEW_CHECKS}
        review["checks"]["fidelity"] = "fail"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not fully approved"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_changed_draft_or_source_edition_blocks_publication(self):
        review_path = self._approved_review()
        draft_path = self.run_root / "Drafts" / "episode-0001.md"
        draft_path.write_bytes(b"changed after review")
        with self.assertRaisesRegex(ValueError, "draft changed"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )
        self.assertFalse((self.translation_root / "episode-0001.md").exists())

    def test_run_manifest_accepts_zero_byte_draft_metadata(self):
        run = json.loads(
            (self.run_root / "run.json").read_text(encoding="utf-8")
        )
        run["episodes"][0]["draft_bytes"] = 0
        run["episodes"][0]["draft_sha256"] = hashlib.sha256(b"").hexdigest()
        (self.run_root / "run.json").write_text(
            json.dumps(run, ensure_ascii=False),
            encoding="utf-8",
        )

        _, loaded_run, _ = _load_run(self.run_root)

        self.assertEqual(loaded_run["episodes"][0]["draft_bytes"], 0)

    def test_run_manifest_can_include_only_selected_pending_episodes(self):
        first_indexed = self.ai_index["episodes"][0]
        second_id = "67891"
        second_indexed = {
            **first_indexed,
            "episode_id": second_id,
            "position": 2,
            "title": "Second synthetic episode",
            "ai_archive_relative_path": "archive/second.md",
            "ai_edition_version_id": "ai-edition-second",
            "ai_relative_path": "chapters/second.md",
            "raw_source_version_id": "raw-source-second",
        }
        indexed_episodes = {
            self.episode_id: first_indexed,
            second_id: second_indexed,
        }
        source_bytes = self.draft_bytes
        plan_episodes = []
        for position, (episode_id, indexed) in enumerate(
            indexed_episodes.items(), start=1
        ):
            plan_episodes.append(
                {
                    "episode_id": episode_id,
                    "position": position,
                    "title": indexed["title"],
                    "source_file": indexed["ai_archive_relative_path"],
                    "source_version_id": indexed[
                        "ai_edition_version_id"
                    ],
                    "source_input_version_id": indexed[
                        "raw_source_version_id"
                    ],
                    "source_input_file": indexed["ai_relative_path"],
                    "source_sha256": indexed["output_sha256"],
                    "translation_file": f"episode-{position:04d}.md",
                    "tm_key": f"source-edition:{self.work_id}:{episode_id}",
                }
            )
        plan = {
            **self.plan,
            "episodes": plan_episodes,
        }
        (self.run_root / "Drafts" / "episode-0001.md").unlink()
        (self.run_root / "Drafts" / "episode-0002.md").write_bytes(
            source_bytes
        )
        ai_result = {
            "index": {
                **self.ai_index,
                "episodes": list(indexed_episodes.values()),
                "catalog": {"relative_path": "catalog.json"},
            },
            "episodes_by_id": indexed_episodes,
            "edition_manifest": {},
        }

        def normalized_metadata(_manifest, version_id):
            indexed = next(
                item
                for item in indexed_episodes.values()
                if item["ai_edition_version_id"] == version_id
            )
            return {
                "relative_path": indexed["ai_archive_relative_path"],
                "content_sha256": indexed["output_sha256"],
                "version_id": version_id,
            }

        with (
            patch(
                "translation_review.verify_ai_edition_index",
                return_value=ai_result,
            ),
            patch(
                "translation_review.verify_current_normalized_source_metadata",
                side_effect=normalized_metadata,
            ),
            patch(
                "translation_review.read_verified_ai_edition_bytes",
                return_value=source_bytes,
            ) as read_source,
        ):
            manifest = build_translation_run_manifest(
                run_id="b" * 32,
                plan=plan,
                source_root=str(self.source_root),
                source_manifest="source_manifest.json",
                edition_manifest="source_editions_manifest.json",
                catalog="catalog.json",
                ai_root=str(self.ai_root),
                draft_root=str(self.run_root / "Drafts"),
                translation_root=str(self.translation_root),
                episode_ids=[second_id],
            )

        self.assertEqual(
            [episode["episode_id"] for episode in manifest["episodes"]],
            [second_id],
        )
        self.assertEqual(read_source.call_count, 1)

    def test_review_input_accepts_bundle_larger_than_run_manifest_limit(self):
        bundle_bytes = b"x" * (translation_review._MAX_RUN_BYTES + 1)
        bundle_relative_path = "collections/ai/book-ai.json"
        bundle_path = self.ai_root / bundle_relative_path
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(bundle_bytes)
        source_snapshot_id = "source-v1-" + "a" * 64
        bundle_set = {
            "source_snapshot_id": source_snapshot_id,
            "bundles": {
                "ai": {
                    "bundle_id": "ai-v1-" + "b" * 64,
                    "relative_path": bundle_relative_path,
                    "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
                }
            },
        }
        bundle_set_bytes = json.dumps(
            bundle_set,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        bundle_set_path = self.source_root / "collections" / "bundle-set.json"
        bundle_set_path.parent.mkdir()
        bundle_set_path.write_bytes(bundle_set_bytes)
        run = dict(self.run_manifest)
        run["book_bundle"] = {
            "source_snapshot_id": source_snapshot_id,
            "ai_bundle_id": bundle_set["bundles"]["ai"]["bundle_id"],
            "bundle_set_relative_path": "collections/bundle-set.json",
            "bundle_set_sha256": hashlib.sha256(bundle_set_bytes).hexdigest(),
            "ai_bundle_relative_path": bundle_relative_path,
            "ai_bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        }

        source_bytes = translation_review._verify_current_inputs(
            run,
            run["episodes"][0],
        )

        self.assertEqual(
            source_bytes,
            (self.ai_root / run["episodes"][0]["source_input_file"]).read_bytes(),
        )
        with patch.object(
            translation_review,
            "_verify_run_book_bundle",
            wraps=translation_review._verify_run_book_bundle,
        ) as verify_bundle:
            verify_inputs, revalidate_bundle = (
                translation_review._make_batch_input_verifier(run)
            )
            verify_inputs(run, run["episodes"][0])
            verify_inputs(run, run["episodes"][0])
            self.assertEqual(verify_bundle.call_count, 1)
            bundle_path.write_bytes(bundle_bytes + b"changed")
            with self.assertRaisesRegex(ValueError, "book bundle changed"):
                revalidate_bundle()
            self.assertEqual(verify_bundle.call_count, 2)


if __name__ == "__main__":
    unittest.main()
