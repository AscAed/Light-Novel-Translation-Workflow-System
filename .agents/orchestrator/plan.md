# Orchestrator Plan: RAG Translation Pipeline Upgrade

This plan coordinates the migration of the translation pipeline to a RAG-enabled translation workflow system.

## Milestones

### Milestone 1: Translation Memory Alignment & Indexing (Scripts Setup)
- **Goal**: Develop `scripts/align_chapters.py` to parse paragraphs of chapters 1-18 from `生肉` and `熟肉`.
- **Requirements**:
  - Handle paragraph splitting by double-newline.
  - Match paragraph counts: 1:1 if matching, fallback to heuristic or semantic alignment if not matching, logging warnings.
  - Call Gemini Embedding 2 (`text-embedding-004`) to generate paragraph vectors.
  - Cache results in `Knowledge/translation_memory.json`.
- **Status**: PLANNED

### Milestone 2: RAG Retrieval Module & Glossary Parser
- **Goal**: Implement `rag_engine.py` to provide vector search and metadata-cleaning utilities.
- **Requirements**:
  - Clean Glossary Parser: Extract pure terms (`src`, `dst`) and explanation/comments metadata (`info`) from `Glossary.json`.
  - Partition Guidelines: Separate `Knowledge/guidelines.txt` into global and chapter-specific rules, falling back to adjacent semantic matching if not found.
  - Vector cosine similarity engine using NumPy.
  - Interface to append new translations dynamically.
- **Status**: PLANNED

### Milestone 3: Pipeline Refactoring & API Migration
- **Goal**: Integrate `rag_engine.py` into `pipeline.py` and migrate API calls.
- **Requirements**:
  - Integrate Sakura-14B API at `http://127.0.0.1:6006/v1` via standard OpenAI client wrapper using ChatML templates.
  - Replace DashScope with DeepSeek (`deepseek-v4-flash` / `deepseek-v4-pro` or equivalent OpenAI-compatible) APIs.
  - Auto-fallback to Gemini 3.1 Flash Lite (with `BLOCK_NONE` safety settings) when DeepSeek triggers a safety block on explicit content.
  - Retries, line-count assertions (1:1), and quote mark preservation.
- **Status**: PLANNED

### Milestone 4: Dual Track E2E Test Suite Creation
- **Goal**: Construct an E2E test suite using requirement-driven opaque-box testing.
- **Requirements**:
  - Four tiers of testing: Tier 1 (Feature Coverage), Tier 2 (Boundary & Corner), Tier 3 (Cross-Feature Combinations), Tier 4 (Real-World Application Scenarios).
  - Produce `TEST_INFRA.md` and publish `TEST_READY.md` upon completion.
- **Status**: PLANNED

### Milestone 5: Verification & Integration (Implementation Track Final Milestone)
- **Goal**: Verify the implementation against E2E test cases, and execute Phase 2 adversarial coverage hardening.
- **Status**: PLANNED
