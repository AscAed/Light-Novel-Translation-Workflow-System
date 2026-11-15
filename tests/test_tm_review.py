import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_engine import RAGEngine
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from tm_review import (
    create_tm_review_template,
    load_reviewed_tm_snapshot,
    publish_reviewed_tm,
)


class TranslationMemoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_input = self.root / "source-input"
        self.source_root = self.root / "source"
        self.translation_root = self.root / "translated"
        self.knowledge_root = self.root / "Knowledge"
        for directory in (
            self.source_input,
            self.source_root,
            self.translation_root,
            self.knowledge_root,
        ):
            directory.mkdir()

        self.raw_text = "alpha raw\n\nbeta raw\n"
        self.translation_text = "alpha target\n\nbeta target\n"
        (self.source_input / "chapter.txt").write_bytes(self.raw_text.encode())
        self.artifact_root = self.root / "archive"
        self.artifact_root.mkdir()
        adapter = LocalFileAdapter(
            self.source_input,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "Synthetic chapter", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(
            adapter,
            root=str(self.artifact_root),
            work_id="synthetic-work",
            checkpoint_relative_path="checkpoint.json",
        )
        artifact = materialize_episode_markdown(
            str(self.artifact_root),
            work_id="synthetic-work",
            episode_id="episode-1",
        )
        self.source_root = self.artifact_root
        self.translation_path = self.translation_root / "第1話.md"
        self.translation_path.write_bytes(self.translation_text.encode())
        self.tm_path = self.knowledge_root / "translation_memory.json"
        source_digest = hashlib.sha256(self.raw_text.encode()).hexdigest()
        translation_digest = hashlib.sha256(
            self.translation_text.encode()
        ).hexdigest()
        self.tm = {
            "chapters": {
                "第1話.md": [
                    {
                        "raw": "alpha raw",
                        "translated": "alpha target",
                        "embedding": [1.0, 0.0],
                    },
                    {
                        "raw": "beta raw",
                        "translated": "beta target",
                        "embedding": [0.0, 1.0],
                    },
                ]
            },
            "source_provenance": {
                "第1話.md": {
                    "schema_version": 1,
                    "producer": "synthetic-test",
                    "raw_file": artifact["relative_path"],
                    "raw_sha256": source_digest,
                    "translation_file": "第1話.md",
                    "translation_sha256": translation_digest,
                    "source_version_id": artifact["version_id"],
                    "pair_mappings": [
                        {
                            "pair_index": 1,
                            "raw_paragraph_indices": [1],
                            "translation_paragraph_indices": [1],
                            "trace_status": "matched",
                        },
                        {
                            "pair_index": 2,
                            "raw_paragraph_indices": [2],
                            "translation_paragraph_indices": [2],
                            "trace_status": "matched",
                        },
                    ],
                }
            },
        }
        self.tm_path.write_text(
            json.dumps(self.tm, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.review_path = self.knowledge_root / "tm-review.json"
        self.bundle_path = self.knowledge_root / "translation_memory_reviewed.json"

    def tearDown(self):
        self.temporary.cleanup()

    def _template(self):
        return create_tm_review_template(
            str(self.tm_path),
            self.review_path.name,
            str(self.source_root),
            str(self.translation_root),
            "source_manifest.json",
        )

    def _complete_receipt(self, decisions=("approved", "rejected")):
        template = json.loads(self.review_path.read_text(encoding="utf-8"))
        template["reviewer"] = {
            "provider_id": "synthetic-reviewer",
            "model_id": "fixture-v1",
            "review_id": "review-001",
        }
        template["reviewed_at_utc"] = "2026-11-15T00:00:00Z"
        for item, decision in zip(template["decisions"], decisions):
            item["decision"] = decision
            item["rationale"] = f"Synthetic decision: {decision}."
        self.review_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return template

    def _publish(self):
        return publish_reviewed_tm(
            str(self.tm_path),
            str(self.review_path),
            self.bundle_path.name,
            str(self.source_root),
            str(self.translation_root),
            "source_manifest.json",
        )

    def test_receipt_is_pending_hash_bound_and_approved_snapshot_is_filtered(self):
        result = self._template()
        receipt = json.loads(self.review_path.read_text(encoding="utf-8"))
        self.assertEqual(result["decision_count"], 2)
        self.assertEqual(
            receipt["candidate_tm_sha256"],
            hashlib.sha256(self.tm_path.read_bytes()).hexdigest(),
        )
        self.assertTrue(
            all(item["decision"] == "pending" for item in receipt["decisions"])
        )

        self._complete_receipt()
        published = self._publish()
        snapshot = load_reviewed_tm_snapshot(
            str(self.bundle_path),
            str(self.source_root),
            str(self.translation_root),
            "source_manifest.json",
        )

        self.assertEqual(published["approved_pair_count"], 1)
        self.assertEqual(
            [pair["raw"] for pair in snapshot["chapters"]["第1話.md"]],
            ["alpha raw"],
        )
        self.assertEqual(
            [item["pair_index"] for item in snapshot["source_provenance"]["第1話.md"]["pair_mappings"]],
            [1],
        )

    def test_pending_and_stale_receipts_cannot_publish(self):
        self._template()
        with self.assertRaisesRegex(ValueError, "pending or unknown"):
            self._publish()

        self._complete_receipt()
        with self.tm_path.open("a", encoding="utf-8") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(ValueError, "current inputs"):
            self._publish()
        self.assertFalse(self.bundle_path.exists())

    def test_reviewed_snapshot_rejects_source_changes(self):
        self._template()
        self._complete_receipt()
        self._publish()

        self.translation_path.write_text(
            "changed target\n\nbeta target\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "fully verified"):
            load_reviewed_tm_snapshot(
                str(self.bundle_path),
                str(self.source_root),
                str(self.translation_root),
                "source_manifest.json",
            )

    def test_rag_uses_only_the_explicit_reviewed_snapshot(self):
        self._template()
        self._complete_receipt()
        self._publish()
        rag = RAGEngine(
            str(self.tm_path),
            str(self.knowledge_root / "Glossary.json"),
            str(self.knowledge_root / "guidelines.txt"),
            source_root=str(self.source_root),
            source_manifest_path="source_manifest.json",
            reviewed_tm_path=str(self.bundle_path),
            translation_root=str(self.translation_root),
        )

        with patch.object(
            RAGEngine,
            "_generate_embedding_sync",
            return_value=[1.0, 0.0],
        ):
            result = asyncio.run(
                rag.query_translation_memory("synthetic query", top_k=5)
            )

        self.assertEqual(
            result,
            [{"raw": "alpha raw", "translated": "alpha target"}],
        )
        self.assertEqual(len(rag.tm_data["chapters"]["第1話.md"]), 2)
        self.assertEqual(
            len(rag.tm_retrieval_data["chapters"]["第1話.md"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
