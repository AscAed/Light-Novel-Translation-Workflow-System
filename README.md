# AI 轻小说翻译工作流

## 项目状态

> 项目翻译通过 `scripts/run_kakuyomu_workflow.py` 创建活动 run 并启动流水线；直接运行 `pipeline.py --project` 不属于受支持的项目翻译入口。试点当前尚无与来源匹配的 reviewed 全书概要和术语表，因此受审项目流程会失败关闭。

- 当前架构：Python CLI 通过来源 catalog、版本清单和 AI/人读双版索引追踪书籍输入；默认翻译正文来自项目 `RAWs_AI/`，来源归档保留溯源元数据。Kakuyomu 翻译由编排 CLI 执行，计划、结构化审阅、知识审核、run 草稿和正式发布各有独立门禁。详见[架构与边界](docs/architecture.md)与[翻译流程](docs/translation-workflow.md)。
- 当前试点：88 话计划已绑定 AI 与人读索引；计划审阅模板中的 264 项决定仍为 pending，尚无匹配审批回执或 reviewed 全书知识。用户抽查了两版的部分单话和合集文件，未见明显问题；该报告不代表全量验收，记录见[开发与验证](docs/development.md#2026-11-19-人类版与-ai-版原文抽样核实)。
- 当前验证：当前非 E2E 回归 666 项运行、662 项通过、4 项因非提升进程的符号链接权限和 Windows FIFO 能力跳过；提升权限后安全路径模块 11 项运行、10 项通过，3 个符号链接用例均通过，1 项 FIFO 用例跳过；本地 mock E2E 7 项通过（201.455 秒）；试点 HTML 回放 88/88 验证通过。未调用真实 Provider、未验收翻译质量或线上部署。详见[开发与验证](docs/development.md#2026-11-19-审核决定并发与人读版身份绑定修复)。
- 下一步与限制：真实试点需先完成人工映射/双版本验收、生成审批回执并审核全书知识，再按授权条件开展 Provider 试译。完整路线与验收项见[项目现状](docs/project-status.md)、[路线图](docs/roadmap.md)及[实施目标](docs/end-to-end-workflow-target.md)。
- 决策 D-11 记录逐章恢复事务的保证边界，见[决策记录](docs/decisions/README.md)。来源采集、知识治理和 EPUB/Notion 仍按各自文档跟踪。
- 当前产品目标为日语轻小说译成中文；多语言、多文本类型属于长期目标，尚非当前实现能力。

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

python scripts/align_chapters.py --project <项目目录名>
python scripts/validate_tm_provenance.py --project <项目目录名>
python scripts/validate_knowledge_provenance.py --root <原文数据根目录> --manifest source_manifest.json --provenance <知识目录/KNOWLEDGE_PROVENANCE_draft.json>
python scripts/ingest_kakuyomu_pages.py --source-root <catalog目录> --catalog <catalog.json> --output-root <原文数据根目录>
python scripts/ingest_kakuyomu_pages.py --source-root <原文数据根目录> --work-url <作品主页URL> --output-root <原文数据根目录>
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog source_catalog.discovered.json --translation-root <译文数据根目录> --manifest source_manifest.json --plan-only --plan-output projects\<项目名>\Workflow\Plans\translation-plan.json
python scripts/prepare_translation_plan_review.py --plan <计划文件.json> --human-index <人读根>\SOURCE_MAP.json --output <计划审阅.json>
python scripts/approve_translation_plan.py --plan <计划文件.json> --review <计划审阅.json> --human-index <人读根>\SOURCE_MAP.json --receipt <审批回执.json> --reviewer <审核者标签>
python scripts/run_kakuyomu_workflow.py --source-root <原文数据根目录> --catalog source_catalog.discovered.json --translation-root <译文数据根目录> --config <项目配置.json> --approval-receipt projects\<项目名>\Workflow\Approvals\translation-plan-receipt.json
python scripts/export_book_bundles.py --source-root <SourceArchive> --catalog <catalog.json> --checkpoint <checkpoint.json> --human-root <生肉> --ai-root <RAWs_AI>
python scripts/prepare_translation_review.py --run-directory <Workflow\Runs\<run_id>>
python scripts/publish_reviewed_translation.py --run-directory <Workflow\Runs\<run_id>> --episode-id <episode-id> --review <review.json>
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --create-template review_receipt.json
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review <回执文件名> --output Glossary_reviewed.json
python tests/run_tests.py
```

Kakuyomu 页面导入和依赖安装会访问外网，运行前需在同一 PowerShell 会话中设置仓库要求的代理环境变量。配置模式和验证限制见[开发与验证](docs/development.md)。仓库没有依赖锁文件、CI 配置或部署清单；安装依赖不代表真实模型端点或外部部署已验证。

`run_kakuyomu_workflow.py --plan-only` 默认只读取已有 catalog、manifest 和目标目录并将计划写到 stdout，不联网、不调用 Provider、不写文件、不输出章节正文。显式使用 `--plan-output` 时会在 `SourceArchive/` 之外排他新建计划文件；项目内计划放在 `Workflow/Plans/`，回执放在 `Workflow/Approvals/`。AI 版计划必须先生成并完成人读映射、AI 版和人读版的结构化审阅，再用 `--review` 与 `--human-index` 创建 schema v2 回执；不带这两个参数的 schema v1 回执仅保留旧流程兼容，不满足 AI 版计划的当前审阅要求。计划和回执 CLI 均拒绝把工作流文件写入计划绑定的来源归档根。经 Kakuyomu 编排入口执行翻译时，必须通过 `--approval-receipt` 提交与当前源版本及映射一致的回执。回执未签名，审核者标签是调用者声明，不提供身份认证。稳定映射未变化时可用原回执续跑，但运行时仍会核验现有译文与 TM 的一致性。详细流程见[翻译流程](docs/translation-workflow.md#映射预览与人工核验)。

## 维护约定

- 修改代码或行为时，同步更新受影响的事实文档和验证证据。
- 只将可由当前源代码、配置、测试或 Git 状态支持的内容标为“已实现/已验证”。
- 建议、目标、待决策和未知项不得与实现事实混写。
- 新决策写入[决策记录](docs/decisions/README.md)；阶段状态写入[路线图](docs/roadmap.md)。
