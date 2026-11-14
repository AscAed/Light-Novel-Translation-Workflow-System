import re
import os
import math
import json
import tempfile
from pathlib import Path, PureWindowsPath
from typing import List, Optional


PROVIDER_DATA_CATEGORIES = frozenset(
    {"source_text", "translation_text", "book_knowledge", "evaluation_samples"}
)


def parse_api_timeout(value) -> float:
    """Parse an API timeout expressed in finite, positive seconds."""
    if isinstance(value, bool):
        raise ValueError("API_TIMEOUT must be a finite number greater than zero.")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "API_TIMEOUT must be a finite number greater than zero."
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("API_TIMEOUT must be a finite number greater than zero.")
    return timeout


def parse_provider_data_policy(value) -> dict[str, frozenset[str]]:
    """Parse explicit per-provider grants for book-data categories."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("PROVIDER_DATA_POLICY must be a JSON object.") from exc
    if not isinstance(value, dict):
        raise ValueError("PROVIDER_DATA_POLICY must be a JSON object.")

    policy = {}
    for provider, categories in value.items():
        if not isinstance(provider, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", provider
        ):
            raise ValueError("PROVIDER_DATA_POLICY contains an invalid provider ID.")
        provider_id = provider.lower()
        if provider_id in policy:
            raise ValueError("PROVIDER_DATA_POLICY contains duplicate provider IDs.")
        if not isinstance(categories, (list, tuple, set, frozenset)):
            raise ValueError(
                f"PROVIDER_DATA_POLICY entry for '{provider_id}' must be an array."
            )
        category_values = list(categories)
        if any(not isinstance(category, str) for category in category_values):
            raise ValueError(
                f"PROVIDER_DATA_POLICY entry for '{provider_id}' has a non-text category."
            )
        category_set = set(category_values)
        unknown_categories = category_set - PROVIDER_DATA_CATEGORIES
        if unknown_categories:
            raise ValueError(
                f"PROVIDER_DATA_POLICY entry for '{provider_id}' has unknown categories: "
                f"{', '.join(sorted(unknown_categories))}."
            )
        policy[provider_id] = frozenset(category_set)
    return policy


def require_provider_data_authorized(
    provider_id: Optional[str],
    data_categories,
    policy: dict[str, frozenset[str]],
    *,
    endpoint_is_local: bool = False,
) -> None:
    """Block external provider calls unless every data category is authorized."""
    if endpoint_is_local:
        return
    if not provider_id:
        raise PermissionError(
            "External provider calls require a provider ID and explicit data categories."
        )
    if isinstance(data_categories, str):
        requested_categories = {data_categories}
    elif data_categories is None:
        requested_categories = set()
    else:
        category_values = list(data_categories)
        if any(not isinstance(category, str) for category in category_values):
            raise ValueError("Provider data categories must be text values.")
        requested_categories = set(category_values)
    if not requested_categories:
        raise PermissionError(
            f"External provider '{provider_id}' requires declared data categories."
        )
    unknown_categories = requested_categories - PROVIDER_DATA_CATEGORIES
    if unknown_categories:
        raise ValueError(
            "Unknown provider data categories: "
            + ", ".join(sorted(unknown_categories))
            + "."
        )

    granted_categories = policy.get(provider_id.lower(), frozenset())
    missing_categories = requested_categories - granted_categories
    if missing_categories:
        raise PermissionError(
            f"Provider '{provider_id}' is not authorized to receive: "
            f"{', '.join(sorted(missing_categories))}. "
            "Grant only approved categories in PROVIDER_DATA_POLICY."
        )


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


def resolve_relative_path(
    root: str, relative_path: str, *, allow_missing: bool = False
) -> Path:
    """Resolve a slash-separated path beneath root without following links."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Expected a non-empty relative path.")
    if "\\" in relative_path or Path(relative_path).is_absolute():
        raise ValueError("Expected a relative path using forward slashes.")
    if PureWindowsPath(relative_path).drive:
        raise ValueError("Absolute paths and drive prefixes are not allowed.")

    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Relative paths cannot contain empty or traversal components.")
    if any(":" in part for part in parts):
        raise ValueError("Relative path components cannot contain a colon.")

    root_path = Path(root).resolve(strict=True)
    candidate = root_path
    for index, part in enumerate(parts):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symbolic links are not allowed in mapped paths.")
        if index < len(parts) - 1 and not candidate.is_dir():
            raise ValueError("Mapped path parent directories must already exist.")

    resolved = candidate.resolve(strict=not allow_missing)
    try:
        common = os.path.commonpath(
            (os.path.normcase(str(root_path)), os.path.normcase(str(resolved)))
        )
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


def read_relative_text(root: str, relative_path: str) -> str:
    """Read a mapped file under root after checking each path component."""
    path = resolve_relative_path(root, relative_path)
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


def write_new_relative_text(root: str, relative_path: str, content: str) -> None:
    """Create a mapped file under root without replacing an existing file."""
    path = resolve_relative_path(root, relative_path, allow_missing=True)
    if not path.parent.is_dir():
        raise ValueError("Mapped output parent directory does not exist.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o666)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def write_text_atomically(path: str, content: str) -> None:
    """Replace a file atomically, leaving its previous contents intact on failure."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Symbolic links are not allowed for persisted data.")

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def split_paragraphs(text: str) -> List[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def validate_tm_source_provenance(provenance: dict, pair_count: int) -> None:
    """Validate optional file and paragraph references stored beside TM entries."""
    if (
        not isinstance(provenance, dict)
        or isinstance(provenance.get("schema_version"), bool)
        or provenance.get("schema_version") != 1
    ):
        raise ValueError("TM source provenance must use schema_version 1.")

    for field in ("producer", "raw_file", "translation_file"):
        if not isinstance(provenance.get(field), str) or not provenance[field].strip():
            raise ValueError(f"TM source provenance requires {field}.")

    for field in ("raw_sha256", "translation_sha256"):
        digest = provenance.get(field)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"TM source provenance requires a valid {field}.")

    mappings = provenance.get("pair_mappings")
    if not isinstance(mappings, list) or len(mappings) != pair_count:
        raise ValueError("TM source provenance pair mapping count is invalid.")

    previous_paragraph_index = {"raw": 0, "translation": 0}
    for index, mapping in enumerate(mappings, start=1):
        pair_index = mapping.get("pair_index") if isinstance(mapping, dict) else None
        if (
            not isinstance(pair_index, int)
            or isinstance(pair_index, bool)
            or pair_index != index
        ):
            raise ValueError(f"TM source provenance pair {index} has an invalid index.")
        raw_indices = mapping.get("raw_paragraph_indices")
        translation_indices = mapping.get("translation_paragraph_indices")
        if not isinstance(raw_indices, list) or not isinstance(translation_indices, list):
            raise ValueError(f"TM source provenance pair {index} requires paragraph arrays.")
        for side, paragraph_indices in (
            ("raw", raw_indices),
            ("translation", translation_indices),
        ):
            if (
                any(
                    not isinstance(paragraph_index, int)
                    or isinstance(paragraph_index, bool)
                    or paragraph_index < 1
                    for paragraph_index in paragraph_indices
                )
                or paragraph_indices != sorted(set(paragraph_indices))
            ):
                raise ValueError(
                    f"TM source provenance pair {index} has invalid paragraph indices."
                )
            if paragraph_indices:
                if paragraph_indices[0] <= previous_paragraph_index[side]:
                    raise ValueError(
                        f"TM source provenance pair {index} reuses or reorders "
                        f"{side} paragraph indices."
                    )
                previous_paragraph_index[side] = paragraph_indices[-1]

        expected_status = (
            "matched"
            if raw_indices and translation_indices
            else "partial"
            if raw_indices or translation_indices
            else "unmatched"
        )
        if mapping.get("trace_status") != expected_status:
            raise ValueError(f"TM source provenance pair {index} has invalid trace status.")


def _require_aligned_count(source: List, target: List, stage: str) -> None:
    if not isinstance(source, list) or not isinstance(target, list):
        raise ValueError(f"{stage} must use paragraph arrays.")
    if len(source) != len(target):
        raise ValueError(
            f"{stage} returned {len(target)} paragraphs for {len(source)} source paragraphs."
        )


def require_aligned_paragraphs(source: List, target: List, stage: str) -> None:
    _require_aligned_count(source, target, stage)
    for index, paragraph in enumerate(target, start=1):
        if not isinstance(paragraph, str) or not paragraph.strip():
            raise ValueError(
                f"{stage} returned an empty or non-text paragraph at index {index}."
            )


def require_aligned_annotations(source: List[str], target: List, stage: str) -> None:
    _require_aligned_count(source, target, stage)
    for index, (source_paragraph, annotation) in enumerate(
        zip(source, target), start=1
    ):
        if not isinstance(annotation, dict):
            raise ValueError(f"{stage} returned a non-object annotation at index {index}.")
        paragraph = annotation.get("paragraph")
        speaker = annotation.get("speaker")
        context_hint = annotation.get("context_hint")
        if not isinstance(paragraph, str) or not paragraph.strip():
            raise ValueError(f"{stage} returned an empty or non-text paragraph at index {index}.")
        if paragraph != source_paragraph:
            raise ValueError(f"{stage} changed source paragraph text at index {index}.")
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"{stage} returned an empty or non-text speaker at index {index}.")
        if not isinstance(context_hint, str):
            raise ValueError(f"{stage} returned a non-text context hint at index {index}.")


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
