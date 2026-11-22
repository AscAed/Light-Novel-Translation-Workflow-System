"""Create a human review template or finalize its source-bound receipt."""

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
from metadata_translation_review import (  # noqa: E402
    create_metadata_translation_review_template,
    finalize_metadata_translation_review,
    verify_metadata_translation_review,
    verify_metadata_translation_review_template,
)
from metadata_translation_freshness import (  # noqa: E402
    verify_metadata_translation_plan_freshness,
)
from utils import (  # noqa: E402
    open_regular_file,
    resolve_child_path,
    write_new_child_bytes_atomically,
)


_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")
_MAX_INPUT_BYTES = 64 * 1024 * 1024
_MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Metadata review input contains a duplicate JSON key.")
        result[key] = value
    return result


def _reject_non_finite(value: str):
    raise ValueError("Metadata review input contains a non-finite JSON number.")


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


def _plans_root(plan_path: str) -> tuple[Path, Path]:
    requested_plan = Path(plan_path)
    if _is_reparse_point(requested_plan):
        raise ValueError("Metadata plan must not be a symbolic link.")
    plan_file = requested_plan.resolve(strict=True)
    plans_root = plan_file.parent
    workflow_root = plans_root.parent
    if (
        plans_root.name != "Plans"
        or workflow_root.name != "Workflow"
        or not plans_root.is_dir()
        or _is_reparse_point(plans_root)
        or _is_reparse_point(workflow_root)
        or plans_root.resolve(strict=True) != plans_root
        or workflow_root.resolve(strict=True) != workflow_root
    ):
        raise ValueError("Plan must be stored under an existing Workflow/Plans directory.")
    return plan_file, plans_root


def _load_context(
    plan_path: str,
    candidate_name: str,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str,
) -> tuple[Path, Path, dict, dict, dict]:
    if not isinstance(candidate_name, str) or not _FILENAME.fullmatch(candidate_name):
        raise ValueError("Candidate name must be a simple JSON filename.")
    plan_file, plans_root = _plans_root(plan_path)
    candidate_path = resolve_child_path(str(plans_root), candidate_name)
    plan = _load_json_file(plan_file, "Metadata plan")
    candidate = _load_json_file(candidate_path, "Metadata candidate")
    verify_metadata_translation_plan(plan)
    verify_metadata_translation_candidate(candidate, plan)
    freshness = verify_metadata_translation_plan_freshness(
        plan,
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
    )
    return plans_root, candidate_path, plan, candidate, freshness


def _write_or_reuse(plans_root: Path, name: str, payload: bytes) -> tuple[Path, bool]:
    if not isinstance(name, str) or not _FILENAME.fullmatch(name):
        raise ValueError("Output name must be a simple JSON filename.")
    if len(payload) > _MAX_OUTPUT_BYTES:
        raise ValueError("Metadata review output exceeds the maximum size.")
    output_path = resolve_child_path(str(plans_root), name, allow_missing=True)
    try:
        write_new_child_bytes_atomically(str(plans_root), name, payload)
        return output_path, False
    except FileExistsError:
        with open_regular_file(output_path, binary=True) as stream:
            existing = stream.read(_MAX_OUTPUT_BYTES + 1)
        if existing != payload:
            raise ValueError("Metadata review output already exists with different content.")
        return output_path, True


def create_review_template(
    *,
    plan_path: str,
    candidate_name: str,
    template_name: str,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str = "source_manifest.json",
) -> tuple[Path, dict, bool]:
    plans_root, _, plan, candidate, _ = _load_context(
        plan_path,
        candidate_name,
        source_root,
        catalog_relative_path,
        manifest_relative_path,
    )
    template = create_metadata_translation_review_template(plan, candidate)
    payload = (json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path, reused = _write_or_reuse(plans_root, template_name, payload)
    return output_path, template, reused


def finalize_review(
    *,
    plan_path: str,
    candidate_name: str,
    template_name: str,
    report_name: str,
    source_root: str,
    catalog_relative_path: str,
    manifest_relative_path: str = "source_manifest.json",
) -> tuple[Path, dict, bool]:
    plans_root, _, plan, candidate, freshness = _load_context(
        plan_path,
        candidate_name,
        source_root,
        catalog_relative_path,
        manifest_relative_path,
    )
    if not isinstance(template_name, str) or not _FILENAME.fullmatch(template_name):
        raise ValueError("Template name must be a simple JSON filename.")
    template_path = resolve_child_path(str(plans_root), template_name)
    template = _load_json_file(template_path, "Metadata review template")
    verify_metadata_translation_review_template(template, plan, candidate)
    report = finalize_metadata_translation_review(
        template,
        plan,
        candidate,
        {
            "catalog_sha256": freshness["catalog_sha256"],
            "manifest_sha256": freshness["manifest_sha256"],
        },
    )
    verify_metadata_translation_review(report, plan, candidate)
    final_freshness = verify_metadata_translation_plan_freshness(
        plan,
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        manifest_relative_path=manifest_relative_path,
    )
    if (
        final_freshness["catalog_sha256"] != report["source_snapshot"]["catalog_sha256"]
        or final_freshness["manifest_sha256"]
        != report["source_snapshot"]["manifest_sha256"]
    ):
        raise ValueError("Metadata source changed while the review was finalized.")
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path, reused = _write_or_reuse(plans_root, report_name, payload)
    return output_path, report, reused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a pending field-by-field human review template or finalize "
            "a local receipt. Reviewer identity is a declaration, not authentication."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create-template", metavar="FILENAME")
    mode.add_argument("--review-template", metavar="FILENAME")
    parser.add_argument("--report-name")
    args = parser.parse_args(argv)
    try:
        if args.create_template:
            if args.report_name:
                parser.error("--report-name is only valid with --review-template.")
            output_path, template, reused = create_review_template(
                plan_path=args.plan,
                candidate_name=args.candidate,
                template_name=args.create_template,
                source_root=args.source_root,
                catalog_relative_path=args.catalog,
                manifest_relative_path=args.manifest,
            )
            result = {
                "status": "metadata_review_template_reused"
                if reused
                else "metadata_review_template_created",
                "output": str(output_path),
                "plan_sha256": template["plan_sha256"],
                "candidate_sha256": template["candidate_sha256"],
                "field_count": template["field_count"],
                "review_status": "pending_review",
            }
        else:
            if not args.report_name:
                parser.error("--report-name is required with --review-template.")
            output_path, report, reused = finalize_review(
                plan_path=args.plan,
                candidate_name=args.candidate,
                template_name=args.review_template,
                report_name=args.report_name,
                source_root=args.source_root,
                catalog_relative_path=args.catalog,
                manifest_relative_path=args.manifest,
            )
            result = {
                "status": "metadata_review_receipt_reused"
                if reused
                else "metadata_review_receipt_created",
                "output": str(output_path),
                "plan_sha256": report["plan_sha256"],
                "candidate_sha256": report["candidate_sha256"],
                "review_sha256": report["review_sha256"],
                "decision_count": report["decision_count"],
                "decision_counts": report["decision_counts"],
                "source_snapshot": report["source_snapshot"],
                "review_status": report["status"],
                "reviewer_authenticated": False,
                "publication_performed": False,
            }
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata review operation refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
