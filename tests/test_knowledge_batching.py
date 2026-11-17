import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tokenizers import Tokenizer, models, pre_tokenizers

from knowledge_batching import (
    BatchBudgetError,
    BatchCountError,
    SourceParagraph,
    count_message_tokens,
    load_tokenizer_json,
    plan_paragraph_batches,
    validate_batch_budget,
)


class CharacterTokenizer:
    def encode(self, text):
        return SimpleNamespace(ids=list(text))


class TestKnowledgeBatching(unittest.TestCase):
    def test_loads_and_hashes_a_bounded_local_tokenizer_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tokenizer_path = Path(temp_dir) / "tokenizer.json"
            tokenizer = Tokenizer(
                models.WordLevel(
                    {"[UNK]": 0, "system": 1, "user": 2, "hello": 3},
                    unk_token="[UNK]",
                )
            )
            tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
            tokenizer.save(str(tokenizer_path))

            loaded, digest = load_tokenizer_json(str(tokenizer_path))

            self.assertEqual(len(digest), 64)
            self.assertEqual(count_message_tokens(loaded, "system", "hello user"), 3)

    def test_budget_reserves_output_safety_and_message_overhead(self):
        limit = validate_batch_budget(
            context_window_tokens=4096,
            max_output_tokens=1024,
            safety_margin_tokens=256,
            message_overhead_tokens=64,
        )

        self.assertEqual(limit, 2816)
        with self.assertRaises(BatchBudgetError):
            validate_batch_budget(
                context_window_tokens=100,
                max_output_tokens=80,
                safety_margin_tokens=20,
                message_overhead_tokens=1,
            )

    def test_paragraph_batches_cover_order_once_under_token_and_call_limits(self):
        paragraphs = [
            SourceParagraph(
                source_id=f"C0001P{index:05d}",
                filename="chapter.md",
                paragraph_index=index,
                text=letter * 700,
            )
            for index, letter in enumerate(("a", "b", "c"), start=1)
        ]
        batches = plan_paragraph_batches(
            paragraphs,
            tokenizer=CharacterTokenizer(),
            system_text="system",
            render_user_text=lambda rows: "|".join(
                f"{row.source_id}:{row.text}" for row in rows
            ),
            input_token_limit=1500,
            message_overhead_tokens=100,
            max_provider_calls=3,
        )

        source_ids = [
            paragraph.source_id
            for batch in batches
            for paragraph in batch["paragraphs"]
        ]
        self.assertEqual(source_ids, [row.source_id for row in paragraphs])
        self.assertEqual(len(batches), 3)
        self.assertTrue(all(batch["input_tokens"] <= 1500 for batch in batches))

    def test_rejects_an_oversized_paragraph_and_excess_provider_calls(self):
        oversized = [
            SourceParagraph("C0001P00001", "chapter.md", 1, "x" * 1000)
        ]
        with self.assertRaises(BatchBudgetError):
            plan_paragraph_batches(
                oversized,
                tokenizer=CharacterTokenizer(),
                system_text="system",
                render_user_text=lambda rows: "|".join(row.text for row in rows),
                input_token_limit=100,
                message_overhead_tokens=10,
                max_provider_calls=1,
            )

        paragraphs = [
            SourceParagraph(f"C0001P{index:05d}", "chapter.md", index, "x" * 100)
            for index in range(1, 4)
        ]
        with self.assertRaises(BatchCountError):
            plan_paragraph_batches(
                paragraphs,
                tokenizer=CharacterTokenizer(),
                system_text="system",
                render_user_text=lambda rows: "|".join(row.text for row in rows),
                input_token_limit=150,
                message_overhead_tokens=10,
                max_provider_calls=1,
            )


if __name__ == "__main__":
    unittest.main()
