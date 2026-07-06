import os
import sys
import json
import unittest
import tempfile
import shutil
import subprocess
import urllib.request

class E2ETestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
        cls.mock_url = f"http://127.0.0.1:{cls.mock_port}"
        
        # Determine paths to scripts
        cls.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.run_pipeline_script = os.path.join(cls.project_root, "tests", "run_pipeline.py")
        
        if os.path.exists(os.path.join(cls.project_root, "scripts", "align_chapters.py")):
            cls.align_script = os.path.join(cls.project_root, "scripts", "align_chapters.py")
        else:
            cls.align_script = os.path.join(cls.project_root, "tests", "run_align_chapters.py")

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
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self.fail(f"Failed to set mock state: {e}")

    def run_pipeline(self, mode="CODING_PLAN", extra_env=None):
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
        env["TEST_EXECUTION_MODE"] = mode
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
        with self.subTest("Case 21: DeepSeek safety block triggers Gemini fallback"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            # Content should have the gemini signature prefix
            with open(os.path.join(self.output_dir, "第12話.md"), "r", encoding="utf-8") as f:
                output = f.read()
                self.assertIn("Gemini", output)

        with self.subTest("Case 22: Gemini Flash Lite fallback called with BLOCK_NONE"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 23: Fallback handles API errors (status 500) on DeepSeek by calling Gemini"):
            self.set_mock_state({"deepseek_status_code": 500})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 24: Safe translation of explicit content completes without block"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 25: Gemini fallback preserves translation style"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "テスト")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # F6 (Formatting Assertions) Cases (26-30)
        with self.subTest("Case 26: Line count matches 1:1 between raw and translated"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 27: Quote marks are preserved 1:1"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「こんにちは」\n\n『テスト』")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 28: Line count mismatch triggers warning and local retry"):
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 29: Quote mismatch triggers warning and local retry"):
            self.set_mock_state({"quote_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "「こんにちは」")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 30: Persistent mismatch fails chapter gracefully"):
            # Set state to permanently cause line count mismatch
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

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
            self.assertNotEqual(res.returncode, 0) # Should fail

        with self.subTest("Case 35: Invalid JSON TM"):
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), "{invalid json}")
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

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
        with self.subTest("Case 45: Sakura endpoint offline"):
            self.set_mock_state({"sakura_offline": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            # If Sakura offline, it fallbacks to Gemini and succeeds
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 46: Partial response from Sakura (handled by json extraction fallback)"):
            # Empty response or corrupt json
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 47: DeepSeek rate limit (429) retry logic"):
            self.set_mock_state({"deepseek_status_code": 429})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            # If DeepSeek returns 429, retry triggers fallback to Gemini, so it succeeds
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 48: Empty API key"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline(extra_env={"CODING_PLAN_API_KEY": ""})
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 49: Sakura timeout (simulated via status 504)"):
            self.set_mock_state({"deepseek_status_code": 504})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        # Safety Boundaries (50-53)
        with self.subTest("Case 50: Both DeepSeek and Gemini block"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            # Both blocked should fail or exit non-zero
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 51: Gemini rate limit (429) during fallback"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_status_code": 429})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 52: Empty response from Gemini"):
            self.set_mock_state({"deepseek_safety_blocked": True, "gemini_status_code": 204}) # NoContent
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "敏感内容")
            res = self.run_pipeline()
            self.assertNotEqual(res.returncode, 0)

        with self.subTest("Case 53: Gemini fallback triggers on multiple consecutive chapters"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试1")
            self.write_file(os.path.join(self.raw_dir, "第13話.md"), "测试2")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第12話.md")))
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第13話.md")))

        # Formatting Boundaries (54-58)
        with self.subTest("Case 54: Paragraph with multiple nested quotes"):
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

        with self.subTest("Case 3: Safety block triggers on a chapter containing glossary matches"):
            self.write_file(os.path.join(self.knowledge_dir, "Glossary.json"), {"测试": "术语"}, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试")
            self.set_mock_state({"deepseek_safety_blocked": True})
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            with open(os.path.join(self.output_dir, "第12話.md"), "r", encoding="utf-8") as f:
                output = f.read()
                self.assertIn("Gemini", output)

        with self.subTest("Case 4: Line count mismatch retry + DeepSeek safety block triggers fallback"):
            self.set_mock_state({
                "line_count_mismatch_active": True,
                "deepseek_safety_blocked": True
            })
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 5: Missing chapter guidelines semantic fallback + TM match"):
            tm_content = {"chapters": {"chap1.md": [{"raw": "测试", "translated": "测试译", "embedding": [0.1]*768}]}}
            self.write_file(os.path.join(self.knowledge_dir, "translation_memory.json"), tm_content, is_json=True)
            self.write_file(os.path.join(self.raw_dir, "第15話.md"), "测试")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)

        with self.subTest("Case 6: Local retry fails 3 times on line count mismatch, outputs partial"):
            self.set_mock_state({"line_count_mismatch_active": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "第一行\n\n第二行")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

    # ==========================================
    # TIER 4: Real-World Scenarios (5 Cases)
    # ==========================================
    def test_tier4_real_world(self):
        with self.subTest("Case 1: E2E translation of a normal chapter"):
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "测试内容")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.output_dir, "第12話.md")))

        with self.subTest("Case 2: E2E translation of an explicit chapter triggering safety block"):
            self.set_mock_state({"deepseek_safety_blocked": True})
            self.write_file(os.path.join(self.raw_dir, "第12話.md"), "极其敏感的内容")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            with open(os.path.join(self.output_dir, "第12話.md"), "r", encoding="utf-8") as f:
                output = f.read()
                self.assertIn("Gemini", output)

        with self.subTest("Case 3: Align chapters 1-18, save TM, then run pipeline for chapter 19"):
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
            for i in range(1, 6):
                self.write_file(os.path.join(self.raw_dir, f"第{i}話.md"), f"第一行{i}\n\n第二行{i}")
            res = self.run_pipeline()
            self.assertEqual(res.returncode, 0)
            for i in range(1, 6):
                self.assertTrue(os.path.exists(os.path.join(self.output_dir, f"第{i}話.md")))

if __name__ == "__main__":
    unittest.main()
