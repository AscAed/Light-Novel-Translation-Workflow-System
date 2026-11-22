"""Create a source-bound metadata translation inventory for a verified book."""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from book_bundles import load_verified_ai_book_bundle  # noqa: E402
from metadata_translation import (  # noqa: E402
    create_metadata_translation_plan,
    verify_metadata_translation_plan,
)
from source_ingestion import source_artifact_id  # noqa: E402
from source_manifest import (  # noqa: E402
    latest_artifacts_by_kind,
    parse_manifest_bytes,
)
from utils import (  # noqa: E402
    open_regular_file,
    resolve_relative_path,
    write_new_child_bytes_atomically,
)


_PLAN_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


def _current_work_metadata_version_id(
    source_root: Path,
    manifest_relative_path: str,
    work_id: str,
    expected_metadata: dict,
    expected_manifest_sha256: str,
) -> str:
    manifest_path = resolve_relative_path(
        str(source_root),
        manifest_relative_path,
    )
    with open_regular_file(manifest_path, binary=True) as stream:
        manifest_bytes = stream.read()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError(
            "Current source manifest differs from the verified bundle."
        )
    manifest = parse_manifest_bytes(manifest_bytes)
    artifact = latest_artifacts_by_kind(manifest, "work").get(
        source_artifact_id(work_id, "work", "metadata")
    )
    if (
        not isinstance(artifact, dict)
        or not isinstance(artifact.get("version_id"), str)
        or not isinstance(artifact.get("relative_path"), str)
    ):
        raise ValueError("Current work metadata artifact is missing.")
    artifact_path = resolve_relative_path(
        str(source_root),
        artifact["relative_path"],
    )
    with open_regular_file(artifact_path, binary=True) as stream:
        content = stream.read(4 * 1024 * 1024 + 1)
    if (
        len(content) > 4 * 1024 * 1024
        or hashlib.sha256(content).hexdigest() != artifact["content_sha256"]
    ):
        raise ValueError(
            "Current work metadata artifact failed its digest or size check."
        )
    try:
        record = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("Current work metadata artifact is invalid.") from exc
    if (
        not isinstance(record, dict)
        or isinstance(record.get("schema_version"), bool)
        or not isinstance(record.get("schema_version"), int)
        or record.get("schema_version") != 1
        or record.get("work_id") != work_id
        or record.get("metadata") != expected_metadata
    ):
        raise ValueError("Current work metadata differs from the verified bundle.")
    return artifact["version_id"]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Metadata source contains a duplicate JSON key.")
        result[key] = value
    return result


def prepare_metadata_translation(
    *,
    source_root: str,
    catalog_relative_path: str,
    checkpoint_relative_path: str,
    bundle_set_relative_path: str,
    human_root: str,
    ai_root: str,
    plan_name: str,
    manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = "source_editions_manifest.json",
) -> tuple[Path, dict]:
    """Create a plan under the existing project's Workflow/Plans directory."""
    if not isinstance(plan_name, str) or not _PLAN_FILENAME.fullmatch(plan_name):
        raise ValueError("Plan name must be a simple JSON filename.")
    source_path = Path(source_root).resolve(strict=True)
    project_root = source_path.parent
    workflow_root = project_root / "Workflow"
    plans_root = workflow_root / "Plans"
    if (
        not workflow_root.is_dir()
        or not plans_root.is_dir()
        or _is_reparse_point(workflow_root)
        or _is_reparse_point(plans_root)
        or workflow_root.resolve(strict=True) != workflow_root
        or plans_root.resolve(strict=True) != plans_root
    ):
        raise ValueError("Project Workflow/Plans directory must already exist.")

    verified_bundle = load_verified_ai_book_bundle(
        source_root=str(source_path),
        catalog_relative_path=catalog_relative_path,
        checkpoint_relative_path=checkpoint_relative_path,
        bundle_set_relative_path=bundle_set_relative_path,
        human_root=human_root,
        ai_root=ai_root,
        manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
    )
    verified_bundle["bundle"]["work_metadata_version_id"] = (
        _current_work_metadata_version_id(
            source_path,
            manifest_relative_path,
            verified_bundle["work_id"],
            verified_bundle["bundle"]["work_metadata"],
            verified_bundle["bundle"]["provenance"]["source_manifest"]["sha256"],
        )
    )
    plan = create_metadata_translation_plan(verified_bundle)
    verify_metadata_translation_plan(plan)
    payload = (
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_new_child_bytes_atomically(str(plans_root), plan_name, payload)
    return plans_root / plan_name, plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a local, source-version-bound inventory for translating "
            "work metadata, chapter titles, and episode titles. It does not "
            "call a provider or include episode body text."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--bundle-set", required=True)
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument("--plan-name", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default="source_editions_manifest.json",
    )
    args = parser.parse_args(argv)
    try:
        output_path, plan = prepare_metadata_translation(
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            checkpoint_relative_path=args.checkpoint,
            bundle_set_relative_path=args.bundle_set,
            human_root=args.human_root,
            ai_root=args.ai_root,
            plan_name=args.plan_name,
            manifest_relative_path=args.manifest,
            edition_manifest_relative_path=args.edition_manifest,
        )
    except (KeyError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata translation inventory refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "metadata_translation_inventory_created",
                "output": str(output_path),
                "plan_sha256": plan["plan_sha256"],
                "field_count": plan["field_count"],
                "pending_count": plan["pending_count"],
                "missing_count": plan["missing_count"],
                "provider_calls_made": 0,
                "episode_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
