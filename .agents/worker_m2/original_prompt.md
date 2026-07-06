## 2026-06-08T14:10:34Z
You are the RAG Engine Implementer (teamwork_preview_worker).
Your working directory is: d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/.agents/worker_m2
Your parent conversation ID is: 5c16cbb5-ce45-4d54-add9-e9c114b4d369

Your task is to implement the RAG retrieval module `rag_engine.py` under the project root, as specified in PROJECT.md (Milestone 2).

### Requirements for `rag_engine.py`
1. Implement the class `RAGEngine` in `rag_engine.py` under the project root.
2. The class interface MUST conform to the contract defined in PROJECT.md:
   - `def __init__(self, tm_path: str, glossary_path: str, guidelines_path: str)`: Initialises paths and loads data from files.
   - `async def query_translation_memory(self, raw_text: str, top_k: int = 3) -> List[Dict[str, str]]`:
     - Computes the embedding for the `raw_text` using Gemini Embedding 2 (`text-embedding-004`) via the official `google-genai` client (with standard API key config, or checking if `MOCK_SERVER_PORT` is set in the environment to redirect to the mock server as done in `align_chapters.py`).
     - Computes cosine similarity against all paragraphs in `translation_memory.json` using NumPy.
     - Returns the top_k most similar paragraph pairs (each as a dict with `raw` and `translated` keys). If TM is empty or missing, return an empty list.
   - `def get_cleaned_glossary(self, raw_text: str) -> List[Dict[str, str]]`:
     - Parses `Glossary.json` (removing single-line comments like `// ...` if present, since Glossary.json contains comments).
     - Applies the cleaning heuristics:
       - Keys: Remove parentheses (e.g., `ネトラレラ (Netorarera)` -> `src = "ネトラレラ"`). Split the cleaned key into keywords by separators (e.g. `/`, `／`, `or`, `,`, `，`, `、`).
       - Matches if any keyword is present in `raw_text`.
       - For matched items, the `src` is the first keyword in the list.
       - Values: Split by `/` or parentheses to separate direct translation `dst` and explanation/metadata `info`. Extract the first concise term as `dst` (e.g. `"努力豆（マメ本意为...） / 老茧"` -> `dst = "努力豆"`, `info = "努力豆（マメ本意为...） / 老茧"`).
       - Returns a list of dicts: `[{"src": src, "dst": dst, "info": info}, ...]`.
   - `def get_partitioned_guidelines(self, chapter_filename: str) -> str`:
     - Parses `guidelines.txt` into sections.
     - Section headers match `《翻译指导原则》- [第 X 章]` or `《翻译指导原则》- [全局通用]`.
     - Extract global guidelines from `[全局通用]` (and any text before chapter sections).
     - Find chapter number from `chapter_filename` (e.g., `第12話.md` -> 12).
     - Search for matching chapter guidelines `[第 12 章]`.
     - If not found, fall back to semantic similarity matching among adjacent chapters:
       - Retrieve adjacent chapters (e.g. `target_chap-1`, `target_chap-2`, `target_chap+1`, `target_chap+2`) that have guidelines.
       - Query their raw text in `translation_memory.json` or raw files. Compare the current chapter's raw text embedding with the candidates' raw text embeddings (e.g. average embedding of paragraphs in `translation_memory.json`).
       - If no semantic candidate is available, fall back to the closest chapter number by absolute difference.
       - Return the combined guidelines. Ensure the result is constrained to <10KB.
   - `def update_translation_memory(self, chapter_filename: str, paragraph_pairs: List[Dict[str, Any]])`:
     - Appends new mappings to `translation_memory.json`.
     - Generates embedding vectors for the raw paragraphs using Gemini Embedding 2 (`text-embedding-004`).
     - Saves the updated translation memory database to disk.
3. Write clean, modular code following the constraints:
   - Max 50 lines per function.
   - Max 700 lines per file.
   - Cyclomatic complexity under 10.
   - Use Australian English spelling conventions (e.g. "initialise", "categorised").
   - Handle exceptions and edge cases gracefully.
4. Write unit tests for `rag_engine.py` in `tests/test_rag_engine_unit.py`.
5. Run the unit tests and verify they all pass.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Please report implementation outcomes, list files created, and write your handoff report in handoff.md.
