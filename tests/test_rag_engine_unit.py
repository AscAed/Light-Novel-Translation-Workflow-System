# tests/test_rag_engine_unit.py
# Unit tests for RAGEngine class in rag_engine.py.
# Compliant with Australian English spelling conventions.

import os
import json
import hashlib
import asyncio
import unittest
import tempfile
import shutil
import numpy as np
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch, MagicMock
from rag_engine import RAGEngine
from embedding_provider import embedding_identity_for_vector
from embedding_provider import is_compatible_embedding
from utils import write_bytes_atomically


class TestRAGEngineUnit(unittest.TestCase):

    def setUp(self):
        """Set up a temporary directory and default paths for RAGEngine testing."""
        self.test_dir = tempfile.mkdtemp()
        self.tm_path = os.path.join(self.test_dir, "translation_memory.json")
        self.glossary_path = os.path.join(self.test_dir, "Glossary.json")
        self.guidelines_path = os.path.join(self.test_dir, "guidelines.txt")

        # Set up default files with minimal mock data
        embedding = [0.1] * 768
        embedding_identity = embedding_identity_for_vector(embedding)
        self.default_tm = {
            "chapters": {
                "第1話.md": [
                    {
                        "raw": "こんにちは",
                        "translated": "你好",
                        "embedding": embedding,
                        "embedding_identity": embedding_identity,
                    },
                    {
                        "raw": "さようなら",
                        "translated": "再见",
                        "embedding": [-0.1] * 768,
                        "embedding_identity": embedding_identity,
                    }
                ]
            }
        }
        with open(self.tm_path, "w", encoding="utf-8") as f:
            json.dump(self.default_tm, f)

        self.default_glossary = """
        // This is a single-line comment in glossary
        {
            "ネトラレラ (Netorarera)": "努力豆（マメ本意为...） / 老茧",
            "テスト": "测试"
        }
        """
        with open(self.glossary_path, "w", encoding="utf-8") as f:
            f.write(self.default_glossary)

        self.default_guidelines = """《翻译指导原则》
Global guidelines content.
《翻译指导原则》 - [第 1 章]
Chapter 1 specific guidelines.
《翻译指导原则》 - [第 2 章]
Chapter 2 specific guidelines.
"""
        with open(self.guidelines_path, "w", encoding="utf-8") as f:
            f.write(self.default_guidelines)

    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initialise_with_missing_files(self):
        """Verify RAGEngine initialises gracefully when input files are missing."""
        engine = RAGEngine(
            tm_path=os.path.join(self.test_dir, "nonexistent_tm.json"),
            glossary_path=os.path.join(self.test_dir, "nonexistent_glossary.json"),
            guidelines_path=os.path.join(self.test_dir, "nonexistent_guidelines.txt")
        )
        self.assertEqual(engine.tm_data, {"chapters": {}})
        self.assertEqual(engine.glossary_raw, "")
        self.assertEqual(engine.guidelines_raw, "")

    def test_initialise_with_invalid_json(self):
        """Verify RAGEngine initialises and raises on invalid JSON in database files."""
        bad_json_path = os.path.join(self.test_dir, "bad.json")
        with open(bad_json_path, "w", encoding="utf-8") as f:
            f.write("{invalid json content}")

        import json
        with self.assertRaises(json.JSONDecodeError):
            RAGEngine(
                tm_path=bad_json_path,
                glossary_path=bad_json_path,
                guidelines_path=self.guidelines_path
            )

    def test_reviewed_tm_uses_publication_root_when_output_is_a_draft_root(self):
        with patch("rag_engine.load_reviewed_tm_snapshot") as load_snapshot:
            RAGEngine(
                self.tm_path,
                self.glossary_path,
                self.guidelines_path,
                source_root="source",
                source_manifest_path="source_manifest.json",
                reviewed_tm_path="reviewed_tm.json",
                translation_root="run/Drafts",
                reviewed_tm_translation_root="published",
            )

        load_snapshot.assert_called_once_with(
            "reviewed_tm.json",
            "source",
            "published",
            "source_manifest.json",
            source_input_root=None,
            source_input_map=None,
        )

    def test_draft_glossary_cannot_be_loaded_for_retrieval(self):
        draft_path = os.path.join(self.test_dir, "Glossary_draft.json")
        with open(draft_path, "w", encoding="utf-8") as f:
            json.dump({"候选词": "候选译名"}, f)

        with self.assertRaisesRegex(ValueError, "candidate draft"):
            RAGEngine(self.tm_path, draft_path, self.guidelines_path)

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_query_translation_memory_empty(self, mock_embed):
        """Verify querying translation memory with empty input returns empty list."""
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        # Empty query
        import asyncio
        res = asyncio.run(engine.query_translation_memory(""))
        self.assertEqual(res, [])
        mock_embed.assert_not_called()

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_unreviewed_tm_is_not_retrieved_by_default(self, mock_embed):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)

        import asyncio
        res = asyncio.run(engine.query_translation_memory("hello"))

        self.assertEqual(res, [])
        self.assertEqual(engine.tm_data, self.default_tm)
        self.assertEqual(engine.tm_retrieval_data, {"chapters": {}})
        mock_embed.assert_not_called()

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_query_translation_memory_similarity(self, mock_embed):
        """Verify cosine similarity search retrieves the closest matches from TM."""
        # Query matching closer to the first vector
        mock_embed.return_value = [0.11] * 768
        engine = RAGEngine(
            self.tm_path,
            self.glossary_path,
            self.guidelines_path,
            allow_unreviewed_tm=True,
        )
        
        import asyncio
        res = asyncio.run(engine.query_translation_memory("hello", top_k=1))
        
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["raw"], "こんにちは")

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_legacy_vectors_without_identity_are_not_retrieved(self, mock_embed):
        legacy_tm = json.loads(json.dumps(self.default_tm))
        for pair in legacy_tm["chapters"]["第1話.md"]:
            pair.pop("embedding_identity")
        Path(self.tm_path).write_text(
            json.dumps(legacy_tm), encoding="utf-8"
        )
        engine = RAGEngine(
            self.tm_path,
            self.glossary_path,
            self.guidelines_path,
            allow_unreviewed_tm=True,
        )

        result = asyncio.run(engine.query_translation_memory("synthetic query"))

        self.assertEqual(result, [])
        mock_embed.assert_not_called()

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_vectors_with_a_different_identity_are_not_retrieved(self, mock_embed):
        incompatible_tm = json.loads(json.dumps(self.default_tm))
        for pair in incompatible_tm["chapters"]["第1話.md"]:
            pair["embedding_identity"]["model"] = "different-model"
        Path(self.tm_path).write_text(
            json.dumps(incompatible_tm), encoding="utf-8"
        )
        engine = RAGEngine(
            self.tm_path,
            self.glossary_path,
            self.guidelines_path,
            allow_unreviewed_tm=True,
        )

        result = asyncio.run(engine.query_translation_memory("synthetic query"))

        self.assertEqual(result, [])
        mock_embed.assert_not_called()

    def test_embedding_identity_requires_exact_model_and_dimension_types(self):
        vector = [0.25, 0.75]
        identity = embedding_identity_for_vector(vector)

        self.assertTrue(is_compatible_embedding(vector, identity))
        self.assertFalse(is_compatible_embedding(vector + [0.5], identity))
        self.assertFalse(
            is_compatible_embedding(
                vector,
                {**identity, "schema_version": True},
            )
        )

    @patch(
        "rag_engine.RAGEngine._generate_embedding_sync",
        side_effect=RuntimeError("SYNTHETIC_PRIVATE_ERROR"),
    )
    def test_query_embedding_failure_is_not_reported_as_no_matches(self, mock_embed):
        engine = RAGEngine(
            self.tm_path,
            self.glossary_path,
            self.guidelines_path,
            allow_unreviewed_tm=True,
        )

        with self.assertRaisesRegex(RuntimeError, "embedding failed") as raised:
            import asyncio
            asyncio.run(engine.query_translation_memory("synthetic query"))

        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", str(raised.exception))
        mock_embed.assert_called_once_with("synthetic query")

    def test_get_cleaned_glossary_matches(self):
        """Verify glossary cleans keys/values and matches terms in raw text."""
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        
        # Matches "ネトラレラ"
        res = engine.get_cleaned_glossary("这里有ネトラレラ的存在。")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["src"], "ネトラレラ")
        self.assertEqual(res[0]["dst"], "努力豆")
        self.assertEqual(res[0]["info"], "努力豆（マメ本意为...） / 老茧")

        # Matches "测试" which is the translation for "テスト"
        res_test = engine.get_cleaned_glossary("进行テスト中。")
        self.assertEqual(len(res_test), 1)
        self.assertEqual(res_test[0]["src"], "テスト")
        self.assertEqual(res_test[0]["dst"], "测试")

    def test_get_cleaned_glossary_merges_reviewed_chapter_terms(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)

        result = engine.get_cleaned_glossary(
            "alpha appears",
            additional_glossary={"alpha": "阿尔法"},
        )

        self.assertEqual(
            result,
            [{"src": "alpha", "dst": "阿尔法", "info": "阿尔法"}],
        )

    def test_get_cleaned_glossary_rejects_conflicting_reviewed_terms(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)

        with self.assertRaisesRegex(ValueError, "glossaries conflict"):
            engine.get_cleaned_glossary(
                "ネトラレラ",
                additional_glossary={"ネトラレラ (Netorarera)": "另一个译名"},
            )

    def test_get_cleaned_glossary_preserves_global_alias_matches(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.glossary_raw = '{"alpha/beta":"甲","alpha":"乙"}'

        result = engine.get_cleaned_glossary("alpha")

        self.assertEqual(
            result,
            [
                {"src": "alpha", "dst": "甲", "info": "甲"},
                {"src": "alpha", "dst": "乙", "info": "乙"},
            ],
        )

    def test_get_cleaned_glossary_rejects_local_alias_conflict(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.glossary_raw = '{"alpha/beta":"甲"}'

        with self.assertRaisesRegex(ValueError, "conflicting source terms"):
            engine.get_cleaned_glossary(
                "alpha",
                additional_glossary={"alpha": "乙"},
            )

    def test_get_cleaned_glossary_rejects_conflicting_secondary_alias(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.glossary_raw = '{"alpha/beta":"甲"}'

        with self.assertRaisesRegex(ValueError, "conflicting source terms"):
            engine.get_cleaned_glossary(
                "beta",
                additional_glossary={"beta": "乙"},
            )

    def test_get_cleaned_glossary_compares_destinations_not_descriptions(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.glossary_raw = '{"alpha":"甲（全书说明）"}'

        result = engine.get_cleaned_glossary(
            "alpha",
            additional_glossary={"alpha": "甲（本话说明）"},
        )

        self.assertEqual(
            result,
            [
                {"src": "alpha", "dst": "甲", "info": "甲（全书说明）"},
                {"src": "alpha", "dst": "甲", "info": "甲（本话说明）"},
            ],
        )

    def test_get_cleaned_glossary_keeps_local_participation_for_same_value(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.glossary_raw = '{"alpha/beta":"甲","alpha":"乙"}'

        with self.assertRaisesRegex(ValueError, "conflicting source terms"):
            engine.get_cleaned_glossary(
                "alpha",
                additional_glossary={"alpha": "乙"},
            )

    def test_get_partitioned_guidelines_direct_match(self):
        """Verify guidelines direct matching retrieves specific chapter rules."""
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        res = engine.get_partitioned_guidelines("第1話.md")
        self.assertIn("Global guidelines content.", res)
        self.assertIn("Chapter 1 specific guidelines.", res)
        self.assertNotIn("Chapter 2 specific guidelines.", res)

    def test_mapped_filename_uses_chapter_number_not_volume_number(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.guidelines_raw = (
            "《翻译指导原则》 - [第 2 章]\nVolume 2 guidance.\n"
            "《翻译指导原则》 - [第 10 章]\nChapter 10 guidance."
        )

        result = engine.get_partitioned_guidelines("Volume 2/chapter10.md")

        self.assertIn("Chapter 10 guidance.", result)
        self.assertNotIn("Volume 2 guidance.", result)

    def test_explicit_chapter_position_overrides_opaque_source_filename(self):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        engine.guidelines_raw = (
            "《翻译指导原则》 - [第 1 章]\nChapter 1 guidance.\n"
            "《翻译指导原则》 - [第 2 章]\nChapter 2 guidance."
        )

        result = engine.get_partitioned_guidelines(
            "normalized/opaque-hash.md",
            chapter_position=2,
        )

        self.assertIn("Chapter 2 guidance.", result)
        self.assertNotIn("Chapter 1 guidance.", result)

    @patch("rag_engine.RAGEngine._load_current_chapter_raw")
    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_get_partitioned_guidelines_absolute_fallback(self, mock_embed, mock_load):
        """Verify absolute difference fallback matches the closest chapter number."""
        # Chapter 3 requested, guidelines only exist for 1 and 2.
        # It should fall back to Chapter 2 (closest by absolute difference).
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        mock_load.return_value = ""
        mock_embed.return_value = [0.1] * 768
        
        res = engine.get_partitioned_guidelines("第3話.md")
        self.assertIn("Global guidelines content.", res)
        self.assertIn("Chapter 2 specific guidelines.", res)

    @patch("rag_engine.RAGEngine._load_current_chapter_raw")
    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    @patch("rag_engine.RAGEngine._find_best_semantic_match")
    def test_guideline_fallback_uses_supplied_mapped_source_text(
        self, mock_best_match, mock_embed, mock_load
    ):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        mock_embed.return_value = [0.1] * 768
        mock_best_match.return_value = 1

        result = engine.get_partitioned_guidelines(
            "Volume1/第3話.md",
            current_raw_text="synthetic mapped source",
        )

        self.assertIn("Chapter 1 specific guidelines.", result)
        mock_load.assert_not_called()
        mock_embed.assert_called_once_with("synthetic mapped source")
        mock_best_match.assert_called_once()

    def test_get_partitioned_guidelines_truncation(self):
        """Verify combined guidelines are truncated when exceeding size limits."""
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        # Set a very long guidelines text
        engine.guidelines_raw = "Global rule\n" * 1500 + "\n《翻译指导原则》 - [第 1 章]\nChapter 1 info"
        
        res = engine.get_partitioned_guidelines("第1話.md")
        self.assertTrue(len(res.encode("utf-8")) < 10240)
        self.assertTrue(res.endswith("[Truncated due to length limit]"))

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_update_translation_memory(self, mock_embed):
        """Verify updating translation memory appends items and saves database."""
        mock_embed.return_value = [0.5] * 768
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        
        pairs = [{"raw": "新原文", "translated": "新译文"}]
        source_provenance = {
            "schema_version": 1,
            "producer": "pipeline",
            "raw_file": "第2話.md",
            "raw_sha256": "a" * 64,
            "translation_file": "第2話.md",
            "translation_sha256": "b" * 64,
            "pair_mappings": [
                {
                    "pair_index": 1,
                    "raw_paragraph_indices": [1],
                    "translation_paragraph_indices": [1],
                    "trace_status": "matched",
                }
            ],
        }
        engine.update_translation_memory(
            "第2話.md", pairs, source_provenance=source_provenance
        )
        
        # Verify it was updated in memory
        self.assertIn("第2話.md", engine.tm_data["chapters"])
        self.assertEqual(engine.tm_data["chapters"]["第2話.md"][0]["raw"], "新原文")
        self.assertEqual(engine.tm_data["chapters"]["第2話.md"][0]["embedding"], [0.5] * 768)
        self.assertEqual(
            engine.tm_data["chapters"]["第2話.md"][0]["embedding_identity"],
            embedding_identity_for_vector([0.5] * 768),
        )
        self.assertEqual(
            engine.tm_data["source_provenance"]["第2話.md"],
            source_provenance,
        )

        # Verify it was saved to file
        with open(self.tm_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("第2話.md", data["chapters"])
            self.assertEqual(
                data["source_provenance"]["第2話.md"],
                source_provenance,
            )

    @patch("rag_engine.RAGEngine._generate_embedding_sync")
    def test_invalid_tm_source_provenance_is_rejected_before_embedding(
        self, mock_embed
    ):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)

        with self.assertRaisesRegex(ValueError, "valid raw_sha256"):
            engine.update_translation_memory(
                "第2話.md",
                [{"raw": "新原文", "translated": "新译文"}],
                source_provenance={
                    "schema_version": 1,
                    "producer": "pipeline",
                    "raw_file": "第2話.md",
                    "raw_sha256": "invalid",
                    "translation_file": "第2話.md",
                    "translation_sha256": "b" * 64,
                    "pair_mappings": [],
                },
            )

        mock_embed.assert_not_called()

    @patch("rag_engine.RAGEngine._generate_embedding_sync", return_value=[0.5] * 768)
    def test_overwriting_chapter_without_provenance_clears_stale_mapping(
        self, mock_embed
    ):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        stale_mapping = {
            "schema_version": 1,
            "producer": "pipeline",
            "raw_file": "第2話.md",
            "raw_sha256": "a" * 64,
            "translation_file": "第2話.md",
            "translation_sha256": "b" * 64,
            "pair_mappings": [
                {
                    "pair_index": 1,
                    "raw_paragraph_indices": [1],
                    "translation_paragraph_indices": [1],
                    "trace_status": "matched",
                }
            ],
        }
        other_chapter_mapping = dict(stale_mapping, raw_file="第3話.md")
        engine.tm_data["chapters"]["第2話.md"] = [
            {"raw": "旧原文", "translated": "旧译文", "embedding": [0.1] * 768}
        ]
        engine.tm_data["source_provenance"] = {
            "第2話.md": stale_mapping,
            "第3話.md": other_chapter_mapping,
        }

        engine.update_translation_memory(
            "第2話.md",
            [{"raw": "新原文", "translated": "新译文"}],
        )

        self.assertNotIn("第2話.md", engine.tm_data["source_provenance"])
        self.assertEqual(
            engine.tm_data["source_provenance"]["第3話.md"],
            other_chapter_mapping,
        )
        with open(self.tm_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertNotIn("第2話.md", saved_data["source_provenance"])
        self.assertEqual(
            saved_data["source_provenance"]["第3話.md"],
            other_chapter_mapping,
        )

        engine.update_translation_memory(
            "第3話.md",
            [{"raw": "第三章新原文", "translated": "第三章新译文"}],
        )

        self.assertNotIn("source_provenance", engine.tm_data)
        with open(self.tm_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertNotIn("source_provenance", saved_data)
        self.assertEqual(mock_embed.call_count, 2)

    @patch(
        "rag_engine.RAGEngine._generate_embedding_sync",
        side_effect=RuntimeError("SYNTHETIC_PRIVATE_ERROR"),
    )
    def test_embedding_failure_aborts_tm_update_without_partial_write(self, mock_embed):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        original_data = json.loads(json.dumps(engine.tm_data))
        original_bytes = Path(self.tm_path).read_bytes()
        with self.assertLogs("rag_engine", level="WARNING") as captured:
            with self.assertRaisesRegex(RuntimeError, "TM update was aborted") as raised:
                engine.update_translation_memory(
                    "第3話.md",
                    [{"raw": "新原文", "translated": "新译文"}],
                )

        self.assertEqual(engine.tm_data, original_data)
        self.assertEqual(Path(self.tm_path).read_bytes(), original_bytes)
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", str(raised.exception))
        self.assertNotIn(
            "SYNTHETIC_PRIVATE_ERROR", "\n".join(captured.output)
        )

    @patch("rag_engine.RAGEngine._generate_embedding_sync", return_value=[0.5] * 768)
    def test_translation_memory_persistence_failure_preserves_state_for_retry(
        self, mock_embed
    ):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        original_tm_data = json.loads(json.dumps(engine.tm_data))
        cached_embedding = [0.25] * 768
        engine._chapter_tm_embeddings_cache = {"第3話.md": cached_embedding}

        with patch(
            "rag_engine.write_bytes_atomically", side_effect=OSError("disk full")
        ) as mock_write:
            with self.assertRaisesRegex(OSError, "disk full"):
                engine.update_translation_memory(
                    "第3話.md",
                    [{"raw": "新原文", "translated": "新译文"}],
                )

        mock_write.assert_called_once()
        self.assertEqual(engine.tm_data, original_tm_data)
        self.assertIs(
            engine._chapter_tm_embeddings_cache["第3話.md"],
            cached_embedding,
        )

        engine.update_translation_memory(
            "第3話.md",
            [{"raw": "新原文", "translated": "新译文"}],
        )

        with open(self.tm_path, "r", encoding="utf-8") as stream:
            saved_tm_data = json.load(stream)
        self.assertEqual(
            saved_tm_data["chapters"]["第3話.md"][0]["raw"], "新原文"
        )
        self.assertEqual(engine.tm_data, saved_tm_data)
        self.assertNotIn("第3話.md", engine._chapter_tm_embeddings_cache)
        self.assertEqual(mock_embed.call_count, 2)

    @patch("rag_engine.RAGEngine._generate_embedding_sync", return_value=[0.5] * 768)
    def test_tm_fingerprint_tracks_written_snapshot_not_later_external_edit(
        self, mock_embed
    ):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        written = {}

        def write_then_edit(path, content):
            written["content"] = content
            write_bytes_atomically(path, content)
            Path(path).write_bytes(b'{"chapters": {"external.md": []}}')

        with patch("rag_engine.write_bytes_atomically", side_effect=write_then_edit):
            engine.update_translation_memory(
                "第3話.md",
                [{"raw": "新原文", "translated": "新译文"}],
            )

        expected_fingerprint = hashlib.sha256(written["content"]).hexdigest()
        self.assertEqual(engine._tm_disk_sha256, expected_fingerprint)
        self.assertNotEqual(engine.current_tm_disk_sha256(), expected_fingerprint)
        with self.assertRaisesRegex(RuntimeError, "changed on disk"):
            engine.update_translation_memory(
                "第4話.md",
                [{"raw": "another source", "translated": "another translation"}],
            )
        self.assertEqual(mock_embed.call_count, 1)

    @patch("rag_engine.RAGEngine._generate_embedding_sync", return_value=[0.5] * 768)
    def test_external_tm_change_is_not_overwritten(self, mock_embed):
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        original_data = json.loads(json.dumps(engine.tm_data))
        with open(self.tm_path, "w", encoding="utf-8") as stream:
            json.dump({"chapters": {"external.md": []}}, stream)

        with self.assertRaisesRegex(RuntimeError, "changed on disk"):
            engine.update_translation_memory(
                "第3話.md",
                [{"raw": "新原文", "translated": "新译文"}],
            )

        self.assertEqual(engine.tm_data, original_data)
        mock_embed.assert_not_called()

    def test_mock_embedding_response_without_values_is_rejected(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{}"
        with patch.dict(os.environ, {"MOCK_SERVER_PORT": "1234"}):
            with patch("urllib.request.urlopen", return_value=response):
                engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
                engine.provider_data_policy = {"gemini": {"source_text"}}
                with self.assertRaisesRegex(RuntimeError, "invalid vector"):
                    engine._generate_embedding_sync("query")

    def test_gemini_embedding_client_uses_configured_request_timeout(self):
        client = MagicMock()
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.5] * 768)]
        )
        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")
        http_options_args = {}

        def make_http_options(**kwargs):
            http_options_args.update(kwargs)
            return SimpleNamespace(**kwargs)

        types_module.HttpOptions = make_http_options
        genai_module.Client = MagicMock(return_value=client)
        google_module.genai = genai_module

        with patch.dict(
            "sys.modules",
            {
                "google": google_module,
                "google.genai": genai_module,
                "google.genai.types": types_module,
            },
        ):
            with patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "API_TIMEOUT": "3.5",
                    "PROVIDER_DATA_POLICY": '{"gemini":["source_text"]}',
                },
                clear=True,
            ):
                engine = RAGEngine(
                    self.tm_path, self.glossary_path, self.guidelines_path
                )
                result = engine._generate_embedding_sync("query")

        self.assertEqual(result, [0.5] * 768)
        self.assertEqual(http_options_args, {"timeout": 3500})
        genai_module.Client.assert_called_once_with(
            api_key="test-key",
            http_options=SimpleNamespace(timeout=3500),
        )

    def test_external_embedding_is_blocked_without_explicit_data_grant(self):
        with patch.dict(os.environ, {}, clear=True):
            engine = RAGEngine(
                self.tm_path, self.glossary_path, self.guidelines_path
            )
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                engine._generate_embedding_sync("source paragraph")

    def test_mock_embedding_uses_validated_timeout_in_seconds(self):
        engine = RAGEngine(
            self.tm_path,
            self.glossary_path,
            self.guidelines_path,
            api_timeout=3.5,
            provider_data_policy={"gemini": {"source_text"}},
        )
        response = json.dumps({"embedding": {"values": [0.5] * 768}}).encode("utf-8")
        with patch.dict(os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True):
            with patch("urllib.request.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value = response
                self.assertEqual(engine._generate_embedding_sync("query"), [0.5] * 768)

        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.5)


if __name__ == "__main__":
    unittest.main()
