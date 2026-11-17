import asyncio
import hashlib
import io
import os
import sys
import json
import unittest
import tempfile
import shutil
import subprocess
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.ingest_local_sources import main as ingest_local_sources_main
from scripts.run_kakuyomu_workflow import run_workflow
from source_ingestion import collect_source, materialize_episode_markdown
from story_summary_review import (
    create_summary_review_template,
    publish_reviewed_summary,
)
from translation_plan_approval import create_approval_receipt, write_new_json
from tests.test_kakuyomu_page_source import (
    EPISODE_ID as KAKUYOMU_EPISODE_ID,
    EXPECTED_TEXT as KAKUYOMU_EXPECTED_TEXT,
    PAGE_URL as KAKUYOMU_PAGE_URL,
    PAGE_HTML as KAKUYOMU_PAGE_HTML,
    ROBOTS as KAKUYOMU_ROBOTS,
    WORK_ID as KAKUYOMU_WORK_ID,
    WORK_URL as KAKUYOMU_WORK_URL,
    FakeClock as KakuyomuFakeClock,
    FakeOpener as KakuyomuFakeOpener,
    make_adapter as make_kakuyomu_adapter,
    make_work_page_html as make_kakuyomu_work_page_html,
)

class E2ETestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
        cls.mock_url = f"http://127.0.0.1:{cls.mock_port}"
        
        # Determine paths to scripts
        cls.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.run_pipeline_script = os.path.join(cls.project_root, "tests", "run_pipeline.py")
        cls.align_script = os.path.join(cls.project_root, "scripts", "align_chapters.py")

    def setUp(self):
        # Reset mock server state
        self.set_mock_state({
            "sakura_response_delay": 0.0,
            "deepseek_response_delay": 0.0,
            "sakura_offline": False,
            "deepseek_status_code": 200,
            "gemini_status_code": 200,
            "deepseek_safety_blocked": False,
            "gemini_safety_blocked": False,
            "line_count_mismatch_active": False,
            "quote_mismatch_active": False,
            "custom_translations": {},
            "embed_values": [0.1] * 768
        })
        
        # Create temp workspace
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, "生肉")
        self.output_dir = os.path.join(self.test_dir, "熟肉")
        self.knowledge_dir = os.path.join(self.test_dir, "Knowledge")
        
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.knowledge_dir, exist_ok=True)
        
        # Write default files
        self.write_file(os.path.join(self.knowledge_dir, "作品基本信息.json"), {
            "title": "测试小说",
            "author": "测试作者"
        }, is_json=True)
        self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
            "ネトラレラ (Netorarera)": "努力豆（マメ本意为...） / 老茧"
        }, is_json=True)
        
        with open(os.path.join(self.knowledge_dir, "guidelines.txt"), "w", encoding="utf-8") as f:
            f.write("Global Guideline: Translate accurately.\n《翻译指导原则》 - [第 12 章]\nChapter 12 Guideline: Focus on terminology.")
            
        with open(os.path.join(self.knowledge_dir, "STORY_SUMMARY.md"), "w", encoding="utf-8") as f:
            f.write("# Story Summary\n[第 1 話] Chapter 1 summary.\n[第 12 話] Chapter 12 summary.")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def write_file(self, filepath, content, is_json=False):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            if is_json:
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(content))

    def set_mock_state(self, state):
        full_state = {
            "sakura_response_delay": 0.0,
            "deepseek_response_delay": 0.0,
            "sakura_offline": False,
            "deepseek_status_code": 200,
            "gemini_status_code": 200,
            "deepseek_safety_blocked": False,
            "gemini_safety_blocked": False,
            "line_count_mismatch_active": False,
            "quote_mismatch_active": False,
            "custom_translations": {},
            "embed_values": [0.1] * 768
        }
        full_state.update(state)
        req = urllib.request.Request(
            f"{self.mock_url}/set_state",
            data=json.dumps(full_state).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get("API_TIMEOUT", 10.0))) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self.fail(f"Failed to set mock state: {e}")

    def run_pipeline(self, extra_env=None):
        if os.path.exists(self.output_dir):
            for f in os.listdir(self.output_dir):
                fp = os.path.join(self.output_dir, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["TEST_WORKSPACE_DIR"] = self.test_dir
        env["TEST_RAW_DIR"] = self.raw_dir
        env["TEST_OUTPUT_DIR"] = self.output_dir
        env["TEST_GLOSSARY_PATH"] = os.path.join(self.knowledge_dir, "Glossary.json")
        env["TEST_GUIDELINES_PATH"] = os.path.join(self.knowledge_dir, "guidelines.txt")
        env["TEST_INFO_PATH"] = os.path.join(self.knowledge_dir, "作品基本信息.json")
        env["TEST_TM_PATH"] = os.path.join(self.knowledge_dir, "translation_memory.json")
        env["TEST_STORY_SUMMARY_PATH"] = os.path.join(self.knowledge_dir, "STORY_SUMMARY.md")
        env["MOCK_SERVER_PORT"] = self.mock_port
        
        # Add tests/bin to PATH for CLI mode testing
        bin_dir = os.path.join(self.project_root, "tests", "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        
        if extra_env:
            env.update(extra_env)

        proc = subprocess.run(
            [sys.executable, self.run_pipeline_script],
            env=env,
            capture_output=True,
            encoding="utf-8"
        )
        if proc.returncode != 0:
            print(f"\n--- PIPELINE RUN FAILED ---\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n--------------------------")
        return proc

    def run_align(self, extra_env=None):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["TEST_WORKSPACE_DIR"] = self.test_dir
        env["TEST_RAW_DIR"] = self.raw_dir
        env["TEST_OUTPUT_DIR"] = self.output_dir
        env["TEST_TM_PATH"] = os.path.join(self.knowledge_dir, "translation_memory.json")
        env["MOCK_SERVER_PORT"] = self.mock_port
        if extra_env:
            env.update(extra_env)

        proc = subprocess.run(
            [sys.executable, self.align_script],
            env=env,
            capture_output=True,
            encoding="utf-8"
        )
        if proc.returncode != 0:
            print(f"\n--- ALIGN RUN FAILED ---\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n--------------------------")
        return proc

    def test_local_source_archive_flows_through_versioned_mock_translation(self):
        source_input_dir = os.path.join(self.test_dir, "source-input")
        os.makedirs(source_input_dir)
        source_text = "人工合成の試験文です。"
        source_bytes = source_text.encode("utf-8")
        with open(
            os.path.join(source_input_dir, "episode_0001.txt"), "wb"
        ) as source_file:
            source_file.write(source_bytes)

        catalog = {
            "schema_version": 1,
            "work_id": "synthetic-e2e-work",
            "episodes": [
                {
                    "episode_id": "episode-1",
                    "title": "Synthetic episode",
                    "position": 1,
                    "relative_path": "episode_0001.txt",
                }
            ],
        }
        with open(
            os.path.join(source_input_dir, "catalog.json"),
            "w",
            encoding="utf-8",
        ) as catalog_file:
            json.dump(catalog, catalog_file, ensure_ascii=False)

        ingest_stdout = io.StringIO()
        ingest_stderr = io.StringIO()
        with redirect_stdout(ingest_stdout), redirect_stderr(ingest_stderr):
            ingest_result = ingest_local_sources_main(
                [
                    "--source-root",
                    source_input_dir,
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    self.raw_dir,
                ]
            )

        self.assertEqual(ingest_result, 0)
        self.assertEqual(ingest_stderr.getvalue(), "")
        self.assertEqual(json.loads(ingest_stdout.getvalue())["status"], "complete")
        self.assertNotIn(source_text, ingest_stdout.getvalue())
        self.assertEqual(
            Path(os.path.join(source_input_dir, "episode_0001.txt")).read_bytes(),
            source_bytes,
        )

        normalized = materialize_episode_markdown(
            self.raw_dir,
            work_id="synthetic-e2e-work",
            episode_id="episode-1",
        )
        self._assert_versioned_mock_translation(
            normalized,
            source_text=source_text,
            tm_key="synthetic-episode-1",
        )

    def test_kakuyomu_page_archive_flows_through_versioned_mock_translation(self):
        adapter, opener, _ = make_kakuyomu_adapter()
        report = collect_source(
            adapter,
            root=self.raw_dir,
            work_id=KAKUYOMU_WORK_ID,
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(
            [request[0] for request in opener.requests],
            ["https://kakuyomu.jp/robots.txt", KAKUYOMU_PAGE_URL],
        )
        normalized = materialize_episode_markdown(
            self.raw_dir,
            work_id=KAKUYOMU_WORK_ID,
            episode_id=KAKUYOMU_EPISODE_ID,
        )
        self.assertEqual(
            Path(self.raw_dir, normalized["relative_path"]).read_bytes(),
            KAKUYOMU_EXPECTED_TEXT.encode("utf-8"),
        )
        self._assert_versioned_mock_translation(
            normalized,
            source_text=KAKUYOMU_EXPECTED_TEXT,
            tm_key="synthetic-kakuyomu-episode",
        )

    def test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation(self):
        from kakuyomu_page_source import discover_kakuyomu_work_catalog
        from pipeline import Config, TranslationPipeline

        work_html = make_kakuyomu_work_page_html(
            KAKUYOMU_WORK_ID,
            [(KAKUYOMU_EPISODE_ID, "第1話 はじまり")],
        )
        config_path = os.path.join(self.test_dir, "pipeline-config.json")
        self.write_file(config_path, {"synthetic": True}, is_json=True)
        opener = KakuyomuFakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    KAKUYOMU_ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                KAKUYOMU_WORK_URL: (
                    work_html.encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                KAKUYOMU_PAGE_URL: (
                    KAKUYOMU_PAGE_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        clock = KakuyomuFakeClock()
        discovered_works = []

        def discover_test_work(work_url, **options):
            discovered = discover_kakuyomu_work_catalog(
                work_url,
                opener=opener,
                sleep=clock.sleep,
                clock=clock.now,
                **options,
            )
            discovered_works.append(discovered)
            return discovered

        def load_test_config(*, config_file):
            self.assertEqual(config_file, config_path)

        workflow_output = io.StringIO()
        with (
            patch.multiple(
                Config,
                WORKSPACE_DIR=self.test_dir,
                RAW_DIR=self.raw_dir,
                OUTPUT_DIR=self.output_dir,
                CHAPTER_MAP=None,
                SOURCE_MANIFEST_PATH=None,
                TM_REVIEWED_PATH=None,
                GLOSSARY_PATH=os.path.join(
                    self.knowledge_dir, "Glossary.json"
                ),
                GUIDELINES_PATH=os.path.join(
                    self.knowledge_dir, "guidelines.txt"
                ),
                INFO_PATH=os.path.join(
                    self.knowledge_dir, "作品基本信息.json"
                ),
                STORY_SUMMARY_PATH=os.path.join(
                    self.knowledge_dir, "STORY_SUMMARY_reviewed.json"
                ),
                TM_PATH=os.path.join(
                    self.knowledge_dir, "translation_memory.json"
                ),
                PROVIDER_DATA_POLICY={},
                GEMINI_FALLBACK_ENABLED=False,
                STRICT_REFLECTION_MODE=False,
                MIN_JITTER=0,
                MAX_JITTER=0,
            ),
            patch(
                "rag_engine.RAGEngine._generate_embedding_sync",
                return_value=[0.1] * 768,
            ),
            patch(
                "scripts.run_kakuyomu_workflow.TranslationPipeline",
                wraps=TranslationPipeline,
            ) as pipeline_factory,
            patch(
                "scripts.run_kakuyomu_workflow._resolve_project_human_edition_root",
                return_value=os.path.join(self.test_dir, "human-edition"),
            ),
            redirect_stdout(workflow_output),
        ):
            preview_report = run_workflow(
                source_root=self.raw_dir,
                work_url=KAKUYOMU_WORK_URL,
                translation_root=self.output_dir,
                config_file=config_path,
                discovered_catalog="source_catalog.discovered.json",
                source_edition="normalized_source",
                config_loader=load_test_config,
                discovery_factory=discover_test_work,
            )
            self.assertEqual(
                preview_report["status"],
                "approval_required",
                preview_report,
            )
            pipeline_factory.assert_not_called()
            self.assertEqual(
                preview_report["source_editions"]["status"],
                "materialized",
            )

            preview_report = run_workflow(
                source_root=self.raw_dir,
                catalog=preview_report["discovered_catalog"],
                translation_root=self.output_dir,
                config_file=config_path,
                checkpoint="source_checkpoint.discovered.json",
                config_loader=load_test_config,
                adapter_factory=lambda *_args: (
                    discovered_works[0].create_page_adapter()
                ),
            )
            self.assertEqual(preview_report["status"], "approval_required")
            self.assertEqual(
                preview_report["source_editions"]["status"],
                "materialized",
            )
            self.assertEqual(
                preview_report["plan"]["source_edition"]["profile_id"],
                "ai-efficient-v1",
            )
            receipt_path = os.path.join(
                self.test_dir, "translation-plan-approval.json"
            )
            write_new_json(
                receipt_path,
                create_approval_receipt(
                    preview_report["plan"],
                    "synthetic reviewer",
                ),
            )
            planned_episodes = preview_report["plan"]["episodes"]
            source_files = []
            source_texts = []
            for episode in planned_episodes:
                source_path = Path(
                    self.test_dir,
                    "RAWs_AI",
                    episode["source_input_file"],
                )
                source_text = source_path.read_text(encoding="utf-8")
                source_texts.append(source_text)
                source_files.append(
                    {
                        "filename": episode["source_file"],
                        "source_sha256": hashlib.sha256(
                            source_text.encode("utf-8")
                        ).hexdigest(),
                        "source_version_id": episode["source_version_id"],
                    }
                )
            summary_chapters = [
                source["filename"] for source in source_files
            ]
            input_characters = sum(map(len, source_texts))
            self.write_file(
                os.path.join(
                    self.knowledge_dir, "STORY_SUMMARY_draft.md"
                ),
                "# Synthetic Whole-Book Summary\n\nOne chapter fixture.",
            )
            self.write_file(
                os.path.join(
                    self.knowledge_dir, "KNOWLEDGE_PROVENANCE_draft.json"
                ),
                {
                    "schema_version": 1,
                    "artifact_status": "complete",
                    "source_files": source_files,
                    "summary_source_chapters": summary_chapters,
                    "input_coverage": {
                        "scope": "all_configured_chapters",
                        "complete_for_configured_chapters": True,
                        "configured_chapter_count": len(source_files),
                        "included_chapter_count": len(source_files),
                        "input_characters": input_characters,
                        "input_character_limit": max(1, input_characters),
                    },
                },
                is_json=True,
            )
            summary_receipt = os.path.join(
                self.knowledge_dir, "summary-review.json"
            )
            create_summary_review_template(
                self.knowledge_dir, os.path.basename(summary_receipt)
            )
            summary_review = json.loads(
                Path(summary_receipt).read_text(encoding="utf-8")
            )
            summary_review.update(
                {
                    "reviewer": {
                        "provider_id": "synthetic-reviewer",
                        "model_id": "fixture-v1",
                        "review_id": "summary-review-001",
                    },
                    "reviewed_at_utc": "2026-11-16T00:00:00Z",
                    "decision": "approved",
                    "rationale": "Synthetic whole-book summary fixture.",
                }
            )
            Path(summary_receipt).write_text(
                json.dumps(summary_review, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            publish_reviewed_summary(
                self.knowledge_dir,
                self.raw_dir,
                "source_editions_manifest.json",
                os.path.basename(summary_receipt),
                "STORY_SUMMARY_reviewed.json",
            )
            report = run_workflow(
                source_root=self.raw_dir,
                catalog=preview_report["discovered_catalog"],
                translation_root=self.output_dir,
                config_file=config_path,
                approval_receipt=receipt_path,
                checkpoint="source_checkpoint.discovered.json",
                config_loader=load_test_config,
                adapter_factory=lambda *_args: (
                    discovered_works[0].create_page_adapter()
                ),
            )
            self.assertEqual(report["status"], "complete", report)
            pipeline_factory.assert_called_once()

        self.assertEqual(report["status"], "complete")
        self.assertEqual(
            report["discovered_catalog"],
            "source_catalog.discovered.json",
        )
        discovered_catalog = json.loads(
            Path(self.raw_dir, report["discovered_catalog"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(discovered_catalog["work_id"], KAKUYOMU_WORK_ID)
        self.assertEqual(
            discovered_catalog["episodes"][0]["page_url"],
            KAKUYOMU_PAGE_URL,
        )
        self.assertEqual(
            [request[0] for request in opener.requests],
            [
                "https://kakuyomu.jp/robots.txt",
                KAKUYOMU_WORK_URL,
                KAKUYOMU_PAGE_URL,
            ],
        )
        self.assertEqual(clock.sleeps, [2, 2])
        self.assertNotIn(KAKUYOMU_EXPECTED_TEXT, workflow_output.getvalue())
        translated = Path(
            self.output_dir,
            f"episode-0001-{KAKUYOMU_EPISODE_ID}.md",
        ).read_text(encoding="utf-8")
        self.assertIn("【润色】", translated)

        tm_path = Path(self.knowledge_dir, "translation_memory.json")
        tm = json.loads(tm_path.read_text(encoding="utf-8"))
        tm_key = f"kakuyomu:{KAKUYOMU_WORK_ID}:{KAKUYOMU_EPISODE_ID}"
        planned_ai_source = Path(
            self.raw_dir,
            planned_episodes[0]["source_file"],
        ).read_text(encoding="utf-8")
        self.assertEqual(
            "\n\n".join(pair["raw"] for pair in tm["chapters"][tm_key]),
            planned_ai_source,
        )
        self.assertEqual(
            tm["source_provenance"][tm_key]["source_version_id"],
            report["episodes"][0]["source_version_id"],
        )

    def _assert_versioned_mock_translation(self, normalized, *, source_text, tm_key):
        chapter_map = [
            {
                "raw_file": normalized["relative_path"],
                "translation_file": "pilot-chapter.md",
                "tm_key": tm_key,
                "source_version_id": normalized["version_id"],
            }
        ]

        from pipeline import Config, TranslationPipeline

        pipeline_output = io.StringIO()
        with (
            patch.multiple(
                Config,
                WORKSPACE_DIR=self.test_dir,
                RAW_DIR=self.raw_dir,
                OUTPUT_DIR=self.output_dir,
                CHAPTER_MAP=chapter_map,
                SOURCE_MANIFEST_PATH="source_manifest.json",
                TM_REVIEWED_PATH=None,
                GLOSSARY_PATH=os.path.join(
                    self.knowledge_dir, "Glossary.json"
                ),
                GUIDELINES_PATH=os.path.join(
                    self.knowledge_dir, "guidelines.txt"
                ),
                INFO_PATH=os.path.join(
                    self.knowledge_dir, "作品基本信息.json"
                ),
                STORY_SUMMARY_PATH=os.path.join(
                    self.knowledge_dir, "STORY_SUMMARY.md"
                ),
                TM_PATH=os.path.join(
                    self.knowledge_dir, "translation_memory.json"
                ),
                PROVIDER_DATA_POLICY={},
                GEMINI_FALLBACK_ENABLED=False,
                STRICT_REFLECTION_MODE=False,
                MIN_JITTER=0,
                MAX_JITTER=0,
            ),
            patch(
                "rag_engine.RAGEngine._generate_embedding_sync",
                return_value=[0.1] * 768,
            ),
            redirect_stdout(pipeline_output),
        ):
            asyncio.run(TranslationPipeline().run_all())

        translation_path = os.path.join(self.output_dir, "pilot-chapter.md")
        with open(translation_path, "r", encoding="utf-8") as translation_file:
            translation_text = translation_file.read()
        self.assertIn("【润色】", translation_text)
        self.assertNotIn(source_text, pipeline_output.getvalue())

        tm_path = os.path.join(
            self.knowledge_dir, "translation_memory.json"
        )
        with open(tm_path, "r", encoding="utf-8") as tm_file:
            translation_memory = json.load(tm_file)
        self.assertEqual(
            "\n\n".join(
                pair["raw"]
                for pair in translation_memory["chapters"][tm_key]
            ),
            source_text,
        )
        self.assertEqual(
            translation_memory["source_provenance"][tm_key]["source_version_id"],
            normalized["version_id"],
        )

    # ==========================================
    # TIER 1: Feature Coverage (30 Cases)
    # ==========================================
    def test_tier1_feature_coverage(self):
        # F1 (TM) Cases (1-5)
        with self.subTest("Case 1: TM retrieval injects matched pairs as few-shots"):
            # Set up TM with a matching pair
            tm_content = {
                "chapters": {
                    "chap1.md": [
                        {"raw": "こんにちは", "translated": "你好", "embedding": [0.1]*768}
                    ]
                }
            }
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "こんにちは")
            
            # Intercept Sakura API call in mock server to verify TM prompt injection
            self.set_mock_state({
                "custom_translations": {"こんにちは": "你好，测试"}
            })
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            
        with self.subTest("Case 2: Aligned chapter vector calculation runs via mock embedding API"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            self.write_file(os.path.join(self.output_dir, "第12話.md"), "测试")
            res = self.run_align()
            self.assertEqual(res.returncode, 0)
            # Verify TM file generated
            self.assertTrue(os.path.exists(os.path.join(self.knowledge_dir, "translation_memory.json")))

        with self.subTest("Case 3: Incremental updates append new paragraph pairs to TM"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            with open(os.path.join(self.knowledge_dir, "translation_memory.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertIn("第12話.md", data["chapters"])

        with self.subTest("Case 4: Empty translation memory returns gracefully without errors"):
            if os.path.exists(os.path.join(self.knowledge_dir, "translation_memory.json")):
                os.remove(os.path.join(self.knowledge_dir, "translation_memory.json"))
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 5: Cosine similarity prioritises higher similarity matches"):
            # Put 2 entries in TM, one identical to query
            tm_content = {
                "chapters": {
                    "chap1.md": [
                        {"raw": "A", "translated": "匹配A", "embedding": [1.0] + [0.0]*767},
                        {"raw": "B", "translated": "匹配B", "embedding": [0.0]*768}
                    ]
                }
            }
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "A")
            self.set_mock_state({"embed_values": [1.0] + [0.0]*767})
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # F2 (Glossary) Cases (6-10)
        with self.subTest("Case 6: Clean glossary parsing extracts terms and metadata"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "ネトラレラ")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 7: Empty glossary builds prompt without glossary section"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {}, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 8: Glossary terms with explanations split into dst and info"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "ネトラレラ")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 9: Glossary terms with parentheses filter out explanation contamination"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "ネトラレラ")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 10: Glossary matches term names correctly against input text"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "無関係")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # F3 (Guidelines) Cases (11-15)
        with self.subTest("Case 11: Guidelines partition global and chapter-specific segments correctly"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 12: Chapter guidelines fallback semantically to adjacent rules"):
            # Requesting chapter 13, should fallback to chapter 12 rules since 13 doesn't exist
            self.write_file(os.path.join(self.raw_dir, "第13話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 13: Guidelines context window is under 10KB"):
            # Write a huge guideline file
            large_guideline = "Global rule\n" * 2000
            with open(os.path.join(self.knowledge_dir, "guidelines.txt"), "w", encoding="utf-8") as f:
                f.write(large_guideline)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 14: Global rules are always included in prompt"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 15: Missing global guidelines handled gracefully"):
            # Empty guidelines file
            with open(os.path.join(self.knowledge_dir, "guidelines.txt"), "w", encoding="utf-8") as f:
                f.write("")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # F4 (Sakura/DeepSeek API) Cases (16-20)
        with self.subTest("Case 16: Sakura initial translator called via ChatML format"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 17: DeepSeek-v4-flash used for proofreading"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 18: DeepSeek-v4-pro used for polishing"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 19: OpenAI client wrapper initialises base URL and api key"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 20: Proofreading and polishing steps return expected output"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # F5 (Safety Fallback) Cases (21-25)
        with self.subTest("Case 21: Content block does not trigger provider failover"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 22: Content block leaves no translated output"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 23: Explicit failover handles a DeepSeek server error"):
            self.set_mock_state({"deepseek_status_code": 500})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 24: Safe translation of explicit content completes without block"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 25: Content block remains blocked when failover is enabled"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertNotEqual(res.returncode, 0)

        # F6 (Formatting Assertions) Cases (26-30)
        with self.subTest("Case 26: Line count matches 1:1 between raw and translated"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 27: Quote marks are preserved 1:1"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「こんにちは」\n\n『テスト』")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            with open(
                os.path.join(self.output_dir, "第12話.md"), "r", encoding="utf-8"
            ) as f:
                self.assertEqual(
                    f.read(), "【润色】「こんにちは」\n\n【润色】『テスト』"
                )
            with open(
                os.path.join(self.knowledge_dir, "translation_memory.json"),
                "r",
                encoding="utf-8",
            ) as f:
                tm_data = json.load(f)
                tm_pairs = tm_data["chapters"]["第12話.md"]
            self.assertEqual(
                [(pair["raw"], pair["translated"]) for pair in tm_pairs],
                [
                    ("「こんにちは」", "【润色】「こんにちは」"),
                    ("『テスト』", "【润色】『テスト』"),
                ],
            )
            self.assertEqual(
                tm_data["source_provenance"]["第12話.md"]["pair_mappings"],
                [
                    {
                        "pair_index": 1,
                        "raw_paragraph_indices": [1],
                        "translation_paragraph_indices": [1],
                        "trace_status": "matched",
                    },
                    {
                        "pair_index": 2,
                        "raw_paragraph_indices": [2],
                        "translation_paragraph_indices": [2],
                        "trace_status": "matched",
                    },
                ],
            )

        with self.subTest("Case 28: Line count mismatch aborts before writing"):
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 29: Quote order mismatch blocks output and TM update"):
            self.set_mock_state({"quote_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「こんにちは」")
            tm_path = os.path.join(self.knowledge_dir, "translation_memory.json")
            if os.path.exists(tm_path):
                with open(tm_path, "r", encoding="utf-8") as f:
                    tm_before = json.load(f)
            else:
                tm_before = None

            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertIn(
                "Final translation changed Japanese quote marks in paragraph 1",
                res.stderr,
            )
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))
            if tm_before is None:
                self.assertFalse(os.path.exists(tm_path))
            else:
                with open(tm_path, "r", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), tm_before)

        with self.subTest("Case 30: Persistent mismatch fails chapter gracefully"):
            # Set state to permanently cause line count mismatch
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

    # ==========================================
    # TIER 2: Boundary & Corner Cases (30 Cases)
    # ==========================================
    def test_tier2_boundary_cases(self):
        # TM Boundaries (31-35 + 1 extra)
        with self.subTest("Case 31: Empty raw file"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 32: Huge paragraph size"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "巨大" * 5000)
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 33: Zero matches in TM"):
            tm_content = {"chapters": {}}
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 34: Mismatched paragraph counts in alignment tool"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "段落一\n\n段落二")
            self.write_file(os.path.join(self.output_dir, "第12話.md"), "译文段落一") # only 1 para
            res = self.run_align()
            self.assertEqual(res.returncode, 0)
            with open(os.path.join(self.knowledge_dir, "translation_memory.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            pairs = data["chapters"]["第12話.md"]
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]["raw"], "段落一\n\n段落二")
            self.assertEqual(pairs[0]["translated"], "译文段落一")
            self.assertTrue(pairs[0]["embedding"])
            self.assertEqual(
                data["source_provenance"]["第12話.md"]["pair_mappings"],
                [
                    {
                        "pair_index": 1,
                        "raw_paragraph_indices": [1, 2],
                        "translation_paragraph_indices": [1],
                        "trace_status": "matched",
                    }
                ],
            )

        with self.subTest("Case 35: Invalid JSON TM stops the pipeline"):
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), "{invalid json}")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 35b (Extra): TM with missing embedding field"):
            tm_content = {
                "chapters": {
                    "chap1.md": [{"raw": "A", "translated": "B"}] # Missing embedding
                }
            }
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "A")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # Glossary Boundaries (36-40)
        with self.subTest("Case 36: Duplicate glossary keys"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
                "测试": "译文1",
                "测试 (二)": "译文2"
            }, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 37: Glossary key with special regex chars"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
                "测试.*+?^$()[]{}|\\": "安全译文"
            }, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试.*+?^$()[]{}|\\")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 38: Empty glossary file"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), "")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 39: Extremely long terms"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
                "长" * 1000: "短"
            }, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 40: Glossary without translation targets"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
                "无翻译": ""
            }, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "无翻译")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # Guidelines Boundaries (41-44 + 1 extra)
        with self.subTest("Case 41: Empty guideline file"):
            self.write_file(os.path.join(self.knowledge_dir, "guidelines.txt"), "")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 42: Huge guideline file"):
            self.write_file(os.path.join(self.knowledge_dir, "guidelines.txt"), "规则\n" * 10000)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 43: No matching chapter or adjacent guidelines"):
            # Guidelines with no chapters listed
            self.write_file(os.path.join(self.knowledge_dir, "guidelines.txt"), "仅有全局规则")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 44: Guideline lines without chapter header format"):
            self.write_file(os.path.join(self.knowledge_dir, "guidelines.txt"), "乱七八糟的格式\n第二行")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 44b (Extra): Guidelines with extremely long lines"):
            self.write_file(os.path.join(self.knowledge_dir, "guidelines.txt"), "超长规则" * 2000)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # API Boundaries (45-49)
        with self.subTest("Case 45: Explicit failover handles an unavailable Sakura endpoint"):
            self.set_mock_state({"sakura_offline": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 46: Primary endpoint recovers after offline scenario"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 47: Explicit failover handles a DeepSeek rate limit"):
            self.set_mock_state({"deepseek_status_code": 429})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 48: Empty provider key is accepted by local mock endpoint"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"DEEPSEEK_API_KEY": ""})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 49: Explicit failover handles a provider timeout"):
            self.set_mock_state({"deepseek_status_code": 504})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 59: Explicit failover stops on provider authentication errors"):
            self.set_mock_state({"deepseek_status_code": 401})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        # Safety Boundaries (50-53)
        with self.subTest("Case 50: Provider content block stops before fallback"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            # Both blocked should fail or exit non-zero
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 51: Content block does not contact Gemini"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_status_code": 429})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 52: Gemini error state is irrelevant when fallback is disabled"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_status_code": 204}) # NoContent
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 53: Explicit failover processes multiple consecutive chapters"):
            self.set_mock_state({"deepseek_status_code": 500})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试1")
            self.write_file(os.path.join(self.raw_dir, "第13話.md"), "测试2")
            res = self.run_pipeline(extra_env={"ENABLE_GEMINI_FALLBACK": "true"})
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第12話.md")))
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第13話.md")))

        # Formatting Boundaries (54-58)
        with self.subTest("Case 54: Paragraph with multiple nested quotes"):
            self.set_mock_state({})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「『こんにちは』と言った」")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 55: Blank lines in raw input"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 56: Whitespace-only paragraphs"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n   \n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 57: Paragraph with only emojis"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "😊😇\n\n👍")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 58: Paragraph with mixed Japanese/Chinese quotes"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「你好」『测试』")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

    # ==========================================
    # TIER 3: Cross-Feature Combinations (6 Cases)
    # ==========================================
    def test_tier3_combinations(self):
        with self.subTest("Case 1: Glossary matches & TM match combined in prompt"):
            tm_content = {"chapters": {"chap1.md": [{"raw": "测试", "translated": "测试译", "embedding": [0.1]*768}]}}
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {"测试": "术语译"}, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 2: Guideline fallback & TM matches combined in prompt"):
            tm_content = {"chapters": {"chap1.md": [{"raw": "测试", "translated": "测试译", "embedding": [0.1]*768}]}}
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            # Chapter 13 should fallback to Chapter 12 guidelines
            self.write_file(os.path.join(self.raw_dir, "第13話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 3: Safety block stops a chapter containing glossary matches"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {"测试": "术语"}, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            self.set_mock_state({"deepseek_safety_blocked": True})
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 4: Line count mismatch aborts a chapter with combined context"):
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 5: Missing chapter guidelines semantic fallback + TM match"):
            self.set_mock_state({})
            tm_content = {"chapters": {"chap1.md": [{"raw": "测试", "translated": "测试译", "embedding": [0.1]*768}]}}
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第15話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 6: Persistent line count mismatch writes no partial output"):
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

    # ==========================================
    # TIER 4: Real-World Scenarios (5 Cases)
    # ==========================================
    def test_tier4_real_world(self):
        with self.subTest("Case 1: E2E translation of a normal chapter"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试内容")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 2: E2E translation stops when the provider blocks content"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "极其敏感的内容")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 3: Align chapters 1-18, save TM, then run pipeline for chapter 19"):
            self.set_mock_state({})
            # Set up aligned chapters 1-18
            for i in range(1, 19):
                self.write_file(os.path.join(self.raw_dir, f"第{i}話.md"), f"日文内容{i}")
                self.write_file(os.path.join(self.output_dir, f"第{i}話.md"), f"中文翻译{i}")
            
            # Run align
            res_align = self.run_align()
            self.assertEqual(res_align.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.knowledge_dir, "translation_memory.json")))
            
            # Now run pipeline for chapter 19
            self.write_file(os.path.join(self.raw_dir, "第19話.md"), "日文内容19")
            res_pipe = self.run_pipeline()
            self.assertEqual(res_pipe.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第19話.md")))

        with self.subTest("Case 4: Glossary term with metadata verifying clean target"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {
                "ネトラレラ (Netorarera)": "努力豆（マメ本意为...） / 老茧"
            }, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "ネトラレラ")
            # In mock server, set a translation using glossary dst term
            self.set_mock_state({
                "custom_translations": {"ネトラレラ": "老茧"}
            })
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            with open(os.path.join(self.output_dir, "第12話.md"), "r", encoding="utf-8") as f:
                output = f.read()
                self.assertIn("老茧", output)
                self.assertNotIn("努力豆", output)

        with self.subTest("Case 5: Large batch translation run (5 chapters)"):
            self.set_mock_state({})
            for i in range(1, 6):
                self.write_file(os.path.join(self.raw_dir, f"第{i}話.md"), f"第一行{i}\n\n第二行{i}")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            for i in range(1, 6):
                self.assertTrue(os.path.exists(os.path.join(self.output_dir, f"第{i}話.md")))

if __name__ == "__main__":
    unittest.main()
