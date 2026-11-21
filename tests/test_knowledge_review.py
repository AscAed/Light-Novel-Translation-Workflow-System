import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_engine import RAGEngine
from scripts.apply_knowledge_review import (
    _validate_evidence,
    apply_knowledge_review,
    create_knowledge_review_template,
    main,
)
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from utils import read_relative_text


class KnowledgeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.knowledge_root = self.root / "Knowledge"
        self.source_root = self.root / "source"
        self.archive_root = self.root / "archive"
        self.knowledge_root.mkdir()
        self.source_root.mkdir()
        self.archive_root.mkdir()
        self.source_file = self.source_root / "chapter.txt"
        self.source_file.write_text(
            "alpha appears.\n\nbeta appears.\n",
            encoding="utf-8",
            newline="",
        )
        self.artifact = self._collect_and_materialize()
        self._write_candidates()
        self._write_receipt(
            [
                self._decision("alpha", "approved"),
                self._decision("not-found", "escalated"),
            ]
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _collect_and_materialize(self, checkpoint="checkpoint.json"):
        adapter = LocalFileAdapter(
            self.source_root,
            [
                LocalEpisodeFile(
                    EpisodeMetadata("episode-1", "Synthetic episode", 1),
                    "chapter.txt",
                )
            ],
        )
        collect_source(
            adapter,
            root=self.archive_root,
            work_id="synthetic-work",
            checkpoint_relative_path=checkpoint,
        )
        return materialize_episode_markdown(
            self.archive_root,
            work_id="synthetic-work",
            episode_id="episode-1",
        )

    def _write_candidates(self):
        normalized_text = read_relative_text(
            str(self.archive_root), self.artifact["relative_path"]
        )
        source_file = {
            "filename": self.artifact["relative_path"],
            "tm_key": "第1話.md",
            "source_sha256": hashlib.sha256(
                normalized_text.encode("utf-8")
            ).hexdigest(),
            "source_version_id": self.artifact["version_id"],
            "included_characters": len(normalized_text),
            "included_sha256": hashlib.sha256(
                normalized_text.encode("utf-8")
            ).hexdigest(),
            "included_paragraph_count": 2,
        }
        glossary = {"alpha": "阿尔法", "not-found": "不存在词"}
        provenance = {
            "schema_version": 1,
            "artifact_status": "complete",
            "source_files": [source_file],
            "glossary_evidence": [
                {
                    "src": "alpha",
                    "occurrences": [
                        {
                            "chapter": self.artifact["relative_path"],
                            "paragraph_indices": [1],
                        }
                    ],
                },
                {"src": "not-found", "occurrences": []},
            ],
        }
        self.glossary_bytes = json.dumps(
            glossary, ensure_ascii=False, indent=2
        ).encode("utf-8")
        self.provenance_bytes = json.dumps(
            provenance, ensure_ascii=False, indent=2
        ).encode("utf-8")
        (self.knowledge_root / "Glossary_draft.json").write_bytes(
            self.glossary_bytes
        )
        (self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").write_bytes(
            self.provenance_bytes
        )

    def _decision(self, source, status):
        return {
            "src": source,
            "decision": status,
            "rationale": f"Synthetic review: {status}.",
        }

    def _write_receipt(self, decisions):
        receipt = {
            "schema_version": 1,
            "candidate_glossary_sha256": hashlib.sha256(
                self.glossary_bytes
            ).hexdigest(),
            "candidate_provenance_sha256": hashlib.sha256(
                self.provenance_bytes
            ).hexdigest(),
            "reviewer": {
                "provider_id": "synthetic-reviewer",
                "model_id": "fixture-v1",
                "review_id": "synthetic-review-001",
            },
            "reviewed_at_utc": "2026-11-15T00:00:00Z",
            "decisions": decisions,
        }
        (self.knowledge_root / "review.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _publish(
        self,
        output="Glossary_reviewed.json",
        *,
        source_input_root=None,
        source_input_map=None,
        expected_book_bundle=None,
        require_full_book_coverage=False,
    ):
        return apply_knowledge_review(
            str(self.knowledge_root),
            str(self.archive_root),
            "source_manifest.json",
            "review.json",
            output,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
            expected_book_bundle=expected_book_bundle,
            require_full_book_coverage=require_full_book_coverage,
        )

    def test_review_cli_derives_current_ai_map_from_verified_bundle(self):
        identity = {
            "source_snapshot_id": "source-v1-" + "a" * 64,
            "ai_bundle_id": "ai-v1-" + "b" * 64,
            "bundle_set_relative_path": "collections/set/bundle-set.json",
            "bundle_set_sha256": "c" * 64,
            "ai_bundle_relative_path": "collections/ai/book-ai.json",
            "ai_bundle_sha256": "d" * 64,
            "episode_count": 1,
        }
        verified_episode = {
            "source_file": self.artifact["relative_path"],
            "source_version_id": self.artifact["version_id"],
            "source_input_file": "chapters/episode.md",
            "source_sha256": "e" * 64,
        }
        with (
            patch(
                "scripts.apply_knowledge_review.load_verified_ai_book_bundle",
                return_value={
                    "status": "verified",
                    **identity,
                    "episodes_by_source_input_file": {
                        verified_episode["source_input_file"]: verified_episode
                    },
                },
            ) as load_bundle,
            patch(
                "scripts.apply_knowledge_review.apply_knowledge_review",
                return_value={
                    "output": "Glossary_reviewed.json",
                    "approved_term_count": 1,
                    "decision_count": 1,
                    "output_sha256": "f" * 64,
                },
            ) as apply_review,
        ):
            result = main(
                [
                    "--knowledge-root",
                    str(self.knowledge_root),
                    "--source-root",
                    str(self.archive_root),
                    "--manifest",
                    "source_manifest.json",
                    "--review",
                    "review.json",
                    "--output",
                    "Glossary_reviewed.json",
                    "--catalog",
                    "source_catalog.json",
                    "--checkpoint",
                    "source_checkpoint.json",
                    "--bundle-set",
                    "collections/set/bundle-set.json",
                    "--human-root",
                    str(self.root / "human-edition"),
                    "--ai-root",
                    str(self.root / "ai-edition"),
                    "--require-full-book-coverage",
                ]
            )

        self.assertEqual(result, 0)
        load_bundle.assert_called_once()
        call = apply_review.call_args
        self.assertEqual(
            call.kwargs["source_input_map"],
            {
                self.artifact["relative_path"]: {
                    "source_version_id": self.artifact["version_id"],
                    "source_input_file": "chapters/episode.md",
                    "source_sha256": "e" * 64,
                }
            },
        )
        self.assertEqual(call.kwargs["source_input_root"], str(self.root / "ai-edition"))
        self.assertEqual(call.kwargs["expected_book_bundle"], identity)
        self.assertTrue(call.kwargs["require_full_book_coverage"])

    def test_full_book_coverage_accepts_empty_chapter_evidence(self):
        provenance = json.loads(self.provenance_bytes)
        empty_digest = hashlib.sha256(b"").hexdigest()
        provenance["source_files"] = [
            *provenance["source_files"],
            {
                "filename": "empty-chapter.md",
                "tm_key": "第2話.md",
                "source_sha256": empty_digest,
                "source_version_id": "empty-version",
                "included_characters": 0,
                "included_sha256": empty_digest,
                "included_paragraph_count": 0,
            },
        ]
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 2,
            "included_chapter_count": 2,
            "input_characters": 100,
            "input_character_limit": 500,
        }

        evidence = _validate_evidence(
            provenance,
            {"alpha": "阿尔法", "not-found": "不存在词"},
        )

        self.assertEqual(
            evidence["alpha"],
            [
                {
                    "chapter": self.artifact["relative_path"],
                    "paragraph_indices": [1],
                }
            ],
        )

    def test_full_book_coverage_must_match_source_file_count(self):
        provenance = json.loads(self.provenance_bytes)
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 2,
            "included_chapter_count": 1,
            "input_characters": 100,
            "input_character_limit": 500,
        }

        with self.assertRaisesRegex(
            ValueError, "incomplete full-book coverage"
        ):
            _validate_evidence(
                provenance,
                {"alpha": "阿尔法", "not-found": "不存在词"},
            )

    def test_review_template_binds_candidates_and_is_not_publishable_until_completed(self):
        result = create_knowledge_review_template(
            str(self.knowledge_root),
            "review-template.json",
        )
        template_path = self.knowledge_root / result["output"]
        template = json.loads(template_path.read_text(encoding="utf-8"))
        self.assertEqual(result["decision_count"], 2)
        self.assertEqual(
            template["candidate_glossary_sha256"],
            hashlib.sha256(self.glossary_bytes).hexdigest(),
        )
        self.assertEqual(
            template["candidate_provenance_sha256"],
            hashlib.sha256(self.provenance_bytes).hexdigest(),
        )
        self.assertEqual(
            result["output_sha256"],
            hashlib.sha256(template_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [item["src"] for item in template["decisions"]],
            ["alpha", "not-found"],
        )
        self.assertTrue(
            all(item["decision"] == "pending" for item in template["decisions"])
        )
        self.assertNotIn(
            "alpha appears.",
            json.dumps(template, ensure_ascii=False),
        )

        with self.assertRaises(ValueError):
            apply_knowledge_review(
                str(self.knowledge_root),
                str(self.archive_root),
                "source_manifest.json",
                "review-template.json",
                "Glossary_from_template.json",
            )
        self.assertFalse(
            (self.knowledge_root / "Glossary_from_template.json").exists()
        )

        self._write_receipt(
            [
                self._decision("alpha", "approved"),
                self._decision("not-found", "rejected"),
            ]
        )
        completed_receipt = json.loads(
            (self.knowledge_root / "review.json").read_text(encoding="utf-8")
        )
        template["reviewer"] = completed_receipt["reviewer"]
        template["reviewed_at_utc"] = completed_receipt["reviewed_at_utc"]
        template["decisions"] = completed_receipt["decisions"]
        template_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = apply_knowledge_review(
            str(self.knowledge_root),
            str(self.archive_root),
            "source_manifest.json",
            "review-template.json",
            "Glossary_from_template.json",
        )
        self.assertEqual(result["approved_term_count"], 1)

    def test_review_template_does_not_overwrite_existing_receipt(self):
        template_path = self.knowledge_root / "review-template.json"
        template_path.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            create_knowledge_review_template(
                str(self.knowledge_root),
                "review-template.json",
            )
        self.assertEqual(template_path.read_text(encoding="utf-8"), "preserve")

    def test_cli_creates_review_template_without_source_arguments(self):
        result = main(
            [
                "--knowledge-root",
                str(self.knowledge_root),
                "--create-template",
                "review-template.json",
            ]
        )
        self.assertEqual(result, 0)
        self.assertTrue((self.knowledge_root / "review-template.json").is_file())

    def test_publishes_only_approved_source_backed_terms_for_rag(self):
        result = self._publish()
        self.assertEqual(result["approved_term_count"], 1)
        self.assertEqual(
            result["output_sha256"],
            hashlib.sha256(
                (self.knowledge_root / result["output"]).read_bytes()
            ).hexdigest(),
        )

        bundle = json.loads(
            (self.knowledge_root / result["output"]).read_text(encoding="utf-8")
        )
        self.assertEqual(bundle["terms"], {"alpha": "阿尔法"})
        self.assertEqual(
            bundle["review"]["decisions"][0]["evidence"],
            [
                {
                    "chapter": self.artifact["relative_path"],
                    "paragraph_indices": [1],
                }
            ],
        )
        self.assertNotIn("alpha appears.", json.dumps(bundle, ensure_ascii=False))

        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(self.knowledge_root / result["output"]),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
        )
        self.assertEqual(
            engine.get_cleaned_glossary("alpha"),
            [{"src": "alpha", "dst": "阿尔法", "info": "阿尔法"}],
        )
        self.assertEqual(engine.get_cleaned_glossary("not-found"), [])

    def test_ai_edition_glossary_binds_current_full_book_bundle(self):
        provenance_path = self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        ai_text = "alpha appears after cleanup.\n\nbeta appears.\n"
        ai_root = self.root / "RAWs_AI"
        ai_root.mkdir()
        ai_path = ai_root / "episode-ai.md"
        ai_path.write_text(ai_text, encoding="utf-8")
        ai_bytes_digest = hashlib.sha256(ai_path.read_bytes()).hexdigest()
        ai_text_digest = hashlib.sha256(
            ai_text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        ).hexdigest()
        provenance["source_files"][0].update(
            {
                "source_input_file": "episode-ai.md",
                "source_sha256": ai_text_digest,
                "included_characters": len(ai_text),
                "included_sha256": ai_text_digest,
                "included_paragraph_count": 2,
            }
        )
        provenance["input_coverage"] = {
            "scope": "all_configured_chapters",
            "complete_for_configured_chapters": True,
            "configured_chapter_count": 1,
            "included_chapter_count": 1,
            "input_characters": len(ai_text),
            "input_character_limit": len(ai_text),
        }
        bundle_identity = {
            "source_snapshot_id": "source-v1-" + "a" * 64,
            "ai_bundle_id": "ai-v1-" + "b" * 64,
            "bundle_set_relative_path": "collections/set/bundle-set.json",
            "bundle_set_sha256": "c" * 64,
            "ai_bundle_relative_path": "collections/ai/book-ai.json",
            "ai_bundle_sha256": "d" * 64,
            "episode_count": 1,
        }
        provenance["book_bundle"] = bundle_identity
        provenance_path.write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.provenance_bytes = provenance_path.read_bytes()
        source_input_map = {
            self.artifact["relative_path"]: {
                "source_version_id": self.artifact["version_id"],
                "source_input_file": "episode-ai.md",
                "source_sha256": ai_bytes_digest,
            }
        }
        self._write_receipt(
            [
                self._decision("alpha", "approved"),
                self._decision("not-found", "rejected"),
            ]
        )

        with patch(
            "source_manifest._verify_artifact_file",
            side_effect=AssertionError("archive body read for AI source"),
        ):
            result = self._publish(
                source_input_root=str(ai_root),
                source_input_map=source_input_map,
                expected_book_bundle=bundle_identity,
                require_full_book_coverage=True,
            )

        reviewed_path = self.knowledge_root / result["output"]
        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
        self.assertEqual(reviewed["review"]["book_bundle"], bundle_identity)
        self.assertEqual(
            reviewed["review"]["input_coverage"],
            provenance["input_coverage"],
        )

        with self.assertRaisesRegex(
            ValueError, "AI edition knowledge sources require"
        ):
            self._publish(
                output="Glossary_without_ai_map.json",
                expected_book_bundle=bundle_identity,
                require_full_book_coverage=True,
            )

        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(reviewed_path),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
            source_input_root=str(ai_root),
            source_input_map=source_input_map,
            expected_book_bundle=bundle_identity,
            require_full_book_coverage=True,
        )
        self.assertEqual(
            engine.get_cleaned_glossary("alpha"),
            [{"src": "alpha", "dst": "阿尔法", "info": "阿尔法"}],
        )

        without_map_engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(reviewed_path),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
            expected_book_bundle=bundle_identity,
            require_full_book_coverage=True,
        )
        with self.assertRaisesRegex(ValueError, "current AI chapter map"):
            without_map_engine.get_cleaned_glossary("alpha")

        bad_coverage_path = self.knowledge_root / "Glossary_bad_coverage.json"
        bad_coverage = json.loads(reviewed_path.read_text(encoding="utf-8"))
        bad_coverage["review"]["input_coverage"][
            "configured_chapter_count"
        ] = True
        bad_coverage_path.write_text(
            json.dumps(bad_coverage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "current AI chapter map"):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(bad_coverage_path),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map=source_input_map,
                expected_book_bundle=bundle_identity,
                require_full_book_coverage=True,
            ).get_cleaned_glossary("alpha")

        bad_bundle_path = self.knowledge_root / "Glossary_bad_bundle.json"
        bad_bundle = json.loads(reviewed_path.read_text(encoding="utf-8"))
        bad_bundle["review"]["book_bundle"][
            "bundle_set_relative_path"
        ] = "../bundle-set.json"
        bad_bundle_path.write_text(
            json.dumps(bad_bundle, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "malformed book bundle"):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(bad_bundle_path),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map=source_input_map,
                expected_book_bundle=bundle_identity,
                require_full_book_coverage=True,
            ).get_cleaned_glossary("alpha")

        with self.assertRaisesRegex(ValueError, "different AI book bundle"):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(reviewed_path),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map=source_input_map,
                expected_book_bundle={
                    **bundle_identity,
                    "ai_bundle_sha256": "e" * 64,
                },
                require_full_book_coverage=True,
            ).get_cleaned_glossary("alpha")

        with self.assertRaisesRegex(ValueError, "current AI chapter map"):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(reviewed_path),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                source_input_root=str(ai_root),
                source_input_map={
                    **source_input_map,
                    "new-episode.md": {
                        "source_version_id": "new-version",
                        "source_input_file": "new-episode.md",
                        "source_sha256": "f" * 64,
                    },
                },
                expected_book_bundle=bundle_identity,
                require_full_book_coverage=True,
            ).get_cleaned_glossary("alpha")

    def test_reviewed_glossary_requires_manifest_for_rag_use(self):
        self._publish()
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(self.knowledge_root / "Glossary_reviewed.json"),
            str(self.root / "guidelines.txt"),
        )

        with self.assertRaisesRegex(ValueError, "requires a source root"):
            engine.get_cleaned_glossary("alpha")

    def test_strict_rag_requires_a_reviewed_glossary_bundle(self):
        legacy_glossary = self.knowledge_root / "Glossary.json"
        legacy_glossary.write_text(
            '{"alpha":"unreviewed translation"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "requires a reviewed glossary bundle"):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(legacy_glossary),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                require_reviewed_glossary=True,
            )

    def test_strict_rag_rejects_a_missing_reviewed_glossary_bundle(self):
        with self.assertRaisesRegex(
            ValueError, "requires a readable reviewed glossary bundle"
        ):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(self.knowledge_root / "Glossary_reviewed.json"),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                require_reviewed_glossary=True,
            )

    def test_strict_rag_rejects_a_malformed_reviewed_glossary_bundle(self):
        reviewed_glossary = self.knowledge_root / "Glossary_reviewed.json"
        reviewed_glossary.write_text(
            '{"_knowledge_review_schema":1,"terms":',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError, "requires a valid reviewed glossary bundle"
        ):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(reviewed_glossary),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                require_reviewed_glossary=True,
            )

    def test_strict_rag_validates_reviewed_glossary_during_initialization(self):
        self._publish()
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(self.knowledge_root / "Glossary_reviewed.json"),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
            require_reviewed_glossary=True,
        )

        self.assertEqual(
            engine.get_cleaned_glossary("alpha"),
            [{"src": "alpha", "dst": "阿尔法", "info": "阿尔法"}],
        )

    def test_strict_rag_rejects_stale_reviewed_glossary_during_initialization(self):
        self._publish()
        self.source_file.write_text(
            "updated alpha appears.\n\nbeta appears.\n",
            encoding="utf-8",
            newline="",
        )
        self._collect_and_materialize("updated-checkpoint.json")

        with self.assertRaisesRegex(
            ValueError, "source versions are not current"
        ):
            RAGEngine(
                str(self.root / "translation_memory.json"),
                str(self.knowledge_root / "Glossary_reviewed.json"),
                str(self.root / "guidelines.txt"),
                source_root=str(self.archive_root),
                source_manifest_path="source_manifest.json",
                require_reviewed_glossary=True,
            )

    def test_rejects_changed_candidate_hash_before_writing(self):
        (self.knowledge_root / "Glossary_draft.json").write_text(
            '{"alpha":"changed"}', encoding="utf-8"
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            self._publish()
        self.assertFalse(
            (self.knowledge_root / "Glossary_reviewed.json").exists()
        )

    def test_rejects_source_that_became_stale_after_review(self):
        self.source_file.write_text(
            "updated alpha appears.\n\nbeta appears.\n",
            encoding="utf-8",
            newline="",
        )
        self._collect_and_materialize("updated-checkpoint.json")

        with self.assertRaisesRegex(ValueError, "not fully verified"):
            self._publish()
        self.assertFalse(
            (self.knowledge_root / "Glossary_reviewed.json").exists()
        )

    def test_rag_refuses_published_glossary_after_source_update(self):
        self._publish()
        self.source_file.write_text(
            "updated alpha appears.\n\nbeta appears.\n",
            encoding="utf-8",
            newline="",
        )
        self._collect_and_materialize("updated-checkpoint.json")
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(self.knowledge_root / "Glossary_reviewed.json"),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
        )

        with self.assertRaisesRegex(ValueError, "source versions are not current"):
            engine.get_cleaned_glossary("alpha")

    def test_rag_revalidates_reviewed_glossary_sources_on_every_query(self):
        self._publish()
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(self.knowledge_root / "Glossary_reviewed.json"),
            str(self.root / "guidelines.txt"),
            source_root=str(self.archive_root),
            source_manifest_path="source_manifest.json",
        )

        first_result = engine.get_cleaned_glossary("alpha")
        self.assertEqual(first_result[0]["dst"], "阿尔法")
        self.source_file.write_text(
            "updated alpha appears.\n\nbeta appears.\n",
            encoding="utf-8",
            newline="",
        )
        self._collect_and_materialize("updated-checkpoint.json")

        with self.assertRaisesRegex(ValueError, "source versions are not current"):
            engine.get_cleaned_glossary("alpha")

    def test_rag_rejects_truncated_reviewed_bundle_without_legacy_fallback(self):
        reviewed_path = self.knowledge_root / "Glossary_reviewed.json"
        reviewed_path.write_text(
            '{"_knowledge_review_schema":1,"terms":{"alpha":"unverified"},',
            encoding="utf-8",
        )
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(reviewed_path),
            str(self.root / "guidelines.txt"),
        )

        with self.assertRaisesRegex(ValueError, "bundle is malformed"):
            engine.get_cleaned_glossary("alpha")

    def test_rejects_forged_paragraph_location_even_when_receipt_matches(self):
        provenance_path = (
            self.knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json"
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["glossary_evidence"][0]["occurrences"][0][
            "paragraph_indices"
        ] = [2]
        self.provenance_bytes = json.dumps(
            provenance, ensure_ascii=False, indent=2
        ).encode("utf-8")
        provenance_path.write_bytes(self.provenance_bytes)
        self._write_receipt(
            [
                self._decision("alpha", "approved"),
                self._decision("not-found", "escalated"),
            ]
        )

        with self.assertRaisesRegex(ValueError, "locations do not match"):
            self._publish()
        self.assertFalse(
            (self.knowledge_root / "Glossary_reviewed.json").exists()
        )

    def test_does_not_publish_approved_terms_without_source_locations(self):
        self._write_receipt(
            [
                self._decision("alpha", "rejected"),
                self._decision("not-found", "approved"),
            ]
        )

        with self.assertRaisesRegex(ValueError, "without source evidence"):
            self._publish()
        self.assertFalse(
            (self.knowledge_root / "Glossary_reviewed.json").exists()
        )

    def test_existing_output_is_never_overwritten(self):
        output = self.knowledge_root / "Glossary_reviewed.json"
        output.write_text("preserve", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self._publish()
        self.assertEqual(output.read_text(encoding="utf-8"), "preserve")

    def test_rag_rejects_reviewed_bundle_with_changed_approved_terms(self):
        self._publish()
        output = self.knowledge_root / "Glossary_reviewed.json"
        bundle = json.loads(output.read_text(encoding="utf-8"))
        bundle["terms"]["alpha"] = "tampered"
        output.write_text(
            json.dumps(bundle, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RAGEngine(
            str(self.root / "translation_memory.json"),
            str(output),
            str(self.root / "guidelines.txt"),
        )

        with self.assertRaisesRegex(ValueError, "term hash"):
            engine.get_cleaned_glossary("alpha")


if __name__ == "__main__":
    unittest.main()
