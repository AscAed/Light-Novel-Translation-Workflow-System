import re
from typing import Optional

def extract_chapter_num(filename: str, default: Optional[float] = None) -> Optional[float]:
    """
    Extract chapter number from file name.
    First tries to match standard format (第...話/话), then falls back to any number.
    Returns the default value if no number is found.
    """
    match = re.search(r"第\s*(\d+(?:\.\d+)?)\s*[話话]", filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = re.search(r"(\d+(?:\.\d+)?)", filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default
