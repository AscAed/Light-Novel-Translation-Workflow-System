import re
import os
from pathlib import Path, PureWindowsPath
from typing import List, Optional


def resolve_child_path(root: str, filename: str, *, allow_missing: bool = False) -> Path:
    """Resolve one file directly under root and reject links or path escapes."""
    if not filename or filename in {".", ".."}:
        raise ValueError("Expected a file name.")
    if "/" in filename or "\\" in filename or Path(filename).is_absolute() or PureWindowsPath(filename).drive:
        raise ValueError("Expected a file name without path components.")

    root_path = Path(root).resolve(strict=True)
    candidate = root_path / filename
    if candidate.is_symlink():
        raise ValueError("Symbolic links are not allowed for chapter files.")

    resolved = candidate.resolve(strict=not allow_missing)
    try:
        common = os.path.commonpath((os.path.normcase(str(root_path)), os.path.normcase(str(resolved))))
    except ValueError as exc:
        raise ValueError("Path is outside the configured directory.") from exc
    if common != os.path.normcase(str(root_path)):
        raise ValueError("Path is outside the configured directory.")
    return resolved


def read_child_text(root: str, filename: str) -> str:
    """Read a regular file after checking that it stays directly under root."""
    path = resolve_child_path(root, filename)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        return stream.read()


def write_new_child_text(root: str, filename: str, content: str) -> None:
    """Create a new file directly under root without following an existing link."""
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    path = resolve_child_path(str(root_path), filename, allow_missing=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o666)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def split_paragraphs(text: str) -> List[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def require_aligned_paragraphs(source: List, target: List, stage: str) -> None:
    if not isinstance(source, list) or not isinstance(target, list):
        raise ValueError(f"{stage} must use paragraph arrays.")
    if len(source) != len(target):
        raise ValueError(
            f"{stage} returned {len(target)} paragraphs for {len(source)} source paragraphs."
        )


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
