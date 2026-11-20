"""Shared embedding adapter and vector identity for translation-memory data."""

import hashlib
import json
import math
import os
import re
import urllib.request

from utils import parse_api_timeout, require_provider_data_authorized


GEMINI_EMBEDDING_MODEL = "gemini-embedding-2"
_IDENTITY_V1_FIELDS = {
    "schema_version",
    "provider",
    "protocol",
    "model",
    "task_type",
    "dimensions",
}
_IDENTITY_V2_FIELDS = _IDENTITY_V1_FIELDS | {"endpoint_sha256"}
_PROVIDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def _validated_vector(values) -> list[float]:
    if (
        not isinstance(values, list)
        or not values
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not _is_finite(value)
            for value in values
        )
    ):
        raise RuntimeError("Embedding response contains an invalid vector.")
    return [float(value) for value in values]


def _is_finite(value) -> bool:
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _default_embedding_config() -> dict:
    return {
        "provider": "gemini",
        "protocol": "google-genai",
        "model": GEMINI_EMBEDDING_MODEL,
    }


def _active_embedding_config() -> dict:
    raw = os.environ.get("TRANSLATORAI_EMBEDDING_CONFIG")
    if not raw:
        return _default_embedding_config()
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("TRANSLATORAI_EMBEDDING_CONFIG must be valid JSON.") from exc
    if not isinstance(config, dict):
        raise ValueError("TRANSLATORAI_EMBEDDING_CONFIG must be an object.")
    protocol = config.get("protocol")
    expected = (
        {"provider", "protocol", "model"}
        if protocol == "google-genai"
        else {"provider", "protocol", "model", "base_url"}
        if protocol == "openai-compatible"
        else set()
    )
    if (
        not expected
        or set(config) != expected
        or not isinstance(config.get("provider"), str)
        or not _PROVIDER_ID.fullmatch(config["provider"])
        or not isinstance(config.get("model"), str)
        or not config["model"]
        or config["model"] != config["model"].strip()
    ):
        raise ValueError("Embedding provider configuration is invalid.")
    if protocol == "google-genai" and config["provider"].lower() != "gemini":
        raise ValueError("Google GenAI embedding provider must be gemini.")
    if protocol == "openai-compatible":
        if (
            config["provider"].lower() == "gemini"
            or config["provider"].lower().startswith("pool-")
        ):
            raise ValueError("OpenAI-compatible embedding provider ID is invalid.")
        from pipeline import validate_provider_base_url

        config["base_url"] = validate_provider_base_url(config["base_url"])
    return config


def embedding_identity_for_vector(values, config=None) -> dict:
    vector = _validated_vector(values)
    config = _active_embedding_config() if config is None else config
    identity = {
        "schema_version": 1 if config["protocol"] == "google-genai" else 2,
        "provider": config["provider"].lower(),
        "protocol": config["protocol"],
        "model": config["model"],
        "task_type": "default",
        "dimensions": len(vector),
    }
    if config["protocol"] == "openai-compatible":
        endpoint = config["base_url"].rstrip("/")
        identity["endpoint_sha256"] = hashlib.sha256(
            endpoint.encode("utf-8")
        ).hexdigest()
    return identity


def is_compatible_embedding(values, identity, config=None) -> bool:
    try:
        vector = _validated_vector(values)
        if not isinstance(identity, dict) or frozenset(identity) not in {
            frozenset(_IDENTITY_V1_FIELDS),
            frozenset(_IDENTITY_V2_FIELDS),
        }:
            return False
        if (
            isinstance(identity["schema_version"], bool)
            or not isinstance(identity["schema_version"], int)
            or isinstance(identity["dimensions"], bool)
            or not isinstance(identity["dimensions"], int)
            or any(
                not isinstance(identity[field], str)
                for field in ("provider", "protocol", "model", "task_type")
            )
        ):
            return False
        return identity == embedding_identity_for_vector(vector, config)
    except (TypeError, ValueError, RuntimeError):
        return False


def generate_embeddings(
    texts: list[str],
    *,
    batch_size: int = 50,
    api_timeout: float = 10.0,
    provider_data_policy=None,
    require_api_key: bool = False,
) -> tuple[list[list[float]], dict | None]:
    """Generate one consistent vector per input text using the active provider."""
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise ValueError("Embedding input must be a list of strings.")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")
    if not texts:
        return [], None

    config = _active_embedding_config()
    provider_id = config["provider"].lower()
    require_provider_data_authorized(
        provider_id,
        {"source_text"},
        provider_data_policy,
    )
    timeout = parse_api_timeout(api_timeout)
    mock_port = os.environ.get("MOCK_SERVER_PORT")
    configured = bool(os.environ.get("TRANSLATORAI_EMBEDDING_CONFIG"))
    api_key = (
        os.environ.get("TRANSLATORAI_EMBEDDING_KEY")
        if configured
        else os.environ.get("GEMINI_API_KEY")
    )
    if configured and not api_key:
        raise RuntimeError("Configured embedding API key is missing.")
    if not configured and require_api_key and not api_key and not mock_port:
        raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings.")

    if config["protocol"] == "google-genai":
        if mock_port:
            vectors = _generate_mock_embeddings(
                texts, batch_size, timeout, mock_port, config["model"]
            )
        else:
            from google import genai
            from google.genai import types

            client_options = {
                "http_options": types.HttpOptions(timeout=int(timeout * 1000)),
            }
            if api_key:
                client_options["api_key"] = api_key
            client = genai.Client(**client_options)
            vectors = []
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                response = client.models.embed_content(
                    model=config["model"],
                    contents=batch,
                )
                response_items = getattr(response, "embeddings", None)
                if not isinstance(response_items, list) or len(response_items) != len(batch):
                    raise RuntimeError(
                        "Embedding response count did not match the input batch."
                    )
                vectors.extend(
                    _validated_vector(getattr(item, "values", None))
                    for item in response_items
                )
    else:
        if mock_port:
            raise RuntimeError(
                "OpenAI-compatible embeddings are not served by the local mock endpoint."
            )
        if not api_key:
            raise RuntimeError("Configured embedding API key is missing.")
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=config["base_url"],
            timeout=timeout,
            max_retries=0,
        )
        vectors = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            response = client.embeddings.create(
                model=config["model"],
                input=batch,
                encoding_format="float",
            )
            response_items = getattr(response, "data", None)
            if not isinstance(response_items, list) or len(response_items) != len(batch):
                raise RuntimeError(
                    "Embedding response count did not match the input batch."
                )
            indexed = []
            for item in response_items:
                index = getattr(item, "index", None)
                if isinstance(index, bool) or not isinstance(index, int):
                    raise RuntimeError("Embedding response index was invalid.")
                indexed.append(
                    (index, _validated_vector(getattr(item, "embedding", None)))
                )
            indexed.sort(key=lambda item: item[0])
            if [index for index, _ in indexed] != list(range(len(batch))):
                raise RuntimeError("Embedding response indices were inconsistent.")
            vectors.extend(vector for _, vector in indexed)

    dimensions = {len(vector) for vector in vectors}
    if len(vectors) != len(texts) or len(dimensions) != 1:
        raise RuntimeError("Embedding response dimensions were inconsistent.")
    return vectors, embedding_identity_for_vector(vectors[0], config)


def _generate_mock_embeddings(
    texts: list[str],
    batch_size: int,
    timeout: float,
    mock_port: str,
    model: str,
) -> list[list[float]]:
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        payload = {
            "model": model,
            "contents": batch,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{mock_port}/gemini/embedContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception:
            raise RuntimeError("Mock embedding request failed.") from None

        response_items = result.get("embeddings") if isinstance(result, dict) else None
        if isinstance(response_items, list):
            if len(response_items) != len(batch):
                raise RuntimeError(
                    "Mock embedding response count did not match the input batch."
                )
            vectors.extend(
                _validated_vector(item.get("values") if isinstance(item, dict) else None)
                for item in response_items
            )
            continue

        single_embedding = (
            result.get("embedding") if isinstance(result, dict) else None
        )
        single = (
            single_embedding.get("values")
            if isinstance(single_embedding, dict)
            else None
        )
        vector = _validated_vector(single)
        vectors.extend([vector] * len(batch))
    return vectors
