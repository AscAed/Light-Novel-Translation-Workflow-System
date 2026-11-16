import asyncio
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pipeline import Config
from scripts import auto_extract_knowledge
from source_ingestion import source_artifact_id


def make_client(response_text):
    client = SimpleNamespace()
    client.chat = SimpleNamespace()
    client.chat.completions = SimpleNamespace()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=response_text)
                )
            ]
        )
    )
    return client


class TestKnowledgeExtractionUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw_dir = self.root / "raw"
        self.output_dir = self.root / "Knowledge"
        base_url_patch = patch.object(
            Config, "DEEPSEEK_BASE_URL", "http://127.0.0.1:6006/v1"
        )
        base_url_patch.start()
        self.addCleanup(base_url_patch.stop)
        mock_port_patch = patch.dict(os.environ, {"MOCK_SERVER_PORT": ""})
        mock_port_patch.start()
        self.addCleanup(mock_port_patch.stop)
        self.raw_dir.mkdir()
        (self.raw_dir / "第1話.md").write_text(
            "サンプル語はテスト用語です。\n\n第二段落です。",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_knowledge_provenance_records_source_version_id(self):
        content = "Synthetic source paragraph."
        sample_text = f"\n\n--- source.md ---\n\n{content}"
        content_start = sample_text.index(content)
        provenance = auto_extract_knowledge._build_provenance_manifest(
            [
                {
                    "filename": "source.md",
                    "tm_key": "Volume1/source.md",
                    "content": content,
                    "content_start": content_start,
                    "content_end": content_start + len(content),
                    "source_version_id": "source-version-1",
                }
            ],
            sample_text,
            [],
            "synthetic-model",
            "synthetic-provider",
        )

        self.assertEqual(
            provenance["source_files"][0]["source_version_id"],
            "source-version-1",
        )
        self.assertEqual(provenance["producer"]["provider_id"], "synthetic-provider")

    def test_bounded_source_read_accepts_limit_and_normalizes_newlines(self):
        source_path = self.raw_dir / "第1話.md"
        source_path.write_bytes(b"a\r\nb")

        with patch.object(
            auto_extract_knowledge, "_MAX_SOURCE_FILE_BYTES", len(b"a\r\nb")
        ):
            content = auto_extract_knowledge._read_source_chapter(
                str(self.raw_dir), "第1話.md", mapped=False
            )

        self.assertEqual(content, "a\nb")

    def test_bound_source_is_rechecked_after_mapping_validation_before_provider(self):
        source_path = self.raw_dir / "normalized" / "episode-1.md"
        source_path.parent.mkdir()
        original = b"versioned source"
        source_path.write_bytes(original)
        raw_source_path = self.raw_dir / "raw" / "episode-1.txt"
        raw_source_path.parent.mkdir()
        raw_source_path.write_bytes(original)
        (self.raw_dir / "source_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifacts": [
                        {
                            "artifact_id": source_artifact_id(
                                "synthetic-work",
                                "raw_source",
                                "episode-1",
                            ),
                            "version_id": "raw-version-1",
                            "kind": "raw_source",
                            "content_sha256": hashlib.sha256(
                                original
                            ).hexdigest(),
                            "relative_path": "raw/episode-1.txt",
                            "parent_version_ids": [],
                        },
                        {
                            "artifact_id": source_artifact_id(
                                "synthetic-work",
                                "normalized_source",
                                "episode-1",
                            ),
                            "version_id": "version-1",
                            "kind": "normalized_source",
                            "content_sha256": hashlib.sha256(original).hexdigest(),
                            "relative_path": "normalized/episode-1.md",
                            "parent_version_ids": ["raw-version-1"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        chapter_map = [
            {
                "raw_file": "normalized/episode-1.md",
                "translation_file": "episode-1.md",
                "tm_key": "episode-1",
                "source_version_id": "version-1",
            }
        ]
        translation_root = self.root / "translations"
        translation_root.mkdir()
        original_reader = auto_extract_knowledge._read_source_chapter

        def replace_before_read(*args, **kwargs):
            source_path.write_bytes(b"changed source")
            return original_reader(*args, **kwargs)

        with patch.object(Config, "CHAPTER_MAP", chapter_map), patch.object(
            Config, "OUTPUT_DIR", str(translation_root)
        ), patch.object(
            Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"
        ), patch(
            "scripts.auto_extract_knowledge._read_source_chapter",
            side_effect=replace_before_read,
        ), patch(
            "scripts.auto_extract_knowledge.get_openai_client"
        ) as client_factory:
            with self.assertRaisesRegex(ValueError, "changed after source-version"):
                asyncio.run(
                    auto_extract_knowledge.extract_knowledge(
                        str(self.raw_dir), str(self.output_dir)
                    )
                )

        client_factory.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_oversized_source_is_rejected_before_provider_creation(self):
        (self.raw_dir / "第1話.md").write_bytes(b"12345")

        with patch.object(auto_extract_knowledge, "_MAX_SOURCE_FILE_BYTES", 4):
            with patch(
                "scripts.auto_extract_knowledge.get_openai_client"
            ) as client_factory:
                with self.assertRaisesRegex(ValueError, "size limit"):
                    asyncio.run(
                        auto_extract_knowledge.extract_knowledge(
                            str(self.raw_dir), str(self.output_dir)
                        )
                    )

        client_factory.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_unapproved_remote_provider_is_rejected_before_source_read(self):
        with patch.object(
            Config, "DEEPSEEK_BASE_URL", "https://provider.example/v1"
        ):
            with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
                with patch(
                    "scripts.auto_extract_knowledge.get_api_key",
                    return_value="test-key",
                ):
                    with patch(
                        "scripts.auto_extract_knowledge._read_source_chapter"
                    ) as source_reader:
                        with patch(
                            "scripts.auto_extract_knowledge.get_openai_client"
                        ) as client_factory:
                            with self.assertRaisesRegex(
                                PermissionError, "not authorized"
                            ):
                                asyncio.run(
                                    auto_extract_knowledge.extract_knowledge(
                                        str(self.raw_dir), str(self.output_dir)
                                    )
                                )

        source_reader.assert_not_called()
        client_factory.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_missing_remote_provider_key_is_rejected_before_source_read(self):
        with patch.object(
            Config, "DEEPSEEK_BASE_URL", "https://provider.example/v1"
        ):
            with patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"deepseek": frozenset({"source_text"})},
            ):
                with patch(
                    "scripts.auto_extract_knowledge.get_api_key",
                    return_value=None,
                ):
                    with patch(
                        "scripts.auto_extract_knowledge._read_source_chapter"
                    ) as source_reader:
                        with patch(
                            "scripts.auto_extract_knowledge.get_openai_client"
                        ) as client_factory:
                            with self.assertRaisesRegex(
                                RuntimeError, "API key is required"
                            ):
                                asyncio.run(
                                    auto_extract_knowledge.extract_knowledge(
                                        str(self.raw_dir), str(self.output_dir)
                                    )
                                )

        source_reader.assert_not_called()
        client_factory.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_valid_response_creates_only_non_overwriting_drafts(self):
        response = {
            "glossary": [
                {
                    "src": "サンプル語",
                    "dst": "示例词",
                    "info": "测试条目",
                }
            ],
            "summary": "Synthetic chapter summary.",
        }
        client = make_client(json.dumps(response, ensure_ascii=False))

        with patch(
            "scripts.auto_extract_knowledge.get_openai_client",
            return_value=client,
        ) as client_factory:
            with patch(
                "scripts.auto_extract_knowledge.get_api_key",
                return_value=None,
            ):
                asyncio.run(
                    auto_extract_knowledge.extract_knowledge(
                        str(self.raw_dir), str(self.output_dir)
                    )
                )

        glossary_path = self.output_dir / "Glossary_draft.json"
        summary_path = self.output_dir / "STORY_SUMMARY_draft.md"
        provenance_path = self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json"
        self.assertEqual(
            json.loads(glossary_path.read_text(encoding="utf-8")),
            {"サンプル語": "示例词 （测试条目）"},
        )
        self.assertIn(
            "Synthetic chapter summary.",
            summary_path.read_text(encoding="utf-8"),
        )
        self.assertFalse((self.output_dir / "Glossary.json").exists())
        self.assertFalse((self.output_dir / "STORY_SUMMARY.md").exists())
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        self.assertEqual(provenance["schema_version"], 1)
        self.assertEqual(provenance["artifact_status"], "complete")
        self.assertEqual(
            provenance["glossary_evidence"],
            [
                {
                    "src": "サンプル語",
                    "occurrences": [
                        {"chapter": "第1話.md", "paragraph_indices": [1]}
                    ],
                }
            ],
        )
        self.assertEqual(provenance["summary_source_chapters"], ["第1話.md"])
        self.assertEqual(
            provenance["source_files"][0]["source_sha256"],
            hashlib.sha256(
                "サンプル語はテスト用語です。\n\n第二段落です。".encode("utf-8")
            ).hexdigest(),
        )
        client_factory.assert_called_once_with(
            Config.DEEPSEEK_BASE_URL,
            None,
            provider_id="deepseek",
            data_categories={"source_text"},
        )
        client.chat.completions.create.assert_awaited_once()

    def test_extraction_uses_the_configured_model_provider_route(self):
        routes = (
            (
                "gpt-6-luna",
                "JOJO_BASE_URL",
                "jojo",
                "JOJO_API_KEY",
            ),
            (
                "deepseek-v4.1-flash",
                "JYQF_BASE_URL",
                "jyqf",
                "JYQF_API_KEY",
            ),
        )
        response = json.dumps(
            {"glossary": [], "summary": "Synthetic summary."}
        )

        for index, (model, base_url_name, provider_id, api_key_name) in enumerate(
            routes
        ):
            with self.subTest(provider=provider_id):
                client = make_client(response)
                base_url = f"https://{provider_id}.example/v1"
                output_dir = self.root / f"Knowledge-{index}"
                with patch.object(Config, "PROOFREAD_MODEL", model):
                    with patch.object(Config, base_url_name, base_url):
                        with patch.object(
                            Config,
                            "PROVIDER_DATA_POLICY",
                            {provider_id: frozenset({"source_text"})},
                        ):
                            with patch(
                                "scripts.auto_extract_knowledge.get_api_key",
                                return_value=f"synthetic-{provider_id}-key",
                            ) as key_loader:
                                with patch(
                                    "scripts.auto_extract_knowledge.get_openai_client",
                                    return_value=client,
                                ) as client_factory:
                                    asyncio.run(
                                        auto_extract_knowledge.extract_knowledge(
                                            str(self.raw_dir), str(output_dir)
                                        )
                                    )

                key_loader.assert_called_once_with(api_key_name)
                client_factory.assert_called_once_with(
                    base_url,
                    f"synthetic-{provider_id}-key",
                    provider_id=provider_id,
                    data_categories={"source_text"},
                )
                self.assertEqual(
                    client.chat.completions.create.call_args.kwargs["model"],
                    model,
                )
                provenance = json.loads(
                    (
                        output_dir / "KNOWLEDGE_PROVENANCE_draft.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    provenance["producer"]["provider_id"], provider_id
                )

    def test_unsupported_extraction_model_fails_before_source_read(self):
        with patch.object(Config, "PROOFREAD_MODEL", "unsupported-model"):
            with patch(
                "scripts.auto_extract_knowledge._read_source_chapter"
            ) as source_reader:
                with patch(
                    "scripts.auto_extract_knowledge.get_openai_client"
                ) as client_factory:
                    with self.assertRaisesRegex(
                        ValueError, "Unsupported model name"
                    ):
                        asyncio.run(
                            auto_extract_knowledge.extract_knowledge(
                                str(self.raw_dir), str(self.output_dir)
                            )
                        )

        source_reader.assert_not_called()
        client_factory.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_extraction_reads_only_the_explicit_nested_source_mapping(self):
        raw_file = "Volume 2/第3話.md"
        source_text = "合成章节原文。"
        nested_raw = self.raw_dir / "Volume 2"
        nested_translation = self.root / "translated" / "Ntera"
        nested_raw.mkdir()
        nested_translation.mkdir(parents=True)
        (nested_raw / "第3話.md").write_text(source_text, encoding="utf-8")
        response = {
            "glossary": [{"src": "合成", "dst": "synthetic"}],
            "summary": "Synthetic summary.",
        }
        client = make_client(json.dumps(response, ensure_ascii=False))
        chapter_map = [
            {
                "raw_file": raw_file,
                "translation_file": "Ntera/第3話.md",
                "tm_key": "Volume2/第3話.md",
            }
        ]

        with patch.object(Config, "CHAPTER_MAP", chapter_map):
            with patch.object(Config, "OUTPUT_DIR", str(self.root / "translated")):
                with patch(
                    "scripts.auto_extract_knowledge.get_openai_client",
                    return_value=client,
                ):
                    asyncio.run(
                        auto_extract_knowledge.extract_knowledge(
                            str(self.raw_dir), str(self.output_dir)
                        )
                    )

        provenance = json.loads(
            (self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(provenance["summary_source_chapters"], [raw_file])
        self.assertEqual(
            provenance["source_files"][0]["tm_key"], "Volume2/第3話.md"
        )
        self.assertEqual(
            provenance["source_files"][0]["source_sha256"],
            hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )

    def test_malformed_response_does_not_create_draft_files(self):
        invalid_results = (
            [],
            {"summary": "summary without glossary"},
            {"glossary": [], "summary": "   "},
            {"glossary": ["not an object"], "summary": "summary"},
            {
                "glossary": [{"src": "source", "dst": ""}],
                "summary": "summary",
            },
            {
                "glossary": [
                    {"src": "source", "dst": "first"},
                    {"src": "source", "dst": "second"},
                ],
                "summary": "summary",
            },
        )

        for result in invalid_results:
            with self.subTest(result=result):
                client = make_client(json.dumps(result, ensure_ascii=False))
                with patch(
                    "scripts.auto_extract_knowledge.get_openai_client",
                    return_value=client,
                ):
                    with self.assertRaises(ValueError):
                        asyncio.run(
                            auto_extract_knowledge.extract_knowledge(
                                str(self.raw_dir), str(self.output_dir)
                            )
                        )

                self.assertFalse(
                    (self.output_dir / "Glossary_draft.json").exists()
                )
                self.assertFalse(
                    (self.output_dir / "STORY_SUMMARY_draft.md").exists()
                )

    def test_existing_draft_is_never_overwritten_or_sent_to_provider(self):
        self.output_dir.mkdir()
        draft_path = self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json"
        draft_path.write_text("preserve this draft", encoding="utf-8")

        with patch(
            "scripts.auto_extract_knowledge.get_openai_client"
        ) as client_factory:
            with self.assertRaises(FileExistsError):
                asyncio.run(
                    auto_extract_knowledge.extract_knowledge(
                        str(self.raw_dir), str(self.output_dir)
                    )
                )

        self.assertEqual(
            draft_path.read_text(encoding="utf-8"),
            "preserve this draft",
        )
        client_factory.assert_not_called()

    def test_unmatched_glossary_term_is_marked_without_source_occurrences(self):
        response = {
            "glossary": [{"src": "未登場語", "dst": "未登场词"}],
            "summary": "Synthetic chapter summary.",
        }
        client = make_client(json.dumps(response, ensure_ascii=False))

        with patch(
            "scripts.auto_extract_knowledge.get_openai_client",
            return_value=client,
        ):
            asyncio.run(
                auto_extract_knowledge.extract_knowledge(
                    str(self.raw_dir), str(self.output_dir)
                )
            )

        provenance = json.loads(
            (self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            provenance["glossary_evidence"],
            [{"src": "未登場語", "occurrences": []}],
        )

    def test_source_manifest_records_only_text_within_prompt_limit(self):
        raw_text = "サンプル語。\n\n" + ("synthetic " * 3000)
        (self.raw_dir / "第1話.md").write_text(raw_text, encoding="utf-8")
        client = make_client(
            json.dumps(
                {"glossary": [], "summary": "Synthetic summary."},
                ensure_ascii=False,
            )
        )

        with patch(
            "scripts.auto_extract_knowledge.get_openai_client",
            return_value=client,
        ):
            asyncio.run(
                auto_extract_knowledge.extract_knowledge(
                    str(self.raw_dir), str(self.output_dir)
                )
            )

        prompt = client.chat.completions.create.call_args.kwargs["messages"][1][
            "content"
        ]
        prompt_sample = prompt.split("[小说内容]\n", 1)[1]
        provenance = json.loads(
            (self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(prompt_sample), 20000)
        self.assertEqual(
            provenance["prompt_sample_sha256"],
            hashlib.sha256(prompt_sample.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            provenance["source_files"][0]["included_characters"],
            len(prompt_sample) - len("\n\n--- 第1話.md ---\n\n"),
        )

    def test_partial_write_failure_leaves_no_complete_provenance_marker(self):
        response = {
            "glossary": [{"src": "サンプル語", "dst": "示例词"}],
            "summary": "Synthetic chapter summary.",
        }
        client = make_client(json.dumps(response, ensure_ascii=False))
        write_child = auto_extract_knowledge.write_new_child_text

        def fail_summary_write(root, filename, content):
            if filename == "STORY_SUMMARY_draft.md":
                raise OSError("synthetic write failure")
            write_child(root, filename, content)

        with patch(
            "scripts.auto_extract_knowledge.get_openai_client",
            return_value=client,
        ):
            with patch(
                "scripts.auto_extract_knowledge.write_new_child_text",
                side_effect=fail_summary_write,
            ):
                with self.assertRaisesRegex(OSError, "synthetic write failure"):
                    asyncio.run(
                        auto_extract_knowledge.extract_knowledge(
                            str(self.raw_dir), str(self.output_dir)
                        )
                    )

        self.assertTrue((self.output_dir / "Glossary_draft.json").exists())
        self.assertFalse((self.output_dir / "STORY_SUMMARY_draft.md").exists())
        self.assertFalse(
            (self.output_dir / "KNOWLEDGE_PROVENANCE_draft.json").exists()
        )

    def test_no_chapters_returns_without_provider_call(self):
        with patch("scripts.auto_extract_knowledge.get_chapters", return_value=[]):
            with patch(
                "scripts.auto_extract_knowledge.get_openai_client"
            ) as client_factory:
                asyncio.run(
                    auto_extract_knowledge.extract_knowledge(
                        str(self.raw_dir), str(self.output_dir)
                    )
                )

        self.assertFalse(self.output_dir.exists())
        client_factory.assert_not_called()

    def test_provider_preflight_runs_before_chapter_discovery(self):
        with patch.object(
            Config, "DEEPSEEK_BASE_URL", "https://provider.example/v1"
        ):
            with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
                with patch(
                    "scripts.auto_extract_knowledge.get_api_key",
                    return_value="test-key",
                ):
                    with patch(
                        "scripts.auto_extract_knowledge.get_chapters"
                    ) as chapter_scan:
                        with self.assertRaisesRegex(
                            PermissionError, "not authorized"
                        ):
                            asyncio.run(
                                auto_extract_knowledge.extract_knowledge(
                                    str(self.raw_dir), str(self.output_dir)
                                )
                            )

        chapter_scan.assert_not_called()

    def test_cli_error_does_not_print_exception_message(self):
        stderr = io.StringIO()
        with patch("scripts.auto_extract_knowledge.Config.load_config"):
            with patch.object(
                Config, "WORKSPACE_DIR", str(self.root), create=True
            ):
                with patch.object(
                    Config, "RAW_DIR", str(self.raw_dir), create=True
                ):
                    with patch(
                        "scripts.auto_extract_knowledge.extract_knowledge",
                        new_callable=AsyncMock,
                        side_effect=RuntimeError("SYNTHETIC_PRIVATE_ERROR"),
                    ):
                        with redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as raised:
                                auto_extract_knowledge.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("RuntimeError", stderr.getvalue())
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", stderr.getvalue())

    def test_cli_reports_source_limit_without_sensitive_error_text(self):
        stderr = io.StringIO()
        with patch("scripts.auto_extract_knowledge.Config.load_config"):
            with patch.object(
                Config, "WORKSPACE_DIR", str(self.root), create=True
            ):
                with patch.object(
                    Config, "RAW_DIR", str(self.raw_dir), create=True
                ):
                    with patch(
                        "scripts.auto_extract_knowledge.extract_knowledge",
                        new_callable=AsyncMock,
                        side_effect=auto_extract_knowledge._SourceChapterSizeLimitError(
                            "SYNTHETIC_PRIVATE_CHAPTER_NAME"
                        ),
                    ):
                        with redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as raised:
                                auto_extract_knowledge.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("exceeds the configured source read limit", stderr.getvalue())
        self.assertNotIn("SYNTHETIC_PRIVATE_CHAPTER_NAME", stderr.getvalue())
