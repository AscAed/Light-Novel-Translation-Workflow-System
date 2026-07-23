## 2024-10-18 - Python re.compile overhead in loops
**Learning:** Python's internal `re` module caches a limited number of recently compiled patterns, but calling `re.search()`, `re.match()`, or `re.sub()` directly inside high-frequency loops or widely-used utility functions (like sorting keys) still incurs non-trivial cache lookup overhead and risks cache eviction thrashing.
**Action:** Always pre-compile regular expressions explicitly using `re.compile()` at the module level or outside of loops, and call the `.match()`, `.search()`, etc. methods directly on the compiled `re.Pattern` object to guarantee O(1) initialization.

## 2026-07-22 - Python re.compile overhead in RAG engine and Pipeline
**Learning:** In `pipeline.py` and `rag_engine.py`, there are still places where `re.search`, `re.sub`, and `re.split` are called directly. These operations are not within massive loops, but for a codebase where precompilation is preferred, they should be precompiled at the module or class level to avoid any cache lookup overhead, as RAG engines are highly sensitive to latency.
**Action:** Always pre-compile regular expressions explicitly using `re.compile()` at the module level or outside of loops, and call the `.match()`, `.search()`, etc. methods directly on the compiled `re.Pattern` object to guarantee O(1) initialization.
