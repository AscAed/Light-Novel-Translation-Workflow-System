## 2026-06-08T14:07:47Z
Act as the E2E Doc Publisher.
Your working directory is: d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/.agents/e2e_testing_worker_4
Your parent conversation ID is: e21a89da-33e6-421f-922c-5461f03aa379

Your task:
1. Create and write the file `TEST_INFRA.md` at the project root `d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/TEST_INFRA.md` with the following content:

```markdown
# E2E Test Infra: RAG Translation Pipeline

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on implementation design.
- Methodology: Category-Partition + BVA + Pairwise + Workload Testing.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | F1: Translation Memory & Alignment | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | F2: Glossary Parser & Retrieval | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 3 | F3: Partitioned Guidelines Retrieval | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 4 | F4: Sakura/DeepSeek API Migration | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 5 | F5: Dual-Track Safety Fallback | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 6 | F6: Formatting Integrity & Assertions | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |

## Test Architecture
- **Test runner**: `tests/run_tests.py` - Allocates a free TCP port, launches the local mock server, runs E2E tests using standard `unittest`, and terminates the mock server.
- **Test mock server**: `tests/mock_server.py` - Intercepts HTTP calls to Sakura API, DeepSeek API, Gemini API, and Gemini Embedding API, returning mock responses and allowing test-driven state overrides.
- **Directory layout**:
  - `tests/mock_server.py` - Built-in http.server mock API handler.
  - `tests/test_e2e.py` - The main test case suite comprising 71 tests.
  - `tests/run_pipeline.py` - Pipeline execution wrapper with fallback RAG simulation.
  - `tests/run_align_chapters.py` - Chapter alignment execution wrapper.
  - `tests/bin/` - CLI executable paths for Gemini.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Normal translation run with TM, Glossary, Guidelines | F1, F2, F3, F4, F6 | Medium |
| 2 | Explicit translation triggering safety fallback | F4, F5, F6 | Medium |
| 3 | Align chapters 1-18, save TM, translate chapter 19 | F1, F4, F6 | High |
| 4 | Glossary metadata term cleaning verify no explanation leaks | F2, F4, F6 | Medium |
| 5 | Batch translation of multiple normal and explicit chapters | F1, F2, F3, F4, F5, F6 | High |

## Coverage Thresholds
- Tier 1: 5 cases per feature (30 total)
- Tier 2: 5 cases per feature (30 total)
- Tier 3: 6 pairwise combinations
- Tier 4: 5 realistic application scenarios
```

2. Create and write the file `TEST_READY.md` at the project root `d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/TEST_READY.md` with the following content:

```markdown
# E2E Test Suite Ready

## Test Runner
- Command: `python tests/run_tests.py`
- Expected: all tests pass with exit code 0

## Coverage Summary
| Tier | Count | Description |
|------|------:|-------------|
| 1. Feature Coverage | 30 | 5 test cases per feature covering happy paths |
| 2. Boundary & Corner | 30 | 5 test cases per feature covering limit/error inputs |
| 3. Cross-Feature | 6 | Pairwise interactions of major RAG/API features |
| 4. Real-World Application | 5 | Multi-chapter runs, safety failover, glossary metadata cleaning |
| **Total** | **71** | |

## Feature Checklist
| Feature | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---------|:------:|:------:|:------:|:------:|
| F1: Translation Memory | 5 | 5 | ✓ | ✓ |
| F2: Glossary Parser | 5 | 5 | ✓ | ✓ |
| F3: Partitioned Guidelines | 5 | 5 | ✓ | ✓ |
| F4: Sakura/DeepSeek API | 5 | 5 | ✓ | ✓ |
| F5: Safety Fallback | 5 | 5 | ✓ | ✓ |
| F6: Formatting Assertions | 5 | 5 | ✓ | ✓ |
```

3. Write your handoff report to `.agents/e2e_testing_worker_4/handoff.md` summarizing the files published.
