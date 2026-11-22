"""Session-only OpenAI-compatible provider pool configuration."""

import json
import os
import re


POOL_ENV = "TRANSLATORAI_API_POOL"
FALLBACK_ENV = "TRANSLATORAI_POOL_FALLBACK"
_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")


def resolve_pool_route(alias: str) -> dict:
    slot = alias.removeprefix("pool:")
    if not alias.startswith("pool:") or not _ID.fullmatch(slot):
        raise ValueError("Invalid API pool slot.")
    try:
        pool = json.loads(os.environ.get(POOL_ENV, "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid API pool configuration.") from exc
    if not isinstance(pool, dict) or not isinstance(pool.get(slot), dict):
        raise ValueError(f"API pool slot '{slot}' is not configured.")
    entry = pool[slot]
    url, model = entry.get("base_url"), entry.get("model")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"API pool slot '{slot}' requires a URL.")
    if not isinstance(model, str) or not model or model != model.strip():
        raise ValueError(f"API pool slot '{slot}' requires a model ID.")
    return {
        "provider_id": f"pool-{slot}",
        "base_url": url,
        "model": model,
        "key_env": f"TRANSLATORAI_POOL_KEY_{slot.upper()}",
    }
