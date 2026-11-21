import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.plan_knowledge_extraction import plan_full_book_extraction


class CharacterTokenizer:
    def encode(self, text):
        return SimpleNamespace(ids=list(text))


class TestKnowledgeExtractionPlan(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.texts = [
            "Synthetic source marker one.\n\nSecond paragraph.",
            "Synthetic source marker two.",
        ]
        self.bundle = self._bundle()
        self.tokenizer_patch = patch(
            "scripts.plan_knowledge_extraction.load_tokenizer_json",
            return_value=(CharacterTokenizer(), "a" * 64),
        )
        self.tokenizer_patch.start()
        self.addCleanup(self.tokenizer_patch.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _bundle(self, *, status="verified"):
        episodes = {}
        for position, text in enumerate(self.texts, start=1):
            source_input_file = f"episodes/episode-{position}.md"
            episodes[source_input_file] = {
                "position": position,
                "source_file": f"editions/ai/episode-{position}.md",
                "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_text": text,
            }
        return {
            "status": status,
            "source_snapshot_id": "source-v1-" + "b" * 64,
            "ai_bundle_id": "ai-v1-" + "c" * 64,
            "bundle_set_relative_path": "collections/set/bundle-set.json",
            "bundle_set_sha256": "d" * 64,
            "ai_bundle_relative_path": "collections/ai/book-ai.json",
            "ai_bundle_sha256": "e" * 64,
            "episode_count": len(episodes),
            "episodes_by_source_input_file": episodes,
        }

    def _plan(self, **overrides):
        arguments = {
            "source_root": str(self.root / "SourceArchive"),
            "catalog_relative_path": "catalog.json",
            "checkpoint_relative_path": "checkpoint.json",
            "bundle_set_relative_path": "collections/set/bundle-set.json",
            "human_root": str(self.root / "human"),
            "ai_root": str(self.root / "ai"),
            "tokenizer_json": str(self.root / "tokenizer.json"),
            "model_id": "synthetic-model-v1",
            "max_input_characters": 1000,
            "context_window_tokens": 10000,
            "max_output_tokens": 100,
            "safety_margin_tokens": 100,
            "message_overhead_tokens": 10,
            "max_provider_calls": 10,
            "manifest_relative_path": "source_manifest.json",
            "edition_manifest_relative_path": "source_editions_manifest.json",
        }
        arguments.update(overrides)
        with patch(
            "scripts.plan_knowledge_extraction.load_verified_ai_book_bundle",
            return_value=self.bundle,
        ):
            return plan_full_book_extraction(**arguments)

    def test_plan_is_content_free_and_reports_zero_calls_and_writes(self):
        report = self._plan()

        self.assertEqual(report["status"], "ready_for_extraction")
        self.assertEqual(report["scope"], "all_verified_ai_bundle_chapters")
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(report["paragraph_count"], 3)
        self.assertEqual(report["model_id_source"], "caller_declared_not_verified")
        self.assertEqual(report["provider_calls_made"], 0)
        self.assertEqual(report["files_written"], 0)
        self.assertFalse(report["source_text_included"])
        self.assertIsNone(report["provider_cost_estimate"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(self.texts[0], serialized)
        self.assertNotIn(self.texts[1], serialized)
        self.assertNotIn("episode-1.md", serialized)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_plan_reserves_a_synthesis_call_for_multiple_batches(self):
        with patch(
            "scripts.plan_knowledge_extraction.plan_paragraph_batches",
            return_value=[
                {"user_text": "batch one", "input_tokens": 20},
                {"user_text": "batch two", "input_tokens": 30},
            ],
        ):
            report = self._plan(max_provider_calls=5)

        self.assertEqual(report["extraction_batch_count"], 2)
        self.assertEqual(report["minimum_provider_calls"], 3)
        self.assertEqual(
            report["remaining_provider_call_budget_for_synthesis"], 3
        )

    def test_plan_rejects_input_character_overflow(self):
        with self.assertRaisesRegex(ValueError, "character limit"):
            self._plan(max_input_characters=10)

    def test_plan_rejects_unverified_bundle_before_batching(self):
        self.bundle = self._bundle(status="stale")
        with patch(
            "scripts.plan_knowledge_extraction.plan_paragraph_batches"
        ) as batch_planner:
            with self.assertRaisesRegex(ValueError, "not verified"):
                self._plan()
        batch_planner.assert_not_called()

    def test_plan_rejects_inconsistent_bundle_chapter_count(self):
        self.bundle["episode_count"] = 3
        with self.assertRaisesRegex(ValueError, "chapter count"):
            self._plan()

    def test_plan_rejects_boolean_bundle_chapter_count(self):
        self.bundle["episode_count"] = True
        with self.assertRaisesRegex(ValueError, "chapter count"):
            self._plan()

    def test_plan_rejects_chapter_digest_mismatch(self):
        self.bundle["episodes_by_source_input_file"][
            "episodes/episode-1.md"
        ]["source_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "digest is inconsistent"):
            self._plan()

    def test_plan_rejects_missing_synthesis_call_reserve(self):
        with patch(
            "scripts.plan_knowledge_extraction.plan_paragraph_batches",
            return_value=[
                {"user_text": "batch one", "input_tokens": 20},
                {"user_text": "batch two", "input_tokens": 30},
            ],
        ):
            with self.assertRaisesRegex(ValueError, "reserve"):
                self._plan(max_provider_calls=2)


if __name__ == "__main__":
    unittest.main()
