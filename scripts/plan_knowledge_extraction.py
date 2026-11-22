"""Plan full-book knowledge extraction without loading provider credentials."""

import argparse
import hashlib
import json
import re
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from book_bundles import load_verified_ai_book_bundle  # noqa: E402
from knowledge_batching import (  # noqa: E402
    SourceParagraph,
    count_message_tokens,
    load_tokenizer_json,
    plan_paragraph_batches,
    validate_batch_budget,
)
from scripts.auto_extract_knowledge import (  # noqa: E402
    _FULL_BOOK_SYSTEM_PROMPT,
    _render_full_book_batch_prompt,
)
from utils import split_paragraphs  # noqa: E402


_MAX_SOURCE_CHAPTERS = 1000
_MAX_PROVIDER_CALLS = 100


def plan_full_book_extraction(
    *,
    source_root: str,
    catalog_relative_path: str,
    checkpoint_relative_path: str,
    bundle_set_relative_path: str,
    human_root: str,
    ai_root: str,
    tokenizer_json: str,
    model_id: str,
    max_input_characters: int,
    context_window_tokens: int,
    max_output_tokens: int,
    safety_margin_tokens: int,
    message_overhead_tokens: int,
    max_provider_calls: int = _MAX_PROVIDER_CALLS,
    manifest_relative_path: str = "source_manifest.json",
    edition_manifest_relative_path: str = "source_editions_manifest.json",
) -> dict:
    """Return a content-free plan using the same bundle and batch contracts."""
    if (
        not isinstance(model_id, str)
        or not model_id.strip()
        or len(model_id) > 256
        or any(ord(character) < 32 for character in model_id)
    ):
        raise ValueError("A declared model ID is required.")
    if model_id != model_id.strip():
        raise ValueError("Model ID must not contain surrounding whitespace.")
    for name, value in (
        ("max_input_characters", max_input_characters),
        ("max_provider_calls", max_provider_calls),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if max_provider_calls > _MAX_PROVIDER_CALLS:
        raise ValueError("Knowledge planning is limited to 100 provider calls.")

    tokenizer, tokenizer_sha256 = load_tokenizer_json(tokenizer_json)
    input_token_limit = validate_batch_budget(
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        message_overhead_tokens=message_overhead_tokens,
    )
    bundle = load_verified_ai_book_bundle(
        source_root=source_root,
        catalog_relative_path=catalog_relative_path,
        checkpoint_relative_path=checkpoint_relative_path,
        bundle_set_relative_path=bundle_set_relative_path,
        human_root=human_root,
        ai_root=ai_root,
        manifest_relative_path=manifest_relative_path,
        edition_manifest_relative_path=edition_manifest_relative_path,
    )
    if bundle.get("status") != "verified":
        raise ValueError("Current AI book bundle is not verified.")

    episodes_by_input = bundle.get("episodes_by_source_input_file")
    if not isinstance(episodes_by_input, dict) or not episodes_by_input:
        raise ValueError("Verified AI book bundle has no chapter inputs.")
    if len(episodes_by_input) > _MAX_SOURCE_CHAPTERS:
        raise ValueError("Book chapter count exceeds the configured limit.")
    if (
        isinstance(bundle.get("episode_count"), bool)
        or not isinstance(bundle.get("episode_count"), int)
        or bundle["episode_count"] != len(episodes_by_input)
    ):
        raise ValueError("Verified AI book bundle chapter count is inconsistent.")

    episodes = []
    seen_positions = set()
    for source_input_file, episode in episodes_by_input.items():
        if (
            not isinstance(source_input_file, str)
            or not source_input_file
            or not isinstance(episode, dict)
        ):
            raise ValueError("Verified AI book bundle has an invalid chapter map.")
        position = episode.get("position")
        source_file = episode.get("source_file")
        source_text = episode.get("source_text")
        source_sha256 = episode.get("source_sha256")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or position in seen_positions
            or not isinstance(source_file, str)
            or not source_file
            or not isinstance(source_text, str)
            or not isinstance(source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        ):
            raise ValueError("Verified AI book bundle has an invalid chapter record.")
        if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != source_sha256:
            raise ValueError("Verified AI book bundle chapter digest is inconsistent.")
        seen_positions.add(position)
        episodes.append(
            (position, source_file, source_input_file, source_text)
        )

    episodes.sort(key=lambda row: row[0])
    if [row[0] for row in episodes] != list(range(1, len(episodes) + 1)):
        raise ValueError("Verified AI book bundle chapter positions are not contiguous.")

    paragraphs = []
    input_characters = 0
    for source_index, (position, source_file, _, source_text) in enumerate(
        episodes, start=1
    ):
        normalized_text = source_text.replace("\r\n", "\n").replace("\r", "\n")
        section_header = f"\n\n--- {source_file} ---\n\n"
        input_characters += len(section_header) + len(normalized_text)
        if input_characters > max_input_characters:
            raise ValueError("Book input exceeds the configured character limit.")
        for paragraph_index, paragraph in enumerate(
            split_paragraphs(normalized_text), start=1
        ):
            paragraphs.append(
                SourceParagraph(
                    source_id=f"C{source_index:04d}P{paragraph_index:05d}",
                    filename=source_file,
                    paragraph_index=paragraph_index,
                    text=paragraph,
                )
            )

    batches = plan_paragraph_batches(
        paragraphs,
        tokenizer=tokenizer,
        system_text=_FULL_BOOK_SYSTEM_PROMPT,
        render_user_text=_render_full_book_batch_prompt,
        input_token_limit=input_token_limit,
        message_overhead_tokens=message_overhead_tokens,
        max_provider_calls=max_provider_calls,
    )
    synthesis_call_reserve = max_provider_calls - len(batches)
    if len(batches) > 1 and synthesis_call_reserve < 1:
        raise ValueError(
            "Provider-call budget must reserve at least one call for synthesis."
        )
    batch_tokens = [
        count_message_tokens(
            tokenizer,
            _FULL_BOOK_SYSTEM_PROMPT,
            batch["user_text"],
        )
        + message_overhead_tokens
        for batch in batches
    ]
    synthesis_calls_minimum = 1 if len(batches) > 1 else 0

    return {
        "schema_version": 1,
        "status": "ready_for_extraction",
        "scope": "all_verified_ai_bundle_chapters",
        "model_id": model_id,
        "model_id_source": "caller_declared_not_verified",
        "book_bundle": {
            field: bundle[field]
            for field in (
                "source_snapshot_id",
                "ai_bundle_id",
                "bundle_set_relative_path",
                "bundle_set_sha256",
                "ai_bundle_relative_path",
                "ai_bundle_sha256",
                "episode_count",
            )
        },
        "episode_count": len(episodes),
        "paragraph_count": len(paragraphs),
        "input_characters": input_characters,
        "input_character_limit": max_input_characters,
        "tokenizer_sha256": tokenizer_sha256,
        "context_window_tokens": context_window_tokens,
        "max_input_tokens_per_request": input_token_limit,
        "max_output_tokens_per_request": max_output_tokens,
        "safety_margin_tokens": safety_margin_tokens,
        "message_overhead_tokens": message_overhead_tokens,
        "extraction_batch_count": len(batches),
        "estimated_extraction_input_tokens": sum(batch_tokens),
        "largest_estimated_batch_input_tokens": max(batch_tokens),
        "minimum_provider_calls": len(batches) + synthesis_calls_minimum,
        "max_provider_calls": max_provider_calls,
        "remaining_provider_call_budget_for_synthesis": synthesis_call_reserve,
        "provider_cost_estimate": None,
        "provider_calls_made": 0,
        "files_written": 0,
        "source_text_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and budget a full-book knowledge extraction without "
            "reading provider credentials or making network requests."
        )
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--bundle-set", required=True)
    parser.add_argument("--human-root", required=True)
    parser.add_argument("--ai-root", required=True)
    parser.add_argument("--tokenizer-json", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--max-input-characters", type=int, required=True)
    parser.add_argument("--context-window-tokens", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--safety-margin-tokens", type=int, required=True)
    parser.add_argument("--message-overhead-tokens", type=int, required=True)
    parser.add_argument("--max-provider-calls", type=int, default=_MAX_PROVIDER_CALLS)
    parser.add_argument("--manifest", default="source_manifest.json")
    parser.add_argument(
        "--edition-manifest",
        default="source_editions_manifest.json",
    )
    args = parser.parse_args(argv)

    try:
        report = plan_full_book_extraction(
            source_root=args.source_root,
            catalog_relative_path=args.catalog,
            checkpoint_relative_path=args.checkpoint,
            bundle_set_relative_path=args.bundle_set,
            human_root=args.human_root,
            ai_root=args.ai_root,
            tokenizer_json=args.tokenizer_json,
            model_id=args.model_id,
            max_input_characters=args.max_input_characters,
            context_window_tokens=args.context_window_tokens,
            max_output_tokens=args.max_output_tokens,
            safety_margin_tokens=args.safety_margin_tokens,
            message_overhead_tokens=args.message_overhead_tokens,
            max_provider_calls=args.max_provider_calls,
            manifest_relative_path=args.manifest,
            edition_manifest_relative_path=args.edition_manifest,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, KeyError) as exc:
        print(
            f"ERROR: knowledge extraction planning refused ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
