import os
import sys
import types

import aiohttp


class MockPart:
    @staticmethod
    def from_text(text):
        return types.SimpleNamespace(text=text)


class MockContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


class MockGenerateContentConfig:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class MockModels:
    def __init__(self, port):
        self.port = port

    async def generate_content(self, model, contents, config):
        serializable_contents = [
            {
                "role": content.role,
                "parts": [{"text": part.text} for part in content.parts],
            }
            for content in contents
        ]
        response_schema = getattr(config, "response_schema", None)
        payload = {
            "model": model,
            "contents": serializable_contents,
            "config": {"response_schema": response_schema} if response_schema else {},
        }
        timeout = aiohttp.ClientTimeout(
            total=float(os.environ.get("API_TIMEOUT", 10.0))
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"http://127.0.0.1:{self.port}/gemini/generateContent",
                json=payload,
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Mock Gemini API returned {response.status}.")
                data = await response.json()

        class ResponsePart:
            def __init__(self, value):
                self.text = value.get("text", "")

        class ResponseContent:
            def __init__(self, value):
                self.role = value.get("role", "model")
                self.parts = [ResponsePart(item) for item in value.get("parts", [])]

        class ResponseCandidate:
            def __init__(self, value):
                self.finish_reason = value.get("finish_reason", "STOP")
                self.content = ResponseContent(value.get("content", {}))

        class Response:
            def __init__(self, value):
                self.candidates = [
                    ResponseCandidate(item) for item in value.get("candidates", [])
                ]

            @property
            def text(self):
                if self.candidates and self.candidates[0].content.parts:
                    return self.candidates[0].content.parts[0].text
                return ""

        return Response(data)


class MockGenAIClient:
    def __init__(self, api_key=None, http_options=None):
        port = int(os.environ["MOCK_SERVER_PORT"])
        self.aio = types.SimpleNamespace(models=MockModels(port))
        self.models = MockModels(port)


def install_mock_genai():
    genai_module = types.ModuleType("google.genai")
    genai_module.Client = MockGenAIClient

    types_module = types.ModuleType("google.genai.types")
    types_module.Part = MockPart
    types_module.Content = MockContent
    types_module.GenerateContentConfig = MockGenerateContentConfig

    google_module = types.ModuleType("google")
    google_module.genai = genai_module
    sys.modules["google"] = google_module
    sys.modules["google.genai"] = genai_module
    sys.modules["google.genai.types"] = types_module
