import re
from typing import Optional

# Precompile regular expressions for performance
_CHAPTER_NUM_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_FALLBACK_NUM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
# Optimization: Precompile regular expressions at the module level
# This avoids the overhead of recompiling or looking up the regex in Python's internal cache
# during repeated calls to extract_chapter_num.
CHAPTER_FORMAT_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
ANY_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
_RE_CHAP_NUM = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_RE_ANY_NUM = re.compile(r"(\d+(?:\.\d+)?)")
# ⚡ Bolt Optimization: Precompile regex patterns at module level to avoid repeated compilation and cache-lookup overhead in frequently called loops/functions.
_CHAP_NUM_RE = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_FALLBACK_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
# Precompile regex patterns used for chapter extraction
_CHAPTER_STD_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_CHAPTER_FALLBACK_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")

def extract_chapter_num(filename: str, default: Optional[float] = None) -> Optional[float]:
    """
    Extract chapter number from file name.
    First tries to match standard format (第...話/话), then falls back to any number.
    Returns the default value if no number is found.
    """
    match = _CHAPTER_NUM_PATTERN.search(filename)
    match = CHAPTER_FORMAT_PATTERN.search(filename)
    match = _RE_CHAP_NUM.search(filename)
    match = _CHAP_NUM_RE.search(filename)
    match = _CHAPTER_STD_PATTERN.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = _FALLBACK_NUM_PATTERN.search(filename)
    match = ANY_NUMBER_PATTERN.search(filename)
    match = _RE_ANY_NUM.search(filename)
    match = _FALLBACK_NUM_RE.search(filename)
    match = _CHAPTER_FALLBACK_PATTERN.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default
