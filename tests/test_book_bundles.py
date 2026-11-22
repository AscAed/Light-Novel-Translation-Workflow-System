import asyncio
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import book_bundles
from book_bundles import export_book_bundles, load_verified_ai_book_bundle
from pipeline import Config
from scripts import auto_extract_knowledge
from scripts.export_book_bundles import main as export_main
from scripts.review_knowledge_candidates import _load_current_review_inputs
from source_editions import prepare_source_editions
from story_summary_review import _validate_summary_provenance
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from scripts.plan_knowledge_extraction import plan_full_book_extraction


class BookBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.input_root = self.root / "input"
        self.source_root = self.root / "archive"
        self.human_root = self.root / "human"
        self.ai_root = self.root / "ai"
        for path in (self.input_root, self.source_root, self.human_root, self.ai_root):
            path.mkdir()

        self.work_id = "12345"
        self.work_metadata = {
            "source_url": "https://kakuyomu.jp/works/12345",
            "title": "Synthetic work",
            "author_name": "Synthetic author",
            "author_screen_name": "synthetic",
            "catchphrase": "A test work",
            "introduction": "Synthetic introduction",
            "genre": "fantasy",
            "tags": ["synthetic"],
            "serial_status": "ongoing",
            "published_at": None,
            "last_episode_published_at": None,
            "public_episode_count": 2,
        }
        self.source_text = {
            "101": "Synthetic first episode.\n",
            "102": "Synthetic second episode.\n",
        }
        episodes = []
        for episode_id, title, position in (
            ("101", "First episode", 1),
            ("102", "Second episode", 2),
        ):
            page_url = (
                "https://kakuyomu.jp/works/12345/episodes/" + episode_id
            )
            filename = episode_id + ".txt"
            (self.input_root / filename).write_bytes(
                self.source_text[episode_id].encode("utf-8")
            )
            episodes.append(
                LocalEpisodeFile(
                    EpisodeMetadata(
                        episode_id,
                        title,
                        position,
                        page_url,
                    ),
                    filename,
                )
            )
        collect_source(
            LocalFileAdapter(self.input_root, episodes),
            root=self.source_root,
            work_id=self.work_id,
            work_metadata=self.work_metadata,
        )
        self.catalog_path = self.source_root / "catalog.json"
        catalog = {
            "schema_version": 3,
            "work_id": self.work_id,
            "work_metadata": self.work_metadata,
            "episodes": [
                {
                    "episode_id": item.metadata.episode_id,
                    "title": item.metadata.title,
                    "position": item.metadata.position,
                    "page_url": item.metadata.source_ref,
                }
                for item in episodes
            ],
            "chapters": [
                {
                    "group_id": "chapter-1",
                    "chapter_id": "chapter-1",
                    "title": "Chapter One",
                    "level": 1,
                    "position_start": 1,
                    "position_end": 2,
                    "episode_ids": ["101", "102"],
                }
            ],
        }
        self.catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )
        for item in episodes:
            materialize_episode_markdown(
                self.source_root,
                work_id=self.work_id,
                episode_id=item.metadata.episode_id,
            )
        prepare_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            manifest_relative_path="source_manifest.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _export(self, **overrides):
        arguments = {
            "source_root": str(self.source_root),
            "catalog_relative_path": "catalog.json",
            "human_root": str(self.human_root),
            "ai_root": str(self.ai_root),
            "checkpoint_relative_path": "source_checkpoint.json",
        }
        arguments.update(overrides)
        return export_book_bundles(**arguments)

    def test_exports_complete_self_contained_bundles_and_manifest(self):
        report = self._export()
        bundle_set = json.loads(
            (self.source_root / report["bundle_set_relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        paths = {
            name: Path(root) / record["relative_path"]
            for name, root in (
                ("raw", self.source_root),
                ("ai", self.ai_root),
                ("human", self.human_root),
            )
            for record in [bundle_set["bundles"][name]]
        }
        raw_bundle = json.loads(paths["raw"].read_text(encoding="utf-8"))
        ai_bundle = json.loads(paths["ai"].read_text(encoding="utf-8"))
        human_bundle = paths["human"].read_text(encoding="utf-8")

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["episode_count"], 2)
        self.assertEqual(bundle_set["status"], "complete")
        self.assertEqual(
            bundle_set["completeness"]["status"],
            "complete_for_declared_public_catalog",
        )
        self.assertEqual(
            bundle_set["completeness"]["platform_enumeration_exhaustiveness"],
            "not_independently_proven",
        )
        self.assertEqual(
            [item["source_text"] for item in raw_bundle["episodes"]],
            list(self.source_text.values()),
        )
        self.assertEqual(
            [item["source_text"] for item in ai_bundle["episodes"]],
            list(self.source_text.values()),
        )
        self.assertIn(_HUMAN_MARKER, human_bundle)
        self.assertIn("episode:start:1", human_bundle)
        self.assertIn("episode:end:2", human_bundle)
        self.assertNotIn("Synthetic first episode.", json.dumps(report))
        for edition, path in paths.items():
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                bundle_set["bundles"][edition]["sha256"],
            )

    def test_knowledge_extraction_plan_uses_verified_current_bundle(self):
        report = self._export()

        class CharacterTokenizer:
            def encode(self, text):
                return SimpleNamespace(ids=list(text))

        with patch(
            "scripts.plan_knowledge_extraction.load_tokenizer_json",
            return_value=(CharacterTokenizer(), "a" * 64),
        ):
            plan = plan_full_book_extraction(
                source_root=str(self.source_root),
                catalog_relative_path="catalog.json",
                checkpoint_relative_path="source_checkpoint.json",
                bundle_set_relative_path=report["bundle_set_relative_path"],
                human_root=str(self.human_root),
                ai_root=str(self.ai_root),
                tokenizer_json="synthetic-tokenizer.json",
                model_id="synthetic-model-v1",
                max_input_characters=10_000,
                context_window_tokens=100_000,
                max_output_tokens=1_000,
                safety_margin_tokens=1_000,
                message_overhead_tokens=100,
                max_provider_calls=10,
            )

        self.assertEqual(plan["status"], "ready_for_extraction")
        self.assertEqual(plan["episode_count"], 2)
        self.assertEqual(
            plan["book_bundle"]["source_snapshot_id"],
            report["source_snapshot_id"],
        )
        self.assertEqual(plan["provider_calls_made"], 0)
        self.assertEqual(plan["files_written"], 0)
        self.assertFalse(plan["source_text_included"])
        self.assertNotIn("Synthetic first episode.", json.dumps(plan))

    def test_ai_knowledge_review_inputs_follow_extraction_and_verified_bundle(self):
        report = self._export()
        bundle_set = json.loads(
            (
                self.source_root / report["bundle_set_relative_path"]
            ).read_text(encoding="utf-8")
        )
        verified = load_verified_ai_book_bundle(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            checkpoint_relative_path="source_checkpoint.json",
            bundle_set_relative_path=report["bundle_set_relative_path"],
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )
        chapter_specs = [
            SimpleNamespace(
                raw_file=episode["source_file"],
                source_input_file=source_input_file,
                source_sha256=episode["source_sha256"],
                source_version_id=episode["source_version_id"],
                chapter_position=episode["position"],
                tm_key=episode["episode_id"],
            )
            for source_input_file, episode in verified[
                "episodes_by_source_input_file"
            ].items()
        ]
        extraction_response = {
            "glossary": [
                {
                    "src": "Synthetic",
                    "dst": "合成词条",
                    "info": "",
                    "evidence_ids": ["C0001P00001"],
                }
            ],
            "summary_claims": [
                {
                    "text": "A synthetic opening claim.",
                    "evidence_ids": ["C0001P00001"],
                }
            ],
            "worldbuilding_claims": [],
            "narrative_voice_claims": [],
        }
        provider_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(
                            extraction_response,
                            ensure_ascii=False,
                        )
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=200),
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=provider_response)
                )
            )
        )

        class CharacterTokenizer:
            def encode(self, text):
                return SimpleNamespace(ids=list(text))

        route = SimpleNamespace(
            provider_id="synthetic-provider",
            base_url="https://provider.invalid/v1",
            api_key_env="SYNTHETIC_KEY",
            request_model="synthetic-model-v1",
        )
        knowledge_root = self.root / "Knowledge"
        knowledge_root.mkdir()
        with (
            patch.object(Config, "PROOFREAD_MODEL", "synthetic-model-v1"),
            patch.object(Config, "CHAPTER_MAP", [{"chapter_position": 1}, {"chapter_position": 2}]),
            patch.object(Config, "OUTPUT_DIR", str(self.root / "translations")),
            patch.object(Config, "SOURCE_MANIFEST_PATH", "source_manifest.json"),
            patch.object(Config, "AI_EDITION_ROOT", str(self.ai_root)),
            patch(
                "scripts.auto_extract_knowledge.get_primary_provider_route",
                return_value=route,
            ),
            patch("scripts.auto_extract_knowledge.get_api_key", return_value=None),
            patch(
                "scripts.auto_extract_knowledge.resolve_openai_client_settings"
            ),
            patch(
                "scripts.auto_extract_knowledge.load_tokenizer_json",
                return_value=(CharacterTokenizer(), "a" * 64),
            ),
            patch(
                "scripts.auto_extract_knowledge.get_chapter_specs",
                return_value=chapter_specs,
            ),
            patch(
                "scripts.auto_extract_knowledge.get_openai_client",
                return_value=client,
            ),
            patch("scripts.auto_extract_knowledge._read_source_chapter") as source_reader,
        ):
            asyncio.run(
                auto_extract_knowledge.extract_knowledge(
                    str(self.source_root),
                    str(knowledge_root),
                    full_book=True,
                    require_book_bundle=True,
                    max_input_characters=10000,
                    tokenizer_json="synthetic-tokenizer.json",
                    context_window_tokens=10000,
                    max_output_tokens=1000,
                    safety_margin_tokens=500,
                    message_overhead_tokens=50,
                    max_provider_calls=10,
                    catalog_relative_path="catalog.json",
                    checkpoint_relative_path="source_checkpoint.json",
                    bundle_set_relative_path=report["bundle_set_relative_path"],
                    ai_book_bundle_path=bundle_set["bundles"]["ai"]["relative_path"],
                    human_root=str(self.human_root),
                )
            )

        source_reader.assert_not_called()
        provenance = json.loads(
            (knowledge_root / "KNOWLEDGE_PROVENANCE_draft.json").read_text(
                encoding="utf-8"
            )
        )
        claims_by_category = {
            category: []
            for category in ("summary", "worldbuilding", "narrative_voice")
        }
        for claim in provenance["claim_evidence"]:
            claims_by_category[claim["category"]].append(claim)
        expected_summary = (
            "# Story Summary (Draft)\n\n"
            + auto_extract_knowledge._render_full_book_summary(
                claims_by_category,
                synthesized=False,
            )
        )
        self.assertEqual(
            (knowledge_root / "STORY_SUMMARY_draft.md").read_text(
                encoding="utf-8"
            ),
            expected_summary,
        )
        normalized_provenance = _validate_summary_provenance(provenance)
        normalized_claims_by_category = {
            category: []
            for category in ("summary", "worldbuilding", "narrative_voice")
        }
        for claim in normalized_provenance["claim_evidence"]:
            normalized_claims_by_category[claim["category"]].append(claim)
        normalized_expected = (
            "# Story Summary (Draft)\n\n"
            + auto_extract_knowledge._render_full_book_summary(
                normalized_claims_by_category,
                synthesized=(
                    normalized_provenance["token_budget"].get(
                        "synthesis_status"
                    )
                    == "completed"
                ),
            )
        )
        self.assertEqual(
            (knowledge_root / "STORY_SUMMARY_draft.md").read_text(
                encoding="utf-8"
            ),
            normalized_expected,
        )
        (
            current_identity,
            _,
            _,
            _,
            _,
            _,
            candidates,
        ) = _load_current_review_inputs(
            knowledge_root=str(knowledge_root),
            source_root=str(self.source_root),
            manifest_relative_path="source_manifest.json",
            edition_manifest_relative_path="source_editions_manifest.json",
            catalog_relative_path="catalog.json",
            checkpoint_relative_path="source_checkpoint.json",
            bundle_set_relative_path=report["bundle_set_relative_path"],
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

        self.assertEqual(
            current_identity["ai_bundle_sha256"],
            verified["ai_bundle_sha256"],
        )
        self.assertEqual(
            [item["candidate_id"] for item in candidates],
            ["G000001", "B0001-summary-0001"],
        )
        self.assertEqual(
            candidates[0]["evidence"][0]["text"],
            "Synthetic first episode.",
        )

    def test_repeated_export_is_idempotent(self):
        first = self._export()
        second = self._export()

        self.assertEqual(first["source_snapshot_id"], second["source_snapshot_id"])
        self.assertTrue(all(first["created"].values()))
        self.assertFalse(any(second["created"].values()))
        self.assertEqual(
            first["bundles"],
            second["bundles"],
        )

    def test_ai_bundle_loader_verifies_complete_current_snapshot(self):
        report = self._export()
        verified = load_verified_ai_book_bundle(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            checkpoint_relative_path="source_checkpoint.json",
            bundle_set_relative_path=report["bundle_set_relative_path"],
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["episode_count"], 2)
        self.assertEqual(
            verified["source_snapshot_id"],
            report["source_snapshot_id"],
        )
        self.assertEqual(
            [
                episode["source_text"]
                for episode in verified["bundle"]["episodes"]
            ],
            list(self.source_text.values()),
        )
        for episode in verified["episodes_by_source_input_file"].values():
            self.assertTrue(episode["source_file"])

    def test_ai_bundle_loader_rejects_changed_bundle_content(self):
        report = self._export()
        ai_bundle_path = (
            self.ai_root / report["bundles"]["ai"]["relative_path"]
        )
        ai_bundle_path.write_bytes(b"changed after completion")

        with self.assertRaisesRegex(ValueError, "completion set"):
            load_verified_ai_book_bundle(
                source_root=str(self.source_root),
                catalog_relative_path="catalog.json",
                checkpoint_relative_path="source_checkpoint.json",
                bundle_set_relative_path=report["bundle_set_relative_path"],
                human_root=str(self.human_root),
                ai_root=str(self.ai_root),
            )

    def test_ai_bundle_loader_rejects_duplicate_or_missing_catalog_episodes(self):
        report = self._export()
        ai_bundle_path = (
            self.ai_root / report["bundles"]["ai"]["relative_path"]
        )
        bundle_set_path = (
            self.source_root / report["bundle_set_relative_path"]
        )
        ai_bundle = json.loads(ai_bundle_path.read_text(encoding="utf-8"))
        bundle_set = json.loads(bundle_set_path.read_text(encoding="utf-8"))
        first_episode = ai_bundle["episodes"][0]
        invalid_episode_lists = (
            [first_episode],
            [first_episode, first_episode],
        )

        for episodes in invalid_episode_lists:
            with self.subTest(episode_count=len(episodes)):
                mutated_bundle = dict(ai_bundle)
                mutated_bundle["episodes"] = episodes
                bundle_bytes = json.dumps(
                    mutated_bundle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                ai_bundle_path.write_bytes(bundle_bytes)

                mutated_set = dict(bundle_set)
                mutated_records = dict(bundle_set["bundles"])
                mutated_ai_record = dict(bundle_set["bundles"]["ai"])
                mutated_ai_record["sha256"] = hashlib.sha256(
                    bundle_bytes
                ).hexdigest()
                mutated_records["ai"] = mutated_ai_record
                mutated_set["bundles"] = mutated_records
                bundle_set_path.write_text(
                    json.dumps(
                        mutated_set,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with self.assertRaises(ValueError):
                    load_verified_ai_book_bundle(
                        source_root=str(self.source_root),
                        catalog_relative_path="catalog.json",
                        checkpoint_relative_path="source_checkpoint.json",
                        bundle_set_relative_path=report[
                            "bundle_set_relative_path"
                        ],
                        human_root=str(self.human_root),
                        ai_root=str(self.ai_root),
                    )

    def test_failed_partial_export_can_resume_before_completion_marker(self):
        original = book_bundles._write_immutable
        failed = [False]

        def fail_once(root, relative_path, content):
            if relative_path.endswith("/book-ai.json") and not failed[0]:
                failed[0] = True
                raise OSError("synthetic write interruption")
            return original(root, relative_path, content)

        with patch("book_bundles._write_immutable", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "write interruption"):
                self._export()

        collection_root = self.source_root / "collections"
        self.assertTrue(collection_root.exists())
        self.assertEqual(list(collection_root.rglob("bundle-set.*.json")), [])

        resumed = self._export()
        self.assertFalse(resumed["created"]["raw"])
        self.assertTrue(resumed["created"]["ai"])
        self.assertTrue(resumed["created"]["human"])
        self.assertTrue(resumed["created"]["bundle_set"])

    def test_immutable_bundle_file_is_not_visible_before_atomic_link(self):
        root = self.root / "immutable"
        root.mkdir()
        target = root / "bundle.json"

        with patch(
            "book_bundles.os.link",
            side_effect=OSError("synthetic publication interruption"),
        ):
            with self.assertRaisesRegex(OSError, "publication interruption"):
                book_bundles._write_immutable(root, "bundle.json", b"complete")

        self.assertFalse(target.exists())
        self.assertEqual(list(root.glob("*.tmp")), [])

    def test_export_and_loader_accept_custom_edition_index_paths(self):
        ai_custom_root = self.ai_root / "metadata"
        human_custom_root = self.human_root / "metadata"
        ai_custom_root.mkdir()
        human_custom_root.mkdir()
        (self.ai_root / "catalog.json").rename(
            ai_custom_root / "edition-index.json"
        )
        (self.human_root / "SOURCE_MAP.json").rename(
            human_custom_root / "edition-index.json"
        )

        report = self._export(
            ai_index_relative_path="metadata/edition-index.json",
            human_index_relative_path="metadata/edition-index.json",
        )
        verified = load_verified_ai_book_bundle(
            source_root=str(self.source_root),
            catalog_relative_path="catalog.json",
            checkpoint_relative_path="source_checkpoint.json",
            bundle_set_relative_path=report["bundle_set_relative_path"],
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["episode_count"], 2)

    def test_catalog_change_after_parse_is_detected(self):
        original_loader = book_bundles._load_catalog_snapshot
        changed = [False]

        def load_then_change(source_root, relative_path, **kwargs):
            snapshot = original_loader(source_root, relative_path, **kwargs)
            if not changed[0]:
                changed[0] = True
                self.catalog_path.write_bytes(
                    self.catalog_path.read_bytes() + b"\n"
                )
            return snapshot

        with patch(
            "book_bundles._load_catalog_snapshot",
            side_effect=load_then_change,
        ):
            with self.assertRaisesRegex(
                (RuntimeError, ValueError),
                "inputs changed|stale for the current catalog",
            ):
                self._export()

        self.assertFalse((self.source_root / "collections").exists())

    def test_source_snapshot_identity_includes_checkpoint_provenance(self):
        first = self._export()
        checkpoint = self.source_root / "source_checkpoint.json"
        alternate_checkpoint = self.source_root / "alternate_checkpoint.json"
        alternate_checkpoint.write_bytes(checkpoint.read_bytes())

        second = self._export(
            checkpoint_relative_path="alternate_checkpoint.json"
        )

        self.assertNotEqual(
            first["source_snapshot_id"],
            second["source_snapshot_id"],
        )

    def test_incomplete_checkpoint_fails_before_writing(self):
        checkpoint_path = self.source_root / "source_checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["status"] = "paused"
        checkpoint["pause_reason"] = "unavailable"
        checkpoint_path.write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "complete current checkpoint"):
            self._export()
        self.assertFalse((self.source_root / "collections").exists())

    def test_output_limit_fails_before_writing(self):
        with self.assertRaisesRegex(ValueError, "output byte limit"):
            self._export(max_total_output_bytes=1)
        self.assertFalse((self.source_root / "collections").exists())
        self.assertFalse((self.ai_root / "collections").exists())
        self.assertFalse((self.human_root / "collections").exists())

    def test_cli_reports_metadata_without_chapter_text(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = export_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--human-root",
                    str(self.human_root),
                    "--ai-root",
                    str(self.ai_root),
                    "--checkpoint",
                    "source_checkpoint.json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn('"status": "complete"', stdout.getvalue())
        for source_text in self.source_text.values():
            self.assertNotIn(source_text.strip(), stdout.getvalue())
        self.assertIn("source_snapshot_id", stdout.getvalue())


_HUMAN_MARKER = "<!-- translation-workflow-human-bundle:v1"


if __name__ == "__main__":
    unittest.main()
