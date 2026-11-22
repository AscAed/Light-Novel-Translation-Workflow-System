"""Budget metadata translation requests without reading credentials or calling providers."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata_translation import verify_metadata_translation_plan  # noqa: E402
from metadata_translation_generation import (  # noqa: E402
    plan_metadata_translation_generation,
)
from utils import open_regular_file  # noqa: E402


_MAX_PLAN_BYTES = 64 * 1024 * 1024


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Metadata plan contains a duplicate JSON key.")
        result[key] = value
    return result


def load_plan_from_workflow_plans(plan_path: str) -> dict:
    requested = Path(plan_path)
    if requested.is_symlink():
        raise ValueError("Metadata plan must not be a symbolic link.")
    resolved = requested.resolve(strict=True)
    plans_root = resolved.parent
    workflow_root = plans_root.parent
    if (
        plans_root.name != "Plans"
        or workflow_root.name != "Workflow"
        or plans_root.resolve(strict=True) != plans_root
        or workflow_root.resolve(strict=True) != workflow_root
    ):
        raise ValueError("Metadata plan must be stored under Workflow/Plans.")
    with open_regular_file(resolved, binary=True) as stream:
        content = stream.read(_MAX_PLAN_BYTES + 1)
    if len(content) > _MAX_PLAN_BYTES:
        raise ValueError("Metadata plan exceeds the maximum input size.")
    try:
        plan = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("Metadata plan contains a non-finite JSON number.")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Metadata plan is not valid UTF-8 JSON.") from exc
    verify_metadata_translation_plan(plan)
    return plan


def _positive_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a finite positive number.") from exc
    if result <= 0 or result == float("inf") or result != result:
        raise argparse.ArgumentTypeError("Must be a finite positive number.")
    return result


def _nonnegative_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a finite non-negative number.") from exc
    if result < 0 or result == float("inf") or result != result:
        raise argparse.ArgumentTypeError("Must be a finite non-negative number.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plan source-bound metadata translation batches and a declared "
            "cost ceiling. This command makes no provider calls and reads no credentials."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument("--tokenizer-json", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--context-window-tokens", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--safety-margin-tokens", type=int, required=True)
    parser.add_argument("--message-overhead-tokens", type=int, required=True)
    parser.add_argument("--input-price-per-million-tokens", type=_nonnegative_float, required=True)
    parser.add_argument("--output-price-per-million-tokens", type=_nonnegative_float, required=True)
    parser.add_argument("--max-estimated-cost", type=_positive_float, required=True)
    parser.add_argument("--max-provider-calls", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        plan = load_plan_from_workflow_plans(args.plan)
        report = plan_metadata_translation_generation(
            plan,
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            manifest_relative_path=args.manifest,
            tokenizer_json=args.tokenizer_json,
            model_id=args.model_id,
            context_window_tokens=args.context_window_tokens,
            max_output_tokens=args.max_output_tokens,
            safety_margin_tokens=args.safety_margin_tokens,
            message_overhead_tokens=args.message_overhead_tokens,
            input_price_per_million_tokens=args.input_price_per_million_tokens,
            output_price_per_million_tokens=args.output_price_per_million_tokens,
            max_estimated_cost=args.max_estimated_cost,
            max_provider_calls=args.max_provider_calls,
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata generation planning refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
