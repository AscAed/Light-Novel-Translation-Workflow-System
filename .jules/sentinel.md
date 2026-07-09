## 2025-07-09 - Path Traversal Vulnerability Mitigation
**Vulnerability:** A path traversal vulnerability was present in the handling of chapter filenames. The use of `os.path.normpath('/' + chapter_filename).lstrip('/')` was insufficient to prevent directory escape, especially on Windows or complex edge cases, allowing potential read/write operations outside intended directories.
**Learning:** `os.path.normpath` followed by `.lstrip('/')` is not a secure way to sanitize filenames.
**Prevention:** Use `os.path.basename()` to strictly isolate the filename component from any provided user input when reading or writing files within controlled directories.
