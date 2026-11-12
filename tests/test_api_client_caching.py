"""Regression tests for API client reuse added to the pipeline and RAG engine."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pipeline
import rag_engine
from rag_engine import RAGEngine
from scripts import align_chapters


def make_embedding_client(values):
    client = MagicMock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=values)]
    )
    return client


class TestAPIClientCaching(unittest.TestCase):
    def test_rag_engine_reuses_clients_and_separates_api_keys(self):
        first_client = make_embedding_client([0.1, 0.2])
        second_client = make_embedding_client([0.3, 0.4])
        engine = RAGEngine(
            "missing-tm.json", "missing-glossary.json", "missing-guidelines.txt"
        )

        with (
            patch.object(rag_engine, "_gemini_clients", {}) as cache,
            patch(
                "google.genai.Client", side_effect=[first_client, second_client]
            ) as client_factory,
            patch.dict(os.environ, {"MOCK_SERVER_PORT": "", "API_TIMEOUT": "1200"}),
        ):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "key-one"}):
                self.assertEqual(engine._generate_embedding_sync("first"), [0.1, 0.2])
                self.assertEqual(engine._generate_embedding_sync("second"), [0.1, 0.2])
            with patch.dict(os.environ, {"GEMINI_API_KEY": "key-two"}):
                self.assertEqual(engine._generate_embedding_sync("third"), [0.3, 0.4])

            self.assertEqual(set(cache), {"key-one", "key-two"})
            self.assertEqual(client_factory.call_count, 2)
            first_client.models.embed_content.assert_has_calls(
                [
                    call(model="gemini-embedding-2", contents=["first"]),
                    call(model="gemini-embedding-2", contents=["second"]),
                ]
            )
            client_factory.assert_any_call(http_options={"timeout": 1200.0})

    def test_align_script_reuses_clients_and_separates_api_keys(self):
        first_client = make_embedding_client([0.1])
        second_client = make_embedding_client([0.2])

        with (
            patch.object(align_chapters, "_gemini_clients", {}) as cache,
            patch(
                "google.genai.Client", side_effect=[first_client, second_client]
            ) as client_factory,
            patch.dict(os.environ, {"MOCK_SERVER_PORT": "", "API_TIMEOUT": "1200"}),
        ):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "key-one"}):
                self.assertEqual(
                    align_chapters.generate_embeddings_batched(["first"]), [[0.1]]
                )
                self.assertEqual(
                    align_chapters.generate_embeddings_batched(["second"]), [[0.1]]
                )
            with patch.dict(os.environ, {"GEMINI_API_KEY": "key-two"}):
                self.assertEqual(
                    align_chapters.generate_embeddings_batched(["third"]), [[0.2]]
                )

            self.assertEqual(set(cache), {"key-one", "key-two"})
            self.assertEqual(client_factory.call_count, 2)
            client_factory.assert_any_call(http_options={"timeout": 1200.0})


class TestPipelineClientCaching(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_client_is_reused_and_api_key_isolated(self):
        first_client = MagicMock()
        first_client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(text="ok", candidates=[])
        )
        second_client = MagicMock()
        second_client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(text="ok", candidates=[])
        )

        with (
            patch.object(pipeline, "_gemini_clients", {}) as cache,
            patch(
                "pipeline.get_api_key", side_effect=["key-one", "key-one", "key-two"]
            ),
            patch(
                "google.genai.Client", side_effect=[first_client, second_client]
            ) as client_factory,
            patch.dict(os.environ, {"MOCK_SERVER_PORT": "", "API_TIMEOUT": "1200"}),
        ):
            agent = pipeline.UnifiedAgent("test-model", "system instruction")
            self.assertEqual(await agent._call_gemini("prompt 1", "system"), "ok")
            self.assertEqual(await agent._call_gemini("prompt 2", "system"), "ok")
            self.assertEqual(await agent._call_gemini("prompt 3", "system"), "ok")

            self.assertEqual(set(cache), {"key-one", "key-two"})
            self.assertEqual(client_factory.call_count, 2)
            client_factory.assert_any_call(
                api_key="key-one", http_options={"timeout": 1200.0}
            )
            client_factory.assert_any_call(
                api_key="key-two", http_options={"timeout": 1200.0}
            )

    def test_openai_client_is_reused_by_url_and_api_key(self):
        with (
            patch.object(pipeline, "_openai_clients", {}) as cache,
            patch(
                "pipeline.AsyncOpenAI", side_effect=[MagicMock(), MagicMock()]
            ) as client_factory,
            patch.dict(os.environ, {"MOCK_SERVER_PORT": "", "API_TIMEOUT": "1200"}),
        ):
            first = pipeline.get_openai_client(
                "https://api.example.invalid/v1", "key-one"
            )
            self.assertIs(
                pipeline.get_openai_client("https://api.example.invalid/v1", "key-one"),
                first,
            )
            second = pipeline.get_openai_client(
                "https://api.example.invalid/v1", "key-two"
            )

            self.assertIsNot(second, first)
            self.assertEqual(len(cache), 2)
            self.assertEqual(client_factory.call_count, 2)
            client_factory.assert_any_call(
                api_key="key-one",
                base_url="https://api.example.invalid/v1",
                timeout=1200.0,
            )
            client_factory.assert_any_call(
                api_key="key-two",
                base_url="https://api.example.invalid/v1",
                timeout=1200.0,
            )


if __name__ == "__main__":
    unittest.main()
