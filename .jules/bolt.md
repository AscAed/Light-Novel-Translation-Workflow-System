
## 2024-07-12 - Vectorized TM similarity search
**Learning:** Python `for` loops computing cosine similarity sequentially scale very poorly as translation memory grows. Vectorizing with numpy dot products and pre-calculating L2 norms dramatically reduces retrieval latency for RAG operations.
**Action:** Always extract embedding datasets into numpy matrices and use vectorized math operations (like `np.dot` and `np.argpartition`) for large-scale similarity searches instead of standard Python loops.

## 2026-07-14 - json.JSONDecoder().raw_decode string slicing performance
**Learning:** Slicing large strings inside loops (e.g., `clean_content[start:]` for JSON parsing) allocates a new copy of the sliced string every iteration, leading to O(N^2) memory usage and execution time.
**Action:** Use the `idx` parameter built into `json.JSONDecoder().raw_decode(s, idx)` to pass the original string and start index directly, avoiding accidental O(N^2) bottlenecks when parsing malformed or large JSON documents.

## 2026-07-25 - Regex precompilation performance
**Learning:** Repetitive compilation and cache-lookup overhead of `re.search`, `re.sub`, and `re.split` inside loops and frequently called functions scales poorly.
**Action:** Always precompile regular expressions at the module or class level using `re.compile()` when they are used inside loops or frequently called functions, rather than calling `re.search`, `re.sub`, or `re.split` directly with string literals.
