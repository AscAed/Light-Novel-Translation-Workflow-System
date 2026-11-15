# 知识库治理

## 当前数据类型

| 数据 | 当前路径/格式 | 当前用途 | 状态 |
| --- | --- | --- | --- |
| 作品元信息 | `Knowledge/作品基本信息.json` | 角色/作品上下文 | 文件存在；字段规范未正式定义 |
| 术语表（兼容格式） | `Knowledge/Glossary.json` | 原文命中后提供 src/dst/info | 文件存在；启发式解析；条目内审核状态未建模 |
| 已审核术语 bundle | 操作者显式设置的 `GLOSSARY_PATH` | RAG 仅消费 bundle 中批准术语 | 本地回执发布与来源新鲜度校验已局部实现；回执未签名/认证 |
| 翻译指导 | `Knowledge/guidelines.txt` | 全局/章节风格与约束 | 文件存在；章节标记依赖约定文本 |
| 故事概要 | `Knowledge/STORY_SUMMARY.md` | 按章节裁剪上下文 | 文件存在；来源和审核流程未定义 |
| 翻译记忆 | `Knowledge/translation_memory.json` | 段落向量检索与 few-shot | 运行时自动写入并原子替换；默认仍直接检索该文件；可选 `TM_REVIEWED_PATH` 快照仅供检索；新条目有可选文件哈希/段落映射，旧条目无回填 |
| 自动提取草稿 | `Glossary_draft.json`、`STORY_SUMMARY_draft.md`、`KNOWLEDGE_PROVENANCE_draft.json` | 实验性候选与输入来源核查 | 脚本校验响应并记录输入哈希、范围和术语出现段落；不构成批准或正式写入流程 |

## 风险

- 自动把译文写回 TM 会将未审校、错位或低质量段落传播到后续章节。
- 译文/TM 是两个文件，不能由单个文件系统原子操作共同提交。`chapter_transaction.py` 现先排他创建逐章恢复日志，再排他写译文并原子更新 TM；成功后删除日志。TM 写入失败或进程中断后，重跑会先验证日志绑定的章节映射、当前源文、译文哈希、格式门禁和 TM 基线，再幂等恢复；内容冲突时停止且不覆盖，日志保留供人工处理。TM 原子写失败时 `RAGEngine` 的磁盘及内存候选状态不变。该局部机制仅支持单写入者的进程中断重试，不提供多进程锁、断电持久性或通用对账；确认原译段落对齐后仍可用 `scripts/align_chapters.py` 手动重建 TM。
- 恢复日志包含完整译文明文，保存在输出文件同目录，最大 64 MiB；完成后删除。SHA-256 仅用于内容一致性校验，不是签名或审核凭证。中断在日志发布前可能遗留临时文件；不支持硬链接的文件系统可能无法创建日志。异常输出、源文或 TM 基线冲突需人工检查，不应手动删除待处理日志后直接继续。
- 知识抽取的三个草稿文件逐个排他写入，不构成文件组事务；来源清单最后写入并标记 `artifact_status: complete`。若异常导致清单缺失/无效，其他草稿可能残留，必须人工核对后再决定是否移走或重跑；脚本不会自动覆盖或清理。
- `scripts/align_chapters.py` 使用启发式段落对齐；对齐失败/错位可能制造错误训练样例。
- 术语表清洗规则以分隔符启发式识别词条和说明，可能错误拆分合法内容。
- 概要、人物关系、语气和文化注释尚无统一来源/置信度/冲突机制。
- 单一 JSON TM 更新可能被并发写入覆盖；并发场景未验证。
- 原子替换只能防止写入中断留下半截 JSON，不能提供多进程合并、版本回滚或知识审核。

## 实施经验与约束

以下结论来自当前实现与已有验证记录，不代表已发生过具体知识污染事故：

- 外部模型数据发送由 `PROVIDER_DATA_POLICY` 明确控制，默认空策略并拒绝远端请求。请求类别为 `source_text`、`translation_text`、`book_knowledge`、`evaluation_samples`；只要该调用包含的任一类别未获对应 Provider 授权，调用就在客户端边界失败。用户已授权 JOJO/JYQF 接收其职责所需的最小类别；默认空策略表示尚未在运行配置中显式启用，不是待用户补充授权。该决定不包括 Gemini embedding、Notion 或其他接收方。loopback OpenAI-compatible endpoint 与 RAG 直接使用的本地 HTTP mock 不属于外发授权判定；Gemini SDK 调用始终检查授权，E2E runner 为合成 fixture 显式配置测试 grant。
- 流水线完成模型阶段并通过当前格式检查后会自动更新 TM；当前门禁拒绝空/非文本段落、段落数错配及逐段 `「」『』` 数量或顺序变化。未通过时不写译文或 TM。通过格式门禁仍不等同于人工批准，也不能证明译文语义正确；阶段 2 仍需确定何时允许进入正式检索集合。
- 章节对齐使用启发式方法。对齐结果需要保留来源并可审查；仅仅成功生成向量或写入 JSON，不构成高质量双语样本的验收。
- `auto_extract_knowledge.py` 生成的是实验性草稿：写入前校验响应结构、必填字段和同一原词的冲突译名，并拒绝覆盖既有草稿。`KNOWLEDGE_PROVENANCE_draft.json` 记录实际送入提示词的章节范围/哈希、样本哈希和可精确匹配的术语段落序号；未命中项保留为空命中。它不验证术语语义，也不为概要逐句归因；其他知识与历史 TM 条目仍缺来源、置信度或审核状态。不得因结构校验或来源命中就将模型建议提升为已批准知识。
- 2026-11-15 新增运行时 fail-closed 子项：`RAGEngine` 拒绝将精确命名为 `Glossary_draft.json` 的文件作为术语输入；翻译流水线启动时拒绝将 `Glossary_draft.json` 或 `STORY_SUMMARY_draft.md` 配置为正式输入，且在读取项目知识前失败。现有 `Glossary.json`、`STORY_SUMMARY.md` 和旧项目格式保持兼容。该检查仅基于抽取脚本的约定文件名；改名后的草稿仍可能被当作正式文件，不构成审核记录、批准 schema 或完整知识状态机。
- 流水线与章节对齐器新写 TM 时在顶层可选 `source_provenance` 中按章节记录原文/译文文本哈希及每个 TM 对应的 1-based 段落序号；哈希针对读取后的 Unicode 文本重新编码为 UTF-8（文本 I/O 会统一换行），不是原始文件字节哈希。显式 `source_version_id` 的原始字节完整性由来源 manifest 的 `content_sha256` 独立验证。对齐无法精确映射时记录 `partial`/`unmatched`，不伪造引用。覆盖章节但未提供新索引时会移除该章旧索引，保留其他章节索引，避免元数据误指向新条目。旧 TM 不迁移，既有无来源条目仍不可追溯。
- Mock 和单元测试可验证本地数据流、格式与失败行为，不能验证真实模型输出或知识正确性。任何知识发布标准都应分别说明自动测试证据与人工/真实样本验收证据。
- 运行诊断不输出生成的校对意见；RAG embedding、知识抽取 CLI 和章节对齐 CLI 的失败信息不包含异常消息正文，以降低章节文本或上游响应被写入控制台/日志的风险。此约束不控制第三方 SDK 或外围调用工具自身的日志。
- 用户选择由专门审核 AI 审核并制定升级规则；风险分层、效果验证和错误条目更正/废弃流程仍需设计。具体外部 API 数据授权仍需人类确认；不得假设审核闭环已实现。
- 后续验收须覆盖候选隔离、审核决定和升级可追溯、冲突保留及更正/废弃；低风险 TM 的门禁与抽查也须有记录。审核 AI 的错误和升级效果需要获准样本评估，不能仅以模型输出或格式校验代替。

## 抽取来源清单 v1

- `schema_version` 固定为 `1`；`producer` 和 `generated_at_utc` 记录生成脚本、Provider/模型及生成时间。
- `prompt_sample_sha256` 校验实际送入模型的完整章节样本文本；`source_files` 记录文件名、完整源文件哈希、实际纳入提示词的字符数/哈希和段落数。
- `glossary_evidence` 仅按原词精确子串匹配，段落序号从 `1` 开始；未找到时 `occurrences` 为空。它是定位线索，不判断该译名或模型说明是否正确。
- `summary_source_chapters` 仅说明概要生成时纳入的章节范围，不给概要中的单条事实提供逐句证据。
- 三份草稿逐文件写入；来源清单最后写入并将 `artifact_status` 设为 `complete`。缺少清单、状态不为 `complete` 或 JSON 无法解析时，整组草稿视为不完整，先人工检查残留文件。
- 2026-11-15 输入/外发前置检查：`scripts/auto_extract_knowledge.py` 按 `Config.PROOFREAD_MODEL` 复用 `get_primary_provider_route`，在读取章节正文前解析匹配的 OpenAI-compatible base URL、Provider ID 和专属 API key，再检查该 Provider 的 `source_text` 授权；创建客户端时再次检查。未知模型名、未授权类别或缺少远端 key 时不读取章节、不创建客户端或草稿。最多读取前 3 个所选章节，每个文件最多 16 MiB，超过上限即在创建 Provider 客户端前拒绝；CLI 只报告通用超限提示，不回显路径或异常正文。单次源文件读取总量因此最多为 48 MiB。随后仍把含章节标记的样本文本截到 20,000 个 Unicode 字符。字节上限控制本地读取量，字符截断不是 token 估算；全书上下文预算、分批抽取和可配置上限仍未实现。当前路由增量的验证见[开发与验证](development.md#2026-11-15-知识抽取-provider-路由对齐)。

## 知识候选来源新鲜度核验

- 执行 `python scripts/validate_knowledge_provenance.py --root <原文数据根目录> --manifest source_manifest.json --provenance <Knowledge目录/KNOWLEDGE_PROVENANCE_draft.json>`，只读核验完整的 provenance v1 草稿及每个 `source_files` 条目；源文本摘要流式计算，不将全文载入内存。
- 记录 `source_version_id` 时，审计会验证所指 manifest artifact 的原始字节哈希、`normalized_source` 类型、相对路径及文本读取哈希，再对比同一 `artifact_id` 的最新追加版本。已有版本过旧时报告 `stale`，最新 artifact 无法校验时报告 `invalid`，来源字段不匹配时报告 `mismatch`。
- provenance 没有 `source_version_id` 时，即使当前文本哈希一致也报告 `unverified`；文本哈希已变化时报告 `stale`。退出码 `0` 表示全部核验通过，`1` 表示发现 stale/mismatch/invalid 或输入无效，`2` 表示存在 unverified。
- 工具不会输出来源正文，也不修改术语草稿、概要、provenance 或版本清单；报告是运行时观察，不是持久化批准/过期状态，不证明候选语义正确或已经审核。

## 草稿输入保护（局部实现）

- 自动抽取输出固定名为 `Glossary_draft.json`、`STORY_SUMMARY_draft.md` 和 `KNOWLEDGE_PROVENANCE_draft.json`。前两个若被显式设置为运行时 glossary 或 summary 路径，程序会在翻译流水线读取项目知识前拒绝启动；直接将 glossary 草稿传给 `RAGEngine` 也会失败。
- 这仅防止直接误配生成的候选文件名，不检测文件内容或 provenance 状态，也无法阻止重命名/复制到正式路径。现有正式路径仍是兼容的旧数据格式，不能据其文件名推断每条内容已审核。
- 2026-11-15 合成回归：草稿 glossary 被 RAG 拒绝；配置草稿 summary 时流水线在读取知识和构造 RAG 前拒绝。相关 12 模块和 mock E2E 结果见[开发与验证](development.md)。

## 审核回执与已批准术语表（局部实现）

- `scripts/apply_knowledge_review.py` 从固定的 `Glossary_draft.json`、`KNOWLEDGE_PROVENANCE_draft.json` 和显式 `--review` 回执创建一个新的术语表 bundle；输出必须是新文件，不会覆盖既有文件。它也可生成绑定候选哈希的未完成回执模板；不调用 Provider，也不替 reviewer 作决定。
- 回执 schema v1 绑定候选术语表和 provenance 的原始字节 SHA-256；每个候选词条必须且只能有一个 `approved`、`rejected` 或 `escalated` 决定、非空理由，并记录 reviewer 的 Provider/model/review ID 和 UTC 时间。这些身份字段是调用者提供的声明，不签名、不认证，也不能证明某个 AI 实际审阅过内容。
- 发布前要求 provenance 的来源审计全部为 `verified`；重新核对 manifest 中 `normalized_source` 版本、相对路径、原始字节和规范化文本哈希、样本前缀哈希、段落数及术语实际出现位置。输入 JSON 和每个源章节各限制为 16 MiB。审核结论只用于明确批准且有来源命中的术语；没有任何批准项时拒绝发布。输出保留决定、理由、证据位置和哈希，不复制原文正文。
- `RAGEngine` 识别 `_knowledge_review_schema: 1` bundle，验证状态、批准集合、规范化术语摘要和来源新鲜度；加载这类 bundle 时必须提供 `source_root` 与 `source_manifest_path`。该术语摘要是格式/一致性检查，不是签名或防篡改证明。默认 `Glossary.json` 兼容路径不自动切换到审核版，须由操作者显式将 `GLOSSARY_PATH` 配置为新 bundle。
- 先创建模板：`python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --create-template review_receipt.json`。模板为每个术语预填 `pending`，并绑定候选文件原始字节哈希；它不含批准结论，不能直接发布。完成 reviewer 信息、UTC 时间、每项决定和理由后，再执行：`python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review review_receipt.json --output Glossary_reviewed.json`。模板和 bundle 都是排他新建，既有文件不会覆盖；候选文件在审阅期间变化时，原哈希绑定会使发布失败。回执 schema、完整合成测试与限制见[开发与验证](development.md)。
- 概要候选可使用 `scripts/apply_story_summary_review.py --knowledge-root <Knowledge目录> --create-template summary_review.json` 创建 `pending` 回执；补全 reviewer、UTC 时间、`approved`/`rejected`/`escalated` 决定和理由后，运行 `python scripts/apply_story_summary_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review summary_review.json --output STORY_SUMMARY_reviewed.json`。发布器绑定概要和 provenance 候选哈希，只接受明确批准，并要求 `summary_source_chapters` 与带 `source_version_id` 的 provenance 来源顺序一致、manifest 中均为最新 `normalized_source`。输出不复制原文正文；候选哈希在发布时核验，概要 bundle 与来源新鲜度会在翻译流水线初始化时再次检查。概要 JSON bundle 必须显式配置为 `STORY_SUMMARY_PATH`，且需要 `SOURCE_MANIFEST_PATH`；既有 Markdown 手工概要保持兼容，但不提供审核/来源新鲜度证明。回执和 bundle 都是本地可编辑、未签名 JSON，哈希只检测未同步修改，不认证审核者或证明语义正确。
- 这是候选隔离与局部发布机制，不是端到端 AI 审核服务或完整知识状态机。它不验证回执的签名、审核者身份或模型质量，不审核人物设定，不实现风险分层、升级效果评估、冲突更正/废弃或历史迁移；TM 仅有需显式启用的局部检索快照，默认仍未设审核门禁，因此阶段 2 仍为`部分实现`。

## TM 来源索引 v1

- TM 顶层的 `source_provenance` 按章节文件名索引，记录 `producer`、源/译文文件名与 SHA-256，以及 `pair_mappings`。
- 每个映射对应 `chapters[章节名]` 中相同 1-based 序号的条目；其 `raw_paragraph_indices` 和 `translation_paragraph_indices` 是相对各原始章节文件的 1-based 段落序号。
- 每一侧的段落引用必须随 TM 条目序号严格递增且不重叠；共享 schema 校验在持久化前拒绝重复或倒序映射。
- `trace_status` 为 `matched`、`partial` 或 `unmatched`，只描述文本位置是否映射成功，不表示译文正确或经过审核。
- 字段为可选，旧 TM 读取不要求迁移；带索引的新写入会替换该章节索引，不带索引的覆盖写入会清除该章旧索引。来源哈希基于应用读取的 UTF-8 文本，不含正文副本。

## TM 来源核验

- 执行 `python scripts/validate_tm_provenance.py --project <项目名>` 可只读核对来源文件哈希、段落序号与 TM 中保存的原译词对。配置 `SOURCE_MANIFEST_PATH` 时，还会验证记录的 `source_version_id`，并在同一 `artifact_id` 有更新的 `normalized_source` 版本时报告 `stale`；未配置 manifest 的版本关联报告为 `unverified`。
- 工具通过 `read_child_text` 读取配置目录内的文件，拒绝路径穿越和符号链接；不修改或修复 TM。
- 退出码 `0` 表示所有已索引章节核验一致，且没有未索引章节；`1` 表示索引结构、哈希、引用范围或词对内容不一致；`2` 表示旧 TM 无索引、来源映射为 partial/unmatched 或源文件不可读取。`2` 表示证据不完整，不代表通过。
- 核验只证明记录与当前文件的结构和文本位置一致，并可指出 manifest 中存在更新来源版本；它不自动改写或标记译文/知识状态，也不判断译文准确性、知识审核状态、原文授权或模型输出质量。

TM 与知识 provenance 的源文本摘要均针对文本模式读取后重新编码的 UTF-8，不等同于 manifest 对字节保真的 `.md` 文件计算的原始字节摘要。审计分层核验这两种摘要；尤其不能直接比较 CRLF 文件的字节哈希与换行统一后的文本哈希。

## TM 审核回执与显式检索快照（局部实现）

- 先为当前 TM 和已验证来源创建 `pending` 回执模板：`.venv\Scripts\python.exe scripts\apply_tm_review.py --tm <Knowledge\translation_memory.json> --source-root <原文数据根目录> --translation-root <译文数据根目录> --manifest source_manifest.json --chapter 第1話.md --create-template tm_review.json`。`--chapter` 可重复指定 TM 章节键；省略时选择全部章节。所选章节必须具有当前 manifest 版本、完整且新鲜的原/译文哈希与逐对映射，所有 pair embedding 维度必须一致。
- 模板绑定完整 TM 文件和 manifest 原始字节 SHA-256，并为每个原译对生成内容哈希。填写 `reviewer.provider_id`、`model_id`、`review_id`、UTC `reviewed_at_utc`，并为每一对填写 `approved`、`rejected` 或 `escalated` 及非空理由后，发布：`.venv\Scripts\python.exe scripts\apply_tm_review.py --tm <Knowledge\translation_memory.json> --source-root <原文数据根目录> --translation-root <译文数据根目录> --manifest source_manifest.json --review tm_review.json --output translation_memory_reviewed.json`。发布前重新核对候选、回执、manifest 和原/译文件；只输出明确批准且 provenance 为 `matched` 的原译对，重排其段落映射。没有批准项或输出文件已存在时拒绝发布。
- 回执模板和审核快照在 TM 所在目录排他新建，不覆盖文件。该工具不调用 Provider 或 AI；审核人、模型和审核时间是未认证声明。SHA-256 绑定用于发现不同步修改，不是签名或防篡改凭证，也不能证明内容已实际审核或译文正确。
- 只有显式将 `TM_REVIEWED_PATH` 设置为已发布快照路径（环境变量或配置 JSON）时，`RAGEngine` 才在初始化时加载该快照，并按当前 manifest、原文和译文重新核验后用于检索。运行时新增 TM 仍写入 `TM_PATH` 的完整可写记忆，不会改写审核快照；TM 或来源变化后旧快照会因哈希/来源不匹配而拒绝加载，应重新审核并排他发布新文件。未设置 `TM_REVIEWED_PATH` 时保持原有行为，直接从完整可写 TM 检索；因此这不是全局默认门禁，旧 TM 也不会自动获得批准状态。
- 该原型不实现审核 AI 调用、审核者认证、风险分层与升级规则、抽查策略、更正/废弃、审核历史迁移或候选冲突解决。完整合成验证与限制见[开发与验证](development.md#2026-11-15-tm-审核回执与显式检索快照)。

## 后续候选知识状态建议

以下是全局知识状态机的设计建议，不是现有 schema；术语审核回执的局部决定格式见上节：

```text
candidate -> reviewed -> approved -> deprecated
```

每条候选知识至少应能追溯书籍、来源章节/段落、原文摘录、提出时间/流程、置信度和审核结论。持久化格式、版本兼容和审核 UI 尚待决策。

## 采集元数据与版本边界

- 来源平台元数据、章节简介、Tag 和全书预读结果都属于外部来源或模型候选，不能因进入项目目录就视为已验证知识。
- 规划中的原始采集、规范化章节、翻译和知识候选需关联来源 ID、版本、哈希及段落位置；来源版本变化时标记依赖该版本的译文/知识待复核，不静默覆盖。
- 将原文/译文备份到 Notion 属于向另一外部服务披露数据，须独立于模型 Provider 的 `PROVIDER_DATA_POLICY` 取得授权。Notion 计划定位为副本，不是批准状态或权威版本的替代品。
- 采集平台许可、来源版本、Notion 同步和删除策略见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)；本节只维护知识信任/审核规则。

## 建议写入规则

1. 翻译、对齐或抽取阶段只产生候选，不自动把新术语/剧情推断标为已批准。
2. 依据来源区分原文明确事实、译者决策、模型推断和外部解释。
3. 发生冲突时保留冲突及证据，不能以最近写入值静默覆盖。
4. TM 只有经过格式/段落验收的原译对才可进入正式检索集合；当前可显式配置来源核验过的 approved-only 快照，但默认检索和 TM 写入仍不受其门禁保护。低风险 TM 的抽查与风险分层仍待设计、验证。
5. 支持更正、废弃和回溯；不得通过删除历史证据掩盖知识污染。
6. 不默认将一本书的私有术语/剧情知识跨书共享。

## 需要人类决策

- `需要人类决策`：哪些项目数据允许发送到各外部模型/API，以及是否允许保存供应商请求日志。
- `计划`：专门审核 AI 制定升级规则并执行风险分层审核；术语候选先审核，高风险人物/剧情事实逐条批准，低风险 TM 经门禁和抽查。风险分类、抽样和效果需设计验证。
- `计划`：按版本保留至用户显式删除，设计本地及远端删除和撤回处理；适用保留义务仍待核实。

具体外发授权未确认前，外发策略保持空表；候选 -> 已批准规则和目标 schema 是设计约束，不能宣称已在软件中生效。
