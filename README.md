# AI 轻小说翻译工作流

## 项目状态

- 状态基准日：2026-11-13。
- 当前实现：Python CLI 翻译流水线、RAG 检索模块、章节对齐脚本和 mock 测试。
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
| [决策记录](docs/decisions/README.md) | 已确认决策与待决事项索引 |
| [本地凭据风险记录](docs/security-notes.md) | 凭据暴露边界与需人工处理事项 |

## 现有命令

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python pipeline.py --project <项目目录名>
python scripts/align_chapters.py --project <项目目录名>
python tests/run_tests.py
```

配置模式和验证限制见[开发与验证](docs/development.md)。仓库没有依赖锁文件、CI 配置或部署清单；安装依赖不代表真实模型端点或外部部署已验证。

## 维护约定

- 修改代码或行为时，同步更新受影响的事实文档和验证证据。
- 只将可由当前源代码、配置、测试或 Git 状态支持的内容标为“已实现/已验证”。
- 建议、目标、待决策和未知项不得与实现事实混写。
- 新决策写入[决策记录](docs/decisions/README.md)；阶段状态写入[路线图](docs/roadmap.md)。
