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
scripts/validate_knowledge_provenance.py -> KNOWLEDGE_PROVENANCE_draft.json + manifest/原文 -> 只读核验
tests/run_tests.py -> tests/mock_server.py -> tests/test_e2e.py
```

该图仅描述仓库代码。没有证据表明存在独立服务、云部署、Web UI、Agent 编排平台或持续集成。

具体站点的原文采集适配器、Notion 同步和完整 EPUB 流程尚未实现；I5 有离线 EPUB candidate 构建原型，但不验证质量、全书完整性或阅读器兼容，详见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。`source_manifest.py` 提供本地 JSON 版本清单校验/追加及显式路径字节 SHA-256 核验；`source_ingestion.py` 提供注入适配器的分页/续传/归档编排核心、仅读取显式 catalog 列出文件的本地 adapter、单话 UTF-8 `.md` 字节保真物化，以及章节集合 `export`。集合导出可由调用者显式选择有序 episode ID，也可要求完整 checkpoint v5：后者核对当前 checkpoint JSON 记录的发现/完成 ID 集合、每话绑定的 raw 版本及 manifest 当前版本一致，再导出所列章节。checkpoint 未签名且可编辑，因此校验不证明记录未经改写或外部平台枚举穷尽。两种模式均校验 normalized 文件及当前 raw 父文件，固定以两个 LF 字节分隔，要求调用者指定输出字节上限，并记录 normalized 版本为父版本；不清洗格式或生成差异映射。对应 CLI 为 `scripts/materialize_source_markdown.py` 与 `scripts/merge_source_markdown.py`。显式 `CHAPTER_MAP` 可选绑定 `source_version_id`，当前翻译、章节对齐、知识抽取与来源审计会验证/记录该来源版本。TM 与知识草稿 provenance 只读审计会按 manifest 中同一 `artifact_id` 的最后追加版本报告旧版本为 `stale`，并校验最新文件哈希；审计不改写 TM/草稿，也不持久化下游过期状态。来源工具均不发起 HTTP 请求或解析平台页面。

显式 JSON 的 `CHAPTER_MAP` 为嵌套项目提供逐章映射：原文根目录相对路径、译文根目录相对路径和唯一 TM 键由操作者逐项指定；若增加 `source_version_id`，还须配置相对 `RAW_DIR` 的 `SOURCE_MANIFEST_PATH`，程序会验证所选 artifact 类型、路径和文件哈希。流水线、对齐器、知识抽取和 TM 来源审计消费同一映射；省略来源版本字段时保持旧契约。实际书籍映射需要单独核验，不会从章节编号推测。

## 模块职责

| 模块 | 当前责任 | 主要输入/输出 |
| --- | --- | --- |
| `pipeline.py` | 配置解析、章节循环、阶段调用、输出保存 | Markdown 章节、项目知识文件、模型响应 |
| `rag_engine.py` | TM 相似检索、词条匹配、指导检索、TM 更新 | `Knowledge` 文件；可选审核 TM 快照；写入完整 JSON TM 和可选来源索引 |
| `scripts/align_chapters.py` | 对已有双语章节做段落对齐、生成嵌入与段落来源映射 | `生肉/`、`熟肉/` -> `translation_memory.json` |
| `scripts/validate_tm_provenance.py` | 只读核对 TM 来源哈希、段落索引、原译词对及 manifest 当前来源版本 | TM JSON、`生肉/`、`熟肉/`、可选 manifest -> 状态报告 |
| `scripts/apply_tm_review.py` | 创建 TM 逐对审核回执模板并发布来源核验的 approved-only 快照 | 完整 TM、回执、manifest、原/译文件 -> 新审核回执或快照 |
| `scripts/validate_knowledge_provenance.py` | 只读核对知识草稿 provenance、来源文本哈希、manifest 版本及最新来源 | provenance JSON + 来源根目录/manifest -> 状态报告 |
| `scripts/validate_source_manifest.py` | 只读核对版本清单 schema 与列出文件的字节哈希 | 显式清单路径 + 数据根目录 -> 汇总状态 |
| `scripts/materialize_source_markdown.py` | 从 manifest 指定的原始版本生成字节保真的 UTF-8 `.md` 派生版本 | 数据根目录 + work/episode ID -> `normalized_source` artifact |
| `scripts/merge_source_markdown.py` | 按显式来源顺序合并章节集合，支持完整 checkpoint v5 门禁并记录输入版本 | 数据根目录 + work ID + 显式有序 episode IDs 或完整 checkpoint + 必填输出字节上限 -> `export` artifact |
| `scripts/build_epub_candidate.py` | 用精确版本匹配的 Pandoc 构建显式章节选集的 EPUB candidate 并执行有限结构检查 | 章节 catalog + 译文 Markdown -> candidate EPUB + 输入/输出哈希 sidecar |
| `epub_builder.py` | 校验 EPUB candidate catalog、尺寸/版本约束及 ZIP/OPF/XHTML 基本结构 | 合成/真实 Markdown 输入与 Pandoc -> candidate 及局部验证结果 |
| `scripts/auto_extract_knowledge.py` | 实验性生成知识和来源清单草稿 | 原文前几章 -> `Glossary_draft.json`、概要及 `KNOWLEDGE_PROVENANCE_draft.json` |
| `chapter_transaction.py` | 逐章记录译文/TM 更新意图，并在重跑时验证和恢复未完成提交 | 章节映射、原文/译文哈希、TM 基线 -> 输出文件与 TM |
| `source_manifest.py` | 校验并追加本地版本清单元数据原型；按版本 ID 核验单个 artifact | ID、SHA-256、相对路径、父版本 ID -> JSON 清单/选定文件校验 |
| `source_ingestion.py` | 消费注入适配器的分页和原文 bytes；维护断点并写版本化本地副本；提供显式相对路径本地文件 adapter、字节保真 Markdown 物化和章节集合导出 | `SourceAdapter`/`LocalFileAdapter`/指定版本 -> 原文、元数据、Markdown/export artifact、manifest/checkpoint |
| `prompts/*.md` | 阶段角色的指令文本 | 被 `TranslationPipeline` 按路径读取 |
| `tests/` | Mock API 和本地行为测试 | 临时项目目录；无真实模型质量验证 |

## 当前阶段数据流

1. `Config.load_config` 从项目参数、JSON 配置或环境变量解析路径；代码还会尝试读取仓库根目录 `.env`。项目名模式不再自动选择 `生肉/`、`熟肉/` 下的第一个子目录；检测到子目录时要求通过显式 `--config` 指定 `RAW_DIR`、`OUTPUT_DIR`，并可逐章配置 `CHAPTER_MAP`。
2. `TranslationPipeline` 读取作品信息、概要，并创建 `RAGEngine`；显式配置 `TM_REVIEWED_PATH` 时同时传入译文根目录以核验审核快照。
3. 每章检索指导、词条和概要上下文；TM 默认来自完整可写记忆，显式设置 `TM_REVIEWED_PATH` 后才改为从当前来源核验通过的 approved-only 快照检索。
4. 按阶段调用上下文标注、初译、逻辑校对、润色。
5. 校验阶段结果是非空文本数组、段落数与原文一致，并在每段内核对 `「」『』` 的字符数量和序列；验证失败时不创建译文/TM。通过后、提交前复读源文，并在配置 `source_version_id` 时复核 manifest artifact 的类型、路径和文件哈希。源文变化时拒绝发布，但复读与后续写入之间仍无并发写锁。随后 `chapter_transaction.py` 在输出目录排他创建逐章恢复日志，再排他写译文、原子更新 TM，成功后移除日志。重跑时先检查待处理日志，再决定跳过已有译文；恢复前核验章节映射、源文/译文哈希、格式门禁、输出内容和 TM 基线，冲突时停止且不覆盖已有内容。日志记录完整译文文本，临时保存在本地输出目录；日志 SHA-256 用于一致性校验，不认证审核者或文件来源。此机制只支持单写入者的进程中断恢复，不保证多进程并发、断电后的目录项持久性或自动解决外部冲突。TM 以同目录临时文件加原子替换写入；嵌入失败时保留词对但不写入伪造向量。格式门禁不验证语义准确性，也不构成知识审核。
6. `align_chapters.py` 按 `CHAPTER_MAP` 或平铺扫描结果读取原译文件；锚点不匹配时使用 Gale-Church 对齐，验证 embedding 数量后原子更新 TM。溯源记录保存原文/译文相对路径；只读审计用相同路径验证文件哈希和段落引用。

## 外部集成与约束

- 源码默认初译模型名 `sakura-14b`，Sakura base URL 为 `http://127.0.0.1:6006/v1`。
- 源码默认校对/润色模型名分别为 `deepseek-v4-flash`、`deepseek-v4-pro`；base URL 默认 `https://api.deepseek.com/v1`。
- `UnifiedAgent` 默认不跨 Provider 回退。仅显式设置 `ENABLE_GEMINI_FALLBACK=true` 时，连接/超时、HTTP 408/429 和 5xx 错误会将相同请求发送至 Gemini；鉴权/请求错误、响应 schema 错误和 Provider 内容拦截不回退。Gemini 请求未显式放宽安全阈值。真实模型可用性和服务端版本未验证。
- `API_TIMEOUT` 默认 10 秒，必须为有限正数，配置为请求超时并应用到 OpenAI-compatible 聊天及 Gemini 生成、RAG embedding 和章节对齐 embedding；Gemini SDK 的超时值按毫秒传入。实际 Provider 延迟需在获准端点单独验收。
- `PROVIDER_DATA_POLICY` 是按 Provider 和数据类别配置的外发 allowlist，默认 `{}`，拒绝远端请求；请求所需类别必须全部获准。类别为 `source_text`、`translation_text`、`book_knowledge`、`evaluation_samples`。loopback OpenAI-compatible endpoint 和 RAG 的直接本地 mock 请求不经过外发授权检查；Gemini SDK 调用始终需要 Gemini 授权，不以 `MOCK_SERVER_PORT` 环境变量代替授权。测试 runner 只为合成 fixture 显式注入 Gemini mock grant。流水线启动前会检查各生成阶段权限；直接调用、Gemini 回退、RAG、章节对齐和知识抽取也会在请求边界检查。
- `source_manifest.py` schema v1 核验清单字段、唯一版本 ID、同类型逻辑 ID、SHA-256 字符串、相对路径语法、父版本存在性和无环关系；`verify_manifest_files` 只读取调用者显式提供的 manifest 所列文件并核对字节 SHA-256，使用 `utils.resolve_relative_path` 限定在显式根目录内。`scripts/validate_source_manifest.py` 提供只读 CLI。两者不扫描目录、不执行平台访问或授权检查、不管理生命周期状态、版本迁移、删除或跨进程并发。
- `source_ingestion.py` 通过 `SourceAdapter` 接收已解析的目录页和原文 bytes，不创建网络请求。适配器必须提供稳定的 `source_fingerprint`；checkpoint v5 绑定来源/额度快照、目标 manifest 相对路径和已完成 episode 的 raw 版本 ID。v1/v2 因缺少可核验来源指纹拒绝自动迁移；v3/v4 只有无已完成 episode 且来源指纹匹配时才可迁移；旧 checkpoint 无法提供 raw 版本绑定。完整 checkpoint 导出还会核对这些 raw 版本仍是 manifest 当前版本。`LocalFileAdapter` 指纹涵盖显式 catalog 的顺序、元数据、路径和源文件 SHA-256，并在读取时复核内容。CLI 为 `scripts/ingest_local_sources.py`。数据写入内容寻址的 metadata/raw 文件并追加 manifest 版本；artifact ID 由作品 ID、类型和章节 ID 的规范化元组派生，避免分隔符碰撞。限流、访问拒绝和暂时不可用会暂停；分页循环会在处理当前页后暂停。此原型没有 Kakuyomu/其他站点 adapter、HTTP/HTML 解析、删除/缺失差分、并发锁或流水线集成。
- Gemini embedding 未获 `source_text` 授权时，RAG 查询/写入按现有异常降级处理，不发送文本；查询不返回语义匹配，TM 可保留无向量条目。章节对齐和知识抽取若缺少必要授权则停止，避免写入部分结果。Provider 授权矩阵仍待用户确认。
- `rag_engine.py` 与对齐脚本当前请求 `gemini-embedding-2`；本地 mock 仅用于测试，不能证明真实模型可用。
- 翻译、对齐、知识抽取、TM 审计、来源 manifest 和来源采集的静态路径检查拒绝绝对路径、路径穿越和符号链接；嵌套输出目录必须预先存在。普通文件读取先以 `O_NONBLOCK`/`O_NOFOLLOW`（平台支持时）打开，再用 `fstat` 拒绝 FIFO 等特殊文件；这避免特殊文件阻塞，但不消除目录被另一个本地进程并发替换时的 TOCTOU 风险。跨平台目录句柄级 containment 和跨进程写锁仍未实现。TM 更新采用原子替换；译文和知识草稿使用排他新建。
- 本地来源 CLI 只处理显式 catalog 列出的文件；catalog 有界读取、章节快照/归档读取有单章与单批上限，另提供无默认值的 `--max-archive-bytes` 逻辑清单内容上限。该额度不计物理分配、未登记孤儿/临时文件，也不约束其他工具后续写入；不是物理磁盘配额。当前仍按本地、人工选择的导入试点使用；不可信输入上线前还需评估网络响应流大小、并发写入和真正的磁盘配额。
- 项目名解析会检查已解析路径仍位于 `projects/` 下；显式 JSON 配置路径不存在时立即报错。JSON 配置中的目录仍可由操作者显式指定到仓库外。
- README 曾描述的 Sakura/DeepSeek/Gemini 型号、`DEVELOPMENT_PLAN.md` 的旧模型栈与现行源码不完全一致。以源码默认值为实现事实，以真实账户/服务实测为可用性事实。
- 项目级数据目录 `projects/*` 默认被忽略，仅示例项目例外。真实项目知识、译文和 TM 通常不在版本控制中。
- 当前 JSON 文件适用于现有单机代码路径；逐章恢复日志覆盖经测试的进程中断重试，不提供多进程写锁，也未验证断电恢复或规模化查询。

## 目标边界（建议，非现状）

- 把工作流阶段契约与 Provider/API 适配边界分开，使语言、文本类型和模型替换不改变核心流程。
- 把书籍级知识与通用语言资源分开；每条可复用知识携带来源、状态和审核信息。
- 将最终章节完整性校验定义为显式门禁，而不是只依赖提示词遵循。
- 在引入服务、数据库、队列或 UI 前，先由路线图定义需求和验收；本仓库未选定上述技术。
