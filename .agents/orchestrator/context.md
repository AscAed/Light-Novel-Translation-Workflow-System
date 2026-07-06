# Project Context & References

## Project Description
RAG-based upgrade to a light novel translation workflow pipeline. Replaces a static large-context prompt stuffing system with dynamic retrieval.

## System Components
1. **SakuraLLM (Sakura-14B-Qwen2.5-v1.0-GGUF)**: Local translation model running at `127.0.0.1:6006`.
2. **DeepSeek (deepseek-v4-flash / deepseek-v4-pro)**: Proofreader and Polisher agents.
3. **Gemini 3.1 Flash Lite**: Safety fallback for proofreader/polisher when DeepSeek censors sensitive content.
4. **Gemini Embedding 2 (text-embedding-004)**: For semantic vector calculation.
5. **Translation Memory**: `Knowledge/translation_memory.json`.
6. **Glossary**: `Glossary.json` (cleaned dynamically to avoid explanatory contamination).
7. **Guidelines**: `Knowledge/guidelines.txt` (partitioned to global and chapter-specific).

## Crucial Paths
- Workspace root: `d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人`
- Raw input directory: `生肉` (e.g. `生肉/1.神んてらの世界`, `生肉/2.小学五年生`)
- Translation output directory: `熟肉` (e.g. `熟肉/Ntera神的世界`)
- Glossary file: `Glossary.json`
- Guidelines file: `Knowledge/guidelines.txt`
