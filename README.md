# AI 轻小说翻译工作流

## 项目状态

- 当前代码基线：`main` HEAD `df4e3ed`，PR #60 已合并 Kakuyomu 本地映射预览；PR #58/#59 的功能与文档也在该基线上。完整测试结果及仍待人工/真实服务验收的边界见[开发与验证](docs/development.md#2026-11-16-pr-60-合并后基线)。
- D-11：新增逐章恢复日志，TM 写入失败或进程中断后可在重跑时恢复同一译文/TM 更新；多进程并发、断电持久性和日志冲突自动解决不在保证范围内。
- 当前实现：Python CLI 翻译流水线、RAG 检索、章节对齐、来源版本清单、显式本地导入、UTF-8 Markdown 物化/章节导出与来源版本映射。Kakuyomu 专用工作流可从 `--work-url` 解析主页公开目录、校验唯一 episode ID 数等于 `publicEpisodeCount`、保存发现 catalog、按目录顺序访问全部普通 episode URL 并版本化归档；本次 source-only live 采集已完成主页声明的 88/88 话，生成 88 个单话 Markdown 和一份全书 export。工作流不登录、不跟随重定向、不访问 `/read`，请求间隔默认为 2 秒并限制为 1.5–3 秒；`run_kakuyomu_workflow.py` 还可预检 Provider、生成确定性章节映射并调用生产流水线。用户明确不要求官方澄清并要求普通 URL 路径；平台规则风险另有记录，不代表平台背书或公开分发授权。作品范围限于主页当前声明的公开话目，不包括草稿/私有章节或其声明外完整性；正文/ruby/旁点人工验收、真实 Provider 翻译尚未完成。目录解析、限额、验证和阶段边界见[项目现状](docs/project-status.md)与[原文采集方案](docs/source-ingestion-and-publication-plan.md)。
- 阶段 2 可为术语、概要和 TM 原译对生成绑定候选哈希的本地审核回执；TM approved-only 快照仅在显式配置 `TM_REVIEWED_PATH` 时作为 RAG 检索源，运行时仍写入完整 `TM_PATH`。回执未签名/认证审核者身份，不证明审核真实发生或语义正确；旧 Markdown 概要仍兼容但未验证。默认 TM 检索仍未受门禁保护；完整知识状态机、人物知识治理、风险分层、更正/废弃和审核者认证未完成。
- I5 EPUB builder 只产出显式选集 candidate 并运行有限结构检查，不代表质量/完整性批准或阅读器兼容；格式规范化、来源目录完整性独立证明、持久化下游过期状态、Notion 与完整 EPUB 构建尚未完成。
- 外部 Provider 的书籍数据发送默认拒绝；逐 Provider/数据类别授权配置见[开发与验证](docs/development.md)。
- 当前工作目标：日语轻小说译为中文；通用多语言、多文本类型是长期目标，不是现有能力。
- 事实、限制和未知项见[项目现状](docs/project-status.md)。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Codex/Agent 工作约束、验证与文档维护规则 |
| [项目现状](docs/project-status.md) | 以仓库证据记录已实现、部分实现、计划和未知 |
| [架构与边界](docs/architecture.md) | 当前模块、数据流、接口与目标边界 |
| [翻译流程](docs/translation-workflow.md) | 当前流水线阶段、角色职责、质量要求 |
| [知识库治理](docs/knowledge-governance.md) | 当前知识数据与建议的审核、写入规则 |
| [开发与验证](docs/development.md) | 环境、配置、命令、测试事实和限制 |
| [路线图](docs/roadmap.md) | 分阶段目标、依赖、交付物与验收条件 |
| [模型与 API 配置方案](docs/model-provider-configuration-plan.md) | 模型候选、职责分配、配置交互、安全边界与实施计划（计划，未经实测） |
| [原文采集与成果归档方案](docs/source-ingestion-and-publication-plan.md) | 来源许可、原文版本、翻译衔接、EPUB 与 Notion 工作包（部分原型，其余为计划） |
| [当前续接交接](docs/handoffs/2026-11-15-translation-workflow.md) | 最近的阶段状态、验证结果、合并记录及可直接执行的后续步骤 |
| [历史续接交接](docs/handoffs/2026-11-14-translation-workflow.md) | 历次实现与验证的历史快照；现状以项目现状和路线图为准 |
| [决策记录](docs/decisions/README.md) | 已确认决策与待决事项索引 |
| [本地凭据风险记录](docs/security-notes.md) | 凭据暴露边界与需人工处理事项 |

## 现有命令

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Requires a local Clash Verge proxy listening on 127.0.0.1:7897; change these addresses if your proxy differs.
$env:http_proxy = "http://127.0.0.1:7897"; $env:https_proxy = "http://127.0.0.1:7897"; $env:all_proxy = "socks5://127.0.0.1:7897"
python -m pip install -r requirements.txt

python pipeline.py --project <项目目录名>
python scripts/align_chapters.py --project <项目目录名>
python scripts/validate_tm_provenance.py --project <项目目录名>
python scripts/validate_knowledge_provenance.py --root <原文数据根目录> --manifest source_manifest.json --provenance <知识目录/KNOWLEDGE_PROVENANCE_draft.json>
python scripts/ingest_kakuyomu_pages.py --source-root <catalog目录> --catalog <catalog.json> --output-root <原文数据根目录>
python scripts/ingest_kakuyomu_pages.py --source-root <原文数据根目录> --work-url <作品主页URL> --output-root <原文数据根目录>
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog source_catalog.discovered.json --translation-root <译文数据根目录> --manifest source_manifest.json --plan-only
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog <相对catalog.json> --translation-root <译文数据根目录> --config <项目配置.json>
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --create-template review_receipt.json
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review <回执文件名> --output Glossary_reviewed.json
python tests/run_tests.py
```

Kakuyomu 页面导入和依赖安装会访问外网，运行前需在同一 PowerShell 会话中设置仓库要求的代理环境变量。配置模式和验证限制见[开发与验证](docs/development.md)。仓库没有依赖锁文件、CI 配置或部署清单；安装依赖不代表真实模型端点或外部部署已验证。

`run_kakuyomu_workflow.py --plan-only` 只读取已有 catalog、manifest 和目标目录，输出待人工核对的章节映射 JSON；无需 Provider 配置，不联网、不写文件、不输出原文。摘要哈希用于识别该份预览，不代表审核凭证，也不会被正式翻译命令强制校验。

## 维护约定

- 修改代码或行为时，同步更新受影响的事实文档和验证证据。
- 只将可由当前源代码、配置、测试或 Git 状态支持的内容标为“已实现/已验证”。
- 建议、目标、待决策和未知项不得与实现事实混写。
- 新决策写入[决策记录](docs/decisions/README.md)；阶段状态写入[路线图](docs/roadmap.md)。
