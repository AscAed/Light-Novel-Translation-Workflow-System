# 架构与边界

## 当前结构

```text
CLI
└── pipeline.py: Config / TranslationPipeline / UnifiedAgent
    ├── prompts/*.md: 阶段指令
    ├── rag_engine.py: 书籍上下文检索与记忆写入
    ├── projects/<project>/{生肉,熟肉,Knowledge}/: 输入、输出、知识数据
    └── providers: Sakura-compatible endpoint / DeepSeek-compatible endpoint / Gemini SDK

scripts/align_chapters.py -> 双语章节 -> 对齐段落 -> Gemini embeddings -> translation_memory.json
tests/run_tests.py -> tests/mock_server.py -> tests/test_e2e.py
```

该图仅描述仓库代码。没有证据表明存在独立服务、云部署、Web UI、Agent 编排平台或持续集成。

## 模块职责

| 模块 | 当前责任 | 主要输入/输出 |
| --- | --- | --- |
| `pipeline.py` | 配置解析、章节循环、阶段调用、输出保存 | Markdown 章节、项目知识文件、模型响应 |
| `rag_engine.py` | TM 相似检索、词条匹配、指导检索、TM 更新 | `Knowledge` 文件；查询上下文；写入 JSON TM |
| `scripts/align_chapters.py` | 对已有双语章节做段落对齐并生成嵌入 | `生肉/`、`熟肉/` -> `translation_memory.json` |
| `scripts/auto_extract_knowledge.py` | 实验性生成知识草稿 | 原文前几章 -> `Glossary_draft.json` 与摘要草稿 |
| `prompts/*.md` | 阶段角色的指令文本 | 被 `TranslationPipeline` 按路径读取 |
| `tests/` | Mock API 和本地行为测试 | 临时项目目录；无真实模型质量验证 |

## 当前阶段数据流

1. `Config.load_config` 从项目参数、JSON 配置或环境变量解析路径；代码还会尝试读取仓库根目录 `.env`。
2. `TranslationPipeline` 读取作品信息、概要，并创建 `RAGEngine`。
3. 每章检索指导、TM、词条和概要上下文。
4. 按阶段调用上下文标注、初译、逻辑校对、润色。
5. 校验各阶段段落数组与原文段落数量一致，再创建译文文件并按数组位置形成段落对更新 TM。TM 以同目录临时文件加原子替换写入；嵌入失败时保留词对但不写入伪造向量。
6. `align_chapters.py` 通过章节子路径校验读取原译文件；锚点不匹配时使用 Gale-Church 对齐，验证 embedding 数量后原子更新 TM。

## 外部集成与约束

- 源码默认初译模型名 `sakura-14b`，Sakura base URL 为 `http://127.0.0.1:6006/v1`。
- 源码默认校对/润色模型名分别为 `deepseek-v4-flash`、`deepseek-v4-pro`；base URL 默认 `https://api.deepseek.com/v1`。
- `UnifiedAgent` 默认不跨 Provider 回退。仅显式设置 `ENABLE_GEMINI_FALLBACK=true` 时，普通调用异常会将相同请求发送至 Gemini；Provider 内容拦截为终止状态，不触发跨 Provider 回退。Gemini 请求未显式放宽安全阈值。模型可用性和服务端版本未验证。
- `rag_engine.py` 与对齐脚本当前请求 `gemini-embedding-2`；本地 mock 仅用于测试，不能证明真实模型可用。
- 翻译和对齐章节读取拒绝直接子文件符号链接并限制为配置目录下的文件；知识提取脚本也使用该读取校验。TM 更新采用原子替换；知识草稿使用排他新建。显式配置根目录仍由操作者负责，跨进程并发写入未实现。
- 项目名解析会检查已解析路径仍位于 `projects/` 下；显式 JSON 配置路径不存在时立即报错。JSON 配置中的目录仍可由操作者显式指定到仓库外。
- README 曾描述的 Sakura/DeepSeek/Gemini 型号、`DEVELOPMENT_PLAN.md` 的旧模型栈与现行源码不完全一致。以源码默认值为实现事实，以真实账户/服务实测为可用性事实。
- 项目级数据目录 `projects/*` 默认被忽略，仅示例项目例外。真实项目知识、译文和 TM 通常不在版本控制中。
- 当前 JSON 文件适用于现有单机代码路径；并发写入、崩溃恢复、规模化查询能力未验证。

## 目标边界（建议，非现状）

- 把工作流阶段契约与 Provider/API 适配边界分开，使语言、文本类型和模型替换不改变核心流程。
- 把书籍级知识与通用语言资源分开；每条可复用知识携带来源、状态和审核信息。
- 将最终章节完整性校验定义为显式门禁，而不是只依赖提示词遵循。
- 在引入服务、数据库、队列或 UI 前，先由路线图定义需求和验收；本仓库未选定上述技术。
