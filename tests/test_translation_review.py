import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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
    build_translation_run_manifest,
    prepare_translation_review,
    publish_reviewed_translation,
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
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_bytes(), self.draft_bytes)
        receipt = json.loads(
            (
                self.run_root
                / "Published"
                / f"{self.episode_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["draft_sha256"], hashlib.sha256(self.draft_bytes).hexdigest())

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
        self.assertFalse(second["created"])
        output = self.translation_root / "episode-0001.md"
        output.write_bytes(b"human edit")
        with self.assertRaisesRegex(FileExistsError, "differs"):
            publish_reviewed_translation(
                self.run_root,
                self.episode_id,
                review_path,
            )
        self.assertEqual(output.read_bytes(), b"human edit")

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


if __name__ == "__main__":
    unittest.main()
