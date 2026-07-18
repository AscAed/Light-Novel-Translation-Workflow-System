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
