import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import translation_review
from scripts.publish_reviewed_run import main as publish_reviewed_run_main
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
    build_translation_run_manifest,
    has_verified_translation_publication,
    prepare_translation_review,
    publish_reviewed_run,
    publish_reviewed_translation,
    record_translation_review_decision,
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
                Path(root) == published_root
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


if __name__ == "__main__":
    unittest.main()
