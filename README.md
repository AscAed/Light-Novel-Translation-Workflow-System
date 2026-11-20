# AI 轻小说翻译工作流

## 项目状态

> 项目翻译通过 `scripts/run_kakuyomu_workflow.py` 创建活动 run 并启动流水线；直接运行 `pipeline.py --project` 不属于受支持的项目翻译入口。试点当前尚无与来源匹配的 reviewed 全书概要和术语表，因此受审项目流程会失败关闭。

- 当前架构：Python CLI 通过来源 catalog、版本清单和 AI/人读双版索引追踪书籍输入；默认翻译正文来自项目 `RAWs_AI/`，来源归档保留溯源元数据。Kakuyomu 翻译由编排 CLI 执行，计划、结构化审阅、知识审核、run 草稿和正式发布各有独立门禁。详见[架构与边界](docs/architecture.md)与[翻译流程](docs/translation-workflow.md)。
- 当前试点：2026-11-20 只读复核确认当前计划 `ready_for_review`、88/88 来源有效，按计划绑定的 raw-html catalog 做 plan-only 及双版本一致性验证均通过；但模板 3 类决定各 88 项仍 pending，尚无匹配审批回执或 reviewed 全书概要。用户于 2026-11-21 报告人类版与 AI 版的部分单话及合集抽样未发现明显问题；这不代表全量验收，实际检查日期及样本清单未提供。详见[抽样核实记录](docs/development.md#2026-11-21-用户报告的原文抽样核实)。详情见[开发记录](docs/development.md#2026-11-20-k5-试点门禁复核)及[项目现状](docs/project-status.md#2026-11-20-k5-试点门禁复核)。
- 当前验证：2026-11-21 最终工作树完整非 E2E 回归 784 项运行、780 项通过、4 项 Windows 能力跳过、0 失败；loopback mock E2E 7 项通过（229.117 秒）。安全路径模块普通权限 11 项运行、7 项通过、4 项跳过；管理员复跑 11 项运行、10 项通过，仅 FIFO 因 Windows 能力限制跳过，3 项 symlink 全部通过；`pip check` 无依赖冲突。未调用真实 Provider、未验收翻译质量或部署。详见[最新开发记录](docs/development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)。
- 当前 K4：`scripts/run_ai_translation_workflow.py` 显式运行或续接单话的双次 AI 终审、有限定向返工、复审和通过后发布；I4 freshness snapshot 现可只读核验发布回执、历史来源与当前译文字节，并识别 stale 译文。若项目采集时当前映射缺失但发现已有 run/译文，会记录聚合未核验状态而不误报逐话通过。同一话目由 run 内异步文件锁串行，重复并发调用复用已落盘评估 sidecar/报告/候选；单次评估完成后原子保存，进程重启只请求缺失评估。终审只在两次评估均通过信/达/雅、八项检查和定性收敛门时发布；返工由 `PROOFREAD_MODEL` 仅修订 findings 指向的段落，并将不可变候选写入 run。默认返工预算 2；耗尽后须由人工增加预算才能继续，或走人工 checklist 放行当前候选。策略、来源、候选、报告和路由摘要互相绑定。该实现只经合成测试/mock，未验证语义正确性或模型独立性；Provider 响应后、评估 sidecar 落盘前仍有重复计费窗口。
- 下一步与限制：先完成人审模板的映射/双版本决定和计划回执，再审核当前 bundle 绑定的全书知识；之后由凭据所有者核验 Provider 路由、授权和预算，执行获准单话试译与质量验收。定向修订仍依赖 AI findings，无法从结构契约证明它修复了真实问题；“none/low”是定性收敛代理，不是收益计算；策略由操作者提供，不是项目核准 taxonomy。本机 API profile 未读取，TM embedding 候选仍须人工审核后切换。当前交付为 CLI，无部署服务。详见[项目现状](docs/project-status.md)、[路线图](docs/roadmap.md)、[开发记录](docs/development.md)。
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

批量配置 OpenAI 兼容 API 并在同一进程运行现有工作流：

```powershell
.\.venv\Scripts\python.exe scripts\configure_api_pool.py -- <run_kakuyomu_workflow.py 的参数>
```

向导逐项说明初译、校对/知识抽取和润色职责，可选绑定使用不同端点和模型的终审角色；另支持多个生成 API、逐职责分配及一个临时错误备用 API。embedding 可独立选择 Gemini 或 OpenAI-compatible 接口，并单独确认 `source_text` 授权。API 池 v1 profile 经确认迁移到 v2；保存含终审角色的新配置使用 v3。显式运行终审 CLI 才会发送原文与候选；自动发布仅发生在双评估通过并通过既有发布门禁后。可选择保存到当前 Windows 用户的凭据管理器；不保存时只在当前进程有效。无参数运行可配置和保存，但不执行翻译；现有来源、知识及发布审核门禁仍然有效。详见[模型与 API 配置方案](docs/model-provider-configuration-plan.md)。

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
