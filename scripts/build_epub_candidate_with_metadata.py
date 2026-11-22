"""Build an EPUB candidate using a current, approved metadata artifact."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epub_builder import _read_catalog, build_epub_candidate  # noqa: E402
from metadata_translation_epub import create_epub_metadata_catalog  # noqa: E402
from metadata_translation_freshness import (  # noqa: E402
    verify_metadata_translation_plan_freshness,
)
from scripts.publish_metadata_translation import (  # noqa: E402
    _load_json_file,
    _project_paths,
)
from utils import resolve_child_path  # noqa: E402


_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")


def build_epub_candidate_with_metadata(
    *,
    input_root: str,
    epub_catalog_relative_path: str,
    source_root: str,
    source_manifest_relative_path: str,
    metadata_source_catalog_relative_path: str,
    plan_path: str,
    candidate_name: str,
    review_name: str,
    artifact_name: str,
    output_root: str,
    max_chapter_bytes: int,
    max_total_bytes: int,
    max_output_bytes: int,
    pandoc_executable: str = "pandoc",
    timeout_seconds: int = 120,
) -> dict:
    for name, label in (
        (candidate_name, "Metadata candidate"),
        (review_name, "Metadata review"),
        (artifact_name, "Metadata artifact"),
    ):
        if not isinstance(name, str) or not _FILENAME.fullmatch(name):
            raise ValueError(f"{label} must be a simple JSON filename.")
    plan_file, plans_root, metadata_root = _project_paths(plan_path)
    candidate_path = resolve_child_path(str(plans_root), candidate_name)
    review_path = resolve_child_path(str(plans_root), review_name)
    artifact_path = resolve_child_path(str(metadata_root), artifact_name)
    plan = _load_json_file(plan_file, "Metadata plan")
    candidate = _load_json_file(candidate_path, "Metadata candidate")
    review = _load_json_file(review_path, "Metadata review")
    artifact = _load_json_file(artifact_path, "Metadata artifact")

    freshness = verify_metadata_translation_plan_freshness(
        plan,
        source_root=source_root,
        catalog_relative_path=metadata_source_catalog_relative_path,
        manifest_relative_path=source_manifest_relative_path,
        allow_field_drift=True,
    )
    source_snapshot = {
        "catalog_sha256": freshness["catalog_sha256"],
        "manifest_sha256": freshness["manifest_sha256"],
    }
    input_dir = Path(input_root).resolve(strict=True)
    epub_catalog = _read_catalog(input_dir, epub_catalog_relative_path)
    overlaid_catalog, provenance = create_epub_metadata_catalog(
        epub_catalog,
        artifact,
        plan,
        candidate,
        review,
        source_snapshot,
        freshness["field_statuses"],
        freshness["current_field_sources"],
    )

    with tempfile.TemporaryDirectory(
        prefix=".metadata-epub-catalog-",
        dir=input_dir,
    ) as temporary:
        temporary_catalog = Path(temporary) / "epub-catalog.json"
        with open(temporary_catalog, "xb") as stream:
            stream.write(
                (
                    json.dumps(
                        overlaid_catalog,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        relative_catalog = temporary_catalog.relative_to(input_dir).as_posix()
        result = build_epub_candidate(
            input_root=input_dir,
            catalog_relative_path=relative_catalog,
            source_root=source_root,
            source_manifest_relative_path=source_manifest_relative_path,
            output_root=output_root,
            max_chapter_bytes=max_chapter_bytes,
            max_total_bytes=max_total_bytes,
            max_output_bytes=max_output_bytes,
            pandoc_executable=pandoc_executable,
            timeout_seconds=timeout_seconds,
            metadata_translation_provenance=provenance,
            chapter_source_titles={
                chapter["episode_id"]: chapter["title"]
                for chapter in epub_catalog["chapters"]
            },
        )
    result["metadata_translation_artifact_sha256"] = provenance["artifact_sha256"]
    return result


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive integer.") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build an EPUB candidate after verifying approved, source-current "
            "bilingual metadata."
        )
    )
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--epub-catalog", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-manifest", default="source_manifest.json")
    parser.add_argument("--metadata-source-catalog", required=True)
    parser.add_argument("--metadata-plan", required=True)
    parser.add_argument("--metadata-candidate", required=True)
    parser.add_argument("--metadata-review", required=True)
    parser.add_argument("--metadata-artifact", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--max-chapter-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-total-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-output-bytes", type=_positive_int, required=True)
    parser.add_argument("--timeout-seconds", type=_positive_int, default=120)
    args = parser.parse_args(argv)
    try:
        result = build_epub_candidate_with_metadata(
            input_root=args.input_root,
            epub_catalog_relative_path=args.epub_catalog,
            source_root=args.source_root,
            source_manifest_relative_path=args.source_manifest,
            metadata_source_catalog_relative_path=args.metadata_source_catalog,
            plan_path=args.metadata_plan,
            candidate_name=args.metadata_candidate,
            review_name=args.metadata_review,
            artifact_name=args.metadata_artifact,
            output_root=args.output_root,
            max_chapter_bytes=args.max_chapter_bytes,
            max_total_bytes=args.max_total_bytes,
            max_output_bytes=args.max_output_bytes,
            pandoc_executable=args.pandoc,
            timeout_seconds=args.timeout_seconds,
        )
    except (
        FileExistsError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        RuntimeError,
        TimeoutError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            f"ERROR: EPUB candidate with metadata refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
