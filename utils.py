import re
from typing import Optional

# ⚡ Bolt Optimization: Precompile regex patterns at module level to avoid repeated compilation and cache-lookup overhead in frequently called loops/functions.
_CHAP_NUM_RE = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[話话]")
_FALLBACK_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

def extract_chapter_num(filename: str, default: Optional[float] = None) -> Optional[float]:
    """
    Extract chapter number from file name.
    First tries to match standard format (第...話/话), then falls back to any number.
    Returns the default value if no number is found.
    """
    match = _CHAP_NUM_RE.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = _FALLBACK_NUM_RE.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default
