"""Persist non-secret pool settings and Windows credential references."""

import json
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from windows_credentials import CredentialStoreError, delete_secret, read_secret, write_secret

_SLOT = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_PROVIDER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_API_TARGET = re.compile(r"TranslatorAI/API/[0-9a-f]{32}\Z")
_EMBEDDING_TARGET = re.compile(r"TranslatorAI/Embedding/[0-9a-f]{32}\Z")
_ROLES = {"INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL"}
_FINAL_REVIEW_ROLE = "FINAL_REVIEW_MODEL"
_CATEGORIES = {"source_text", "translation_text", "book_knowledge"}
_V1_FIELDS = {"version", "pool", "assignments", "fallback", "grants"}
_V2_FIELDS = _V1_FIELDS | {"embedding"}


def provider_model_identity(entry):
    parsed = urlsplit(entry["base_url"])
    port = parsed.port
    if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        port,
        parsed.path.rstrip("/"),
        entry["model"],
    )


def default_profile_path():
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise ValueError("无法找到 LOCALAPPDATA，不能持久化 API 配置。")
    return Path(root) / "TranslatorAI" / "api-pool.json"


def _profile_digest(profile):
    return hashlib.sha256(
        json.dumps(
            profile,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_embedding(embedding, validate_url):
    if embedding is None:
        return
    if not isinstance(embedding, dict):
        raise ValueError("嵌入配置无效。")
    protocol = embedding.get("protocol")
    if protocol == "google-genai":
        required = {"provider", "protocol", "model", "credential_ref", "grants"}
        if embedding.get("provider") != "gemini":
            raise ValueError("Google GenAI 嵌入 Provider 无效。")
    elif protocol == "openai-compatible":
        required = {
            "provider",
            "protocol",
            "base_url",
            "model",
            "credential_ref",
            "grants",
        }
        provider = embedding.get("provider")
        if (
            not isinstance(provider, str)
            or not _PROVIDER.fullmatch(provider)
            or provider.lower() == "gemini"
            or provider.lower().startswith("pool-")
        ):
            raise ValueError("OpenAI-compatible 嵌入 Provider ID 无效。")
        validate_url(embedding.get("base_url"))
    else:
        raise ValueError("嵌入协议不受支持。")
    if set(embedding) != required:
        raise ValueError("嵌入配置字段无效。")
    model = embedding.get("model")
    if not isinstance(model, str) or not model or model != model.strip():
        raise ValueError("嵌入模型 ID 无效。")
    if not isinstance(embedding.get("credential_ref"), str) or not _EMBEDDING_TARGET.fullmatch(
        embedding["credential_ref"]
    ):
        raise ValueError("嵌入凭据引用无效。")
    grants = embedding.get("grants")
    if grants != ["source_text"]:
        raise ValueError("嵌入 Provider 必须且只能授权 source_text。")


def _validate(profile, validate_url):
    if not isinstance(profile, dict):
        raise ValueError("API 池配置结构无效。")
    version = profile.get("version")
    if (
        isinstance(version, bool)
        or version not in (1, 2, 3)
        or set(profile) != (_V1_FIELDS if version == 1 else _V2_FIELDS)
    ):
        raise ValueError("API 池版本或配置结构无效。")
    pool, assignments, fallback, grants = (profile[k] for k in ("pool", "assignments", "fallback", "grants"))
    if not isinstance(pool, dict) or not pool:
        raise ValueError("API 池版本或列表无效。")
    for slot, entry in pool.items():
        if not isinstance(slot, str) or not _SLOT.fullmatch(slot) or not isinstance(entry, dict):
            raise ValueError("API 池标识无效。")
        if set(entry) != {"base_url", "model", "credential_ref"}:
            raise ValueError("API 池条目无效。")
        validate_url(entry["base_url"])
        model, ref = entry["model"], entry["credential_ref"]
        if not isinstance(model, str) or not model or model != model.strip():
            raise ValueError("模型 ID 无效。")
        if not isinstance(ref, str) or not _API_TARGET.fullmatch(ref):
            raise ValueError("凭据引用无效。")
    expected_roles = _ROLES | ({_FINAL_REVIEW_ROLE} if version == 3 else set())
    if not isinstance(assignments, dict) or set(assignments) != expected_roles:
        raise ValueError("职责分配无效。")
    if any(not isinstance(v, str) or v not in pool for v in assignments.values()):
        raise ValueError("职责引用了不存在的 API。")
    if version == 3 and provider_model_identity(
        pool[assignments[_FINAL_REVIEW_ROLE]]
    ) == provider_model_identity(pool[assignments["INITIAL_MODEL"]]):
        raise ValueError("终审模型必须与初译模型使用不同的端点和模型。")
    if not isinstance(fallback, str) or (fallback and (fallback not in pool or fallback in assignments.values())):
        raise ValueError("备用 API 无效。")
    if not isinstance(grants, dict):
        raise ValueError("API 授权无效。")
    used = set(assignments.values()) | ({fallback} if fallback else set())
    if set(grants) != {f"pool-{slot}" for slot in used}:
        raise ValueError("API 授权与职责不匹配。")
    for slot in used:
        categories = grants[f"pool-{slot}"]
        if not isinstance(categories, list) or any(not isinstance(c, str) for c in categories):
            raise ValueError("API 授权类别无效。")
        required = ({"source_text", "book_knowledge"} if assignments["INITIAL_MODEL"] == slot else set())
        if slot == fallback or any(
            assignments.get(role) == slot
            for role in (
                "PROOFREAD_MODEL",
                "STYLE_MODEL",
                _FINAL_REVIEW_ROLE,
            )
        ):
            required |= _CATEGORIES
        if not required <= set(categories) or not set(categories) <= _CATEGORIES:
            raise ValueError("API 授权类别不足或包含未支持类别。")
    if version in (2, 3):
        _validate_embedding(profile["embedding"], validate_url)


def save_profile(
    pool,
    assignments,
    fallback,
    grants,
    keys,
    validate_url,
    *,
    embedding=None,
    path=None,
):
    path = Path(path) if path is not None else default_profile_path()
    if set(keys) != set(pool) or any(not isinstance(v, str) or not v for v in keys.values()):
        raise ValueError("API Key 缺失。")
    entries = {
        slot: {**entry, "credential_ref": f"TranslatorAI/API/{uuid.uuid4().hex}"}
        for slot, entry in pool.items()
    }
    embedding_entry = None
    embedding_key = None
    if embedding is not None:
        if not isinstance(embedding, dict):
            raise ValueError("嵌入配置无效。")
        embedding_key = embedding.get("api_key")
        if not isinstance(embedding_key, str) or not embedding_key:
            raise ValueError("嵌入 API Key 缺失。")
        embedding_entry = {
            key: value for key, value in embedding.items() if key != "api_key"
        }
        embedding_entry["credential_ref"] = (
            f"TranslatorAI/Embedding/{uuid.uuid4().hex}"
        )
    profile = {
        "version": (
            3
            if isinstance(assignments, dict)
            and _FINAL_REVIEW_ROLE in assignments
            else 2
        ),
        "pool": entries,
        "assignments": assignments,
        "fallback": fallback,
        "grants": grants,
        "embedding": embedding_entry,
    }
    _validate(profile, validate_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _profile_digest(profile)
    written_refs = []
    temporary = None
    try:
        for slot, entry in entries.items():
            write_secret(entry["credential_ref"], json.dumps(
                {"profile_sha256": digest, "key": keys[slot]}, ensure_ascii=False
            ))
            written_refs.append(entry["credential_ref"])
        if embedding_entry is not None:
            write_secret(
                embedding_entry["credential_ref"],
                json.dumps(
                    {"profile_sha256": digest, "key": embedding_key},
                    ensure_ascii=False,
                ),
            )
            written_refs.append(embedding_entry["credential_ref"])
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".api-pool-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException as save_error:
        cleanup_failed = False
        for ref in written_refs:
            try:
                delete_secret(ref)
            except Exception:
                cleanup_failed = True
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            raise CredentialStoreError(
                "API 配置保存失败，且部分新建凭据未能清理；请检查 Windows 凭据管理器中的 TranslatorAI/API 与 TranslatorAI/Embedding 项。"
            ) from save_error
        raise


def load_profile(validate_url, *, path=None):
    path = Path(path) if path is not None else default_profile_path()
    with path.open(encoding="utf-8") as stream:
        profile = json.load(stream)
    _validate(profile, validate_url)
    digest = _profile_digest(profile)
    keys = {}
    for slot, entry in profile["pool"].items():
        try:
            stored = json.loads(read_secret(entry["credential_ref"]))
        except (ValueError, TypeError) as exc:
            raise ValueError("已保存的凭据格式无效。") from exc
        if not isinstance(stored, dict) or stored.get("profile_sha256") != digest:
            raise ValueError("API 配置与凭据绑定不一致，请重新配置。")
        if not isinstance(stored.get("key"), str) or not stored["key"]:
            raise ValueError("已保存的 API Key 为空。")
        keys[slot] = stored["key"]
    embedding = None
    if profile["version"] in (2, 3) and profile["embedding"] is not None:
        entry = profile["embedding"]
        try:
            stored = json.loads(read_secret(entry["credential_ref"]))
        except (ValueError, TypeError) as exc:
            raise ValueError("已保存的嵌入凭据格式无效。") from exc
        if not isinstance(stored, dict) or stored.get("profile_sha256") != digest:
            raise ValueError("嵌入配置与凭据绑定不一致，请重新配置。")
        if not isinstance(stored.get("key"), str) or not stored["key"]:
            raise ValueError("已保存的嵌入 API Key 为空。")
        embedding = {key: value for key, value in entry.items() if key != "credential_ref"}
        embedding["api_key"] = stored["key"]
    pool = {slot: {"base_url": entry["base_url"], "model": entry["model"]}
            for slot, entry in profile["pool"].items()}
    return (
        pool,
        profile["assignments"],
        profile["fallback"],
        profile["grants"],
        keys,
        embedding,
    )


def get_profile_version(*, path=None):
    path = Path(path) if path is not None else default_profile_path()
    with path.open(encoding="utf-8") as stream:
        profile = json.load(stream)
    _validate(profile, lambda _: None)
    return profile["version"]


def migrate_v1_profile(validate_url, *, path=None):
    """Upgrade a validated v1 profile while preserving its credentials and backup."""
    path = Path(path) if path is not None else default_profile_path()
    with path.open(encoding="utf-8") as stream:
        profile = json.load(stream)
    _validate(profile, validate_url)
    if profile["version"] != 1:
        raise ValueError("只有 API 池 v1 配置需要迁移。")

    settings = load_profile(validate_url, path=path)
    backup_path = path.with_name(
        f"{path.stem}.v1-{uuid.uuid4().hex}.backup.json"
    )
    backup_temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".api-pool-v1-backup-",
            delete=False,
        ) as stream:
            backup_temporary = Path(stream.name)
            stream.write(path.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(backup_temporary, backup_path)
        backup_temporary = None
    except BaseException:
        if backup_temporary is not None and backup_temporary.exists():
            backup_temporary.unlink()
        raise

    save_profile(
        *settings[:5],
        validate_url,
        embedding=None,
        path=path,
    )
    return load_profile(validate_url, path=path), backup_path
