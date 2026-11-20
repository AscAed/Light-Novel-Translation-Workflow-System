"""Create a source-verified TM candidate with embeddings from the active provider."""

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from embedding_provider import generate_embeddings, is_compatible_embedding
from scripts.validate_tm_provenance import audit_translation_memory
from utils import (
    open_regular_file,
    resolve_relative_path,
    write_new_child_bytes_atomically,
)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Translation memory contains a duplicate JSON field.")
        result[key] = value
    return result


def _read_tm(path: str) -> tuple[bytes, dict]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("Symbolic links are not allowed for translation memory.")
    with open_regular_file(candidate, binary=True) as stream:
        content = stream.read()
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Translation memory must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("chapters"), dict):
        raise ValueError("Translation memory must contain a chapters object.")
    return content, value


def _file_sha256(path: Path) -> str:
    with open_regular_file(path, binary=True) as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def _selected_data(tm: dict, chapter_names: list[str] | None) -> tuple[list[str], dict]:
    chapters = tm["chapters"]
    provenance = tm.get("source_provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("TM source provenance must be an object.")
    selected_names = list(chapters) if chapter_names is None else chapter_names
    if (
        not selected_names
        or any(
            not isinstance(name, str) or not name or name not in chapters
            for name in selected_names
        )
        or len(selected_names) != len(set(selected_names))
    ):
        raise ValueError("TM rebuild selected an invalid or duplicate chapter.")

    selected_chapters = {}
    selected_provenance = {}
    for name in selected_names:
        pairs = chapters[name]
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("Selected TM chapter must contain pairs.")
        for pair in pairs:
            if (
                not isinstance(pair, dict)
                or not isinstance(pair.get("raw"), str)
                or not pair["raw"].strip()
                or not isinstance(pair.get("translated"), str)
                or not pair["translated"].strip()
            ):
                raise ValueError("Selected TM chapter contains an invalid pair.")
        selected_chapters[name] = pairs
        if name in provenance:
            selected_provenance[name] = provenance[name]
    return selected_names, {
        "chapters": selected_chapters,
        "source_provenance": selected_provenance,
    }


def _require_verified_sources(
    selected: dict,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
    *,
    source_input_root: str | None,
    source_input_map: dict[str, dict] | None,
) -> None:
    findings = audit_translation_memory(
        selected,
        source_root,
        translation_root,
        manifest_relative_path,
        source_input_root=source_input_root,
        source_input_map=source_input_map,
    )
    if (
        len(findings) != len(selected["chapters"])
        or any(item["status"] != "verified" for item in findings)
    ):
        raise ValueError("Selected TM source provenance is not fully verified.")


def rebuild_translation_memory_embeddings(
    tm_path: str,
    output_filename: str,
    source_root: str,
    translation_root: str,
    manifest_relative_path: str,
    chapter_names: list[str] | None = None,
    *,
    source_input_root: str | None = None,
    source_input_map: dict[str, dict] | None = None,
    batch_size: int = 50,
    api_timeout: float = 10.0,
    provider_data_policy=None,
) -> dict:
    """Write an immutable candidate without changing the source TM."""
    tm_bytes, tm = _read_tm(tm_path)
    selected_names, selected = _selected_data(tm, chapter_names)
    output_root = str(Path(tm_path).parent)
    output_path = resolve_relative_path(
        output_root, output_filename, allow_missing=True
    )
    if output_path.exists():
        raise FileExistsError("TM rebuild output already exists.")

    manifest_path = resolve_relative_path(source_root, manifest_relative_path)
    manifest_digest = _file_sha256(manifest_path)
    _require_verified_sources(
        selected,
        source_root,
        translation_root,
        manifest_relative_path,
        source_input_root=source_input_root,
        source_input_map=source_input_map,
    )

    ordered_pairs = [
        pair
        for name in selected_names
        for pair in selected["chapters"][name]
    ]
    vectors, identity = generate_embeddings(
        [pair["raw"] for pair in ordered_pairs],
        batch_size=batch_size,
        api_timeout=api_timeout,
        provider_data_policy=provider_data_policy,
    )
    if len(vectors) != len(ordered_pairs) or any(
        not is_compatible_embedding(vector, identity) for vector in vectors
    ):
        raise ValueError("Embedding response did not match the selected TM pairs.")

    if hashlib.sha256(_read_tm(tm_path)[0]).hexdigest() != hashlib.sha256(
        tm_bytes
    ).hexdigest():
        raise ValueError("Translation memory changed during embedding rebuild.")
    if _file_sha256(manifest_path) != manifest_digest:
        raise ValueError("Source manifest changed during embedding rebuild.")
    _require_verified_sources(
        selected,
        source_root,
        translation_root,
        manifest_relative_path,
        source_input_root=source_input_root,
        source_input_map=source_input_map,
    )

    candidate = copy.deepcopy(tm)
    vector_index = 0
    for name in selected_names:
        for pair in candidate["chapters"][name]:
            pair["embedding"] = vectors[vector_index]
            pair["embedding_identity"] = identity
            vector_index += 1
    candidate_bytes = json.dumps(
        candidate,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    write_new_child_bytes_atomically(output_root, output_filename, candidate_bytes)
    return {
        "output": output_filename,
        "chapter_count": len(selected_names),
        "pair_count": len(ordered_pairs),
        "output_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a source-verified TM embedding candidate; never modify the "
            "configured TM or reviewed snapshot."
        )
    )
    parser.add_argument("--project")
    parser.add_argument("--config")
    parser.add_argument(
        "--output",
        default="translation_memory.reembedded.json",
        help="New filename in the configured TM directory.",
    )
    parser.add_argument(
        "--chapter",
        action="append",
        dest="chapters",
        help="TM chapter key to rebuild; repeat to select more than one.",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args(argv)

    try:
        from pipeline import Config

        Config.load_config(project=args.project, config_file=args.config)
        source_input_map = {
            item["raw_file"]: {
                "source_version_id": item.get("source_version_id"),
                "source_input_file": item.get("source_input_file"),
                "source_sha256": item.get("source_sha256"),
            }
            for item in (Config.CHAPTER_MAP or [])
            if isinstance(item, dict)
            and isinstance(item.get("raw_file"), str)
            and isinstance(item.get("source_input_file"), str)
        }
        result = rebuild_translation_memory_embeddings(
            Config.TM_PATH,
            args.output,
            Config.RAW_DIR,
            Config.OUTPUT_DIR,
            Config.SOURCE_MANIFEST_PATH,
            args.chapters,
            source_input_root=Config.AI_EDITION_ROOT if source_input_map else None,
            source_input_map=source_input_map,
            batch_size=args.batch_size,
            api_timeout=Config.API_TIMEOUT,
            provider_data_policy=Config.PROVIDER_DATA_POLICY,
        )
    except Exception as exc:
        print(
            f"TM embedding candidate was not created ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"TM embedding candidate created: {result['output']} "
        f"(chapters={result['chapter_count']}, pairs={result['pair_count']}, "
        f"sha256={result['output_sha256']})"
    )
    print(
        "The source TM and reviewed snapshot were not changed. "
        "Create and approve a TM review receipt before switching retrieval."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
