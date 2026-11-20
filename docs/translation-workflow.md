# 翻译流程与 Agent 职责

> 目标仍是翻译前核对 AI 大合集并建立经审核的全书与局部知识，逐话独立终审后才发布。2026-11-20 起提供显式单话 AI 工作流 CLI：绑定策略/候选摘要，执行双次终审、有限定向返工、复审和通过后发布；失败及人工暂停均不发布。该闭环只经合成验证，语义质量/客观收益阈值、真实 Provider 与试点验收仍未完成。目标契约见[全书到单话翻译目标方案](end-to-end-workflow-target.md)。

> `计划` “信、达、雅”各自的翻译和审核职责、逐级通过、返工及正式发布的依赖和验收见[知识库与翻译闭环实施计划](end-to-end-workflow-target.md#知识库与翻译闭环实施计划)。当前初译、校对和润色的顺序不等于上述逐级语义门禁已实现。

## 适用边界

- 项目名模式的数据解析默认从 `RAWs_AI` 生成待译章节映射，并要求已审核、来源版本仍有效的全书概要与术语表。正式翻译入口是 `scripts/run_kakuyomu_workflow.py`，它先建立活动审核 run，再调用项目流水线；直接运行 `pipeline.py --project` 没有活动 `run_id`，会被拒绝。缺少或过期的输入不会退回人读版或旧式 `Glossary.json`。显式 JSON 配置仍由调用者选择兼容格式。
- 直接未审核翻译需声明输出模式：显式 JSON 添加 `"TRANSLATION_OUTPUT_MODE": "compatibility_draft"`；直接 Python API 设置 `Config.TRANSLATION_OUTPUT_MODE = "compatibility_draft"`。不标记时在创建 pipeline 前失败。该模式输出始终是草稿，不能写入已识别的正式译文根，也不能替代 run 审核发布。项目/Kakuyomu run 使用内部 `reviewed_run_draft`；测试工作区使用 `test_draft`。
- `当前场景`：日语轻小说 -> 简体中文。
- `通用目标`：多源语言、多目标语言和多文本类型；尚未实现，不得反向限制为固定日轻工作流。
- `质量顺序`：信（不增删误译）优先于达（清晰自然），达优先于雅（风格润色）。下游润色不得覆盖源文证据。
- `部分实现`：采集器产出的同一份完整可见原文分别进入两条清洗流程；AI 版按识别效率选择转换，人读版按阅读体验选择转换。两版不是不同来源，也不由一版复制另一版。Kakuyomu 完整采集并物化后自动调用双版本清洗器；之后计划与翻译默认从 `RAWs_AI` 读取通过索引、镜像字节哈希和归档 lineage 元数据核验的 AI 清洗正文。`SourceArchive` 只保存不可变归档文件与清单：章节映射用 `raw_file`/`source_version_id` 记录归档来源，另用 `source_input_file`/`source_sha256` 指定和校验实际 AI 输入；运行时读取归档清单元数据，不读取归档章节正文。`source_input_file` 的 SHA-256 是 AI 镜像原始字节哈希；概要/知识 provenance 可按换行规范化文本记录哈希，二者用途不同。通用项目模式同样默认选 AI 版；支持 `--project`、`TRANSLATOR_PROJECT` 和无参数唯一项目自动发现。多个项目同时存在且未显式选择时失败关闭。AI 版缺失、过期或不完整时失败关闭，不读取人读版 `生肉/`。没有项目且没有 JSON 配置时也失败关闭，不退回仓库根 `生肉/`。项目名模式还要求绑定当前完整 AI 章节映射的已审核全书概要；Kakuyomu 流程另需匹配当前映射的计划审批回执。Kakuyomu 只有显式指定 `--source-edition normalized_source` 才改用采集器规范化版本。显式 JSON `RAW_DIR`/`CHAPTER_MAP` 是调用者配置的输入来源，也可用于需要人工指定旧版目录的场景，且保留旧 Markdown 概要兼容行为。用户指定路径、profile 与验收边界见[双版本清洗实施](source-ingestion-and-publication-plan.md#2026-11-17-双版本清洗实施)。人读版观感仍待人工验收。

## 当前流水线

| 顺序 | 当前阶段 | 责任 | 外发数据类别 | 证据/边界 |
| --- | --- | --- | --- |
| 0 | 上下文标注 | 推断段落说话人和上下文提示 | `source_text`、`book_knowledge` | `pipeline.py::_run_context_annotation`；请求校对模型；校验结构化字段、段落顺序和源段落原样保留 |
| 1 | 初译 | 使用书籍上下文及词条翻译段落数组 | `source_text`、`book_knowledge` | `prompts/translator_skill.md`；要求 1:1 JSON 数组 |
| 2 | 逻辑校对 | 对照原文和初译，返回严重度、意见、修订段落 | `source_text`、`translation_text`、`book_knowledge` | `prompts/proofreader_skill.md`；正式项目路径在无效响应或未解决的 `severe` 时阻断；显式 JSON/兼容路径保留旧回退行为 |
| 3 | 文风润色 | 对校对译文进行中文风格调整 | `source_text`、`translation_text`、`book_knowledge` | `prompts/polisher_skill.md`；正式项目路径对响应契约/段落数据错误失败关闭，兼容路径仍回退至校对结果 |
| 4 | 保存与学习 | 校验段落映射、文本非空及每段日文引号序列；提交前复读源文并在版本映射场景复核 manifest，再保存输出和 TM | 不调用 Provider | `pipeline.py::run_chapter`、`chapter_transaction.py`、`utils.py::require_aligned_paragraphs`；正式项目质量门禁异常发生在提交调用前，本章译文/TM 不写入；源文变化或格式门禁失败时也不写输出/TM。逐章恢复日志先记录预期结果，TM 更新采用候选状态并在原子写成功后切换进程内状态。重跑优先验证并恢复待处理日志；源文、输出或 TM 基线冲突时停止且不覆盖。源文复读与提交之间仍无并发写锁 |

`STRICT_REFLECTION_MODE` 默认关闭；启用时，反思重译还会接收 `translation_text`，其类别为三类全集，正式项目路径在现有反思预算耗尽后仍报告 `severe` 时阻断。代码中的当前两次重试上限是既有实现细节，不是已确认的终审返工策略。正式项目门禁不自动打开反思重译，避免未显式配置时增加模型请求和外发数据类别。为同一 Provider 复用多个阶段时，预检要求该 Provider 覆盖它实际负责阶段的类别并集；启用 Gemini 回退时，对 Gemini 按相同阶段类别预检。`PROVIDER_DATA_POLICY` 仍默认拒绝未获准的远端数据。

当前流程不是多 Agent 服务集群；各阶段在同一 Python 进程中顺序调用模型接口。

## AI 终审与发布

`scripts/review_translation_candidate.py` 对显式指定 run/话目/策略文件执行一次终审。初审绑定已验证 `Drafts/` 草稿；续审必须使用 run 内 `ReviewCandidates/<episode_id>/` 候选。终审器把完整原文、候选和策略 code 定义发送给 `FINAL_REVIEW_MODEL`，每个请求最多 64,000 合并字符且拒绝截断；不发送 book knowledge。模型输出仅接受严格 JSON，finding 只保留策略 code 与原文/译文段落索引。

通过需要两次评估对 fidelity、fluency、style 全部判 pass，优化潜力均为 `none` 或 `low`，且现有八项发布检查在两次评估中全部为 pass。每次结构化评估通过校验后会以原子 create-only sidecar 保存到 `AIReviews/<episode_id>/`；sidecar 绑定 run/source/candidate/policy/reviewer route 和评估序号，仅保存规范化 verdict、登记 code、段落索引和检查项，不包含原文、译文或模型自由文本。重试先校验并复用已有 sidecar，只请求尚缺的评估。此处“none/low”只是用户收敛方向的定性代理，评估结果不证明译文正确或 reviewer 语义独立。通过时程序生成绑定决策、候选路径/哈希和 run 的审核快照，再调用现有 create-only 发布器；该发布器继续复核来源、候选和检查回执。`rework`、`needs_human` 均不会发布。

单次 `scripts/review_translation_candidate.py` 只执行一轮双次评估；闭环入口 `scripts/run_ai_translation_workflow.py` 会在 `rework` 时调用 `PROOFREAD_MODEL` 生成下一候选，再用同策略复审，直到通过或转人工。返工输入是完整 source/candidate 中不超过 64,000 个合并字符，以及阻断 findings、对应策略定义和段落索引；不发送 book knowledge。生成模型仅可返回严格 JSON 中列明的目标段落译文，程序只替换这些段落，保留其余文字和段落分隔，并复核 UTF-8 字节上限、段落对齐和日文引号契约。数据类别为 `source_text`、`translation_text`。终审路由与 `PROOFREAD_MODEL` 必须使用不同的规范化端点和模型身份。

每个返工版本写入 `ReviewCandidates/<episode_id>/revision-NNNN.md`，配套 `AIReworks/<episode_id>/revision-NNNN.json` 只存候选、父决定、审核报告、策略、findings 和路由的摘要/身份，不存正文或模型自由文本。两者均 create-only；重跑可校验并复用已存在候选，不能将没有生成记录的候选伪装成 AI 生成。Provider 返回后、候选落盘前发生进程中断时，重试可能再次调用并计费；响应过长、schema 错误或目标段落不完整则失败关闭，不写候选。

返工预算默认两次，可在初审 CLI 用 `--max-rework-attempts` 设置；续跑读取决策链预算，明确传入的值不匹配时拒绝。预算耗尽后，先用 `scripts/resolve_translation_review.py --action increase_budget --reviewed-decision-sha256 <当前审阅的 decision_sha256>` 追加人工预算回执，再续接工作流。人工回执命令必须绑定操作者实际审阅的最新决定摘要；若决定已变化，需重新审阅后再提交。成功回执 JSON 的 `new_max_rework_attempts` 是获准的新预算。增加预算后续跑时省略 `--max-rework-attempts` 以采用链上预算，或传入该回执中的新值；不能沿用旧值。`approve_current` 同样要求当前审阅的 `decision_sha256`，且不触发 AI 发布；它只允许创建绑定当前候选的人工 checklist，仍需八项检查全部通过后由既有发布器写入。两次终审评估使用相同 reviewer route，不等同于身份认证或独立性证明。

同一话目的终审、返工和完整工作流通过 run 内 `AIWorkflowLocks/<sha256(episode_id)>.lock` 异步文件锁串行化；并发重复调用会在锁内重新读取决策链并恢复已存评估/报告/候选，避免同时发起相同模型工作。进程退出会释放系统锁；Provider 已返回但对应评估 sidecar 尚未原子落盘时中断，重试仍可能重复该次调用并计费。该锁不代替 decision append lock 或人工审批。

```powershell
.\.venv\Scripts\python.exe scripts\review_translation_candidate.py `
  --project <项目目录名> `
  --run-directory <Workflow\Runs\run_id> `
  --episode-id <话目ID> `
  --review-policy-file <review-policy.json> `
  --max-rework-attempts 2
```

显式启动或续接自动返工循环（重跑同一命令会从 run 内决策和候选恢复）：

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_translation_workflow.py `
  --project <项目目录名> `
  --run-directory <Workflow\Runs\run_id> `
  --episode-id <话目ID> `
  --review-policy-file <review-policy.json> `
  --max-rework-attempts 2
```

CLI 在任何模型请求前静态校验 `FINAL_REVIEW_MODEL` 和返工 Provider 配置、角色路由区分及本次所需授权；该检查不连接服务。显式运行前仍需核对凭据、接收方数据政策和输入可外发。本阶段验证使用注入的合成生成器/assessor，未调用真实 Provider，也未对试点数据或译文做人工质量验收。

未提供显式 `CHAPTER_MAP` 时，普通目录扫描与 `scripts/align_chapters.py` 只枚举配置目录第一层 Markdown，不递归扫描；项目名翻译模式必须有 `SourceArchive/`、`RAWs_AI/` 并通过 AI 清洗索引核验，再生成版本绑定映射，不扫描人读版目录。缺少 AI 版时明确失败；如确需旧目录，必须通过显式 `--config` 指定。项目名模式还要求 `Knowledge/STORY_SUMMARY_reviewed.json` 通过审核、覆盖完整 AI 章节映射并匹配所有文件/来源版本；缺少或过期时在读取其他知识前失败。旧 Markdown 概要兼容仅适用于显式 JSON 配置。`workflow_paths.json` 可分别设置已存在的译文 `output_dir` 和可选人读版 `human_edition_root`，两者不得重叠原文根；未设置人读根时默认为项目 `生肉/`。空章节扫描会明确失败；对齐器在全部译文缺失时也会非零退出且不保存 TM。本书采集版本归档在 `projects/祝福のネトラレラ/SourceArchive/`，翻译输入 AI 版在 `projects/祝福のネトラレラ/RAWs_AI/`，人读版在 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉`，译文根在同书外部目录 `...\熟肉`。人读版按 `<章节名>/<话名.md>` 组织；仓库通用默认 `projects/祝福のネトラレラ/生肉`、`熟肉` 不是本书实际位置。路径证据见[项目现状](project-status.md#未知与待验证)及[开发与验证](development.md#2026-11-17-raws-ai-作为默认翻译输入)。`projects/祝福のネトラレラ/EPUB/` 中的文件库存不代表章节映射或正文格式已验收。普通 Kakuyomu 项目仍需人工审阅章节名称/位置、来源版本、输出路径和 TM 键后再创建审批回执并真实调用。

显式 JSON 配置现支持 `CHAPTER_MAP`：每项包含 `raw_file`、`translation_file` 和唯一 `tm_key`，并可选 `source_version_id`。AI 版映射还可包含 `source_input_file` 与 `source_sha256`；此时调用方同时提供 `source_input_root`，加载和每次读取都会校验 AI 镜像字节哈希与归档 manifest 登记的 artifact `content_sha256` 一致。运行时读取归档 manifest 元数据进行版本/lineage 检查，不打开归档正文；`raw_file` 是 manifest 内归档相对路径，不是 AI 翻译正文的读取路径。使用版本 ID 时还须配置相对 `RAW_DIR` 的 `SOURCE_MANIFEST_PATH`；流水线/对齐/知识抽取会校验 manifest 中 artifact 类型、路径和 lineage 元数据，TM/知识来源记录保留归档版本 ID，TM 只读审计可复核它。物理归档字节由 `scripts/validate_source_manifest.py`、`scripts/validate_source_editions.py` 等显式验证命令核验。旧三字段映射保持兼容。清单顺序就是处理顺序；路径相对各自根目录，输出父目录需预先存在。Kakuyomu 的 AI 版入口将 `SOURCE_MANIFEST_PATH` 指向 `source_editions_manifest.json`，其中的 AI artifact 仍以当前 raw 版本为父版本；翻译正文从 `RAWs_AI` 读取，提交前复核 AI 输入哈希及归档 lineage 元数据。版本化通用流水线遇到已有译文/TM 时，只跳过与当前原文、版本、译文文件和 TM 配对完全匹配的已提交结果；否则保留旧数据并阻断。`scripts/snapshot_downstream_freshness.py` 可显式生成 manifest 绑定的只读审核快照；Kakuyomu 完整编排在生成计划后自动追加翻译前快照，成功翻译后追加翻译后快照。Kakuyomu 自动快照记录 TM、知识来源和已审核全书概要的状态及输入哈希，不含正文；按内容寻址，相同状态复用旧快照、变化时追加新快照。手动 CLI 仍按 `--output` 路径排他新建。单独运行 Kakuyomu 采集 CLI 时可显式传入 `--project <项目名>`，它要求 source/output 根均为该项目 `SourceArchive/`，同步来源历史到 `source_editions_manifest.json` 并追加含 AI 索引状态的新鲜度快照；缺 AI 索引时记为 `unverified`，来源或 catalog 前进时记为 `stale`。此模式不清洗双版本、不更新 AI 索引；完整采集到清洗与默认 AI 翻译输入仍由 `scripts/run_kakuyomu_workflow.py` 负责。不传 `--project` 时来源 CLI 保持 source-only 行为。快照不改写消费者数据、不替代运行时门禁，也不自动重建译文/知识。概要审计需与当前版本化章节映射核对全书覆盖。配置示例与验证边界见[开发与验证](development.md#2026-11-17-独立-kakuyomu-采集的项目新鲜度留档)。

## 映射预览与人工核验

对已有 Kakuyomu catalog，可在不读取 Provider 配置、不联网、不写文件的情况下生成映射预览。默认从来源归档同级的 `RAWs_AI` 选择 AI 清洗版本；`--ai-edition-root` 可覆盖该目录。计划会核对 `catalog.json`、`source_editions_manifest.json`、AI 镜像和版本归档，并把 profile、索引/清单哈希、逐话 `RAWs_AI` 输入路径/哈希和归档版本纳入审批摘要：

`RAWs_AI` 提供 AI 版索引、镜像和实际翻译正文；`SourceArchive/editions/ai-efficient-v1/` 下的不可变 artifact 只用于版本归档。翻译、章节对齐、知识抽取、概要/TM 审计读取正文时打开的是 `RAWs_AI` 镜像；运行时只读取归档 manifest 元数据核对登记的字节摘要和 lineage，不打开归档章节正文。两份正文的实际归档字节是否匹配，由显式来源/双版本验证器核对。人读版目录不在默认翻译输入链路中。`SourceArchive/` 仅容纳来源归档数据、其清单/采集状态及不可变校验快照。待审翻译计划保存在项目 `Workflow/Plans/`，审批回执保存在 `Workflow/Approvals/`；计划和回执 CLI 都不允许将工作流文件写入 `SourceArchive/`。

```powershell
python scripts/run_kakuyomu_workflow.py `
  --source-root projects\祝福のネトラレラ\SourceArchive `
  --catalog source_catalog.raw-html-2026-11-17.json `
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
  --catalog source_catalog.raw-html-2026-11-17.json `
  --translation-root <熟肉目录> `
  --manifest source_manifest.json `
  --edition-manifest source_editions_manifest.json `
  --config <项目配置.json> `
  --approval-receipt <审批回执.json>
```

为避免只核对摘要而遗漏双版本人工验收，可先创建不含正文的结构化模板，再在人工检查后生成绑定模板摘要的 schema v2 回执：

```powershell
python scripts/prepare_translation_plan_review.py `
  --plan <计划文件.json> `
  --human-index <人读根>\SOURCE_MAP.json `
  --output <计划审阅.json>

# 人工逐话填写 mapping_decision、ai_edition_decision、
# human_edition_decision；三项均为 pass 且 issues 为空后：
python scripts/approve_translation_plan.py `
  --plan <计划文件.json> `
  --review <计划审阅.json> `
  --human-index <人读根>\SOURCE_MAP.json `
  --receipt <审批回执.json> `
  --reviewer <审核者标签>
```

计划核对 catalog 与 manifest 的作品/章节元数据，验证最新 raw 与 normalized artifact 文件哈希及父版本关系，并标记已存在的译文目标。默认 AI 版模式要求索引完整覆盖 catalog 的 episode ID/位置/标题；每个 AI 输出须同时匹配版本归档清单和 `RAWs_AI` 镜像哈希，且清洗版本必须以当前 raw 为父版本。指定 `--source-edition normalized_source` 才改用采集器规范化版本。stdout JSON 只含章节 ID、位置、标题、来源相对路径/版本、目标路径、TM 键和问题代码，不包含原文/译文/知识内容。`--plan-output` 会排他新建一个 JSON 文件；目标已存在时拒绝覆盖。`ready_for_review` 只表示本地来源与映射检查通过，尚不表示人工批准；存在来源缺失、过期、损坏、元数据错配或目标冲突时计划为 `blocked`。

审批 CLI 展示每条映射并要求操作者输入计划的完整 SHA-256。摘要绑定作品 ID、解析后的原文/译文根目录、catalog/manifest 路径，以及逐话 ID、位置、标题、来源文件与版本、译文目标和 TM 键；AI 模式还绑定 profile、AI 索引根/路径/hash 与版本清单路径/hash。使用结构化模板时，回执 schema v2 另绑定 `review_sha256`，验证时会重算当前人读索引、逐话映射和索引指向的实际文件摘要，拒绝 pending/failed 决定、未解决 issues、缺话、文件哈希不符或索引变化。审核者标签与时间一并写入新回执。回执是本地普通 JSON 文件，未签名、未认证审核者身份；它记录人工声明，不证明审核者身份或判断质量。计划或来源身份变化会使旧摘要/回执失效。schema v1 回执仍可读取，但不包含双版本人工审阅证明。

`main` 经 Kakuyomu 编排入口执行翻译时要求 `--approval-receipt`。无回执时工作流在创建 `TranslationPipeline` 和调用 Provider 前返回 `approval_required`。同一映射因已存在译文目标而重新计划时，可继续使用匹配的旧回执；该例外仅适用于计划没有其他问题且全部来源仍通过核验的情况。执行前还会检查既有译文和 TM 是否与本次来源及事务状态一致，不一致则停止。此门禁由 PR #62 合并；验证记录见[开发与验证](development.md#2026-11-16-翻译计划审批门禁pr-62-已合并)。

## 上下文来源

- `作品基本信息.json`：标题、作者等项目元数据。
- `Glossary_reviewed.json`：项目名模式使用的、绑定当前 AI 来源版本的已审核术语 bundle；缺失、过期或不匹配时停止。`Glossary.json` 仅保留为显式 JSON 配置的兼容输入，按当前章节原文启发式匹配，不等同于已审核术语。
- `Knowledge/ChapterDrafts/episode-<position>-<episode-id>-<source-version-hash>-bundle-<bundle-key>/STORY_SUMMARY_reviewed.json`：单话已审概要；Kakuyomu 当前 run 对每个待翻译非空章节都要求其位置、当前来源版本、AI 输入路径/哈希和整书 bundle 身份匹配。缺失或过期时，流水线在任何章节模型调用前阻断；同一来源版本可在新 bundle 目录重新生成候选，旧审核产物保留。
- 同一单话目录下的 `Glossary_reviewed.json` 可选；若存在，只注入当前章节来源验证通过的批准词条，并与全书 reviewed glossary 合并。相同来源词或别名解析出冲突译名时停止。无局部术语文件时继续使用全书已审核术语。
- `guidelines.txt`：全局及章节指导；缺失章节会尝试语义匹配/邻章回退。
- `STORY_SUMMARY.md`：按当前章节裁剪的故事概要。
- `translation_memory.json`：相似段落译文示例的完整可写存储。新流水线/对齐写入会附带可选顶层 `source_provenance`（文件哈希与段落序号）；覆盖章节时若未提供新索引，会清除该章旧索引，避免其指向新条目。来源索引不是审核或批准状态。`scripts/apply_tm_review.py` 可为来源完整核验的原译对生成回执并发布 approved-only 快照；RAG 默认只检索显式配置且通过当前来源核验的 `TM_REVIEWED_PATH` 快照。没有快照时不检索候选 TM，也不生成查询 embedding；`ALLOW_UNREVIEWED_TM=true` 仅为兼容调用覆盖，正式项目翻译会拒绝此配置，已配置快照始终优先。流水线仍向完整可写 TM 保存新候选。详情与限制见[知识库治理](knowledge-governance.md#tm-审核回执与显式检索快照局部实现)。

检索结果是建议上下文，不是事实校验器。低置信度、冲突和缺失信息应标记出来，不得由 Agent 静默补全。

## 原文来源与发布衔接

- 项目名模式及 Kakuyomu 编排器在版本化来源归档布局下都默认选用经验证的 AI 清洗版；显式 JSON `RAW_DIR`/`CHAPTER_MAP` 仍可配置其他来源。Kakuyomu adapter 可从作品主页发现按 `tableOfContentsV2` 分组排列的公开 episode ID/title，并读取 `Chapter` ID、标题和层级；discovered catalog schema v2 还保存每组 episode ID 和连续目录位置范围，schema v1 显式 catalog 继续兼容。发现时校验唯一条目数等于 `publicEpisodeCount` 后生成普通 episode URL，再逐话请求目录页面。用户是普通读者，主页发现是本试点要求的路径，不依赖作者 ZIP。`scripts/ingest_kakuyomu_pages.py --work-url` 可在无 Provider 配置时发现并归档原文；历史 source-only 运行已获取 88/88 个主页公开话目，生成 88 个单话 Markdown 和一份有序全书 export。`scripts/run_kakuyomu_workflow.py --work-url` 在采集完成后自动分别生成 AI 与人读版，之后默认从 `RAWs_AI` 读取 AI 清洗正文并形成确定性译文路径、TM 键和版本映射；映射以 `source_input_file`/`source_sha256` 指定实际正文，以 `raw_file`/`source_version_id` 记录 `SourceArchive` 归档来源。运行时检查 `robots.txt`，不登录、不跟随重定向、不访问 `/read`；站点目录/count 结构不符时停止。parser v4 保留段落、ruby、旁点及 U+3000；本地离线 catalog diff 可报告快照变化并排他导出新增/元数据更新子集。作品元数据可保存为带记录时间和父版本的 manifest `kind=work` artifact。Kakuyomu 来源 CLI 还支持绑定完整基线 catalog/checkpoint 的显式正文全量刷新：仅接受目录完全一致的快照，未变正文复用、变化正文追加 raw 版本并报告新旧哈希；需显式使用新 checkpoint。`SourceArchive` 将可见 UTF-8 原文保存为 `raw_source`，并另存精确页面响应字节为 `raw_page_html`；2026-11-17 对 88 个最新页面完成 parser v4 正文重放校验，历史未归档 HTML 无法恢复。独立清洗的 AI/人类 Markdown 已生成。Kakuyomu 完整编排及显式项目采集模式现自动持久化新鲜度快照；尚未实现将 stale 状态写回各 consumer 记录或自动重建概要/知识/译文。作品元数据对概要/知识的失效传播、人工格式/ruby/旁点验收和真实 Provider 翻译仍未完成。用户明确不要求官方澄清；平台规则风险另行记录，不代表平台背书或公开分发授权。采集范围不包括草稿/私有话，也不证明主页声明以外的完整性。详见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。
- `scripts/export_source_editions.py` 可单独执行；Kakuyomu 编排器在完整采集后直接调用相同清洗器，从同一当前采集来源版本分别生成两种清洗结果。AI 版用于翻译输入，人读版用于阅读呈现。两版索引都记录来源与 raw 版本、输入哈希、清洗 profile 和输出哈希，不通过文件名推断来源关系。`scripts/validate_source_editions.py` 可从当前 raw 字节重算两版并逐字节核验归档和镜像，作为 manifest 哈希检查之外的 profile 一致性验证。项目可用 `workflow_paths.json` 的 `human_edition_root` 指向人读版目录；未配置时默认为项目 `生肉/`。当前版式和试点具体路径见[双版本清洗实施](source-ingestion-and-publication-plan.md#2026-11-17-双版本清洗实施)。
- `scripts/auto_extract_knowledge.py --chapter-position N` 可从已验证 AI bundle 为当前话生成来源版本隔离的局部候选。使用现有 `scripts/apply_story_summary_review.py` 明确批准后，发布器写出同目录 reviewed summary；局部术语候选可用 `scripts/apply_knowledge_review.py` 按词审核并发布。Kakuyomu 翻译在启动时预检所有待翻译非空章节的局部 reviewed summary，逐章上下文再复核；批准的局部概要和可选术语进入当前话上下文。`--full-book` 和单话候选都不证明目录映射或语义质量，未审核候选不会进入知识库。
- Notion 备份与 EPUB 均为派生/副本路径，不替代本地权威内容。详细状态与依赖见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md)。

## 目标流程约束（待落实）

1. 初译保留不确定点和源文依据，不自行批准新词条。
2. 校对优先查漏译、误译、指代、因果和术语；对来源不足的判断标为待核查。
3. 润色只优化中文表达；保留原文事实、角色声音、段落边界与已批准术语。
4. `已实现` 最终保存前验证非空文本、段落映射及每段 `「」『』` 的种类/数量/顺序；正式项目运行另在 `Workflow/Runs/<run_id>/StageReports/` 记录哈希化阶段轨迹和重复尝试，不保存正文或提示词；`部分实现` D-11 逐章恢复日志可以在重跑时恢复匹配的输出/TM 更新，但不保证多进程或断电一致性；`计划` 术语一致性和知识变更状态仍需治理闭环。
5. `已实现` 当前硬门禁失败时，不写该章节的译文或 TM；通过现有格式门禁仍不代表语义正确或 TM 已获审核。逐对审核回执/快照发布是`部分实现`；RAG 默认只检索已配置且来源核验通过的快照，无快照时不检索候选，`ALLOW_UNREVIEWED_TM=true` 是显式兼容覆盖。审核者身份可信度、风险分层、更正/废弃规则仍待设计。D-11 恢复边界见`部分实现`状态及[决策记录](decisions/README.md)。

## 2026-11-18 受审草稿与发布

- Kakuyomu 正式编排先导出并复核完整 raw/AI/human book bundle。full-book 知识 CLI 在 `--full-book` 模式要求当前 catalog、checkpoint、bundle-set、匹配 AI bundle、human root、tokenizer 和预算参数；授权预检通过后才读取 bundle 正文。`KNOWLEDGE_PROVENANCE_draft.json` 保存来源章节及 bundle-set/AI bundle 身份。该能力有合成数据验证，本轮没有对真实书籍调用 Provider。
- 单话抽取使用同一 catalog/checkpoint/bundle-set/AI bundle/human root 与 tokenizer 预算参数，将 `--full-book` 换成互斥的 `--chapter-position <N>`。在输出的 `ChapterDrafts` 子目录分别创建概要/术语待审回执；补全人工决定后，使用 `scripts/apply_story_summary_review.py --knowledge-root <单话目录> --source-root <SourceArchive> --manifest source_editions_manifest.json --review <概要回执> --output STORY_SUMMARY_reviewed.json` 发布概要。若审核了术语，同样用 `scripts/apply_knowledge_review.py` 发布 `Glossary_reviewed.json`。两个发布器均拒绝覆盖；单话概要是正式 Kakuyomu 翻译的必需项，局部术语表为可选项。
- 摘要审核必须声明 full-book coverage，并绑定与本次 workflow 相同的 bundle-set 与 AI bundle 哈希。`TranslationPipeline` 项目模式核对 `Config.EXPECTED_BOOK_BUNDLE`，同时要求完整版本映射；直接运行 `pipeline.py --project` 没有活动 run 状态时会被拒绝。
- 完成翻译后，章节草稿、`run.json`、`StageReports/` 和状态为 `review_pending` 的 `run_state.json` 位于 `Workflow/Runs/<run_id>/`；清单绑定计划、AI index、book bundle、每话来源及草稿 SHA-256。可用 `scripts/record_translation_review_decision.py` 为每话追加内容无关的三阶段决定：初版绑定 `Drafts/<translation_file>`；返工版本须保存到 `ReviewCandidates/<episode_id>/`，并通过 `--candidate-file` 指定。调用方还必须传入审阅时记录的 `--reviewed-candidate-sha256 <sha256>`，程序会在写入决定前重新读取候选并拒绝摘要不一致的内容。策略摘要须明确提供；新决策链最大返工次数默认为 2，可通过 `--max-rework-attempts` 配置。决策链在话目锁内加载、校验并以完整 JSON 原子创建。通过后，`scripts/prepare_translation_review.py --run-directory <run-dir>` 创建绑定最终候选版本、路径和哈希的 schema v2 checklist；链尾未通过不能生成普通可发布 checklist，也不能绕过决策链改走旧 checklist。若链尾因耗尽等原因进入 `needs_human`，操作者应先审阅最新决定，再使用 `scripts/resolve_translation_review.py --run-directory <run-dir> --episode-id <episode-id> --action approve_current --reviewed-decision-sha256 <当前审阅的 decision_sha256> --reviewer <标签> --reviewed-at-utc <UTC时间> --rationale <理由>` 明确接受当前候选；该 create-only 人工回执单独绑定失败决定、候选和失败阶段，不改写原 verdict。若决定摘要已变化，命令拒绝仲裁，必须先重新审阅最新候选。随后只解锁绑定此回执的 schema v3 checklist。人工 checklist 仍须独立性声明、八项检查全部通过且无 issues；最终由 `scripts/publish_reviewed_translation.py --run-directory <run-dir> --episode-id <episode-id> --review <review.json>` 校验输入并 create-only 发布。若选择继续返工，使用 `--action increase_budget --new-max-rework-attempts <更大次数>` 并提供当前审阅的 `--reviewed-decision-sha256` 扩展预算，再将下一版放入 `ReviewCandidates/<episode_id>/` 并重新记录审核；预算只能增加，旧候选/决定均保留。无决策链的旧 run 仍使用 schema v1 checklist。发布回执和快照绑定审核及候选摘要；run 状态核验也会复查实际译文字节。仲裁 reviewer 身份未认证；当前三类 verdict 过粗，不会将一次放行扩散为其他话目的同类失败豁免。
- 若需要按整次 run 处理已完成的审核，可使用 `.venv\Scripts\python.exe scripts\publish_reviewed_run.py --run-directory <run-dir>`。该入口按话目顺序逐项调用同一发布门禁，缺少审核文件或单话失败时保留已完成成果并返回可安全重试的摘要；不会把部分发布报告成整次 run 完成。
- checklist 与决定记录中的 reviewer 身份未签名认证；本地哈希只能绑定数据，不能证明审核者身份、审核质量或策略真实执行。发现不匹配的既有审核快照/回执、候选变动或无效 run 状态时，发布器会停止并保留现场。决策链使用调用方显式提供的阶段判定，不自带语义阈值；生产 Provider/model、返工上限和冲突/耗尽后的人工责任仍待确认。正式门禁为`部分实现`。成功发布按单话进行，不提供整卷多文件事务。
- 未启用正式审核的兼容 pipeline 会拒绝写入项目默认 `熟肉/` 与 `workflow_paths.json` 指定的正式输出根；其他显式 JSON 输出路径无法自动判定用途，仍属于未经审核的兼容输出，不能作为正式发布。显式 `--source-edition normalized_source` 仍可用于计划预览；正式执行会返回 `reviewed_publication_requires_ai_edition`，不调用翻译模型。当前没有部署清单或 Web 应用，本实现是本地 CLI 工作流。

## Agent 输出契约

- 当前契约由 `pipeline.py` 的 response schema、inline 标注格式、`prompts/*.md` 及 `tests/test_pipeline_contracts.py` 共同表达；三种生产提示词输出字段须与调用端 schema 保持一致。
- 新增/修改阶段时，必须同时检查输入字段、输出字段、失败响应、重试次数、日志敏感信息及调用方消费方式。
- 提示词要求 JSON 不等于服务端强制 schema，也不代表响应内容经过语义验收。
- 不在提示词中暴露密钥。外部模型调用声明其实际类别，按上表最小化；仅当 `PROVIDER_DATA_POLICY` 对目标 Provider 覆盖该调用的所有类别时才发送。默认空策略拒绝远端书籍数据；loopback OpenAI-compatible endpoint 与 RAG 的直接本地 HTTP mock 使用本地路径，Gemini SDK 调用始终要求授权。E2E runner 仅为合成 fixture 显式设置 Gemini 测试 grant。用户已明确确认指定作品获得授权；平台自动化访问规则与 Provider/Notion 接收方及数据类别仍分别处理。
