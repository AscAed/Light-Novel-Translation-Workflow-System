# 2026-11-21 项目自检

## 基线与范围

- checkout：`codex/translation-workflow-audit-20261117`，HEAD `3c2f6c62c3e01bc99c3d538a5c6c2e49b2989fec`。
- 代码验证基线：`c1d140d`。`c1d140d..3c2f6c6` 仅包含 `README.md` 与 `docs/development.md` 两个 Markdown 文件，因此其后代码未变。
- 证据来源：当前仓库文件/配置、试点审阅 JSON 的非正文元数据、本地测试和依赖命令记录、PR #71 当前 GitHub 状态。审计不读取密钥、API profile 值或小说正文；未调用真实 Provider。
- 工作区原有未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 保持不读、不改、不提交。
- 本报告是该 checkout 的状态快照，不是对其他分支、平台、Python 版本、真实服务或线上部署的认证。

优先级含义：`P0` 阻止本试点真实执行或验收；`P1` 在启用真实服务/合并交付前需处理或明确接受；`P2` 可维护性、可复现性或发布准备风险；`P3` 已知平台边界或当前无需动作。状态词遵循仓库 [`AGENTS.md`](../../AGENTS.md)。

## 覆盖矩阵

| 范围 | 状态 | 结论与证据 |
| --- | --- | --- |
| 架构与模块 | `部分实现` | 当前交付是本地 Python CLI；来源/版本管理、AI/人读版本、知识治理、Kakuyomu 编排、run 草稿、审校与受控发布的职责和调用边界见[架构与边界](../architecture.md)。多语言、多文本类型、独立服务和 Web UI 不是当前已实现能力。 |
| 翻译流程 | `部分实现` | K0–K4 的若干流程在当前代码中已有本地实现和合成验证；K4 终审、返工、复审不能证明语义正确、审核独立或“信达雅”实际达标。目标与代码现状分别见[翻译流程](../translation-workflow.md)和[全书到单话目标](../end-to-end-workflow-target.md)。 |
| 依赖与环境 | `已验证` / `部分实现` | 当前 Windows 虚拟环境为 Python 3.14.7；`pip check` 无冲突，`pip-audit` 未发现已知漏洞。五项直接依赖均有代码/测试使用点；未发现可安全删除的直接依赖。`requirements.txt` 未锁定，仓库没有依赖锁文件；仅安装工具 `pip` 和 `google-genai` 的传递依赖 `tenacity` 有较新版本，本轮未升级。详细命令和范围见[依赖复查](../development.md#2026-11-21-依赖与漏洞公告复查)。 |
| 配置与凭据 | `未验证` | 项目配置和数据授权规则有文档与合成测试；当前本机 API profile、凭据、端点可达性、账号权限、预算及实际模型兼容性没有在本次审计中验证。不得以 `.env.example`、静态预检或历史配置快照代替。见[模型与 API 配置方案](../model-provider-configuration-plan.md)及[安全记录](../security-notes.md)。 |
| 构建与打包 | `未知` | 仓库当前以 Python 源码/脚本运行；本次文件盘点未发现 `pyproject.toml`、`setup.py`、`setup.cfg`、wheel 构建配置或正式打包产物。没有已确认的打包发布流程。 |
| 测试 | `已验证` | 代码基线 `c1d140d` 的非 E2E 回归为 784 项运行、780 项通过、4 项跳过、0 项失败；loopback mock E2E 7 项通过。普通权限安全路径模块 11 项中 7 项通过、4 项跳过；管理员复跑 11 项中 10 项通过、仅 FIFO 因 Windows 不支持跳过，3 项 symlink 均通过。测试范围、命令和 fixture 限制见[开发与验证](../development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)。 |
| 安全 | `部分实现` | 当前虚拟环境漏洞扫描无已知发现；限定 PR 差异扫描覆盖 9 个文件、无可报告发现；路径越界/符号链接用例有本地和管理员验证。它们不是全仓库渗透测试、真实 Provider 安全评估或部署安全认证。原文和译文未被本次自检读取。 |
| 兼容性 | `部分实现` | 仅能确认当前 Windows + Python 3.14.7 虚拟环境及其依赖组合通过记录的本地测试。其他 Python 版本、操作系统、API endpoint/model 与外部客户端协议没有矩阵或真实端点验证。 |
| CI 与部署 | `部分实现` / `未验证` | 已添加 Ubuntu/Windows Python 3.14 CI，前四次 hosted run 的 Ubuntu job 通过、Windows 单测逐步暴露编码与路径断言兼容问题；当前修正 head 的 hosted rerun 尚待结果。仓库无 Docker/Compose 或部署清单，产品仍为本地 CLI，没有已验证线上服务。PR #71 的 mergeable 状态不代表 CI 或项目验收。 |
| 试点数据与人审 | `部分实现` | 当前计划含 88 话；映射、AI 版、人读版决定各 `pending=88`。`Workflow/Approvals/`、`Workflow/Runs/` 和 `STORY_SUMMARY_reviewed.json` 均不存在。用户报告部分单话及合集抽样未见明显问题，但样本清单/标准未知，不能替代逐话审阅或全书验收。详见[K5 试点门禁](../project-status.md#2026-11-20-k5-试点门禁复核)。 |

## 优先问题

| ID | 优先级 | 发现与影响 | 后续动作/责任 |
| --- | --- | --- | --- |
| AUD-01 | `P0` | 88 话三类审阅仍共 264 项 `pending`，没有与当前计划匹配的批准回执或 reviewed 全书知识。正式试点应按门禁失败关闭，不能生成真实翻译验收结论。 | 需要有权限的人逐话确认映射、AI 清洗版和人读版，生成匹配回执并审核当前 bundle 绑定的全书知识。 |
| AUD-02 | `P0` | 没有真实 Provider 试译、人工语义质量验收或经验证的成本/延迟数据；endpoint、模型 ID、账号权限和预算状态未知。mock 测试不能证明实际翻译可执行或合格。 | 完成 AUD-01 后，由凭据所有者核验路由、数据授权与预算，再执行获准单话试译和人工验收；不要在文档或提交中记录秘密。 |
| AUD-03 | `P1` | CI 工作流已建立，但前四次 hosted run 均有 Windows 单测失败；本地已修复并通过，当前修正提交的 hosted matrix 尚未完成。PR #71 无正式 review approval。 | 完成当前 head 的 Ubuntu/Windows hosted rerun，处理任何剩余失败；人类仍需决定是否为该 CLI 建立分支保护，不把 mergeable 状态当作验收。 |
| AUD-04 | `P2` | 直接依赖未锁版本，传递依赖和安装结果会随时间变化；当前单一 Windows/Python 环境不能代表其他支持平台。 | 需要人类决定支持的 Python/OS 范围和是否采用锁文件；再选择与现有安装方式一致的最小实现并验证干净环境重建。 |
| AUD-05 | `P2` | 没有可验证的打包或部署目标。若产品继续作为本地 CLI，这不是当前功能缺陷；若要求 Web/服务化交付，则运行方式、数据持久化、凭据管理和运维边界均需先决策。 | 在增加部署工作前，由产品负责人确认交付形态；当前不引入未经选择的容器、云服务或 Agent 平台。 |
| AUD-06 | `P3` | Windows FIFO 安全用例因平台不支持 `os.mkfifo` 跳过；普通权限下 symlink 用例因 `WinError 1314` 跳过，但授权管理员复跑的三个 symlink 用例均通过。 | 记录为平台能力边界；如需要跨平台 FIFO 等价覆盖，再为目标平台设计独立 fixture。 |

## 已处理与剩余

- PR #71 当前可见的审查线程均已解决或标记过时；相关来源绑定、恢复、reviewed glossary、tokenizer truncation、发布和性能问题的修复及回归按日期记在[开发与验证](../development.md)。
- 本审计没有发现需要删除的直接依赖或当前环境已知漏洞，因此没有升级/移除依赖；依赖漂移由 AUD-04 跟踪。
- 本审计没有修改业务代码、依赖声明或运行配置。自检结论不能写成“没有任何遗漏”：真实 Provider、完整人审、跨平台兼容和部署仍缺乏证据。
- README/项目导航入口见[README](../../README.md)。路线图任务与依赖关系见[路线图](../roadmap.md)；该路线图保持目标/计划与当前实现状态分离。

## 后续状态更新

- 本报告覆盖其基线 `3c2f6c6`。2026-11-21 随后新增 GitHub Actions Ubuntu/Windows Python 3.14 workflow 与统一非 E2E 单测入口。前四次 hosted run 的 Ubuntu job 通过，Windows 暴露 Python 默认控制台编码和临时目录短/长路径表示差异；当前工作树已修正已知断言，细节见[持续集成](../development.md#持续集成)。
- `已验证` 当前 Windows/Python 3.14.7 工作树运行 785 项非 E2E 测试，780 项通过、5 项因 Windows symlink/FIFO 能力跳过、0 失败；loopback mock E2E 7 项通过。`pip check`、YAML 语法、相关 runner/模块编译与 `git diff --check` 通过。
- `未验证` 当前修正提交的最终 GitHub Actions matrix 尚待复跑完成；本机及早期 Ubuntu job 结果不能代替当前 head Windows job 通过。
- 其余人工试点、真实 Provider/质量、依赖锁定以及是否建立分支保护等门槛不因 CI 配置而关闭。
