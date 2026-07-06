## 2026-06-08T22:20:59+08:00
You are the Pipeline Refactoring Implementer (teamwork_preview_worker).
Your working directory is: d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/.agents/worker_m3
Your parent conversation ID is: 5c16cbb5-ce45-4d54-add9-e9c114b4d369

Your task is to refactor `pipeline.py` under the project root to integrate the RAG retrieval module `rag_engine.py` and migrate the API stack to Sakura and DeepSeek, with safety fallback to Gemini.

### Key Requirements
1. Import `RAGEngine` from `rag_engine.py`.
2. Initialise the RAG engine in `TranslationPipeline.__init__`:
   `self.rag = RAGEngine(Config.TM_PATH, Config.GLOSSARY_PATH, Config.GUIDELINES_PATH)`
3. In `run_chapter` under `TranslationPipeline`:
   - Retrieve guidelines: `guidelines = self.rag.get_partitioned_guidelines(chapter_filename)`
   - Query TM matches: `tm_matches = await self.rag.query_translation_memory(raw_text)`
     Format TM few-shots in the prompt if not empty.
   - Get cleaned glossary entries matching `raw_text`: `glossary_matches = self.rag.get_cleaned_glossary(raw_text)`
     Format glossary in the prompt according to the template in `DEVELOPMENT_PLAN.md`:
     - If not empty:
       ```
       根据以下术语表（可以为空）：
       [src_1]->[dst_1] #[info_1]
       ...
       将下面的日文文本根据对应关系和备注翻译成中文：[japanese]
       ```
       (Do not append ` #[info_1]` if `info_1` is empty or not provided).
     - If empty:
       ```
       将下面的日文文本翻译成中文：[japanese]
       ```
   - Combine guidelines, glossary, and TM few-shots into the background context.
   - Include the sliced story summary using `get_sliced_story_summary(self.story_summary, current_chap_num)` in the background context.
4. API client config and migration:
   - Initial translation uses Sakura-14B API (using ChatML templates at `Config.SAKURA_BASE_URL`).
   - Proofreading uses `deepseek-v4-flash` via `Config.DEEPSEEK_BASE_URL`.
   - Polishing uses `deepseek-v4-pro` via `Config.DEEPSEEK_BASE_URL`.
   - In `pipeline.py`, define:
     - `Config.SAKURA_BASE_URL = "http://127.0.0.1:6006/v1"`
     - `Config.DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"`
     - If `os.environ.get("MOCK_SERVER_PORT")` is set, or if `Config.CODING_PLAN_BASE_URL` contains `127.0.0.1` or the mock port, redirect Sakura and DeepSeek clients to use that mock URL to ensure E2E tests route to the mock server correctly.
   - Implement automatic fallback to Gemini 3.1 Flash Lite (`gemini-3.1-flash-lite`) via `google-genai` client, with safety settings set to `BLOCK_NONE`, whenever a DeepSeek (or Sakura) API call throws an exception, or returns a response containing `"Content blocked"` / has `finish_reason == "content_filter"`.
5. Local retry loop for formatting integrity (up to 3 retries, i.e., 4 total attempts):
   - Run Proofreading and Polishing inside the retry loop.
   - Check line-count: Split raw and polished text by double newlines (`\n\n`) and compare counts.
   - Check quotes: Preserve Japanese quote marks `『』` and `「」` 1:1.
   - If there is a mismatch, warn and retry. If it still fails on the 4th attempt, warn and output the best result anyway.
6. Incremental TM updates:
   - Upon successful chapter translation, call `self.rag.update_translation_memory(chapter_filename, pairs)` where `pairs` is `[{"raw": rp, "translated": tp} for rp, tp in zip(raw_paras, trans_paras)]`.
7. Keep the code concise and clean:
   - **CRITICAL**: The final `pipeline.py` file must be under 700 lines. Completely remove unused CLI execution modes, KV cache code, and any unused variables to achieve this.
   - Keep functions under 50 lines.
   - Keep cyclomatic complexity under 10.
   - Use Australian English spelling defaults.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Please perform the refactoring, write a brief summary of changes, and report the path of any files modified.
