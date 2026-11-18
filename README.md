# AI 轻小说翻译工作流

## 项目状态

> 默认 `pipeline.py --project` 同时要求当前来源有效的 `Knowledge/STORY_SUMMARY_reviewed.json` 与 `Knowledge/Glossary_reviewed.json`；旧式 `Glossary.json` 仅保留给显式 JSON 配置。试点当前尚无 reviewed glossary bundle，因此该默认项目入口会在 RAG 初始化时失败关闭。

- 2026-11-17 工作集在 `main` 基线 `e2fe611` 上继续实现 token 预算分批的全书知识抽取、AI/人读双版本清洗和 AI 版默认翻译选源；Kakuyomu 完整采集后会自动生成双版本，并默认从经索引、哈希和 lineage 核验的 `RAWs_AI` AI 清洗版读取翻译输入。`SourceArchive` 只保存原始/派生版本、来源清单/采集状态和不可变校验快照；翻译计划与审批回执分别存放在项目 `Workflow/Plans/`、`Workflow/Approvals/`。章节映射保留归档路径和版本 ID 用于溯源校验。通用项目模式也默认使用 AI 清洗版；无参数时仅在存在唯一非示例项目时自动发现，多项目时要求 `--project` 或 `TRANSLATOR_PROJECT`。没有 AI 项目且未提供显式 JSON 配置时，流水线失败关闭，不退回仓库根 `生肉/`。当前增量验证结果见[开发与验证](docs/development.md#2026-11-17-raws-ai-作为默认翻译输入)。
- 2026-11-17 试点来源归档位于 `projects\祝福のネトラレラ\SourceArchive`，AI 清洗版位于项目 `RAWs_AI`；翻译正文只从 `RAWs_AI` 读取。计划和审批回执分别存放于项目 `Workflow/Plans/`、`Workflow/Approvals/`，不会写入归档。人读版为用户指定外部 `生肉`，译文根为同书外部 `熟肉`。全量刷新已保存 88 个独立 `raw_page_html` 响应体 artifact，正文版本未变；`source_manifest.json` 356/356、合并 `source_editions_manifest.json` 532/532 校验通过。当前 schema v2 AI 计划 88/88 来源有效、0 问题；译文目录仍为空，未调用 Provider。当前映射待人工审阅，详情见[项目现状](docs/project-status.md)与[原始 HTML 归档验证](docs/development.md#2026-11-17-原始-html-归档与默认-ai-计划复核)。
- 2026-11-17 真实追加无变化复查：88 话发现并复用、0 新增、未请求正文；随后仅刷新双版索引，章节 Markdown 未变。默认 `--plan-only` 再验 AI 版 88/88、0 问题；定向回归 56 项通过。新增话正文抓取仍待 live 验证；TM 有 19 条未索引、reviewed 全书概要缺失，未调用 Provider。详见[开发与验证](docs/development.md#2026-11-17-kakuyomu-追加无变化复查与-ai-默认输入)。
- 2026-11-17 新增双版本只读验证器：从当前 raw 字节重算 AI/人读清洗 profile，并对照索引、不可变归档和镜像；当前 88 话 `verified`，19 项合成回归通过。它验证可重复性，不代替人工映射/阅读器验收。详见[开发与验证](docs/development.md#2026-11-17-ai-与人读版清洗产物可重复验证)。
- 2026-11-18 增加内容寻址的 raw/AI/human 全书 bundle、full-book 知识输入绑定、译文 run 草稿区及逐话人工审核后 create-only 发布。试点 88 话 bundle-set 与 AI bundle v2 已由当前来源、checkpoint 和 edition index 复核；未调用真实 Provider，也未生成真实知识或译文。人工映射/清洗验收、审核者身份、返工链和返工次数仍待处理。详见[项目现状](docs/project-status.md#2026-11-18-翻译工作流续接)、[翻译流程](docs/translation-workflow.md#2026-11-18-受审草稿与发布)和[开发与验证](docs/development.md#2026-11-18-整书快照与审核发布门禁)。
- 2026-11-18 后续接通版本绑定的单话知识审核与翻译上下文注入；Kakuyomu 会在首个模型调用前预检全部待翻译章节。最新非 E2E 回归 551 项通过、4 项 Windows 能力跳过；mock E2E 7 项通过。真实 Provider、88 话人工映射/清洗验收与知识/译文质量仍未验证，见[开发与验证](docs/development.md#2026-11-18-最终续接验证)。
- D-11：新增逐章恢复日志，TM 写入失败或进程中断后可在重跑时恢复同一译文/TM 更新；多进程并发、断电持久性和日志冲突自动解决不在保证范围内。
- 当前实现：Python CLI 翻译流水线、RAG 检索、章节对齐、来源版本清单、显式本地导入、UTF-8 Markdown 物化/章节导出与来源版本映射。Kakuyomu 专用工作流可从 `--work-url` 解析主页公开目录、校验唯一 episode ID 数等于 `publicEpisodeCount`、保存发现 catalog、按目录顺序访问全部普通 episode URL 并版本化归档；解析后的 UTF-8 可见文本保存为 `raw_source`，原始页面响应体 bytes 独立存入 `raw_page_html`。完整采集后自动从同一 `raw_source` 生成 AI 清洗版与人读版，再默认把经 lineage/hash 校验的 `RAWs_AI` 镜像路径写入翻译输入映射；`SourceArchive` 仅用于归档版本、清单及溯源校验。AI 版用于翻译，人读版用于阅读体验。人读根由项目 `workflow_paths.json` 的 `human_edition_root` 配置，未设置时为项目 `生肉/`。2026-11-17 全量刷新完成主页声明的 88/88 话，正文哈希未变并归档 88 个页面响应；基础 manifest 356/356、合并 edition manifest 532/532。独立 `scripts/ingest_kakuyomu_pages.py --project <项目名>` 可在限定的 `SourceArchive/` 下同步来源历史并追加含 AI 索引状态的新鲜度快照；它不重跑双版本清洗，索引过期时默认翻译入口仍失败关闭。纯追加续采会校验旧 catalog/checkpoint/manifest 并只请求目录末尾新增话；2026-11-17 已真实运行无变化场景，新增话正文请求仍待 live 验证。审批计划及 pipeline 版本校验绑定 AI profile、索引/清单哈希、RAWs_AI 输入路径/哈希与逐话来源版本；`--ai-edition-root` 只覆盖 AI 版目录，规范化来源仅可通过 `--source-edition normalized_source` 显式选择。工作流不登录、不跟随重定向、不访问 `/read`，请求间隔限制为 1.5–3 秒；用户明确不要求官方澄清并要求普通 URL 路径，平台风险另有记录，不代表平台背书或公开分发授权。作品范围限于主页当前声明的公开话目，不包括草稿/私有章节或其声明外完整性；自动重建译文/知识、人工格式验收、真实 Provider 翻译仍未完成。目录解析、限额、验证和阶段边界见[项目现状](docs/project-status.md)与[原文采集方案](docs/source-ingestion-and-publication-plan.md)。
- 阶段 2 可为术语、概要和 TM 原译对生成绑定候选哈希的本地审核回执；TM approved-only 快照仅在显式配置 `TM_REVIEWED_PATH` 时作为 RAG 检索源，运行时仍写入完整 `TM_PATH`。全书知识候选可按显式 tokenizer/context/output/safety/message 预算分批抽取并保存逐段来源指针；Kakuyomu 正式入口与默认 `pipeline.py --project` 均要求已审核的全书概要 bundle 覆盖并匹配当前 AI 版章节映射。显式 JSON 兼容配置仍支持旧 Markdown 概要。回执未签名/认证审核者身份，不证明审核真实发生或语义正确。完整知识状态机、人物知识治理、风险分层、更正/废弃和审核者认证未完成。
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
| [试点映射人工审阅](docs/handoffs/2026-11-16-pilot-plan-review.md) | 88 话计划摘要、人工核对项及尚未批准的边界 |
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
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog source_catalog.discovered.json --translation-root <译文数据根目录> --manifest source_manifest.json --plan-only --plan-output projects\<项目名>\Workflow\Plans\translation-plan.json
python scripts/approve_translation_plan.py --plan projects\<项目名>\Workflow\Plans\translation-plan.json --receipt projects\<项目名>\Workflow\Approvals\translation-plan-receipt.json --reviewer <审核者标签>
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog source_catalog.discovered.json --translation-root <译文数据根目录> --config <项目配置.json> --approval-receipt projects\<项目名>\Workflow\Approvals\translation-plan-receipt.json
python scripts/export_book_bundles.py --source-root <SourceArchive> --catalog <catalog.json> --checkpoint <checkpoint.json> --human-root <生肉> --ai-root <RAWs_AI>
python scripts/prepare_translation_review.py --run-directory <Workflow\Runs\<run_id>>
python scripts/publish_reviewed_translation.py --run-directory <Workflow\Runs\<run_id>> --episode-id <episode-id> --review <review.json>
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --create-template review_receipt.json
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review <回执文件名> --output Glossary_reviewed.json
python tests/run_tests.py
```

Kakuyomu 页面导入和依赖安装会访问外网，运行前需在同一 PowerShell 会话中设置仓库要求的代理环境变量。配置模式和验证限制见[开发与验证](docs/development.md)。仓库没有依赖锁文件、CI 配置或部署清单；安装依赖不代表真实模型端点或外部部署已验证。

`run_kakuyomu_workflow.py --plan-only` 默认只读取已有 catalog、manifest 和目标目录并将计划写到 stdout，不联网、不调用 Provider、不写文件、不输出章节正文。显式使用 `--plan-output` 时会在 `SourceArchive/` 之外排他新建计划文件；项目内计划放在 `Workflow/Plans/`，回执放在 `Workflow/Approvals/`。`approve_translation_plan.py` 展示全部映射并要求输入完整计划摘要，之后排他新建本地审批回执；计划和回执 CLI 均拒绝把工作流文件写入计划绑定的来源归档根。经 Kakuyomu 编排入口执行翻译时，必须通过 `--approval-receipt` 提交与当前源版本及映射一致的回执。回执未签名，审核者标签是调用者声明，不提供身份认证。稳定映射未变化时可用原回执续跑，但运行时仍会核验现有译文与 TM 的一致性。详细流程见[翻译流程](docs/translation-workflow.md#映射预览与人工核验)。

## 维护约定

- 修改代码或行为时，同步更新受影响的事实文档和验证证据。
- 只将可由当前源代码、配置、测试或 Git 状态支持的内容标为“已实现/已验证”。
- 建议、目标、待决策和未知项不得与实现事实混写。
- 新决策写入[决策记录](docs/decisions/README.md)；阶段状态写入[路线图](docs/roadmap.md)。
