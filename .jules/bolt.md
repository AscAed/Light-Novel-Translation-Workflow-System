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
## 2025-02-12 - Vector similarity optimizations
**Learning:** In applications repeatedly computing cosine similarities over large datasets (like translation memory embeddings), division operations (`/`) and memory bandwidth for float64 arrays become a measurable bottleneck on the query hot path.
**Action:** When computing dot products or cosine similarities via NumPy, cast array elements to `np.float32` to halve memory footprint and improve SIMD throughput. Additionally, pre-calculate L2 norms on the cached matrix to make the runtime cosine calculation a simple dot product, bypassing per-query division overhead.

## 2025-01-28 - External API Client Connection Pooling
**Learning:** Re-instantiating external API clients like `AsyncOpenAI` or `genai.Client` for every request incurs significant TCP/TLS handshake overhead (100-200ms per call) and instantiation time (30ms per call).
**Action:** Cache and reuse a single client instance per base URL/API key pair to maximize connection pooling and reduce request latency.
## 2024-05-18 - Optimize Cosine Similarity in RAG Engine
**Learning:** In the RAG Engine's translation memory querying (`rag_engine.py`), the cosine similarity calculation was previously performed by keeping vectors unnormalized and computing `np.dot(matrix, q) / (norms * q_norm)` at query time with `float64` vectors. This was slow for large matrix multiplication. By pre-allocating the numpy matrix as `np.float32` and pre-normalizing the vectors within `_build_cache`, the memory footprint is halved and the cosine similarity calculation at query time is reduced to a pure dot product: `np.dot(matrix, q)`, achieving around a 2x speedup on similarity searches.
**Action:** When implementing semantic search or any distance metric with embeddings over a large pre-computed dataset, always cast vectors to `np.float32` and pre-normalize them if using Cosine Similarity, so that similarity computations become simple dot products without runtime division overhead.
## 2026-08-04 - [Optimize NumPy Array Memory Footprint for Embeddings]
**Learning:** Default NumPy array initializations (`np.array`) use 64-bit float precision (`float64`), which doubles the memory footprint and increases computation overhead compared to 32-bit floats. This is especially relevant when handling dense embedding vectors (like those from Gemini/OpenAI).
**Action:** When caching, computing, or generating embeddings for Vector/Similarity Search workflows, explicitly declare `dtype=np.float32` and use `.astype(np.float32)` for generated metrics (like `.norm()`) to halve memory footprint and speed up SIMD dot products.
