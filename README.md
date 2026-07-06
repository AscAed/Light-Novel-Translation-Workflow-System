# Light Novel Translation Workflow System

This system handles Japanese-to-Chinese translation for light novels, using a RAG (Retrieval-Augmented Generation) pipeline, translation memory, glossary hybrid retrieval, guideline partitioning, and multi-agent polishing with safety fallbacks.

## Architecture

The system coordinates several decoupled components:
1. **Translation Memory (TM)**: Paragraph-level translation database. Cosine similarity matches raw paragraphs to inject matching translated pairs as few-shot context examples.
2. **Glossary Hybrid Retrieval**: Extracts term mappings (`src`, `dst`, `info`) from the project glossary, cleaning out explanation comments.
3. **Partitioned Guidelines**: Splits guideline rules into global and chapter-specific rules, falling back semantically if a chapter-specific rule is missing.
4. **Agent Pipeline**:
   * **Initial Translation**: Invokes the Sakura LLM API.
   * **Proofreading**: Invokes the DeepSeek API (`deepseek-v4-flash`) for logical checks.
   * **Polishing**: Invokes the DeepSeek API (`deepseek-v4-pro`) for tone adjustment.
5. **Safety Fallback**: Redirects blocked explicit content or API failures from DeepSeek to `gemini-3.1-flash-lite` with safety settings disabled (`BLOCK_NONE`).
6. **Formatting Verification**: Enforces paragraph count and quote mark matching 1:1, retrying locally up to three times on mismatch.

## Setup

### Prerequisites
* Python 3.10+
* Dependencies:
  ```bash
  pip install openai google-genai aiohttp numpy
  ```

### Environment Variables
Create a `.env` file in the root directory using the [.env.example](file:///D:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的寝取系女主/.env.example) template:
```env
SAKURA_API_KEY="your-sakura-key"
DEEPSEEK_API_KEY="your-deepseek-key"
GEMINI_API_KEY="your-gemini-key"

SAKURA_BASE_URL="http://127.0.0.1:6006/v1"
DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
```

### Project Layout
Individual novel translation tasks are managed as standalone projects inside the `projects/` directory (which is gitignored). Each project folder follows this convention:
```
projects/[ProjectName]/
├── 生肉/                       # Input raw chapter markdown files
├── 熟肉/                       # Output translated markdown files
└── Knowledge/
    ├── 作品基本信息.json       # Novel title, author, and character metadata
    ├── Glossary.json          # Terminology glossary mappings
    ├── guidelines.txt         # Global and chapter-specific style rules
    ├── STORY_SUMMARY.md       # Sliced chapter synopsis
    └── translation_memory.json # Compiled vector database (generated)
```

Refer to [projects/example/](file:///D:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的寝取系女主/projects/example/) for a template structure.

## Usage

The scripts support running via project name or using a custom config file path.

### 1. Compile Translation Memory
To align existing raw and translated chapters and compile the translation memory database:
```bash
# Project mode (convention-based layout)
python scripts/align_chapters.py --project [ProjectName]

# Explicit configuration path mode
python scripts/align_chapters.py --config /path/to/config.json
```
This reads raw and translated chapters, generates embeddings via Gemini, and writes to `projects/[ProjectName]/Knowledge/translation_memory.json`.

### 2. Run Translation Pipeline
To run the translation workflow for remaining chapters:
```bash
# Project mode (convention-based layout)
python pipeline.py --project [ProjectName]

# Explicit configuration path mode
python pipeline.py --config /path/to/config.json
```

### 3. Prompt Customisation
Default system prompts for the agents are stored in the global `prompts/` directory:
- [translator_skill.md](file:///D:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的寝取系女主/prompts/translator_skill.md)
- [proofreader_skill.md](file:///D:/OWN/Programming/AI/TranslatorAI/祝福のネトラレ原_祝福的寝取系女主/prompts/proofreader_skill.md)
- [polisher_skill.md](file:///D:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的寝取系女主/prompts/polisher_skill.md)

To customise behaviour or style guidelines for a specific novel (e.g. character voices, explicit descriptions), place customized prompt files inside the project prompts directory:
`projects/[ProjectName]/prompts/custom_polisher_skill.md`

## Tests

Execute the full mock-server E2E integration test suite to verify changes:
```bash
python tests/run_tests.py
```
This allocates a free port, runs a background mock server simulating Sakura, DeepSeek, and Gemini API endpoints, and completes the assertions defined in `tests/test_e2e.py`.
