"""Token-budgeted, evidence-preserving knowledge extraction batches."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from utils import open_regular_file


_MAX_TOKENIZER_BYTES = 64 * 1024 * 1024
_MAX_PARAGRAPHS_PER_BATCH = 500
_MAX_PROVIDER_CALLS = 100


class TokenizerArtifactError(ValueError):
    pass


class BatchBudgetError(ValueError):
    pass


class BatchCountError(ValueError):
    pass


@dataclass(frozen=True)
class SourceParagraph:
    source_id: str
    filename: str
    paragraph_index: int
    text: str

    def to_prompt_record(self) -> dict:
        return asdict(self)

    def to_evidence_record(self) -> dict:
        return {
            "source_id": self.source_id,
            "filename": self.filename,
            "paragraph_index": self.paragraph_index,
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
        }


def load_tokenizer_json(path: str):
    tokenizer_path = Path(path)
    if tokenizer_path.is_symlink() or not tokenizer_path.is_file():
        raise TokenizerArtifactError(
            "Tokenizer JSON must be an existing regular file."
        )
    try:
        with open_regular_file(tokenizer_path, binary=True) as stream:
            tokenizer_bytes = stream.read(_MAX_TOKENIZER_BYTES + 1)
    except OSError as exc:
        raise TokenizerArtifactError("Tokenizer JSON could not be read.") from exc
    if len(tokenizer_bytes) > _MAX_TOKENIZER_BYTES:
        raise TokenizerArtifactError("Tokenizer JSON exceeds the size limit.")
    try:
        tokenizer_text = tokenizer_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TokenizerArtifactError("Tokenizer JSON must be UTF-8.") from exc

    try:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_str(tokenizer_text)
        tokenizer.no_truncation()
    except Exception as exc:
        raise TokenizerArtifactError(
            "Tokenizer JSON is not supported by the installed tokenizers package."
        ) from exc
    return tokenizer, hashlib.sha256(tokenizer_bytes).hexdigest()


def count_message_tokens(tokenizer, system_text: str, user_text: str) -> int:
    try:
        system_count = len(tokenizer.encode(system_text).ids)
        user_count = len(tokenizer.encode(user_text).ids)
    except (AttributeError, TypeError, ValueError) as exc:
        raise BatchBudgetError("Tokenizer could not count request text.") from exc
    if system_count < 0 or user_count < 0:
        raise BatchBudgetError("Tokenizer returned an invalid token count.")
    return system_count + user_count


def render_batch_records(paragraphs: list[SourceParagraph]) -> str:
    return json.dumps(
        [paragraph.to_prompt_record() for paragraph in paragraphs],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def plan_paragraph_batches(
    paragraphs: list[SourceParagraph],
    *,
    tokenizer,
    system_text: str,
    render_user_text,
    input_token_limit: int,
    message_overhead_tokens: int,
    max_provider_calls: int,
) -> list[dict]:
    if not paragraphs:
        raise BatchBudgetError("Full-book extraction has no non-empty paragraphs.")
    for name, value in (
        ("input_token_limit", input_token_limit),
        ("message_overhead_tokens", message_overhead_tokens),
        ("max_provider_calls", max_provider_calls),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BatchBudgetError(f"{name} must be a positive integer.")
    if max_provider_calls > _MAX_PROVIDER_CALLS:
        raise BatchCountError(
            f"Full-book extraction is limited to {_MAX_PROVIDER_CALLS} provider calls."
        )

    batches = []
    current = []

    def request_size(candidate):
        user_text = render_user_text(candidate)
        request_tokens = (
            count_message_tokens(tokenizer, system_text, user_text)
            + message_overhead_tokens
        )
        return user_text, request_tokens

    for paragraph in paragraphs:
        candidate = current + [paragraph]
        _, candidate_tokens = request_size(candidate)
        if (
            candidate_tokens <= input_token_limit
            and len(candidate) <= _MAX_PARAGRAPHS_PER_BATCH
        ):
            current = candidate
            continue

        if not current:
            raise BatchBudgetError(
                "A source paragraph exceeds the configured per-request token budget."
            )
        user_text, input_tokens = request_size(current)
        batches.append(
            {
                "paragraphs": current,
                "user_text": user_text,
                "input_tokens": input_tokens,
            }
        )
        if len(batches) >= max_provider_calls:
            raise BatchCountError(
                "Full-book extraction exceeds the configured provider-call limit."
            )

        current = [paragraph]
        _, single_tokens = request_size(current)
        if single_tokens > input_token_limit:
            raise BatchBudgetError(
                "A source paragraph exceeds the configured per-request token budget."
            )

    if current:
        user_text, input_tokens = request_size(current)
        batches.append(
            {
                "paragraphs": current,
                "user_text": user_text,
                "input_tokens": input_tokens,
            }
        )
    if len(batches) > max_provider_calls:
        raise BatchCountError(
            "Full-book extraction exceeds the configured provider-call limit."
        )
    return batches


def validate_batch_budget(
    *,
    context_window_tokens: int,
    max_output_tokens: int,
    safety_margin_tokens: int,
    message_overhead_tokens: int,
) -> int:
    values = {
        "context_window_tokens": context_window_tokens,
        "max_output_tokens": max_output_tokens,
        "safety_margin_tokens": safety_margin_tokens,
        "message_overhead_tokens": message_overhead_tokens,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BatchBudgetError(f"{name} must be a positive integer.")
    input_limit = (
        context_window_tokens
        - max_output_tokens
        - safety_margin_tokens
    )
    if input_limit < 1:
        raise BatchBudgetError(
            "Context window cannot contain the input, output reserve, and safety margin."
        )
    return input_limit
