# 架构与边界

## 当前结构

```text
CLI
└── pipeline.py: Config / TranslationPipeline / UnifiedAgent
    ├── prompts/*.md: 阶段指令
    ├── rag_engine.py: 书籍上下文检索与记忆写入
    ├── projects/<project>/{生肉,熟肉,Knowledge}/: 输入、输出、知识数据
    └── providers: Sakura-compatible endpoint / DeepSeek-compatible endpoint / Gemini SDK

scripts/review_translation_candidate.py
└── ai_translation_review.py -> FINAL_REVIEW_MODEL
    └── translation_review.py / translation_review_state.py
        -> hash-bound review decision -> create-only publication gate
scripts/run_ai_translation_workflow.py
└── ai_translation_workflow.py
    └── ai_translation_rework.py -> PROOFREAD_MODEL
        -> create-only ReviewCandidates/ + content-free AIReworks/
        -> repeat review until pass or human boundary

scripts/align_chapters.py -> 双语章节 -> 对齐段落 -> Gemini embeddings -> translation_memory.json
scripts/validate_tm_provenance.py -> translation_memory.json + 生肉/熟肉 -> 只读核验
scripts/validate_knowledge_provenance.py -> KNOWLEDGE_PROVENANCE_draft.json + manifest/原文 -> 只读核验
tests/run_tests.py -> tests/mock_server.py -> tests/test_e2e.py
```

该图仅描述仓库代码。没有证据表明存在独立服务、云部署、Web UI、Agent 编排平台或持续集成。

Kakuyomu 普通 episode URL 采集、作品主页目录发现和到现有翻译流水线的编排均已实现；Notion 同步和完整 EPUB 流程尚未实现。作品目录 parser 从主页 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 按顺序提取 episode ID/title，要求唯一 ID 数量等于 `publicEpisodeCount` 后才生成 canonical 普通 episode URL；这表示页面当前公开目录与其公开话数计数相符，不覆盖草稿/私有章节，也不证明平台声明以外的作品完整性。`scripts/ingest_kakuyomu_pages.py --work-url` 已 source-only 归档试点公开目录 88/88 话；parser v4 从 `widget-episodeBody`/`js-episode-body` 正文区域保留段落边界、将 ruby 转为 `｜基字《读音》`、旁点转为 `｜文本《・・・》` 并保留 U+3000。2026-11-17 全量刷新为 88 话新增精确响应字节 `raw_page_html` artifact；可见 UTF-8 正文仍独立保存为 `raw_source`。当前 `source_manifest.json` 有 356 个文件型 artifact 且通过哈希核验；88 个单话 Markdown 与有序全书 export 已生成。两种派生清洗 profile 生成 176 个不可变版本，记录在 `source_editions_manifest.json`；与来源清单合并验证为 532/532。`scripts/run_kakuyomu_workflow.py --work-url` 在完整采集并物化来源后自动调用 `prepare_source_editions`，分别生成 AI 与人读版，再核验 `RAWs_AI` 索引/镜像与不可变归档版本；映射把 `RAWs_AI` 镜像设为实际正文输入，把归档版本保留为来源 provenance 并校验其哈希。计划摘要绑定两类路径/哈希，pipeline 从 `RAWs_AI` 读取正文并复核归档来源。人读根路径取项目 `workflow_paths.json` 的 `human_edition_root`，未设置时为项目 `生肉/`；AI 根默认与 `SourceArchive/` 同级。已有话目文件必须字节一致才复用，索引只在旧话/章节保持不变且内容为尾部追加时自动刷新。`--ai-edition-root` 仅覆盖 AI 版目录；只有显式指定 `--source-edition normalized_source` 才选择 collector `normalized_source`。目录结构变化或计数不符时 fail-closed。该流程不登录、不跟随重定向、不访问 `/read`，请求间隔限定 1.5–3 秒且默认 2 秒。用户明确表示无需官方澄清并要求普通 URL 路径；服务条款观察作为风险记录，不代表平台背书或公开分发授权。真实 Provider 翻译、正文格式/ruby/旁点人工验收尚未完成。I5 有离线 EPUB candidate 构建原型，但不验证质量、全书完整性或阅读器兼容，详见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。`source_manifest.py` 提供本地 JSON 版本清单校验/追加及显式路径字节 SHA-256 核验；`source_ingestion.py` 提供注入适配器的分页/续传/归档编排核心、显式本地文件 adapter、UTF-8 `.md` 字节保真物化，以及章节集合 `export`。完整 checkpoint 导出校验当前 JSON 记录的发现/完成 ID、逐话 raw 版本及 manifest 当前版本后导出所列章节；checkpoint 未签名且可编辑，因此不证明记录未被改写或外部平台枚举穷尽。导出校验 normalized 文件及当前 raw 父文件，以两个 LF 字节分隔，要求显式输出上限，并记录 normalized 版本父节点；不做语义清洗或差异映射。显式 `CHAPTER_MAP` 可选绑定 `source_version_id`，当前翻译、章节对齐、知识抽取与来源审计会验证/记录该来源版本。TM 与知识草稿只读审计可报告旧来源 `stale` 并校验最新哈希，不改写消费者数据；新鲜度结果可写入独立内容寻址快照，Kakuyomu 完整编排和项目模式采集会自动追加，快照本身不重建或改写下游消费者。

翻译读取边界：清洗/导出和显式归档验证器可读取 `SourceArchive/` 中的原始或派生 artifact；正式翻译、概要/术语来源核验及运行前计划检查只从归档 manifest/catalog 读取版本、lineage 和已登记摘要，不打开归档章节正文。实际 AI 正文及其文件字节哈希只从 `RAWs_AI/` 读取；该哈希与归档 manifest 中 AI artifact 的 `content_sha256` 元数据比较。需要重新验证归档正文实字节时，运行 `scripts/validate_source_manifest.py` 或 `scripts/validate_source_editions.py`。

`raw_page_html` 保存响应体原始 bytes，不按字符集转码。新采集会将 HTTP `Content-Type` 中解析并规范化的 charset 写入 episode metadata；该 metadata 是 HTML artifact 的父版本，归档 validator 按绑定的 charset 重放。旧 metadata 无 `page_charset` 时兼容按 UTF-8 解码；这只能兼容既有假设，不能追溯证明历史响应头字符集。

显式 JSON 的 `CHAPTER_MAP` 为嵌套项目提供逐章映射：可由操作者逐项指定，也可由 `scripts/run_kakuyomu_workflow.py` 根据 catalog 中明确列出的 episode ID/position 生成确定性映射；译文文件名和 TM 键由稳定 episode ID 派生，不依赖标题或原文文件名推断。`chapter_position` 是可选的正整数；提供时优先用于摘要窗口和章节指导选择，避免从内容哈希或平台 ID 推断章节号。若使用 `source_version_id`，还须配置相对 `RAW_DIR` 的 `SOURCE_MANIFEST_PATH`，程序会验证所选 artifact 类型、路径和文件哈希。Kakuyomu 工作流默认将 AI 清洗版作为翻译输入；映射以 `raw_file`/`source_version_id` 指向 `SourceArchive/editions/ai-efficient-v1/` 中不可变的 AI artifact（其 manifest artifact kind 为 `normalized_source`）保留来源 provenance，再以 `source_input_file`/`source_sha256` 指向并核验 `RAWs_AI/` 中的实际正文。翻译运行时只比较 AI 镜像字节哈希与归档 manifest 登记的 artifact digest，并依据归档元数据检查 lineage；不读取归档章节正文。归档物理字节与镜像/profile 的逐字节核验由显式来源验证器完成。运行入口会在目录发现和正文获取前拒绝 `SourceArchive`、人读根、`RAWs_AI` 根与译文根的重叠；共享 AI 索引校验器也会拒绝归档根与 AI 根相同或重叠，覆盖通用项目模式。只有显式 `--source-edition normalized_source` 才选择采集器的规范化来源作为兼容覆盖。流水线、对齐器、知识抽取和 TM 来源审计消费同一映射；省略新增字段时保持旧契约。Kakuyomu 编排重试时，仅跳过输出、TM 词对、段落映射和当前来源版本 provenance 均匹配的已提交章节；冲突内容不覆盖。该 CLI 不发现页面。

## 章节映射预览

`scripts/run_kakuyomu_workflow.py --plan-only` 是本地预览入口：只读已有 catalog、manifest 元数据和 AI 输入镜像，验证 episode 元数据、最新 raw/cleaned 版本的 lineage、镜像文件哈希与译文目标路径，然后输出 JSON 映射与 `plan_sha256`。默认从来源归档同级 `RAWs_AI` 验证 AI 索引完整覆盖 catalog、AI 镜像字节哈希与归档 manifest 中登记的摘要、清洗清单及 raw lineage；该模式不打开归档章节正文。计划的 `source_input_file` 指向 AI 镜像，`source_file` 与 `source_version_id` 保留归档溯源。缺失或过期时停止，不回退到未经 AI 清洗的来源。`--ai-edition-root` 可覆盖 AI 镜像目录，`--source-edition normalized_source` 是显式规范化版本覆盖。审批摘要绑定逐话归档来源路径/版本及 AI 输入路径/哈希；AI 模式还绑定 profile、索引根/路径/hash 和清洗清单路径/hash。正式翻译通过 `CHAPTER_MAP` 从 `RAWs_AI` 读取正文，并用归档 manifest 元数据复核哈希与 lineage。默认 stdout 模式不加载项目配置或 Provider 密钥、不联网、不读取已有译文/TM 内容、不写文件或输出书籍正文；显式 `--plan-output` 仅排他新建不含正文的计划 JSON。`ready_for_review` 只表示预览完整且没有检测到目标冲突或来源问题；仍需本地人工审核，不代表已批准。审批回执是未签名本地 JSON，身份标签未认证。正式模式仍按当前 catalog/来源版本重算映射。

## 模块职责

| 模块 | 当前责任 | 主要输入/输出 |
| --- | --- | --- |
| `pipeline.py` | 配置解析、项目模式 AI 默认选源/版本映射、章节循环、阶段调用、输出保存与正式运行阶段轨迹 | `RAWs_AI` AI 清洗镜像/显式 JSON 来源映射、归档 manifest provenance、项目知识文件、模型响应；正式 run 另写 hash-only `StageReports` |
| `ai_translation_review.py` / `scripts/review_translation_candidate.py` | 显式执行单轮双次 AI 终审；绑定来源、候选、策略和 reviewer route；逐次持久化通过校验的结构化结果；两次门禁通过后调用现有发布器 | 活动 run、策略 JSON、`FINAL_REVIEW_MODEL` -> 仅含 verdict/登记 code/段落索引/检查的 `AIReviews/` sidecar、报告与 schema v4 决策；单次命令失败时不发布；有限返工由下方工作流 CLI 编排 |
| `ai_translation_workflow.py` / `ai_translation_rework.py` / `scripts/run_ai_translation_workflow.py` | 显式续接单话的终审、有限定向返工、复审和通过后发布；返工只改 findings 指向的段落 | `PROOFREAD_MODEL`、source/candidate、策略定义与 findings -> create-only `ReviewCandidates/` 和内容无关 `AIReworks/`；结构错误、授权/路由不符、预算耗尽或需人工状态不发布 |
| `translation_review.py` / `translation_review_state.py` | 记录/核验候选版本决策链、人工仲裁、审核快照并执行 create-only 发布 | run/source/candidate/policy 摘要、阶段 verdict 与检查 -> `ReviewDecisions/`、`ReviewResolutions/`、正式译文/回执 |
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
| `scripts/auto_extract_knowledge.py` / `knowledge_batching.py` | 实验性生成知识和来源清单草稿；默认前三章；`--full-book` 或 `--chapter-position` 从 verified AI bundle 按本地 tokenizer/context 限额分批，并校验候选段落引用 | verified AI bundle + 字符上限、tokenizer 与模型容量参数 -> 全书候选或单话局部候选及 provenance；单话概要/可选术语经人工回执发布后由 `pipeline.py` 按当前章节及 bundle 身份校验并注入上下文 |
| `chapter_transaction.py` | 逐章记录译文/TM 更新意图，并在重跑时验证和恢复未完成提交 | 章节映射、原文/译文哈希、TM 基线 -> 输出文件与 TM |
| `source_manifest.py` | 校验并追加本地版本清单元数据原型；按版本 ID 核验单个 artifact | ID、SHA-256、相对路径、父版本 ID -> JSON 清单/选定文件校验 |
| `source_ingestion.py` | 消费注入适配器的分页和原文 bytes；维护断点并写版本化本地副本；提供显式相对路径本地文件 adapter、字节保真 Markdown 物化和章节集合导出 | `SourceAdapter`/`LocalFileAdapter`/指定版本 -> `raw_source`、`raw_page_html`、元数据、Markdown/export artifact、manifest/checkpoint |
| `source_editions.py` / `scripts/export_source_editions.py` / `scripts/validate_source_editions.py` | 从同一当前 raw source 独立生成 AI/人读 profile；清洗输出以不可变版本归档，独立清单保留 source 与 edition lineage；只读验证器可从 raw bytes 重算两版并核对归档与镜像 | 来源 manifest/catalog + 两个输出根 -> AI/human 镜像、索引及 `source_editions_manifest.json`；只读验证返回计数与索引摘要 |
| `kakuyomu_html_archive.py` / `scripts/validate_kakuyomu_html_archive.py` | 只读核对来源文件哈希，并重放最新 Kakuyomu HTML，验证标题、当前 raw lineage 与可见正文哈希；不联网、不输出正文 | source root + manifest -> parser 版本、artifact/话数及字节计数摘要 |
| `kakuyomu_page_source.py` | 检查 Kakuyomu robots；从作品页 Next.js Apollo 目录中按 `publicEpisodeCount` 校验并发现公开 episode URL，再提取可见标题/正文文本并返回原始 HTTP 响应体 bytes；不登录、不跟随重定向、不访问 `/read` | 作品主页或显式 episode catalog -> UTF-8 章节文本、页面响应 bytes、目录与来源指纹 |
| `scripts/ingest_kakuyomu_pages.py` | 从作品主页发现公开目录或加载显式 catalog，验证输出不覆盖输入并把全部所列页面接入版本化归档核心 | `source-root` + work URL/catalog + output-root -> discovered catalog/manifest/checkpoint/raw source |
| `scripts/run_kakuyomu_workflow.py` | `--plan-only` 默认核验并选用 AI 清洗版，输出章节映射预览；完整采集后自动生成 AI/人读版，再默认选 AI 版；`--source-edition normalized_source` 是显式兼容覆盖；正式模式先校验项目配置和 Provider 授权/凭据 | source root + catalog/manifest + optional AI edition root + translation root -> JSON 映射预览；或 work URL/catalog + project JSON -> catalog/versioned source/AI edition/human edition/translation/TM |
| `scripts/create_verified_translation_plan_review.py` | 只有全量双版本字节/profile/lineage 验证及计划/索引摘要一致时，才 create-only 写入结构审阅；不调用模型或 Provider | 当前计划 + 人读索引 + raw/AI/人读根目录 -> 内容无关的逐话结构审阅 JSON |
| `prompts/*.md` | 阶段角色的指令文本 | 被 `TranslationPipeline` 按路径读取 |
| `tests/` | Mock API 和本地行为测试 | 临时项目目录；无真实模型质量验证 |

## 当前阶段数据流

项目名模式中的路径边界：`SourceArchive/` 存放原始页面、可见正文、规范化文本、派生版本、source/edition manifests、采集 catalog/checkpoint 和不可变校验快照；不存放 AI 工作副本或翻译计划/审批回执。`Workflow/Plans/` 保存待审翻译计划，`Workflow/Approvals/` 保存计划审批回执。`RAWs_AI/` 保存 AI 清洗镜像和索引，是默认翻译正文的读取位置。`CHAPTER_MAP.raw_file` 与 `source_version_id` 指向归档版本，仅用于版本溯源；`source_input_file` 指向 `RAWs_AI/` 下的实际翻译输入，`source_sha256` 是镜像字节哈希，并与归档 manifest 的 `content_sha256` 元数据核对。翻译、概要、术语和 TM 来源运行时读取 AI 正文只访问 `RAWs_AI/`；归档目录只提供 lineage 和已登记摘要，不打开归档章节正文。镜像缺失或哈希不符时失败关闭，不改读归档或人读版。来源 manifest/edition 验证器和清洗/导出流程可显式读取归档正文。计划与审批 CLI 均拒绝向 `SourceArchive/` 写入工作流文件。

默认项目模式还固定使用 `Knowledge/STORY_SUMMARY_reviewed.json` 和 `Knowledge/Glossary_reviewed.json`。概要须覆盖完整 AI 章节映射，术语 bundle 须通过来源版本核验；缺失、旧式或过期的知识输入在创建翻译请求前失败关闭。显式 JSON 配置保留调用者指定旧格式的兼容路径。

`TranslationPipeline` 输出也有显式模式边界：项目/Kakuyomu run 使用内部 `reviewed_run_draft` 并要求活动 run；未审核兼容调用必须设置 `TRANSLATION_OUTPUT_MODE="compatibility_draft"`，测试工作区使用独立 `test_draft`。显式 JSON 配置只接受兼容 draft 标记，缺失或与 reviewed publication 冲突时拒绝创建 pipeline。兼容输出即使位于任意外部目录也不具备正式发布资格；正式译文只能由审核发布器从有效 run 草稿 create-only 创建。直接使用 Python API 的调用方也必须明确指定输出模式。

AI 终审和自动返工都是显式 CLI，不会在 `TranslationPipeline` 初译后自动触发。终审将完整 source/candidate 和策略定义发送给 `FINAL_REVIEW_MODEL`，但不发送 book knowledge；同一候选执行两次结构化评估，每次通过校验后将不含正文/自由文本的规范化结果原子保存至 run 内 `AIReviews/`，恢复时按来源、候选、策略、路由和序号身份复用已完成评估，仅请求缺失项。两次评估必须同时通过 fidelity/fluency/style、八项发布检查及定性收敛门。若 Provider 已返回而对应 sidecar 尚未落盘时进程中断，该次请求仍可能重复。工作流 CLI 在 `rework` 时将完整 source/candidate（限制合计 64,000 字符）、阻断 findings 和相应策略定义发送给不同的 `PROOFREAD_MODEL`，不发送 book knowledge；严格校验 JSON 后仅替换命中段落，并 create-only 保存候选和内容无关 sidecar，再续审。通过时复用既有审核发布器；冲突、预算耗尽、需要人工或生成契约失败均不发布。结构绑定与合成测试不证明实际修订修复了语义问题，reviewer 身份、语义质量和真实端点仍未验证。

Kakuyomu run 还要求每个待翻译的非空章节拥有来源版本和当前整书 bundle 均匹配的 `ChapterDrafts/.../STORY_SUMMARY_reviewed.json`。启动预检覆盖全部待翻译章节，避免后续章节缺少回执时前面章节已调用模型；每章上下文构建时再次复核。局部 `Glossary_reviewed.json` 可选；与全书批准词条冲突时失败关闭。

1. `Config.load_config` 从项目参数、JSON 配置或环境变量解析路径；代码还会尝试读取仓库根目录 `.env`。项目名模式要求 `SourceArchive/` 和 `RAWs_AI/` 都存在，默认验证 AI 索引、其 catalog 摘要与 ID/title/position 完整覆盖、清洗清单、镜像字节哈希及归档 manifest lineage；生成的 `CHAPTER_MAP` 分开保存归档溯源路径/版本与 `RAWs_AI` 实际输入路径/哈希。pipeline 从 AI 镜像读取正文，并将镜像字节哈希与归档 manifest 登记的 `content_sha256` 比较；它读取归档 metadata，不读取归档章节正文。缺失、过期或不完整时失败关闭，不读取人读版 `生肉/`。项目名模式同时把概要路径设为 `Knowledge/STORY_SUMMARY_reviewed.json` 并启用全书审核门禁。显式 JSON `RAW_DIR`/`CHAPTER_MAP` 仍由调用者指定，可用于迁移旧版目录。项目根可选 `workflow_paths.json`（schema v1）设置已存在的 `output_dir` 和可选 `human_edition_root`；路径可相对项目根或绝对指定，不接受原文根或章节映射覆盖，译文根不得与原文目录重叠。没有该文件时，默认 `熟肉/` 若含子目录仍须通过显式 `--config` 指定译文根。
2. `TranslationPipeline` 在加载作品信息、RAG 和翻译阶段前，验证项目模式的概要 bundle 已批准、覆盖完整 AI 章节映射，并与每章 AI 文件名及 `source_version_id` 一致；缺失、过期或不匹配时失败关闭。显式 JSON 兼容配置仍可配置旧概要路径。显式配置 `TM_REVIEWED_PATH` 时同时传入译文根目录以核验审核快照。
3. 每章检索指导、词条和概要上下文；RAG 默认只从显式设置且通过当前来源核验的 `TM_REVIEWED_PATH` 快照检索。未设置快照时不注入 TM 示例，也不生成查询 embedding。完整可写 TM 仍接收候选写入；`ALLOW_UNREVIEWED_TM=true` 仅可用于兼容调用，正式项目翻译会拒绝此配置；已配置快照始终优先。
4. 按阶段调用上下文标注、初译、逻辑校对、润色。
5. 校验阶段结果是非空文本数组、段落数与原文一致，并在每段内核对 `「」『』` 的字符数量和序列；验证失败时不创建译文/TM。通过后、提交前复读源文，并在配置 `source_version_id` 时复核 manifest artifact 的类型、路径和版本状态。AI 映射下复读正文只从 `RAWs_AI` 取字节，归档侧只读 manifest 元数据并比对登记 digest；显式非 AI 映射仍按 manifest 路径读取并校验来源文件。正式 run 同时向 `Workflow/Runs/<run_id>/StageReports/` 追加按话目的阶段状态、输入/输出摘要、模型标识和失败类型；报告不含正文/提示词，也不等同于独立语义审核。源文变化时拒绝发布，但复读与后续写入之间仍无并发写锁。随后 `chapter_transaction.py` 在输出目录排他创建逐章恢复日志，再排他写译文、原子更新 TM，成功后移除日志。重跑时先检查待处理日志，再决定跳过已有译文；恢复前核验章节映射、源文/译文哈希、格式门禁、输出内容和 TM 基线，冲突时停止且不覆盖已有内容。日志记录完整译文文本，临时保存在本地输出目录；日志 SHA-256 用于一致性校验，不认证审核者或文件来源。此机制只支持单写入者的进程中断恢复，不保证多进程并发、断电后的目录项持久性或自动解决外部冲突。TM 以同目录临时文件加原子替换写入；嵌入失败时保留词对但不写入伪造向量。格式门禁不验证语义准确性，也不构成知识审核。
6. `align_chapters.py` 按 `CHAPTER_MAP` 或平铺扫描结果读取原译文件；锚点不匹配时使用 Gale-Church 对齐，验证 embedding 数量后原子更新 TM。溯源记录保存原文/译文相对路径；只读审计用相同路径验证文件哈希和段落引用。

## 外部集成与约束

- 源码默认初译模型名 `sakura-14b`，Sakura base URL 为 `http://127.0.0.1:6006/v1`。
- 源码默认校对/润色模型名分别为 `deepseek-v4-flash`、`deepseek-v4-pro`；base URL 默认 `https://api.deepseek.com/v1`。
- `UnifiedAgent` 默认不跨 Provider 回退。仅显式设置 `ENABLE_GEMINI_FALLBACK=true` 时，连接/超时、HTTP 408/429 和 5xx 错误会将相同请求发送至 Gemini；鉴权/请求错误、响应 schema 错误和 Provider 内容拦截不回退。Gemini 请求未显式放宽安全阈值。真实模型可用性和服务端版本未验证。
- `API_TIMEOUT` 默认 10 秒，必须为有限正数，配置为请求超时并应用到 OpenAI-compatible 聊天及 Gemini 生成、RAG embedding 和章节对齐 embedding；Gemini SDK 的超时值按毫秒传入。实际 Provider 延迟需在获准端点单独验收。
- `PROVIDER_DATA_POLICY` 是按 Provider 和数据类别配置的外发 allowlist，默认 `{}`，拒绝远端请求；请求所需类别必须全部获准。类别为 `source_text`、`translation_text`、`book_knowledge`、`evaluation_samples`。用户已授权 JOJO/JYQF 接收各自职责所需的最小类别，生成流水线当前按实际阶段计算；allowlist 默认空表示运行时尚未显式配置，不是待用户补充授权。loopback OpenAI-compatible endpoint 和 RAG 的直接本地 mock 请求不经过外发授权检查；Gemini SDK 调用始终需要 Gemini 授权，不以 `MOCK_SERVER_PORT` 环境变量代替授权。测试 runner 只为合成 fixture 显式注入 Gemini mock grant。直接调用、Gemini 回退、RAG、章节对齐和知识抽取也会在请求边界检查。
- `source_manifest.py` schema v1 核验清单字段、唯一版本 ID、同类型逻辑 ID、SHA-256 字符串、相对路径语法、父版本存在性和无环关系；`verify_manifest_files` 只读取调用者显式提供的 manifest 所列文件并核对字节 SHA-256，使用 `utils.resolve_relative_path` 限定在显式根目录内。`scripts/validate_source_manifest.py` 提供只读 CLI。两者不扫描目录、不执行平台访问或授权检查、不管理生命周期状态、版本迁移、删除或跨进程并发。
- `source_ingestion.py` 通过 `SourceAdapter` 接收目录页和原文 bytes；适配器必须提供稳定的 `source_fingerprint`。checkpoint v5 绑定目录/额度快照、目标 manifest 相对路径和已完成 episode 的 raw 版本 ID；v1/v2 因无来源指纹拒绝迁移，v3/v4 仅在无已完成 episode 且来源指纹匹配时迁移。完整 checkpoint 导出还会核对 raw 版本仍是 manifest 当前版本。`LocalFileAdapter` 的指纹涵盖显式 catalog 顺序、元数据、路径和源文件 SHA-256，并在读取时复核内容；CLI 为 `scripts/ingest_local_sources.py`。`KakuyomuPageAdapter` 位于 `kakuyomu_page_source.py`：可从作品主页 Next.js Apollo 目录发现并校验所有公开 episode ID/title，或读取显式 catalog；校验条目数与 `publicEpisodeCount` 相等后生成普通 episode URL。运行前检查 robots，随后由 checkpoint 核心逐话请求页面、校验标题/唯一正文区域并即时归档解析文本及原始响应体 bytes；`raw_page_html` 以当前 episode metadata 和对应 `raw_source` 版本为父节点。访问失败时保留已完成版本，下次从首个未完成话继续，不重抓已完成正文。它拒绝 robots disallow、非 200/重定向、429、非 HTML、缺失/重复目标区域、标题不符和超限；不登录、不访问 `/read`。Kakuyomu 来源指纹绑定 parser、robots、目录 ID/title/顺序和限额，不绑定正文；可见正文及 HTML 响应分别由 artifact 哈希记录。续传是按话滚动采集，不是同一时刻的原子全书快照；目录未变时完整 checkpoint 不自动重抓正文，需要刷新时使用新 checkpoint。`scripts/ingest_kakuyomu_pages.py --work-url` 可独立发现并归档全部公开目录话目，不需 Provider；`scripts/run_kakuyomu_workflow.py --work-url` 还可物化版本、生成确定性 `CHAPTER_MAP` 并调用现有流水线。公开目录不含草稿/私有话，也不证明平台声明外的完整性；缺失/删除差分、并发锁仍未实现。
- Gemini embedding 未获 `source_text` 授权时，RAG 查询/写入按现有异常降级处理，不发送文本；查询不返回语义匹配，TM 可保留无向量条目。章节对齐和知识抽取若缺少必要授权则停止，避免写入部分结果。用户对 JOJO/JYQF 的最小职责类别授权不包括 Gemini embedding 或其他未指定接收方。
- `rag_engine.py` 与对齐脚本当前请求 `gemini-embedding-2`；本地 mock 仅用于测试，不能证明真实模型可用。
- 翻译、对齐、知识抽取、TM 审计、来源 manifest 和来源采集的静态路径检查拒绝绝对路径、路径穿越和符号链接；嵌套输出目录必须预先存在。普通文件读取先以 `O_NONBLOCK`/`O_NOFOLLOW`（平台支持时）打开，再用 `fstat` 拒绝 FIFO 等特殊文件；这避免特殊文件阻塞，但不消除目录被另一个本地进程并发替换时的 TOCTOU 风险。跨平台目录句柄级 containment 和通用跨进程写锁仍未实现；审核决定链是例外，按话目使用专用 append lock 串行化链校验和决定文件创建。TM 更新采用原子替换；译文和知识草稿使用排他新建。
- 本地来源 CLI 只处理显式 catalog 列出的文件；catalog 有界读取、章节快照/归档读取有单章与单批上限，另提供无默认值的 `--max-archive-bytes` 逻辑清单内容上限。该额度不计物理分配、未登记孤儿/临时文件，也不约束其他工具后续写入；不是物理磁盘配额。当前仍按本地、人工选择的导入试点使用；不可信输入上线前还需评估网络响应流大小、并发写入和真正的磁盘配额。
- 项目名解析会检查已解析路径仍位于 `projects/` 下；显式 JSON 配置路径不存在时立即报错。JSON 配置中的目录仍可由操作者显式指定到仓库外。
- README 曾描述的 Sakura/DeepSeek/Gemini 型号、`DEVELOPMENT_PLAN.md` 的旧模型栈与现行源码不完全一致。以源码默认值为实现事实，以真实账户/服务实测为可用性事实。
- 项目级数据目录 `projects/*` 默认被忽略，仅示例项目例外。真实项目知识、译文和 TM 通常不在版本控制中。
- 当前 JSON 文件适用于现有单机代码路径；逐章恢复日志覆盖经测试的进程中断重试，不提供通用多进程写锁，也未验证断电恢复或规模化查询。审核决定链的按话目 append lock 只保护该决定链，不扩展为其他 JSON、TM 或多文件事务的并发协调。

## 目标边界（建议，非现状）

- 把工作流阶段契约与 Provider/API 适配边界分开，使语言、文本类型和模型替换不改变核心流程。
- 把书籍级知识与通用语言资源分开；每条可复用知识携带来源、状态和审核信息。
- 将最终章节完整性校验定义为显式门禁，而不是只依赖提示词遵循。
- 在引入服务、数据库、队列或 UI 前，先由路线图定义需求和验收；本仓库未选定上述技术。
