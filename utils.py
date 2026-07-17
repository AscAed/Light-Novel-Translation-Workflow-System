import re
from typing import Optional

# Optimization: Precompile regular expressions at the module level
# This avoids the overhead of recompiling or looking up the regex in Python's internal cache
# during repeated calls to extract_chapter_num.
CHAPTER_FORMAT_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
ANY_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")

def extract_chapter_num(filename: str, default: Optional[float] = None) -> Optional[float]:
    """
    Extract chapter number from file name.
    First tries to match standard format (第...話/话), then falls back to any number.
    Returns the default value if no number is found.
    """
    match = CHAPTER_FORMAT_PATTERN.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = ANY_NUMBER_PATTERN.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default
