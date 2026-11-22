from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from embedding_provider import (
    embedding_identity_for_vector,
    generate_embeddings,
    is_compatible_embedding,
)


class EmbeddingProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "provider": "embed_primary",
            "protocol": "openai-compatible",
            "base_url": "https://embed.example.test/v1",
            "model": "embed-model-v2",
        }
        self.environment = {
            "TRANSLATORAI_EMBEDDING_CONFIG": json.dumps(self.config),
            "TRANSLATORAI_EMBEDDING_KEY": "synthetic-secret",
        }
        self.policy = {"embed_primary": frozenset({"source_text"})}

    @staticmethod
    def _response(vectors):
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=vector)
                for index, vector in enumerate(vectors)
            ]
        )

    def test_openai_compatible_embeddings_are_ordered_and_identity_bound(self):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ]
        )
        with patch.dict(
            os.environ,
            {**self.environment, "MOCK_SERVER_PORT": ""},
        ), patch(
            "openai.OpenAI", return_value=client
        ) as openai_client:
            vectors, identity = generate_embeddings(
                ["first", "second"],
                batch_size=2,
                api_timeout=3,
                provider_data_policy=self.policy,
            )

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(
            identity,
            embedding_identity_for_vector(vectors[0], self.config),
        )
        self.assertEqual(openai_client.call_args.kwargs["api_key"], "synthetic-secret")
        self.assertEqual(
            openai_client.call_args.kwargs["base_url"],
            self.config["base_url"],
        )
        self.assertEqual(openai_client.call_args.kwargs["timeout"], 3)
        self.assertEqual(openai_client.call_args.kwargs["max_retries"], 0)
        self.assertEqual(
            client.embeddings.create.call_args.kwargs,
            {
                "model": "embed-model-v2",
                "input": ["first", "second"],
                "encoding_format": "float",
            },
        )

    def test_openai_compatible_sdk_uses_loopback_embedding_route(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                captured.append((self.path, self.headers.get("Authorization"), payload))
                response = {
                    "object": "list",
                    "data": [
                        {
                            "object": "embedding",
                            "index": index,
                            "embedding": [float(index + 1), 0.5],
                        }
                        for index, _ in enumerate(payload["input"])
                    ],
                    "model": payload["model"],
                    "usage": {
                        "prompt_tokens": len(payload["input"]),
                        "total_tokens": len(payload["input"]),
                    },
                }
                body = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = {
            **self.config,
            "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
        }
        environment = {
            "TRANSLATORAI_EMBEDDING_CONFIG": json.dumps(config),
            "TRANSLATORAI_EMBEDDING_KEY": "synthetic-loopback-key",
            "MOCK_SERVER_PORT": "",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
        try:
            with patch.dict(os.environ, environment):
                vectors, identity = generate_embeddings(
                    ["one", "two"],
                    batch_size=2,
                    provider_data_policy=self.policy,
                )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(vectors, [[1.0, 0.5], [2.0, 0.5]])
        self.assertTrue(identity["endpoint_sha256"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], "/v1/embeddings")
        self.assertEqual(captured[0][1], "Bearer synthetic-loopback-key")
        self.assertEqual(
            captured[0][2],
            {
                "input": ["one", "two"],
                "model": "embed-model-v2",
                "encoding_format": "float",
            },
        )

    def test_embedding_requires_provider_specific_source_authorization(self):
        with patch.dict(
            os.environ,
            {**self.environment, "MOCK_SERVER_PORT": ""},
        ), patch(
            "openai.OpenAI"
        ) as openai_client:
            with self.assertRaises(PermissionError):
                generate_embeddings(
                    ["synthetic source"],
                    provider_data_policy={"another-provider": {"source_text"}},
                )
        openai_client.assert_not_called()

    def test_configured_gemini_uses_dedicated_key_and_selected_model(self):
        config = {
            "provider": "gemini",
            "protocol": "google-genai",
            "model": "custom-embedding-model",
        }
        client = MagicMock()
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.25, 0.75])]
        )
        with patch.dict(
            os.environ,
            {
                "TRANSLATORAI_EMBEDDING_CONFIG": json.dumps(config),
                "TRANSLATORAI_EMBEDDING_KEY": "synthetic-gemini-key",
                "MOCK_SERVER_PORT": "",
            },
        ), patch("google.genai.Client", return_value=client) as genai_client:
            vectors, identity = generate_embeddings(
                ["synthetic source"],
                provider_data_policy={"gemini": {"source_text"}},
            )

        self.assertEqual(vectors, [[0.25, 0.75]])
        self.assertEqual(identity["model"], "custom-embedding-model")
        self.assertEqual(genai_client.call_args.kwargs["api_key"], "synthetic-gemini-key")
        self.assertEqual(
            client.models.embed_content.call_args.kwargs,
            {
                "model": "custom-embedding-model",
                "contents": ["synthetic source"],
            },
        )

    def test_inconsistent_response_count_index_and_dimensions_fail_closed(self):
        scenarios = (
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0])]),
            SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[1.0]),
                    SimpleNamespace(index=0, embedding=[0.0]),
                ]
            ),
            SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[1.0]),
                    SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                ]
            ),
        )
        for response in scenarios:
            with self.subTest(response=response), patch.dict(
                os.environ,
                {**self.environment, "MOCK_SERVER_PORT": ""},
            ), patch("openai.OpenAI") as openai_client:
                openai_client.return_value.embeddings.create.return_value = response
                with self.assertRaises(RuntimeError):
                    generate_embeddings(
                        ["one", "two"],
                        provider_data_policy=self.policy,
                    )

    def test_vector_identity_separates_models_providers_and_endpoints(self):
        vector = [0.1, 0.2]
        identity = embedding_identity_for_vector(vector, self.config)
        other_endpoint = {
            **self.config,
            "base_url": "https://other.example.test/v1",
        }
        other_model = {**self.config, "model": "different-model"}
        other_provider = {**self.config, "provider": "other-provider"}

        self.assertTrue(is_compatible_embedding(vector, identity, self.config))
        self.assertFalse(
            is_compatible_embedding(vector, identity, other_endpoint)
        )
        self.assertFalse(is_compatible_embedding(vector, identity, other_model))
        self.assertFalse(
            is_compatible_embedding(vector, identity, other_provider)
        )
        self.assertFalse(
            is_compatible_embedding(
                vector,
                {
                    "schema_version": 1,
                    "provider": "gemini",
                    "protocol": "google-genai",
                    "model": "gemini-embedding-2",
                    "task_type": "default",
                    "dimensions": 2,
                },
                self.config,
            )
        )

    def test_endpoint_identity_preserves_case_sensitive_path(self):
        vector = [0.1, 0.2]
        base_url = "https://embed.example.test/CaseSensitive/v1"
        first_config = {**self.config, "base_url": base_url}
        second_config = {
            **self.config,
            "base_url": "https://embed.example.test/casesensitive/v1",
        }
        first_identity = embedding_identity_for_vector(vector, first_config)

        self.assertFalse(
            is_compatible_embedding(vector, first_identity, second_config)
        )

    def test_malformed_embedding_configuration_is_rejected(self):
        with patch.dict(
            os.environ,
            {
                **self.environment,
                "TRANSLATORAI_EMBEDDING_CONFIG": "{",
                "MOCK_SERVER_PORT": "",
            },
        ):
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                generate_embeddings(
                    ["synthetic"],
                    provider_data_policy=self.policy,
                )

    def test_openai_compatible_embeddings_do_not_fall_through_to_real_service_in_mock_mode(self):
        with patch.dict(
            os.environ,
            {**self.environment, "MOCK_SERVER_PORT": "12345"},
        ), patch("openai.OpenAI") as openai_client:
            with self.assertRaisesRegex(RuntimeError, "local mock endpoint"):
                generate_embeddings(
                    ["synthetic"],
                    provider_data_policy=self.policy,
                )
        openai_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
