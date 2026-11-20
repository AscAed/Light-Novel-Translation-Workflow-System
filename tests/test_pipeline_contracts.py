import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pipeline as pipeline_module
from api_pool import FALLBACK_ENV
from openai import APIConnectionError, APIStatusError

from chapter_transaction import commit_chapter_translation
from pipeline import (
    ChapterSpec,
    Config,
    ContentBlockedError,
    ResponseContractError,
    TranslationQualityGateError,
    TranslationPipeline,
    UnifiedAgent,
    get_api_key,
    get_base_url,
    get_chapter_specs,
    get_openai_client,
    get_primary_provider_route,
    validate_provider_configuration,
    validate_final_review_provider_configuration,
    validate_translation_rework_provider_configuration,
    validate_provider_base_url,
    _read_chapter_source_text,
    _reject_unreviewed_project_publication,
    _resolve_project_content_dir,
    _resolve_project_human_edition_root,
)
from source_manifest import append_artifact
from utils import (
    extract_chapter_num,
    parse_provider_data_policy,
    require_aligned_annotations,
    require_aligned_paragraphs,
    require_provider_data_authorized,
    split_paragraphs,
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
    def test_translation_rework_requires_a_distinct_reviewer_route(self):
        with (
            patch("pipeline.validate_provider_configuration") as preflight,
            patch(
                "pipeline._resolve_provider_route_identity",
                side_effect=[
                    (None, None, ("https", "writer.example", 443, "/v1", "writer")),
                    (None, None, ("https", "reviewer.example", 443, "/v1", "reviewer")),
                ],
            ),
            patch.object(Config, "PROOFREAD_MODEL", "pool:writer"),
            patch.object(Config, "FINAL_REVIEW_MODEL", "pool:reviewer"),
        ):
            validate_translation_rework_provider_configuration()

        preflight.assert_called_once_with()

    def test_translation_rework_rejects_reviewer_route_reuse(self):
        cases = (
            (
                ("https", "shared.example", 443, "/v1", "writer"),
                ("https", "shared.example", 443, "/v1", "reviewer"),
            ),
            (
                ("https", "writer.example", 443, "/v1", "shared-model"),
                ("https", "reviewer.example", 443, "/v1", "shared-model"),
            ),
            (
                ("https", "shared.example", 443, "/v1", "same-model"),
                ("https", "shared.example", 443, "/v1", "same-model"),
            ),
        )
        for rework_identity, reviewer_identity in cases:
            with self.subTest(
                rework_identity=rework_identity,
                reviewer_identity=reviewer_identity,
            ):
                with (
                    patch("pipeline.validate_provider_configuration"),
                    patch(
                        "pipeline._resolve_provider_route_identity",
                        side_effect=[
                            (None, None, rework_identity),
                            (None, None, reviewer_identity),
                        ],
                    ),
                    patch.object(Config, "PROOFREAD_MODEL", "pool:writer"),
                    patch.object(Config, "FINAL_REVIEW_MODEL", "pool:reviewer"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "different endpoint and model",
                    ):
                        validate_translation_rework_provider_configuration()

    def test_final_review_rejects_shared_endpoint_or_model(self):
        cases = (
            (
                ("https", "shared.example", 443, "/v1", "translator"),
                ("https", "shared.example", 443, "/v1", "reviewer"),
            ),
            (
                ("https", "translator.example", 443, "/v1", "shared-model"),
                ("https", "reviewer.example", 443, "/v1", "shared-model"),
            ),
        )
        for translator_identity, reviewer_identity in cases:
            with self.subTest(
                translator_identity=translator_identity,
                reviewer_identity=reviewer_identity,
            ):
                with (
                    patch(
                        "pipeline._resolve_provider_route_identity",
                        side_effect=[
                            (None, None, reviewer_identity),
                            (None, None, translator_identity),
                        ],
                    ),
                    patch.object(Config, "FINAL_REVIEW_MODEL", "pool:reviewer"),
                    patch.object(Config, "INITIAL_MODEL", "pool:translator"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "different endpoint and model",
                    ):
                        validate_final_review_provider_configuration()

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
        self.assertNotIn("max_retries", client_kwargs)
        await client_kwargs["http_client"].aclose()

    async def test_openai_client_can_disable_sdk_retries(self):
        with patch("pipeline.AsyncOpenAI") as client_factory:
            get_openai_client(
                "http://127.0.0.1:6006/v1",
                None,
                max_retries=0,
            )

        client_kwargs = client_factory.call_args.kwargs
        self.assertEqual(client_kwargs["max_retries"], 0)
        await client_kwargs["http_client"].aclose()

    def test_pipeline_rejects_draft_summary_before_loading_knowledge(self):
        with (
            patch.object(Config, "WORKSPACE_DIR", "configured"),
            patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
            patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
            patch.object(
                Config,
                "STORY_SUMMARY_PATH",
                "Knowledge/STORY_SUMMARY_draft.md",
            ),
            patch("pipeline.load_json") as load_json,
            patch("pipeline.RAGEngine") as rag_engine,
        ):
            with self.assertRaisesRegex(ValueError, "candidate draft"):
                TranslationPipeline()

        load_json.assert_not_called()
        rag_engine.assert_not_called()

    def test_pipeline_loads_reviewed_summary_before_other_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "STORY_SUMMARY_reviewed.json"
            reviewed_tm_path = Path(temporary) / "translation_memory_reviewed.json"
            output_dir = Path(temporary) / "translated"
            reviewed_tm_translation_root = Path(temporary) / "published"
            summary_path.write_text("{}", encoding="utf-8")
            events = []
            rag_kwargs = {}

            def load_summary(*args):
                events.append("summary")
                return "Approved synthetic summary."

            def load_info(*args):
                events.append("info")
                return {}

            def build_rag(*args, **kwargs):
                events.append("rag")
                rag_kwargs.update(kwargs)
                return Mock()

            with (
                patch.object(Config, "WORKSPACE_DIR", "configured"),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
                patch.object(Config, "STORY_SUMMARY_PATH", str(summary_path)),
                patch.object(Config, "RAW_DIR", "raw"),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"),
                patch.object(Config, "INFO_PATH", "Info.json"),
                patch.object(Config, "TM_PATH", "TM.json"),
                patch.object(Config, "TM_REVIEWED_PATH", str(reviewed_tm_path)),
                patch.object(Config, "ALLOW_UNREVIEWED_TM", True),
                patch(
                    "pipeline.load_reviewed_story_summary",
                    side_effect=load_summary,
                ) as load_summary_mock,
                patch("pipeline.load_json", side_effect=load_info),
                patch("pipeline.RAGEngine", side_effect=build_rag),
            ):
                translation_pipeline = TranslationPipeline(
                    reviewed_tm_translation_root=str(
                        reviewed_tm_translation_root
                    )
                )

        self.assertEqual(
            translation_pipeline.story_summary,
            "Approved synthetic summary.",
        )
        self.assertEqual(events, ["summary", "info", "rag"])
        load_summary_mock.assert_called_once_with(
            str(summary_path),
            "raw",
            "source_manifest.json",
        )
        self.assertEqual(rag_kwargs["reviewed_tm_path"], str(reviewed_tm_path))
        self.assertEqual(rag_kwargs["translation_root"], str(output_dir))
        self.assertEqual(
            rag_kwargs["reviewed_tm_translation_root"],
            str(reviewed_tm_translation_root),
        )
        self.assertTrue(rag_kwargs["allow_unreviewed_tm"])

    def test_pipeline_rejects_invalid_reviewed_summary_before_loading_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "STORY_SUMMARY_reviewed.json"
            summary_path.write_text("{}", encoding="utf-8")
            with (
                patch.object(Config, "WORKSPACE_DIR", "configured"),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
                patch.object(Config, "STORY_SUMMARY_PATH", str(summary_path)),
                patch.object(Config, "RAW_DIR", "raw"),
                patch.object(Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"),
                patch(
                    "pipeline.load_reviewed_story_summary",
                    side_effect=ValueError("not approved"),
                ),
                patch("pipeline.load_json") as load_json,
                patch("pipeline.RAGEngine") as rag_engine,
            ):
                with self.assertRaisesRegex(ValueError, "not approved"):
                    TranslationPipeline()

        load_json.assert_not_called()
        rag_engine.assert_not_called()

    def test_optional_ai_summary_load_uses_current_ai_input_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "STORY_SUMMARY_reviewed.json"
            summary_path.write_text("{}", encoding="utf-8")
            chapter_map = [
                {
                    "raw_file": "editions/ai/episode-1.md",
                    "translation_file": "episode-0001-101.md",
                    "tm_key": "source-edition:work-1:101",
                    "source_version_id": "ai-version-1",
                    "source_input_file": "chapters/episode-1.md",
                    "source_sha256": "a" * 64,
                }
            ]
            with (
                patch.object(Config, "WORKSPACE_DIR", "configured"),
                patch.object(
                    Config,
                    "TRANSLATION_OUTPUT_MODE",
                    "compatibility_draft",
                ),
                patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
                patch.object(Config, "STORY_SUMMARY_PATH", str(summary_path)),
                patch.object(Config, "RAW_DIR", "SourceArchive"),
                patch.object(
                    Config,
                    "SOURCE_MANIFEST_PATH",
                    "source_editions_manifest.json",
                ),
                patch.object(Config, "AI_EDITION_ROOT", "RAWs_AI"),
                patch.object(Config, "CHAPTER_MAP", chapter_map),
                patch(
                    "pipeline.load_reviewed_story_summary",
                    return_value="Approved synthetic summary.",
                ) as load_summary,
                patch("pipeline.load_json", return_value={}),
                patch("pipeline.RAGEngine", return_value=Mock()),
            ):
                TranslationPipeline()

        load_summary.assert_called_once_with(
            str(summary_path),
            "SourceArchive",
            "source_editions_manifest.json",
            source_input_root="RAWs_AI",
            source_input_map={
                "editions/ai/episode-1.md": {
                    "source_version_id": "ai-version-1",
                    "source_input_file": "chapters/episode-1.md",
                    "source_sha256": "a" * 64,
                }
            },
        )

    def test_project_pipeline_requires_reviewed_full_book_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "STORY_SUMMARY_reviewed.json"
            with (
                patch.object(Config, "WORKSPACE_DIR", "configured"),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
                patch.object(Config, "STORY_SUMMARY_PATH", str(summary_path)),
                patch.object(Config, "REQUIRE_REVIEWED_STORY_SUMMARY", True),
                patch.object(Config, "RAW_DIR", "raw"),
                patch.object(Config, "SOURCE_MANIFEST_PATH", "source_editions_manifest.json"),
                patch("pipeline.load_json") as load_json,
                patch("pipeline.RAGEngine") as rag_engine,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "requires an approved full-book story summary",
                ):
                    TranslationPipeline()

        load_json.assert_not_called()
        rag_engine.assert_not_called()

    def test_project_pipeline_binds_reviewed_summary_to_current_ai_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "STORY_SUMMARY_reviewed.json"
            summary_path.write_text("{}", encoding="utf-8")
            source_sha256 = hashlib.sha256(b"AI edition text").hexdigest()
            chapter = ChapterSpec(
                raw_file="editions/ai/episode-1.md",
                translation_file="episode-0001-101.md",
                tm_key="source-edition:work-1:101",
                source_version_id="ai-version-1",
                chapter_position=1,
                source_input_file="episodes/episode-1.md",
                source_sha256=source_sha256,
            )
            expected_bundle = {
                "source_snapshot_id": "source-v1-" + "a" * 64,
                "ai_bundle_id": "ai-v1-" + "b" * 64,
                "bundle_set_relative_path": "collections/set.json",
                "bundle_set_sha256": "c" * 64,
                "ai_bundle_relative_path": "collections/ai/book.json",
                "ai_bundle_sha256": "d" * 64,
                "episode_count": 1,
            }
            with (
                patch.object(Config, "WORKSPACE_DIR", "configured"),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "GLOSSARY_PATH", "Knowledge/Glossary.json"),
                patch.object(Config, "STORY_SUMMARY_PATH", str(summary_path)),
                patch.object(Config, "REQUIRE_REVIEWED_STORY_SUMMARY", True),
                patch.object(Config, "EXPECTED_BOOK_BUNDLE", expected_bundle),
                patch.object(Config, "RAW_DIR", "SourceArchive"),
                patch.object(Config, "OUTPUT_DIR", "external-translation-root"),
                patch.object(
                    Config,
                    "SOURCE_MANIFEST_PATH",
                    "source_editions_manifest.json",
                ),
                patch.object(Config, "AI_EDITION_ROOT", "RAWs_AI"),
                patch.object(
                    Config,
                    "CHAPTER_MAP",
                    [
                        {
                            "raw_file": chapter.raw_file,
                            "source_version_id": chapter.source_version_id,
                            "source_input_file": chapter.source_input_file,
                            "source_sha256": source_sha256,
                        }
                    ],
                ),
                patch.object(Config, "INFO_PATH", "Knowledge/作品基本信息.json"),
                patch.object(Config, "TM_PATH", "Knowledge/translation_memory.json"),
                patch("pipeline.get_chapter_specs", return_value=[chapter]),
                patch(
                    "pipeline.load_reviewed_story_summary",
                    return_value="Approved synthetic summary.",
                ) as load_summary,
                patch("pipeline.load_json", return_value={}),
                patch("pipeline.RAGEngine", return_value=Mock()),
            ):
                translation_pipeline = TranslationPipeline()

        self.assertEqual(
            translation_pipeline.story_summary,
            "Approved synthetic summary.",
        )
        load_summary.assert_called_once_with(
            str(summary_path),
            "SourceArchive",
            "source_editions_manifest.json",
            require_full_book_coverage=True,
            require_book_bundle=True,
            expected_book_bundle=expected_bundle,
            expected_sources=[
                {
                    "filename": "editions/ai/episode-1.md",
                    "source_version_id": "ai-version-1",
                    "source_input_file": "episodes/episode-1.md",
                    "source_sha256": source_sha256,
                }
            ],
            source_input_root="RAWs_AI",
            source_input_map={
                "editions/ai/episode-1.md": {
                    "source_version_id": "ai-version-1",
                    "source_input_file": "episodes/episode-1.md",
                    "source_sha256": source_sha256,
                }
            },
        )

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
        with (
            patch.object(Config, "JOJO_BASE_URL", "https://jojo.test/v1"),
            patch.object(Config, "JYQF_BASE_URL", "https://jyqf.test/v1"),
        ):
            jojo_route = get_primary_provider_route("gpt-6-Luna")
            jyqf_route = get_primary_provider_route("deepseek-v4.1-flash")
        deepseek_flash_route = get_primary_provider_route("deepseek-flash")

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
        self.assertEqual(
            (jojo_route.provider_id, jojo_route.base_url, jojo_route.api_key_env),
            ("jojo", "https://jojo.test/v1", "JOJO_API_KEY"),
        )
        self.assertEqual(
            (jyqf_route.provider_id, jyqf_route.base_url, jyqf_route.api_key_env),
            ("jyqf", "https://jyqf.test/v1", "JYQF_API_KEY"),
        )
        self.assertEqual(
            (
                deepseek_flash_route.provider_id,
                deepseek_flash_route.api_key_env,
            ),
            ("deepseek", "DEEPSEEK_API_KEY"),
        )

    async def test_unknown_model_name_is_rejected_before_client_creation(self):
        agent = UnifiedAgent("unsupported-model", "instruction")

        with patch("pipeline.get_openai_client") as client_factory:
            with self.assertRaisesRegex(
                ValueError, "Unsupported model name for primary provider routing"
            ):
                await agent._call_primary("synthetic prompt", "instruction")

        client_factory.assert_not_called()

    async def test_run_all_rejects_unknown_model_before_chapter_scan(self):
        translation_pipeline = TranslationPipeline.__new__(TranslationPipeline)

        with patch.object(Config, "INITIAL_MODEL", "unsupported-model"):
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

    async def test_run_all_uses_minimum_stage_categories_for_preflight(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        source_and_knowledge = frozenset({"source_text", "book_knowledge"})
        full_translation = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        policy = {
            "jojo": source_and_knowledge,
            "jyqf": full_translation,
            "deepseek": full_translation,
        }
        with (
            patch.object(Config, "INITIAL_MODEL", "gpt-6-luna"),
            patch.object(Config, "PROOFREAD_MODEL", "deepseek-v4.1-flash"),
            patch.object(Config, "STYLE_MODEL", "deepseek-v4-flash"),
            patch.object(Config, "PROVIDER_DATA_POLICY", policy),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", False),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch("pipeline.get_api_key", return_value="synthetic-key"),
            patch("pipeline.get_chapter_specs", return_value=[]) as chapter_scan,
        ):
            with self.assertRaisesRegex(RuntimeError, "No Markdown chapters found"):
                await pipeline.run_all()

        chapter_scan.assert_called_once()

    async def test_reflection_preflight_requires_translation_category(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        policy = {
            "jojo": frozenset({"source_text", "book_knowledge"}),
            "jyqf": frozenset(
                {"source_text", "translation_text", "book_knowledge"}
            ),
            "deepseek": frozenset(
                {"source_text", "translation_text", "book_knowledge"}
            ),
        }
        with (
            patch.object(Config, "INITIAL_MODEL", "gpt-6-luna"),
            patch.object(Config, "PROOFREAD_MODEL", "deepseek-v4.1-flash"),
            patch.object(Config, "STYLE_MODEL", "deepseek-v4-flash"),
            patch.object(Config, "STRICT_REFLECTION_MODE", True),
            patch.object(Config, "PROVIDER_DATA_POLICY", policy),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", False),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch("pipeline.get_api_key", return_value="synthetic-key"),
            patch("pipeline.get_chapter_specs") as chapter_scan,
        ):
            with self.assertRaisesRegex(
                PermissionError, "translation_text"
            ):
                await pipeline.run_all()

        chapter_scan.assert_not_called()

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

    @patch.dict(os.environ, {"JYQF_API_KEY": "test-key"}, clear=True)
    async def test_jojo_primary_uses_jyqf_for_retryable_provider_errors(self):
        errors = [
            APIConnectionError(request=object()),
            *(make_api_status_error(code) for code in (408, 429, 500, 599)),
        ]
        categories = frozenset({"source_text", "book_knowledge"})
        for error in errors:
            with self.subTest(error=type(error).__name__):
                agent = UnifiedAgent(
                    "gpt-6-luna",
                    "instruction",
                    data_categories=list(categories),
                )
                agent._call_primary = AsyncMock(side_effect=error)
                agent._call_jyqf = AsyncMock(return_value="fallback")

                with (
                    patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
                    patch.object(
                        Config, "PROVIDER_DATA_POLICY", {"jyqf": categories}
                    ),
                ):
                    self.assertEqual(
                        await agent.call("source text"),
                        "fallback",
                    )

                agent._call_jyqf.assert_awaited_once()

    async def test_jyqf_fallback_uses_the_selected_route_and_model(self):
        categories = ["source_text", "book_knowledge"]
        agent = UnifiedAgent(
            "gpt-6-luna",
            "instruction",
            data_categories=categories,
        )
        create_completion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="fallback response"),
                    )
                ]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create_completion)
            )
        )

        with (
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"jyqf": frozenset(categories)},
            ),
            patch("pipeline.get_api_key", return_value="synthetic-jyqf-key"),
            patch("pipeline.get_openai_client", return_value=client) as client_factory,
        ):
            result = await agent._call_jyqf("source prompt", "system prompt")

        self.assertEqual(result, "fallback response")
        client_factory.assert_called_once_with(
            Config.JYQF_BASE_URL,
            "synthetic-jyqf-key",
            provider_id="jyqf",
            data_categories=categories,
            max_retries=0,
        )
        create_completion.assert_awaited_once()
        self.assertEqual(
            create_completion.call_args.kwargs["model"],
            "deepseek-v4.1-flash",
        )

    async def test_local_jyqf_fallback_does_not_require_remote_data_grant(self):
        agent = UnifiedAgent(
            "gpt-6-luna",
            "instruction",
            data_categories=["source_text"],
        )
        create_completion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="local response"),
                    )
                ]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create_completion)
            )
        )

        with (
            patch.object(Config, "PROVIDER_DATA_POLICY", {}),
            patch("pipeline.get_api_key", return_value=None),
            patch(
                "pipeline.get_base_url",
                return_value="http://127.0.0.1:12345/v1",
            ),
            patch("pipeline.get_openai_client", return_value=client) as client_factory,
        ):
            result = await agent._call_jyqf("source prompt", "system prompt")

        self.assertEqual(result, "local response")
        client_factory.assert_called_once_with(
            Config.JYQF_BASE_URL,
            None,
            provider_id="jyqf",
            data_categories=["source_text"],
            max_retries=0,
        )

    async def test_jyqf_fallback_requires_provider_data_authorization(self):
        categories = ["source_text", "book_knowledge"]
        agent = UnifiedAgent(
            "gpt-6-luna",
            "instruction",
            data_categories=categories,
        )
        agent._call_primary = AsyncMock(
            side_effect=APIConnectionError(request=object())
        )

        with (
            patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
            patch.object(Config, "PROVIDER_DATA_POLICY", {}),
        ):
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                await agent.call("source text")

        agent._call_primary.assert_awaited_once()

    @patch.dict(os.environ, {"JYQF_API_KEY": "test-key"}, clear=True)
    async def test_jojo_auth_contract_and_content_errors_do_not_fall_back(self):
        errors = [
            *(make_api_status_error(code) for code in (400, 401, 403, 404)),
            ResponseContractError("invalid response"),
            ContentBlockedError("blocked"),
        ]
        categories = frozenset({"source_text"})
        for error in errors:
            with self.subTest(error=type(error).__name__):
                agent = UnifiedAgent(
                    "gpt-6-luna",
                    "instruction",
                    data_categories=list(categories),
                )
                agent._call_primary = AsyncMock(side_effect=error)
                agent._call_jyqf = AsyncMock(return_value="fallback")

                with (
                    patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
                    patch.object(
                        Config, "PROVIDER_DATA_POLICY", {"jyqf": categories}
                    ),
                ):
                    with self.assertRaises(type(error)):
                        await agent.call("source text")

                agent._call_jyqf.assert_not_awaited()

    async def test_jyqf_failure_does_not_cascade_to_gemini(self):
        fallback_error = make_api_status_error(500)
        categories = ["source_text"]
        agent = UnifiedAgent(
            "gpt-6-luna",
            "instruction",
            data_categories=categories,
        )
        agent._call_primary = AsyncMock(
            side_effect=[
                APIConnectionError(request=object()),
                fallback_error,
            ]
        )
        agent._call_gemini = AsyncMock(return_value="unexpected Gemini response")

        with (
            patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", True),
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"jyqf": frozenset(categories)},
            ),
        ):
            with self.assertRaises(APIStatusError) as raised:
                await agent.call("source text")

        self.assertIs(raised.exception, fallback_error)
        self.assertEqual(agent._call_primary.await_count, 2)
        agent._call_gemini.assert_not_awaited()

    def test_jyqf_fallback_preflight_checks_the_fallback_scope(self):
        all_categories = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        models = (
            patch.object(Config, "INITIAL_MODEL", "gpt-6-luna"),
            patch.object(Config, "PROOFREAD_MODEL", "gpt-6-luna"),
            patch.object(Config, "STYLE_MODEL", "gpt-6-luna"),
            patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", False),
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {
                    "jojo": all_categories,
                    "jyqf": frozenset({"source_text", "book_knowledge"}),
                },
            ),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch("pipeline.get_api_key", return_value="synthetic-key"),
        )
        with (
            models[0],
            models[1],
            models[2],
            models[3],
            models[4],
            models[5],
            models[6],
            models[7],
        ):
            with self.assertRaisesRegex(PermissionError, "translation_text"):
                validate_provider_configuration()

    def test_jyqf_fallback_preflight_requires_remote_credentials(self):
        all_categories = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        models = (
            patch.object(Config, "INITIAL_MODEL", "gpt-6-luna"),
            patch.object(Config, "PROOFREAD_MODEL", "gpt-6-luna"),
            patch.object(Config, "STYLE_MODEL", "gpt-6-luna"),
            patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", False),
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"jojo": all_categories, "jyqf": all_categories},
            ),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch(
                "pipeline.get_api_key",
                side_effect=lambda name: (
                    None if name == "JYQF_API_KEY" else "synthetic-key"
                ),
            ),
        )
        with (
            models[0],
            models[1],
            models[2],
            models[3],
            models[4],
            models[5],
            models[6],
            models[7],
        ):
            with self.assertRaisesRegex(RuntimeError, "JYQF_API_KEY"):
                validate_provider_configuration()

    def test_jyqf_fallback_preflight_only_requires_reachable_gemini_scope(self):
        source_and_knowledge = frozenset(
            {"source_text", "book_knowledge"}
        )
        full_translation = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        with (
            patch.object(Config, "INITIAL_MODEL", "sakura-test"),
            patch.object(Config, "PROOFREAD_MODEL", "gpt-6-luna"),
            patch.object(Config, "STYLE_MODEL", "gpt-6-luna"),
            patch.object(Config, "STRICT_REFLECTION_MODE", False),
            patch.object(Config, "JYQF_FALLBACK_ENABLED", True),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", True),
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {
                    "sakura": source_and_knowledge,
                    "jojo": full_translation,
                    "jyqf": full_translation,
                    "gemini": source_and_knowledge,
                },
            ),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch("pipeline.get_api_key", return_value="synthetic-key"),
        ):
            validate_provider_configuration()

    @patch.dict(
        os.environ,
        {
            FALLBACK_ENV: "pool:backup",
            "GEMINI_API_KEY": "synthetic-key",
        },
        clear=True,
    )
    def test_pool_fallback_preflight_does_not_require_gemini_translation_scope(self):
        all_categories = frozenset(
            {"source_text", "translation_text", "book_knowledge"}
        )
        source_and_knowledge = frozenset({"source_text", "book_knowledge"})

        def route_for(model_name):
            slot = model_name.split(":", 1)[1]
            return SimpleNamespace(
                provider_id=slot,
                base_url=f"https://{slot}.example/v1",
                api_key_env=f"{slot.upper()}_API_KEY",
            )

        with (
            patch.object(Config, "INITIAL_MODEL", "pool:primary"),
            patch.object(Config, "PROOFREAD_MODEL", "pool:primary"),
            patch.object(Config, "STYLE_MODEL", "pool:primary"),
            patch.object(Config, "STRICT_REFLECTION_MODE", False),
            patch.object(Config, "JYQF_FALLBACK_ENABLED", False),
            patch.object(Config, "GEMINI_FALLBACK_ENABLED", True),
            patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {
                    "primary": all_categories,
                    "backup": all_categories,
                    "gemini": source_and_knowledge,
                },
            ),
            patch("pipeline.get_primary_provider_route", side_effect=route_for),
            patch("pipeline.get_base_url", side_effect=lambda url: url),
            patch("pipeline.get_api_key", return_value="synthetic-key"),
        ):
            validate_provider_configuration()

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
    def test_no_project_default_does_not_fall_back_to_repository_raws(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("sys.argv", ["pipeline.py"]),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch.object(Config, "WORKSPACE_DIR", ""),
            ):
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    "verified AI edition was selected",
                ):
                    Config.load_config()

    def test_no_project_default_rejects_ambiguous_project_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            projects_dir = repo_dir / "projects"
            (projects_dir / "book-a").mkdir(parents=True)
            (projects_dir / "book-b").mkdir()
            (projects_dir / "example").mkdir()

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("sys.argv", ["pipeline.py"]),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch.object(Config, "WORKSPACE_DIR", ""),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Multiple translation projects.*--project.*TRANSLATOR_PROJECT",
                ):
                    Config.load_config()

    def test_unreviewed_tm_opt_in_defaults_off_and_resets(self):
        self.addCleanup(setattr, Config, "ALLOW_UNREVIEWED_TM", False)
        with patch.dict(
            os.environ,
            {
                "TEST_WORKSPACE_DIR": "isolated-test-workspace",
                "ALLOW_UNREVIEWED_TM": "true",
            },
            clear=True,
        ):
            Config.load_config()
        self.assertTrue(Config.ALLOW_UNREVIEWED_TM)

        with patch.dict(
            os.environ,
            {"TEST_WORKSPACE_DIR": "isolated-test-workspace"},
            clear=True,
        ):
            Config.load_config()
        self.assertFalse(Config.ALLOW_UNREVIEWED_TM)

    def test_unreviewed_tm_opt_in_uses_json_and_environment_override(self):
        self.addCleanup(setattr, Config, "ALLOW_UNREVIEWED_TM", False)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"ALLOW_UNREVIEWED_TM": True}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertTrue(Config.ALLOW_UNREVIEWED_TM)

            with patch.dict(
                os.environ,
                {"ALLOW_UNREVIEWED_TM": "false"},
                clear=True,
            ):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertFalse(Config.ALLOW_UNREVIEWED_TM)

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
            (project_dir / "SourceArchive").mkdir()
            (project_dir / "RAWs_AI").mkdir()
            (project_dir / "熟肉" / "EPUB").mkdir(parents=True)
            (project_dir / "熟肉" / "Ntera").mkdir()

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    pipeline_module, "__file__", str(repo_dir / "pipeline.py")
                ):
                    with patch(
                        "pipeline._default_ai_edition_config",
                        return_value={
                            "source_root": str(project_dir / "SourceArchive"),
                            "ai_edition_root": str(project_dir / "RAWs_AI"),
                            "source_manifest_path": "source_editions_manifest.json",
                            "chapter_map": [],
                        },
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

    def test_project_mode_defaults_to_ai_mirror_with_archive_lineage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            project_dir = repo_dir / "projects" / "sample"
            source_root = project_dir / "SourceArchive"
            ai_root = project_dir / "RAWs_AI"
            (project_dir / "生肉").mkdir(parents=True)
            (project_dir / "生肉" / "human-copy.md").write_text(
                "human-readable source", encoding="utf-8"
            )
            source_root.mkdir()
            ai_root.mkdir()
            (project_dir / "熟肉").mkdir()
            index = {
                "work_id": "work-1",
                "catalog": {
                    "relative_path": "source_catalog.json",
                    "sha256": "catalog-hash",
                },
                "episodes": [
                    {
                        "episode_id": "102",
                        "title": "Episode 2",
                        "position": 2,
                        "ai_archive_relative_path": "editions/ai/102/v2.md",
                        "ai_relative_path": "episodes/0002-102.md",
                        "output_sha256": "2" * 64,
                        "ai_edition_version_id": "ai-version-2",
                    },
                    {
                        "episode_id": "101",
                        "title": "Episode 1",
                        "position": 1,
                        "ai_archive_relative_path": "editions/ai/101/v1.md",
                        "ai_relative_path": "episodes/0001-101.md",
                        "output_sha256": "1" * 64,
                        "ai_edition_version_id": "ai-version-1",
                    },
                ],
            }

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch(
                    "pipeline.verify_ai_edition_index",
                    return_value={"index": index},
                ) as verify_index,
                patch(
                    "pipeline._load_catalog_snapshot",
                    return_value={
                        "work_id": "work-1",
                        "sha256": "catalog-hash",
                        "episodes": (
                            SimpleNamespace(
                                metadata=SimpleNamespace(
                                    episode_id="101",
                                    title="Episode 1",
                                    position=1,
                                )
                            ),
                            SimpleNamespace(
                                metadata=SimpleNamespace(
                                    episode_id="102",
                                    title="Episode 2",
                                    position=2,
                                )
                            ),
                        ),
                    },
                ) as load_catalog,
                patch.object(Config, "WORKSPACE_DIR", ""),
                patch.object(Config, "RAW_DIR", ""),
                patch.object(Config, "OUTPUT_DIR", ""),
                patch.object(Config, "SOURCE_MANIFEST_PATH", None),
                patch.object(Config, "CHAPTER_MAP", None),
            ):
                Config.load_config(project="sample")

                self.assertEqual(
                    Path(Config.RAW_DIR).resolve(), source_root.resolve()
                )
                self.assertEqual(
                    Path(Config.AI_EDITION_ROOT).resolve(), ai_root.resolve()
                )
                self.assertTrue(Config.REQUIRE_REVIEWED_STORY_SUMMARY)
                self.assertTrue(Config.REQUIRE_REVIEWED_GLOSSARY)
                self.assertTrue(Config.REQUIRE_REVIEWED_PUBLICATION)
                self.assertEqual(
                    Config.GLOSSARY_PATH,
                    str(
                        (project_dir / "Knowledge" / "Glossary_reviewed.json")
                        .resolve()
                    ),
                )
                self.assertEqual(
                    Config.STORY_SUMMARY_PATH,
                    str(
                        (
                            project_dir
                            / "Knowledge"
                            / "STORY_SUMMARY_reviewed.json"
                        ).resolve()
                    ),
                )
                self.assertEqual(
                    Config.SOURCE_MANIFEST_PATH,
                    "source_editions_manifest.json",
                )
                self.assertEqual(
                    [chapter["raw_file"] for chapter in Config.CHAPTER_MAP],
                    [
                        "editions/ai/101/v1.md",
                        "editions/ai/102/v2.md",
                    ],
                )
                self.assertEqual(
                    [chapter["source_input_file"] for chapter in Config.CHAPTER_MAP],
                    [
                        "episodes/0001-101.md",
                        "episodes/0002-102.md",
                    ],
                )
                self.assertEqual(
                    [chapter["source_version_id"] for chapter in Config.CHAPTER_MAP],
                    ["ai-version-1", "ai-version-2"],
                )
                self.assertEqual(
                    [chapter["translation_file"] for chapter in Config.CHAPTER_MAP],
                    ["episode-0001-101.md", "episode-0002-102.md"],
                )
                self.assertEqual(
                    [chapter["tm_key"] for chapter in Config.CHAPTER_MAP],
                    [
                        "source-edition:work-1:101",
                        "source-edition:work-1:102",
                    ],
                )
                self.assertEqual(
                    Path(
                        verify_index.call_args.kwargs["source_root"]
                    ).resolve(),
                    source_root.resolve(),
                )
                self.assertEqual(
                    Path(
                        verify_index.call_args.kwargs["ai_root"]
                    ).resolve(),
                    ai_root.resolve(),
                )
                self.assertEqual(
                    verify_index.call_args.kwargs[
                        "source_manifest_relative_path"
                    ],
                    "source_manifest.json",
                )
                self.assertEqual(
                    verify_index.call_args.kwargs[
                        "edition_manifest_relative_path"
                    ],
                    "source_editions_manifest.json",
                )
                self.assertEqual(
                    Path(load_catalog.call_args.args[0]).resolve(),
                    source_root.resolve(),
                )
                self.assertEqual(
                    load_catalog.call_args.args[1],
                    "source_catalog.json",
                )

    def test_project_pipeline_cannot_write_without_an_active_review_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "OUTPUT_DIR", str(workspace / "熟肉")),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "reviewed_run_draft"),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "TRANSLATION_RUN_ID", None),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "run_kakuyomu_workflow.py",
                ):
                    TranslationPipeline()

    def test_project_pipeline_rejects_unreviewed_tm_override_before_loading_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "OUTPUT_DIR", str(workspace / "drafts")),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "reviewed_run_draft"),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "ALLOW_UNREVIEWED_TM", True),
                patch("pipeline.load_json") as load_json,
                patch("pipeline.RAGEngine") as rag_engine,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "cannot enable unreviewed TM retrieval",
                ):
                    TranslationPipeline()

            load_json.assert_not_called()
            rag_engine.assert_not_called()

    def test_unreviewed_pipeline_cannot_write_to_project_publication_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            publication_root = workspace / "熟肉"
            publication_root.mkdir()
            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "OUTPUT_DIR", str(publication_root)),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", False),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "cannot write to a project publication directory",
                ):
                    TranslationPipeline()

    def test_unreviewed_pipeline_cannot_write_to_configured_external_publication_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "project"
            publication_root = Path(temporary) / "final-translation"
            workspace.mkdir()
            publication_root.mkdir()
            (workspace / "workflow_paths.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "output_dir": str(publication_root),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "OUTPUT_DIR", str(publication_root)),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", False),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "cannot write to a project publication directory",
                ):
                    TranslationPipeline()

    def test_unreviewed_pipeline_allows_nonpublication_compat_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "project"
            draft_root = workspace / "Workflow" / "LegacyDrafts"
            draft_root.mkdir(parents=True)
            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "OUTPUT_DIR", str(draft_root)),
                patch.object(Config, "TRANSLATION_OUTPUT_MODE", "compatibility_draft"),
                patch.object(Config, "GLOSSARY_PATH", ""),
                patch.object(Config, "STORY_SUMMARY_PATH", ""),
                patch.object(Config, "INFO_PATH", ""),
                patch.object(Config, "TM_PATH", ""),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", False),
                patch("pipeline.load_json", return_value={}),
                patch("pipeline.RAGEngine", return_value=Mock()),
            ):
                TranslationPipeline()

    def test_unreviewed_pipeline_checks_mapped_publication_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            chapter_map = [
                {
                    "raw_file": "raw/episode.md",
                    "translation_file": "熟肉/episode.md",
                    "tm_key": "episode-1",
                }
            ]

            with self.assertRaisesRegex(
                ValueError,
                "cannot write to a project publication directory",
            ):
                _reject_unreviewed_project_publication(
                    str(workspace),
                    str(workspace),
                    chapter_map,
                )

            _reject_unreviewed_project_publication(
                str(workspace),
                str(workspace),
                [
                    {
                        "raw_file": "raw/episode.md",
                        "translation_file": "Workflow/Drafts/episode.md",
                        "tm_key": "episode-1",
                    }
                ],
            )

    def test_explicit_json_pipeline_requires_compatibility_draft_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "project"
            output_root = Path(temporary) / "arbitrary-output"
            workspace.mkdir()
            output_root.mkdir()
            config_path = Path(temporary) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(workspace),
                        "RAW_DIR": str(workspace / "source"),
                        "OUTPUT_DIR": str(output_root),
                    }
                ),
                encoding="utf-8",
            )
            with patch.multiple(
                Config,
                WORKSPACE_DIR="",
                RAW_DIR="",
                OUTPUT_DIR="",
                TRANSLATION_OUTPUT_MODE=None,
                CHAPTER_MAP=None,
                SOURCE_MANIFEST_PATH=None,
                AI_EDITION_ROOT=None,
                REQUIRE_REVIEWED_PUBLICATION=False,
                TRANSLATION_RUN_ID=None,
                REQUIRE_REVIEWED_STORY_SUMMARY=False,
                EXPECTED_BOOK_BUNDLE=None,
                REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE=False,
                REQUIRE_REVIEWED_GLOSSARY=False,
                TM_REVIEWED_PATH=None,
                ALLOW_UNREVIEWED_TM=False,
                GLOSSARY_PATH="",
                GUIDELINES_PATH="",
                INFO_PATH="",
                STORY_SUMMARY_PATH="",
                TM_PATH="",
            ):
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch("pipeline.os.path.exists", return_value=False),
                ):
                    Config.load_config(config_file=str(config_path))

                self.assertIsNone(Config.TRANSLATION_OUTPUT_MODE)
                with self.assertRaisesRegex(
                    ValueError,
                    "explicit TRANSLATION_OUTPUT_MODE='compatibility_draft'",
                ):
                    TranslationPipeline()

    def test_explicit_json_pipeline_accepts_marked_compatibility_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "project"
            output_root = Path(temporary) / "draft-output"
            workspace.mkdir()
            output_root.mkdir()
            config_path = Path(temporary) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(workspace),
                        "RAW_DIR": str(workspace / "source"),
                        "OUTPUT_DIR": str(output_root),
                        "TRANSLATION_OUTPUT_MODE": "compatibility_draft",
                        "GLOSSARY_PATH": "",
                        "GUIDELINES_PATH": "",
                        "INFO_PATH": "",
                        "STORY_SUMMARY_PATH": "",
                        "TM_PATH": "",
                    }
                ),
                encoding="utf-8",
            )
            with patch.multiple(
                Config,
                WORKSPACE_DIR="",
                RAW_DIR="",
                OUTPUT_DIR="",
                TRANSLATION_OUTPUT_MODE=None,
                CHAPTER_MAP=None,
                SOURCE_MANIFEST_PATH=None,
                AI_EDITION_ROOT=None,
                REQUIRE_REVIEWED_PUBLICATION=False,
                TRANSLATION_RUN_ID=None,
                REQUIRE_REVIEWED_STORY_SUMMARY=False,
                EXPECTED_BOOK_BUNDLE=None,
                REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE=False,
                REQUIRE_REVIEWED_GLOSSARY=False,
                TM_REVIEWED_PATH=None,
                ALLOW_UNREVIEWED_TM=False,
                GLOSSARY_PATH="",
                GUIDELINES_PATH="",
                INFO_PATH="",
                STORY_SUMMARY_PATH="",
                TM_PATH="",
            ):
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch("pipeline.os.path.exists", return_value=False),
                ):
                    Config.load_config(config_file=str(config_path))

                with (
                    patch("pipeline.load_json", return_value={}),
                    patch("pipeline.RAGEngine", return_value=Mock()),
                ):
                    TranslationPipeline()

                self.assertEqual(
                    Config.TRANSLATION_OUTPUT_MODE,
                    "compatibility_draft",
                )

    def test_compatibility_draft_mode_cannot_claim_reviewed_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            config_path = workspace / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(workspace),
                        "REQUIRE_REVIEWED_PUBLICATION": True,
                        "TRANSLATION_OUTPUT_MODE": "compatibility_draft",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    with self.assertRaisesRegex(
                        ValueError,
                        "cannot enable reviewed project publication",
                    ):
                        Config.load_config(config_file=str(config_path))

    def test_project_output_override_keeps_ai_edition_as_translation_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / "repo"
            project_dir = repo_dir / "projects" / "sample"
            source_root = project_dir / "SourceArchive"
            ai_root = project_dir / "RAWs_AI"
            output_root = repo_dir / "external-translation-root"
            human_root = repo_dir / "external-human-root"
            source_root.mkdir(parents=True)
            ai_root.mkdir()
            output_root.mkdir()
            human_root.mkdir()
            (project_dir / "熟肉").mkdir()
            settings = {
                "schema_version": 1,
                "output_dir": "../../external-translation-root",
                "human_edition_root": "../../external-human-root",
            }
            (project_dir / "workflow_paths.json").write_text(
                json.dumps(settings),
                encoding="utf-8",
            )
            ai_chapter_map = [
                {
                    "raw_file": "editions/ai/episode-1.md",
                    "translation_file": "episode-0001-101.md",
                    "tm_key": "source-edition:work-1:101",
                    "source_version_id": "ai-version-1",
                    "chapter_position": 1,
                }
            ]

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch(
                    "pipeline._default_ai_edition_config",
                    return_value={
                        "source_root": str(source_root),
                        "ai_edition_root": str(ai_root),
                        "source_manifest_path": "source_editions_manifest.json",
                        "chapter_map": ai_chapter_map,
                    },
                ) as resolve_ai,
                patch.object(Config, "WORKSPACE_DIR", ""),
                patch.object(Config, "RAW_DIR", ""),
                patch.object(Config, "OUTPUT_DIR", ""),
                patch.object(Config, "SOURCE_MANIFEST_PATH", None),
                patch.object(Config, "CHAPTER_MAP", None),
            ):
                Config.load_config(project="sample")

                self.assertEqual(
                    Path(Config.RAW_DIR).resolve(), source_root.resolve()
                )
                self.assertEqual(
                    Path(Config.AI_EDITION_ROOT).resolve(), ai_root.resolve()
                )
                self.assertEqual(
                    Config.TRANSLATION_OUTPUT_MODE,
                    "reviewed_run_draft",
                )
                self.assertEqual(Config.OUTPUT_DIR, str(output_root.resolve()))
                self.assertEqual(
                    Config.SOURCE_MANIFEST_PATH,
                    "source_editions_manifest.json",
                )
                self.assertEqual(Config.CHAPTER_MAP, ai_chapter_map)
                resolve_ai.assert_called_once()
                self.assertEqual(
                    _resolve_project_human_edition_root(str(project_dir)),
                    str(human_root.resolve()),
                )

    def test_project_mode_does_not_fall_back_when_ai_edition_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            project_dir = repo_dir / "projects" / "sample"
            (project_dir / "SourceArchive").mkdir(parents=True)
            (project_dir / "RAWs_AI").mkdir()
            (project_dir / "生肉").mkdir()
            (project_dir / "生肉" / "human-copy.md").write_text(
                "human-readable source", encoding="utf-8"
            )

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch(
                    "pipeline.verify_ai_edition_index",
                    side_effect=ValueError("AI edition index is stale."),
                ),
                patch.object(Config, "WORKSPACE_DIR", ""),
            ):
                with self.assertRaisesRegex(
                    ValueError, "AI edition index is stale"
                ):
                    Config.load_config(project="sample")

    def test_project_mode_requires_ai_edition_instead_of_using_human_readable_raws(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            project_dir = repo_dir / "projects" / "sample"
            raw_dir = project_dir / "生肉"
            raw_dir.mkdir(parents=True)
            (raw_dir / "human-copy.md").write_text(
                "human-readable source", encoding="utf-8"
            )
            (project_dir / "熟肉").mkdir()

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch.object(Config, "WORKSPACE_DIR", ""),
            ):
                with self.assertRaisesRegex(
                    FileNotFoundError, "requires a verified AI edition"
                ):
                    Config.load_config(project="sample")

    def test_project_mode_rejects_ai_index_for_a_changed_catalog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            project_dir = repo_dir / "projects" / "sample"
            (project_dir / "SourceArchive").mkdir(parents=True)
            (project_dir / "RAWs_AI").mkdir()
            index = {
                "work_id": "work-1",
                "catalog": {
                    "relative_path": "source_catalog.json",
                    "sha256": "old-catalog-hash",
                },
                "episodes": [],
            }

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    pipeline_module,
                    "__file__",
                    str(repo_dir / "pipeline.py"),
                ),
                patch(
                    "pipeline.verify_ai_edition_index",
                    return_value={"index": index},
                ),
                patch(
                    "pipeline._load_catalog_snapshot",
                    return_value={
                        "work_id": "work-1",
                        "sha256": "current-catalog-hash",
                        "episodes": (),
                    },
                ),
                patch.object(Config, "WORKSPACE_DIR", ""),
            ):
                with self.assertRaisesRegex(
                    ValueError, "stale for its source catalog"
                ):
                    Config.load_config(project="sample")

    def test_test_workspace_populates_all_path_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            tm_path = workspace / "custom" / "memory.json"
            env = {
                "TEST_WORKSPACE_DIR": str(workspace),
                "TEST_TM_PATH": str(tm_path),
                "TEST_TM_REVIEWED_PATH": str(workspace / "reviewed.json"),
                "TEST_RAW_DIR": str(workspace / "input"),
                "TEST_OUTPUT_DIR": str(workspace / "output"),
            }
            with patch.dict(os.environ, env, clear=True):
                Config.load_config()

            self.assertEqual(Config.TM_PATH, str(tm_path))
            self.assertEqual(
                Config.TM_REVIEWED_PATH,
                str(workspace / "reviewed.json"),
            )
            self.assertEqual(Config.RAW_DIR, str(workspace / "input"))
            self.assertEqual(Config.OUTPUT_DIR, str(workspace / "output"))
            self.assertEqual(Config.TRANSLATION_OUTPUT_MODE, "test_draft")

    def test_test_workspace_default_pipeline_uses_nonpublication_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            knowledge_dir = workspace / "Knowledge"
            knowledge_dir.mkdir()
            (knowledge_dir / "作品基本信息.json").write_text(
                "{}",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"TEST_WORKSPACE_DIR": str(workspace)},
                clear=True,
            ):
                Config.load_config()
                with patch("pipeline.RAGEngine"):
                    TranslationPipeline()

            self.assertEqual(
                Config.OUTPUT_DIR,
                str(workspace / "translated"),
            )

    def test_output_mode_resets_when_reloading_unmarked_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(root / "project"),
                        "RAW_DIR": str(root / "project" / "source"),
                        "OUTPUT_DIR": str(root / "drafts"),
                    }
                ),
                encoding="utf-8",
            )
            with patch.multiple(
                Config,
                WORKSPACE_DIR="",
                RAW_DIR="",
                OUTPUT_DIR="",
                TRANSLATION_OUTPUT_MODE=None,
                CHAPTER_MAP=None,
                SOURCE_MANIFEST_PATH=None,
                AI_EDITION_ROOT=None,
                REQUIRE_REVIEWED_PUBLICATION=False,
                TRANSLATION_RUN_ID=None,
                REQUIRE_REVIEWED_STORY_SUMMARY=False,
                EXPECTED_BOOK_BUNDLE=None,
                REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE=False,
                REQUIRE_REVIEWED_GLOSSARY=False,
                TM_REVIEWED_PATH=None,
                ALLOW_UNREVIEWED_TM=False,
            ):
                with patch.dict(
                    os.environ,
                    {"TEST_WORKSPACE_DIR": str(root / "test-workspace")},
                    clear=True,
                ):
                    Config.load_config()
                self.assertEqual(Config.TRANSLATION_OUTPUT_MODE, "test_draft")

                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch("pipeline.os.path.exists", return_value=False),
                ):
                    Config.load_config(config_file=str(config_path))

                self.assertIsNone(Config.TRANSLATION_OUTPUT_MODE)

    def test_pipeline_cli_rejects_unmarked_json_before_translation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "project"
            output_root = root / "arbitrary-output"
            workspace.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WORKSPACE_DIR": str(workspace),
                        "RAW_DIR": str(workspace / "source"),
                        "OUTPUT_DIR": str(output_root),
                    }
                ),
                encoding="utf-8",
            )
            repo_root = Path(__file__).resolve().parents[1]
            environment = os.environ.copy()
            environment.pop("TEST_WORKSPACE_DIR", None)
            environment.pop("TRANSLATOR_PROJECT", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "pipeline.py"),
                    "--config",
                    str(config_path),
                ],
                cwd=repo_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "TRANSLATION_OUTPUT_MODE='compatibility_draft'",
            completed.stderr,
        )
        self.assertFalse(output_root.exists())
        self.assertNotIn("/v1/chat/completions", completed.stderr)

    def test_jyqf_fallback_requires_explicit_enablement(self):
        self.addCleanup(setattr, Config, "JYQF_FALLBACK_ENABLED", False)
        with patch.dict(
            os.environ,
            {
                "TEST_WORKSPACE_DIR": "isolated-test-workspace",
                "ENABLE_JYQF_FALLBACK": "true",
            },
            clear=True,
        ):
            Config.load_config()
        self.assertTrue(Config.JYQF_FALLBACK_ENABLED)

        with patch.dict(
            os.environ,
            {"TEST_WORKSPACE_DIR": "isolated-test-workspace"},
            clear=True,
        ):
            Config.load_config()
        self.assertFalse(Config.JYQF_FALLBACK_ENABLED)

    def test_jyqf_fallback_uses_json_config_unless_environment_overrides(self):
        self.addCleanup(setattr, Config, "JYQF_FALLBACK_ENABLED", False)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"ENABLE_JYQF_FALLBACK": True}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertTrue(Config.JYQF_FALLBACK_ENABLED)

            with patch.dict(
                os.environ,
                {"ENABLE_JYQF_FALLBACK": "false"},
                clear=True,
            ):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertFalse(Config.JYQF_FALLBACK_ENABLED)

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

    def test_reviewed_tm_path_uses_json_configuration_and_environment_override(self):
        self.addCleanup(setattr, Config, "TM_REVIEWED_PATH", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"TM_REVIEWED_PATH": "Knowledge/reviewed.json"}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertEqual(Config.TM_REVIEWED_PATH, "Knowledge/reviewed.json")

            with patch.dict(
                os.environ,
                {"TM_REVIEWED_PATH": "Knowledge/override.json"},
                clear=True,
            ):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))
            self.assertEqual(Config.TM_REVIEWED_PATH, "Knowledge/override.json")

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

    def test_stage_models_can_be_overridden_from_environment(self):
        original_models = {
            name: getattr(Config, name)
            for name in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")
        }
        for name, value in original_models.items():
            self.addCleanup(setattr, Config, name, value)

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "INITIAL_MODEL": "json-initial",
                        "PROOFREAD_MODEL": "json-proofread",
                        "STYLE_MODEL": "json-style",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "INITIAL_MODEL": "gpt-6-Luna",
                    "PROOFREAD_MODEL": "gpt-6-Luna",
                    "STYLE_MODEL": "gpt-6-Luna",
                },
                clear=True,
            ):
                with patch("pipeline.os.path.exists", return_value=False):
                    Config.load_config(config_file=str(config_path))

        self.assertEqual(Config.INITIAL_MODEL, "gpt-6-Luna")
        self.assertEqual(Config.PROOFREAD_MODEL, "gpt-6-Luna")
        self.assertEqual(Config.STYLE_MODEL, "gpt-6-Luna")

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
    def test_split_paragraphs_preserves_fullwidth_and_nonbreaking_indent(self):
        self.assertEqual(
            split_paragraphs("　全角空格保留\n\n\u00a0不换行空格保留"),
            ["　全角空格保留", "\u00a0不换行空格保留"],
        )
        self.assertEqual(
            split_paragraphs("第一段\n\n　\n\n\u00a0\n\n第二段"),
            ["第一段", "第二段"],
        )

    def test_split_paragraphs_normalizes_windows_and_classic_mac_newlines(self):
        self.assertEqual(
            split_paragraphs("第一段\r\n\r\n第二段\r内换行"),
            ["第一段", "第二段\n内换行"],
        )

    def test_aligned_paragraphs_normalize_internal_line_endings(self):
        from utils import require_aligned_paragraphs

        target = ["first\r\nsecond"]
        require_aligned_paragraphs(["source"], target, "synthetic stage")
        self.assertEqual(target, ["first\nsecond"])

        with self.assertRaisesRegex(ValueError, "multiple paragraphs"):
            require_aligned_paragraphs(
                ["source"],
                ["first\r\n\r\nsecond"],
                "synthetic stage",
            )

    def test_chapter_map_preserves_catalog_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "normalized-hash.md").write_text(
                "synthetic source", encoding="utf-8"
            )
            chapter_map = [
                {
                    "raw_file": "normalized-hash.md",
                    "translation_file": "episode-0002.md",
                    "tm_key": "episode:2",
                    "chapter_position": 2,
                }
            ]

            specs = get_chapter_specs(
                str(raw_dir), str(output_dir), chapter_map
            )

        self.assertEqual(specs[0].chapter_position, 2)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "normalized-hash.md").write_text(
                "synthetic source", encoding="utf-8"
            )
            chapter_map[0]["chapter_position"] = True
            with self.assertRaisesRegex(ValueError, "chapter_position"):
                get_chapter_specs(str(raw_dir), str(output_dir), chapter_map)

    def test_bound_ai_source_reader_uses_raws_ai_mirror(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "SourceArchive"
            ai_root = root / "RAWs_AI"
            archive.mkdir()
            ai_root.mkdir()
            translations = root / "translations"
            translations.mkdir()
            archived_text = "archived copy"
            ai_text = "AI edition input"
            archive_file = archive / "editions" / "ai" / "episode.md"
            ai_file = ai_root / "episodes" / "episode.md"
            archive_file.parent.mkdir(parents=True)
            ai_file.parent.mkdir(parents=True)
            archive_file.write_text(archived_text, encoding="utf-8")
            ai_file.write_text(ai_text, encoding="utf-8")
            raw_file = archive / "raw" / "episode.txt"
            raw_file.parent.mkdir()
            raw_file.write_text("archived raw source", encoding="utf-8")
            append_artifact(
                archive / "source_manifest.json",
                {
                    "artifact_id": "episode:raw",
                    "version_id": "raw-version-1",
                    "kind": "raw_source",
                    "content_sha256": hashlib.sha256(
                        b"archived raw source"
                    ).hexdigest(),
                    "relative_path": "raw/episode.txt",
                    "parent_version_ids": [],
                },
            )
            append_artifact(
                archive / "source_manifest.json",
                {
                    "artifact_id": "episode:ai",
                    "version_id": "ai-version-1",
                    "kind": "normalized_source",
                    "content_sha256": hashlib.sha256(
                        ai_text.encode("utf-8")
                    ).hexdigest(),
                    "relative_path": "editions/ai/episode.md",
                    "parent_version_ids": ["raw-version-1"],
                },
            )

            with (
                patch.object(Config, "RAW_DIR", str(archive)),
                patch.object(Config, "AI_EDITION_ROOT", str(ai_root)),
                patch(
                    "source_manifest._verify_artifact_file",
                    side_effect=AssertionError(
                        "archive body read during AI translation setup"
                    ),
                ),
            ):
                specs = get_chapter_specs(
                    str(archive),
                    str(translations),
                    [
                        {
                            "raw_file": "editions/ai/episode.md",
                            "translation_file": "episode.md",
                            "tm_key": "episode:1",
                            "source_version_id": "ai-version-1",
                            "chapter_position": 1,
                            "source_input_file": "episodes/episode.md",
                            "source_sha256": hashlib.sha256(
                                ai_text.encode("utf-8")
                            ).hexdigest(),
                        }
                    ],
                    "source_manifest.json",
                    str(ai_root),
                )
                self.assertEqual(
                    _read_chapter_source_text(specs[0], mapped_paths=True),
                    ai_text,
                )

    async def test_context_passes_explicit_position_to_guideline_selection(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline.rag = SimpleNamespace(
            get_partitioned_guidelines=Mock(return_value="chapter rules"),
            query_translation_memory=AsyncMock(return_value=[]),
            get_cleaned_glossary=Mock(return_value=[]),
        )
        pipeline.story_summary = ""
        pipeline.info = {}

        await pipeline._build_run_context(
            "normalized/opaque-content-hash.md",
            "synthetic source",
            2,
        )

        pipeline.rag.get_partitioned_guidelines.assert_called_once_with(
            "normalized/opaque-content-hash.md",
            current_raw_text="synthetic source",
            chapter_position=2,
        )

    async def test_context_includes_reviewed_chapter_summary_and_terms(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline.rag = SimpleNamespace(
            get_partitioned_guidelines=Mock(return_value="chapter rules"),
            query_translation_memory=AsyncMock(return_value=[]),
            get_cleaned_glossary=Mock(return_value=[]),
        )
        pipeline.story_summary = "Whole-book summary."
        pipeline.info = {}
        chapter_knowledge = {
            "summary": "Approved chapter fact.",
            "terms": {"alpha": "阿尔法"},
        }

        with (
            patch.object(Config, "REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE", True),
            patch.object(
                pipeline,
                "_load_reviewed_chapter_knowledge",
                return_value=chapter_knowledge,
            ) as load_chapter_knowledge,
        ):
            context = await pipeline._build_run_context(
                "editions/ai/episode-2.md",
                "alpha source text",
                2,
            )

        load_chapter_knowledge.assert_called_once_with(
            "editions/ai/episode-2.md",
            2,
        )
        pipeline.rag.get_cleaned_glossary.assert_called_once_with(
            "alpha source text",
            additional_glossary={"alpha": "阿尔法"},
        )
        self.assertIn("<CHAPTER_KNOWLEDGE>\nApproved chapter fact.", context["static_context"])

    async def test_run_all_checks_every_pending_chapter_before_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ai_root = root / "RAWs_AI"
            ai_root.mkdir()
            chapters = []
            chapter_map = []
            for position in (1, 2):
                input_file = f"episodes/{position}.md"
                source_path = ai_root / input_file
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(
                    f"synthetic source {position}",
                    encoding="utf-8",
                )
                source_hash = hashlib.sha256(
                    source_path.read_bytes()
                ).hexdigest()
                raw_file = f"editions/ai/episode-{position}.md"
                chapter_map.append(
                    {
                        "raw_file": raw_file,
                        "translation_file": f"episode-{position}.md",
                        "tm_key": f"episode:{position}",
                        "source_version_id": f"version-{position}",
                        "chapter_position": position,
                        "source_input_file": input_file,
                        "source_sha256": source_hash,
                    }
                )
                chapters.append(
                    ChapterSpec(
                        raw_file=raw_file,
                        translation_file=f"episode-{position}.md",
                        tm_key=f"episode:{position}",
                        source_version_id=f"version-{position}",
                        chapter_position=position,
                        source_input_file=input_file,
                        source_sha256=source_hash,
                    )
                )

            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(tm_data={"chapters": {}})
            pipeline.run_chapter = AsyncMock()
            with (
                patch.object(Config, "REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE", True),
                patch.object(Config, "CHAPTER_MAP", chapter_map),
                patch.object(Config, "AI_EDITION_ROOT", str(ai_root)),
                patch.object(Config, "OUTPUT_DIR", str(root / "Drafts")),
                patch.object(Config, "RAW_DIR", str(root / "SourceArchive")),
                patch.object(Config, "SOURCE_MANIFEST_PATH", "manifest.json"),
                patch.object(
                    pipeline_module,
                    "validate_provider_configuration",
                ),
                patch.object(
                    pipeline_module,
                    "get_chapter_specs",
                    return_value=chapters,
                ),
                patch.object(
                    pipeline,
                    "_load_reviewed_chapter_knowledge",
                    side_effect=[
                        {"summary": "approved", "terms": {}},
                        ValueError("missing reviewed chapter summary"),
                    ],
                ) as load_chapter_knowledge,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "missing reviewed chapter summary",
                ):
                    await pipeline.run_all()

            self.assertEqual(load_chapter_knowledge.call_count, 2)
            pipeline.run_chapter.assert_not_awaited()

    async def test_chapter_knowledge_preflight_skips_empty_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ai_root = root / "RAWs_AI"
            ai_root.mkdir()
            source_path = ai_root / "episodes/empty.md"
            source_path.parent.mkdir()
            source_path.write_text("", encoding="utf-8")
            source_hash = hashlib.sha256(b"").hexdigest()
            chapter = ChapterSpec(
                raw_file="editions/ai/empty.md",
                translation_file="episode-empty.md",
                tm_key="episode:empty",
                source_version_id="empty-version",
                chapter_position=1,
                source_input_file="episodes/empty.md",
                source_sha256=source_hash,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(tm_data={"chapters": {}})
            pipeline._load_reviewed_chapter_knowledge = Mock()
            (root / "Drafts").mkdir()

            with (
                patch.object(Config, "AI_EDITION_ROOT", str(ai_root)),
                patch.object(Config, "OUTPUT_DIR", str(root / "Drafts")),
            ):
                pipeline._preflight_reviewed_chapter_knowledge([chapter])

            pipeline._load_reviewed_chapter_knowledge.assert_not_called()

    def test_chapter_knowledge_preflight_does_not_trust_orphaned_tm_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ai_root = root / "RAWs_AI"
            output_root = root / "Drafts"
            (ai_root / "episodes").mkdir(parents=True)
            output_root.mkdir()
            source_text = "synthetic AI source"
            (ai_root / "episodes" / "episode.md").write_text(
                source_text,
                encoding="utf-8",
            )
            source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            chapter = ChapterSpec(
                raw_file="normalized/episode.md",
                translation_file="episode.md",
                tm_key="source-edition:synthetic-work:episode-1",
                source_version_id="source-version-1",
                chapter_position=1,
                source_input_file="episodes/episode.md",
                source_sha256=source_hash,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={
                    "chapters": {
                        chapter.tm_key: [
                            {
                                "raw": "previous source",
                                "translated": "previous draft",
                            }
                        ]
                    }
                }
            )
            pipeline._load_reviewed_chapter_knowledge = Mock()

            with (
                patch.object(Config, "AI_EDITION_ROOT", str(ai_root)),
                patch.object(Config, "OUTPUT_DIR", str(output_root)),
            ):
                pipeline._preflight_reviewed_chapter_knowledge([chapter])

            pipeline._load_reviewed_chapter_knowledge.assert_called_once_with(
                chapter.raw_file,
                1,
            )

    def test_chapter_knowledge_loader_binds_current_map_and_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            source_root = workspace / "SourceArchive"
            ai_root = workspace / "RAWs_AI"
            draft_root = workspace / "Knowledge" / "ChapterDrafts"
            source_root.mkdir(parents=True)
            ai_root.mkdir()
            source_version_id = "current-ai-version"
            source_version_key = hashlib.sha256(
                source_version_id.encode("utf-8")
            ).hexdigest()[:16]
            source_hash = hashlib.sha256(b"current AI text").hexdigest()
            expected_bundle = {
                "source_snapshot_id": "source-v1-" + "a" * 64,
                "ai_bundle_id": "ai-v1-" + "b" * 64,
                "bundle_set_relative_path": "collections/set.json",
                "bundle_set_sha256": "c" * 64,
                "ai_bundle_relative_path": "collections/ai.json",
                "ai_bundle_sha256": "d" * 64,
                "episode_count": 88,
            }
            current_bundle_dir = (
                f"episode-0002-episode-2-{source_version_key}-bundle-"
                + expected_bundle["bundle_set_sha256"][:16]
            )
            (draft_root / current_bundle_dir).mkdir(parents=True)
            (draft_root / f"episode-0002-episode-2-{source_version_key}").mkdir()
            chapter_map = [
                {
                    "raw_file": "editions/ai/episode-2.md",
                    "source_version_id": source_version_id,
                    "source_input_file": "episodes/episode-2.md",
                    "source_sha256": source_hash,
                    "chapter_position": 2,
                }
            ]
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace()

            with (
                patch.object(Config, "WORKSPACE_DIR", str(workspace)),
                patch.object(Config, "RAW_DIR", str(source_root)),
                patch.object(Config, "AI_EDITION_ROOT", str(ai_root)),
                patch.object(
                    Config,
                    "SOURCE_MANIFEST_PATH",
                    "source_editions_manifest.json",
                ),
                patch.object(Config, "CHAPTER_MAP", chapter_map),
                patch.object(Config, "EXPECTED_BOOK_BUNDLE", expected_bundle),
                patch(
                    "pipeline.load_reviewed_story_summary",
                    return_value="Approved chapter summary.",
                ) as load_summary,
            ):
                result = pipeline._load_reviewed_chapter_knowledge(
                    "editions/ai/episode-2.md",
                    2,
                )

        self.assertEqual(result, {"summary": "Approved chapter summary.", "terms": {}})
        self.assertEqual(
            load_summary.call_args.args[0],
            str(
                draft_root
                / current_bundle_dir
                / "STORY_SUMMARY_reviewed.json"
            ),
        )
        self.assertEqual(
            load_summary.call_args.kwargs["expected_chapter_local"],
            {
                "position": 2,
                "source_file": "editions/ai/episode-2.md",
                "source_version_id": source_version_id,
                "source_input_file": "episodes/episode-2.md",
                "source_sha256": source_hash,
            },
        )
        self.assertEqual(
            load_summary.call_args.kwargs["expected_book_bundle"],
            expected_bundle,
        )

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
            raw_source_path = raw_dir / "raw_sources" / "chapter10.txt"
            raw_source_path.parent.mkdir()
            raw_source_path.write_bytes(b"synthetic source")
            append_artifact(
                raw_dir / "source_manifest.json",
                {
                    "artifact_id": "raw-chapter10",
                    "version_id": "raw-source-version-1",
                    "kind": "raw_source",
                    "content_sha256": hashlib.sha256(
                        b"synthetic source"
                    ).hexdigest(),
                    "relative_path": "raw_sources/chapter10.txt",
                    "parent_version_ids": [],
                },
            )
            append_artifact(
                raw_dir / "source_manifest.json",
                {
                    "artifact_id": "chapter10",
                    "version_id": "source-version-1",
                    "kind": "normalized_source",
                    "content_sha256": hashlib.sha256(
                        b"synthetic source"
                    ).hexdigest(),
                    "relative_path": "Volume 2/chapter10.md",
                    "parent_version_ids": ["raw-source-version-1"],
                },
            )
            spec = ChapterSpec(
                "Volume 2/chapter10.md",
                "Ntera/chapter10.md",
                "Volume2/chapter10.md",
                "source-version-1",
                2,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={
                    "chapters": {
                        "Volume2/chapter10.md": [
                            {
                                "raw": "previous source",
                                "translated": "previous draft",
                            }
                        ]
                    }
                },
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
                    with patch.object(
                        Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"
                    ):
                        await pipeline.run_chapter(spec)

            output_path = output_dir / "Ntera" / "chapter10.md"
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "synthetic translation",
            )
            self.assertEqual(
                pipeline._build_run_context.await_args.args,
                ("Volume 2/chapter10.md", "synthetic source", 2),
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
            self.assertEqual(
                provenance["source_version_id"], "source-version-1"
            )

    def test_formal_stage_report_is_hash_only_and_attempts_are_append_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "Workflow" / "Runs" / ("a" * 32) / "Drafts"
            output_dir.mkdir(parents=True)
            spec = ChapterSpec(
                "episodes/episode-1.md",
                "episode-0001-episode-1.md",
                "source-edition:synthetic:episode-1",
                "source-v1",
                1,
                "episodes/episode-1.md",
                "b" * 64,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline._stage_trace = {
                "translation": {
                    "status": "completed",
                    "input_sha256": hashlib.sha256(
                        "secret source text".encode("utf-8")
                    ).hexdigest(),
                    "output_sha256": hashlib.sha256(
                        "secret translated text".encode("utf-8")
                    ).hexdigest(),
                    "model": "synthetic-model",
                }
            }

            with (
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "TRANSLATION_RUN_ID", "a" * 32),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
            ):
                pipeline._write_stage_report(
                    spec,
                    status="failed",
                    failure_stage="translation",
                    error_type="ValueError",
                )
                pipeline._stage_trace["translation"]["status"] = "completed"
                pipeline._write_stage_report(spec, status="completed")

            report_path = (
                root
                / "Workflow"
                / "Runs"
                / ("a" * 32)
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
                    + ".json"
                )
            )
            self.assertTrue(report_path.is_file())
            report_text = report_path.read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["run_id"], "a" * 32)
            self.assertEqual(report["work_id"], "synthetic-work")
            self.assertEqual(report["episode"]["source_sha256"], "b" * 64)
            self.assertEqual(len(report["attempts"]), 2)
            self.assertEqual(report["attempts"][0]["status"], "failed")
            self.assertEqual(
                report["attempts"][0]["failure_stage"], "translation"
            )
            self.assertEqual(report["attempts"][0]["error_type"], "ValueError")
            self.assertEqual(report["attempts"][1]["status"], "completed")
            self.assertNotIn("secret source text", report_text)
            self.assertNotIn("secret translated text", report_text)
            self.assertNotIn("prompt", report_text.lower())

    def test_formal_stage_report_recovery_fills_missing_report_without_rerun(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "Workflow" / "Runs" / ("a" * 32) / "Drafts"
            output_dir.mkdir(parents=True)
            spec = ChapterSpec(
                "episode.md",
                "episode.md",
                "source-edition:synthetic:episode-1",
                "source-v1",
                1,
                "episode.md",
                "b" * 64,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline._stage_trace = {"translation": {"status": "completed"}}

            with (
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "TRANSLATION_RUN_ID", "a" * 32),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
            ):
                pipeline._ensure_recovered_stage_report(
                    spec,
                    reason="verified_output_missing_stage_report",
                )
                pipeline._ensure_recovered_stage_report(
                    spec,
                    reason="should_not_append",
                )

            report_path = (
                root
                / "Workflow"
                / "Runs"
                / ("a" * 32)
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
                    + ".json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["attempts"]), 1)
            self.assertEqual(report["attempts"][0]["status"], "recovered")
            self.assertEqual(
                report["attempts"][0]["recovery_reason"],
                "verified_output_missing_stage_report",
            )
            self.assertEqual(report["attempts"][0]["stages"], {})

    def test_formal_stage_report_appends_recovery_after_failed_commit_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "Workflow" / "Runs" / ("a" * 32) / "Drafts"
            output_dir.mkdir(parents=True)
            spec = ChapterSpec(
                "episode.md",
                "episode.md",
                "source-edition:synthetic:episode-1",
                "source-v1",
                1,
                "episode.md",
                "b" * 64,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline._stage_trace = {}

            with (
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "TRANSLATION_RUN_ID", "a" * 32),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
            ):
                pipeline._write_stage_report(
                    spec,
                    status="failed",
                    failure_stage="commit",
                    error_type="OSError",
                )
                pipeline._ensure_recovered_stage_report(
                    spec,
                    reason="committed_output_recovered",
                )
                pipeline._ensure_recovered_stage_report(
                    spec,
                    reason="should_not_duplicate",
                )

            report_path = (
                root
                / "Workflow"
                / "Runs"
                / ("a" * 32)
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
                    + ".json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["status"] for item in report["attempts"]],
                ["failed", "recovered"],
            )
            self.assertEqual(
                report["attempts"][-1]["recovery_reason"],
                "committed_output_recovered",
            )

    def test_formal_stage_report_preserves_malformed_existing_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "Workflow" / "Runs" / ("a" * 32) / "Drafts"
            output_dir.mkdir(parents=True)
            reports_root = output_dir.parent / "StageReports"
            reports_root.mkdir(parents=True)
            spec = ChapterSpec(
                "episode.md",
                "episode.md",
                "source-edition:synthetic:episode-1",
                "source-v1",
                1,
                "episode.md",
                "b" * 64,
            )
            report_path = reports_root / (
                "episode-"
                + hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
                + ".json"
            )
            report_path.write_text("{invalid report", encoding="utf-8")
            original_bytes = report_path.read_bytes()
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline._stage_trace = {}

            with (
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "TRANSLATION_RUN_ID", "a" * 32),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
            ):
                with self.assertRaises(json.JSONDecodeError):
                    pipeline._write_stage_report(spec, status="completed")

            self.assertEqual(report_path.read_bytes(), original_bytes)

    def _write_versioned_source(self, raw_dir: Path, source_text: str, version_id: str):
        raw_dir.mkdir(parents=True, exist_ok=True)
        source_path = raw_dir / "chapter.md"
        source_path.write_bytes(source_text.encode("utf-8"))
        raw_source_path = raw_dir / "raw_sources" / "chapter.txt"
        raw_source_path.parent.mkdir()
        raw_source_path.write_bytes(source_text.encode("utf-8"))
        append_artifact(
            raw_dir / "source_manifest.json",
            {
                "artifact_id": "episode-1-raw",
                "version_id": f"{version_id}-raw",
                "kind": "raw_source",
                "content_sha256": hashlib.sha256(
                    source_text.encode("utf-8")
                ).hexdigest(),
                "relative_path": "raw_sources/chapter.txt",
                "parent_version_ids": [],
            },
        )
        append_artifact(
            raw_dir / "source_manifest.json",
            {
                "artifact_id": "episode-1-normalized",
                "version_id": version_id,
                "kind": "normalized_source",
                "content_sha256": hashlib.sha256(
                    source_text.encode("utf-8")
                ).hexdigest(),
                "relative_path": "chapter.md",
                "parent_version_ids": [f"{version_id}-raw"],
            },
        )
        return source_path

    async def test_versioned_run_preserves_and_blocks_stale_existing_translation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            output_dir.mkdir()
            current_text = "current source"
            output_path = output_dir / "episode-1.md"
            output_path.write_text("older translation", encoding="utf-8")
            self._write_versioned_source(raw_dir, current_text, "normalized-v2")
            old_raw = "previous source"
            old_translation = "older translation"
            tm_data = {
                "chapters": {
                    "episode-1": [
                        {"raw": old_raw, "translated": old_translation}
                    ]
                },
                "source_provenance": {
                    "episode-1": {
                        "raw_file": "chapter.md",
                        "raw_sha256": hashlib.sha256(
                            old_raw.encode("utf-8")
                        ).hexdigest(),
                        "translation_file": "episode-1.md",
                        "translation_sha256": hashlib.sha256(
                            old_translation.encode("utf-8")
                        ).hexdigest(),
                        "source_version_id": "normalized-v1",
                    }
                },
            }
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data=tm_data,
                update_translation_memory=Mock(),
            )
            pipeline._build_run_context = AsyncMock()
            pipeline._run_context_annotation = AsyncMock()
            pipeline._run_translation_phase = AsyncMock()
            pipeline._run_refinement_loop = AsyncMock()
            spec = ChapterSpec(
                "chapter.md",
                "episode-1.md",
                "episode-1",
                "normalized-v2",
                1,
            )

            with (
                patch.object(Config, "RAW_DIR", str(raw_dir)),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(
                    Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"
                ),
            ):
                with self.assertRaisesRegex(
                    FileExistsError, "does not match the current source version"
                ):
                    await pipeline.run_chapter(spec)

            self.assertEqual(
                output_path.read_text(encoding="utf-8"), old_translation
            )
            pipeline.rag.update_translation_memory.assert_not_called()
            pipeline._build_run_context.assert_not_awaited()

    async def test_versioned_run_skips_existing_translation_verified_for_current_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            output_dir = root / "translated"
            output_dir.mkdir()
            source_text = "current source one\n\ncurrent source two"
            translation_text = "current translation one\n\ncurrent translation two"
            self._write_versioned_source(raw_dir, source_text, "normalized-v2")
            spec = ChapterSpec(
                "chapter.md",
                "episode-1.md",
                "episode-1",
                "normalized-v2",
                1,
            )
            tm_data = {"chapters": {}, "source_provenance": {}}

            def update_translation_memory(
                tm_key, pairs, *, source_provenance, expected_tm_sha256=None
            ):
                tm_data["chapters"][tm_key] = pairs
                tm_data["source_provenance"][tm_key] = source_provenance

            rag = SimpleNamespace(
                tm_data=tm_data,
                update_translation_memory=update_translation_memory,
            )
            commit_chapter_translation(
                str(output_dir),
                source_text,
                spec,
                translation_text,
                rag,
                lambda _raw, _translation: None,
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = rag
            pipeline._build_run_context = AsyncMock()
            pipeline._run_context_annotation = AsyncMock()
            pipeline._run_translation_phase = AsyncMock()
            pipeline._run_refinement_loop = AsyncMock()

            with (
                patch.object(Config, "RAW_DIR", str(raw_dir)),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(
                    Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"
                ),
            ):
                await pipeline.run_chapter(spec)

            self.assertEqual(
                (output_dir / "episode-1.md").read_text(encoding="utf-8"),
                translation_text,
            )
            pipeline._build_run_context.assert_not_awaited()

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

    async def test_formal_project_blocks_severe_proofreading_before_polish(self):
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

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch.object(Config, "STRICT_REFLECTION_MODE", False),
            patch("pipeline.UnifiedAgent", return_value=proofreader) as factory,
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "severe proofreading issues"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(factory.call_count, 1)
        proofreader.call.assert_awaited_once()
        self.assertEqual(
            pipeline._stage_trace["proofreading"][0]["metadata"][
                "reported_severity"
            ],
            "severe",
        )
        self.assertEqual(pipeline._active_refinement_stage, "proofreading")

    async def test_refinement_trace_separates_proofreading_reflection_and_polishing(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader_first = Mock()
        proofreader_first.call = AsyncMock(
            return_value={
                "severity": "severe",
                "critique": "SYNTHETIC_PRIVATE_CRITIQUE",
                "corrected_text": ["SYNTHETIC_PROOFREAD"],
            }
        )
        reflection = Mock()
        reflection.call = AsyncMock(
            return_value={"translated_paragraphs": ["SYNTHETIC_REFLECTION"]}
        )
        proofreader_second = Mock()
        proofreader_second.call = AsyncMock(
            return_value={
                "severity": "minor",
                "critique": "",
                "corrected_text": ["SYNTHETIC_CORRECTED"],
            }
        )
        polisher = Mock()
        polisher.call = AsyncMock(
            return_value={"polished_paragraphs": ["SYNTHETIC_POLISHED"]}
        )

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", False),
            patch.object(Config, "STRICT_REFLECTION_MODE", True),
            patch(
                "pipeline.UnifiedAgent",
                side_effect=[
                    proofreader_first,
                    reflection,
                    proofreader_second,
                    polisher,
                ],
            ),
        ):
            result = await pipeline._run_refinement_loop(
                "SYNTHETIC_SOURCE",
                ["SYNTHETIC_INITIAL"],
                "",
                [],
            )

        self.assertEqual(result, ["SYNTHETIC_POLISHED"])
        trace = pipeline._stage_trace
        self.assertEqual(
            [item["status"] for item in trace["proofreading"]],
            ["completed", "completed"],
        )
        self.assertEqual(
            [item["metadata"]["attempt"] for item in trace["proofreading"]],
            [1, 2],
        )
        self.assertEqual(
            trace["proofreading"][0]["metadata"]["reported_severity"],
            "severe",
        )
        self.assertEqual(trace["reflection"][0]["status"], "completed")
        self.assertEqual(
            trace["reflection"][0]["metadata"]["attempt"], 1
        )
        self.assertEqual(trace["polishing"][0]["status"], "completed")
        self.assertEqual(
            trace["polishing"][0]["metadata"]["attempt"], 1
        )
        trace_text = json.dumps(trace, ensure_ascii=False)
        for secret in (
            "SYNTHETIC_PRIVATE_CRITIQUE",
            "SYNTHETIC_SOURCE",
            "SYNTHETIC_POLISHED",
        ):
            self.assertNotIn(secret, trace_text)

    async def test_refinement_trace_marks_provider_failure_by_stage(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            side_effect=RuntimeError("synthetic provider failure")
        )

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch.object(Config, "STRICT_REFLECTION_MODE", False),
            patch("pipeline.UnifiedAgent", return_value=proofreader),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic provider failure"):
                await pipeline._run_refinement_loop(
                    "synthetic source", ["synthetic translation"], "", []
                )

        self.assertEqual(
            pipeline._stage_trace["proofreading"][0]["status"], "failed"
        )
        self.assertEqual(pipeline._active_refinement_stage, "proofreading")

    async def test_formal_project_blocks_after_strict_reflection_budget(self):
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
        translator = Mock()
        translator.call = AsyncMock(
            return_value={"translated_paragraphs": ["retry translation"]}
        )
        agents = [proofreader, translator, proofreader, translator, proofreader]

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch.object(Config, "STRICT_REFLECTION_MODE", True),
            patch(
                "pipeline.UnifiedAgent", side_effect=agents
            ) as factory,
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "severe proofreading issues"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(factory.call_count, 5)
        self.assertEqual(proofreader.call.await_count, 3)
        self.assertEqual(translator.call.await_count, 2)

    async def test_formal_project_rejects_invalid_proofread_contract(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            return_value={
                "severity": "none",
                "corrected_text": ["untrusted replacement"],
            }
        )

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch("pipeline.UnifiedAgent", return_value=proofreader) as factory,
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "proofreader response"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(factory.call_count, 1)

    async def test_formal_project_rejects_unreadable_proofread_response(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        proofreader = Mock()
        proofreader.call = AsyncMock(
            side_effect=ResponseContractError("synthetic malformed response")
        )

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch("pipeline.UnifiedAgent", return_value=proofreader) as factory,
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "proofreader response"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(factory.call_count, 1)

    async def test_formal_project_rejects_invalid_reflection_response(self):
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
        translator = Mock()
        translator.call = AsyncMock(return_value={"unexpected": ["retry"]})

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch.object(Config, "STRICT_REFLECTION_MODE", True),
            patch(
                "pipeline.UnifiedAgent",
                side_effect=[proofreader, translator],
            ) as factory,
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "reflection translation response"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

        self.assertEqual(factory.call_count, 2)

    async def test_formal_project_rejects_polisher_contract_fallback(self):
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
            side_effect=ResponseContractError("synthetic malformed response")
        )

        with (
            patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
            patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]),
        ):
            with self.assertRaisesRegex(
                TranslationQualityGateError, "polisher response"
            ):
                await pipeline._run_refinement_loop(
                    "source", ["initial translation"], "", []
                )

    async def test_formal_project_gate_failure_does_not_write_translation_or_tm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            run_id = "c" * 32
            output_dir = root / "Workflow" / "Runs" / run_id / "Drafts"
            raw_dir.mkdir()
            (raw_dir / "chapter.md").write_text("source paragraph", encoding="utf-8")
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
                return_value=["initial translation"]
            )
            pipeline._get_agent_instruction = Mock(return_value="")
            proofreader = Mock()
            proofreader.call = AsyncMock(
                return_value={
                    "severity": "severe",
                    "critique": "synthetic critique",
                    "corrected_text": ["proofread translation"],
                }
            )

            with (
                patch.object(Config, "RAW_DIR", str(raw_dir)),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "STRICT_REFLECTION_MODE", False),
                patch.object(Config, "TRANSLATION_RUN_ID", run_id),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
                patch("pipeline.UnifiedAgent", return_value=proofreader),
            ):
                with self.assertRaises(
                    TranslationQualityGateError
                ) as raised:
                    await pipeline.run_chapter(
                        ChapterSpec(
                            "chapter.md",
                            "chapter.md",
                            "chapter.md",
                            chapter_position=7,
                        )
                    )

            self.assertEqual(raised.exception.chapter_position, 7)
            self.assertFalse((output_dir / "chapter.md").exists())
            pipeline.rag.update_translation_memory.assert_not_called()
            report_path = (
                output_dir.parent
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(b"chapter.md").hexdigest()[:32]
                    + ".json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["attempts"][0]["status"], "failed")
            self.assertEqual(
                report["attempts"][0]["failure_stage"], "proofreading"
            )

    async def test_formal_project_polisher_gate_does_not_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            run_id = "d" * 32
            output_dir = root / "Workflow" / "Runs" / run_id / "Drafts"
            raw_dir.mkdir()
            (raw_dir / "chapter.md").write_text("source paragraph", encoding="utf-8")
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
                return_value=["initial translation"]
            )
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
                side_effect=ResponseContractError("synthetic malformed response")
            )

            with (
                patch.object(Config, "RAW_DIR", str(raw_dir)),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "STRICT_REFLECTION_MODE", False),
                patch.object(Config, "TRANSLATION_RUN_ID", run_id),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
                patch("pipeline.UnifiedAgent", side_effect=[proofreader, polisher]),
            ):
                with self.assertRaisesRegex(
                    TranslationQualityGateError, "polisher response"
                ) as raised:
                    await pipeline.run_chapter(
                        ChapterSpec(
                            "chapter.md",
                            "chapter.md",
                            "chapter.md",
                            chapter_position=7,
                        )
                    )

            self.assertEqual(raised.exception.chapter_position, 7)
            self.assertFalse((output_dir / "chapter.md").exists())
            pipeline.rag.update_translation_memory.assert_not_called()
            report_path = (
                output_dir.parent
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(b"chapter.md").hexdigest()[:32]
                    + ".json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["attempts"][0]["status"], "failed")
            self.assertEqual(
                report["attempts"][0]["failure_stage"], "polishing"
            )

    async def test_run_chapter_refuses_source_changed_during_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"
            output_dir = Path(temp_dir) / "translated"
            raw_dir.mkdir()
            raw_path = raw_dir / "第1話.md"
            raw_path.write_text("source paragraph", encoding="utf-8")
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
                return_value=["translated paragraph"]
            )

            async def change_source_before_commit(
                raw_text,
                raw_translation_list,
                static_context,
                glossary_matches,
                annotated_context,
            ):
                raw_path.write_text("changed source paragraph", encoding="utf-8")
                return ["translated paragraph"]

            pipeline._run_refinement_loop = AsyncMock(
                side_effect=change_source_before_commit
            )

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    with self.assertRaisesRegex(
                        ValueError, "changed during processing"
                    ):
                        await pipeline.run_chapter("第1話.md")

            self.assertFalse((output_dir / "第1話.md").exists())
            pipeline.rag.update_translation_memory.assert_not_called()

    def test_aligned_paragraphs_trim_boundary_whitespace_and_reject_blank_lines(self):
        target = ["  translated text  "]
        require_aligned_paragraphs(["source"], target, "Test")
        self.assertEqual(target, ["translated text"])

        unicode_indentation = ["　translated text", "\u00a0translated text"]
        require_aligned_paragraphs(
            ["source one", "source two"], unicode_indentation, "Test"
        )
        self.assertEqual(
            unicode_indentation,
            ["　translated text", "\u00a0translated text"],
        )

        with self.assertRaisesRegex(ValueError, "multiple paragraphs at index 1"):
            require_aligned_paragraphs(
                ["source"], ["first\n\nsecond"], "Test"
            )

    def test_chapter_number_uses_filename_not_parent_directory(self):
        self.assertEqual(extract_chapter_num("Volume 2/chapter10.md"), 10.0)
        self.assertEqual(extract_chapter_num(r"Volume 2\chapter10.md"), 10.0)

    async def test_tm_persistence_failure_recovers_from_journal_on_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={"chapters": {}},
                update_translation_memory=Mock(
                    side_effect=[OSError("disk full"), None]
                ),
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

            pipeline.rag.update_translation_memory.assert_called()
            self.assertEqual(pipeline.rag.update_translation_memory.call_count, 2)
            warning.assert_not_called()
            pipeline._build_run_context.assert_awaited_once()
            pipeline._run_context_annotation.assert_awaited_once()
            pipeline._run_translation_phase.assert_awaited_once()
            pipeline._run_refinement_loop.assert_awaited_once()
            self.assertEqual(list(output_dir.glob(".codex-chapter-transaction-*.json")), [])

    async def test_tm_failure_recovery_commits_with_real_rag_engine(self):
        from rag_engine import RAGEngine

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
            tm_path = root / "translation_memory.json"
            rag = RAGEngine(
                str(tm_path),
                str(root / "Glossary.json"),
                str(root / "guidelines.txt"),
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = rag
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
                    with patch(
                        "rag_engine.RAGEngine._generate_embedding_sync",
                        return_value=[0.5],
                    ):
                        with patch(
                            "rag_engine.write_bytes_atomically",
                            side_effect=OSError("disk full"),
                        ):
                            with self.assertRaisesRegex(OSError, "disk full"):
                                await pipeline.run_chapter("第1話.md")

                        self.assertTrue((output_dir / "第1話.md").is_file())
                        self.assertEqual(rag.tm_data, {"chapters": {}})
                        await pipeline.run_chapter("第1話.md")

            with tm_path.open("r", encoding="utf-8") as stream:
                persisted_tm = json.load(stream)
            self.assertEqual(rag.tm_data, persisted_tm)
            self.assertEqual(
                persisted_tm["chapters"]["第1話.md"][0]["translated"],
                "translated paragraph",
            )
            self.assertEqual(
                persisted_tm["source_provenance"]["第1話.md"][
                    "translation_file"
                ],
                "第1話.md",
            )
            self.assertEqual(
                list(output_dir.glob(".codex-chapter-transaction-*.json")), []
            )
            pipeline._run_translation_phase.assert_awaited_once()

    async def test_embedding_failure_keeps_chapter_transaction_for_retry(self):
        from rag_engine import RAGEngine

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            raw_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
            tm_path = root / "translation_memory.json"
            rag = RAGEngine(
                str(tm_path),
                str(root / "Glossary.json"),
                str(root / "guidelines.txt"),
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = rag
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
                    with patch(
                        "rag_engine.RAGEngine._generate_embedding_sync",
                        side_effect=[
                            RuntimeError("SYNTHETIC_PRIVATE_ERROR"),
                            [0.5],
                        ],
                    ) as embed:
                        with self.assertRaisesRegex(RuntimeError, "TM update was aborted") as raised:
                            await pipeline.run_chapter("第1話.md")

                        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", str(raised.exception))
                        output_path = output_dir / "第1話.md"
                        self.assertEqual(
                            output_path.read_text(encoding="utf-8"),
                            "translated paragraph",
                        )
                        self.assertEqual(rag.tm_data, {"chapters": {}})
                        self.assertTrue(
                            list(output_dir.glob(".codex-chapter-transaction-*.json"))
                        )

                        await pipeline.run_chapter("第1話.md")

            self.assertEqual(embed.call_count, 2)
            self.assertEqual(pipeline._run_translation_phase.await_count, 1)
            self.assertEqual(pipeline._run_refinement_loop.await_count, 1)
            self.assertIn("第1話.md", rag.tm_data["chapters"])
            self.assertFalse(
                list(output_dir.glob(".codex-chapter-transaction-*.json"))
            )

    async def test_pending_chapter_transaction_refuses_changed_source(self):
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
                    (raw_dir / "第1話.md").write_text(
                        "changed source paragraph", encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ValueError, "hashes do not match"):
                        await pipeline.run_chapter("第1話.md")

            pipeline.rag.update_translation_memory.assert_called_once()
            self.assertEqual(
                (output_dir / "第1話.md").read_text(encoding="utf-8"),
                "translated paragraph",
            )
            self.assertEqual(
                len(list(output_dir.glob(".codex-chapter-transaction-*.json"))),
                1,
            )

    async def test_pending_chapter_transaction_does_not_overwrite_changed_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
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
                    output_path.write_text("translated", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "differs from its recorded"):
                        await pipeline.run_chapter("第1話.md")

            pipeline.rag.update_translation_memory.assert_called_once()
            self.assertEqual(output_path.read_text(encoding="utf-8"), "translated")

    async def test_pending_chapter_transaction_preserves_shortened_output_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
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
                    output_path.write_text("translated", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "differs from its recorded"):
                        await pipeline.run_chapter("第1話.md")

            self.assertEqual(output_path.read_text(encoding="utf-8"), "translated")
            pipeline.rag.update_translation_memory.assert_called_once()

    async def test_output_publish_interruption_recovers_from_pending_transaction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
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
                return_value=["translated paragraph"]
            )
            pipeline._run_refinement_loop = AsyncMock(
                return_value=["translated paragraph"]
            )

            original_link = os.link
            link_calls = 0

            def interrupted_publish(source, destination):
                nonlocal link_calls
                link_calls += 1
                if link_calls == 2:
                    raise OSError("simulated process interruption")
                return original_link(source, destination)

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    with patch(
                        "chapter_transaction.os.link",
                        side_effect=interrupted_publish,
                    ):
                        with self.assertRaisesRegex(
                            OSError, "simulated process interruption"
                        ):
                            await pipeline.run_chapter("第1話.md")

                    output_path = output_dir / "第1話.md"
                    self.assertFalse(output_path.exists())
                    await pipeline.run_chapter("第1話.md")

            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "translated paragraph",
            )
            pipeline.rag.update_translation_memory.assert_called_once()
            pipeline._build_run_context.assert_awaited_once()
            self.assertEqual(
                list(output_dir.glob(".codex-chapter-transaction-*.json")), []
            )

    async def test_pending_chapter_transaction_is_found_after_tm_key_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
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
            original_spec = ChapterSpec(
                "第1話.md", "第1話.md", "old-tm-key"
            )
            changed_spec = ChapterSpec(
                "第1話.md", "第1話.md", "new-tm-key"
            )

            with patch.object(Config, "RAW_DIR", str(raw_dir)):
                with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        await pipeline.run_chapter(original_spec)
                    with self.assertRaisesRegex(
                        ValueError, "does not match the current chapter map"
                    ):
                        await pipeline.run_chapter(changed_spec)

            pipeline.rag.update_translation_memory.assert_called_once()
            self.assertEqual(
                (output_dir / "第1話.md").read_text(encoding="utf-8"),
                "translated paragraph",
            )
            self.assertEqual(
                len(list(output_dir.glob(".codex-chapter-transaction-*.json"))),
                1,
            )

    async def test_empty_output_after_pending_transaction_is_preserved_as_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "生肉"
            output_dir = Path(temp_dir) / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "第1話.md").write_text("source paragraph", encoding="utf-8")
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = SimpleNamespace(
                tm_data={"chapters": {}},
                update_translation_memory=Mock(
                    side_effect=[OSError("disk full"), None]
                ),
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
                    output_path.write_bytes(b"")
                    with self.assertRaisesRegex(
                        ValueError, "differs from its recorded result"
                    ):
                        await pipeline.run_chapter("第1話.md")

            self.assertEqual(output_path.read_bytes(), b"")
            pipeline.rag.update_translation_memory.assert_called_once()
            self.assertEqual(
                len(list(output_dir.glob(".codex-chapter-transaction-*.json"))),
                1,
            )

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

    async def test_empty_versioned_chapter_commits_and_resumes_without_provider_calls(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "RAWs_AI"
            raw_dir.mkdir()
            source_path = raw_dir / "episodes" / "empty.md"
            source_path.parent.mkdir()
            source_path.write_bytes(b"")
            run_id = "a" * 32
            run_root = root / "Workflow" / "Runs" / run_id
            output_dir = run_root / "Drafts"
            (run_root / "StageReports").mkdir(parents=True)
            output_dir.mkdir()
            spec = ChapterSpec(
                "episodes/empty.md",
                "episode-0001-empty-zh.md",
                "source-edition:synthetic:empty",
                "source-v1",
                1,
            )
            rag = SimpleNamespace(
                tm_data={"chapters": {}, "source_provenance": {}}
            )

            def update_translation_memory(
                key, pairs, *, source_provenance, expected_tm_sha256=None
            ):
                rag.tm_data["chapters"][key] = pairs
                rag.tm_data["source_provenance"][key] = source_provenance

            rag.update_translation_memory = Mock(
                side_effect=update_translation_memory
            )
            pipeline = TranslationPipeline.__new__(TranslationPipeline)
            pipeline.rag = rag
            pipeline._verify_chapter_source_snapshot = Mock()

            with (
                patch.object(Config, "RAW_DIR", str(raw_dir)),
                patch.object(Config, "OUTPUT_DIR", str(output_dir)),
                patch.object(Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"),
                patch.object(Config, "REQUIRE_REVIEWED_PUBLICATION", True),
                patch.object(Config, "TRANSLATION_RUN_ID", run_id),
                patch.object(
                    Config,
                    "EXPECTED_BOOK_BUNDLE",
                    {"work_id": "synthetic-work"},
                ),
            ):
                await pipeline.run_chapter(spec)
                await pipeline.run_chapter(spec)

            self.assertEqual((output_dir / spec.translation_file).read_bytes(), b"")
            self.assertEqual(rag.tm_data["chapters"][spec.tm_key], [])
            self.assertEqual(
                rag.tm_data["source_provenance"][spec.tm_key][
                    "source_version_id"
                ],
                "source-v1",
            )
            rag.update_translation_memory.assert_called_once()
            self.assertEqual(
                list(output_dir.glob(".codex-chapter-transaction-*.json")),
                [],
            )
            report_path = (
                run_root
                / "StageReports"
                / (
                    "episode-"
                    + hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
                    + ".json"
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["attempts"]), 1)
            self.assertEqual(report["attempts"][0]["status"], "completed")
            self.assertEqual(
                set(report["attempts"][0]["stages"]),
                {"source_validation", "commit"},
            )

    async def test_annotation_phase_preserves_valid_structured_records(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        annotation = {
            "paragraph": "source paragraph",
            "speaker": "旁白",
            "context_hint": "",
        }
        agent = Mock()
        agent.call = AsyncMock(return_value={"annotated_paragraphs": [annotation]})

        with patch("pipeline.UnifiedAgent", return_value=agent) as agent_factory:
            result = await pipeline._run_context_annotation("source paragraph", "")

        self.assertEqual(result, [annotation])
        self.assertEqual(
            agent_factory.call_args.kwargs["data_categories"],
            ("source_text", "book_knowledge"),
        )
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

    async def test_translation_phase_requests_only_source_and_book_knowledge(self):
        pipeline = TranslationPipeline.__new__(TranslationPipeline)
        pipeline._get_agent_instruction = Mock(return_value="")
        fake_agent = Mock()
        fake_agent.call = AsyncMock(
            return_value={"translated_paragraphs": ["translated"]}
        )

        with patch("pipeline.UnifiedAgent", return_value=fake_agent) as agent_factory:
            result = await pipeline._run_translation_phase("source", "", [])

        self.assertEqual(result, ["translated"])
        self.assertEqual(
            agent_factory.call_args.kwargs["data_categories"],
            ("source_text", "book_knowledge"),
        )

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
