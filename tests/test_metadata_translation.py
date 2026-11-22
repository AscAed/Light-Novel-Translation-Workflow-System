import asyncio
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from metadata_translation import (
    create_metadata_translation_candidate,
    create_metadata_translation_plan,
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)
from metadata_translation_review import (
    create_metadata_translation_review_template,
    finalize_metadata_translation_review,
    verify_metadata_translation_review,
    verify_metadata_translation_review_template,
)
from metadata_translation_freshness import (
    verify_metadata_translation_plan_freshness,
)
from metadata_translation_generation import (
    build_metadata_translation_generation_plan,
    plan_metadata_translation_generation,
)
from metadata_translation_publication import (
    create_metadata_translation_artifact,
    verify_metadata_translation_artifact,
)
from metadata_translation_executor import (
    _lock_generation_run,
    execute_metadata_translation_generation,
)
from metadata_translation_epub import create_epub_metadata_catalog
from scripts.import_metadata_translation_candidate import (
    import_metadata_translation_candidate,
    main as import_candidate_main,
)
from scripts.plan_metadata_translation_generation import (
    main as plan_generation_main,
)
from scripts.review_metadata_translation_candidate import (
    main as review_candidate_main,
)
from scripts.prepare_metadata_translation import (
    _current_work_metadata_version_id,
    main as prepare_main,
    prepare_metadata_translation,
)
from scripts.publish_metadata_translation import (
    publish_metadata_translation_artifact,
)
from scripts.generate_metadata_translation_candidate import (
    main as generate_candidate_main,
)
from scripts.build_epub_candidate_with_metadata import (
    build_epub_candidate_with_metadata,
)
from source_ingestion import source_artifact_id


class MetadataTranslationTests(unittest.TestCase):
    class CharacterTokenizer:
        @staticmethod
        def encode(text):
            return SimpleNamespace(ids=[0] * len(text))

    class FakeMetadataClient:
        def __init__(self, *, omit_last_translation=False):
            self.calls = []
            self.omit_last_translation = omit_last_translation
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_completion)
            )

        async def create_completion(self, **request):
            self.calls.append(request)
            user_text = request["messages"][1]["content"]
            records = json.loads(user_text.split("\n", 1)[1])
            translations = [
                {
                    "field_id": item["field_id"],
                    "translation_value": f"中文 {item['field_id']}",
                }
                for item in records
            ]
            if self.omit_last_translation:
                translations = translations[:-1]
                self.omit_last_translation = False
            response_text = json.dumps(
                {"translations": translations},
                ensure_ascii=False,
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=response_text),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

        async def close(self):
            return None

    def _verified_bundle(self, **overrides):
        work_id = "work-1"
        work_metadata = {
            "title": "Synthetic work",
            "catchphrase": "Synthetic catchphrase",
            "introduction": "Synthetic introduction",
            "genre": None,
            "tags": ["Synthetic tag", "　"],
            "author_name": "Preserved author",
            "author_screen_name": "stable-author-id",
            "serial_status": "ongoing",
            "published_at": "2026-01-01T00:00:00Z",
            "last_episode_published_at": None,
            "public_episode_count": 2,
        }
        bundle = {
            "work_id": work_id,
            "work_metadata": work_metadata,
            "work_metadata_version_id": "v-work-1",
            "provenance": {
                "catalog": {"sha256": "a" * 64},
                "source_manifest": {"sha256": "b" * 64},
            },
            "groups": [
                {
                    "group_id": "group-1",
                    "chapter_id": "chapter-1",
                    "title": "Synthetic chapter",
                },
                {
                    "group_id": "group-2",
                    "chapter_id": "chapter-2",
                    "title": None,
                },
            ],
            "episodes": [
                {
                    "episode_id": "episode-1",
                    "position": 1,
                    "title": "Synthetic episode one",
                    "episode_metadata_version_id": "v-episode-1",
                    "source_text": "Must not be copied into this plan.",
                },
                {
                    "episode_id": "episode-2",
                    "position": 2,
                    "title": "Synthetic episode two",
                    "episode_metadata_version_id": "v-episode-2",
                    "source_text": "Must not be copied into this plan.",
                },
            ],
        }
        bundle.update(overrides)
        return {
            "status": "verified",
            "work_id": work_id,
            "episode_count": 2,
            "bundle": bundle,
        }

    @staticmethod
    def _translations(plan):
        return {
            item["field_id"]: f"译文 {index}"
            for index, item in enumerate(plan["fields"], start=1)
            if item["source_value"] is not None
        }

    @staticmethod
    def _manual_provenance():
        return {
            "declared_origin": "manual",
            "provider_id": None,
            "model_id": None,
            "prompt_sha256": None,
            "recorded_at_utc": "2026-11-22T00:00:00Z",
        }

    def _candidate(self, plan):
        return create_metadata_translation_candidate(
            plan,
            self._translations(plan),
            self._manual_provenance(),
        )

    @staticmethod
    def _reviewed_template(plan, candidate):
        template = create_metadata_translation_review_template(plan, candidate)
        template["reviewer_id"] = "reviewer-local-1"
        template["reviewed_at_utc"] = "2026-11-22T01:02:03Z"
        for item in template["decisions"]:
            for check, value in item["quality_checks"].items():
                value["status"] = (
                    "not_applicable"
                    if check in {"terminology", "localization"}
                    else "pass"
                )
                value["rationale"] = (
                    f"Checked {check} for {item['field_id']}."
                )
        return template

    @staticmethod
    def _review_source_snapshot():
        return {"catalog_sha256": "b" * 64, "manifest_sha256": "d" * 64}

    @staticmethod
    def _current_field_sources(plan):
        return {
            item["field_id"]: {
                "source_version_id": item["source_version_id"],
                "source_sha256": item["source_sha256"],
            }
            for item in plan["fields"]
        }

    def _write_freshness_sources(
        self,
        root,
        plan,
        *,
        changed_work_title=False,
        changed_chapter_title=False,
        changed_episode_title=False,
    ):
        source_root = root / "SourceArchive"
        source_root.mkdir()
        bundle = self._verified_bundle()["bundle"]
        work_metadata = dict(bundle["work_metadata"])
        if changed_work_title:
            work_metadata["title"] = "Changed work title"
        work_bytes = json.dumps(
            {
                "schema_version": 1,
                "work_id": plan["work_id"],
                "recorded_at_utc": "2026-11-22T00:00:00Z",
                "metadata": work_metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        artifacts = [
            {
                "artifact_id": source_artifact_id(
                    plan["work_id"], "work", "metadata"
                ),
                "version_id": (
                    "v-work-1-changed" if changed_work_title else "v-work-1"
                ),
                "kind": "work",
                "content_sha256": hashlib.sha256(work_bytes).hexdigest(),
                "relative_path": "work-metadata.json",
                "parent_version_ids": [],
            }
        ]
        (source_root / "work-metadata.json").write_bytes(work_bytes)
        episode_records = []
        for index, episode in enumerate(bundle["episodes"], start=1):
            title = episode["title"]
            if changed_episode_title and index == 1:
                title = "Changed episode title"
            episode_metadata = {
                "schema_version": 1,
                "work_id": plan["work_id"],
                "episode_id": episode["episode_id"],
                "title": title,
                "position": episode["position"],
                "source_ref": None,
            }
            content = json.dumps(
                episode_metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            relative_path = f"episode-{index}.json"
            (source_root / relative_path).write_bytes(content)
            version_id = (
                "v-episode-1-changed"
                if changed_episode_title and index == 1
                else episode["episode_metadata_version_id"]
            )
            artifacts.append(
                {
                    "artifact_id": source_artifact_id(
                        plan["work_id"], "episode", episode["episode_id"]
                    ),
                    "version_id": version_id,
                    "kind": "episode",
                    "content_sha256": hashlib.sha256(content).hexdigest(),
                    "relative_path": relative_path,
                    "parent_version_ids": [],
                }
            )
            episode_records.append(
                SimpleNamespace(
                    metadata=SimpleNamespace(
                        episode_id=episode["episode_id"],
                        title=title,
                        position=episode["position"],
                    )
                )
            )
        (source_root / "source_manifest.json").write_text(
            json.dumps({"schema_version": 1, "artifacts": artifacts}),
            encoding="utf-8",
        )
        catalog = {
            "schema_version": 3,
            "work_id": plan["work_id"],
            "work_metadata": work_metadata,
            "episodes": tuple(episode_records),
            "chapters": [
                {
                    "group_id": group["group_id"],
                    "title": (
                        "Changed chapter title"
                        if changed_chapter_title and index == 0
                        else group["title"]
                    ),
                }
                for index, group in enumerate(bundle["groups"])
            ],
            "sha256": (
                "c" * 64
                if (
                    changed_work_title
                    or changed_chapter_title
                    or changed_episode_title
                )
                else bundle["provenance"]["catalog"]["sha256"]
            ),
        }
        return source_root, catalog

    def _plan_generation(
        self,
        plan,
        source_root,
        catalog,
        *,
        max_estimated_cost=1.0,
        **overrides,
    ):
        arguments = {
            "source_root": str(source_root),
            "catalog_relative_path": "catalog.json",
            "manifest_relative_path": "source_manifest.json",
            "tokenizer_json": "synthetic-tokenizer.json",
            "model_id": "operator-declared-model",
            "context_window_tokens": 1000,
            "max_output_tokens": 100,
            "safety_margin_tokens": 100,
            "message_overhead_tokens": 4,
            "input_price_per_million_tokens": 10.0,
            "output_price_per_million_tokens": 20.0,
            "max_estimated_cost": max_estimated_cost,
            "max_provider_calls": 10,
        }
        arguments.update(overrides)
        with patch(
            "metadata_translation_freshness._load_catalog_snapshot",
            return_value=catalog,
        ), patch(
            "metadata_translation_generation.load_tokenizer_json",
            return_value=(self.CharacterTokenizer(), "e" * 64),
        ):
            return plan_metadata_translation_generation(plan, **arguments)

    def _build_generation(self, plan, source_root, catalog, **overrides):
        arguments = {
            "source_root": str(source_root),
            "catalog_relative_path": "catalog.json",
            "manifest_relative_path": "source_manifest.json",
            "tokenizer_json": "synthetic-tokenizer.json",
            "model_id": "operator-declared-model",
            "context_window_tokens": 1000,
            "max_output_tokens": 100,
            "safety_margin_tokens": 100,
            "message_overhead_tokens": 4,
            "input_price_per_million_tokens": 10.0,
            "output_price_per_million_tokens": 20.0,
            "max_estimated_cost": 1.0,
            "max_provider_calls": 10,
        }
        arguments.update(overrides)
        with patch(
            "metadata_translation_freshness._load_catalog_snapshot",
            return_value=catalog,
        ), patch(
            "metadata_translation_generation.load_tokenizer_json",
            return_value=(self.CharacterTokenizer(), "e" * 64),
        ):
            return build_metadata_translation_generation_plan(plan, **arguments)

    def test_plan_tracks_translatable_metadata_and_missing_fields(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        digest = verify_metadata_translation_plan(plan)

        self.assertEqual(digest, plan["plan_sha256"])
        self.assertEqual(plan["source_locale"], "ja-JP")
        self.assertEqual(plan["target_locale"], "zh-CN")
        self.assertEqual(plan["field_count"], 10)
        self.assertEqual(plan["pending_count"], 7)
        self.assertEqual(plan["missing_count"], 3)
        self.assertEqual(
            [item["field_id"] for item in plan["fields"][:6]],
            [
                "work.title",
                "work.catchphrase",
                "work.introduction",
                "work.genre",
                "work.tags.0001",
                "work.tags.0002",
            ],
        )
        fields = {item["field_id"]: item for item in plan["fields"]}
        self.assertEqual(fields["work.title"]["status"], "pending_translation")
        self.assertEqual(
            fields["work.title"]["source_version_id"],
            "v-work-1",
        )
        self.assertEqual(
            fields["work.title"]["source_sha256"],
            hashlib.sha256("Synthetic work".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(fields["work.genre"]["status"], "missing_source")
        self.assertIsNone(fields["work.genre"]["source_value"])
        self.assertEqual(fields["work.tags.0002"]["status"], "missing_source")
        self.assertEqual(
            fields["chapter.group-2.title"]["status"],
            "missing_source",
        )
        self.assertNotIn("author_name", json.dumps(plan))
        self.assertNotIn("serial_status", json.dumps(plan))
        self.assertNotIn("source_text", json.dumps(plan))
        self.assertTrue(
            all(item["translation_value"] is None for item in plan["fields"])
        )

    def test_plan_digest_binds_source_text_and_rejects_mutation(self):
        verified = self._verified_bundle()
        first = create_metadata_translation_plan(verified)
        verified["bundle"]["work_metadata"]["introduction"] = "Changed source"
        second = create_metadata_translation_plan(verified)

        self.assertNotEqual(first["plan_sha256"], second["plan_sha256"])
        first["fields"][0]["source_value"] = "tampered"
        with self.assertRaisesRegex(ValueError, "digest"):
            verify_metadata_translation_plan(first)

    def test_candidate_binds_complete_translation_to_current_plan(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = create_metadata_translation_candidate(
            plan,
            self._translations(plan),
            self._manual_provenance(),
        )

        self.assertEqual(
            verify_metadata_translation_candidate(candidate, plan),
            candidate["candidate_sha256"],
        )
        self.assertEqual(candidate["status"], "review_pending")
        self.assertEqual(candidate["field_count"], plan["pending_count"])
        self.assertEqual(
            candidate["missing_source_count"],
            plan["missing_count"],
        )
        self.assertTrue(
            all(item["review_status"] == "pending" for item in candidate["fields"])
        )
        self.assertEqual(
            [item["field_id"] for item in candidate["fields"]],
            [
                item["field_id"]
                for item in plan["fields"]
                if item["source_value"] is not None
            ],
        )
        self.assertNotIn(
            "Must not be copied into this plan.",
            json.dumps(candidate, ensure_ascii=False),
        )

    def test_candidate_rejects_incomplete_extra_and_empty_translations(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        translations = self._translations(plan)
        with self.assertRaisesRegex(ValueError, "every source-backed field"):
            create_metadata_translation_candidate(
                plan,
                {key: value for key, value in translations.items() if key != "work.title"},
                self._manual_provenance(),
            )

        with self.assertRaisesRegex(ValueError, "every source-backed field"):
            create_metadata_translation_candidate(
                plan,
                {**translations, "unknown.field": "unexpected"},
                self._manual_provenance(),
            )

        with self.assertRaisesRegex(ValueError, "empty or invalid"):
            create_metadata_translation_candidate(
                plan,
                {**translations, "work.title": " \t"},
                self._manual_provenance(),
            )

    def test_candidate_rejects_plans_with_no_source_backed_fields(self):
        verified = self._verified_bundle()
        work_metadata = verified["bundle"]["work_metadata"]
        for field_name in ("title", "catchphrase", "introduction", "genre"):
            work_metadata[field_name] = None
        work_metadata["tags"] = ["　"]
        for group in verified["bundle"]["groups"]:
            group["title"] = None
        for episode in verified["bundle"]["episodes"]:
            episode["title"] = None
        plan = create_metadata_translation_plan(verified)
        self.assertEqual(plan["pending_count"], 0)

        with self.assertRaisesRegex(ValueError, "at least one source-backed field"):
            create_metadata_translation_candidate(
                plan,
                {},
                self._manual_provenance(),
            )

    def test_review_template_binds_candidate_fields_and_starts_pending(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        template = create_metadata_translation_review_template(plan, candidate)

        verify_metadata_translation_review_template(template, plan, candidate)
        self.assertEqual(template["status"], "pending_review")
        self.assertEqual(template["schema_version"], 2)
        self.assertEqual(template["quality_rules_version"], "metadata-translation-semantic-v1")
        self.assertRegex(template["quality_rules_sha256"], r"^[0-9a-f]{64}$")
        self.assertIsNone(template["reviewer_id"])
        self.assertEqual(template["field_count"], candidate["field_count"])
        self.assertTrue(
            all(
                check["status"] == "pending"
                for item in template["decisions"]
                for check in item["quality_checks"].values()
            )
        )
        template["decisions"][0]["translation_value"] = "changed"
        with self.assertRaisesRegex(ValueError, "not bound to its candidate"):
            verify_metadata_translation_review_template(template, plan, candidate)

        template = create_metadata_translation_review_template(plan, candidate)
        template["quality_criteria"]["source_fidelity"] = "approve everything"
        with self.assertRaisesRegex(ValueError, "header is invalid"):
            verify_metadata_translation_review_template(template, plan, candidate)

    def test_freshness_verifier_accepts_current_sources_and_rejects_new_episode_version(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root, catalog = self._write_freshness_sources(root, plan)
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ):
                result = verify_metadata_translation_plan_freshness(
                    plan,
                    source_root=str(source_root),
                    catalog_relative_path="catalog.json",
                )
            self.assertEqual(result["status"], "current")
            self.assertEqual(result["field_count"], plan["field_count"])
            self.assertEqual(result["catalog_sha256"], "a" * 64)
            self.assertTrue(
                all(status == "current" for status in result["field_statuses"].values())
            )

        changed_field_ids = {
            "changed_work_title": "work.title",
            "changed_chapter_title": "chapter.group-1.title",
            "changed_episode_title": "episode.episode-1.title",
        }
        for changed_field, expected_stale_id in changed_field_ids.items():
            with self.subTest(changed_field=changed_field):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source_root, catalog = self._write_freshness_sources(
                        root,
                        plan,
                        **{changed_field: True},
                    )
                    with patch(
                        "metadata_translation_freshness._load_catalog_snapshot",
                        return_value=catalog,
                    ):
                        with self.assertRaises(ValueError):
                            verify_metadata_translation_plan_freshness(
                                plan,
                                source_root=str(source_root),
                                catalog_relative_path="catalog.json",
                            )
                        result = verify_metadata_translation_plan_freshness(
                            plan,
                            source_root=str(source_root),
                            catalog_relative_path="catalog.json",
                            allow_field_drift=True,
                        )
                    self.assertEqual(result["status"], "stale")
                    self.assertEqual(
                        result["field_statuses"][expected_stale_id],
                        "stale",
                    )
                    unaffected_id = "episode.episode-2.title"
                    self.assertEqual(
                        result["field_statuses"][unaffected_id],
                        "current",
                    )

    def test_generation_plan_is_source_bound_budgeted_and_value_free(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            source_root, catalog = self._write_freshness_sources(
                Path(temporary),
                plan,
            )
            manifest_sha256 = hashlib.sha256(
                (source_root / "source_manifest.json").read_bytes()
            ).hexdigest()
            report = self._plan_generation(plan, source_root, catalog)

        report_text = json.dumps(report, ensure_ascii=False)
        self.assertEqual(report["status"], "ready_for_operator_review")
        self.assertEqual(report["field_count"], plan["pending_count"])
        self.assertGreater(report["planned_batch_count"], 1)
        self.assertLessEqual(report["planned_batch_count"], report["max_provider_calls"])
        self.assertEqual(report["max_input_tokens_per_request"], 800)
        self.assertEqual(report["model_id_source"], "operator_declared_not_verified")
        self.assertEqual(report["tokenizer_sha256"], "e" * 64)
        self.assertEqual(report["source_snapshot"]["catalog_sha256"], "a" * 64)
        self.assertEqual(report["source_snapshot"]["manifest_sha256"], manifest_sha256)
        self.assertLessEqual(
            report["estimated_cost_upper_bound"],
            report["max_estimated_cost"],
        )
        self.assertFalse(report["provider_cost_cap_enforced"])
        self.assertEqual(report["provider_calls_made"], 0)
        self.assertEqual(report["files_written"], 0)
        self.assertFalse(report["source_values_in_report"])
        self.assertNotIn("Synthetic work", report_text)
        self.assertNotIn("Synthetic introduction", report_text)

    def test_generation_plan_rejects_stale_source_and_exceeded_budgets(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            source_root, changed_catalog = self._write_freshness_sources(
                Path(temporary),
                plan,
                changed_episode_title=True,
            )
            with self.assertRaises(ValueError):
                self._plan_generation(plan, source_root, changed_catalog)

        with tempfile.TemporaryDirectory() as temporary:
            source_root, catalog = self._write_freshness_sources(
                Path(temporary),
                plan,
            )
            with self.assertRaisesRegex(ValueError, "cost budget"):
                self._plan_generation(
                    plan,
                    source_root,
                    catalog,
                    max_estimated_cost=1e-12,
                    input_price_per_million_tokens=1000.0,
                    output_price_per_million_tokens=1000.0,
                )
            with self.assertRaisesRegex(ValueError, "provider-call limit"):
                self._plan_generation(
                    plan,
                    source_root,
                    catalog,
                    max_provider_calls=1,
                )

    def test_generation_plan_rejects_non_finite_or_unrepresentable_cost_inputs(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            source_root, catalog = self._write_freshness_sources(
                Path(temporary),
                plan,
            )
            with self.assertRaisesRegex(ValueError, "finite positive number"):
                self._plan_generation(
                    plan,
                    source_root,
                    catalog,
                    input_price_per_million_tokens=10**10000,
                )

    def test_generation_plan_cli_reports_summary_without_writing_or_logging_values(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            source_root, catalog = self._write_freshness_sources(project, plan)
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            arguments = [
                "--plan",
                str(plan_path),
                "--source-root",
                str(source_root),
                "--catalog",
                "catalog.json",
                "--tokenizer-json",
                "synthetic-tokenizer.json",
                "--model-id",
                "operator-declared-model",
                "--context-window-tokens",
                "1000",
                "--max-output-tokens",
                "100",
                "--safety-margin-tokens",
                "100",
                "--message-overhead-tokens",
                "4",
                "--input-price-per-million-tokens",
                "10",
                "--output-price-per-million-tokens",
                "20",
                "--max-estimated-cost",
                "1",
            ]
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), patch(
                "metadata_translation_generation.load_tokenizer_json",
                return_value=(self.CharacterTokenizer(), "e" * 64),
            ), patch("sys.stdout") as output:
                self.assertEqual(plan_generation_main(arguments), 0)
            stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertIn('"provider_calls_made": 0', stdout)
            self.assertIn('"files_written": 0', stdout)
            self.assertNotIn("Synthetic work", stdout)
            self.assertNotIn("Synthetic introduction", stdout)
            self.assertEqual(
                {path.name for path in plans_root.iterdir()},
                {"metadata-plan.json"},
            )
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), patch(
                "metadata_translation_generation.load_tokenizer_json",
                return_value=(self.CharacterTokenizer(), "e" * 64),
            ), patch(
                "scripts.generate_metadata_translation_candidate._load_execution_route",
                side_effect=AssertionError("invalid names must fail before route loading"),
            ), redirect_stderr(io.StringIO()):
                self.assertEqual(
                    generate_candidate_main(
                        arguments
                        + [
                            "--execute",
                            "--candidate-name",
                            "..\\outside.json",
                        ]
                    ),
                    1,
                )
            self.assertEqual(
                {path.name for path in plans_root.iterdir()},
                {"metadata-plan.json"},
            )

    def test_generation_cli_executes_bounded_batches_and_resumes_from_checkpoints(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            source_root, catalog = self._write_freshness_sources(project, plan)
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            client = self.FakeMetadataClient()
            arguments = [
                "--plan",
                str(plan_path),
                "--source-root",
                str(source_root),
                "--catalog",
                "catalog.json",
                "--tokenizer-json",
                "synthetic-tokenizer.json",
                "--model-id",
                "operator-declared-model",
                "--context-window-tokens",
                "1000",
                "--max-output-tokens",
                "100",
                "--safety-margin-tokens",
                "100",
                "--message-overhead-tokens",
                "4",
                "--input-price-per-million-tokens",
                "10",
                "--output-price-per-million-tokens",
                "20",
                "--max-estimated-cost",
                "1",
                "--candidate-name",
                "provider-candidate.json",
                "--execute",
            ]
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), patch(
                "metadata_translation_generation.load_tokenizer_json",
                return_value=(self.CharacterTokenizer(), "e" * 64),
            ), patch(
                "scripts.generate_metadata_translation_candidate._load_execution_route",
                return_value=("synthetic-provider", "request-model", "f" * 64, client),
            ), patch("sys.stdout") as output:
                self.assertEqual(generate_candidate_main(arguments), 0)

            stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            result = json.loads(stdout.strip())
            self.assertEqual(result["status"], "metadata_translation_candidate_created")
            self.assertEqual(result["provider_calls_made"], len(client.calls))
            self.assertGreater(result["provider_calls_made"], 1)
            self.assertLessEqual(
                result["provider_calls_made"],
                result["field_count"],
            )
            self.assertEqual(result["model_id"], "request-model")
            self.assertEqual(result["review_status"], "review_pending")
            self.assertFalse(result["provider_cost_cap_enforced"])
            self.assertNotIn("Synthetic work", stdout)
            self.assertNotIn("中文 ", stdout)
            self.assertTrue(
                all(
                    request["max_tokens"] == 100
                    and request["model"] == "request-model"
                    for request in client.calls
                )
            )

            candidate_path = plans_root / "provider-candidate.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(
                verify_metadata_translation_candidate(candidate, plan),
                candidate["candidate_sha256"],
            )
            self.assertEqual(candidate["status"], "review_pending")
            receipt_path = plans_root / result["receipt_name"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["candidate_sha256"], result["candidate_sha256"])
            self.assertEqual(
                receipt["provider_calls_for_run"],
                result["provider_calls_made"],
            )
            self.assertNotIn("translations", receipt)
            self.assertNotIn("Synthetic work", receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                len(list(plans_root.glob("*.checkpoint.json"))),
                result["provider_calls_made"],
            )
            self.assertEqual(
                len(list(plans_root.glob("*.intent.json"))),
                result["provider_calls_made"],
            )

            resumed_client = self.FakeMetadataClient()
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), patch(
                "metadata_translation_generation.load_tokenizer_json",
                return_value=(self.CharacterTokenizer(), "e" * 64),
            ), patch(
                "scripts.generate_metadata_translation_candidate._load_execution_route",
                return_value=(
                    "synthetic-provider",
                    "request-model",
                    "f" * 64,
                    resumed_client,
                ),
            ), patch("sys.stdout") as output:
                self.assertEqual(generate_candidate_main(arguments), 0)
            resumed_stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            resumed_result = json.loads(resumed_stdout.strip())
            self.assertEqual(
                resumed_result["status"],
                "metadata_translation_candidate_reused",
            )
            self.assertEqual(resumed_result["provider_calls_made"], 0)
            self.assertEqual(
                resumed_result["provider_calls_reused"],
                result["provider_calls_made"],
            )
            self.assertEqual(resumed_client.calls, [])
            self.assertEqual(
                resumed_result["receipt_sha256"],
                result["receipt_sha256"],
            )
            self.assertEqual(
                candidate_path.read_text(encoding="utf-8"),
                json.dumps(
                    candidate,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
            )

    def test_generation_cli_default_mode_does_not_load_provider_or_write(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            source_root, catalog = self._write_freshness_sources(project, plan)
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            arguments = [
                "--plan",
                str(plan_path),
                "--source-root",
                str(source_root),
                "--catalog",
                "catalog.json",
                "--tokenizer-json",
                "synthetic-tokenizer.json",
                "--model-id",
                "operator-declared-model",
                "--context-window-tokens",
                "1000",
                "--max-output-tokens",
                "100",
                "--safety-margin-tokens",
                "100",
                "--message-overhead-tokens",
                "4",
                "--input-price-per-million-tokens",
                "10",
                "--output-price-per-million-tokens",
                "20",
                "--max-estimated-cost",
                "1",
            ]
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), patch(
                "metadata_translation_generation.load_tokenizer_json",
                return_value=(self.CharacterTokenizer(), "e" * 64),
            ), patch(
                "scripts.generate_metadata_translation_candidate._load_execution_route",
                side_effect=AssertionError("provider route must stay unloaded"),
            ), patch("sys.stdout") as output:
                self.assertEqual(generate_candidate_main(arguments), 0)
            stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertIn('"provider_calls_made": 0', stdout)
            self.assertNotIn("Synthetic work", stdout)
            self.assertEqual(
                {path.name for path in plans_root.iterdir()},
                {"metadata-plan.json"},
            )

    def test_generation_refuses_to_repeat_a_request_with_no_checkpoint(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            source_root, catalog = self._write_freshness_sources(project, plan)
            generation_plan = self._build_generation(plan, source_root, catalog)
            common = {
                "plan": plan,
                "generation_plan": generation_plan,
                "source_root": str(source_root),
                "catalog_relative_path": "catalog.json",
                "manifest_relative_path": "source_manifest.json",
                "plans_root": plans_root,
                "candidate_name": "candidate.json",
                "model_id": "operator-declared-model",
                "request_model": "request-model",
                "provider_id": "synthetic-provider",
                "provider_fingerprint": "f" * 64,
            }
            failed_client = self.FakeMetadataClient(omit_last_translation=True)
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), self.assertRaisesRegex(ValueError, "does not cover"):
                asyncio.run(
                    execute_metadata_translation_generation(
                        client=failed_client,
                        **common,
                    )
                )
            self.assertEqual(len(failed_client.calls), 1)
            self.assertEqual(list(plans_root.glob("*.checkpoint.json")), [])
            self.assertEqual(len(list(plans_root.glob("*.intent.json"))), 1)

            retry_client = self.FakeMetadataClient()
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ), self.assertRaisesRegex(ValueError, "may have been sent"):
                asyncio.run(
                    execute_metadata_translation_generation(
                        client=retry_client,
                        **common,
                    )
                )
            self.assertEqual(retry_client.calls, [])

    def test_generation_rechecks_live_source_before_sending_each_batch(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            source_root, catalog = self._write_freshness_sources(project, plan)
            changed_catalog = dict(catalog)
            changed_catalog["sha256"] = "d" * 64
            generation_plan = self._build_generation(plan, source_root, catalog)
            client = self.FakeMetadataClient()
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                side_effect=[catalog, changed_catalog],
            ), self.assertRaisesRegex(ValueError, "sources changed after"):
                asyncio.run(
                    execute_metadata_translation_generation(
                        plan=plan,
                        generation_plan=generation_plan,
                        source_root=str(source_root),
                        catalog_relative_path="catalog.json",
                        manifest_relative_path="source_manifest.json",
                        plans_root=plans_root,
                        candidate_name="candidate.json",
                        model_id="operator-declared-model",
                        request_model="request-model",
                        provider_id="synthetic-provider",
                        provider_fingerprint="f" * 64,
                        client=client,
                    )
                )
            self.assertEqual(client.calls, [])
            self.assertEqual(list(plans_root.glob("*.intent.json")), [])
            self.assertEqual(list(plans_root.glob("*.checkpoint.json")), [])

    def test_generation_run_lock_refuses_concurrent_identical_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            plans_root = Path(temporary) / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            with _lock_generation_run(plans_root, "a" * 64):
                with self.assertRaisesRegex(ValueError, "run is active"):
                    with _lock_generation_run(plans_root, "a" * 64):
                        self.fail("The second lock acquisition must be rejected.")

    def test_review_approves_only_complete_approved_decisions(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        template = self._reviewed_template(plan, candidate)

        report = finalize_metadata_translation_review(
            template,
            plan,
            candidate,
            self._review_source_snapshot(),
        )

        self.assertEqual(report["status"], "approved")
        self.assertEqual(
            report["decision_counts"]["approved"],
            candidate["field_count"],
        )
        self.assertEqual(report["quality_rules_version"], "metadata-translation-semantic-v1")
        self.assertEqual(
            report["quality_rules_sha256"],
            template["quality_rules_sha256"],
        )
        self.assertEqual(
            verify_metadata_translation_review(report, plan, candidate),
            report["review_sha256"],
        )
        self.assertNotIn("reviewer_authenticated", report)

    def test_review_rejection_or_escalation_requires_resolution(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        for decision in ("rejected", "escalated"):
            with self.subTest(decision=decision):
                template = self._reviewed_template(plan, candidate)
                template["decisions"][0]["quality_checks"]["source_fidelity"][
                    "status"
                ] = "fail" if decision == "rejected" else "uncertain"
                report = finalize_metadata_translation_review(
                    template,
                    plan,
                    candidate,
                    self._review_source_snapshot(),
                )
                self.assertEqual(report["status"], "needs_resolution")
                self.assertEqual(report["decision_counts"][decision], 1)

    def test_review_rejects_pending_missing_rationale_and_non_string_decision(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        template = self._reviewed_template(plan, candidate)

        template["decisions"][0]["quality_checks"]["source_fidelity"][
            "status"
        ] = "pending"
        with self.assertRaisesRegex(ValueError, "invalid status"):
            finalize_metadata_translation_review(
                template,
                plan,
                candidate,
                self._review_source_snapshot(),
            )

        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["source_fidelity"][
            "rationale"
        ] = " "
        with self.assertRaisesRegex(ValueError, "rationale"):
            finalize_metadata_translation_review(
                template,
                plan,
                candidate,
                self._review_source_snapshot(),
            )

        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["source_fidelity"][
            "status"
        ] = ["pass"]
        with self.assertRaisesRegex(ValueError, "invalid status"):
            finalize_metadata_translation_review(
                template,
                plan,
                candidate,
                self._review_source_snapshot(),
            )

    def test_semantic_rubric_escalates_annotation_and_rejects_term_conflict(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)

        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["localization"][
            "status"
        ] = "annotation_required"
        report = finalize_metadata_translation_review(
            template,
            plan,
            candidate,
            self._review_source_snapshot(),
        )
        self.assertEqual(report["decisions"][0]["decision"], "escalated")

        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["terminology"][
            "status"
        ] = "conflict"
        report = finalize_metadata_translation_review(
            template,
            plan,
            candidate,
            self._review_source_snapshot(),
        )
        self.assertEqual(report["decisions"][0]["decision"], "rejected")

        for check in ("source_fidelity", "completeness", "naturalness"):
            with self.subTest(check=check):
                template = self._reviewed_template(plan, candidate)
                template["decisions"][0]["quality_checks"][check][
                    "status"
                ] = "fail"
                report = finalize_metadata_translation_review(
                    template,
                    plan,
                    candidate,
                    self._review_source_snapshot(),
                )
                self.assertEqual(report["decisions"][0]["decision"], "rejected")

    def test_review_report_rejects_decision_that_disagrees_with_checks(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["source_fidelity"][
            "status"
        ] = "fail"
        report = finalize_metadata_translation_review(
            template,
            plan,
            candidate,
            self._review_source_snapshot(),
        )
        report["decisions"][0]["decision"] = "approved"
        report["review_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key != "review_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "does not match its semantic checks"):
            verify_metadata_translation_review(report, plan, candidate)

    def test_review_report_digest_rejects_mutation(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        report = finalize_metadata_translation_review(
            self._reviewed_template(plan, candidate),
            plan,
            candidate,
            self._review_source_snapshot(),
        )
        report["decision_counts"]["approved"] -= 1
        with self.assertRaisesRegex(ValueError, "outcome|digest"):
            verify_metadata_translation_review(report, plan, candidate)

    def test_approved_metadata_artifact_preserves_missing_fields_and_lineage(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        source_snapshot = self._review_source_snapshot()
        report = finalize_metadata_translation_review(
            self._reviewed_template(plan, candidate),
            plan,
            candidate,
            source_snapshot,
        )

        artifact = create_metadata_translation_artifact(
            plan,
            candidate,
            report,
            source_snapshot,
        )

        self.assertEqual(artifact["status"], "approved")
        self.assertEqual(artifact["field_count"], plan["field_count"])
        self.assertEqual(
            artifact["translated_field_count"] + artifact["missing_source_count"],
            artifact["field_count"],
        )
        self.assertEqual(artifact["missing_source_count"], plan["missing_count"])
        self.assertTrue(
            any(item["status"] == "missing_source" for item in artifact["fields"])
        )
        self.assertTrue(
            all(
                item["status"] == "approved"
                for item in artifact["fields"]
                if item["source_value"] is not None
            )
        )
        self.assertEqual(
            verify_metadata_translation_artifact(
                artifact,
                plan,
                candidate,
                report,
                source_snapshot,
            ),
            artifact["artifact_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "current source snapshot"):
            create_metadata_translation_artifact(
                plan,
                candidate,
                report,
                {"catalog_sha256": "e" * 64, "manifest_sha256": "d" * 64},
            )

    def test_metadata_artifact_requires_every_reviewed_field_approved(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        template = self._reviewed_template(plan, candidate)
        template["decisions"][0]["quality_checks"]["source_fidelity"][
            "status"
        ] = "fail"
        report = finalize_metadata_translation_review(
            template,
            plan,
            candidate,
            self._review_source_snapshot(),
        )
        with self.assertRaisesRegex(ValueError, "not fully approved"):
            create_metadata_translation_artifact(
                plan,
                candidate,
                report,
                self._review_source_snapshot(),
            )

    def test_epub_metadata_catalog_uses_only_current_approved_title_fields(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        source_snapshot = self._review_source_snapshot()
        review = finalize_metadata_translation_review(
            self._reviewed_template(plan, candidate),
            plan,
            candidate,
            source_snapshot,
        )
        artifact = create_metadata_translation_artifact(
            plan,
            candidate,
            review,
            source_snapshot,
        )
        epub_catalog = {
            "schema_version": 1,
            "work_id": "work-1",
            "build_id": "edition-001",
            "expected_pandoc_version": "3.9.0.2",
            "title": "Original title",
            "author": "Original author",
            "language": "zh-CN",
            "identifier": "urn:synthetic:work-1",
            "chapters": [
                {
                    "episode_id": "episode-2",
                    "position": 2,
                    "title": "Original episode title",
                    "translation_path": "episode-2.md",
                    "source_version_id": "v-episode-2",
                }
            ],
        }

        result, provenance = create_epub_metadata_catalog(
            epub_catalog,
            artifact,
            plan,
            candidate,
            review,
            source_snapshot,
            {item["field_id"]: "current" for item in plan["fields"]},
            self._current_field_sources(plan),
        )

        translated = {
            field["field_id"]: field["translation_value"]
            for field in artifact["fields"]
            if field["status"] == "approved"
        }
        self.assertEqual(result["title"], translated["work.title"])
        self.assertEqual(
            result["chapters"][0]["title"],
            translated["episode.episode-2.title"],
        )
        self.assertEqual(result["author"], "Original author")
        self.assertEqual(result["identifier"], "urn:synthetic:work-1")
        self.assertEqual(epub_catalog["title"], "Original title")
        self.assertEqual(
            provenance["artifact_sha256"],
            artifact["artifact_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "work ID or language"):
            create_epub_metadata_catalog(
                {**epub_catalog, "language": "ja-JP"},
                artifact,
                plan,
                candidate,
                review,
                source_snapshot,
                {item["field_id"]: "current" for item in plan["fields"]},
                self._current_field_sources(plan),
            )

    def test_epub_candidate_integration_revalidates_and_uses_temporary_catalog(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = self._candidate(plan)
        source_snapshot = self._review_source_snapshot()
        review = finalize_metadata_translation_review(
            self._reviewed_template(plan, candidate),
            plan,
            candidate,
            source_snapshot,
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            plans_root = project / "Workflow" / "Plans"
            metadata_root = project / "Metadata"
            plans_root.mkdir(parents=True)
            metadata_root.mkdir()
            (plans_root / "plan.json").write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            (plans_root / "candidate.json").write_text(
                json.dumps(candidate, ensure_ascii=False),
                encoding="utf-8",
            )
            (plans_root / "review.json").write_text(
                json.dumps(review, ensure_ascii=False),
                encoding="utf-8",
            )
            source_root = project / "SourceArchive"
            source_root.mkdir()
            with patch(
                "scripts.publish_metadata_translation."
                "verify_metadata_translation_plan_freshness",
                return_value=source_snapshot,
            ):
                artifact_path, artifact, reused = (
                    publish_metadata_translation_artifact(
                        plan_path=str(plans_root / "plan.json"),
                        candidate_name="candidate.json",
                        review_name="review.json",
                        source_root=str(source_root),
                        catalog_relative_path="metadata-catalog.json",
                        artifact_name="approved.json",
                    )
                )
            self.assertEqual(artifact_path, metadata_root / "approved.json")
            self.assertFalse(reused)
            input_root = project / "EPUBInputs"
            input_root.mkdir()
            epub_catalog = {
                "schema_version": 1,
                "work_id": "work-1",
                "build_id": "edition-001",
                "expected_pandoc_version": "3.9.0.2",
                "title": "Original title",
                "author": "Original author",
                "language": "zh-CN",
                "identifier": "urn:synthetic:work-1",
                "chapters": [
                    {
                        "episode_id": "episode-1",
                        "position": 1,
                        "title": "Original episode title",
                        "translation_path": "episode-1.md",
                        "source_version_id": "v-episode-1",
                    }
                ],
            }
            original_catalog_bytes = json.dumps(
                epub_catalog,
                ensure_ascii=False,
            ).encode("utf-8")
            (input_root / "catalog.json").write_bytes(original_catalog_bytes)
            captured = {}

            def capture_build(**kwargs):
                captured["catalog"] = json.loads(
                    (Path(kwargs["input_root"]) / kwargs["catalog_relative_path"])
                    .read_text(encoding="utf-8")
                )
                captured["provenance"] = kwargs[
                    "metadata_translation_provenance"
                ]
                captured["temporary_catalog"] = (
                    Path(kwargs["input_root"]) / kwargs["catalog_relative_path"]
                )
                return {"status": "candidate"}

            arguments = {
                "input_root": str(input_root),
                "epub_catalog_relative_path": "catalog.json",
                "source_root": str(source_root),
                "source_manifest_relative_path": "source_manifest.json",
                "metadata_source_catalog_relative_path": "catalog.raw.json",
                "plan_path": str(plans_root / "plan.json"),
                "candidate_name": "candidate.json",
                "review_name": "review.json",
                "artifact_name": "approved.json",
                "output_root": str(project / "Output"),
                "max_chapter_bytes": 1024,
                "max_total_bytes": 2048,
                "max_output_bytes": 4096,
            }
            current_field_statuses = {
                item["field_id"]: "current"
                for item in plan["fields"]
            }
            current_field_sources = self._current_field_sources(plan)
            with patch(
                "scripts.build_epub_candidate_with_metadata."
                "verify_metadata_translation_plan_freshness",
                return_value={
                    "catalog_sha256": source_snapshot["catalog_sha256"],
                    "manifest_sha256": source_snapshot["manifest_sha256"],
                    "field_statuses": current_field_statuses,
                    "current_field_sources": current_field_sources,
                },
            ), patch(
                "scripts.build_epub_candidate_with_metadata."
                "build_epub_candidate",
                side_effect=capture_build,
            ) as build:
                result = build_epub_candidate_with_metadata(**arguments)

            self.assertEqual(build.call_count, 1)
            self.assertEqual(
                captured["catalog"]["title"],
                next(
                    item["translation_value"]
                    for item in artifact["fields"]
                    if item["field_id"] == "work.title"
                ),
            )
            self.assertEqual(
                captured["catalog"]["chapters"][0]["title"],
                next(
                    item["translation_value"]
                    for item in artifact["fields"]
                    if item["field_id"] == "episode.episode-1.title"
                ),
            )
            self.assertEqual(
                (input_root / "catalog.json").read_bytes(),
                original_catalog_bytes,
            )
            self.assertFalse(captured["temporary_catalog"].exists())
            self.assertEqual(
                result["metadata_translation_artifact_sha256"],
                artifact["artifact_sha256"],
            )

            with patch(
                "scripts.build_epub_candidate_with_metadata."
                "verify_metadata_translation_plan_freshness",
                return_value={
                    "catalog_sha256": source_snapshot["catalog_sha256"],
                    "manifest_sha256": "e" * 64,
                    "field_statuses": current_field_statuses,
                    "current_field_sources": current_field_sources,
                },
            ), patch(
                "scripts.build_epub_candidate_with_metadata."
                "build_epub_candidate",
                side_effect=capture_build,
            ) as unrelated_change_build:
                unrelated_result = build_epub_candidate_with_metadata(**arguments)
            unrelated_change_build.assert_called_once()
            self.assertEqual(
                unrelated_result["metadata_translation_artifact_sha256"],
                artifact["artifact_sha256"],
            )

            with patch(
                "scripts.build_epub_candidate_with_metadata."
                "verify_metadata_translation_plan_freshness",
                return_value={
                    "catalog_sha256": source_snapshot["catalog_sha256"],
                    "manifest_sha256": "e" * 64,
                    "field_statuses": {
                        **current_field_statuses,
                        "episode.episode-1.title": "stale",
                    },
                    "current_field_sources": current_field_sources,
                },
            ), patch(
                "scripts.build_epub_candidate_with_metadata."
                "build_epub_candidate",
            ) as stale_build, self.assertRaisesRegex(ValueError, "field is stale"):
                build_epub_candidate_with_metadata(**arguments)
            stale_build.assert_not_called()

    def test_metadata_publication_is_create_only_and_source_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            plans_root = project / "Workflow" / "Plans"
            metadata_root = project / "Metadata"
            plans_root.mkdir(parents=True)
            metadata_root.mkdir()
            plan = create_metadata_translation_plan(self._verified_bundle())
            candidate = self._candidate(plan)
            source_root, catalog = self._write_freshness_sources(project, plan)
            plan_path = plans_root / "plan.json"
            candidate_path = plans_root / "candidate.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(candidate, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ):
                freshness = verify_metadata_translation_plan_freshness(
                    plan,
                    source_root=str(source_root),
                    catalog_relative_path="catalog.json",
                )
            source_snapshot = {
                "catalog_sha256": freshness["catalog_sha256"],
                "manifest_sha256": freshness["manifest_sha256"],
            }
            report = finalize_metadata_translation_review(
                self._reviewed_template(plan, candidate),
                plan,
                candidate,
                source_snapshot,
            )
            (plans_root / "review.json").write_text(
                json.dumps(report, ensure_ascii=False),
                encoding="utf-8",
            )
            arguments = {
                "plan_path": str(plan_path),
                "candidate_name": candidate_path.name,
                "review_name": "review.json",
                "source_root": str(source_root),
                "catalog_relative_path": "catalog.json",
                "artifact_name": "metadata-approved.json",
            }
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ):
                first_path, first, first_reused = (
                    publish_metadata_translation_artifact(**arguments)
                )
                second_path, second, second_reused = (
                    publish_metadata_translation_artifact(**arguments)
                )
            self.assertEqual(first_path, metadata_root / "metadata-approved.json")
            self.assertEqual(second_path, first_path)
            self.assertFalse(first_reused)
            self.assertTrue(second_reused)
            self.assertEqual(first, second)

            first_path.write_text("conflicting data", encoding="utf-8")
            with patch(
                "metadata_translation_freshness._load_catalog_snapshot",
                return_value=catalog,
            ):
                with self.assertRaisesRegex(ValueError, "different content"):
                    publish_metadata_translation_artifact(**arguments)
            self.assertEqual(first_path.read_text(encoding="utf-8"), "conflicting data")

    @patch("metadata_translation_freshness._load_catalog_snapshot")
    def test_review_cli_is_create_only_idempotent_and_does_not_log_values(
        self,
        load_catalog_snapshot,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            plan = create_metadata_translation_plan(self._verified_bundle())
            candidate = self._candidate(plan)
            source_root, catalog = self._write_freshness_sources(project, plan)
            load_catalog_snapshot.return_value = catalog
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            candidate_path = plans_root / "candidate.json"
            candidate_path.write_text(
                json.dumps(candidate, ensure_ascii=False),
                encoding="utf-8",
            )
            common = [
                "--plan",
                str(plan_path),
                "--candidate",
                candidate_path.name,
                "--source-root",
                str(source_root),
                "--catalog",
                "catalog.json",
            ]

            with patch("sys.stdout") as output:
                self.assertEqual(
                    review_candidate_main(common + ["--create-template", "review.json"]),
                    0,
                )
            template_stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertNotIn("译文", template_stdout)
            self.assertNotIn("Synthetic work", template_stdout)
            template_path = plans_root / "review.json"
            with patch("sys.stdout") as output:
                self.assertEqual(
                    review_candidate_main(common + ["--create-template", "review.json"]),
                    0,
                )
            self.assertIn(
                "reused",
                "".join(
                    str(call.args[0])
                    for call in output.write.call_args_list
                    if call.args
                ),
            )
            template = json.loads(template_path.read_text(encoding="utf-8"))
            template["reviewer_id"] = "reviewer-local-1"
            template["reviewed_at_utc"] = "2026-11-22T01:02:03Z"
            for item in template["decisions"]:
                for check, value in item["quality_checks"].items():
                    value["status"] = (
                        "not_applicable"
                        if check in {"terminology", "localization"}
                        else "pass"
                    )
                    value["rationale"] = f"Checked {check} against source."
            template_path.write_text(
                json.dumps(template, ensure_ascii=False),
                encoding="utf-8",
            )

            review_args = common + [
                "--review-template",
                template_path.name,
                "--report-name",
                "receipt.json",
            ]
            with patch("sys.stdout") as output:
                self.assertEqual(review_candidate_main(review_args), 0)
            receipt_stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertIn('"review_status": "approved"', receipt_stdout)
            self.assertIn('"publication_performed": false', receipt_stdout)
            self.assertIn('"source_snapshot"', receipt_stdout)
            self.assertNotIn("译文", receipt_stdout)
            self.assertNotIn("Synthetic work", receipt_stdout)

            with patch("sys.stdout") as output:
                self.assertEqual(review_candidate_main(review_args), 0)
            self.assertIn(
                "reused",
                "".join(
                    str(call.args[0])
                    for call in output.write.call_args_list
                    if call.args
                ),
            )
            report = json.loads((plans_root / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(
                verify_metadata_translation_review(report, plan, candidate),
                report["review_sha256"],
            )

            template["decisions"][0]["quality_checks"]["source_fidelity"][
                "rationale"
            ] = "Changed after receipt."
            template_path.write_text(
                json.dumps(template, ensure_ascii=False),
                encoding="utf-8",
            )
            with redirect_stderr(io.StringIO()):
                self.assertEqual(review_candidate_main(review_args), 1)

    def test_candidate_rejects_source_or_translation_tampering(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        candidate = create_metadata_translation_candidate(
            plan,
            self._translations(plan),
            self._manual_provenance(),
        )
        candidate["fields"][0]["source_version_id"] = "stale-version"
        with self.assertRaisesRegex(ValueError, "not bound to its source"):
            verify_metadata_translation_candidate(candidate, plan)

        candidate = create_metadata_translation_candidate(
            plan,
            self._translations(plan),
            self._manual_provenance(),
        )
        candidate["fields"][0]["translation_value"] = "tampered"
        with self.assertRaisesRegex(ValueError, "translation digest"):
            verify_metadata_translation_candidate(candidate, plan)

    def test_candidate_requires_declared_provider_export_provenance(self):
        plan = create_metadata_translation_plan(self._verified_bundle())
        provenance = {
            "declared_origin": "provider_export",
            "provider_id": "jojo",
            "model_id": "model-test",
            "prompt_sha256": "c" * 64,
            "recorded_at_utc": "2026-11-22T00:00:00+00:00",
        }
        candidate = create_metadata_translation_candidate(
            plan,
            self._translations(plan),
            provenance,
        )
        self.assertEqual(
            candidate["translation_provenance"]["provider_id"],
            "jojo",
        )

        provenance["prompt_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "provenance is incomplete"):
            create_metadata_translation_candidate(
                plan,
                self._translations(plan),
                provenance,
            )

    def test_plan_rejects_unverified_or_duplicate_episode_inputs(self):
        verified = self._verified_bundle()
        verified["status"] = "stale"
        with self.assertRaisesRegex(ValueError, "verified"):
            create_metadata_translation_plan(verified)

        verified = self._verified_bundle()
        verified["bundle"]["episodes"][1]["episode_id"] = "episode-1"
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            create_metadata_translation_plan(verified)

        verified = self._verified_bundle()
        verified["bundle"]["episodes"][1]["position"] = 3
        with self.assertRaisesRegex(ValueError, "contiguous"):
            create_metadata_translation_plan(verified)

    def test_cli_writes_create_only_to_workflow_plans_and_logs_no_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source_root = project / "SourceArchive"
            plans_root = project / "Workflow" / "Plans"
            source_root.mkdir()
            plans_root.mkdir(parents=True)
            verified = self._verified_bundle()
            arguments = [
                "--source-root",
                str(source_root),
                "--catalog",
                "catalog.json",
                "--checkpoint",
                "checkpoint.json",
                "--bundle-set",
                "collections/set.json",
                "--human-root",
                str(project / "human"),
                "--ai-root",
                str(project / "ai"),
                "--plan-name",
                "metadata-plan.json",
            ]
            with patch(
                "scripts.prepare_metadata_translation.load_verified_ai_book_bundle",
                return_value=verified,
            ), patch(
                "scripts.prepare_metadata_translation._current_work_metadata_version_id",
                return_value="v-work-1",
            ):
                with patch("sys.stdout") as output:
                    result = prepare_main(arguments)
                output_text = "".join(
                    str(call.args[0])
                    for call in output.write.call_args_list
                    if call.args
                )
                self.assertEqual(result, 0)
                self.assertNotIn("Synthetic work", output_text)
                self.assertNotIn("Synthetic introduction", output_text)
                plan_path = plans_root / "metadata-plan.json"
                stored = json.loads(plan_path.read_text(encoding="utf-8"))
                self.assertEqual(verify_metadata_translation_plan(stored), stored["plan_sha256"])
                self.assertNotIn("Must not be copied into this plan.", plan_path.read_text(encoding="utf-8"))

                with patch(
                    "scripts.prepare_metadata_translation.load_verified_ai_book_bundle",
                    return_value=verified,
                ), patch(
                    "scripts.prepare_metadata_translation._current_work_metadata_version_id",
                    return_value="v-work-1",
                ), redirect_stderr(io.StringIO()):
                    self.assertEqual(prepare_main(arguments), 1)
                self.assertEqual(len(list(plans_root.iterdir())), 1)

    def test_candidate_import_is_idempotent_and_never_logs_translation_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            plan = create_metadata_translation_plan(self._verified_bundle())
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            imported = {
                "schema_version": 1,
                "plan_sha256": plan["plan_sha256"],
                "translations": self._translations(plan),
                "translation_provenance": self._manual_provenance(),
            }
            translations_path = project / "translation-input.json"
            translations_path.write_text(
                json.dumps(imported, ensure_ascii=False),
                encoding="utf-8",
            )
            arguments = [
                "--plan",
                str(plan_path),
                "--translations",
                str(translations_path),
                "--candidate-name",
                "candidate-1.json",
            ]

            with patch("sys.stdout") as output:
                first_result = import_candidate_main(arguments)
            first_stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertEqual(first_result, 0)
            self.assertNotIn("译文", first_stdout)
            self.assertNotIn("Synthetic work", first_stdout)

            with patch("sys.stdout") as output:
                second_result = import_candidate_main(arguments)
            second_stdout = "".join(
                str(call.args[0])
                for call in output.write.call_args_list
                if call.args
            )
            self.assertEqual(second_result, 0)
            self.assertIn("reused", second_stdout)
            self.assertNotIn("译文", second_stdout)

            candidate_path = plans_root / "candidate-1.json"
            stored = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(
                verify_metadata_translation_candidate(stored, plan),
                stored["candidate_sha256"],
            )
            self.assertEqual(
                len(list(plans_root.glob("candidate-1.json"))),
                1,
            )

            imported["translations"]["work.title"] = "Different title"
            translations_path.write_text(
                json.dumps(imported, ensure_ascii=False),
                encoding="utf-8",
            )
            with redirect_stderr(io.StringIO()):
                self.assertEqual(import_candidate_main(arguments), 1)
            self.assertEqual(
                json.loads(candidate_path.read_text(encoding="utf-8"))["candidate_sha256"],
                stored["candidate_sha256"],
            )

    def test_candidate_import_rejects_reparse_point_plans_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text("{}", encoding="utf-8")
            with patch(
                "scripts.import_metadata_translation_candidate._is_reparse_point",
                side_effect=lambda path: path.name == "Plans",
            ):
                with self.assertRaisesRegex(ValueError, "Workflow/Plans"):
                    import_metadata_translation_candidate(
                        plan_path=str(plan_path),
                        translations_path=str(project / "translations.json"),
                        candidate_name="candidate.json",
                    )

    def test_candidate_import_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            plans_root = project / "Workflow" / "Plans"
            plans_root.mkdir(parents=True)
            plan = create_metadata_translation_plan(self._verified_bundle())
            plan_path = plans_root / "metadata-plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )
            translations_path = project / "translations.json"
            translations_path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                import_metadata_translation_candidate(
                    plan_path=str(plan_path),
                    translations_path=str(translations_path),
                    candidate_name="candidate.json",
                )

    def test_current_work_metadata_version_is_verified_and_matches_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            work_id = "work-1"
            metadata = {"title": "Synthetic work"}
            version_id = "v-work-metadata-1"
            artifact_path = source_root / "work-metadata.json"
            artifact_bytes = json.dumps(
                {
                    "schema_version": 1,
                    "work_id": work_id,
                    "recorded_at_utc": "2026-01-01T00:00:00Z",
                    "metadata": metadata,
                },
                sort_keys=True,
            ).encode("utf-8")
            artifact_path.write_bytes(artifact_bytes)
            artifact = {
                "artifact_id": source_artifact_id(work_id, "work", "metadata"),
                "version_id": version_id,
                "kind": "work",
                "content_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                "relative_path": "work-metadata.json",
                "parent_version_ids": [],
            }
            (source_root / "source_manifest.json").write_text(
                json.dumps(
                    {"schema_version": 1, "artifacts": [artifact]},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            manifest_sha256 = hashlib.sha256(
                (source_root / "source_manifest.json").read_bytes()
            ).hexdigest()

            self.assertEqual(
                _current_work_metadata_version_id(
                    source_root,
                    "source_manifest.json",
                    work_id,
                    metadata,
                    manifest_sha256,
                ),
                version_id,
            )
            with self.assertRaisesRegex(ValueError, "manifest"):
                _current_work_metadata_version_id(
                    source_root,
                    "source_manifest.json",
                    work_id,
                    metadata,
                    "a" * 64,
                )
            with self.assertRaisesRegex(ValueError, "differs"):
                _current_work_metadata_version_id(
                    source_root,
                    "source_manifest.json",
                    work_id,
                    {"title": "Different"},
                    manifest_sha256,
                )

    def test_cli_rejects_reparse_point_workflow_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source_root = project / "SourceArchive"
            plans_root = project / "Workflow" / "Plans"
            source_root.mkdir()
            plans_root.mkdir(parents=True)
            with patch(
                "scripts.prepare_metadata_translation._is_reparse_point",
                side_effect=lambda path: path.name == "Workflow",
            ):
                with self.assertRaisesRegex(ValueError, "Workflow/Plans"):
                    prepare_metadata_translation(
                        source_root=str(source_root),
                        catalog_relative_path="catalog.json",
                        checkpoint_relative_path="checkpoint.json",
                        bundle_set_relative_path="bundle-set.json",
                        human_root=str(project / "human"),
                        ai_root=str(project / "ai"),
                        plan_name="metadata-plan.json",
                    )

    def test_cli_rejects_path_components_in_plan_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source_root = project / "SourceArchive"
            plans_root = project / "Workflow" / "Plans"
            source_root.mkdir()
            plans_root.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "simple JSON filename"):
                prepare_metadata_translation(
                    source_root=str(source_root),
                    catalog_relative_path="catalog.json",
                    checkpoint_relative_path="checkpoint.json",
                    bundle_set_relative_path="bundle-set.json",
                    human_root=str(project / "human"),
                    ai_root=str(project / "ai"),
                    plan_name="..\\outside.json",
                )


if __name__ == "__main__":
    unittest.main()
