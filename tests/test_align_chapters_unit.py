# tests/test_align_chapters_unit.py
# Unit tests for paragraph alignment strategies in scripts/align_chapters.py.
# Compliant with Australian English spelling conventions.

import os
import io
import unittest
import json
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from types import ModuleType, SimpleNamespace
import sys
from scripts.align_chapters import (
    is_translator_note,
    is_dialogue_anchor,
    get_anchor_type,
    check_anchors_match,
    align_narrative_block,
    align_anchor_guided,
    gc_cost,
    gale_church_align,
    align_chapter,
    _find_ordered_paragraph_indices,
    generate_embeddings_batched,
    load_existing_tm,
    main as align_main,
)


class TestParagraphAlignmentUnit(unittest.TestCase):

    def test_translator_note_detection(self):
        """Verify that translator notes are correctly identified."""
        self.assertTrue(is_translator_note("（译：这是一个翻译说明）"))
        self.assertTrue(is_translator_note("(注: 解释说明)"))
        self.assertTrue(is_translator_note("（T/N：some translation note）"))
        self.assertFalse(is_translator_note("这只是普通的叙事段落。"))

    def test_dialogue_anchor_detection(self):
        """Verify that paragraphs bounded by quotes are identified as anchors."""
        self.assertTrue(is_dialogue_anchor("「こんにちは！」"))
        self.assertTrue(is_dialogue_anchor("『テスト内容』"))
        self.assertFalse(is_dialogue_anchor("「こんにちは"))
        self.assertFalse(is_dialogue_anchor("テスト内容』"))
        self.assertFalse(is_dialogue_anchor("普通的说实话段落。"))

    def test_anchor_type_retrieval(self):
        """Verify dialogue anchor quote types are categorised correctly."""
        self.assertEqual(get_anchor_type("「こんにちは！」"), "「」")
        self.assertEqual(get_anchor_type("『テスト内容』"), "『』")
        self.assertEqual(get_anchor_type("普通段落"), "")

    def test_anchors_match_validation(self):
        """Verify anchor matching checks count and sequence sequence of types."""
        raw_paras = ["「A」", "『B』", "普通文本"]
        trans_paras = ["「A译」", "『B译』", "翻译文本"]
        self.assertTrue(check_anchors_match(raw_paras, trans_paras))

        mismatched_types = ["『A』", "「B」"]
        self.assertFalse(check_anchors_match(raw_paras, mismatched_types))

        mismatched_counts = ["「A」"]
        self.assertFalse(check_anchors_match(raw_paras, mismatched_counts))

    def test_narrative_block_alignment(self):
        """Verify narrative blocks align 1:1, filter TNs, or merge on mismatch."""
        # 1:1 match
        raw = ["raw1", "raw2"]
        trans = ["trans1", "trans2"]
        self.assertEqual(
            align_narrative_block(raw, trans),
            [("raw1", "trans1"), ("raw2", "trans2")]
        )

        # Mismatch resolved by TN filtering
        trans_with_tn = ["trans1", "（译：注释）", "trans2"]
        self.assertEqual(
            align_narrative_block(raw, trans_with_tn),
            [("raw1", "trans1"), ("raw2", "trans2")]
        )

        # Mismatch requiring merging fallback
        trans_mismatched = ["trans1", "trans2", "trans3"]
        self.assertEqual(
            align_narrative_block(raw, trans_mismatched),
            [("raw1\n\nraw2", "trans1\n\ntrans2\n\ntrans3")]
        )

    def test_anchor_guided_alignment(self):
        """Verify anchor-guided block alignment partitions narrative correctly."""
        raw = ["raw_nav1", "「quote1」", "raw_nav2"]
        trans = ["trans_nav1", "「quote1_trans」", "trans_nav2"]
        expected = [
            ("raw_nav1", "trans_nav1"),
            ("「quote1」", "「quote1_trans」"),
            ("raw_nav2", "trans_nav2")
        ]
        self.assertEqual(align_anchor_guided(raw, trans), expected)

    def test_gc_cost_calculation(self):
        """Verify Gale-Church length cost returns valid float values."""
        self.assertEqual(gc_cost(0, 0), 0.0)
        cost = gc_cost(10, 12)
        self.assertIsInstance(cost, float)
        self.assertTrue(cost >= 0.0)

    def test_gale_church_alignment(self):
        """Verify Gale-Church DP finds correct alignments for splits and merges."""
        raw = ["This is paragraph one.", "This is paragraph two."]
        trans = ["这是段落一。这是段落二。"]
        aligned = gale_church_align(raw, trans)
        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0][0], "This is paragraph one.\n\nThis is paragraph two.")
        self.assertEqual(aligned[0][1], "这是段落一。这是段落二。")

    def test_align_chapter_integration(self):
        """Verify align_chapter switches to correct strategy based on anchors."""
        # Anchors match -> Anchor-guided
        raw = ["raw_nav1", "「quote1」", "raw_nav2"]
        trans = ["trans_nav1", "「quote1_trans」", "trans_nav2"]
        self.assertEqual(len(align_chapter("\n\n".join(raw), "\n\n".join(trans))), 3)

        # Anchors mismatch -> Gale-Church fallback
        raw_mismatch = ["raw_nav1", "「quote1」", "raw_nav2"]
        trans_mismatch = ["trans_nav1", "trans_nav2"]  # no quote
        # Gale-Church should align them
        self.assertTrue(len(align_chapter("\n\n".join(raw_mismatch), "\n\n".join(trans_mismatch))) > 0)

    def test_no_dialogue_anchors_with_mismatched_counts_uses_gale_church(self):
        aligned = align_chapter("原文一\n\n原文二", "译文段落")
        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0], ("原文一\n\n原文二", "译文段落"))

    def test_aligned_text_maps_back_to_ordered_source_paragraph_indices(self):
        indices, next_index = _find_ordered_paragraph_indices(
            ["第一段", "译者注", "第三段"], "第一段\n\n第三段"
        )
        self.assertEqual(indices, [1, 3])
        self.assertEqual(next_index, 3)

        indices, next_index = _find_ordered_paragraph_indices(
            ["第一段"], "不存在的段落"
        )
        self.assertEqual(indices, [])
        self.assertEqual(next_index, 0)

    def test_corrupt_translation_memory_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "translation_memory.json"
            path.write_text("{invalid", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                load_existing_tm(str(path))

            self.assertEqual(path.read_text(encoding="utf-8"), "{invalid")

    def test_translation_memory_requires_chapters_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "translation_memory.json"
            path.write_text('{"entries": []}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "chapters object"):
                load_existing_tm(str(path))

    def test_embedding_count_mismatch_is_rejected(self):
        from pipeline import Config

        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(embeddings=[])
        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")
        types_module.HttpOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        genai_module.Client = Mock(return_value=client)
        google_module.genai = genai_module

        with patch.object(
            Config,
            "PROVIDER_DATA_POLICY",
            {"gemini": frozenset({"source_text"})},
        ):
            with patch.dict(
                sys.modules,
                {
                    "google": google_module,
                    "google.genai": genai_module,
                    "google.genai.types": types_module,
                },
            ):
                with self.assertRaisesRegex(RuntimeError, "count did not match"):
                    generate_embeddings_batched(["raw paragraph"])

    def test_embedding_client_receives_configured_timeout(self):
        from pipeline import Config

        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.5] * 768)]
        )
        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")
        types_module.HttpOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        genai_module.Client = Mock(return_value=client)
        google_module.genai = genai_module

        with patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.genai": genai_module,
                "google.genai.types": types_module,
            },
        ):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(Config, "API_TIMEOUT", 3.5):
                    with patch.object(
                        Config,
                        "PROVIDER_DATA_POLICY",
                        {"gemini": frozenset({"source_text"})},
                    ):
                        result = generate_embeddings_batched(["raw paragraph"])

        self.assertEqual(result, [[0.5] * 768])
        genai_module.Client.assert_called_once_with(
            http_options=SimpleNamespace(timeout=3500)
        )

    def test_external_embedding_is_blocked_without_explicit_data_grant(self):
        from pipeline import Config

        with patch.dict(
            os.environ, {"MOCK_SERVER_PORT": "12345"}, clear=True
        ):
            with patch.object(Config, "PROVIDER_DATA_POLICY", {}):
                with self.assertRaisesRegex(PermissionError, "not authorized"):
                    generate_embeddings_batched(["source paragraph"])

    def test_cli_embedding_error_does_not_print_exception_message(self):
        from pipeline import Config

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "第1話.md").write_text("synthetic source", encoding="utf-8")
            (output_dir / "第1話.md").write_text(
                "synthetic translation", encoding="utf-8"
            )
            stderr = io.StringIO()
            stdout = io.StringIO()
            with patch("sys.argv", ["align_chapters.py"]):
                with patch("pipeline.Config.load_config"):
                    with patch.object(Config, "RAW_DIR", str(raw_dir)):
                        with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                            with patch.object(
                                Config, "TM_PATH", str(root / "translation_memory.json")
                            ):
                                with patch(
                                    "scripts.align_chapters.generate_embeddings_batched",
                                    side_effect=RuntimeError(
                                        "SYNTHETIC_PRIVATE_ERROR"
                                    ),
                                ):
                                    with redirect_stdout(stdout):
                                        with redirect_stderr(stderr):
                                            with self.assertRaises(SystemExit) as raised:
                                                align_main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("RuntimeError", stderr.getvalue())
        self.assertNotIn(
            "SYNTHETIC_PRIVATE_ERROR", stdout.getvalue() + stderr.getvalue()
        )

    def test_cli_rejects_nested_only_raw_chapters_without_reading_tm(self):
        from pipeline import Config

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            (raw_dir / "第一卷").mkdir(parents=True)
            output_dir.mkdir()
            (raw_dir / "第一卷" / "第1話.md").write_text(
                "synthetic source", encoding="utf-8"
            )
            stderr = io.StringIO()
            with patch("sys.argv", ["align_chapters.py"]):
                with patch("pipeline.Config.load_config"):
                    with patch.object(Config, "RAW_DIR", str(raw_dir)):
                        with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                            with patch.object(
                                Config, "TM_PATH", str(root / "translation_memory.json")
                            ):
                                with patch(
                                    "scripts.align_chapters.load_existing_tm"
                                ) as load_tm:
                                    with patch(
                                        "scripts.align_chapters.save_tm"
                                    ) as save_tm:
                                        with redirect_stderr(stderr):
                                            with self.assertRaises(SystemExit) as raised:
                                                align_main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("No Markdown chapters found directly", stderr.getvalue())
        load_tm.assert_not_called()
        save_tm.assert_not_called()

    def test_cli_rejects_all_missing_translations_without_saving_tm(self):
        from pipeline import Config

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            raw_dir.mkdir()
            output_dir.mkdir()
            (raw_dir / "第1話.md").write_text("synthetic source", encoding="utf-8")
            stderr = io.StringIO()
            with patch("sys.argv", ["align_chapters.py"]):
                with patch("pipeline.Config.load_config"):
                    with patch.object(Config, "RAW_DIR", str(raw_dir)):
                        with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                            with patch.object(
                                Config, "TM_PATH", str(root / "translation_memory.json")
                            ):
                                with patch(
                                    "scripts.align_chapters.load_existing_tm",
                                    return_value={"chapters": {}},
                                ):
                                    with patch(
                                        "scripts.align_chapters.save_tm"
                                    ) as save_tm:
                                        with redirect_stderr(stderr):
                                            with self.assertRaises(SystemExit) as raised:
                                                align_main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("No chapters were aligned", stderr.getvalue())
        save_tm.assert_not_called()

    def test_cli_aligns_explicit_nested_mapping_and_uses_tm_key(self):
        from pipeline import Config

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "生肉"
            output_dir = root / "熟肉"
            (raw_dir / "第一卷").mkdir(parents=True)
            (output_dir / "Ntera").mkdir(parents=True)
            (raw_dir / "第一卷" / "第1話.md").write_text(
                "「synthetic source」", encoding="utf-8"
            )
            (output_dir / "Ntera" / "第一話.md").write_text(
                "「synthetic translation」", encoding="utf-8"
            )
            chapter_map = [
                {
                    "raw_file": "第一卷/第1話.md",
                    "translation_file": "Ntera/第一話.md",
                    "tm_key": "Volume1/第1話.md",
                }
            ]
            stdout = io.StringIO()
            with patch("sys.argv", ["align_chapters.py"]):
                with patch("pipeline.Config.load_config"):
                    with patch.object(Config, "RAW_DIR", str(raw_dir)):
                        with patch.object(Config, "OUTPUT_DIR", str(output_dir)):
                            with patch.object(Config, "CHAPTER_MAP", chapter_map):
                                with patch.object(
                                    Config,
                                    "TM_PATH",
                                    str(root / "translation_memory.json"),
                                ):
                                    with patch(
                                        "scripts.align_chapters.load_existing_tm",
                                        return_value={"chapters": {}},
                                    ):
                                        with patch(
                                            "scripts.align_chapters.generate_embeddings_batched",
                                            return_value=[[0.5]],
                                        ):
                                            with patch(
                                                "scripts.align_chapters.save_tm"
                                            ) as save_tm:
                                                with redirect_stdout(stdout):
                                                    with self.assertRaises(
                                                        SystemExit
                                                    ) as raised:
                                                        align_main()

            self.assertEqual(raised.exception.code, 0)
            tm_data = save_tm.call_args.args[1]
            self.assertIn("Volume1/第1話.md", tm_data["chapters"])
            provenance = tm_data["source_provenance"]["Volume1/第1話.md"]
            self.assertEqual(
                provenance["raw_file"], "第一卷/第1話.md"
            )
            self.assertEqual(
                provenance["translation_file"], "Ntera/第一話.md"
            )
            self.assertIn("Successfully aligned chapter", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
