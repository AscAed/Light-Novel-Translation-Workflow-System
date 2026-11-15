# 翻译流程与 Agent 职责

## 适用边界

- `当前场景`：日语轻小说 -> 简体中文。
- `通用目标`：多源语言、多目标语言和多文本类型；尚未实现，不得反向限制为固定日轻工作流。
- `质量顺序`：信（不增删误译）优先于达（清晰自然），达优先于雅（风格润色）。下游润色不得覆盖源文证据。

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

未提供 `CHAPTER_MAP` 时，`pipeline.py::get_chapters` 与 `scripts/align_chapters.py` 只枚举配置目录第一层 Markdown，不递归扫描。项目名模式不会自动选取 `生肉/`、`熟肉/` 下的第一个子目录；发现嵌套目录时要求显式 `--config`，避免按文件系统枚举顺序选错卷或 EPUB。空章节扫描会明确失败；对齐器在全部译文缺失时也会非零退出且不保存 TM。当前试点外部数据根目录包含已归档的公开来源和知识文件，译文目录为空；根目录、权限与数据类别须以实际配置为准。`projects/祝福のネトラレラ/EPUB/` 中的文件库存不代表章节映射或正文格式已验收。通用 `CHAPTER_MAP` 契约已实现；Kakuyomu 试点可先用下方 plan-only 命令核验确定性映射，仍需人工审阅来源标题、位置、来源版本、输出路径和 TM 键后再真实调用。

显式 JSON 配置现支持 `CHAPTER_MAP`：每项包含 `raw_file`、`translation_file` 和唯一 `tm_key`，并可选 `source_version_id`。使用版本 ID 时还须配置相对 `RAW_DIR` 的 `SOURCE_MANIFEST_PATH`；流水线/对齐/知识抽取会校验 manifest 中 artifact 类型、路径和字节哈希，TM/知识来源记录保留版本 ID，TM 只读审计可复核它。旧三字段映射保持兼容。清单顺序就是处理顺序；路径相对各自根目录，输出父目录需预先存在。通用配置仍可由操作者逐项核定；Kakuyomu 编排 CLI 则按 catalog 显式给出的 episode ID/位置生成稳定译文路径、TM 键和来源版本映射，不按标题或目录顺序猜测作品章节。版本变化后的译文过期标记也尚未实现。配置示例与约束见[开发与验证](development.md)。

## 映射预览与人工核验

对已有 Kakuyomu catalog，可在不读取 Provider 配置、不联网、不写项目数据的情况下生成映射预览：

```powershell
python scripts/run_kakuyomu_workflow.py `
  --source-root <生肉目录> `
  --catalog source_catalog.discovered.json `
  --translation-root <熟肉目录> `
  --manifest source_manifest.json `
  --plan-only
```

命令核对 catalog 与 manifest 中的作品/章节元数据，验证最新 raw 与 normalized artifact 文件哈希及父版本关系，并标记已存在的译文目标。JSON 仅包含章节 ID、位置、标题、来源相对路径/版本、目标路径、TM 键和问题代码，不包含原文/译文/知识内容。`ready_for_review` 表示来源映射可供人工核对，不表示人工已批准；存在缺失、过期、损坏、元数据错配或目标冲突时返回 `blocked` 和非零状态。`plan_sha256` 标识预览 JSON，不是签名回执；正式翻译 CLI 目前不强制提交或复核此摘要。

## 上下文来源

- `作品基本信息.json`：标题、作者等项目元数据。
- `Glossary.json`：按当前章节原文匹配的词条；解析器采用启发式切分。
- `guidelines.txt`：全局及章节指导；缺失章节会尝试语义匹配/邻章回退。
- `STORY_SUMMARY.md`：按当前章节裁剪的故事概要。
- `translation_memory.json`：相似段落检索的译文示例。新流水线/对齐写入会附带可选顶层 `source_provenance`（文件哈希与段落序号）；覆盖章节时若未提供新索引，会清除该章旧索引，避免其指向新条目。旧条目仍可读取且不会自动补录。来源索引不是审核或批准状态。可用 `scripts/apply_tm_review.py` 为来源完整核验的原译对生成回执并发布 approved-only 快照；只有显式设置 `TM_REVIEWED_PATH` 后 RAG 才使用该快照，默认仍检索完整可写 TM。快照详情与剩余限制见[知识库治理](knowledge-governance.md#tm-审核回执与显式检索快照局部实现)。

检索结果是建议上下文，不是事实校验器。低置信度、冲突和缺失信息应标记出来，不得由 Agent 静默补全。

## 原文来源与发布衔接

- 当前翻译输入仍可由项目配置或显式 `CHAPTER_MAP` 指定。Kakuyomu adapter 可从作品主页发现按 `tableOfContentsV2` 分组排列的公开 episode ID/title，校验唯一条目数等于 `publicEpisodeCount` 后生成普通 episode URL，再逐话请求目录页面；也支持显式 catalog。用户是普通读者，主页发现是本试点要求的路径，不依赖作者 ZIP。`scripts/ingest_kakuyomu_pages.py --work-url` 可在无 Provider 配置时发现并归档原文；本次已 source-only 获取 88/88 个主页公开话目，生成 88 个单话 Markdown 和一份有序全书 export。`scripts/run_kakuyomu_workflow.py --work-url` 可进一步生成确定性译文路径、TM 键和 `source_version_id` 映射，并运行现有翻译流水线。运行时检查 `robots.txt`，不登录、不跟随重定向、不访问 `/read`；站点目录/count 结构不符时停止。parser v4 保留段落、ruby、旁点及 U+3000；实际人工格式/ruby/旁点验收和真实 Provider 翻译尚未完成。用户明确不要求官方澄清；平台规则风险另行记录，不代表平台背书或公开分发授权。采集范围不包括草稿/私有话，也不证明主页声明以外的完整性。详见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。
- 计划中的每话 Markdown 将按稳定章节 ID 显式映射到现有流程；清洗版、原始采集版、译文和 TM 需通过版本 ID/哈希关联，不以文件名推测对应关系。
- 全书预读和知识抽取是可选候选生成步骤；上下文超限时需分批并标明未整书输入，候选未审核前不得进入批准知识库。
- Notion 备份与 EPUB 均为派生/副本路径，不替代本地权威内容。详细状态与依赖见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。

## 目标流程约束（待落实）

1. 初译保留不确定点和源文依据，不自行批准新词条。
2. 校对优先查漏译、误译、指代、因果和术语；对来源不足的判断标为待核查。
3. 润色只优化中文表达；保留原文事实、角色声音、段落边界与已批准术语。
4. `已实现` 最终保存前验证非空文本、段落映射及每段 `「」『』` 的种类/数量/顺序；`部分实现` D-11 逐章恢复日志可以在重跑时恢复匹配的输出/TM 更新，但不保证多进程或断电一致性；`计划` 术语一致性和知识变更状态仍需治理闭环。
5. `已实现` 当前硬门禁失败时，不写该章节的译文或 TM；`计划` 通过现有格式门禁仍不代表语义正确或 TM 已获审核。逐对审核快照是`部分实现`且默认关闭；默认检索门禁、身份可信度、风险分层、更正/废弃规则仍待设计。D-11 恢复边界见`部分实现`状态及[决策记录](decisions/README.md)。

## Agent 输出契约

- 当前契约由 `pipeline.py` 的 response schema、inline 标注格式、`prompts/*.md` 及 `tests/test_pipeline_contracts.py` 共同表达；三种生产提示词输出字段须与调用端 schema 保持一致。
- 新增/修改阶段时，必须同时检查输入字段、输出字段、失败响应、重试次数、日志敏感信息及调用方消费方式。
- 提示词要求 JSON 不等于服务端强制 schema，也不代表响应内容经过语义验收。
- 不在提示词中暴露密钥。外部模型调用声明其实际类别，按上表最小化；仅当 `PROVIDER_DATA_POLICY` 对目标 Provider 覆盖该调用的所有类别时才发送。默认空策略拒绝远端书籍数据；loopback OpenAI-compatible endpoint 与 RAG 的直接本地 HTTP mock 使用本地路径，Gemini SDK 调用始终要求授权。E2E runner 仅为合成 fixture 显式设置 Gemini 测试 grant。用户已明确确认指定作品获得授权；平台自动化访问规则与 Provider/Notion 接收方及数据类别仍分别处理。
