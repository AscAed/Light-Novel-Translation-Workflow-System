import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from pipeline import Config, ContentBlockedError, TranslationPipeline, UnifiedAgent, get_api_key


class TestProviderRouting(unittest.IsolatedAsyncioTestCase):
    @patch.dict(os.environ, {"CODING_PLAN_API_KEY": "shared-key"}, clear=True)
    async def test_api_key_does_not_fall_back_to_an_unrelated_provider(self):
        self.assertIsNone(get_api_key("DEEPSEEK_API_KEY"))

    @patch.dict(os.environ, {}, clear=True)
    async def test_primary_failure_does_not_send_content_to_gemini_by_default(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", False):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                await agent.call("source text")
        agent._call_gemini.assert_not_awaited()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_explicit_fallback_setting_allows_gemini_retry(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
            self.assertEqual(await agent.call("source text"), "fallback")
        agent._call_gemini.assert_awaited_once()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_content_filter_does_not_trigger_provider_failover(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(side_effect=ContentBlockedError("blocked"))
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
            with self.assertRaisesRegex(ContentBlockedError, "blocked"):
                await agent.call("source text")
        agent._call_gemini.assert_not_awaited()


class TestTestWorkspaceConfiguration(unittest.TestCase):
    def test_test_workspace_populates_all_path_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            tm_path = workspace / "custom" / "memory.json"
            env = {
                "TEST_WORKSPACE_DIR": str(workspace),
                "TEST_TM_PATH": str(tm_path),
                "TEST_RAW_DIR": str(workspace / "input"),
                "TEST_OUTPUT_DIR": str(workspace / "output"),
            }
            with patch.dict(os.environ, env, clear=True):
                Config.load_config()

            self.assertEqual(Config.TM_PATH, str(tm_path))
            self.assertEqual(Config.RAW_DIR, str(workspace / "input"))
            self.assertEqual(Config.OUTPUT_DIR, str(workspace / "output"))


class TestParagraphContracts(unittest.IsolatedAsyncioTestCase):
    async def test_translation_phase_rejects_mismatched_paragraph_count(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(return_value={"translated_paragraphs": ["one result"]})

        with patch("pipeline.UnifiedAgent", return_value=fake_agent):
            with self.assertRaisesRegex(ValueError, "Translation returned 1 paragraphs for 2"):
                await pipeline._run_translation_phase("one\n\ntwo", "", [])

    async def test_proofreader_mismatch_keeps_the_previous_aligned_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(return_value={
            "severity": "none",
            "critique": "",
            "corrected_text": ["short result"],
        })
        polisher = Mock()
        polisher.call = AsyncMock(return_value={"polished_paragraphs": []})

        with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
            result = await pipeline._run_refinement_loop(
                "source one\n\nsource two",
                ["translation one", "translation two"],
                "",
                [],
            )
        self.assertEqual(result, ["translation one", "translation two"])


if __name__ == "__main__":
    unittest.main()
