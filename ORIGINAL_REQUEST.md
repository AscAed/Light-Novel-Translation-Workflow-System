# Original User Request

## Initial Request — 2026-06-08T13:53:50Z

Upgrade the light novel translation workflow system to a RAG-enabled translation pipeline as specified in `DEVELOPMENT_PLAN.md`, including translation memory, glossary hybrid retrieval, guideline partitioning, API migration to Sakura/DeepSeek, safety fallback to Gemini, and formatting integrity verification.

Working directory: d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人
Integrity mode: development

## Requirements

### R1. Translation Memory Database & Alignment Tool
- Develop a tool `scripts/align_chapters.py` to align paragraph structures of existing Japanese/Chinese translated chapters in `生肉` and `熟肉`.
- The alignment strategy must parse paragraphs by double-newline splitting. If paragraph counts match exactly, align them 1-to-1. If counts do not match, log a warning and use a heuristic or semantic alignment fallback (avoiding corrupted or shifted alignments).
- Call Gemini Embedding 2 API (`text-embedding-004`) to generate and cache vectors for raw paragraphs and save the compiled index to `Knowledge/translation_memory.json`.
- Newly translated chapters must append their paragraph pairs and embeddings to the TM database.

### R2. RAG Retrieval Module & Glossary Parser
- Create `rag_engine.py` with vector search capabilities using cosine similarity.
- Implement heuristic parsing rules to extract clean target terms (`src`, `dst`, `info`) from `Glossary.json` without explanatory contamination.
- Partition guidelines in `Knowledge/guidelines.txt` into global and chapter-specific segments with semantic fallback when no chapter-specific guideline matches.

### R3. Pipeline Refactoring & API Migration
- Integrate `rag_engine.py` into `pipeline.py`.
- Configure Sakura API at `http://127.0.0.1:6006/v1` using standard OpenAI client wrapper for initial translation (using ChatML template).
- Replace DashScope with DeepSeek (`deepseek-v4-flash`/`deepseek-v4-pro` or equivalent OpenAI-compatible endpoint configuration) APIs for proofreading and polishing.
- Implement automatic fallback to Gemini 3.1 Flash Lite (with `BLOCK_NONE` safety settings) when DeepSeek triggers a safety block on explicit content.
- Enforce line-count assertions and punctuation preservation (Japanese quote marks `『』`, `「」`) with local retry logic.

## Acceptance Criteria

### Translation Memory and Retrieval
- [ ] Existing chapters 1-18 are aligned and indexed in `Knowledge/translation_memory.json` with pre-computed vectors.
- [ ] Context window size for guidelines is dynamically retrieved and reduced from ~160KB to <10KB per call.
- [ ] Glossary terms are parsed correctly according to cleaning rules, avoiding explanatory text insertion in translated text.

### Pipeline and Fallback
- [ ] Initial translation calls local Sakura API at `http://127.0.0.1:6006/v1` using standard OpenAI client and ChatML formatting.
- [ ] Proofreading and polishing run via DeepSeek APIs.
- [ ] Dual-track safety fallback successfully redirects blocked explicit scenes to Gemini 3.1 Flash Lite with no block.
- [ ] Paragraph line counts and quote marks match the raw input 1:1.
