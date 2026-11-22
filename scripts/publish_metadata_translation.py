"""Publish an approved metadata artifact under the project's Metadata directory."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata_translation import (  # noqa: E402
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)
from metadata_translation_freshness import (  # noqa: E402
    verify_metadata_translation_plan_freshness,
)
from metadata_translation_publication import (  # noqa: E402
    create_metadata_translation_artifact,
    verify_metadata_translation_artifact,
)
from metadata_translation_review import (  # noqa: E402
    verify_metadata_translation_review,
)
from utils import (  # noqa: E402
    open_regular_file,
    resolve_child_path,
    write_new_child_bytes_atomically,
)


_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")
_MAX_INPUT_BYTES = 128 * 1024 * 1024
_MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Metadata publication input has duplicate JSON keys.")
        result[key] = value
    return result


def _reject_non_finite(value: str):
    raise ValueError("Metadata publication input has a non-finite JSON number.")


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


def _load_json_file(path: Path, label: str) -> dict:
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(_MAX_INPUT_BYTES + 1)
    if len(content) > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds the maximum input size.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _project_paths(plan_path: str) -> tuple[Path, Path, Path]:
    requested_plan = Path(plan_path)
    if _is_reparse_point(requested_plan):
        raise ValueError("Metadata plan must not be a symbolic link.")
    plan_file = requested_plan.resolve(strict=True)
    plans_root = plan_file.parent
    workflow_root = plans_root.parent
    project_root = workflow_root.parent
    if (
        plans_root.name != "Plans"
        or workflow_root.name != "Workflow"
        or not plans_root.is_dir()
        or not workflow_root.is_dir()
        or not project_root.is_dir()
        or any(
            _is_reparse_point(path) or path.resolve(strict=True) != path
            for path in (plans_root, workflow_root, project_root)
        )
    ):
        raise ValueError("Plan must be stored under a real Workflow/Plans directory.")
    metadata_root = project_root / "Metadata"
    if (
        not metadata_root.is_dir()
        or _is_reparse_point(metadata_root)
        or metadata_root.resolve(strict=True) != metadata_root
    ):
        raise ValueError("Project Metadata directory must already exist.")
    return plan_file, plans_root, metadata_root


def publish_metadata_translation_artifact(
    *,
    plan_path: str,
    candidate_name: str,
    review_name: str,
    source_root: str,
    catalog_relative_path: str,
    artifact_name: str,
    manifest_relative_path: str = "source_manifest.json",
) -> tuple[Path, dict, bool]:
    if not isinstance(artifact_name, str) or not _FILENAME.fullmatch(artifact_name):
        raise ValueError("Artifact name must be a simple JSON filename.")
    if not isinstance(candidate_name, str) or not _FILENAME.fullmatch(candidate_name):
        raise ValueError("Candidate name must be a simple JSON filename.")
    if not isinstance(review_name, str) or not _FILENAME.fullmatch(review_name):
        raise ValueError("Review name must be a simple JSON filename.")

    plan_file, plans_root, metadata_root = _project_paths(plan_path)
    candidate_path = resolve_child_path(str(plans_root), candidate_name)
    review_path = resolve_child_path(str(plans_root), review_name)
    plan = _load_json_file(plan_file, "Metadata plan")
    candidate = _load_json_file(candidate_path, "Metadata candidate")
    review = _load_json_file(review_path, "Metadata review")
    verify_metadata_translation_plan(plan)
    verify_metadata_translation_candidate(candidate, plan)
    verify_metadata_translation_review(review, plan, candidate)
    freshness = verify_metadata_translation_plan_freshness(
        plan,
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
    )
    current_source_snapshot = {
        "catalog_sha256": freshness["catalog_sha256"],
        "manifest_sha256": freshness["manifest_sha256"],
    }
    artifact = create_metadata_translation_artifact(
        plan,
        candidate,
        review,
        current_source_snapshot,
    )
    verify_metadata_translation_artifact(
        artifact,
        plan,
        candidate,
        review,
        current_source_snapshot,
    )
    payload = (
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(payload) > _MAX_OUTPUT_BYTES:
        raise ValueError("Metadata release artifact exceeds the maximum output size.")
    output_path = resolve_child_path(
        str(metadata_root),
        artifact_name,
        allow_missing=True,
    )
    try:
        write_new_child_bytes_atomically(str(metadata_root), artifact_name, payload)
        reused = False
    except FileExistsError:
        with open_regular_file(output_path, binary=True) as stream:
            existing = stream.read(_MAX_OUTPUT_BYTES + 1)
        if existing != payload:
            raise ValueError(
                "Metadata artifact already exists with different content."
            )
        reused = True
    return output_path, artifact, reused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an approved, source-current bilingual metadata artifact "
            "under the project's existing Metadata directory."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--artifact-name", required=True)
    args = parser.parse_args(argv)
    try:
        output_path, artifact, reused = publish_metadata_translation_artifact(
            plan_path=args.plan,
            candidate_name=args.candidate,
            review_name=args.review,
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            manifest_relative_path=args.manifest,
            artifact_name=args.artifact_name,
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata publication refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "metadata_artifact_reused"
                if reused
                else "metadata_artifact_created",
                "output": str(output_path),
                "artifact_sha256": artifact["artifact_sha256"],
                "work_id": artifact["work_id"],
                "field_count": artifact["field_count"],
                "translated_field_count": artifact["translated_field_count"],
                "missing_source_count": artifact["missing_source_count"],
                "source_snapshot": artifact["source_snapshot"],
                "consumer_integration_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
