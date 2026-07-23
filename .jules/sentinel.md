## 2025-07-09 - Path Traversal Vulnerability Mitigation
**Vulnerability:** A path traversal vulnerability was present in the handling of chapter filenames. The use of `os.path.normpath('/' + chapter_filename).lstrip('/')` was insufficient to prevent directory escape, especially on Windows or complex edge cases, allowing potential read/write operations outside intended directories.
**Learning:** `os.path.normpath` followed by `.lstrip('/')` is not a secure way to sanitize filenames.
**Prevention:** Use `os.path.basename()` to strictly isolate the filename component from any provided user input when reading or writing files within controlled directories.

## 2025-07-09 - Missing API Key Secure Fallback
**Vulnerability:** The application was not failing securely when API keys were missing. Instead, it would use a hardcoded `"mock-key"` dummy value in production, which would be sent over the wire to actual 3rd-party API endpoints, potentially exposing internal testing logic and wasting outbound network requests. It also bypassed null checks such as `if not api_key:`.
**Learning:** Defaulting to dummy secrets to ease testing creates an insecure default for production.
**Prevention:** Only fallback to dummy credentials if a test-specific environment variable (e.g., `MOCK_SERVER_PORT` or `TEST_WORKSPACE_DIR`) is explicitly set. Otherwise, return an empty string/null to fail early and securely.
## 2025-07-09 - Missing HTTP Timeouts on Generative AI Clients
**Vulnerability:** Instances of `AsyncOpenAI` and `google.genai.Client` were being initialized without explicit timeouts. Because standard API clients might wait indefinitely (or fall back to extremely long OS default socket timeouts) for a response, malicious or overloaded upstream endpoints could easily cause connection pooling exhaustion, memory leaks, and Denial of Service (DoS) across the pipeline.
**Learning:** External API dependencies must always enforce explicit bounds on their waiting periods to fail fast.
**Prevention:** Always define `timeout` limits when configuring API wrappers (e.g., `AsyncOpenAI(timeout=...)` and `genai.Client(http_options={'timeout': ...})`).

## 2026-07-20 - Missing API Timeout Configurations
**Vulnerability:** The application instantiated `AsyncOpenAI` and `genai.Client` without explicit timeout configurations or used an inadequately low timeout value (10.0 seconds). This created a risk of thread/resource exhaustion or Application Denial of Service (DoS) if the upstream generative AI service hung indefinitely or responded very slowly.
**Learning:** Default instantiations of API clients often lack safe timeouts, or they may use timeouts too short for long-running AI inferences, leading to unhandled failures or hangs.
**Prevention:** Always set explicit, generous timeout configurations (e.g., 600.0 seconds) for external Generative AI API clients (e.g. via `timeout=` for OpenAI and `http_options={'timeout': ...}` for Gemini).
