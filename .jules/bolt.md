## 2024-10-18 - Python re.compile overhead in loops
**Learning:** Python's internal `re` module caches a limited number of recently compiled patterns, but calling `re.search()`, `re.match()`, or `re.sub()` directly inside high-frequency loops or widely-used utility functions (like sorting keys) still incurs non-trivial cache lookup overhead and risks cache eviction thrashing.
**Action:** Always pre-compile regular expressions explicitly using `re.compile()` at the module level or outside of loops, and call the `.match()`, `.search()`, etc. methods directly on the compiled `re.Pattern` object to guarantee O(1) initialization.

## 2024-07-12 - Vectorized TM similarity search
**Learning:** Python `for` loops computing cosine similarity sequentially scale very poorly as translation memory grows. Vectorizing with numpy dot products and pre-calculating L2 norms dramatically reduces retrieval latency for RAG operations.
**Action:** Always extract embedding datasets into numpy matrices and use vectorized math operations (like `np.dot` and `np.argpartition`) for large-scale similarity searches instead of standard Python loops.

## 2026-07-14 - json.JSONDecoder().raw_decode string slicing performance
**Learning:** Slicing large strings inside loops (e.g., `clean_content[start:]` for JSON parsing) allocates a new copy of the sliced string every iteration, leading to O(N^2) memory usage and execution time.
**Action:** Use the `idx` parameter built into `json.JSONDecoder().raw_decode(s, idx)` to pass the original string and start index directly, avoiding accidental O(N^2) bottlenecks when parsing malformed or large JSON documents.

## 2026-11-20 - Regex Precompilation in tight loops
**Learning:** Calling module-level regex functions like `re.sub(pattern, ...)` or `re.split(pattern, ...)` inside a loop iterating over thousands of items still incurs a small lookup and parsing overhead, despite Python's internal cache. This overhead becomes measurable in tight loops over large datasets.
**Action:** When performing regex operations on large data structures (like glossary merging or document parsing), explicitly precompile the regexes via `re.compile()` into module-level constants and call the pattern's methods (e.g., `pattern.sub()`) to bypass cache lookups.
## 2026-07-22 - Python re.compile overhead in RAG engine and Pipeline
**Learning:** In `pipeline.py` and `rag_engine.py`, there are still places where `re.search`, `re.sub`, and `re.split` are called directly. These operations are not within massive loops, but for a codebase where precompilation is preferred, they should be precompiled at the module or class level to avoid any cache lookup overhead, as RAG engines are highly sensitive to latency.
**Action:** Always pre-compile regular expressions explicitly using `re.compile()` at the module level or outside of loops, and call the `.match()`, `.search()`, etc. methods directly on the compiled `re.Pattern` object to guarantee O(1) initialization.
