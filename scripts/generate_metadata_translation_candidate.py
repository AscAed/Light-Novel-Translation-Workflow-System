"""Plan or explicitly execute bounded metadata translation batches."""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata_translation_generation import (  # noqa: E402
    build_metadata_translation_generation_plan,
)
from metadata_translation_executor import (  # noqa: E402
    execute_metadata_translation_generation,
)
from scripts.plan_metadata_translation_generation import (  # noqa: E402
    load_plan_from_workflow_plans,
)

_CANDIDATE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json\Z")


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


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan metadata translation without credentials by default. "
            "Only --execute may call the explicitly selected provider."
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
    parser.add_argument(
        "--input-price-per-million-tokens",
        type=_nonnegative_float,
        required=True,
    )
    parser.add_argument(
        "--output-price-per-million-tokens",
        type=_nonnegative_float,
        required=True,
    )
    parser.add_argument("--max-estimated-cost", type=_positive_float, required=True)
    parser.add_argument("--max-provider-calls", type=int, default=100)
    parser.add_argument("--candidate-name")
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Load the explicit model route and authorized credentials, then "
            "call it once per uncheckpointed batch."
        ),
    )
    return parser


def _load_execution_route(model_id: str):
    from pipeline import (
        Config,
        get_api_key,
        get_openai_client,
        get_primary_provider_route,
        resolve_openai_client_settings,
    )

    categories = {"source_text"}
    Config.load_config()
    route = get_primary_provider_route(model_id)
    api_key = get_api_key(route.api_key_env)
    resolve_openai_client_settings(
        route.base_url,
        api_key,
        provider_id=route.provider_id,
        data_categories=categories,
    )
    client = get_openai_client(
        route.base_url,
        api_key,
        provider_id=route.provider_id,
        data_categories=categories,
        max_retries=0,
    )
    from ai_translation_review import _provider_fingerprint

    return (
        route.provider_id,
        route.request_model or model_id,
        _provider_fingerprint(model_id),
        client,
    )


async def _execute_and_close(client, **kwargs):
    try:
        return await execute_metadata_translation_generation(
            client=client,
            **kwargs,
        )
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    client = None
    try:
        plan = load_plan_from_workflow_plans(args.plan)
        generation_plan = build_metadata_translation_generation_plan(
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
        if not args.execute:
            output = generation_plan["summary"]
        else:
            if not isinstance(args.candidate_name, str) or not _CANDIDATE_FILENAME.fullmatch(
                args.candidate_name
            ):
                raise ValueError(
                    "A simple --candidate-name JSON filename is required with --execute."
                )
            (
                provider_id,
                request_model,
                provider_fingerprint,
                client,
            ) = _load_execution_route(args.model_id)
            plan_file = Path(args.plan).resolve(strict=True)
            execution_client = client
            client = None
            output = asyncio.run(
                _execute_and_close(
                    execution_client,
                    plan=plan,
                    generation_plan=generation_plan,
                    source_root=args.source_root,
                    catalog_relative_path=args.catalog,
                    manifest_relative_path=args.manifest,
                    plans_root=plan_file.parent,
                    candidate_name=args.candidate_name,
                    model_id=args.model_id,
                    request_model=request_model,
                    provider_id=provider_id,
                    provider_fingerprint=provider_fingerprint,
                )
            )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            "ERROR: metadata translation generation refused "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            "ERROR: metadata translation generation failed "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    finally:
        if client is not None:
            try:
                asyncio.run(client.close())
            except Exception:
                pass

    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
