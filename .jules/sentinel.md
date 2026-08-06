## 2025-07-09 - Path Traversal Vulnerability Mitigation
**Vulnerability:** A path traversal vulnerability was present in the handling of chapter filenames. The use of `os.path.normpath('/' + chapter_filename).lstrip('/')` was insufficient to prevent directory escape, especially on Windows or complex edge cases, allowing potential read/write operations outside intended directories.
**Learning:** `os.path.normpath` followed by `.lstrip('/')` is not a secure way to sanitize filenames.
**Prevention:** Use `os.path.basename()` to strictly isolate the filename component from any provided user input when reading or writing files within controlled directories.

## 2025-07-09 - Missing API Key Secure Fallback
**Vulnerability:** The application was not failing securely when API keys were missing. Instead, it would use a hardcoded `"mock-key"` dummy value in production, which would be sent over the wire to actual 3rd-party API endpoints, potentially exposing internal testing logic and wasting outbound network requests. It also bypassed null checks such as `if not api_key:`.
**Learning:** Defaulting to dummy secrets to ease testing creates an insecure default for production.
**Prevention:** Only fallback to dummy credentials if a test-specific environment variable (e.g., `MOCK_SERVER_PORT` or `TEST_WORKSPACE_DIR`) is explicitly set. Otherwise, return an empty string/null to fail early and securely.

## 2025-07-18 - Missing Timeout Configuration on External APIs
**Vulnerability:** External API client instantiations (`AsyncOpenAI` and `genai.Client`) were lacking explicit timeout configurations. This could allow unbounded connections leading to resource exhaustion (DoS).
**Learning:** Default client configurations for external APIs do not always enforce timeouts on their own, allowing hanging network requests.
**Prevention:** Always explicitly define timeout policies (`timeout` for OpenAI, `http_options={'timeout': ...}` for Gemini) when initiating external API connections.
## 2025-07-09 - Missing HTTP Timeouts on Generative AI Clients
**Vulnerability:** Instances of `AsyncOpenAI` and `google.genai.Client` were being initialized without explicit timeouts. Because standard API clients might wait indefinitely (or fall back to extremely long OS default socket timeouts) for a response, malicious or overloaded upstream endpoints could easily cause connection pooling exhaustion, memory leaks, and Denial of Service (DoS) across the pipeline.
**Learning:** External API dependencies must always enforce explicit bounds on their waiting periods to fail fast.
**Prevention:** Always define `timeout` limits when configuring API wrappers (e.g., `AsyncOpenAI(timeout=...)` and `genai.Client(http_options={'timeout': ...})`).

## 2026-07-20 - Missing API Timeout Configurations
**Vulnerability:** The application instantiated `AsyncOpenAI` and `genai.Client` without explicit timeout configurations or used an inadequately low timeout value (10.0 seconds). This created a risk of thread/resource exhaustion or Application Denial of Service (DoS) if the upstream generative AI service hung indefinitely or responded very slowly.
**Learning:** Default instantiations of API clients often lack safe timeouts, or they may use timeouts too short for long-running AI inferences, leading to unhandled failures or hangs.
**Prevention:** Always set explicit, generous timeout configurations (e.g., 600.0 seconds) for external Generative AI API clients (e.g. via `timeout=` for OpenAI and `http_options={'timeout': ...}` for Gemini).

## 2026-08-01 - Resource Exhaustion (DoS) and ReDoS Vulnerability Mitigations
**Vulnerability:** The application was vulnerable to Application Denial of Service (DoS) via resource exhaustion when loading excessively large chapter files into memory, and it contained a potential Regular Expression Denial of Service (ReDoS) vulnerability in the JSON extraction regex (`.*` instead of `.*?`).
**Learning:** Operations loading entire files into memory without bounds checking can be exploited to crash the application, and greedy regex operations over large strings can lock the CPU in backtracking.
**Prevention:** Enforce strict file size limits using `os.path.getsize()` before file reading operations, and always prefer non-greedy quantifiers in regular expressions handling dynamic input.
## 2026-08-04 - ReDoS in JSON Extraction Regex
**Vulnerability:** A Regular Expression Denial of Service (ReDoS) vulnerability was present in the `_JSON_BLOCK_RE` regex used for extracting JSON from AI responses. The greedy match `.*` inside the regex could lead to catastrophic backtracking and CPU exhaustion when parsing large or maliciously crafted strings lacking proper JSON block terminations.
**Learning:** Using greedy matching like `.*` for parsing large and arbitrary multiline text blocks can cause catastrophic backtracking if the closing sequence is not found.
**Prevention:** To prevent Regular Expression Denial of Service (ReDoS) vulnerabilities, ensure regex patterns parsing arbitrary text blocks (like JSON extraction) use non-greedy matching (e.g., `.*?` instead of `.*`).
