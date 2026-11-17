# 翻译流程与 Agent 职责

## 适用边界

- 默认 `pipeline.py --project` 使用 AI 清洗版作为待译原文，并要求已审核、来源版本仍有效的全书概要与术语表。缺失或过期时停止；不会退回人读版或旧式 `Glossary.json`。显式 JSON 配置仍由调用者选择兼容格式。
- `当前场景`：日语轻小说 -> 简体中文。
- `通用目标`：多源语言、多目标语言和多文本类型；尚未实现，不得反向限制为固定日轻工作流。
- `质量顺序`：信（不增删误译）优先于达（清晰自然），达优先于雅（风格润色）。下游润色不得覆盖源文证据。
- `部分实现`：采集器产出的同一份完整可见原文分别进入两条清洗流程；AI 版按识别效率选择转换，人读版按阅读体验选择转换。两版不是不同来源，也不由一版复制另一版。Kakuyomu 完整采集并物化后自动调用双版本清洗器；之后计划与翻译默认从 `RAWs_AI` 读取通过索引、镜像字节哈希和归档 lineage 元数据核验的 AI 清洗正文。`SourceArchive` 只保存不可变归档文件与清单：章节映射用 `raw_file`/`source_version_id` 记录归档来源，另用 `source_input_file`/`source_sha256` 指定和校验实际 AI 输入；运行时读取归档清单元数据，不读取归档章节正文。`source_input_file` 的 SHA-256 是 AI 镜像原始字节哈希；概要/知识 provenance 可按换行规范化文本记录哈希，二者用途不同。通用项目模式同样默认选 AI 版；支持 `--project`、`TRANSLATOR_PROJECT` 和无参数唯一项目自动发现。多个项目同时存在且未显式选择时失败关闭。AI 版缺失、过期或不完整时失败关闭，不读取人读版 `生肉/`。没有项目且没有 JSON 配置时也失败关闭，不退回仓库根 `生肉/`。项目名模式还要求绑定当前完整 AI 章节映射的已审核全书概要；Kakuyomu 流程另需匹配当前映射的计划审批回执。Kakuyomu 只有显式指定 `--source-edition normalized_source` 才改用采集器规范化版本。显式 JSON `RAW_DIR`/`CHAPTER_MAP` 是调用者配置的输入来源，也可用于需要人工指定旧版目录的场景，且保留旧 Markdown 概要兼容行为。用户指定路径、profile 与验收边界见[双版本清洗实施](source-ingestion-and-publication-plan.md#2026-11-17-双版本清洗实施)。人读版观感仍待人工验收。

## 当前流水线

| 顺序 | 当前阶段 | 责任 | 外发数据类别 | 证据/边界 |
| --- | --- | --- | --- |
| 0 | 上下文标注 | 推断段落说话人和上下文提示 | `source_text`、`book_knowledge` | `pipeline.py::_run_context_annotation`；请求校对模型；校验结构化字段、段落顺序和源段落原样保留 |
| 1 | 初译 | 使用书籍上下文及词条翻译段落数组 | `source_text`、`book_knowledge` | `prompts/translator_skill.md`；要求 1:1 JSON 数组 |
| 2 | 逻辑校对 | 对照原文和初译，返回严重度、意见、修订段落 | `source_text`、`translation_text`、`book_knowledge` | `prompts/proofreader_skill.md`；源码用 `STRICT_REFLECTION_MODE` 控制反思重试 |
| 3 | 文风润色 | 对校对译文进行中文风格调整 | `source_text`、`translation_text`、`book_knowledge` | `prompts/polisher_skill.md`；接受结构化段落响应 |
| 4 | 保存与学习 | 校验段落映射、文本非空及每段日文引号序列；提交前复读源文并在版本映射场景复核 manifest，再保存输出和 TM | 不调用 Provider | `pipeline.py::run_chapter`、`chapter_transaction.py`、`utils.py::require_aligned_paragraphs`；源文变化或格式门禁失败时不写输出/TM；逐章恢复日志先记录预期结果，TM 更新采用候选状态并在原子写成功后切换进程内状态。重跑优先验证并恢复待处理日志；源文、输出或 TM 基线冲突时停止且不覆盖。源文复读与提交之间仍无并发写锁 |

若 `STRICT_REFLECTION_MODE` 开启，反思重译还会接收 `translation_text`，其类别为三类全集。为同一 Provider 复用多个阶段时，预检要求该 Provider 覆盖它实际负责阶段的类别并集；启用 Gemini 回退时，对 Gemini 按相同阶段类别预检。`PROVIDER_DATA_POLICY` 仍默认拒绝未获准的远端数据。

当前流程不是多 Agent 服务集群；各阶段在同一 Python 进程中顺序调用模型接口。

未提供显式 `CHAPTER_MAP` 时，普通目录扫描与 `scripts/align_chapters.py` 只枚举配置目录第一层 Markdown，不递归扫描；项目名翻译模式必须有 `SourceArchive/`、`RAWs_AI/` 并通过 AI 清洗索引核验，再生成版本绑定映射，不扫描人读版目录。缺少 AI 版时明确失败；如确需旧目录，必须通过显式 `--config` 指定。项目名模式还要求 `Knowledge/STORY_SUMMARY_reviewed.json` 通过审核、覆盖完整 AI 章节映射并匹配所有文件/来源版本；缺少或过期时在读取其他知识前失败。旧 Markdown 概要兼容仅适用于显式 JSON 配置。`workflow_paths.json` 可分别设置已存在的译文 `output_dir` 和可选人读版 `human_edition_root`，两者不得重叠原文根；未设置人读根时默认为项目 `生肉/`。空章节扫描会明确失败；对齐器在全部译文缺失时也会非零退出且不保存 TM。本书采集版本归档在 `projects/祝福のネトラレラ/SourceArchive/`，翻译输入 AI 版在 `projects/祝福のネトラレラ/RAWs_AI/`，人读版在 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉`，译文根在同书外部目录 `...\熟肉`。人读版按 `<章节名>/<话名.md>` 组织；仓库通用默认 `projects/祝福のネトラレラ/生肉`、`熟肉` 不是本书实际位置。路径证据见[项目现状](project-status.md#未知与待验证)及[开发与验证](development.md#2026-11-17-raws-ai-作为默认翻译输入)。`projects/祝福のネトラレラ/EPUB/` 中的文件库存不代表章节映射或正文格式已验收。普通 Kakuyomu 项目仍需人工审阅章节名称/位置、来源版本、输出路径和 TM 键后再创建审批回执并真实调用。

显式 JSON 配置现支持 `CHAPTER_MAP`：每项包含 `raw_file`、`translation_file` 和唯一 `tm_key`，并可选 `source_version_id`。AI 版映射还可包含 `source_input_file` 与 `source_sha256`；此时调用方同时提供 `source_input_root`，加载和每次读取都会校验 AI 镜像字节哈希与归档 manifest 登记的 artifact `content_sha256` 一致。运行时读取归档 manifest 元数据进行版本/lineage 检查，不打开归档正文；`raw_file` 是 manifest 内归档相对路径，不是 AI 翻译正文的读取路径。使用版本 ID 时还须配置相对 `RAW_DIR` 的 `SOURCE_MANIFEST_PATH`；流水线/对齐/知识抽取会校验 manifest 中 artifact 类型、路径和 lineage 元数据，TM/知识来源记录保留归档版本 ID，TM 只读审计可复核它。物理归档字节由 `scripts/validate_source_manifest.py`、`scripts/validate_source_editions.py` 等显式验证命令核验。旧三字段映射保持兼容。清单顺序就是处理顺序；路径相对各自根目录，输出父目录需预先存在。Kakuyomu 的 AI 版入口将 `SOURCE_MANIFEST_PATH` 指向 `source_editions_manifest.json`，其中的 AI artifact 仍以当前 raw 版本为父版本；翻译正文从 `RAWs_AI` 读取，提交前复核 AI 输入哈希及归档 lineage 元数据。版本化通用流水线遇到已有译文/TM 时，只跳过与当前原文、版本、译文文件和 TM 配对完全匹配的已提交结果；否则保留旧数据并阻断。`scripts/snapshot_downstream_freshness.py` 可显式生成 manifest 绑定的只读审核快照；Kakuyomu 完整编排在生成计划后自动追加翻译前快照，成功翻译后追加翻译后快照。Kakuyomu 自动快照记录 TM、知识来源和已审核全书概要的状态及输入哈希，不含正文；按内容寻址，相同状态复用旧快照、变化时追加新快照。手动 CLI 仍按 `--output` 路径排他新建。单独运行 Kakuyomu 采集 CLI 时可显式传入 `--project <项目名>`，它要求 source/output 根均为该项目 `SourceArchive/`，同步来源历史到 `source_editions_manifest.json` 并追加含 AI 索引状态的新鲜度快照；缺 AI 索引时记为 `unverified`，来源或 catalog 前进时记为 `stale`。此模式不清洗双版本、不更新 AI 索引；完整采集到清洗与默认 AI 翻译输入仍由 `scripts/run_kakuyomu_workflow.py` 负责。不传 `--project` 时来源 CLI 保持 source-only 行为。快照不改写消费者数据、不替代运行时门禁，也不自动重建译文/知识。概要审计需与当前版本化章节映射核对全书覆盖。配置示例与验证边界见[开发与验证](development.md#2026-11-17-独立-kakuyomu-采集的项目新鲜度留档)。

## 映射预览与人工核验

对已有 Kakuyomu catalog，可在不读取 Provider 配置、不联网、不写文件的情况下生成映射预览。默认从来源归档同级的 `RAWs_AI` 选择 AI 清洗版本；`--ai-edition-root` 可覆盖该目录。计划会核对 `catalog.json`、`source_editions_manifest.json`、AI 镜像和版本归档，并把 profile、索引/清单哈希、逐话 `RAWs_AI` 输入路径/哈希和归档版本纳入审批摘要：

`RAWs_AI` 提供 AI 版索引、镜像和实际翻译正文；`SourceArchive/editions/ai-efficient-v1/` 下的不可变 artifact 只用于版本归档。翻译、章节对齐、知识抽取、概要/TM 审计读取正文时打开的是 `RAWs_AI` 镜像；运行时只读取归档 manifest 元数据核对登记的字节摘要和 lineage，不打开归档章节正文。两份正文的实际归档字节是否匹配，由显式来源/双版本验证器核对。人读版目录不在默认翻译输入链路中。`SourceArchive/` 仅容纳来源归档数据、其清单/采集状态及不可变校验快照。待审翻译计划保存在项目 `Workflow/Plans/`，审批回执保存在 `Workflow/Approvals/`；计划和回执 CLI 都不允许将工作流文件写入 `SourceArchive/`。

```powershell
python scripts/run_kakuyomu_workflow.py `
  --source-root projects\祝福のネトラレラ\SourceArchive `
  --catalog source_catalog.refresh-2026-11-16.json `
  --translation-root <熟肉目录> `
  --manifest source_manifest.json `
  --edition-manifest source_editions_manifest.json `
  --plan-only `
  --plan-output <计划文件.json>

python scripts/approve_translation_plan.py `
  --plan <计划文件.json> `
  --receipt <审批回执.json> `
  --reviewer <审核者标签>

python scripts/run_kakuyomu_workflow.py `
  --source-root projects\祝福のネトラレラ\SourceArchive `
  --catalog source_catalog.refresh-2026-11-16.json `
  --translation-root <熟肉目录> `
  --manifest source_manifest.json `
  --edition-manifest source_editions_manifest.json `
  --config <项目配置.json> `
  --approval-receipt <审批回执.json>
```

计划核对 catalog 与 manifest 的作品/章节元数据，验证最新 raw 与 normalized artifact 文件哈希及父版本关系，并标记已存在的译文目标。默认 AI 版模式要求索引完整覆盖 catalog 的 episode ID/位置/标题；每个 AI 输出须同时匹配版本归档清单和 `RAWs_AI` 镜像哈希，且清洗版本必须以当前 raw 为父版本。指定 `--source-edition normalized_source` 才改用采集器规范化版本。stdout JSON 只含章节 ID、位置、标题、来源相对路径/版本、目标路径、TM 键和问题代码，不包含原文/译文/知识内容。`--plan-output` 会排他新建一个 JSON 文件；目标已存在时拒绝覆盖。`ready_for_review` 只表示本地来源与映射检查通过，尚不表示人工批准；存在来源缺失、过期、损坏、元数据错配或目标冲突时计划为 `blocked`。

审批 CLI 展示每条映射并要求操作者输入计划的完整 SHA-256。摘要绑定作品 ID、解析后的原文/译文根目录、catalog/manifest 路径，以及逐话 ID、位置、标题、来源文件与版本、译文目标和 TM 键；AI 模式还绑定 profile、AI 索引根/路径/hash 与版本清单路径/hash。审核者标签与时间一并写入新回执。回执是本地普通 JSON 文件，未签名、未认证审核者身份；它记录人工声明，不证明审核者身份或判断质量。计划或来源身份变化会使旧摘要/回执失效。

`main` 经 Kakuyomu 编排入口执行翻译时要求 `--approval-receipt`。无回执时工作流在创建 `TranslationPipeline` 和调用 Provider 前返回 `approval_required`。同一映射因已存在译文目标而重新计划时，可继续使用匹配的旧回执；该例外仅适用于计划没有其他问题且全部来源仍通过核验的情况。执行前还会检查既有译文和 TM 是否与本次来源及事务状态一致，不一致则停止。此门禁由 PR #62 合并；验证记录见[开发与验证](development.md#2026-11-16-翻译计划审批门禁pr-62-已合并)。

## 上下文来源

- `作品基本信息.json`：标题、作者等项目元数据。
- `Glossary_reviewed.json`：项目名模式使用的、绑定当前 AI 来源版本的已审核术语 bundle；缺失、过期或不匹配时停止。`Glossary.json` 仅保留为显式 JSON 配置的兼容输入，按当前章节原文启发式匹配，不等同于已审核术语。
- `guidelines.txt`：全局及章节指导；缺失章节会尝试语义匹配/邻章回退。
- `STORY_SUMMARY.md`：按当前章节裁剪的故事概要。
- `translation_memory.json`：相似段落译文示例的完整可写存储。新流水线/对齐写入会附带可选顶层 `source_provenance`（文件哈希与段落序号）；覆盖章节时若未提供新索引，会清除该章旧索引，避免其指向新条目。来源索引不是审核或批准状态。`scripts/apply_tm_review.py` 可为来源完整核验的原译对生成回执并发布 approved-only 快照；RAG 默认只检索显式配置且通过当前来源核验的 `TM_REVIEWED_PATH` 快照。没有快照时不检索候选 TM，也不生成查询 embedding；仅显式设置 `ALLOW_UNREVIEWED_TM=true` 才恢复完整 TM 的兼容检索，已配置快照始终优先。流水线仍向完整可写 TM 保存新候选。详情与限制见[知识库治理](knowledge-governance.md#tm-审核回执与显式检索快照局部实现)。

检索结果是建议上下文，不是事实校验器。低置信度、冲突和缺失信息应标记出来，不得由 Agent 静默补全。

## 原文来源与发布衔接

- 项目名模式及 Kakuyomu 编排器在版本化来源归档布局下都默认选用经验证的 AI 清洗版；显式 JSON `RAW_DIR`/`CHAPTER_MAP` 仍可配置其他来源。Kakuyomu adapter 可从作品主页发现按 `tableOfContentsV2` 分组排列的公开 episode ID/title，并读取 `Chapter` ID、标题和层级；discovered catalog schema v2 还保存每组 episode ID 和连续目录位置范围，schema v1 显式 catalog 继续兼容。发现时校验唯一条目数等于 `publicEpisodeCount` 后生成普通 episode URL，再逐话请求目录页面。用户是普通读者，主页发现是本试点要求的路径，不依赖作者 ZIP。`scripts/ingest_kakuyomu_pages.py --work-url` 可在无 Provider 配置时发现并归档原文；历史 source-only 运行已获取 88/88 个主页公开话目，生成 88 个单话 Markdown 和一份有序全书 export。`scripts/run_kakuyomu_workflow.py --work-url` 在采集完成后自动分别生成 AI 与人读版，之后默认从 `RAWs_AI` 读取 AI 清洗正文并形成确定性译文路径、TM 键和版本映射；映射以 `source_input_file`/`source_sha256` 指定实际正文，以 `raw_file`/`source_version_id` 记录 `SourceArchive` 归档来源。运行时检查 `robots.txt`，不登录、不跟随重定向、不访问 `/read`；站点目录/count 结构不符时停止。parser v4 保留段落、ruby、旁点及 U+3000；本地离线 catalog diff 可报告快照变化并排他导出新增/元数据更新子集。作品元数据可保存为带记录时间和父版本的 manifest `kind=work` artifact。Kakuyomu 来源 CLI 还支持绑定完整基线 catalog/checkpoint 的显式正文全量刷新：仅接受目录完全一致的快照，未变正文复用、变化正文追加 raw 版本并报告新旧哈希；需显式使用新 checkpoint。`SourceArchive` 将可见 UTF-8 原文保存为 `raw_source`，并另存精确页面响应字节为 `raw_page_html`；2026-11-17 对 88 个最新页面完成 parser v4 正文重放校验，历史未归档 HTML 无法恢复。独立清洗的 AI/人类 Markdown 已生成。Kakuyomu 完整编排及显式项目采集模式现自动持久化新鲜度快照；尚未实现将 stale 状态写回各 consumer 记录或自动重建概要/知识/译文。作品元数据对概要/知识的失效传播、人工格式/ruby/旁点验收和真实 Provider 翻译仍未完成。用户明确不要求官方澄清；平台规则风险另行记录，不代表平台背书或公开分发授权。采集范围不包括草稿/私有话，也不证明主页声明以外的完整性。详见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。
- `scripts/export_source_editions.py` 可单独执行；Kakuyomu 编排器在完整采集后直接调用相同清洗器，从同一当前采集来源版本分别生成两种清洗结果。AI 版用于翻译输入，人读版用于阅读呈现。两版索引都记录来源与 raw 版本、输入哈希、清洗 profile 和输出哈希，不通过文件名推断来源关系。`scripts/validate_source_editions.py` 可从当前 raw 字节重算两版并逐字节核验归档和镜像，作为 manifest 哈希检查之外的 profile 一致性验证。项目可用 `workflow_paths.json` 的 `human_edition_root` 指向人读版目录；未配置时默认为项目 `生肉/`。当前版式和试点具体路径见[双版本清洗实施](source-ingestion-and-publication-plan.md#2026-11-17-双版本清洗实施)。
- 全书预读和知识抽取是可选候选生成步骤；上下文超限时需分批并标明未整书输入，候选未审核前不得进入批准知识库。
- Notion 备份与 EPUB 均为派生/副本路径，不替代本地权威内容。详细状态与依赖见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。

## 目标流程约束（待落实）

1. 初译保留不确定点和源文依据，不自行批准新词条。
2. 校对优先查漏译、误译、指代、因果和术语；对来源不足的判断标为待核查。
3. 润色只优化中文表达；保留原文事实、角色声音、段落边界与已批准术语。
4. `已实现` 最终保存前验证非空文本、段落映射及每段 `「」『』` 的种类/数量/顺序；`部分实现` D-11 逐章恢复日志可以在重跑时恢复匹配的输出/TM 更新，但不保证多进程或断电一致性；`计划` 术语一致性和知识变更状态仍需治理闭环。
5. `已实现` 当前硬门禁失败时，不写该章节的译文或 TM；通过现有格式门禁仍不代表语义正确或 TM 已获审核。逐对审核回执/快照发布是`部分实现`；RAG 默认只检索已配置且来源核验通过的快照，无快照时不检索候选，`ALLOW_UNREVIEWED_TM=true` 是显式兼容覆盖。审核者身份可信度、风险分层、更正/废弃规则仍待设计。D-11 恢复边界见`部分实现`状态及[决策记录](decisions/README.md)。

## Agent 输出契约

- 当前契约由 `pipeline.py` 的 response schema、inline 标注格式、`prompts/*.md` 及 `tests/test_pipeline_contracts.py` 共同表达；三种生产提示词输出字段须与调用端 schema 保持一致。
- 新增/修改阶段时，必须同时检查输入字段、输出字段、失败响应、重试次数、日志敏感信息及调用方消费方式。
- 提示词要求 JSON 不等于服务端强制 schema，也不代表响应内容经过语义验收。
- 不在提示词中暴露密钥。外部模型调用声明其实际类别，按上表最小化；仅当 `PROVIDER_DATA_POLICY` 对目标 Provider 覆盖该调用的所有类别时才发送。默认空策略拒绝远端书籍数据；loopback OpenAI-compatible endpoint 与 RAG 的直接本地 HTTP mock 使用本地路径，Gemini SDK 调用始终要求授权。E2E runner 仅为合成 fixture 显式设置 Gemini 测试 grant。用户已明确确认指定作品获得授权；平台自动化访问规则与 Provider/Notion 接收方及数据类别仍分别处理。
