"""Import a complete metadata translation into a source-bound review candidate."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata_translation import (  # noqa: E402
    create_metadata_translation_candidate,
    verify_metadata_translation_candidate,
    verify_metadata_translation_plan,
)
from utils import (  # noqa: E402
    open_regular_file,
    resolve_child_path,
    write_new_child_bytes_atomically,
)


_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")
_MAX_INPUT_BYTES = 32 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
_INPUT_FIELDS = {
    "schema_version",
    "plan_sha256",
    "translations",
    "translation_provenance",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Translation input contains a duplicate JSON key.")
        result[key] = value
    return result


def _reject_non_finite(value: str):
    raise ValueError("Translation input contains a non-finite JSON number.")


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


def import_metadata_translation_candidate(
    *,
    plan_path: str,
    translations_path: str,
    candidate_name: str,
) -> tuple[Path, dict, bool]:
    if not isinstance(candidate_name, str) or not _FILENAME.fullmatch(
        candidate_name
    ):
        raise ValueError("Candidate name must be a simple JSON filename.")

    plan_file = Path(plan_path)
    if _is_reparse_point(plan_file):
        raise ValueError("Metadata plan must not be a symbolic link.")
    plan_file = plan_file.resolve(strict=True)
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

    plan = _load_json_file(plan_file, "Metadata plan")
    plan_sha256 = verify_metadata_translation_plan(plan)
    imported = _load_json_file(Path(translations_path), "Translation input")
    if set(imported) != _INPUT_FIELDS:
        raise ValueError("Translation input fields do not match schema.")
    if (
        isinstance(imported.get("schema_version"), bool)
        or imported.get("schema_version") != 1
        or imported.get("plan_sha256") != plan_sha256
        or not isinstance(imported.get("translations"), dict)
    ):
        raise ValueError("Translation input does not match the current plan.")

    candidate = create_metadata_translation_candidate(
        plan,
        imported["translations"],
        imported["translation_provenance"],
    )
    verify_metadata_translation_candidate(candidate, plan)
    payload = (
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(payload) > _MAX_CANDIDATE_BYTES:
        raise ValueError("Metadata candidate exceeds the maximum output size.")
    output_path = resolve_child_path(
        str(plans_root),
        candidate_name,
        allow_missing=True,
    )
    try:
        write_new_child_bytes_atomically(
            str(plans_root),
            candidate_name,
            payload,
        )
        reused = False
    except FileExistsError:
        with open_regular_file(output_path, binary=True) as stream:
            existing = stream.read(_MAX_CANDIDATE_BYTES + 1)
        if existing != payload:
            raise ValueError(
                "Candidate output already exists with different content."
            )
        reused = True
    return output_path, candidate, reused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import a complete metadata translation as a source-bound "
            "review-pending candidate. This command does not call a provider."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--translations", required=True)
    parser.add_argument("--candidate-name", required=True)
    args = parser.parse_args(argv)
    try:
        output_path, candidate, reused = import_metadata_translation_candidate(
            plan_path=args.plan,
            translations_path=args.translations,
            candidate_name=args.candidate_name,
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata candidate import refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "metadata_translation_candidate_reused"
                if reused
                else "metadata_translation_candidate_created",
                "output": str(output_path),
                "plan_sha256": candidate["plan_sha256"],
                "candidate_sha256": candidate["candidate_sha256"],
                "field_count": candidate["field_count"],
                "review_status": candidate["status"],
                "provider_calls_made": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
