# 2026-11-21 项目自检

## 基线与范围

- checkout：`codex/translation-workflow-audit-20261117`，HEAD `3c2f6c62c3e01bc99c3d538a5c6c2e49b2989fec`。
- 代码验证基线：`c1d140d`。`c1d140d..3c2f6c6` 仅包含 `README.md` 与 `docs/development.md` 两个 Markdown 文件，因此其后代码未变。
- 证据来源：当前仓库文件/配置、试点审阅 JSON 的非正文元数据、本地测试和依赖命令记录、PR #71 当前 GitHub 状态。审计不读取密钥、API profile 值或小说正文；未调用真实 Provider。
- 工作区原有未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 保持不读、不改、不提交。
- 本报告是该 checkout 的状态快照，不是对其他分支、平台、Python 版本、真实服务或线上部署的认证。
- 本报告最初覆盖基线与其后的记录有时间差；当前工作树复核截至 2026-11-21，下面覆盖矩阵按最新可验证状态更新。测试、静态检查和安全扫描的本轮结果及边界见[当前工作树综合自检](../development.md#2026-11-21-当前工作树综合自检)。

优先级含义：`P0` 阻止本试点真实执行或验收；`P1` 在启用真实服务/合并交付前需处理或明确接受；`P2` 可维护性、可复现性或发布准备风险；`P3` 已知平台边界或当前无需动作。状态词遵循仓库 [`AGENTS.md`](../../AGENTS.md)。

## 覆盖矩阵

| 范围 | 状态 | 结论与证据 |
| --- | --- | --- |
| 架构与模块 | `部分实现` | 当前交付是本地 Python CLI；来源/版本管理、AI/人读版本、知识治理、Kakuyomu 编排、run 草稿、审校与受控发布的职责和调用边界见[架构与边界](../architecture.md)。多语言、多文本类型、独立服务和 Web UI 不是当前已实现能力。 |
| 翻译流程 | `部分实现` | K0–K4 的若干流程在当前代码中已有本地实现和合成验证；K4 终审、返工、复审不能证明语义正确、审核独立或“信达雅”实际达标。目标与代码现状分别见[翻译流程](../translation-workflow.md)和[全书到单话目标](../end-to-end-workflow-target.md)。 |
| 依赖与环境 | `已验证` / `部分实现` | 当前 Windows 虚拟环境为 Python 3.14.7；`pip check` 无冲突，`pip-audit` 未发现已知漏洞。五项直接依赖均有代码/测试使用点；未发现可安全删除的直接依赖。`requirements.txt` 未锁定，仓库没有依赖锁文件；仅安装工具 `pip` 和 `google-genai` 的传递依赖 `tenacity` 有较新版本，本轮未升级。详细命令和范围见[依赖复查](../development.md#2026-11-21-依赖与漏洞公告复查)。 |
| 配置与凭据 | `未验证` | 项目配置和数据授权规则有文档与合成测试；当前本机 API profile、凭据、端点可达性、账号权限、预算及实际模型兼容性没有在本次审计中验证。不得以 `.env.example`、静态预检或历史配置快照代替。见[模型与 API 配置方案](../model-provider-configuration-plan.md)及[安全记录](../security-notes.md)。 |
| 构建与打包 | `未知` | 仓库当前以 Python 源码/脚本运行；本次文件盘点未发现 `pyproject.toml`、`setup.py`、`setup.cfg`、wheel 构建配置或正式打包产物。没有已确认的打包发布流程。 |
| 测试 | `已验证` | 当前工作树非 E2E 回归为 816 项运行、5 项因 Windows 能力跳过、0 项失败；loopback mock E2E 7 项通过。当前工作树详细验证见[综合自检](../development.md#2026-11-21-当前工作树综合自检)；较早 checkout 上的管理员 symlink 复跑仍只适用于其记录的代码状态。 |
| 安全 | `部分实现` | 当前虚拟环境 `pip-audit` 未报告已知漏洞；Codex Security 标准只读扫描未报告发现，但仅审查 4 个非项目数据源码面。路径越界/符号链接用例有旧 checkout 上的本地和管理员验证。它们不是全仓库渗透测试、真实 Provider 安全评估或部署安全认证。原文、译文、凭据及受保护 freshness 文件未被本次扫描读取。 |
| 兼容性 | `部分实现` | 仅能确认当前 Windows + Python 3.14.7 虚拟环境及其依赖组合通过记录的本地测试。其他 Python 版本、操作系统、API endpoint/model 与外部客户端协议没有矩阵或真实端点验证。 |
| CI 与部署 | `部分实现` / `未验证` | run `44815736864` 已验证 Ubuntu/Windows Python 3.14 依赖检查、非 E2E 单测及 loopback mock E2E 全通过。矩阵仅覆盖这两个 runner 和 Python 3.14；仓库无 Docker/Compose 或部署清单，产品仍为本地 CLI，没有已验证线上服务。PR #71 的 mergeable 状态不代表人类审批、真实服务或项目验收。 |
| 试点数据与人审 | `部分实现` | 当前计划的 88 话 mapping、来源 lineage、AI/人读版字节与 profile 结构审阅均已通过，并有绑定计划与 review 摘要的 schema v2 回执；原始 pending 模板是历史/备选材料。该回执不证明语义保真或视觉验收。`Workflow/Runs/`、reviewed 全书知识、正式译文和真实 Provider 试译仍不存在/未验证。详见[K5 门禁复核](../project-status.md#2026-11-21-k5-门禁复核)。 |

## 优先问题

| ID | 优先级 | 发现与影响 | 后续动作/责任 |
| --- | --- | --- | --- |
| AUD-01 | `P0`（本报告基线） | 截至本报告 `3c2f6c6` 基线，88 话三类审阅共 264 项 `pending`，没有匹配回执或 reviewed 全书知识。后续 AI 结构审阅已解决映射、来源 lineage、双版本字节/profile 的结构门禁；尚缺 reviewed 全书知识及其语义审核。 | 当时的结构审阅阻塞已由后续记录更新；当前动作是生成并审核与当前 bundle 绑定的全书知识。不得要求用户重复完成可由工具确定性验证的 264 项结构清单。 |
| AUD-02 | `P0` | 没有真实 Provider 试译、AI 审核效果或经验证的成本/延迟数据；endpoint、模型 ID、账号权限和预算状态未知。mock 测试不能证明实际翻译可执行或合格。 | 完成当前 bundle 绑定的全书知识审核后，由凭据所有者无密钥输出地核验路由、数据授权与预算，再执行获准单话试译；用证据评估 AI 审核与返工是否满足用户标准，只有不确定或超出 AI 可判定范围时才升级用户。不要在文档或提交中记录秘密。 |
| AUD-03 | `P2` | `44815736864` 已使 Ubuntu/Windows Python 3.14 hosted matrix 全绿；仍无其他 Python/OS 矩阵，PR #71 也无正式 review approval。 | 人类决定是否为本地 CLI 建立分支保护并完成 PR 审查；支持范围扩大前补充相应矩阵。不把单一矩阵当作真实 Provider、部署或质量验收。 |
| AUD-04 | `P2` | 直接依赖未锁版本，传递依赖和安装结果会随时间变化；当前单一 Windows/Python 环境不能代表其他支持平台。 | 需要人类决定支持的 Python/OS 范围和是否采用锁文件；再选择与现有安装方式一致的最小实现并验证干净环境重建。 |
| AUD-05 | `P2` | 没有可验证的打包或部署目标。若产品继续作为本地 CLI，这不是当前功能缺陷；若要求 Web/服务化交付，则运行方式、数据持久化、凭据管理和运维边界均需先决策。 | 在增加部署工作前，由产品负责人确认交付形态；当前不引入未经选择的容器、云服务或 Agent 平台。 |
| AUD-06 | `P3` | Windows FIFO 安全用例因平台不支持 `os.mkfifo` 跳过；普通权限下 symlink 用例因 `WinError 1314` 跳过，但授权管理员复跑的三个 symlink 用例均通过。 | 记录为平台能力边界；如需要跨平台 FIFO 等价覆盖，再为目标平台设计独立 fixture。 |

## 已处理与剩余

- PR #71 当前可见的审查线程均已解决或标记过时；相关来源绑定、恢复、reviewed glossary、tokenizer truncation、发布和性能问题的修复及回归按日期记在[开发与验证](../development.md)。
- 本审计没有发现需要删除的直接依赖或当前环境已知漏洞，因此没有升级/移除依赖；依赖漂移由 AUD-04 跟踪。
- 本审计没有修改业务代码、依赖声明或运行配置。自检结论不能写成“没有任何遗漏”：真实 Provider、完整人审、跨平台兼容和部署仍缺乏证据。
- README/项目导航入口见[README](../../README.md)。路线图任务与依赖关系见[路线图](../roadmap.md)；该路线图保持目标/计划与当前实现状态分离。

## 后续状态更新

- `已验证` 截至本次综合自检，当前工作树完整非 E2E 回归为 816 项运行、5 项 Windows 能力跳过、0 失败；mock E2E 为 7 项通过。Python compileall、workflow YAML 语法、3 个 CLI `--help`、26 份 Markdown 的 458 个本地链接目标及 `git diff --check` 通过。当前 Windows Python 3.14.7 环境 `pip check` 无冲突，`pip-audit` 未报告已知漏洞。
- `部分实现` Codex Security 标准只读扫描未报告发现（scan `9e326075-a4ad-459c-8888-e3f2bf1a79f4`），但排除项目数据、凭据和受保护文件，且没有扫描真实运行服务或部署；不能据此声明生产安全已验证。
- `未验证` 本地 API profile/凭据、真实 Provider 端点与授权、预算、试点语义质量、人工验收及生产部署仍无证据。具体范围见[综合自检记录](../development.md#2026-11-21-当前工作树综合自检)。

- `已验证` 本报告原始覆盖基线为 `3c2f6c6`；其 AUD-01 中“264 项待审、无匹配回执”描述的是该时点，不能作为当前状态。随后在 HEAD `b0a4f3d24fc5809e133a824ff81d03d7ea773a82` 对当前计划完成 AI 结构审阅：mapping、来源 lineage、AI/人读版字节与 profile 各 88 项通过、0 issue，并生成与计划及 review 摘要绑定的 schema v2 审批回执。过程和边界见[项目现状 K5 复核](../project-status.md#2026-11-21-k5-门禁复核)及[开发记录](../development.md#2026-11-21-k5-codex-ai-结构审阅与计划审批)。
- 该结构审阅不认证审核者身份，不证明正文语义保真、翻译质量、读者视觉效果，也不证明站点公开目录范围外的完整性；旧 `.human-review.json` 的 `pending` 值仍保留为历史/备选材料，不是当前结构门禁阻塞。
- `未验证` AUD-02 所述真实 Provider 路由、凭据/profile、账号权限、预算及真实翻译质量仍需在受控试点前核验；当前也没有与 bundle 身份绑定并完成审核的全书知识、正式 run 或译文。先完成全书知识构建/审核，再无密钥输出地核验实际 Provider 配置，满足条件后执行受控第 1 话试译。若证据不足，升级需要判断的具体事项，不把结构回执扩大解释为真实验收。
- 本报告覆盖其基线 `3c2f6c6`。2026-11-21 随后新增 GitHub Actions Ubuntu/Windows Python 3.14 workflow 与统一非 E2E 单测入口。提交 `36881d8` 的 run `44815736864` 在两个 runner 上均通过依赖检查、非 E2E 单测和 loopback mock E2E，细节见[持续集成](../development.md#持续集成)。
- `已验证` 当前 Windows/Python 3.14.7 工作树运行 785 项非 E2E 测试，780 项通过、5 项因 Windows symlink/FIFO 能力跳过、0 失败；loopback mock E2E 7 项通过。`pip check`、YAML 语法、相关 runner/模块编译与 `git diff --check` 通过。
- `未验证` 其他 Python/OS 组合、真实 Provider/质量与部署；hosted matrix 仅证明提交 `36881d8` 在指定 Python 3.14 runner 上的自动化回归结果。
- 其余人工试点、真实 Provider/质量、依赖锁定以及是否建立分支保护等门槛不因 CI 配置而关闭。
- `已验证` 本次续接开始时 HEAD 为 `07d5a0334de945fb47bff5571c76efc703ca980c`；其前代码提交 `611805a93278b13fe24734922159d2b8b0be5c53` 新增 K3 正式润色响应契约失败事务回归：异常时不创建译文、不更新 TM，StageReport 记录 `polishing`。完整非 E2E 回归 788 项运行、783 项通过、5 项因 Windows symlink/FIFO 能力跳过；loopback mock E2E 7 项通过（209.754 秒）；`.venv` `pip check` 无依赖冲突。详细证据见[开发与验证](../development.md#2026-11-21-k3-正式润色失败事务门禁)。
- `已验证` hosted run `44832466495` 覆盖实现提交 `611805a93278b13fe24734922159d2b8b0be5c53`，run `44833281731` 覆盖随后纯文档提交 `07d5a0334de945fb47bff5571c76efc703ca980c`；两次 Ubuntu/Windows Python 3.14 job 均通过，CodeRabbit 为 `SKIPPED`。PR #71 仍为 `OPEN`、mergeable，但无正式 review decision，未合并。
- `用户报告` 人类版与 AI 版部分单话和合集抽样结果已记入[开发记录](../development.md#2026-11-21-用户报告的原文抽样核实)。抽查日期、样本清单及标准未知；不作为全量人工验收或 Codex 独立核实证据。
- `用户报告` `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 输出 `Ran 9 tests in 0.032s`、`OK (skipped=3)`。该结果未附 checkout/commit、跳过原因或可确认权限级别，不能据此判断符号链接权限问题是否解决，也不覆盖本审计中绑定当前基线的 11 项安全模块验证。
- 截至本报告原始复核时，未关闭项包括 88 话逐话结构审阅、计划审批回执、reviewed 全书知识、真实 Provider 受控试译与质量验收；后续结构审阅及回执状态见下方更新。部署形态仍未确认，依赖未锁定；本审计没有足够证据支持删除或升级直接依赖，也没有验证过的线上部署目标。
- `已实现` 提交 `180afdc` 为只读已发布译文新鲜度审计增加映射外 Markdown 扫描：未映射文件报告 `unindexed`，符号链接报告 `invalid`，枚举错误或超过 100,000 项报告 `unverified`；不跟随链接、不读取正文、不修改输出。该变更由 4 项新增回归覆盖。
- `已验证` 该提交的完整本地非 E2E 与 loopback mock E2E 结果，以及 hosted run `44841786744` 的 Ubuntu/Windows Python 3.14 结果，见[持续集成记录](../development.md#持续集成)与[I4 新鲜度回归记录](../development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)；CodeRabbit 跳过。
- `未验证` PR #71 仍为 `OPEN`、mergeable，但没有正式 review decision；最新 Codex 自动审查未能完成，不能作为通过或代码缺陷结论。该 PR 未合并。受保护的未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 未读取、暂存、修改或提交。
- `已验证`（较早状态快照）2026-11-21 对当时 K5 计划重新执行只读预检，88/88 来源有效且无计划问题；raw/AI/人类版及指定 AI book bundle 的字节/lineage 核验通过。该次检查时三类逐话审阅各 `pending=88`，未发现审批、run 或 reviewed 全书概要；之后的结构审阅与回执状态见本节前文。命令、摘要和边界见[只读门禁复核记录](../development.md#2026-11-21-k5-只读门禁复核)。
