import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from knowledge_ai_review import (
    KNOWLEDGE_REVIEW_SYSTEM_PROMPT,
    build_knowledge_review_candidates,
    candidate_paragraphs,
    render_knowledge_review_prompt,
    validate_knowledge_review_decisions,
)
from knowledge_batching import SourceParagraph
from scripts.review_knowledge_candidates import (
    _execute_review,
    _review_plan,
    main as review_main,
)


class CharacterTokenizer:
    def encode(self, text):
        return SimpleNamespace(ids=list(text))


class KnowledgeAIReviewTests(unittest.TestCase):
    def setUp(self):
        self.paragraphs = {
            "C0001P00001": SourceParagraph(
                source_id="C0001P00001",
                filename="editions/ai/chapter-1.md",
                paragraph_index=1,
                text="Alice said hello.",
            ),
            "C0001P00002": SourceParagraph(
                source_id="C0001P00002",
                filename="editions/ai/chapter-1.md",
                paragraph_index=2,
                text="The old bell rang twice.",
            ),
        }
        self.provenance = {
            "source_files": [
                {
                    "filename": "editions/ai/chapter-1.md",
                    "source_index": 1,
                }
            ],
            "glossary_evidence": [
                {
                    "src": "Alice",
                    "occurrences": [
                        {
                            "chapter": "editions/ai/chapter-1.md",
                            "paragraph_indices": [1],
                        }
                    ],
                }
            ],
            "claim_evidence": [
                {
                    "claim_id": "R001-summary-0001",
                    "category": "summary",
                    "claim_text": "The bell rang twice.",
                    "evidence": [
                        {
                            "source_id": "C0001P00002",
                            "filename": "editions/ai/chapter-1.md",
                            "paragraph_index": 2,
                        }
                    ],
                }
            ],
        }
        self.candidates = build_knowledge_review_candidates(
            {"Alice": "爱丽丝"},
            self.provenance,
            self.paragraphs,
        )

    def test_candidates_bind_glossary_and_claims_to_current_paragraphs(self):
        self.assertEqual(
            [candidate["candidate_id"] for candidate in self.candidates],
            ["G000001", "R001-summary-0001"],
        )
        self.assertEqual(
            self.candidates[0]["evidence"][0]["text"],
            "Alice said hello.",
        )
        self.assertEqual(
            self.candidates[1]["evidence"][0]["source_id"],
            "C0001P00002",
        )

    def test_candidate_builder_rejects_wrong_glossary_location(self):
        wrong_location = {
            **self.provenance,
            "glossary_evidence": [
                {
                    "src": "Alice",
                    "occurrences": [
                        {
                            "chapter": "editions/ai/chapter-1.md",
                            "paragraph_indices": [8],
                        }
                    ],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "current source"):
            build_knowledge_review_candidates(
                {"Alice": "爱丽丝"},
                wrong_location,
                self.paragraphs,
            )

    def test_prompt_treats_candidate_and_source_as_data(self):
        batch = candidate_paragraphs(self.candidates)
        prompt = render_knowledge_review_prompt(batch)
        self.assertIn("Alice said hello.", prompt)
        self.assertIn("候选与引用段落 JSON", prompt)
        self.assertIn("不引用或复述", prompt)
        self.assertIn("忽略", KNOWLEDGE_REVIEW_SYSTEM_PROMPT)

    def test_review_decisions_require_exact_coverage_and_allowed_evidence(self):
        response = {
            "decisions": [
                {
                    "candidate_id": "G000001",
                    "decision": "approved",
                    "evidence_ids": ["C0001P00001"],
                    "rationale": "The cited passage supports this term occurrence.",
                },
                {
                    "candidate_id": "R001-summary-0001",
                    "decision": "escalated",
                    "evidence_ids": ["C0001P00002"],
                    "rationale": "The cited passage is too short to establish context.",
                },
            ]
        }
        decisions = validate_knowledge_review_decisions(
            response,
            self.candidates,
        )
        self.assertEqual(
            [item["decision"] for item in decisions],
            ["approved", "escalated"],
        )

        invalid = json.loads(json.dumps(response))
        invalid["decisions"][0]["evidence_ids"] = ["C9999P00001"]
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(invalid, self.candidates)

    def test_review_decisions_reject_missing_duplicate_and_unjustified_approval(self):
        decisions = [
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "approved",
                "evidence_ids": [row["source_id"] for row in candidate["evidence"]],
                "rationale": "Supported by the cited passage.",
            }
            for candidate in self.candidates
        ]
        with self.assertRaisesRegex(ValueError, "every candidate"):
            validate_knowledge_review_decisions(
                {"decisions": decisions[:1]},
                self.candidates,
            )

        duplicate = [decisions[0], decisions[0]]
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(
                {"decisions": duplicate},
                self.candidates,
            )

        no_evidence = json.loads(json.dumps({"decisions": decisions}))
        no_evidence["decisions"][0]["evidence_ids"] = []
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(
                no_evidence,
                self.candidates,
            )

        quoted_source = json.loads(json.dumps({"decisions": decisions}))
        quoted_source["decisions"][0]["rationale"] = (
            "The source says: Alice said hello."
        )
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(
                quoted_source,
                self.candidates,
            )

        normalized_quote = json.loads(json.dumps({"decisions": decisions}))
        normalized_quote["decisions"][0]["rationale"] = (
            "The source phrase ALICE SAID HELLO supports the term."
        )
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(
                normalized_quote,
                self.candidates,
            )

        excerpted_source = json.loads(json.dumps({"decisions": decisions}))
        excerpted_source["decisions"][1]["rationale"] = (
            "The passage says 'old bell rang twice', which supports the claim."
        )
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_knowledge_review_decisions(
                excerpted_source,
                self.candidates,
            )

    def test_review_planner_uses_bounded_candidate_batches(self):
        plan = _review_plan(
            self.candidates,
            model_id="synthetic-model-v1",
            tokenizer=CharacterTokenizer(),
            tokenizer_sha256="a" * 64,
            context_window_tokens=10000,
            max_output_tokens=1000,
            safety_margin_tokens=100,
            message_overhead_tokens=20,
            max_provider_calls=10,
        )
        self.assertEqual(plan["review_candidate_count"], 2)
        self.assertEqual(plan["minimum_provider_calls"], 1)
        self.assertEqual(plan["max_provider_calls"], 10)
        self.assertEqual(len(plan["batches"]), 1)

    def test_review_execution_checkpoints_batches_and_resumes_without_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = _review_plan(
                self.candidates,
                model_id="synthetic-model-v1",
                tokenizer=CharacterTokenizer(),
                tokenizer_sha256="a" * 64,
                context_window_tokens=10000,
                max_output_tokens=1000,
                safety_margin_tokens=100,
                message_overhead_tokens=20,
                max_provider_calls=10,
            )
            response = {
                "decisions": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "decision": "approved",
                        "evidence_ids": [
                            row["source_id"] for row in candidate["evidence"]
                        ],
                        "rationale": "The cited passage directly supports the claim.",
                    }
                    for candidate in self.candidates
                ]
            }
            provider_response = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content=json.dumps(response, ensure_ascii=False)
                        ),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=500),
            )
            create = AsyncMock(return_value=provider_response)
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create),
                )
            )
            arguments = {
                "knowledge_root": str(root),
                "plan": plan,
                "candidates": self.candidates,
                "bundle_identity": {
                    "source_snapshot_id": "source-v1-" + "b" * 64,
                    "ai_bundle_id": "ai-v1-" + "c" * 64,
                    "bundle_set_relative_path": "collections/set/bundle-set.json",
                    "bundle_set_sha256": "d" * 64,
                    "ai_bundle_relative_path": "collections/ai/book.json",
                    "ai_bundle_sha256": "e" * 64,
                    "episode_count": 1,
                },
                "glossary_bytes": b'{"Alice":"Alice"}',
                "summary_bytes": b"# Summary",
                "provenance_bytes": b'{"schema_version":1}',
                "provider_id": "synthetic-provider",
                "provider_fingerprint": "f" * 64,
                "client": client,
            }
            first = asyncio.run(_execute_review(**arguments))
            self.assertEqual(first["status"], "all_candidates_approved")
            self.assertEqual(first["provider_calls_made"], 1)
            self.assertEqual(create.await_count, 1)
            report_path = root / first["output"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(
                report["automatic_publication"],
                "not_performed",
            )
            self.assertFalse(report["candidate_completeness_assessed"])
            self.assertNotIn("Alice said hello.", report_path.read_text(encoding="utf-8"))

            original_report = report_path.read_bytes()
            tampered_report = json.loads(original_report.decode("utf-8"))
            tampered_report["decisions"][0]["rationale"] = (
                "This rationale was not present in the batch checkpoint."
            )
            report_path.write_text(
                json.dumps(tampered_report, ensure_ascii=False),
                encoding="utf-8",
            )
            create.reset_mock()
            with self.assertRaisesRegex(ValueError, "checkpoint"):
                asyncio.run(_execute_review(**arguments))
            create.assert_not_awaited()

            report_path.write_bytes(original_report)
            report_path.unlink()
            create.reset_mock()
            resumed = asyncio.run(_execute_review(**arguments))
            self.assertEqual(resumed["provider_calls_made"], 0)
            self.assertEqual(resumed["provider_calls_reused"], 1)
            create.assert_not_awaited()
            self.assertTrue(report_path.is_file())

    def test_cli_preflight_is_provider_free_and_content_free(self):
        bundle_identity = {
            "source_snapshot_id": "source-v1-" + "b" * 64,
            "ai_bundle_id": "ai-v1-" + "c" * 64,
            "bundle_set_relative_path": "collections/set/bundle-set.json",
            "bundle_set_sha256": "d" * 64,
            "ai_bundle_relative_path": "collections/ai/book.json",
            "ai_bundle_sha256": "e" * 64,
            "episode_count": 1,
        }
        with (
            patch(
                "scripts.review_knowledge_candidates.load_tokenizer_json",
                return_value=(CharacterTokenizer(), "a" * 64),
            ),
            patch(
                "scripts.review_knowledge_candidates._load_current_review_inputs",
                return_value=(
                    bundle_identity,
                    {},
                    {},
                    b"glossary",
                    b"summary",
                    b"provenance",
                    self.candidates,
                ),
            ),
            patch("scripts.review_knowledge_candidates.asyncio.run") as run,
            patch("pipeline.Config.load_config") as load_config,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = review_main(
                    [
                        "--knowledge-root",
                        "knowledge",
                        "--source-root",
                        "source",
                        "--catalog",
                        "catalog.json",
                        "--checkpoint",
                        "checkpoint.json",
                        "--bundle-set",
                        "bundle-set.json",
                        "--human-root",
                        "human",
                        "--ai-root",
                        "ai",
                        "--tokenizer-json",
                        "tokenizer.json",
                        "--model-id",
                        "synthetic-model-v1",
                        "--context-window-tokens",
                        "10000",
                        "--max-output-tokens",
                        "1000",
                        "--safety-margin-tokens",
                        "100",
                        "--message-overhead-tokens",
                        "20",
                    ]
                )
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "plan_ready")
        self.assertEqual(report["provider_calls_made"], 0)
        self.assertEqual(report["files_written"], 0)
        self.assertFalse(report["source_passages_included"])
        self.assertNotIn("Alice said hello.", output.getvalue())
        run.assert_not_called()
        load_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
