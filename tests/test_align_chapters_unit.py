# tests/test_align_chapters_unit.py
# Unit tests for paragraph alignment strategies in scripts/align_chapters.py.
# Compliant with Australian English spelling conventions.

import unittest
from scripts.align_chapters import (
    is_translator_note,
    is_dialogue_anchor,
    get_anchor_type,
    check_anchors_match,
    align_narrative_block,
    align_anchor_guided,
    gc_cost,
    gale_church_align,
    align_chapter
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


if __name__ == "__main__":
    unittest.main()
