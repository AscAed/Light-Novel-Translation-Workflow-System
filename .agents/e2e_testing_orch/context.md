# E2E Testing Context

## Project Context
- **Workspace root**: `d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人`
- **Code under test**: `pipeline.py`, `scripts/align_chapters.py` (to be developed)
- **External modules/libs**: standard python libraries, `openai`, `google-genai` (implied by client initialization in pipeline.py)
- **Constraints**: E2E tests must verify CLI / entry-point behaviour without reading internal states of `pipeline.py` or `rag_engine.py` (opaque-box).
- **Execution context**: Windows, PowerShell shell, python runner.

## Discoveries & Findings
- `pipeline.py` currently uses `UnifiedAgent` (OpenAI format, default execution mode is `CODING_PLAN`) and `GeminiAgent` (supports `CLI` or `API` modes).
- `pipeline.py` defines a default `Config` class at the top of the file, with paths like `Config.RAW_DIR`, `Config.OUTPUT_DIR`, `Config.GLOSSARY_PATH`, `Config.GUIDELINES_PATH`.
- To test `pipeline.py` without modifying the user's files and config, the testing system must run it in a way that respects custom input and output paths (e.g. by overriding environment variables, or creating a temporary CLI workspace and copying modified configurations, or passing flags if the pipeline supports it, or rewriting config dynamically for the test run). We will investigate the CLI parameter support or config override strategy.
