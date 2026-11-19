# Kakuyomu 试点映射人工审阅

状态：`需要人类验收`；当前计划尚未批准。用户已明确要求 AI 清洗版作为默认翻译输入；当前计划在 2026-11-17 原始 HTML 全量刷新后生成，HEAD 基线为 `e2fe611258532c9f0bab3672eda52cf928102b1a`，工作区含未提交改动。

## 当前审阅计划

- 计划文件：`projects\祝福のネトラレラ\Workflow\Plans\translation_plan_review_ai_raw_html_schema2_2026-11-17.json`
- 计划摘要：`331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`；schema v2，由当前 `--plan-only --plan-output` 生成并通过 `translation_plan_approval.load_translation_plan` 校验。
- 范围：作品 ID `16817330668011048405` 当前主页公开目录中的 88 个位置。
- 绑定 catalog：`source_catalog.raw-html-2026-11-17.json`；AI profile：`ai-efficient-v1`。计划摘要同时绑定当前 AI 索引和 edition manifest。
- 默认来源：翻译正文从 `RAWs_AI/` 读取；计划中的 archive `source_file`/`source_version_id` 只标记不可变归档 provenance。88/88 正文输入与对应归档均通过索引、manifest、哈希与 raw lineage 校验。
- 计划状态：`ready_for_review`，0 个问题；episode ID、位置、译文目标和 TM key 各 88 个且唯一；88 个译文目标均不存在。
- 计划 JSON 不含章节正文。生成期间网络请求为 0、Provider 调用为 0、文件写入为 1（仅新建此计划文件）；归档正文与译文目录未写入。88 个 episode ID 与译文目标均唯一，计划状态 `ready_for_review`、0 问题。
- 旧的 `translation_plan_review_ai_raw_html_2026-11-17.json` 是 schema v1；现行校验器拒绝该旧 schema。不得用其摘要 `22db6169...` 或此前 `ai_default`/`ai_append` 摘要创建当前审批回执。
- 书籍数据目录被 `.gitignore` 排除，计划不纳入 Git。

## 审阅范围

- 打开计划 JSON，核对全部 88 条 episode ID、目录位置、AI 来源版本路径、译文目标和 TM key。
- 确认 AI 版输出是翻译系统实际使用的来源版本；计划不得改指人读版或未经 AI 清洗的 collector 来源。
- 对照 AI 版目录检查分组、顺序、章节名/话名映射，并抽查位置与话目编号的对应。
- 人读版 Ruby、旁点、缩进、段落与 Markdown 阅读器显示属于独立的视觉验收，不由该计划摘要证明。

程序验证只能确认当前 catalog、索引、来源版本清单和计划映射结构一致。它不能确认采集正文质量、清洗语义、主页公开目录以外的完整性，也不能代替对目标文件名与 TM key 的人工验收。

## 验收与后续门禁

请先查看计划 JSON 的 88 条映射，并确认：

1. 88 个 AI 来源版本、episode 顺序和作品分组符合预期。
2. 稳定 episode ID 派生的 88 个译文目标文件名及 TM key 符合项目约定。
3. AI 清洗后的原文格式适合后续翻译；若有问题，指出 episode 位置和期望修正。

如果需要调整，请指出位置及期望修改。若确认接受，请明确回复批准当前摘要 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`。收到对这一摘要的明确批准后，再运行审批 CLI 创建本地回执。回执的审核者字段仍是调用者声明，不具备签名或身份认证。

映射批准只通过 Kakuyomu 编排入口的计划门禁，不会自动开始翻译。正式运行还要求与 AI 来源版本一致的已审核全书概要、该计划的审批回执和有效的本地 Provider 配置/授权 allowlist；当前未生成译文，也未调用真实 Provider。

## 2026-11-17 通用翻译入口续接

- 用户再次明确：AI 版是清洗后的翻译原文输入。除 Kakuyomu 编排器默认选择 AI 版外，`pipeline.py --project <项目>` 现在要求项目根有成对 `SourceArchive/`、`RAWs_AI/`，核验 AI 索引、索引绑定的 catalog 摘要与完整 episode ID/title/position 覆盖、来源/清洗清单、所有 AI 文件哈希及 raw lineage，再生成带 `source_version_id` 的章节映射。映射的 `raw_file`/`source_version_id` 记录归档 provenance，`source_input_file`/`source_sha256` 指向实际从 `RAWs_AI` 读取的正文。映射按目录位置生成 `episode-<位置>-<ID>.md` 与 `source-edition:<work_id>:<episode_id>` TM 键。
- AI 来源缺失、不完整、损坏或过期时，通用项目模式停止；不会改读专供人类阅读的 `生肉/`。没有 AI 版的旧项目也会明确失败；如需继续使用旧目录，必须由显式 JSON `RAW_DIR`/`CHAPTER_MAP` 指定。
- 本书本地只读配置验证已从 `projects\祝福のネトラレラ\SourceArchive` 读取 `source_editions_manifest.json`，生成 88 项映射；AI 索引所绑 catalog 摘要及 episode ID/title/position 全覆盖通过，首项来源为 `editions/ai-efficient-v1/...`，映射均带 AI 版本 ID。未调用 Provider、未生成译文。
- 通用项目名翻译模式现与 Kakuyomu 正式入口一样，要求已审核的全书概要 bundle 覆盖当前完整 AI 映射，并匹配逐话文件名及 `source_version_id`；门禁在读取作品信息和构造 RAG 前执行。显式 JSON 兼容配置仍可使用旧 Markdown 概要。试点 `Knowledge/` 当前只有旧 `STORY_SUMMARY.md`，没有 `STORY_SUMMARY_reviewed.json`，因此默认翻译会明确失败；下一步需由 AI 版完整映射生成概要候选，经人工审核后发布匹配 bundle，再进入真实 Provider 配置/审批。
- 本次代码改动：`pipeline.py`、`tests/test_pipeline_contracts.py`；事实文档同步到 README、架构、决策、项目现状、开发与验证、翻译流程、路线图、专题计划及本交接。验证：四模块合并定向回归 131 项通过；`.venv\Scripts\python.exe tests\run_tests.py` 的 7 个本地 mock E2E 通过（240.957 秒，退出码 0）；`py_compile`、`git diff --check`、14 份 Markdown 的 183 个本地文件链接检查通过。
- 本次补充概要门禁的定向回归：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_story_summary_review tests.test_kakuyomu_workflow tests.test_source_editions -q`：142 项通过。只读试点配置解析为 `SourceArchive`、88 项 AI 映射，构造 pipeline 因 reviewed 全书概要缺失而在加载知识、RAG 和 Provider 前失败。`.venv\Scripts\python.exe tests\run_tests.py` 本地 mock E2E 7 项通过，221.968 秒，退出码 0；runner 中内容拦截/段落数量错误为预期负向 fixture。没有生成候选概要或译文，也未调用真实 Provider。
- 截至该历史记录形成时，计划 `8a567956...` 后由追加 catalog 的 `1d7ae1ce...` 取代；二者现均已被顶部当前计划再次取代。历史摘要不代表通用项目映射获批，也不触发翻译。项目采集与完整编排已实现不可变新鲜度快照；当前边界见[开发与验证](../development.md)。工作区原有未提交改动需全部保留；执行额度不可见，不声称任何额度阈值。

## 2026-11-17 I4 译文来源版本保护续接

- `pipeline.py` 通用项目版本映射现不会把既有输出文件直接当成成功跳过。只允许已提交 TM provenance、原文哈希、译文哈希、配对内容和 source version 全部匹配当前章节映射的译文跳过；过期/未索引/损坏的现有输出或 TM 会被保留并阻断。无版本 ID 的旧式显式目录路径行为不变。
- 新增 `chapter_transaction.py::is_chapter_translation_committed` 供流水线核验当前提交状态。`tests/test_pipeline_contracts.py` 增加旧来源译文被阻断且字节不变、当前版本已提交译文正常跳过两个用例。
- 验证：五模块回归 139 项通过；`.venv\Scripts\python.exe tests\run_tests.py` 本地 mock E2E 7 项通过（223.785 秒，退出码 0）；`py_compile`、`git diff --check` 通过。正向复用测试覆盖多段 Windows CRLF 译文。实际项目只读仍为 88 项 AI 版来源映射。未调用 Provider、未生成译文。
- 本段记录形成时，freshness 快照仍需手动生成；2026-11-17 后续已将自动留档接入 `scripts/run_kakuyomu_workflow.py` 的翻译前/后流程，以及 `scripts/ingest_kakuyomu_pages.py --project` 的来源采集完成路径。快照按内容寻址追加，记录 manifest 与 TM/知识/概要/AI 索引状态及输入哈希，不写正文。快照不改写消费者数据、不自动重建下游；各消费者仍依当前 manifest 执行自己的运行时门禁。不要把独立消费者数据写回或派生物自动重建描述为已实现。
- 本续接的定向回归 `.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_pipeline_contracts tests.test_story_summary_review tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow -q`：163 项通过；当前真实项目无参数默认解析为 88 条 AI 清洗版映射，译文根为用户指定外部 `熟肉`。本地忽略配置 `projects/祝福のネトラレラ/workflow_paths.json` 只覆盖输出目录；外部人读版 88 个 Markdown 与 `SOURCE_MAP.json` 未移动或改写。`py_compile` 与 `git diff --check` 通过；额度余量不可见，本次在阶段边界记录进度，不声称达到阈值。
- 当前续接重新运行 I4 定向回归：`.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_pipeline_contracts tests.test_story_summary_review tests.test_tm_provenance_unit tests.test_tm_review tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_kakuyomu_workflow tests.test_source_editions -q`，200 项通过。包含快照追加/幂等、损坏快照拒绝、审计期间 manifest 变更拒绝及消费者版本门禁；仅为合成单测，不代表真实 Provider 或书籍翻译验收。

## 2026-11-17 试点路径与产物复核

- `projects\祝福のネトラレラ\workflow_paths.json` 解析的外部人读根和译文根均匹配用户指定的括号版路径且存在。人读目录为 `SOURCE_MAP.json` 加 3 个章节目录，分别有 30、40、18 个 Markdown；AI 目录有 88 个单话 Markdown；当前译文目录为空。
- 截至本历史记录形成时，`source_manifest.json` 为 268/268、`source_editions_manifest.json` 为 444/444；该旧计数随后由原始 HTML 刷新更新，当前状态见本文底部续接记录。
- 后续：人工检查目录标题、episode 顺序/映射、两版清洗差异及目标阅读器的人读 Ruby/旁点/缩进效果；只有确认当前计划完整摘要后才创建审批回执。生成并审核与 AI 来源版本绑定的全书概要后，执行 Provider preflight，再安排受控首话翻译。真实 Provider、全书映射人工批准及阅读器验收仍未完成；作品授权与无需官方澄清已确认，不列为待办。

## 2026-11-17 双版本清洗产物可重复核验

- 新增 `scripts/validate_source_editions.py` 只读验证入口：从当前 catalog 与 manifest 绑定的 raw bytes 重算 AI/人读 profile，核对完整 episode/章节路径、两份索引、不可变 edition artifact 和两个输出镜像。
- 对 `source_catalog.append-2026-11-17.json` 的 88 话实书结果为 `verified`：source 793,183 bytes、AI 774,253 bytes、人读 799,293 bytes。运行只读，不访问网络、不输出正文、不写项目或书籍数据。
- 可复现命令见[开发与验证](../development.md#2026-11-17-ai-与人读版清洗产物可重复验证)；`.venv\Scripts\python.exe -m unittest tests.test_source_editions -q` 为 19 项通过，`py_compile`、CLI `--help` 通过。
- 该结果证明输出与当前清洗 profile 逐字节一致，不代表语义完整性或阅读器视觉验收。仍需人工确认章节映射、AI 输入是否适合翻译、人读 Ruby/旁点/缩进显示；真实 Provider 翻译与译文尚未发生。此记录形成时的代码直接读取 AI 归档文件；该运行时路径随后按用户更正拆分，当前由 `RAWs_AI` 提供正文，归档仅承担版本/来源核验，见下方“默认 AI 翻译输入复核续接”。

## 历史计划

2026-11-16 计划文件 `translation_plan_review_2026-11-16.json` 的摘要为 `36dae9c08069ce5c66eddc1e870a0aa4aa4d1724b00589ed9a5be62ce4bc22d4`。它早于 AI 清洗版默认选源接入，保留供历史追溯，不是当前审阅对象；不得用其摘要创建当前翻译审批回执。

## 2026-11-17 后续验证交接

- 用户再次明确 AI 清洗版就是翻译系统默认的干净原文输入。当前 Kakuyomu CLI 默认 `source-edition=ai`，通用项目模式也只从经核验的 `RAWs_AI/` 建立版本映射；试点本地只读计划复核为 `ai-efficient-v1`、88/88 来源有效、0 问题。计划 stdout 不含原文，网络请求、Provider 调用和文件写入均为 0。
- 复核历史 PR #58 两个问题已由当前工作区实现覆盖：截断 HTTP 响应可暂停并从 checkpoint 续跑；相对 Pandoc executable 在切换工作目录前转为绝对路径。聚焦回归 43 项通过，命令及细节见[开发与验证](../development.md#2026-11-17-历史代码审阅项复核)。
- 当前 checkout 的 `git status` 含此前已有的未提交改动；本轮只追加文档验证记录，未暂存、提交或改写书籍数据。额度信息不可见，未推断额度阈值。
- 可直接续接的工作：先完成人工核对当前摘要对应的 88 话 AI 映射、AI/人读清洗保真和目标阅读器显示；再从当前完整 AI 映射生成并审核全书概要、执行本地 Provider 配置预检，最后安排受控首话翻译。开始翻译前须确认计划摘要仍匹配当前 catalog/index；没有已审核概要、匹配审批回执或有效本地 Provider 配置时，入口应继续失败关闭。
- 尚无真实 Provider 翻译或 Notion 操作；作品授权与用户明确无需官方澄清均已确认，不列为阻塞项。

## 2026-11-17 原始 HTML 归档续接

- 已实现：Kakuyomu adapter 将实际解析的原始 HTTP response body bytes 传入 `FetchedEpisode.page_html`；采集器把它作为独立 `raw_page_html` artifact 追加，父节点绑定 episode metadata 和对应 `raw_source` 版本。解析后的可见 UTF-8 文本仍是唯一的 AI/人读清洗输入；AI profile `ai-efficient-v1` 是默认翻译输入，人读 profile 用于阅读体验。原文未变化而 HTML 变化时可单独追加 HTML 版本；HTML 字节参与归档上限预检。
- 已完成真实全量刷新：通过受配置代理访问主页目录和 88 个普通 episode URL，`status=complete`、88/88，正文 hash 全部不变、待处理 0；新增 88 个 HTML artifact。source manifest 356/356、edition manifest 532/532 验证通过，全部 88 个 HTML artifact 均连接 episode metadata 和对应 raw source。两版清洗输出重算校验 `verified`，88 话，AI 774,253 bytes、人读 799,293 bytes。
- 后续只读 parser v4 回放审计对最新 88 个 HTML artifact 均重抽得到与当前 `raw_source` 一致的正文哈希；正文内结构计数与人工验收限制见[开发与验证](../development.md#2026-11-17-原始-html-归档与默认-ai-计划复核)。
- 当时的计划：`projects\祝福のネトラレラ\Workflow\Plans\translation_plan_review_ai_raw_html_2026-11-17.json`，摘要 `22db616990740a39427146717945deb62ea3841a508af2ac7a2b701630293299`。它是 schema v1，后来被本交接顶部的 schema v2 计划取代；现行校验器拒绝旧 schema。
- 验证：七个来源/清洗/下游模块回归 150 项通过；manifest 与 editions validator 分别为 356/356、532/532；source-edition validator 为 88/88 `verified`；默认 AI `--plan-only` stdout 模式 0 网络、0 Provider、0 写入。完整命令和结果见[开发与验证](../development.md#2026-11-17-原始-html-归档与默认-ai-计划复核)。
- 未完成：人工审阅 88 话 AI 映射/标题/TM key 和 AI 清洗适用性；在人读阅读器验收 Ruby、旁点、缩进、段落及章节显示；生成并审核绑定 AI 版本的全书概要；创建与当前摘要匹配的计划审批回执并检查本地 Provider 凭据/端点，之后才可执行真实翻译。无真实 Provider、Notion 或 EPUB 阅读器验证。此前采集时未保存的 HTML 无法恢复。
- 保留范围：本轮代码与文档改动及被 `.gitignore` 忽略的试点 SourceArchive/RAWs_AI/外部生肉与熟肉目录均保留；未暂存或提交。当前 worktree 还有此前既存未提交改动；任务额度不可见，未声称额度阈值。

## 2026-11-17 默认 AI 翻译输入复核续接

- 用户再次明确 AI 清洗版必须是翻译系统默认的干净原文输入；人读版只服务人类阅读。当前 Kakuyomu 入口默认选择 `ai`，通用项目模式从 AI profile 建立映射；AI 来源无效时失败关闭，不退回人读版。
- 先前交接的运行时路径描述已按用户更正更新：`SourceArchive` 只负责保存来源/派生版本归档及清单；实际 AI 翻译正文从 `RAWs_AI` 读取。映射的 `raw_file`/`source_version_id` 保留归档 provenance，`source_input_file`/`source_sha256` 定位并核验 AI 镜像。直接读取实现和当前验证见[开发与验证](../development.md#2026-11-17-raws-ai-作为默认翻译输入)。
- 当时的只读 `--plan-only` 摘要为 `22db616990740a39427146717945deb62ea3841a508af2ac7a2b701630293299`；该 schema v1 计划现已被 schema v2 计划取代，不能用于当前审批。
- 本轮验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q` 为 121 项通过；仓库 runner 的 `test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 为 1 项通过。E2E 断言计划的 profile 是 `ai-efficient-v1`，且 TM 原文等于计划选中的 AI 来源。`git diff --check` 通过。
- 本轮未调用真实 Provider、未创建译文或审批回执。当前计划人工映射审阅和匹配 AI 版本的已审核全书概要仍是正式翻译门禁；作品授权已确认，不列为待确认事项。
- 工作区原有未提交修改和忽略的试点书籍数据均须保留；本轮仅追加开发记录和此交接记录，没有暂存或提交。

## 2026-11-17 当前工作集完整本地回归续接

- 当前完整非 E2E 回归动态发现 26 个测试模块并排除 `test_e2e.py`，运行 498 项，0 失败、4 跳过；3 个符号链接用例因 Windows `WinError 1314`、1 个 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- 按仓库要求通过 `.venv\Scripts\python.exe tests\run_tests.py` 执行完整 mock E2E，7 项通过，202.879 秒，退出码 0。请求仅发往 runner 启动的 loopback mock server；负向 fixture 的内容拦截、段落错配和故障日志是预期覆盖。
- 结果只验证本地合成/模拟流程；真实 Provider/Notion、人工验收及 EPUB 阅读器仍未验证。记录命令与范围见[开发与验证](../development.md#2026-11-17-当前工作集完整本地回归)。

## 2026-11-17 项目模式 reviewed glossary 门禁续接

- 已实现：`pipeline.py --project` 固定使用 `Knowledge/Glossary_reviewed.json`；RAG 初始化时验证 bundle 状态、批准术语和当前来源 lineage。缺失、旧式 `Glossary.json`、损坏或 stale bundle 均失败关闭；显式 JSON 配置的兼容行为保持不变。
- 依据：知识治理已提供候选哈希绑定回执、approved-only bundle 发布器及来源审计；旧式 glossary 没有审核状态或来源版本。当前试点只存在旧式 `Glossary.json`，因此默认项目模式会在 RAG 初始化时阻断，未读取其正文。
- 验证：`tests.test_pipeline_contracts`、`tests.test_rag_engine_unit`、`tests.test_knowledge_review`、`tests.test_kakuyomu_workflow`、`tests.test_kakuyomu_translation_plan`、`tests.test_story_summary_review` 共 194 项通过；当时的完整非 E2E 回归为 490 项通过、4 项因 Windows 能力跳过，完整 mock E2E 7 项通过（202.879 秒）。之后加入 HTML 归档验证器的 8 项测试；当前 26 模块/498 项回归见上节。
- 下一步：对当前完整 AI 映射生成术语候选、经审核后发布与来源版本绑定的 `Glossary_reviewed.json`；此步骤需要实际审阅决定，且不得把生成候选直接作为 approved。当前计划映射人工审阅、概要审核、匹配计划回执和 Provider 条件仍是实际翻译前置项。
- 保留：工作区原有改动及忽略的书籍数据均保留；本轮只编辑上述代码、合成测试和工作流文档，未暂存或提交。

## 2026-11-17 续接时当前来源与 AI 计划复核

- 当前 checkout 的 source manifest 为 356/356，edition manifest 为 532/532；双版本 validator 重新计算 88 话并返回 `verified`。外部人读目录参数在 PowerShell 中需加引号以保护括号路径，实际目录与 `workflow_paths.json` 一致。
- 当时的 schema v1 计划摘要为 `22db616990740a39427146717945deb62ea3841a508af2ac7a2b701630293299`；它已由本交接顶部的 schema v2 当前计划取代。
- `scripts/validate_kakuyomu_html_archive.py` 已加入当前验证入口；当时真实试点返回 88/88 HTML replay 一致、356 个 manifest 文件有效。历史记录中的 UTF-8 解码假设已由[2026-11-19 字符集续验](../development.md#2026-11-19-当前工作树回归与来源边界修复)更新；历史版本仍只做哈希检查。
- 离线 EPUB candidate builder 的当前合成回归为 23 项通过，语法检查及 CLI `--help` 通过；没有使用试点译文，EPUBCheck 与阅读器验收仍未做，I5 保持`部分实现`。
- 下一步仍需人类验收 88 话映射和两版清洗效果、发布匹配 AI 版本的已审核概要/术语表、创建匹配当前计划摘要的审批回执，并在本地配置可用 Provider 凭据后才能做受控单话翻译。未代替用户做内容批准；作品授权与无需官方澄清维持已确认状态。

## 2026-11-17 RAWs_AI 正文输入路径续接

- 决策：`SourceArchive/` 仅保存不可变的来源/派生版本归档及清单/归档元数据；AI 清洗正文的索引和镜像位于 `RAWs_AI/`。翻译实际正文必须从 `RAWs_AI/` 读取。映射的 `raw_file`/`source_version_id` 只记录 archive provenance 并供 lineage/TM 校验；`source_input_file`/`source_sha256` 才定位并绑定实际 AI 正文。镜像缺失、超限或哈希不符时停止，不回退读取归档或人读版。
- 计划与审批流程文件不属于来源版本归档：待审计划放在项目 `Workflow/Plans/`，审批回执放在 `Workflow/Approvals/`。现有 5 份误放在 `SourceArchive/` 的计划 JSON 已迁移；计划与审批 CLI 均拒绝再次向归档根写工作流文件。迁移和当前 schema v2 计划见本交接较新的“归档目录与当前审批计划复核”。
- 实现：`source_editions.py` 提供有界哈希校验读取；`pipeline.py`、Kakuyomu 编排器、章节对齐和知识抽取均接入 `RAWs_AI` 输入路径；计划 schema v2 和审批摘要绑定 AI 输入路径/哈希。旧文档中将 archive artifact 描述为运行时正文来源的结论已标记为历史并更正。
- 验证：定向回归 226 项通过；仓库 mock runner 目标 E2E 1 项通过；相关 Python `py_compile` 通过。实书只读映射 88 项，分别显示 archive provenance 根和 `RAWs_AI` 输入根，未输出正文/调用 Provider。9 份相关 Markdown 的 182 个本地链接目标存在。
- 尚未完成：人工审阅当前 88 话计划、AI/人读清洗结果；生成并审核当前映射绑定的概要/术语表；创建当前计划摘要的审批回执；确认本地 Provider 配置后再执行受控翻译。作品授权已确认，不是待办或阻塞。
- 工作区所有既存未提交改动均保留；本轮未暂存、提交、回滚或清理。额度不可见，无法核验 5 小时阈值。

## 2026-11-17 归档目录与当前审批计划复核

- 用户再次明确 `SourceArchive/` 只保存归档文件；AI 翻译正文直接从 `RAWs_AI/` 读取。计划与回执放在 `Workflow/Plans/`、`Workflow/Approvals/`。
- 现行校验器只接受计划 schema v2；此前待审文件为 schema v1。保留旧文件作历史记录，并基于当前 catalog/AI 索引重新生成顶部列明的 v2 计划，没有覆盖旧计划。
- 新计划 `ready_for_review`，88/88 `RAWs_AI` 正文及归档 provenance 有效、0 问题；摘要通过当前校验器复算。生成时 0 网络请求、0 Provider 调用、1 次计划文件写入；没有生成审批回执或译文。
- 计划 CLI 和审批 CLI 都拒绝将输出写入 plan 中的归档根。迁移后的归档目录内计划/回执计数均为 0；`Workflow/Plans/` 当前有 6 份计划，其中旧 schema 文件只作历史记录。
- 验证：定向单测 162 项通过，覆盖 `RAWs_AI` 正文读取、归档路径拒绝和审批回执拒绝；相关结果见[开发与验证](../development.md)。

## 2026-11-17 当前工作树全量回归续接

- 当前工作树完整非 E2E 回归运行 505 项，0 失败、4 跳过；仓库 mock E2E runner 运行 7 项，全部通过（317.260 秒）。4 项跳过为当前 Windows 环境限制，细节与完整命令见[开发与验证](../development.md#2026-11-17-当前工作树全量回归与试点门槛)。
- 重新解析项目本地配置时，三阶段模型为 `gpt-6-Luna`，JOJO/JYQF 职责 allowlist 已加载，但两家当前 key 均未配置；本地无已审核全书概要/术语表，仓库内也没有全书抽取所需的 tokenizer 文件。本轮没有生成知识候选或调用 Provider。
- 下一步仍是人工验收当前 88 话 AI/人读清洗与计划映射；完成后发布与 AI 来源版本匹配的 reviewed 概要/术语表及计划审批回执。提供有效 Provider 凭据并确定模型匹配的 tokenizer/context/message 预算后，才可执行受控单话翻译。作品授权已确认，不是待办。
- 当前代码、文档与测试改动均保留；未暂存、提交或回滚。真实 Provider、Notion、EPUB 阅读器及人工语义/视觉验收仍未完成。

## 2026-11-17 SourceArchive 与 RAWs_AI 根目录隔离

- 用户再次明确：`SourceArchive/` 只放来源/派生版本的归档文件与归档元数据；翻译取得 AI 版正文必须直接从 `RAWs_AI/` 读取。归档 AI artifact 只用于版本 lineage 和哈希核验，不是正文读取位置。
- 当前实现区分两种校验：pipeline、概要/知识/TM 运行时从 `RAWs_AI/` 读取正文，并读取归档 manifest/catalog 元数据核对 lineage 和登记的 AI artifact digest；它们不打开 `SourceArchive/` 的章节正文。显式 `validate_source_manifest.py` / `validate_source_editions.py` 仍会读取归档文件，以核对实存字节和 profile 输出。
- `source_input_file` 的 `source_sha256` 是 AI 镜像的原始字节摘要；概要与知识 provenance 可记录换行规范化后的文本摘要。校验分别按字段语义比较，不混用两种摘要。
- Kakuyomu 编排器现于作品目录发现、章节正文请求和归档写入前，对来源归档根、人读版根、AI 版根及译文根执行两两隔离检查。显式 `--ai-edition-root` 或 `workflow_paths.json` 若把人读/AI 目录放进归档根或造成任意根目录重叠，会立即失败。
- 通用项目模式复用的 `verify_ai_edition_index()` 也会拒绝归档根与 AI 根相同或重叠，防止 `RAWs_AI` 路径别名把归档目录当作 AI 工作副本。
- 回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_workflow tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q` 为 133 项通过；目标本地 mock E2E `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 为 1 项通过；三份受影响 Python 文件 `py_compile` 与 `git diff --check` 通过。
- 核心增量后全量非 E2E 回归为 505 项通过、4 项按 Windows 能力跳过、0 失败；`.venv\Scripts\python.exe tests\run_tests.py` 为 7 项本地 mock E2E 全通过（317.260 秒）。项目 `Config.load_config(project="祝福のネトラレラ")` 只读加载 88 话映射并确认 `SourceArchive`、`RAWs_AI` 分别作为归档根和正文输入根。
- 再次只读核验来源 manifest 356/356、合并 edition manifest 532/532，双版本 validator 对当前 88 话返回 `verified`；source/AI/human 输出分别为 793,183/774,253/799,293 bytes。
- 以上测试不调用 Kakuyomu 或真实 Provider。当前 88 话计划/清洗的人工审核、reviewed 全书概要与术语表、匹配当前计划的审批回执和真实单话翻译仍待完成；作品授权已确认。额度状态不可见，不能核实 5 小时额度阈值。

## 2026-11-17 RAWs_AI 输入边界最终续接

- 决策已在实现和文档中统一：翻译系统默认只从项目 `RAWs_AI/` 读取 AI 清洗正文。章节映射的 `source_input_file`/`source_sha256` 是实际正文输入路径和原始字节哈希；`raw_file`/`source_version_id` 只标记 `SourceArchive/` 归档版本，用于 provenance、lineage 和登记摘要核对。项目运行时读取归档 manifest/catalog 元数据，但不打开归档章节正文；显式归档验证器可读取归档文件核对物理字节。人读版不进入默认翻译输入链路，AI 镜像失效时失败关闭。
- 最新完整非 E2E 回归为 511 项运行、0 失败、4 项因 Windows 符号链接/FIFO 能力跳过。命令见[开发与验证](../development.md#2026-11-17-本轮收尾raws_ai-正文与归档职责)。目标本地 mock E2E 1 项通过；受影响 Python 文件 `py_compile`、`git diff --check` 及 README/8 份相关文档 169 个本地 Markdown 链接目标检查均通过。
- 下一步：人工审阅当前 88 话 AI/人读清洗结果和 schema v2 映射计划；按当前 AI 来源版本生成并审核全书概要/术语表；明确批准当前计划摘要后创建审批回执；待所需本地 Provider 条件可用后再执行受控翻译。当前没有真实译文，也没有调用真实 Provider。
- 工作区有大量既存未提交代码、测试、配置和文档改动，并有未跟踪的项目数据/实现文件；全部保留，未暂存、提交、回滚或清理。额度状态不可见，未声称达到额度阈值。

## 2026-11-17 当前工作树全量审查续接

- 在 `e2fe611258532c9f0bab3672eda52cf928102b1a` 基线上审阅现有翻译、来源归档、知识审核、下游 freshness、Provider 配置和 EPUB candidate 改动；工作区原有变更均保留。
- 修复双版本导出输出根的符号链接检查顺序，并增加不依赖管理员权限的回归；删除 source-editions 测试中的重复方法/导入。另修正 freshness CLI 测试辅助函数的全局配置隔离，避免测试顺序改变结果。
- 验证：`tests.test_source_editions` 23 项、`tests.test_downstream_freshness_snapshot` 9 项通过；完整非 E2E 回归 514 项运行、0 失败、4 项 Windows 能力跳过；仓库 mock E2E 7 项通过，224.381 秒。命令和范围见[开发与验证](../development.md#2026-11-17-当前工作树审查与完整回归)。
- 本轮管理员 PowerShell 启动被自动执行策略拦截，没有当前工作树下的提升权限测试结果。3 项符号链接用例仍需在管理员 PowerShell 复跑；1 项 FIFO 跳过是 Windows 平台能力限制。旧提交上的管理员结果不替代本轮验证。
- 实现、测试和文档已提交为 `a8d056d355c4c03c643192296a859893c92539d9`，分支 `codex/translation-workflow-audit-20261117` 已推送。PR #71 已创建，GitHub 当前报告 `OPEN`、`MERGEABLE`、`CLEAN`，无 hosted checks、无评审结果；未自动合并。PR #56 已于 2026-11-14 合并，无需再次操作。
- 试点映射、AI/人读清洗语义、reviewed 概要/术语表、当前审批回执、真实 Provider 翻译及 EPUB 阅读器仍待对应人工或外部验收。
