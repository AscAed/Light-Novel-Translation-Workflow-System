"""Interactive API pool setup for the existing workflow."""

import getpass
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api_pool import FALLBACK_ENV, POOL_ENV
from api_pool_store import (
    default_profile_path,
    get_profile_version,
    load_profile,
    migrate_v1_profile,
    provider_model_identity,
    save_profile,
)
from pipeline import validate_provider_base_url
from windows_credentials import CredentialStoreError


ROLES = (
    ("INITIAL_MODEL", "初译", "日中理解和忠实翻译，能够遵循指令；需要足够上下文及稳定响应"),
    ("PROOFREAD_MODEL", "上下文标注、校对与知识抽取", "日中语义比对、说话人/指代标注、术语抽取和结构化 JSON；需要较强推理和足够上下文"),
    ("STYLE_MODEL", "润色", "中文表达、人物语气和原意保持；需要稳定的长文本生成能力"),
)
ALL_CATEGORIES = ("source_text", "translation_text", "book_knowledge")


def _ask(prompt, default=""):
    return input(prompt).strip() or default


def configure():
    print("API 池配置（支持 OpenAI 兼容的文本生成接口）")
    print("最低要求：至少一个端点 URL、模型 ID、可用 Key，以及对应数据类别授权。")
    print("缺少配置时无法调用知识抽取或翻译；连接与模型质量需要另行验证。")
    print("每个已接入职责：")
    for _, title, description in ROLES:
        print(f"  {title}：{description}")
    print("终审模型必须与初译及校对/返工模型使用不同的端点和模型。")
    print("显式运行 scripts/review_translation_candidate.py 可单次执行双评估终审。")
    print("显式运行 scripts/run_ai_translation_workflow.py 可执行有限返工、复审及通过后发布。")
    print("自动返工只修订审核 findings 指向的段落；真实语义质量仍须单独验收。")
    print("嵌入接口可单独选择 Gemini 或 OpenAI-compatible；默认不启用，且需单独授权 source_text。")
    print("模型上下文长度、速度、价格和质量由渠道及实际测试决定，此处不作保证。")
    pool = {}
    keys = {}
    while True:
        slot = _ask("添加 API 标识（小写字母开头，字母/数字/下划线；留空结束）：")
        if not slot:
            break
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", slot) or slot in pool:
            print("标识无效或重复，请重新输入。")
            continue
        try:
            url = validate_provider_base_url(_ask("API Base URL："))
        except ValueError as exc:
            print(f"URL 无效：{exc}")
            continue
        model = _ask("渠道模型 ID：")
        if not model:
            print("模型 ID 不能为空。")
            continue
        pool[slot] = {"base_url": url, "model": model}
    if not pool:
        raise ValueError("至少需要一个 API。")
    names = ", ".join(pool)
    assignments = {}
    for env_name, title, _ in ROLES:
        slot = _ask(f"{title}使用哪个 API（{names}）：")
        if slot not in pool:
            raise ValueError(f"{title}所选 API 不存在。")
        assignments[env_name] = slot
    reviewer_slot = _ask(
        f"可选终审使用哪个独立 API（{names}；留空表示暂不配置）："
    )
    if reviewer_slot:
        if reviewer_slot not in pool:
            raise ValueError("终审所选 API 不存在。")
        reviewer_identity = provider_model_identity(pool[reviewer_slot])
        if reviewer_identity in {
            provider_model_identity(pool[assignments["INITIAL_MODEL"]]),
            provider_model_identity(pool[assignments["PROOFREAD_MODEL"]]),
        }:
            raise ValueError(
                "终审模型必须与初译及校对/返工模型使用不同的端点和模型。"
            )
        assignments["FINAL_REVIEW_MODEL"] = reviewer_slot
    fallback = _ask(f"临时错误时的备用 API（{names}；留空表示不回退）：")
    if fallback and (fallback not in pool or fallback in assignments.values()):
        raise ValueError("备用 API 必须存在且不同于所有已选择的主 API。")
    grants = {}
    used = set(assignments.values()) | ({fallback} if fallback else set())
    for slot in sorted(used):
        key = getpass.getpass(f"API {slot} 的 Key（不显示）：")
        if not key:
            raise ValueError(f"API {slot} 的 Key 不能为空。")
        keys[slot] = key
        categories = set()
        if assignments.get("INITIAL_MODEL") == slot:
            categories.update(("source_text", "book_knowledge"))
        if any(
            assignments.get(role) == slot
            for role in (
                "PROOFREAD_MODEL",
                "STYLE_MODEL",
                "FINAL_REVIEW_MODEL",
            )
        ):
            categories.update(ALL_CATEGORIES)
        if slot == fallback:
            categories.update(ALL_CATEGORIES)
        print(f"API {slot} 可能接收：{', '.join(sorted(categories))}。")
        if _ask("确认授权这些类别用于相应职责？输入 yes 确认：").lower() != "yes":
            raise PermissionError("未获明确授权，未启用 API 池。")
        grants[f"pool-{slot}"] = sorted(categories)
    active_pool = {slot: pool[slot] for slot in sorted(used)}
    embedding = _configure_embedding()
    return active_pool, assignments, fallback, grants, keys, embedding


def _configure_embedding():
    if _ask("单独配置文本嵌入 Provider？[y/N]：").lower() not in {"y", "yes"}:
        return None
    protocol_choice = _ask(
        "嵌入协议：1) Gemini 2) OpenAI-compatible [1]：",
        "1",
    )
    if protocol_choice == "1":
        provider = "gemini"
        protocol = "google-genai"
        model = _ask("Gemini embedding 模型 ID：", "gemini-embedding-2")
        embedding = {"provider": provider, "protocol": protocol, "model": model}
    elif protocol_choice == "2":
        provider = _ask("嵌入 Provider ID（如 embedding）：", "embedding")
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", provider)
            or provider.lower() == "gemini"
            or provider.lower().startswith("pool-")
        ):
            raise ValueError("嵌入 Provider ID 无效。")
        protocol = "openai-compatible"
        url = validate_provider_base_url(_ask("嵌入 API Base URL："))
        model = _ask("嵌入模型 ID：")
        embedding = {
            "provider": provider,
            "protocol": protocol,
            "base_url": url,
            "model": model,
        }
    else:
        raise ValueError("嵌入协议选择无效。")
    if not model or model != model.strip():
        raise ValueError("嵌入模型 ID 无效。")
    print(f"嵌入 Provider {provider} 将接收 source_text。")
    if _ask("确认授权该 Provider 处理原文文本？输入 yes 确认：").lower() != "yes":
        raise PermissionError("未获明确授权，未启用嵌入 Provider。")
    embedding["grants"] = ["source_text"]
    embedding["api_key"] = getpass.getpass("嵌入 API Key（不显示）：")
    if not embedding["api_key"]:
        raise ValueError("嵌入 API Key 不能为空。")
    return embedding


def activate(pool, assignments, fallback, grants, keys, embedding=None):
    os.environ.pop("FINAL_REVIEW_MODEL", None)
    for name in tuple(os.environ):
        if name.startswith("TRANSLATORAI_POOL_KEY_"):
            os.environ.pop(name, None)
    os.environ.pop("TRANSLATORAI_EMBEDDING_CONFIG", None)
    os.environ.pop("TRANSLATORAI_EMBEDDING_KEY", None)
    os.environ[POOL_ENV] = json.dumps(pool)
    active_grants = {
        provider: set(categories) for provider, categories in grants.items()
    }
    if embedding is not None:
        provider = embedding["provider"].lower()
        active_grants.setdefault(provider, set()).add("source_text")
        runtime_embedding = {
            key: value
            for key, value in embedding.items()
            if key not in {"api_key", "credential_ref", "grants"}
        }
        os.environ["TRANSLATORAI_EMBEDDING_CONFIG"] = json.dumps(
            runtime_embedding,
            ensure_ascii=False,
        )
        os.environ["TRANSLATORAI_EMBEDDING_KEY"] = embedding["api_key"]
    os.environ["PROVIDER_DATA_POLICY"] = json.dumps(
        {provider: sorted(categories) for provider, categories in active_grants.items()},
        ensure_ascii=False,
    )
    os.environ["ENABLE_JYQF_FALLBACK"] = "false"
    os.environ["ENABLE_GEMINI_FALLBACK"] = "false"
    os.environ[FALLBACK_ENV] = f"pool:{fallback}" if fallback else ""
    for slot, key in keys.items():
        os.environ[f"TRANSLATORAI_POOL_KEY_{slot.upper()}"] = key
    for env_name, slot in assignments.items():
        os.environ[env_name] = f"pool:{slot}"
    print("配置完成；尚未连接服务。临时错误回退最多一次，可能产生重复费用。")
    if embedding is None:
        print("未配置嵌入 Provider；TM 向量检索/生成将按授权策略关闭。")
    print("现有全书知识、章节映射审批及最终发布门禁仍需满足。")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--help"] or args == ["-h"]:
        print(
            "用法：configure_api_pool.py "
            "[--knowledge | --rebuild-tm-embeddings] -- <入口参数>"
        )
        print("默认启动 Kakuyomu 翻译编排；--knowledge 启动知识候选抽取。")
        print("--rebuild-tm-embeddings 创建经来源核验的 TM 候选，不改写现有 TM。")
        print("可将配置保存到当前 Windows 用户账户；不提供参数时仅配置。")
        return 0
    mode = args.pop(0) if args and args[0] in {
        "--knowledge",
        "--rebuild-tm-embeddings",
    } else None
    if args and args[0] == "--":
        args.pop(0)
    try:
        profile_path = default_profile_path() if os.name == "nt" else None
        if profile_path and profile_path.is_file() and _ask("发现已保存的 API 池，使用它？[Y/n]：", "yes").lower() in {"y", "yes"}:
            version = get_profile_version(path=profile_path)
            if version == 1 and _ask(
                "将 v1 配置迁移到 v2？迁移会保留旧凭据引用并创建不含 Key 的备份。输入 yes 迁移："
            ).lower() == "yes":
                settings, backup_path = migrate_v1_profile(
                    validate_provider_base_url,
                    path=profile_path,
                )
                print(f"已升级配置；旧配置备份为 {backup_path.name}。")
            else:
                settings = load_profile(validate_provider_base_url, path=profile_path)
            print("已加载保存的 API 池；未连接服务。")
        else:
            settings = configure()
            if _ask("保存 API 池和 Key 供下次使用？输入 yes 保存：").lower() == "yes":
                save_profile(
                    *settings[:5],
                    validate_provider_base_url,
                    embedding=settings[5],
                    path=profile_path,
                )
                print("已保存配置和 Windows 凭据；服务可用性尚未验证。")
        activate(*settings)
        if not args:
            print("未提供工作流参数；本次运行未调用 Provider。")
            print("请使用 python scripts/configure_api_pool.py -- <工作流参数> 启动。")
            return 0
        if mode == "--knowledge":
            from scripts.auto_extract_knowledge import main as extract_knowledge
            old_argv = sys.argv
            try:
                sys.argv = ["auto_extract_knowledge.py", *args]
                return extract_knowledge() or 0
            finally:
                sys.argv = old_argv
        if mode == "--rebuild-tm-embeddings":
            from scripts.rebuild_tm_embeddings import main as rebuild_embeddings
            return rebuild_embeddings(args) or 0
        from scripts.run_kakuyomu_workflow import main as run_workflow
        return run_workflow(args)
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1
    except (ValueError, PermissionError, CredentialStoreError, OSError) as exc:
        print(f"配置失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
