import json
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pipeline as pipeline_module
from openai import APIConnectionError, APIStatusError

from pipeline import (
    ChapterSpec,
    Config,
    ContentBlockedError,
    ResponseContractError,
    TranslationPipeline,
    UnifiedAgent,
    get_api_key,
    get_base_url,
    get_chapter_specs,
    get_openai_client,
    get_primary_provider_route,
    validate_provider_base_url,
    _resolve_project_content_dir,
)
from utils import (
    extract_chapter_num,
    parse_provider_data_policy,
    require_aligned_annotations,
    require_aligned_paragraphs,
    require_provider_data_authorized,
)


def make_api_status_error(status_code):
    response = SimpleNamespace(
        request=object(),
        status_code=status_code,
        headers={},
    )
    return APIStatusError(
        f"simulated HTTP {status_code}",
        response=response,
        body=None,
    )


class TestProviderRouting(unittest.IsolatedAsyncioTestCase):
    async def test_local_http_base_url_is_allowed(self):
        with patch.object(Config, "API_TIMEOUT", 2.0):
            with patch("pipeline.AsyncOpenAI") as client_factory:
                get_openai_client("http://127.0.0.1:6006/v1", None)

        client_kwargs = client_factory.call_args.kwargs
        self.assertEqual(
            {
                "api_key": client_kwargs["api_key"],
                "base_url": client_kwargs["base_url"],
                "timeout": client_kwargs["timeout"],
            },
            {
                "api_key": "local-no-auth",
                "base_url": "http://127.0.0.1:6006/v1",
                "timeout": 2.0,
            },
        )
        self.assertFalse(client_kwargs["http_client"].follow_redirects)
        await client_kwargs["http_client"].aclose()

    def test_remote_http_and_invalid_provider_urls_are_rejected_before_client_creation(self):
        invalid_urls = (
            "http://provider.example/v1",
            "ftp://provider.example/v1",
            "https:///missing-host/v1",
            "https://provider.example:invalid/v1",
            "https://user:secret@provider.example/v1",
            "https://provider.example/v1?token=secret",
            "https://provider.example/v1#fragment",
            "https://provider.example /v1",
        )
        with patch("pipeline.AsyncOpenAI") as client_factory:
            for base_url in invalid_urls:
                with self.subTest(base_url=base_url):
                    with self.assertRaises(ValueError):
                        get_openai_client(base_url, "test-key")

        client_factory.assert_not_called()

    async def test_run_all_rejects_remote_http_endpoint_before_chapter_scan(self):
        translation_pipeline = TranslationPipeline.__new__(TranslationPipeline)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(Config, "SAKURA_BASE_URL", "http://provider.example/v1"):
                with patch("pipeline.get_chapter_specs") as chapter_scan:
                    with self.assertRaisesRegex(
                        ValueError, "Non-loopback provider URLs must use HTTPS"
                    ):
                        await translation_pipeline.run_all()

        chapter_scan.assert_not_called()

    async def test_openai_client_uses_configured_request_timeout_without_following_redirects(self):
        with patch.object(Config, "API_TIMEOUT", 3.5):
            with patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"deepseek": frozenset({"source_text"})},
            ):
                with patch("pipeline.AsyncOpenAI") as client_factory:
                    get_openai_client(
                        "https://provider.example/v1",
                        "test-key",
                        provider_id="deepseek",
                        data_categories={"source_text"},
                    )

        client_kwargs = client_factory.call_args.kwargs
        self.assertEqual(
            {
                "api_key": client_kwargs["api_key"],
                "base_url": client_kwargs["base_url"],
                "timeout": client_kwargs["timeout"],
            },
            {
                "api_key": "test-key",
                "base_url": "https://provider.example/v1",
                "timeout": 3.5,
            },
        )
        self.assertFalse(client_kwargs["http_client"].follow_redirects)
        await client_kwargs["http_client"].aclose()

    def test_openai_client_blocks_ungranted_categories_before_client_creation(self):
        with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
            with patch("pipeline.AsyncOpenAI") as client_factory:
                with self.assertRaisesRegex(PermissionError, "not authorized"):
                    get_openai_client(
                        "https://provider.example/v1",
                        "test-key",
                        provider_id="deepseek",
                        data_categories={"source_text"},
                    )

        client_factory.assert_not_called()

    def test_model_names_resolve_to_their_existing_primary_routes(self):
        with patch.object(Config, "SAKURA_BASE_URL", "http://sakura.test/v1"):
            sakura_route = get_primary_provider_route("QWEN3.6-PLUS")
            sakura_named_route = get_primary_provider_route("sakura")
        with patch.object(Config, "DEEPSEEK_BASE_URL", "https://deepseek.test/v1"):
            deepseek_route = get_primary_provider_route("deepseek-v4-flash")

        self.assertEqual(
            (sakura_route.provider_id, sakura_route.base_url, sakura_route.api_key_env),
            ("sakura", "http://sakura.test/v1", "SAKURA_API_KEY"),
        )
        self.assertEqual(sakura_named_route, sakura_route)
        self.assertEqual(
            (
                deepseek_route.provider_id,
                deepseek_route.base_url,
                deepseek_route.api_key_env,
            ),
            ("deepseek", "https://deepseek.test/v1", "DEEPSEEK_API_KEY"),
        )

    async def test_unknown_model_name_is_rejected_before_client_creation(self):
        agent = UnifiedAgent("gpt-6-luna", "instruction")

        with patch("pipeline.get_openai_client") as client_factory:
            with self.assertRaisesRegex(
                ValueError, "Unsupported model name for primary provider routing"
            ):
                await agent._call_primary("synthetic prompt", "instruction")

        client_factory.assert_not_called()

    async def test_run_all_rejects_unknown_model_before_chapter_scan(self):
        translation_pipeline = TranslationPipeline.__new__(TranslationPipeline)

        with patch.object(Config, "INITIAL_MODEL", "gpt-6-luna"):
            with patch("pipeline.get_chapter_specs") as chapter_scan:
                with self.assertRaisesRegex(
                    ValueError, "Unsupported model name for primary provider routing"
                ):
                    await translation_pipeline.run_all()

        chapter_scan.assert_not_called()

    def test_empty_model_name_is_rejected(self):
        for model_name in ("", "  ", None):
            with self.subTest(model_name=model_name):
                with self.assertRaisesRegex(ValueError, "non-empty model name"):
                    get_primary_provider_route(model_name)

        with self.assertRaisesRegex(ValueError, "leading or trailing whitespace"):
            get_primary_provider_route(" deepseek-v4-flash ")

    @patch.dict(os.environ, {}, clear=True)
    def test_selected_provider_url_is_not_overridden_by_configured_coding_plan_url(self):
        provider_url = "https://api.deepseek.example/v1"
        with patch.object(
            Config, "CODING_PLAN_BASE_URL", "https://coding.example:8443/v1"
        ):
            self.assertEqual(get_base_url(provider_url), provider_url)

    @patch.dict(os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True)
    def test_mock_server_still_overrides_provider_url(self):
        self.assertEqual(
            get_base_url("https://api.deepseek.example/v1"),
            "http://127.0.0.1:12345/v1",
        )

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

    @patch.dict(os.environ, {}, clear=True)
    async def test_run_all_rejects_unapproved_provider_before_reading_chapters(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
            with patch.object(Config, "SAKURA_BASE_URL", "http://127.0.0.1:6006/v1"):
                with patch.object(
                    Config, "DEEPSEEK_BASE_URL", "https://deepseek.example/v1"
                ):
                    with patch.object(Config, "GEMINI_FALLBACK_ENABLED", False):
                        with patch("pipeline.get_chapters") as get_chapters_mock:
                            with self.assertRaisesRegex(
                                PermissionError, "not authorized"
                            ):
                                await pipeline.run_all()

        get_chapters_mock.assert_not_called()

    @patch.dict(os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True)
    async def test_run_all_requires_gemini_grant_even_with_mock_port(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
            with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
                with patch("pipeline.get_chapters") as get_chapters_mock:
                    with self.assertRaisesRegex(PermissionError, "not authorized"):
                        await pipeline.run_all()

        get_chapters_mock.assert_not_called()

    @patch.dict(os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True)
    async def test_run_all_rejects_empty_chapter_list(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        categories = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        policy = {"sakura": categories, "deepseek": categories}
        with patch.object(Config, "PROVIDER_DATA_POLICY", policy):
            with patch.object(Config, "GEMINI_FALLBACK_ENABLED", False):
                with patch(
                    "pipeline.get_chapters", return_value=[]
                ) as get_chapters_mock:
                    with self.assertRaisesRegex(
                        RuntimeError, "No Markdown chapters found"
                    ):
                        await pipeline.run_all()

        get_chapters_mock.assert_called_once_with(Config.RAW_DIR)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_explicit_fallback_setting_allows_gemini_retry(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(
            side_effect=APIConnectionError(request=object())
        )
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
            self.assertEqual(await agent.call("source text"), "fallback")
        agent._call_gemini.assert_awaited_once()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_timeout_rate_limit_and_server_errors_allow_fallback(self):
        for status_code in (408, 429, 500, 599):
            with self.subTest(status_code=status_code):
                agent = UnifiedAgent("deepseek-test", "instruction")
                agent._call_primary = AsyncMock(
                    side_effect=make_api_status_error(status_code)
                )
                agent._call_gemini = AsyncMock(return_value="fallback")

                with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
                    self.assertEqual(await agent.call("source text"), "fallback")
                agent._call_gemini.assert_awaited_once()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_auth_and_request_errors_do_not_trigger_fallback(self):
        for status_code in (400, 401, 403, 404):
            with self.subTest(status_code=status_code):
                agent = UnifiedAgent("deepseek-test", "instruction")
                error = make_api_status_error(status_code)
                agent._call_primary = AsyncMock(side_effect=error)
                agent._call_gemini = AsyncMock(return_value="fallback")

                with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
                    with self.assertRaises(APIStatusError):
                        await agent.call("source text")
                agent._call_gemini.assert_not_awaited()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_response_contract_error_does_not_trigger_fallback(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(
            side_effect=ValueError("Failed to extract JSON from primary response")
        )
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
            with self.assertRaisesRegex(ValueError, "Failed to extract JSON"):
                await agent.call("source text")
        agent._call_gemini.assert_not_awaited()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_content_filter_does_not_trigger_provider_failover(self):
        agent = UnifiedAgent("deepseek-test", "instruction")
        agent._call_primary = AsyncMock(side_effect=ContentBlockedError("blocked"))
        agent._call_gemini = AsyncMock(return_value="fallback")

        with patch.object(Config, "GEMINI_FALLBACK_ENABLED", True):
            with self.assertRaisesRegex(ContentBlockedError, "blocked"):
                await agent.call("source text")
        agent._call_gemini.assert_not_awaited()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    async def test_gemini_call_does_not_disable_provider_safety_settings(self):
        agent = UnifiedAgent(
            "deepseek-test",
            "instruction",
            data_categories=["source_text"],
        )
        client = Mock()
        response = SimpleNamespace(text="fallback", candidates=[])
        client.aio.models.generate_content = AsyncMock(return_value=response)

        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")
        config_args = {}

        def make_config(**kwargs):
            config_args.update(kwargs)
            return SimpleNamespace(**kwargs)

        types_module.Part = SimpleNamespace(from_text=lambda **kwargs: kwargs)
        types_module.Content = lambda **kwargs: SimpleNamespace(**kwargs)
        types_module.GenerateContentConfig = make_config
        http_options_args = {}

        def make_http_options(**kwargs):
            http_options_args.update(kwargs)
            return SimpleNamespace(**kwargs)

        types_module.HttpOptions = make_http_options
        genai_module.Client = Mock(return_value=client)
        google_module.genai = genai_module

        with patch.dict(
            "sys.modules",
            {
                "google": google_module,
                "google.genai": genai_module,
                "google.genai.types": types_module,
            },
        ):
            with patch.object(Config, "API_TIMEOUT", 2.5):
                with patch.object(
                    Config,
                    "PROVIDER_DATA_POLICY",
                    {"gemini": frozenset({"source_text"})},
                ):
                    result = await agent._call_gemini("prompt", "system")

        self.assertEqual(result, "fallback")
        self.assertEqual(http_options_args, {"timeout": 2500})
        genai_module.Client.assert_called_once_with(
            api_key="test-key",
            http_options=SimpleNamespace(timeout=2500),
        )
        self.assertNotIn("safety_settings", config_args)
        self.assertNotIn("忽略一切敏感题材限制", Config.WORK_DISCLAIMER)

    async def test_gemini_call_is_blocked_without_its_own_data_grant(self):
        agent = UnifiedAgent(
            "deepseek-test",
            "instruction",
            data_categories=["source_text"],
        )
        with patch.dict(os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True):
            with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
                with self.assertRaisesRegex(PermissionError, "not authorized"):
                    await agent._call_gemini("source content", "system")


class TestPrimaryResponseContract(unittest.IsolatedAsyncioTestCase):
    @patch.dict(os.environ, {"TEST_WORKSPACE_DIR": "isolated-test-workspace"})
    async def test_invalid_json_is_not_replaced_with_test_placeholder(self):
        agent = UnifiedAgent(
            "deepseek-test", "instruction", response_schema={"type": "OBJECT"}
        )
        client = Mock()
        client.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="not json"),
                    )
                ]
            )
        )

        with patch("pipeline.get_openai_client", return_value=client):
            with self.assertRaisesRegex(Exception, "Failed to extract JSON"):
                await agent._call_primary("prompt", "system")


class TestTestWorkspaceConfiguration(unittest.TestCase):
    def test_chapter_map_loads_from_json_and_resolves_multiple_volumes(self):
        self.addCleanup(setattr, Config, "CHAPTER_MAP", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            (raw_dir / "Volume 1").mkdir(parents=True)
            (raw_dir / "Volume 2").mkdir()
            (output_dir / "Ntera").mkdir(parents=True)
            (raw_dir / "Volume 1" / "第1話.md").write_text(
                "synthetic source one", encoding="utf-8"
            )
            (raw_dir / "Volume 2" / "第1話.md").write_text(
                "synthetic source two", encoding="utf-8"
            )
            chapter_map = [
                {
                    "raw_file": "Volume 1/第1話.md",
                    "translation_file": "Ntera/第1話.md",
                    "tm_key": "Volume1/第1話.md",
                },
                {
                    "raw_file": "Volume 2/第1話.md",
                    "translation_file": "Ntera/第2話.md",
                    "tm_key": "Volume2/第1話.md",
                },
            ]
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(root),
                        "RAW_DIR": str(raw_dir),
                        "OUTPUT_DIR": str(output_dir),
                        "CHAPTER_MAP": chapter_map,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))

            specs = get_chapter_specs(
                Config.RAW_DIR, Config.OUTPUT_DIR, Config.CHAPTER_MAP
            )

        self.assertEqual(
            specs,
            [
                ChapterSpec(
                    "Volume 1/第1話.md",
                    "Ntera/第1話.md",
                    "Volume1/第1話.md",
                ),
                ChapterSpec(
                    "Volume 2/第1話.md",
                    "Ntera/第2話.md",
                    "Volume2/第1話.md",
                ),
            ],
        )

    def test_chapter_map_rejects_duplicate_keys_and_missing_output_parents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "one.md").write_text("synthetic", encoding="utf-8")
            (raw_dir / "two.md").write_text("synthetic", encoding="utf-8")

            duplicate_keys = [
                {
                    "raw_file": "one.md",
                    "translation_file": "one.md",
                    "tm_key": "Volume/Chapter.md",
                },
                {
                    "raw_file": "two.md",
                    "translation_file": "two.md",
                    "tm_key": "volume/chapter.md",
                },
            ]
            with self.assertRaisesRegex(ValueError, "repeats a tm_key"):
                get_chapter_specs(str(raw_dir), str(output_dir), duplicate_keys)

            with self.assertRaisesRegex(ValueError, "trimmed text tm_key"):
                get_chapter_specs(
                    str(raw_dir),
                    str(output_dir),
                    [
                        {
                            "raw_file": "one.md",
                            "translation_file": "one.md",
                            "tm_key": " one ",
                        }
                    ],
                )

            with self.assertRaisesRegex(ValueError, "parent directories"):
                get_chapter_specs(
                    str(raw_dir),
                    str(output_dir),
                    [
                        {
                            "raw_file": "one.md",
                            "translation_file": "new/one.md",
                            "tm_key": "one",
                        }
                    ],
                )

    def test_project_mode_rejects_ambiguous_nested_chapter_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / "repo"
            project_dir = repo_dir / "projects" / "sample"
            (project_dir / "生肉" / "第一卷").mkdir(parents=True)
            (project_dir / "生肉" / "第二卷").mkdir()
            (project_dir / "熟肉" / "EPUB").mkdir(parents=True)
            (project_dir / "熟肉" / "Ntera").mkdir()

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    pipeline_module, "__file__", str(repo_dir / "pipeline.py")
                ):
                    with self.assertRaisesRegex(
                        ValueError, "set both RAW_DIR and OUTPUT_DIR"
                    ):
                        Config.load_config(project="sample")

    def test_project_content_directory_rejects_nested_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            raw_dir = project_dir / "生肉"
            raw_dir.mkdir()
            (raw_dir / "第一卷").mkdir()
            (raw_dir / "第二卷").mkdir()

            with self.assertRaisesRegex(
                ValueError, "set both RAW_DIR and OUTPUT_DIR"
            ):
                _resolve_project_content_dir(
                    str(project_dir), "生肉", "RAW_DIR"
                )

    def test_project_content_directory_keeps_flat_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            raw_dir = project_dir / "生肉"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text("synthetic source", encoding="utf-8")

            self.assertEqual(
                _resolve_project_content_dir(str(project_dir), "生肉", "RAW_DIR"),
                str(raw_dir),
            )

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

    def test_api_timeout_rejects_non_positive_and_non_finite_values(self):
        for value in ("0", "-1", "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"TEST_WORKSPACE_DIR": "isolated-test-workspace", "API_TIMEOUT": value},
                    clear=True,
                ):
                    with self.assertRaisesRegex(ValueError, "API_TIMEOUT"):
                        Config.load_config()

    def test_api_timeout_resets_to_default_when_reloaded_without_override(self):
        with patch.dict(
            os.environ,
            {"TEST_WORKSPACE_DIR": "isolated-test-workspace", "API_TIMEOUT": "3.5"},
            clear=True,
        ):
            Config.load_config()
        self.assertEqual(Config.API_TIMEOUT, 3.5)

        with patch.dict(
            os.environ, {"TEST_WORKSPACE_DIR": "isolated-test-workspace"}, clear=True
        ):
            Config.load_config()
        self.assertEqual(Config.API_TIMEOUT, Config.DEFAULT_API_TIMEOUT)

    def test_api_timeout_uses_json_configuration_when_environment_is_unset(self):
        self.addCleanup(setattr, Config, "API_TIMEOUT", Config.DEFAULT_API_TIMEOUT)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"API_TIMEOUT": 4.25}', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))

        self.assertEqual(Config.API_TIMEOUT, 4.25)

    def test_provider_data_policy_loads_from_environment_and_defaults_to_deny(self):
        self.addCleanup(setattr, Config, "PROVIDER_DATA_POLICY", {})
        with patch.dict(
            os.environ,
            {
                "TEST_WORKSPACE_DIR": "isolated-test-workspace",
                "PROVIDER_DATA_POLICY": '{"deepseek":["source_text"],"gemini":[]}',
            },
            clear=True,
        ):
            Config.load_config()

        self.assertEqual(
            Config.PROVIDER_DATA_POLICY,
            {
                "deepseek": frozenset({"source_text"}),
                "gemini": frozenset(),
            },
        )

    def test_provider_data_policy_uses_json_config_unless_environment_overrides(self):
        self.addCleanup(setattr, Config, "PROVIDER_DATA_POLICY", {})
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {"PROVIDER_DATA_POLICY": {"sakura": ["source_text"]}}
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertEqual(
                Config.PROVIDER_DATA_POLICY,
                {"sakura": frozenset({"source_text"})},
            )

            with patch.dict(
                os.environ,
                {
                    "PROVIDER_DATA_POLICY": '{"deepseek":["source_text"]}',
                },
                clear=True,
            ):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertEqual(
                Config.PROVIDER_DATA_POLICY,
                {"deepseek": frozenset({"source_text"})},
            )

    def test_missing_explicit_config_does_not_fall_back_to_repository_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_config = Path(temp_dir) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                Config.load_config(config_file=str(missing_config))


class TestPromptResponseContract(unittest.TestCase):
    def test_agent_prompt_output_fields_match_pipeline_schemas(self):
        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        expected_outputs = {
            "translator_skill.md": ('"translated_paragraphs"', '"raw_translation"'),
            "proofreader_skill.md": ('"corrected_text"', '"logic_fixed_text"'),
            "polisher_skill.md": (
                '"polished_paragraphs"',
                "不使用任何 JSON 或 Markdown",
            ),
        }
        for filename, (required_output, incompatible_format) in expected_outputs.items():
            with self.subTest(prompt=filename):
                prompt = (prompt_dir / filename).read_text(encoding="utf-8")
                self.assertIn(required_output, prompt)
                self.assertNotIn(incompatible_format, prompt)


class TestProviderDataPolicy(unittest.TestCase):
    def test_policy_requires_all_external_data_categories(self):
        policy = parse_provider_data_policy(
            {"deepseek": ["source_text"], "gemini": []}
        )
        require_provider_data_authorized(
            "deepseek", {"source_text"}, policy
        )

        with self.assertRaisesRegex(PermissionError, "translation_text"):
            require_provider_data_authorized(
                "deepseek",
                {"source_text", "translation_text"},
                policy,
            )
        with self.assertRaisesRegex(PermissionError, "not authorized"):
            require_provider_data_authorized("gemini", {"source_text"}, policy)

    def test_policy_rejects_unknown_categories_and_local_calls_need_no_grant(self):
        with self.assertRaisesRegex(ValueError, "unknown categories"):
            parse_provider_data_policy({"deepseek": ["raw_text"]})

        with self.assertRaisesRegex(ValueError, "must be text"):
            require_provider_data_authorized(
                "deepseek",
                ["source_text", []],
                {},
            )

        require_provider_data_authorized(
            None,
            None,
            {},
            endpoint_is_local=True,
        )


class TestParagraphContracts(unittest.IsolatedAsyncioTestCase):
    async def test_mapped_chapter_writes_nested_output_and_uses_tm_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            (raw_dir / "Volume 2").mkdir(parents=True)
            (output_dir / "Ntera").mkdir(parents=True)
            (raw_dir / "Volume 2" / "chapter10.md").write_text(
                "synthetic source", encoding="utf-8"
            )
            spec = ChapterSpec(
                "Volume 2/chapter10.md",
                "Ntera/chapter10.md",
                "Volume2/chapter10.md",
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={"chapters": {}},
                update_translation_memory=Mock(),
            )
            pipeline._build_run_context = AsyncMock(
                return_value={"static_context": "", "glossary_matches": []}
            )
            pipeline._run_context_annotation = AsyncMock(return_value=[])
            pipeline._run_translation_phase = AsyncMock(
                return_value=["synthetic translation"]
            )
            pipeline._run_refinement_loop = AsyncMock(
                return_value=["synthetic translation"]
            )

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    await pipeline.run_chapter(spec)

            output_path = output_dir / "Ntera" / "chapter10.md"
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "synthetic translation",
            )
            self.assertEqual(
                pipeline._build_run_context.await_args.args,
                ("Volume 2/chapter10.md", "synthetic source", 10.0),
            )
            pipeline.rag.update_translation_memory.assert_called_once()
            self.assertEqual(
                pipeline.rag.update_translation_memory.call_args.args[0],
                "Volume2/chapter10.md",
            )
            provenance = pipeline.rag.update_translation_memory.call_args.kwargs[
                "source_provenance"
            ]
            self.assertEqual(provenance["raw_file"], "Volume 2/chapter10.md")
            self.assertEqual(provenance["translation_file"], "Ntera/chapter10.md")

    async def test_run_chapter_rejects_embedded_paragraph_break_before_persisting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"
            output_dir = Path(temp_dir) / "translated"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text(
                "synthetic source", encoding="utf-8"
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={"chapters": {}},
                update_translation_memory=Mock(),
            )
            pipeline._build_run_context = AsyncMock(
                return_value={"static_context": "", "glossary_matches": []}
            )
            pipeline._run_context_annotation = AsyncMock(return_value=[])
            pipeline._run_translation_phase = AsyncMock(return_value=["valid"])
            pipeline._run_refinement_loop = AsyncMock(
                return_value=["first paragraph\n\nextra paragraph"]
            )

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    with self.assertRaisesRegex(
                        ValueError, "multiple paragraphs at index 1"
                    ):
                        await pipeline.run_chapter("第1話.md")

            self.assertFalse((output_dir / "第1話.md").exists())
            pipeline.rag.update_translation_memory.assert_not_called()

    def test_aligned_paragraphs_trim_boundary_whitespace_and_reject_blank_lines(self):
        target = ["  translated text  "]
        require_aligned_paragraphs(["source"], target, "Test")
        self.assertEqual(target, ["translated text"])

        with self.assertRaisesRegex(ValueError, "multiple paragraphs at index 1"):
            require_aligned_paragraphs(
                ["source"], ["first\n\nsecond"], "Test"
            )

    def test_chapter_number_uses_filename_not_parent_directory(self):
        self.assertEqual(extract_chapter_num("Volume 2/chapter10.md"), 10.0)
        self.assertEqual(extract_chapter_num(r"Volume 2\chapter10.md"), 10.0)

    async def test_tm_persistence_failure_leaves_output_and_warns_on_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={"chapters": {}},
                update_translation_memory=Mock(side_effect=OSError("disk full")),
            )
            pipeline._build_run_context = AsyncMock(
                return_value={"static_context": "", "glossary_matches": []}
            )
            pipeline._run_context_annotation = AsyncMock(return_value=[])
            pipeline._run_translation_phase = AsyncMock(
                return_value=["translated paragraph"]
            )
            pipeline._run_refinement_loop = AsyncMock(
                return_value=["translated paragraph"]
            )

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        await pipeline.run_chapter("第1話.md")

                    output_path = output_dir / "第1話.md"
                    self.assertEqual(
                        output_path.read_text(encoding="utf-8"),
                        "translated paragraph",
                    )

                    with patch("pipeline.logger.warning") as warning:
                        await pipeline.run_chapter("第1話.md")

            pipeline.rag.update_translation_memory.assert_called_once()
            warning.assert_called_once()
            self.assertIn("has no translation-memory entry", warning.call_args.args[0])
            self.assertIn("Check source/output alignment", warning.call_args.args[0])

    async def test_empty_existing_output_does_not_warn_about_missing_tm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "熟肉"
            output_dir.mkdir()
            (output_dir / "第1話.md").write_text("", encoding="utf-8")
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(tm_data={"chapters": {}})

            with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                with patch("pipeline.logger.warning") as warning:
                    await pipeline.run_chapter("第1話.md")

            warning.assert_not_called()

    async def test_annotation_phase_preserves_valid_structured_records(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        annotation = {
            "paragraph": "source paragraph",
            "speaker": "旁白",
            "context_hint": "",
        }
        agent = Mock()
        agent.call = AsyncMock(return_value={"annotated_paragraphs": [annotation]})

        with patch("pipeline.UnifiedAgent", return_value=agent):
            result = await pipeline._run_context_annotation("source paragraph", "")

        self.assertEqual(result, [annotation])
        annotation_prompt = agent.call.await_args.args[0]
        self.assertIn('"annotated_paragraphs"', annotation_prompt)
        self.assertIn('"context_hint"', annotation_prompt)
        self.assertIn("paragraph 必须逐字保留对应源段落", annotation_prompt)

    async def test_annotation_phase_falls_back_for_malformed_records(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        agent = Mock()
        agent.call = AsyncMock(
            return_value={
                "annotated_paragraphs": [
                    {"paragraph": "source paragraph", "speaker": "旁白"}
                ]
            }
        )

        with patch("pipeline.UnifiedAgent", return_value=agent):
            result = await pipeline._run_context_annotation("source paragraph", "")

        self.assertEqual(
            result,
            [{"paragraph": "source paragraph", "speaker": "unknown", "context_hint": ""}],
        )

    def test_annotation_contract_rejects_wrong_item_types_and_changed_source(self):
        source = ["source paragraph"]
        with self.subTest("wrong item type"):
            with self.assertRaisesRegex(ValueError, "non-object annotation"):
                require_aligned_annotations(source, ["not an annotation"], "Annotation")
        with self.subTest("changed source"):
            with self.assertRaisesRegex(ValueError, "changed source paragraph"):
                require_aligned_annotations(
                    source,
                    [{"paragraph": "changed", "speaker": "旁白", "context_hint": ""}],
                    "Annotation",
                )

    async def test_translation_phase_rejects_missing_required_field(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(return_value={"unexpected": ["translation"]})

        with patch("pipeline.UnifiedAgent", return_value=fake_agent):
            with self.assertRaisesRegex(ValueError, "must contain a 'translated_paragraphs' array"):
                await pipeline._run_translation_phase("one", "", [])

    async def test_translation_phase_rejects_mismatched_paragraph_count(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(return_value={"translated_paragraphs": ["one result"]})

        with patch("pipeline.UnifiedAgent", return_value=fake_agent):
            with self.assertRaisesRegex(ValueError, "Translation returned 1 paragraphs for 2"):
                await pipeline._run_translation_phase("one\n\ntwo", "", [])

    async def test_translation_phase_rejects_empty_paragraphs(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(
            return_value={"translated_paragraphs": ["   "]}
        )

        with patch("pipeline.UnifiedAgent", return_value=fake_agent):
            with self.assertRaisesRegex(ValueError, "empty or non-text paragraph"):
                await pipeline._run_translation_phase("one", "", [])

    async def test_translation_phase_rejects_non_text_array_items(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(
            return_value={"translated_paragraphs": ["valid", 7]}
        )

        with patch("pipeline.UnifiedAgent", return_value=fake_agent):
            with self.assertRaisesRegex(ValueError, "empty or non-text paragraph"):
                await pipeline._run_translation_phase("one\n\ntwo", "", [])

    def test_quote_mismatch_counts_each_mark_type(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)

        self.assertEqual(
            pipeline._check_quote_mismatch("「a」『b』", "「a」『b』"), 0
        )
        self.assertEqual(pipeline._check_quote_mismatch("「a」", "」a「"), 1)
        self.assertEqual(pipeline._check_quote_mismatch("「a」", "a"), 2)

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

    async def test_proofreader_missing_required_field_keeps_previous_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={"severity": "none", "corrected_text": ["changed"]}
        )
        polisher = Mock()
        polisher.call = AsyncMock(return_value={"polished_paragraphs": ["polished"]})

        with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
            result = await pipeline._run_refinement_loop(
                "source", ["original translation"], "", []
            )

        self.assertEqual(result, ["polished"])

    async def test_proofreader_invalid_schema_types_keep_previous_translation(self):
        invalid_responses = [
            ("unhashable severity", {
                "severity": ["severe"],
                "critique": "",
                "corrected_text": ["untrusted replacement"],
            }),
            ("non-text critique", {
                "severity": "none",
                "critique": None,
                "corrected_text": ["untrusted replacement"],
            }),
            ("non-array corrected text", {
                "severity": "none",
                "critique": "",
                "corrected_text": "untrusted replacement",
            }),
            ("non-text corrected item", {
                "severity": "none",
                "critique": "",
                "corrected_text": [None],
            }),
        ]
        for label, response in invalid_responses:
            with self.subTest(label=label):
                pipeline = TranslationPipeline.__new__(TranslationPipeline)
                pipeline._get_agent_instruction = Mock(return_value="")
                proofreader = Mock()
                proofreader.call = AsyncMock(return_value=response)
                polisher = Mock()
                polisher.call = AsyncMock(
                    return_value={"polished_paragraphs": ["polished result"]}
                )

                with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
                    result = await pipeline._run_refinement_loop(
                        "source",
                        ["original translation"],
                        "",
                        [],
                    )

                self.assertEqual(result, ["polished result"])
                polish_prompt = polisher.call.await_args.args[0]
                self.assertIn("original translation", polish_prompt)
                self.assertNotIn("untrusted replacement", polish_prompt)

    async def test_invalid_reflection_response_keeps_proofread_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "severe",
                "critique": "SYNTHETIC_PRIVATE_CRITIQUE",
                "corrected_text": ["proofread translation"],
            }
        )
        reflection_translator = Mock()
        reflection_translator.call = AsyncMock(return_value={"unexpected": ["retry"]})
        polisher = Mock()
        polisher.call = AsyncMock(return_value={"polished_paragraphs": ["polished"]})

        with patch.object(Config, "STRICT_REFLECTION_MODE", True):
            with patch(
                "pipeline.UnifiedAgent",
                side_effect=[proofreader, reflection_translator, polisher],
            ):
                with patch("builtins.print") as printed:
                    result = await pipeline._run_refinement_loop(
                        "source", ["initial translation"], "", []
                    )

        self.assertEqual(result, ["polished"])
        printed_output = " ".join(str(call.args) for call in printed.call_args_list)
        self.assertNotIn("SYNTHETIC_PRIVATE_CRITIQUE", printed_output)
        polish_prompt = polisher.call.await_args.args[0]
        self.assertIn("proofread translation", polish_prompt)
        self.assertNotIn("retry", polish_prompt)

    async def test_reflection_parse_error_keeps_proofread_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "severe",
                "critique": "synthetic critique",
                "corrected_text": ["proofread translation"],
            }
        )
        reflection_translator = Mock()
        reflection_translator.call = AsyncMock(
            side_effect=ResponseContractError("malformed response")
        )
        polisher = Mock()
        polisher.call = AsyncMock(
            return_value={"polished_paragraphs": ["polished translation"]}
        )

        with patch.object(Config, "STRICT_REFLECTION_MODE", True):
            with patch(
                "pipeline.UnifiedAgent",
                side_effect=[proofreader, reflection_translator, polisher],
            ):
                result = await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(result, ["polished translation"])
        polish_prompt = polisher.call.await_args.args[0]
        self.assertIn("proofread translation", polish_prompt)
        self.assertNotIn("initial translation", polish_prompt)

    async def test_polisher_parse_error_returns_proofread_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "minor",
                "critique": "",
                "corrected_text": ["proofread translation"],
            }
        )
        polisher = Mock()
        polisher.call = AsyncMock(
            side_effect=ResponseContractError("malformed response")
        )

        with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
            result = await pipeline._run_refinement_loop(
                "source", ["initial translation"], "", []
            )

        self.assertEqual(result, ["proofread translation"])

    async def test_polisher_authorization_error_is_not_swallowed(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "minor",
                "critique": "",
                "corrected_text": ["proofread translation"],
            }
        )
        polisher = Mock()
        polisher.call = AsyncMock(side_effect=make_api_status_error(401))

        with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
            with self.assertRaises(APIStatusError):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

    async def test_invalid_polish_response_returns_proofread_translation(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "minor",
                "critique": "small adjustment",
                "corrected_text": ["proofread translation"],
            }
        )
        polisher = Mock()
        polisher.call = AsyncMock(
            return_value={"polished_paragraphs": [{"paragraph": "wrong item type"}]}
        )

        with patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]):
            result = await pipeline._run_refinement_loop(
                "source", ["initial translation"], "", []
            )

        self.assertEqual(result, ["proofread translation"])


if __name__ == "__main__":
    unittest.main()
