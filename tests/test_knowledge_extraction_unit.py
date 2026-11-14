import asyncio
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pipeline import Config
from scripts import auto_extract_knowledge


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
        self.raw_dir.mkdir()
        (self.raw_dir / "第1話.md").write_text(
            "サンプル語はテスト用語です。\n\n第二段落です。",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

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
