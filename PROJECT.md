# Project: RAG-based Workflow & API Stack Refactoring

## Architecture
- **Translation Memory (TM)**: Aligns and caches paragraph pairs for existing chapters using `Gemini Embedding 2` (`text-embedding-004`). Search uses cosine similarity (via NumPy) to find few-shot context examples.
- **Glossary Hybrid Retrieval**: Extracts clean terminology mappings (`src`, `dst`, `info`) from `Knowledge/Glossary.json` to prevent contamination.
- **Partitioned Guidelines**: Splits global rules and chapter-specific rules, falling back semantically if a chapter-specific guideline is not present.
- **Sakura / DeepSeek Translation Pipeline**: Initial translation via Sakura-14B API (using ChatML templates at `http://127.0.0.1:6006/v1`), logic auditing via `deepseek-v4-flash`, and stylistic polishing via `deepseek-v4-pro`.
- **Dual-Track Safety Fallback**: Automatic failover to `Gemini 3.1 Flash Lite` (with `BLOCK_NONE` safety settings) when DeepSeek triggers a safety block on explicit content.
- **Formatting Assertion**: Enforces paragraph count and quotation preservation 1:1.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1_align_indexing | Develop `scripts/align_chapters.py` to align chapters 1-18, compute embedding vectors and cache in `Knowledge/translation_memory.json`. | None | IN_PROGRESS (Running alignment script) |
| 2 | M2_rag_engine | Create `rag_engine.py` for similarity search, glossary parsing, guideline partitioning, and index updating. | M1 | COMPLETE |
| 3 | M3_pipeline_refactor | Refactor `pipeline.py` to use `rag_engine.py`, migrate to Sakura/DeepSeek, and integrate Gemini fallback. | M2 | COMPLETE |
| 4 | M4_e2e_testing | E2E Testing track: Develop test cases (Tiers 1-4) and publish `TEST_READY.md`. | None | COMPLETE |
| 5 | M5_verification | Implementation Track Final Milestone: Pass 100% E2E tests, then execute Tier 5 adversarial coverage hardening. | M3, M4 | IN_PROGRESS (Running E2E tests) |

## Interface Contracts
### `scripts/align_chapters.py`
- Executed from terminal.
- Input: `生肉` and `熟肉` chapter directories.
- Output: Creates `Knowledge/translation_memory.json`.

### `rag_engine.py` ↔ `pipeline.py`
- `class RAGEngine`:
  - `def __init__(self, tm_path: str, glossary_path: str, guidelines_path: str)`: Initialises paths.
  - `async def query_translation_memory(self, raw_text: str, top_k: int = 3) -> List[Dict[str, str]]`: Returns raw and translated paragraph pairs matched via cosine similarity.
  - `def get_cleaned_glossary(self, raw_text: str) -> List[Dict[str, str]]`: Filters and returns parsed glossary items (containing `src`, `dst`, and optionally `info`).
  - `def get_partitioned_guidelines(self, chapter_filename: str) -> str`: Returns combined global guidelines and matching or semantic-fallback chapter-specific guidelines.
  - `def update_translation_memory(self, chapter_filename: str, paragraph_pairs: List[Dict[str, str]])`: Appends new mappings to `Knowledge/translation_memory.json`.

## Code Layout

- `pipeline.py` - Main translation pipeline script.
- `rag_engine.py` - RAG retrieval logic.
- `scripts/align_chapters.py` - Alignment and indexing tool.
- `Knowledge/` - Directory for guidelines, glossary, and compiled databases.
  - `guidelines.txt` - Source guidelines file.
  - `Glossary.json` - Source glossary file.
  - `translation_memory.json` - Compiled vector search database.
- `tests/` - Directory for test cases and test runner.
