# E2E Testing Plan

## Objective
Design and implement a requirement-driven, opaque-box E2E test suite for the RAG translation pipeline upgrade without depending on implementation details of `pipeline.py` or `rag_engine.py`. Test the pipeline as a CLI/binary or black-box module.

## Verification Scope (Features)
1. **F1: Translation Memory & Alignment** (alignment of chapters, cosine similarity matching, caching, updating)
2. **F2: Glossary Parser & Retrieval** (cleaning heuristics, target/metadata splitting, GPT dictionary format)
3. **F3: Partitioned Guidelines** (global vs chapter rules, semantic similarity fallback)
4. **F4: Sakura/DeepSeek API Integration** (Sakura ChatML template, local endpoints, DeepSeek pro/flash)
5. **F5: Dual-Track Safety Fallback** (Gemini 3.1 Flash Lite fallback with BLOCK_NONE when DeepSeek is blocked)
6. **F6: Formatting Integrity Assertions** (line-count match, quote preservation, retry logic)

## Test Architecture
To test `pipeline.py` as a black box without internet access:
- **Mock Server**: A lightweight local HTTP mock server that simulates:
  - Sakura API (`http://127.0.0.1:6006`)
  - DeepSeek API (OpenAI-compatible chat completions)
  - Gemini API (Google GenAI chat completions / safety block simulation)
  - Gemini Embedding API (for TM vector calculation)
- **Environment Control**: Test cases configure environment variables (e.g. mock server URL, ports, API keys, test folders) to feed custom raw chapters, glossaries, and guidelines to the pipeline, then run the pipeline and assert output file contents.

## Test Tiers

### Tier 1: Feature Coverage (30 cases)
- **F1 (TM)**:
  1. TM retrieval injects matched pairs as few-shots.
  2. Aligned chapter vector calculation runs via mock embedding API.
  3. Incremental updates append new paragraph pairs to TM JSON database.
  4. Empty translation memory returns gracefully without errors.
  5. Cosine similarity correctly prioritises higher similarity matches.
- **F2 (Glossary)**:
  6. Clean glossary parsing extracts terms and metadata from `Glossary.json`.
  7. Empty glossary builds prompt without glossary section.
  8. Glossary terms with explanations split into `dst` and `info`.
  9. Glossary terms with parentheses filter out explanation contamination.
  10. Glossary matches term names correctly against input text.
- **F3 (Guidelines)**:
  11. Guidelines partition global and chapter-specific segments correctly.
  12. Chapter guidelines fallback semantically to adjacent chapter rules if missing.
  13. Guidelines context window is under 10KB.
  14. Global rules are always included in the prompt.
  15. Missing global guidelines handled gracefully.
- **F4 (Sakura/DeepSeek API)**:
  16. Sakura initial translator called via ChatML format at correct URL.
  17. DeepSeek-v4-flash used for proofreading.
  18. DeepSeek-v4-pro used for polishing.
  19. OpenAI client wrapper initialises base URL and api key correctly.
  20. Proofreading and polishing steps return expected output.
- **F5 (Safety Fallback)**:
  21. DeepSeek safety block (e.g. status 400/403 or safety response) triggers Gemini fallback.
  22. Gemini Flash Lite fallback called with `BLOCK_NONE`.
  23. Fallback handles API errors (network timeouts/status 500) on DeepSeek by calling Gemini.
  24. Safe translation of explicit content completes without block.
  25. Gemini fallback preserves translation style.
- **F6 (Formatting Assertions)**:
  26. Line count matches 1:1 between raw and translated output.
  27. Quote marks (`『』`, `「」`) are preserved 1:1.
  28. Line count mismatch triggers warning and local retry.
  29. Quote mismatch triggers warning and local retry.
  30. Persistent mismatch fails chapter gracefully.

### Tier 2: Boundary & Corner Cases (30 cases)
- **F1 (TM)**: empty raw file, huge paragraph size, zero matches, mismatched paragraph counts in alignment tool, invalid JSON TM.
- **F2 (Glossary)**: duplicate glossary keys, glossary key with special regex chars, empty glossary file, extremely long terms, glossary without translation targets.
- **F3 (Guidelines)**: empty guideline file, huge guideline file, no matching chapter or adjacent chapter guidelines, guideline lines without chapter header format.
- **F4 (API)**: Sakura endpoint offline (connection refused), partial response from Sakura, DeepSeek rate-limit (429) retry logic, empty API key, Sakura timeout.
- **F5 (Safety)**: both DeepSeek and Gemini block, Gemini rate limit during fallback, empty response from Gemini, Gemini fallback triggers on multiple consecutive chapters.
- **F6 (Formatting)**: paragraph with multiple nested quotes, blank lines in raw input, whitespace-only paragraphs, paragraph with only emojis, paragraph with mixed Japanese/Chinese quotes.

### Tier 3: Cross-Feature Combinations (6 cases)
1. Glossary matches & TM match combined in prompt.
2. Guideline fallback & TM matches combined in prompt.
3. Safety block triggers on a chapter containing glossary matches.
4. Line count mismatch triggers retry, and during retry DeepSeek safety block triggers fallback to Gemini.
5. Missing chapter guidelines uses semantic similarity, which maps to a chapter that has a TM match.
6. Local retry fails 3 times on line count mismatch, triggers warning, and outputs partial result.

### Tier 4: Real-World Application Scenarios (5 cases)
1. E2E translation of a normal chapter with glossary, guidelines, and TM matches.
2. E2E translation of an explicit chapter with heavy sexual/violent content, triggering DeepSeek safety block and falling back to Gemini.
3. Aligning chapters 1-18 using `align_chapters.py`, saving TM, then running pipeline for chapter 19.
4. Translating a chapter with glossary terms that have metadata, verifying no explanatory text enters the translated text.
5. Large batch translation run (5 chapters) with mixed normal/explicit chapters, verify context window size remains low (<10KB) and formatting matches 1:1.

## Milestones and Status
1. **Define Test Infra & Mock Server**: PLANNED (conv ID: TBD)
2. **Implement Tier 1 & 2 Test Suite**: PLANNED (conv ID: TBD)
3. **Implement Tier 3 & 4 Test Suite**: PLANNED (conv ID: TBD)
4. **Build Test Runner & Verification**: PLANNED (conv ID: TBD)
5. **Publish TEST_INFRA.md & TEST_READY.md**: PLANNED (conv ID: TBD)
