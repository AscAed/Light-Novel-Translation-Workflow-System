# AI 轻小说翻译工作流

## 项目状态

- 当前产品范围是日语轻小说译成中文；多语言、多文本类型仍是长期目标。
- 当前交付形态是本地 Python CLI，试点工作流包含来源版本管理、AI/人读版本、计划与知识审核、逐话翻译审校及受控发布。模块状态与证据见[项目现状](docs/project-status.md)和[架构与边界](docs/architecture.md)。
- 当前 88 话的结构映射、来源 lineage 与双版本机器审阅已有匹配回执；2026-11-22 K5.1 来源、bundle 与计划复核仍为 88/88。K5.2 起尚不能继续：缺少可验证匹配的 tokenizer/model/context/预算和当前 route/allowlist 核验；因此没有 bundle-bound reviewed 全书知识或正式翻译 run。具体输入要求见[项目现状](docs/project-status.md#2026-11-22-k5-输入复核与当前阻塞)和[当前续接交接](docs/handoffs/2026-11-15-translation-workflow.md)。元数据 M0 来源盘点、M1 候选导入/预算预检和受控执行器、M2 版本化人工语义检查、M3 create-only 本地批准 artifact，以及 M4 EPUB 标题消费和逐字段 freshness 门禁均有合成验证；M1 未运行真实试点生成，费用估算不是服务商硬上限。M2 rubric 仍是未认证人工声明，不等于 AI 审核或获准样本质量验收；M3 未生成真实试点 artifact。字段级 freshness 目前仅供 EPUB 消费，M1/M2/M3 写入仍要求完整计划 freshness；Notion/UI 消费未实现。真实 Provider 单话试译、真实 EPUB 和质量验收仍待完成。结构回执不证明逐段语义质量或阅读器视觉效果。最新验证结果和限制集中记录在[开发与验证](docs/development.md)；本地测试不代表真实服务、语义质量或部署已通过。
- GitHub Actions 已配置 Ubuntu/Windows Python 3.14 回归；以具体 commit 的 hosted check 为准，首次执行及依赖锁定状态见[开发与验证](docs/development.md#持续集成)。
- 通用阶段、角色职责和质量门禁见[翻译流程](docs/translation-workflow.md)；阶段依赖与验收标准见[路线图](docs/roadmap.md)。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Codex/Agent 工作约束、验证与文档维护规则 |
| [项目现状](docs/project-status.md) | 以仓库证据记录已实现、部分实现、计划和未知 |
| [项目自检](docs/audits/2026-11-21-project-self-audit.md) | 当前审计范围、风险优先级、证据和未验收门槛 |
| [架构与边界](docs/architecture.md) | 当前模块、数据流、接口与目标边界 |
| [翻译流程](docs/translation-workflow.md) | 当前流水线阶段、角色职责、质量要求 |
| [知识库治理](docs/knowledge-governance.md) | 当前知识数据与建议的审核、写入规则 |
| [全书到单话目标](docs/end-to-end-workflow-target.md) | 目标流程、分阶段设计和未实现验收条件 |
| [开发与验证](docs/development.md) | 环境、配置、命令、测试事实和限制 |
| [路线图](docs/roadmap.md) | 分阶段目标、依赖、交付物与验收条件 |
| [统一交互 CLI/TUI 开发计划](docs/unified-interactive-cli-plan.md) | 统一本地入口、菜单/命令路由、脚本接入策略与分阶段验收 |
| [试点映射人工审阅](docs/handoffs/2026-11-16-pilot-plan-review.md) | 88 话计划摘要、人工核对项及尚未批准的边界 |
| [模型与 API 配置方案](docs/model-provider-configuration-plan.md) | 模型候选、职责分配、配置交互、安全边界与实施计划（计划，未经实测） |
| [原文采集与成果归档方案](docs/source-ingestion-and-publication-plan.md) | 来源许可、原文版本、翻译衔接、EPUB 与 Notion 工作包（部分原型，其余为计划） |
| [当前续接交接](docs/handoffs/2026-11-15-translation-workflow.md) | 最近的阶段状态、验证结果、合并记录及可直接执行的后续步骤 |
| [历史续接交接](docs/handoffs/2026-11-14-translation-workflow.md) | 历次实现与验证的历史快照；现状以项目现状和路线图为准 |
| [决策记录](docs/decisions/README.md) | 已确认决策与待决事项索引 |
| [本地凭据风险记录](docs/security-notes.md) | 凭据暴露边界与需人工处理事项 |

环境准备、代理要求、配置项、工作流命令及测试入口以[开发与验证](docs/development.md)为准；命令语义和审核门禁以[翻译流程](docs/translation-workflow.md)为准。

## 维护约定

- 修改代码或行为时，同步更新受影响的事实文档和验证证据。
- 只将可由当前源代码、配置、测试或 Git 状态支持的内容标为“已实现/已验证”。
- 建议、目标、待决策和未知项不得与实现事实混写。
- 新决策写入[决策记录](docs/decisions/README.md)；阶段状态写入[路线图](docs/roadmap.md)。
