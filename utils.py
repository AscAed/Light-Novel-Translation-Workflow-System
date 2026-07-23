import re
from typing import Optional

# Precompile regex patterns used for chapter extraction
_CHAPTER_STD_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_CHAPTER_FALLBACK_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
_CHAP_NUM_RE_1 = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_CHAP_NUM_RE_2 = re.compile(r"(\d+(?:\.\d+)?)")

def extract_chapter_num(filename: str, default: Optional[float] = None) -> Optional[float]:
    """
    Extract chapter number from file name.
    First tries to match standard format (第...話/话), then falls back to any number.
    Returns the default value if no number is found.
    """
    match = _CHAPTER_STD_PATTERN.search(filename)
    match = _CHAP_NUM_RE_1.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = _CHAPTER_FALLBACK_PATTERN.search(filename)
    match = _CHAP_NUM_RE_2.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default
