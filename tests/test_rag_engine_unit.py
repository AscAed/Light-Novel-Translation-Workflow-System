# tests/test_rag_engine_unit.py
# Unit tests for RAGEngine class in rag_engine.py.
# Compliant with Australian English spelling conventions.

import os
import json
import unittest
import tempfile
import shutil
import numpy as np
from unittest.mock import patch, MagicMock
from rag_engine import RAGEngine


class TestRAGEngineUnit(unittest.TestCase):

    def setUp(self):
        """Set up a temporary directory and default paths for RAGEngine testing."""
        self.test_dir = tempfile.mkdtemp()
        self.tm_path = os.path.join(self.test_dir, "translation_memory.json")
        self.glossary_path = os.path.join(self.test_dir, "Glossary.json")
        self.guidelines_path = os.path.join(self.test_dir, "guidelines.txt")

        # Set up default files with minimal mock data
        self.default_tm = {
            "chapters": {
                "第1話.md": [
                    {"raw": "こんにちは", "translated": "你好", "embedding": [0.1] * 768},
                    {"raw": "さようなら", "translated": "再见", "embedding": [-0.1] * 768}
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
        """Verify RAGEngine initialises and ignores invalid JSON in database files."""
        bad_json_path = os.path.join(self.test_dir, "bad.json")
        with open(bad_json_path, "w", encoding="utf-8") as f:
            f.write("{invalid json content}")

        engine = RAGEngine(
            tm_path=bad_json_path,
            glossary_path=bad_json_path,
            guidelines_path=self.guidelines_path
        )
        self.assertEqual(engine.tm_data, {"chapters": {}})
        self.assertEqual(engine.glossary_raw, "{invalid json content}")

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
    def test_query_translation_memory_similarity(self, mock_embed):
        """Verify cosine similarity search retrieves the closest matches from TM."""
        # Query matching closer to the first vector
        mock_embed.return_value = [0.11] * 768
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        
        import asyncio
        res = asyncio.run(engine.query_translation_memory("hello", top_k=1))
        
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["raw"], "こんにちは")

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

    def test_get_partitioned_guidelines_direct_match(self):
        """Verify guidelines direct matching retrieves specific chapter rules."""
        engine = RAGEngine(self.tm_path, self.glossary_path, self.guidelines_path)
        res = engine.get_partitioned_guidelines("第1話.md")
        self.assertIn("Global guidelines content.", res)
        self.assertIn("Chapter 1 specific guidelines.", res)
        self.assertNotIn("Chapter 2 specific guidelines.", res)

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
        engine.update_translation_memory("第2話.md", pairs)
        
        # Verify it was updated in memory
        self.assertIn("第2話.md", engine.tm_data["chapters"])
        self.assertEqual(engine.tm_data["chapters"]["第2話.md"][0]["raw"], "新原文")
        self.assertEqual(engine.tm_data["chapters"]["第2話.md"][0]["embedding"], [0.5] * 768)

        # Verify it was saved to file
        with open(self.tm_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("第2話.md", data["chapters"])


if __name__ == "__main__":
    unittest.main()
