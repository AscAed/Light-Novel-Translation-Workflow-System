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
scripts/validate_tm_provenance.py -> translation_memory.json + 生肉/熟肉 -> 只读核验
tests/run_tests.py -> tests/mock_server.py -> tests/test_e2e.py
```

该图仅描述仓库代码。没有证据表明存在独立服务、云部署、Web UI、Agent 编排平台或持续集成。

具体站点的原文采集适配器、Notion 同步和 EPUB 构建尚未实现；候选分层与工作包见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。`source_manifest.py` 提供本地 JSON 版本清单校验/追加及显式路径字节 SHA-256 核验；`source_ingestion.py` 提供注入适配器的分页/续传/归档编排核心，以及仅读取显式 catalog 列出文件的本地 adapter，但不发起 HTTP 请求或解析平台页面。它们尚未接入翻译流水线。

显式 JSON 的 `CHAPTER_MAP` 为嵌套项目提供逐章映射：原文根目录相对路径、译文根目录相对路径和唯一 TM 键由操作者逐项指定。流水线、对齐器、知识抽取和 TM 来源审计消费同一清单；省略时仍使用平铺目录发现。实际书籍映射需要单独核验，不会从章节编号推测。

## 模块职责

| 模块 | 当前责任 | 主要输入/输出 |
| --- | --- | --- |
| `pipeline.py` | 配置解析、章节循环、阶段调用、输出保存 | Markdown 章节、项目知识文件、模型响应 |
| `rag_engine.py` | TM 相似检索、词条匹配、指导检索、TM 更新 | `Knowledge` 文件；查询上下文；写入 JSON TM 和可选来源索引 |
| `scripts/align_chapters.py` | 对已有双语章节做段落对齐、生成嵌入与段落来源映射 | `生肉/`、`熟肉/` -> `translation_memory.json` |
| `scripts/validate_tm_provenance.py` | 只读核对 TM 来源哈希、段落索引和原译词对 | TM JSON、`生肉/`、`熟肉/` -> 状态报告 |
| `scripts/validate_source_manifest.py` | 只读核对版本清单 schema 与列出文件的字节哈希 | 显式清单路径 + 数据根目录 -> 汇总状态 |
| `scripts/auto_extract_knowledge.py` | 实验性生成知识和来源清单草稿 | 原文前几章 -> `Glossary_draft.json`、概要及 `KNOWLEDGE_PROVENANCE_draft.json` |
| `source_manifest.py` | 校验并追加本地版本清单元数据原型 | ID、SHA-256、相对路径、父版本 ID -> JSON 清单 |
| `source_ingestion.py` | 消费注入适配器的分页和原文 bytes；维护断点并写版本化本地副本；提供显式相对路径本地文件 adapter | `SourceAdapter`/`LocalFileAdapter` -> 原文/元数据、版本清单、checkpoint |
| `prompts/*.md` | 阶段角色的指令文本 | 被 `TranslationPipeline` 按路径读取 |
| `tests/` | Mock API 和本地行为测试 | 临时项目目录；无真实模型质量验证 |

## 当前阶段数据流

1. `Config.load_config` 从项目参数、JSON 配置或环境变量解析路径；代码还会尝试读取仓库根目录 `.env`。项目名模式不再自动选择 `生肉/`、`熟肉/` 下的第一个子目录；检测到子目录时要求通过显式 `--config` 指定 `RAW_DIR`、`OUTPUT_DIR`，并可逐章配置 `CHAPTER_MAP`。
2. `TranslationPipeline` 读取作品信息、概要，并创建 `RAGEngine`。
3. 每章检索指导、TM、词条和概要上下文。
4. 按阶段调用上下文标注、初译、逻辑校对、润色。
5. 校验阶段结果是非空文本数组、段落数与原文一致，并在每段内核对 `「」『』` 的字符数量和序列；验证失败时停止且不创建译文/TM。通过后先排他新建译文，再按数组位置形成段落对更新 TM。TM 以同目录临时文件加原子替换写入；嵌入失败时保留词对但不写入伪造向量。若 TM 持久化失败，译文文件保留且章节调用报错；后续运行会跳过已有译文，并仅在该文件非空且缺少 TM 章节记录时警告，不自动重建。该门禁不验证语义准确性，也不构成知识审核。
6. `align_chapters.py` 按 `CHAPTER_MAP` 或平铺扫描结果读取原译文件；锚点不匹配时使用 Gale-Church 对齐，验证 embedding 数量后原子更新 TM。溯源记录保存原文/译文相对路径；只读审计用相同路径验证文件哈希和段落引用。

## 外部集成与约束

- 源码默认初译模型名 `sakura-14b`，Sakura base URL 为 `http://127.0.0.1:6006/v1`。
- 源码默认校对/润色模型名分别为 `deepseek-v4-flash`、`deepseek-v4-pro`；base URL 默认 `https://api.deepseek.com/v1`。
- `UnifiedAgent` 默认不跨 Provider 回退。仅显式设置 `ENABLE_GEMINI_FALLBACK=true` 时，连接/超时、HTTP 408/429 和 5xx 错误会将相同请求发送至 Gemini；鉴权/请求错误、响应 schema 错误和 Provider 内容拦截不回退。Gemini 请求未显式放宽安全阈值。真实模型可用性和服务端版本未验证。
- `API_TIMEOUT` 默认 10 秒，必须为有限正数，配置为请求超时并应用到 OpenAI-compatible 聊天及 Gemini 生成、RAG embedding 和章节对齐 embedding；Gemini SDK 的超时值按毫秒传入。实际 Provider 延迟需在获准端点单独验收。
- `PROVIDER_DATA_POLICY` 是按 Provider 和数据类别配置的外发 allowlist，默认 `{}`，拒绝远端请求；请求所需类别必须全部获准。类别为 `source_text`、`translation_text`、`book_knowledge`、`evaluation_samples`。loopback OpenAI-compatible endpoint 和 RAG 的直接本地 mock 请求不经过外发授权检查；Gemini SDK 调用始终需要 Gemini 授权，不以 `MOCK_SERVER_PORT` 环境变量代替授权。测试 runner 只为合成 fixture 显式注入 Gemini mock grant。流水线启动前会检查各生成阶段权限；直接调用、Gemini 回退、RAG、章节对齐和知识抽取也会在请求边界检查。
- `source_manifest.py` schema v1 核验清单字段、唯一版本 ID、同类型逻辑 ID、SHA-256 字符串、相对路径语法、父版本存在性和无环关系；`verify_manifest_files` 只读取调用者显式提供的 manifest 所列文件并核对字节 SHA-256，使用 `utils.resolve_relative_path` 限定在显式根目录内。`scripts/validate_source_manifest.py` 提供只读 CLI。两者不扫描目录、不执行平台访问或授权检查、不管理生命周期状态、版本迁移、删除或跨进程并发。
- `source_ingestion.py` 通过 `SourceAdapter` 接收已解析的目录页和原文 bytes，不创建网络请求。适配器必须提供稳定的 `source_fingerprint`，checkpoint v3 将续传状态绑定到该指纹；快照改变时拒绝恢复。`LocalFileAdapter` 指纹涵盖显式 catalog 的顺序、元数据、路径和源文件 SHA-256，并在读取时复核内容。CLI 为 `scripts/ingest_local_sources.py`。v1/v2 未完成 checkpoint 没有可核验的来源指纹，因此拒绝自动续传；已完成旧 checkpoint 可迁移。数据写入内容寻址的 metadata/raw 文件并追加 manifest 版本。限流、访问拒绝和暂时不可用会暂停；分页循环会在处理当前页后暂停。此原型没有 Kakuyomu/其他站点 adapter、HTTP/HTML 解析、删除/缺失差分、并发锁或流水线集成。
- Gemini embedding 未获 `source_text` 授权时，RAG 查询/写入按现有异常降级处理，不发送文本；查询不返回语义匹配，TM 可保留无向量条目。章节对齐和知识抽取若缺少必要授权则停止，避免写入部分结果。Provider 授权矩阵仍待用户确认。
- `rag_engine.py` 与对齐脚本当前请求 `gemini-embedding-2`；本地 mock 仅用于测试，不能证明真实模型可用。
- 翻译、对齐、知识抽取、TM 审计、来源 manifest 和来源采集的静态路径检查拒绝绝对路径、路径穿越和符号链接；嵌套输出目录必须预先存在。普通文件读取先以 `O_NONBLOCK`/`O_NOFOLLOW`（平台支持时）打开，再用 `fstat` 拒绝 FIFO 等特殊文件；这避免特殊文件阻塞，但不消除目录被另一个本地进程并发替换时的 TOCTOU 风险。跨平台目录句柄级 containment 和跨进程写锁仍未实现。TM 更新采用原子替换；译文和知识草稿使用排他新建。
- 本地来源 CLI 只处理显式 catalog 列出的文件，但 catalog 和单话文件当前整体读取/缓冲，没有大小或归档配额限制。当前按本地、人工选择的导入试点使用；大批量/不可信输入上线前需评估流式处理、大小限制和磁盘配额。
- 项目名解析会检查已解析路径仍位于 `projects/` 下；显式 JSON 配置路径不存在时立即报错。JSON 配置中的目录仍可由操作者显式指定到仓库外。
- README 曾描述的 Sakura/DeepSeek/Gemini 型号、`DEVELOPMENT_PLAN.md` 的旧模型栈与现行源码不完全一致。以源码默认值为实现事实，以真实账户/服务实测为可用性事实。
- 项目级数据目录 `projects/*` 默认被忽略，仅示例项目例外。真实项目知识、译文和 TM 通常不在版本控制中。
- 当前 JSON 文件适用于现有单机代码路径；并发写入、崩溃恢复、规模化查询能力未验证。

## 目标边界（建议，非现状）

- 把工作流阶段契约与 Provider/API 适配边界分开，使语言、文本类型和模型替换不改变核心流程。
- 把书籍级知识与通用语言资源分开；每条可复用知识携带来源、状态和审核信息。
- 将最终章节完整性校验定义为显式门禁，而不是只依赖提示词遵循。
- 在引入服务、数据库、队列或 UI 前，先由路线图定义需求和验收；本仓库未选定上述技术。
