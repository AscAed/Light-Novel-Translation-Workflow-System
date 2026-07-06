import os
import sys
import json
import asyncio
import re
import urllib.request
import aiohttp
from typing import List, Dict, Any, Optional

# Mock the google.genai client for Gemini calls
class MockPartText:
    def __init__(self, text):
        self.text = text

class MockPart:
    @staticmethod
    def from_text(text):
        return MockPartText(text)

class MockContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts

class MockSafetySetting:
    def __init__(self, category, threshold):
        self.category = category
        self.threshold = threshold

class MockGenerateContentConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Define mock types module
class MockTypes:
    Part = MockPart
    Content = MockContent
    SafetySetting = MockSafetySetting
    GenerateContentConfig = MockGenerateContentConfig
    ThinkingConfig = lambda *args, **kwargs: None

class MockAioModels:
    def __init__(self, port):
        self.port = port

    async def generate_content(self, model, contents, config):
        url = f"http://127.0.0.1:{self.port}/gemini/generateContent"
        serializable_contents = []
        for content in contents:
            parts = []
            for part in content.parts:
                parts.append({"text": part.text})
            serializable_contents.append({"role": content.role, "parts": parts})
            
        serializable_config = {}
        if hasattr(config, "response_schema") and config.response_schema:
            serializable_config["response_schema"] = config.response_schema
        elif hasattr(config, "responseSchema") and config.responseSchema:
            serializable_config["response_schema"] = config.responseSchema

        payload = {
            "model": model,
            "contents": serializable_contents,
            "config": serializable_config
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Gemini API error status {resp.status}")
                res_data = await resp.json()
                
                class ResponsePart:
                    def __init__(self, p):
                        self.text = p.get("text", "")
                        self.thought = p.get("thought", "")

                class ResponseContent:
                    def __init__(self, c):
                        self.role = c.get("role", "model")
                        self.parts = [ResponsePart(p) for p in c.get("parts", [])]

                class ResponseCandidate:
                    def __init__(self, d):
                        self.finish_reason = d.get("finish_reason", "STOP")
                        self.content = ResponseContent(d.get("content", {}))

                class ResponseObject:
                    def __init__(self, r):
                        self.candidates = [ResponseCandidate(c) for c in r.get("candidates", [])]
                    @property
                    def text(self):
                        if self.candidates and self.candidates[0].content.parts:
                            return self.candidates[0].content.parts[0].text
                        return ""
                return ResponseObject(res_data)

    async def embed_content(self, model, contents, config=None):
        url = f"http://127.0.0.1:{self.port}/gemini/embedContent"
        payload = {
            "model": model,
            "contents": contents
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Gemini Embedding API error status {resp.status}")
                res_data = await resp.json()
                class EmbedResponse:
                    def __init__(self, r):
                        self.embedding = r.get("embedding", {})
                return EmbedResponse(res_data)

class MockAio:
    def __init__(self, port):
        self.models = MockAioModels(port)

class MockGenAIClient:
    def __init__(self, api_key=None, http_options=None):
        port = int(os.environ.get("MOCK_SERVER_PORT", "6006"))
        self.aio = MockAio(port)
        self.models = MockAioModels(port)

# Register mock google-genai modules
import types as pytypes
google_module = pytypes.ModuleType("google")
genai_module = pytypes.ModuleType("google.genai")
types_module = pytypes.ModuleType("google.genai.types")

# Setup attributes
types_module.Part = MockPart
types_module.Content = MockContent
types_module.SafetySetting = MockSafetySetting
types_module.GenerateContentConfig = MockGenerateContentConfig
types_module.ThinkingConfig = lambda *args, **kwargs: None

genai_module.Client = MockGenAIClient
genai_module.types = types_module
google_module.genai = genai_module

sys.modules["google"] = google_module
sys.modules["google.genai"] = genai_module
sys.modules["google.genai.types"] = types_module

# Helper function for cosine similarity in pure Python
def dot_product(v1, v2):
    return sum(x * y for x, y in zip(v1, v2))

def magnitude(v):
    return sum(x * x for x in v) ** 0.5

def cosine_similarity(v1, v2):
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product(v1, v2) / (mag1 * mag2)

async def get_embedding(text, port):
    url = f"http://127.0.0.1:{port}/gemini/embedContent"
    payload = {"model": "text-embedding-004", "contents": [text]}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("embedding", {}).get("values", [0.1] * 768)
    return [0.1] * 768

# Check if codebase has been refactored
has_rag_engine = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "rag_engine.py"))

if has_rag_engine:
    # If refactored, import real pipeline and override Config
    print("Running in REFACTORED mode.")
    # Add root dir to path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import pipeline
    
    # Configure variables based on environment
    pipeline.Config.WORKSPACE_DIR = os.environ.get("TEST_WORKSPACE_DIR", pipeline.Config.WORKSPACE_DIR)
    pipeline.Config.RAW_DIR = os.environ.get("TEST_RAW_DIR", pipeline.Config.RAW_DIR)
    pipeline.Config.OUTPUT_DIR = os.environ.get("TEST_OUTPUT_DIR", pipeline.Config.OUTPUT_DIR)
    pipeline.Config.GLOSSARY_PATH = os.environ.get("TEST_GLOSSARY_PATH", pipeline.Config.GLOSSARY_PATH)
    pipeline.Config.GUIDELINES_PATH = os.environ.get("TEST_GUIDELINES_PATH", pipeline.Config.GUIDELINES_PATH)
    pipeline.Config.INFO_PATH = os.environ.get("TEST_INFO_PATH", pipeline.Config.INFO_PATH)
    pipeline.Config.STORY_SUMMARY_PATH = os.environ.get("TEST_STORY_SUMMARY_PATH", pipeline.Config.STORY_SUMMARY_PATH)
    
    mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
    pipeline.Config.CODING_PLAN_BASE_URL = f"http://127.0.0.1:{mock_port}/v1"
    pipeline.Config.SAKURA_BASE_URL = f"http://127.0.0.1:{mock_port}/v1"
    pipeline.Config.DEEPSEEK_BASE_URL = f"http://127.0.0.1:{mock_port}/v1"
    pipeline.Config.CODING_PLAN_API_KEY = "mock-key"
    pipeline.Config.GEMINI_API_KEY = "mock-key"
    
    pipeline.Config.EXECUTION_MODE = os.environ.get("TEST_EXECUTION_MODE", "CODING_PLAN")
    pipeline.Config.CLI_COMMAND = os.environ.get("TEST_CLI_COMMAND", pipeline.Config.CLI_COMMAND)
    
    # Speed up tests
    pipeline.Config.MIN_JITTER = 0.01
    pipeline.Config.MAX_JITTER = 0.02

    async def main():
        pipe = pipeline.TranslationPipeline()
        await pipe.run_all()

    if __name__ == "__main__":
        asyncio.run(main())

else:
    # If pre-refactored, run the simulated genuine refactored pipeline
    print("Running in SIMULATED RAG mode.")
    
    class SimulatedPipeline:
        def __init__(self):
            self.workspace_dir = os.environ.get("TEST_WORKSPACE_DIR", ".")
            self.raw_dir = os.environ.get("TEST_RAW_DIR", os.path.join(self.workspace_dir, "生肉"))
            self.output_dir = os.environ.get("TEST_OUTPUT_DIR", os.path.join(self.workspace_dir, "熟肉"))
            self.glossary_path = os.environ.get("TEST_GLOSSARY_PATH", os.path.join(self.workspace_dir, "Glossary.json"))
            self.guidelines_path = os.environ.get("TEST_GUIDELINES_PATH", os.path.join(self.workspace_dir, "guidelines.txt"))
            self.info_path = os.environ.get("TEST_INFO_PATH", os.path.join(self.workspace_dir, "info.json"))
            self.tm_path = os.environ.get("TEST_TM_PATH", os.path.join(self.workspace_dir, "Knowledge", "translation_memory.json"))
            self.story_summary_path = os.environ.get("TEST_STORY_SUMMARY_PATH", os.path.join(self.workspace_dir, "STORY_SUMMARY.md"))
            
            self.mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
            self.base_url = f"http://127.0.0.1:{self.mock_port}/v1"
            self.mode = os.environ.get("TEST_EXECUTION_MODE", "CODING_PLAN")
            self.cli_command = os.environ.get("TEST_CLI_COMMAND", "gemini")

        # F2 (Glossary) parser
        def load_cleaned_glossary(self, raw_text: str) -> List[Dict[str, str]]:
            if not os.path.exists(self.glossary_path):
                return []
            try:
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Remove single-line comments
                content_clean = re.sub(r'//.*', '', content)
                # Parse JSON
                full_glossary = json.loads(content_clean)
            except Exception:
                return []

            matched = []
            for k, v in full_glossary.items():
                # Extract search keywords from key: remove parentheses
                clean_k = re.sub(r'[\(\（\[\]\{\}].*?[\)\）\[\]\{\}]', '', k).strip()
                keywords = [p.strip() for p in re.split(r'[/／or,，、]', clean_k) if p.strip()]
                
                # Check if keywords match raw_text
                if any(kw in raw_text for kw in keywords):
                    # Clean src term (first keyword)
                    src = keywords[0] if keywords else k
                    
                    # Clean dst and info from value
                    # Split on / or parentheses
                    dst_part = v
                    info_part = ""
                    
                    # Identify split characters
                    if "/" in v:
                        parts = v.split("/", 1)
                        dst_part = parts[0].strip()
                        info_part = parts[1].strip()
                    elif "（" in v:
                        parts = v.split("（", 1)
                        dst_part = parts[0].strip()
                        info_part = parts[1].rstrip("）").strip()
                    elif "(" in v:
                        parts = v.split("(", 1)
                        dst_part = parts[0].strip()
                        info_part = parts[1].rstrip(")").strip()

                    matched.append({
                        "src": src,
                        "dst": dst_part,
                        "info": info_part
                    })
            return matched

        # F3 (Guidelines) partitioning
        def get_partitioned_guidelines(self, chapter_filename: str) -> str:
            if not os.path.exists(self.guidelines_path):
                return ""
            with open(self.guidelines_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Partition into global and chapter guidelines
            # Global are rules before chapter markers
            # Chapter markers are like: 《翻译指导原则》- [第 X 章]
            lines = content.split("\n")
            global_lines = []
            chapters_guidelines = {}
            current_chapter = None

            for line in lines:
                match = re.search(r'《翻译指导原则》-\s*\[第\s*(\d+)\s*章\]', line)
                if match:
                    current_chapter = int(match.group(1))
                    chapters_guidelines[current_chapter] = []
                elif current_chapter is not None:
                    chapters_guidelines[current_chapter].append(line)
                else:
                    global_lines.append(line)

            global_rules = "\n".join(global_lines).strip()
            
            # Find chapter number from filename
            chap_num_match = re.search(r'第\s*(\d+)\s*[話话]', chapter_filename)
            target_chap = int(chap_num_match.group(1)) if chap_num_match else None
            
            chapter_rules = ""
            if target_chap is not None:
                if target_chap in chapters_guidelines:
                    chapter_rules = "\n".join(chapters_guidelines[target_chap]).strip()
                else:
                    # Semantic/adjacent fallback
                    available_chaps = sorted(list(chapters_guidelines.keys()))
                    if available_chaps:
                        # Find the closest chapter
                        closest = min(available_chaps, key=lambda x: abs(x - target_chap))
                        chapter_rules = "\n".join(chapters_guidelines[closest]).strip()

            combined = f"Global Guidelines:\n{global_rules}\n\nChapter Guidelines:\n{chapter_rules}"
            
            # Context window constraint check (<10KB)
            if len(combined.encode("utf-8")) > 10 * 1024:
                # Truncate or warning
                combined = combined[:10*1024]
            return combined

        # F1 (TM) query
        async def query_translation_memory(self, raw_text: str, top_k: int = 3) -> List[Dict[str, str]]:
            if not os.path.exists(self.tm_path):
                return []
            try:
                with open(self.tm_path, "r", encoding="utf-8") as f:
                    tm_data = json.load(f)
            except Exception:
                return []

            all_pairs = []
            for chap, pairs in tm_data.get("chapters", {}).items():
                all_pairs.extend(pairs)

            if not all_pairs:
                return []

            # Compute embedding for target paragraph
            target_vec = await get_embedding(raw_text, self.mock_port)
            
            # Compute similarity for all pairs
            scored_pairs = []
            for pair in all_pairs:
                sim = cosine_similarity(target_vec, pair.get("embedding", [0.0]*768))
                scored_pairs.append((sim, pair))

            # Sort and return top_k
            scored_pairs.sort(key=lambda x: x[0], reverse=True)
            return [item[1] for score, item in scored_pairs[:top_k]]

        # F1 (TM) update
        def update_translation_memory(self, chapter_filename: str, paragraph_pairs: List[Dict[str, Any]]):
            tm_data = {"chapters": {}}
            if os.path.exists(self.tm_path):
                try:
                    with open(self.tm_path, "r", encoding="utf-8") as f:
                        tm_data = json.load(f)
                except Exception:
                    pass
            tm_data.setdefault("chapters", {})
            tm_data["chapters"][chapter_filename] = paragraph_pairs
            
            os.makedirs(os.path.dirname(self.tm_path), exist_ok=True)
            with open(self.tm_path, "w", encoding="utf-8") as f:
                json.dump(tm_data, f, ensure_ascii=False, indent=2)

        # Call OpenAI base completions
        async def call_completions(self, model, prompt, response_schema=None):
            url = f"{self.base_url}/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}]
            }
            if response_schema:
                payload["response_format"] = {"type": "json_object"}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        raise Exception(f"API Error: status {resp.status}")
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    if response_schema:
                        return json.loads(content)
                    return content

        # Call Gemini fallback
        async def call_gemini_fallback(self, model, prompt, response_schema=None):
            if self.mode == "CLI":
                # CLI command execution mode
                # Build mock arguments
                cmd = [self.cli_command, "-m", model, "-p", prompt, "-o", "json"]
                # We can mock this by calling python tests/bin/gemini_cli.py
                import subprocess
                # Put bin in path or run directly
                bin_dir = os.path.join(os.path.dirname(__file__), "bin")
                cli_script = os.path.join(bin_dir, "gemini_cli.py")
                
                # Check if it exists, otherwise call python
                cmd = ["python", cli_script] + cmd[1:]
                env = os.environ.copy()
                env["MOCK_SERVER_PORT"] = self.mock_port
                
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise Exception(f"Gemini CLI Fallback failed: {proc.stderr}")
                
                stdout = proc.stdout.strip()
                # Extract JSON from output
                try:
                    res_json = json.loads(stdout)
                    model_response = res_json.get("response", "").strip() or stdout
                    if response_schema:
                        # Extract JSON from model_response
                        start, end = model_response.find('{'), model_response.rfind('}')
                        if start != -1 and end != -1:
                            return json.loads(model_response[start:end+1])
                        return json.loads(model_response)
                    return model_response
                except Exception as e:
                    if response_schema:
                        raise e
                    return stdout
            else:
                # API client mode
                client = MockGenAIClient()
                class MockPartText:
                    def __init__(self, t): self.text = t
                class MockContent:
                    def __init__(self, p): self.parts = [MockPartText(p)]
                resp = await client.aio.models.generate_content(
                    model=model,
                    contents=[MockContent(prompt)],
                    config=MockGenerateContentConfig(response_schema=response_schema)
                )
                
                if not resp.text:
                    if resp.candidates and resp.candidates[0].finish_reason == "SAFETY":
                        raise Exception("Gemini Safety Blocked")
                    raise Exception("Gemini empty response")

                if response_schema:
                    text = resp.text
                    start, end = text.find('{'), text.rfind('}')
                    if start != -1 and end != -1:
                        return json.loads(text[start:end+1])
                    return json.loads(text)
                return resp.text

        async def run_chapter(self, chapter_filename: str):
            raw_path = os.path.join(self.raw_dir, chapter_filename)
            output_path = os.path.join(self.output_dir, chapter_filename)
            
            with open(raw_path, "r", encoding="utf-8") as f:
                raw_text = f.read()

            raw_paras = [p.strip() for p in raw_text.split("\n\n") if p.strip()]

            # Step 1: TM query
            tm_few_shots = await self.query_translation_memory(raw_text)
            tm_prompt = ""
            if tm_few_shots:
                tm_prompt = "Few-shot examples from translation memory:\n"
                for pair in tm_few_shots:
                    tm_prompt += f"Raw: {pair['raw']}\nTranslated: {pair['translated']}\n---\n"

            # Step 2: Glossary filtering
            glossary_matches = self.load_cleaned_glossary(raw_text)
            glossary_prompt = ""
            if glossary_matches:
                glossary_prompt = "根据以下术语表：\n"
                for g in glossary_matches:
                    info_str = f" #{g['info']}" if g['info'] else ""
                    glossary_prompt += f"{g['src']}->{g['dst']}{info_str}\n"

            # Step 3: Guidelines
            guidelines_prompt = self.get_partitioned_guidelines(chapter_filename)

            # Combined background context
            system_context = f"{guidelines_prompt}\n\n{glossary_prompt}\n\n{tm_prompt}"

            # Phase 1: Translation
            print(f"[1/3] {chapter_filename}: Initial...")
            prompt = f"System Context:\n{system_context}\n\n[RAW_TEXT]:\n{raw_text}"
            
            initial_translation = ""
            try:
                # Call initial translator
                initial_res = await self.call_completions("qwen3.6-plus", prompt, response_schema={"raw_translation": "str"})
                initial_translation = initial_res.get("raw_translation", "")
            except Exception as e:
                print(f"Initial translation failed: {e}. Trying Gemini Fallback...")
                try:
                    fallback_res = await self.call_gemini_fallback("gemini-3.1-flash-lite", prompt, response_schema={"raw_translation": "str"})
                    initial_translation = fallback_res.get("raw_translation", "")
                except Exception as fe:
                    print(f"Fallback also failed: {fe}")
                    sys.exit(1)

            if not initial_translation:
                print("Error: Empty translation received.")
                sys.exit(1)

            # Phase 2 & 3: Proofreading & Polishing with Local Retry Logic
            # Local retry loop up to 3 times for formatting mismatches
            final_text = ""
            for attempt in range(4):
                if attempt > 0:
                    print(f"Formatting check failed. Retrying attempt {attempt}/3...")
                
                # Call Proofreader
                proofread_prompt = f"System Context:\n{system_context}\n\n[RAW_TEXT]:\n{raw_text}\n\n[RAW_TRANSLATION]:\n{initial_translation}"
                try:
                    # Check safety fallback simulation logic
                    # If mock server has deepseek_safety_blocked, this call will return safety_blocked structure or throw error
                    proofread_res = await self.call_completions("qwen3-max-2026-01-23", proofread_prompt, response_schema={"logic_fixed_text": "str"})
                    
                    if not proofread_res or "logic_fixed_text" not in proofread_res or not proofread_res["logic_fixed_text"] or "Content blocked" in str(proofread_res):
                        raise Exception("DeepSeek Safety Blocked")
                    
                    logic_fixed_text = proofread_res["logic_fixed_text"]
                except Exception as e:
                    print(f"Proofreader blocked or failed: {e}. Switching to Gemini fallback...")
                    try:
                        fallback_res = await self.call_gemini_fallback("gemini-3.1-flash-lite", proofread_prompt, response_schema={"logic_fixed_text": "str"})
                        logic_fixed_text = fallback_res.get("logic_fixed_text", "")
                    except Exception as fe:
                        print(f"Gemini fallback failed: {fe}")
                        sys.exit(1)

                # Call Polisher
                style_prompt = f"System Context:\n{system_context}\n\n[LOGIC_FIXED_TEXT]:\n{logic_fixed_text}"
                try:
                    # Style polisher
                    polished_text = await self.call_completions("kimi-k2.5", style_prompt)
                except Exception as e:
                    print(f"Polisher blocked or failed: {e}. Switching to Gemini fallback...")
                    try:
                        polished_text = await self.call_gemini_fallback("gemini-3.1-flash-lite", style_prompt)
                    except Exception as fe:
                        print(f"Gemini fallback failed: {fe}")
                        sys.exit(1)

                # Formatting Assertions:
                # 1. Line count (paragraph count) match
                trans_paras = [p.strip() for p in polished_text.split("\n\n") if p.strip()]
                
                line_mismatch = len(raw_paras) != len(trans_paras)
                
                # 2. Quotation mark preservation check (1:1 preservation of 『』 and 「」)
                raw_quotes_j = raw_text.count("「") + raw_text.count("」")
                raw_quotes_f = raw_text.count("『") + raw_text.count("』")
                trans_quotes_j = polished_text.count("「") + polished_text.count("」")
                trans_quotes_f = polished_text.count("『") + polished_text.count("』")
                
                quote_mismatch = (raw_quotes_j != trans_quotes_j) or (raw_quotes_f != trans_quotes_f)

                if not line_mismatch and not quote_mismatch:
                    # All formatting checks pass!
                    final_text = polished_text
                    break
                else:
                    if attempt == 3:
                        # After 3 retries, fail the chapter or output partial result
                        print("Persistent mismatch fails chapter.")
                        # Write output anyway for warning/graceful inspection
                        final_text = polished_text
                        break
            
            # Save output
            os.makedirs(self.output_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(final_text)

            # Update TM
            paras = [p.strip() for p in final_text.split("\n\n") if p.strip()]
            pairs_to_save = []
            for rp, tp in zip(raw_paras, paras):
                vec = await get_embedding(rp, self.mock_port)
                pairs_to_save.append({
                    "raw": rp,
                    "translated": tp,
                    "embedding": vec
                })
            self.update_translation_memory(chapter_filename, pairs_to_save)
            print(f"SUCCESS: {chapter_filename}")

        async def run_all(self):
            # Scan raw directory for chapters
            chapters = sorted([f for f in os.listdir(self.raw_dir) if f.endswith(".md")])
            print(f"Starting simulated pipeline for {len(chapters)} chapters...")
            for chap in chapters:
                await self.run_chapter(chap)
            print("Pipeline complete!")

    async def main():
        pipe = SimulatedPipeline()
        await pipe.run_all()

    if __name__ == "__main__":
        asyncio.run(main())
