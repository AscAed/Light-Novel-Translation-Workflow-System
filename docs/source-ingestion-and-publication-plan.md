# 原文采集、翻译衔接与成果归档方案

> 2026-11-18 用户要求新增自包含元数据及章节来源的原文大合集，以及 AI/人读双版本大合集。旧 checkpoint Markdown export 仍只拼接正文；本日新增内容寻址 raw JSON、AI JSON、human Markdown 与 bundle-set，但人工格式/完整性验收仍未完成。跨系统文件结构、版本绑定和验收见[全书到单话翻译目标方案](end-to-end-workflow-target.md#2026-11-18-实施进度)。

> 状态：`部分实现`，各工作包的范围与验收进度不同。2026-11-18 文档复核基线为分支 `codex/translation-workflow-audit-20261117` 的 `7ea8e10`；此前基于 `07efed2` 工作树的增量现已纳入该提交。历史公开目录采集、双版本和合集核验及其边界见[项目现状](project-status.md#2026-11-18-文档复核基线)和[开发与验证](development.md)；本次未重新采集或核验试点文件。仍需人工格式/映射验收、来源变化后的下游失效传播、真实 Provider 翻译、EPUB 阅读器验收及 Notion 同步。
> 证据边界：现状以当前仓库代码、配置和活动文档为准；历史会话只提供需求背景。本地被忽略的书籍数据不作为授权、来源或质量证据。

> 2026-11-17 双版本实施：采集器发现并抓取的同一份 88 话完整可见原文，分别进入 AI 效率优先和人类阅读体验优先的清洗流程；两版不互相复制，也不分别采集。两条清洗流程、实际路径、验证与未完成的人类观感验收见下方“目标目录与版本约束”和“2026-11-17 双版本清洗实施”。

## 目标与适用范围

规划一个面向日语轻小说的来源接入和成果管理流程，并为未来多平台扩展保留适配边界：

1. 用户按书名或 URL 指定作品；仅从经过来源审查、用户有权处理且技术访问被允许的平台获取公开已发表内容。
2. 保留原始采集证据，再派生结构化、可追踪的每话 Markdown 与全书 Markdown。
3. 将每话内容接入现有章节翻译流程；全书级知识抽取只生成待审核候选。
4. 支持将清洗后的原文、译文和批准知识备份到 Notion；本地项目数据仍为权威数据源。
5. 将章节/全书 Markdown 转换成 EPUB 派生文件，不覆盖原始或规范化文本。

用户于 2026-11-14 选定 Kakuyomu 为首个候选平台，身份为普通用户，并指定试点作品及个人用途；用户于 2026-11-14 明确确认该作品获得授权，并于 2026-11-15 再次明确确认，本计划按已授权记录。该确认不独立证明 Kakuyomu 允许自动访问。Provider 数据范围另已确认：JOJO/JYQF 仅获各自职责所需的最小类别；Notion 接收范围仍须单独核定。本文不提供版权法律结论；逐平台访问规则仍须审查。

## 试点作品与本地文件

- `用户输入`：作品《祝福のネトラレラ》，作者墨色，[Kakuyomu 作品地址](https://kakuyomu.jp/works/16817330668011048405)；首批试点为[第 1 话](https://kakuyomu.jp/works/16817330668011048405/episodes/16817330668011089189)。
- `用户输入`：当前拟作个人非商业读取、保存、翻译、发送模型、Notion 备份和阅读，暂不公开分发。用户于 2026-11-14、2026-11-15 明确确认指定作品已获得授权；本方案按已授权记录。用户是普通读者，不具备作者 ZIP 导出权限，并要求从作品主页发现完整公开目录 URL、再用普通 episode URL 获取原文。用户明确表示不需要官方澄清；该决定不改写为平台许可或法律结论。JOJO/JYQF 各自职责所需的最小 Provider 数据类别另已授权；Notion 接收范围仍单独核定。初始 live 页面结构复核见[I0 核查记录](#kakuyomu-i0-规则核查-2026-11-14-至-2026-11-15)，88/88 实际采集结果见下方 I2 记录。
- `用户输入与数据目录快照`：本书采集版本归档位于 `D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System\projects\祝福のネトラレラ\SourceArchive`，AI 清洗版位于项目内 `RAWs_AI`；用户指定外部 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 为人类阅读版，外部同书 `熟肉` 为译文根。归档含主页声明的 88 个可见正文、章节分组、raw/normalized 来源版本及全书 export；2026-11-16 显式刷新重取 88/88 话且哈希无变化，manifest 268 个文件型 artifact 通过 SHA-256 核验。2026-11-17 已从同一来源分别生成 88 话 AI/人读版；索引和输出哈希通过本地校验。译文目录仍无译文。用户指定路径与忽略项目数据不纳入 Git；此前 2026-11-14 的 48/19 章文件库存是历史快照。
- `用户输入`：用户没有本地原文或译文，希望系统从 Kakuyomu 获取原文后翻译生成译文；不要求用户提供本地章节。用户于 2026-11-15 明确要求从作品主页发现完整公开目录 URL，再逐话访问普通 episode 页面获取正文；后续明确该书已获授权，并要求按发现的全部普通 episode URL 获取原文。主页目录到逐话采集已实现，历史 source-only live run 对主页声明的 88 话完成 88/88。该明确授权和采集范围不改写为平台背书或公开分发授权。
- `不适用的条件路径`：Kakuyomu 官方作者 ZIP 只供作者账号备份自作小说，且无导入功能。用户已明确自己是普通读者，因此本试点不能依赖作者 ZIP；不要求用户另行提供，也不把它作为当前阻塞。
- `已实现（局部）`：`kakuyomu_page_source.py` 与两个 Kakuyomu CLI 支持显式 JSON catalog 或从作品主页发现公开目录。`discover_kakuyomu_work_catalog` 从唯一 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 依序读取分组及 episode ID/title，核验唯一条目数等于 `publicEpisodeCount` 后生成普通 episode URL。目录和正文请求均检查 robots；每页间隔限制为 1.5–3 秒（默认 2 秒）；不登录、不跟随重定向、不访问 `/read`。正文可从 `div.widget-episodeBody` 或 `js-episode-body` 唯一区域提取，并与目录标题交叉核对。parser v4 保留段落边界、ruby (`｜基字《读音》`)、旁点 (`｜文本《・・・》`) 和 U+3000 全角空格；HTML entity 按 HTML 解析规则解码。可见正文保存为 UTF-8 `raw_source`，原始页面响应体自 2026-11-17 起另存为 `raw_page_html`，不作为清洗输入。页面大小默认 4 MiB、单章提取文本 16 MiB、全目录文本 128 MiB、最多 1000 话；归档字节预算包含登记的 HTML artifact。checkpoint 先记录 catalog，再逐话请求并即时归档；失败后从首个未完成话续传。正文和页面响应各由 artifact 哈希绑定；批次是跨时间滚动采集，不是同一时刻的原子全书快照，完整 checkpoint 不自动刷新旧正文。结构/计数异常及 robots 拒绝均 fail-closed。
- `部分实现`：2026-11-15 source-only live 采集已从主页发现并获取主页声明的 88/88 话；生成 88 个单话 Markdown 和一份有序全书 export。完成后来源 manifest 的 267 个文件型 artifact 均通过 SHA-256 核验。真实首话结构检查观察到段落、ruby 标签和 U+3000；旁点由 synthetic fixture 覆盖，不将未出现于样本的标记说成 live 验收。`scripts/run_kakuyomu_workflow.py --work-url` 还可按目录 ID/顺序生成确定性 `CHAPTER_MAP` 并调用生产流水线，但本次没有运行真实 Provider。人工格式/标点/ruby 验收、译文和质量验收未完成。

## 仓库现状与证据等级

### 已实现且有本地验证记录

- `pipeline.py` 提供 Python CLI 章节翻译，单进程顺序执行上下文标注、初译、校对、润色。
- `CHAPTER_MAP` 支持逐话显式指定原文路径、译文路径和 TM 键；不根据章节名自动猜测真实映射。
- 新 TM 写入可包含源文件哈希和段落映射；`scripts/validate_tm_provenance.py` 提供只读来源核验。
- `scripts/auto_extract_knowledge.py` 可生成经过结构校验的知识候选草稿及来源清单；不等于知识已审核或批准。
- `book_bundles.py` 按来源快照导出 raw JSON、AI JSON、human Markdown 和最后写入的 bundle-set marker。loader 会核验当前 catalog、checkpoint、source/edition manifest、双版本索引及逐话映射。2026-11-18 试点 88 话 bundle-set 已生成并由 loader 返回 `verified`；AI bundle contract 为 v2。
- `PROVIDER_DATA_POLICY` 默认拒绝向远端 Provider 发送书籍数据；用户已授权 JOJO/JYQF 接收各自职责所需的最小类别。代码默认 allowlist 仍为空；2026-11-17 的本地忽略配置记录已显式列出试点职责类别，但本次未读取或复核私有配置，真实端点和请求数据未验收。Gemini embedding 与 Notion 接收范围不在此授权内。
- 上述验证是仓库合成测试/mock 证据，不证明真实 Provider、平台访问权或翻译质量。验证记录见[路线图](roadmap.md)和[开发与验证](development.md)。

### 未实现或未知

- 已实现平台无关的分页采集核心、checkpoint 续传、本地 catalog adapter 和 Kakuyomu 主页目录 discovery；新增离线 catalog snapshot diff，可报告新增/消失/标题修改/重排及 v2 分组变化，并可排他导出新增或变化话目清单。纯追加更新验证旧 ID、标题、顺序、URL、章节归属和 manifest raw 版本后，只从追加位置请求新话。显式全量正文刷新绑定完整基线 catalog/checkpoint/manifest，要求当前目录完全一致，再逐话重取正文并按 SHA-256 复用或追加不可变 raw 版本。尚无其他站点 adapter 或独立于站点公开话数声明的完整性证明。纯追加路径不检测旧正文修订；全量刷新拒绝目录变化。续传只在来源快照与目标 manifest 身份匹配时适用；目录 parser 依赖站点服务端页面结构，变化时 fail-closed。
- 仓库未发现 Notion API/数据库同步集成；依赖清单未声明 Notion 客户端。
- 本机能解析到 Pandoc 可执行文件，但本次未核实其版本、EPUB 配置或输出兼容性。其存在不代表项目集成或构建已验证。
- Kakuyomu 为用户选定的平台；指定作品授权按用户明确声明记录。用户明确表示无需官方澄清，并要求普通主页目录发现和普通 episode URL 路径；平台条款及 robots 观察保留为风险记录，不表述为平台背书、许可结论或停止本试点的官方答复门槛。真实 88/88 source-only 采集已执行；其他平台和 Notion 接收范围仍需分别核定。
- 本地忽略目录包含书籍数据且结构复杂；项目现状文档记录了目录/来源审计限制。不得由本计划推断数据合法来源，不得自动上传、改写或生成其映射。

## 搜索与双版本需求复核（2026-11-16）

本节记录用户提出的目标，与现有 I0–I6 工作包共同维护；符合度是需求比较，不替代项目状态标签。`已符合`、`部分符合`、`不符合`、`尚无足够证据确认` 分别表示：已满足并有对应证据、已有局部能力、当前未满足、现有证据不足。本轮复核代码基线为 `main` 的 `e2fe611`，实际能力仍按代码和对应验证范围判断。

| 用户预想 | 符合度 | 当前证据、差距及影响 |
| --- | --- | --- |
| 书名搜索及四种排序 | 不符合 | 当前 Kakuyomu adapter 以作品主页或显式 catalog 为输入；未发现搜索入口、排序选择和结果界面。见 [`kakuyomu_page_source.py`](../kakuyomu_page_source.py)、[采集 CLI](../scripts/ingest_kakuyomu_pages.py)。 |
| 用户名、Tag 搜索与结果选择 | 不符合 | 未发现 `search_user`、`search_tag` 搜索或从用户／Tag 结果选择作品的流程；用户或标签结果不应假定本身就是作品。 |
| 作品主页元数据 | 部分符合 | catalog schema v3 保存主页 URL、作品标题、作者名称/用户名、catchphrase、introduction、genre、tag labels、serial status、发布时间、最近话目发布时间和公开话数；v1/v2 catalog 继续可读。diff 在两份 v3 快照间只报告变化字段名，不输出简介等字段值。主页 `--work-url` 采集已实现将变化后的元数据写成带 `recorded_at_utc`、SHA-256 和父版本的 `kind=work` artifact；相同快照复用当前版本，文件计入 manifest 归档上限。episode 原始 HTML 响应体从 2026-11-17 起作为独立版本归档；作品字段覆盖和下游失效传播仍未验收。缺失字段不得由模型猜测。 |
| 章节名、话目、范围与 URL | 部分符合 | 本地 catalog schema v2/v3 保存目录组 ID、`Chapter` ID/标题/层级、连续位置范围及 episode ID 顺序；v1/v2 catalog 仍可读取。snapshot diff 能比较章节结构并导出新增/episode metadata-updated 子集；v3 另报告作品级元数据变化字段名。纯追加更新复用已验证旧 raw 版本、只抓新增话；显式全量刷新要求完整目录一致，重抓各话并报告正文哈希差异。作品 metadata artifact 不改变 episode source fingerprint，也不会自动刷新正文、概要或知识。TM/知识/概要只读门禁现可识别 raw 已更新但 normalized 尚未重建的 stale 状态；自动重建与持久化失效传播、完整层级人工验收仍未实现。v1 快照不包含章节分组，v1/v2 不包含作品级元数据，无法比较对应变化。 |
| 每话标题、正文和相关元数据 | 部分符合 | 普通 episode 页面抽取标题、正文并校验标题；ruby、旁点和空白有局部处理与合成证据，但前记、后记、作者话、所有页面字段和真实格式完整性尚未验收。 |
| 逐话文件、全书合集与翻译前全书预读 | 部分符合 | 旧 checkpoint Markdown export 仍为正文拼接格式；新增 raw/AI/human bundle 含作品快照、章节分组和逐话来源。full-book CLI 强制加载经验证的 AI bundle，分批候选 provenance 记录 bundle 身份及段落来源，并通过 token 预算内的候选综合保留跨批证据链。配置映射覆盖、真实 Provider 输出/综合质量和人工格式验收仍待处理。历史 88/88 仅对应当时主页声明的公开目录，既非平台之外的完整性证明，也不证明格式保真。 |
| 原始内容及特殊格式完整保留 | 部分符合 | `raw_source` 是提取后的 UTF-8 可见正文；2026-11-17 起，当前 Kakuyomu 页面响应另以精确字节保存为 `raw_page_html` 并绑定话目/正文版本。此前未归档的 HTML 不能恢复；哈希只能证明已保存字节未变，格式语义和人工完整性仍待验收。 |
| AI 专用及人类阅读清洗版 | 部分符合 | `scripts/export_source_editions.py` 从同一组 manifest 验证过的采集来源生成两版，分别转换 ruby、旁点、段首 U+3000 和换行；清洗 profile、源版本及输出哈希写入各自索引。合成规则测试通过；真实文件已生成，人工逐段保真与阅读器观感仍未验收。 |
| `RAWs_AI`、`Metadata` 与人类章／话目录 | 部分符合 | 本书 `RAWs_AI` 和人读版已按用户指定路径生成；人读版使用 `<章节名>/<话名>.md`。项目名模式默认 AI 输入；本书本地忽略的 `workflow_paths.json` 仅设置外部译文根，不覆盖 AI 映射。统一 Metadata 导出、目标译文布局和人工映射验收仍待完成。没有该项目路径设置且默认输出目录有嵌套内容时，通用项目名模式会拒绝并要求显式配置，见 [`pipeline.py`](../pipeline.py)。 |
| 每书 `Knowledge` 与审核 | 部分符合 | 现有项目配置有 `Knowledge`、术语、概要和 TM 路径及局部审核回执；TM 默认只检索来源核验过的审核快照，未配置快照时不检索候选。翻译前全书候选抽取已支持显式 tokenizer/context 预算分批与概要、世界观、叙述候选段落来源；Kakuyomu 入口要求已审核全书概要。审核 AI、人物专门知识流程、风险分层/抽查和采集元数据批准入库闭环仍未实现。见[知识治理](knowledge-governance.md)。 |
| 每话译文、人类目录和概要译文 | 部分符合 | 现有流水线可按映射产生章节译文；目标章节目录、独立元数据概要翻译及其质量／版本追踪尚未实现或验收，真实 Provider 和试点译文仍未验证。 |
| 用户指定输出路径优先 | 尚无足够证据确认 | 显式配置可提供源、译文路径，但没有覆盖全部新产物类别的统一路径优先契约；不能据此认定已符合。 |

### Kakuyomu 页面结构与文本提取（2026-11-16）

用户补充的页面结构观察作为本试点的解析要求记录：作品页初始 HTML 包含服务端目录状态；`__NEXT_DATA__` 内的 Apollo 状态含作品目录、分组和 episode 标识；正文通常位于 `div.widget-episodeBody`，段落可带 `p id="p1"` 等 ID。用户指出 ruby 使用 `<ruby>/<rb>/<rt>/<rp>`，旁点使用 `em.emphasisDots` 与多个 `span`，日文段落缩进可能是 U+3000，空格也可能以 `&nbsp;` 出现。

当前实现与该要求的对应关系：

- `discover_kakuyomu_work_catalog` 从唯一 `__NEXT_DATA__` 脚本解析 Apollo `Work.tableOfContentsV2`，按分组顺序收集 episode ID/title，并要求唯一 episode 数匹配 `publicEpisodeCount` 后才生成普通 episode URL。它获取目录中的全部公开话目，不依据首屏普通 `<a>` 链接数推断完整目录。
- 同一次主页解析从 Apollo `Work` 与关联的 `UserAccount` 白名单读取作品标题、作者名称/用户名、catchphrase、introduction、genre、tag labels、serial status、发布时间、最近话目发布时间和公开话数，写入 discovered catalog schema v3。旧 v1/v2 catalog 仍可读。当前字段契约来自一次主页结构检查与 synthetic fixtures；并不声称涵盖页面所有元数据。
- `--work-url` 采集把作品元数据写为 source manifest 的 `kind=work` JSON artifact，包含 `recorded_at_utc`、作品 ID 和元数据；每个变化版本用 SHA-256 派生版本 ID，并指向前一版。相同字段快照复用已有 artifact，不因重复检查无限增长。该文件纳入 `--max-archive-bytes`；若超过上限，collector 在获取章节正文前返回 `paused / archive_limit`。2026-11-16 的历史试点刷新后清单含一个此类 artifact；变化版本处理仍以合成验证为依据。
- 离线 catalog diff 仅在两份 v3 快照间比较作品元数据，并只输出变化字段名，不把简介、标签等字段值写入差异报告。作品元数据变化不会改变 episode source fingerprint；manifest 已记录版本，但不会自动触发正文刷新或概要/知识过期传播。正文需由操作者显式执行全量刷新；变化报告不表示下游内容已更新。TM/知识/概要门禁会沿 normalized→raw 父版本检测正文变化后的 stale 窗口，但不自动重建或保存过期标记。
- `_EpisodePageParser` 使用标准库 `HTMLParser` 读取唯一的 `widget-episodeBody` 或 `js-episode-body` 区域，遍历段落内的文本节点；`p` ID 不作为筛选条件。解析器保留段落边界，把 ruby 表示为 `｜基字《读音》`、旁点表示为 `｜文字《・・・》`，并保留 `&nbsp;` 解码后的 NBSP 与 U+3000。实现不调用会丢失标记结构的简单 `get_text()`。
- 每次请求之间的间隔限定为 1.5–3 秒，默认 2 秒；429 会暂停采集，403、重定向和 robots 拒绝会停止当前请求，不尝试绕过访问限制。断点续传按已完成的 episode ID 跳过已归档话目。
- `scripts/ingest_kakuyomu_pages.py` 的 append-only 更新通过 `--incremental-from-catalog`、`--incremental-from-checkpoint`、新的 `--discovered-catalog` 和新的 `--checkpoint` 显式指定基线及输出。基线 checkpoint 必须完整且为当前绑定 schema；当前目录必须在旧 episode ID/标题/位置/URL 后纯追加，已有章节归属和元数据须保持不变，旧 manifest 中的 metadata 与 raw SHA-256/版本关系须通过复核。通过后新 checkpoint 继承完整旧话 ID/raw version bindings，分页游标从旧话数开始，只请求新增话；暂停后对同一目录快照重跑会续传。旧快照/清单不覆盖。旧话变更、删除、重排或已有章节变化会停止；更新期间若目录再次变化，需另建版本化 catalog/checkpoint，部分已完成新增话可能重新请求。目录不含正文哈希，因此该模式不会检测或刷新旧正文的静默修订。
- synthetic HTML fixtures 覆盖 `p` ID、ruby、旁点、段落换行、NBSP 和 U+3000。2026-11-15 的历史 live run 覆盖了当时主页声明的 88/88 话，但当时只保存 UTF-8 可见正文、没有保存原始 HTML；2026-11-16 较早的 schema v3 检查点只重新访问主页核对 Apollo 元数据键名/类型，没有请求 episode 页面。之后的实时复核发现当前 88/88 URL，并通过一个普通 episode URL 检查抽取结果；该话未包含旁点/NBSP。历史批量正文与本次单话抽样均不能单独证明所有实时页面格式始终一致。
- 单话 Markdown 和旧式有序全书正文 export 保留采集文本及 U+3000，不在归档来源上原地清洗。逐话 AI／人类双版本导出器在派生目录保存来源版本和哈希。新增 `book_bundles.py` 另生成自描述 raw/AI/human 全书合集；人读版的人工格式和阅读器验收、Notion 批量导入仍属后续工作。
- `部分实现` 翻译前全书预读入口：`--full-book` 现在还须指定 `--catalog`、`--checkpoint`、`--bundle-set`、与 marker 匹配的 `--book-bundle`、`--human-root`，并传入 tokenizer/context/output/safety/message 预算。授权预检通过后，脚本从 loader 核验过的 AI bundle 读取完整章节文本，按段落预算分批生成术语、概要、世界观和叙述习惯候选，再对候选做 token 预算内的分层综合；provenance 记录 bundle 身份、覆盖计数、来源哈希、token 预算、批次候选及跨轮 lineage 和结论级段落引用。综合请求只携带结构化候选，不能新增未经候选授权的段落证据。预算、调用次数或证据校验失败会在草稿发布前停止。候选仍须审核；配置章节映射覆盖、人物知识审核、真实 Provider 输出和语义质量仍未验收。试点本轮只用合成 provider response 验证消费路径，没有生成真实书籍候选。
- `计划` 真实模型与覆盖验收：以 `CHAPTER_MAP`、发现目录和 manifest 核对章节集覆盖；从目标模型的可信本地 tokenizer/config 与端点文档核定 context/output/message 参数，再以已授权 Provider 小样本验证 tokenizer 估算、请求兼容、输出截断/质量与费用。记录偏差并评估候选跨批综合的语义质量，再决定是否把概要/术语审核门禁扩展到其他入口。不得把截断输入标成“全书预读”。当前自动测试只证明本地预算、合成响应契约和综合证据边界。
- Gemini/Claude 是用户给出的能力示例，不表示已选择或授权这些接收方。当前 runtime `PROVIDER_DATA_POLICY` 仍默认为空；不得将全书内容发给新 Provider，或以模型容量推断真实端点支持。优先按已有 JOJO/JYQF 职责授权设计本地调用与合成验证，真实端点与输入类别需在安全配置后独立验收。

### 搜索入口与公开资料

以下 URL 与排序标签为**用户需求输入**，`$书籍名称参数`、`$用户名参数`、`$Tag参数` 是占位符，不是已确认的 URL 编码实现或稳定 API：

- 书名：`https://kakuyomu.jp/search?order=popular&q=$书籍名称参数`；用户要求 `popular`（累計ランキング）、`weekly_ranking`（週間ランキング）、`published_at`（新作順）、`last_episode_published_at`（更新順）。
- 用户名：`https://kakuyomu.jp/search_user?q=$用户名参数`。
- Tag：`https://kakuyomu.jp/search_tag?q=$Tag参数`。

2026-11-16 查阅 [Kakuyomu 官方搜索帮助](https://kakuyomu.jp/help/entry/trends)：该帮助将小说、用户和标签搜索区分开来，并说明可由搜索结果继续筛选；但它没有验证上面每个 URL、排序参数及对应语义。公开搜索页面可作为网页观察，不是稳定开发接口。本次公开网页工具未能打开三个带查询参数的目标页面，因而其 HTTP 返回、分页、编码、响应结构、动态内容、限流和全部排序语义均为`未验证`。实施前在允许的访问范围内复核官方页面、robots 和相关规则，并记录日期及结果；不将网页可访问或用户的作品授权视为平台自动访问许可。

### 目标目录与版本约束

通用默认布局与本书实际路径分开记录。`<书名>` 是展示名占位；路径需处理 Windows 禁用字符、保留设备名、大小写折叠、末尾点／空格、重名及长度限制，并以作品/话目 ID 和清单消歧；不得仅据文件名猜测章节对应。

```text
projects/<书名>/
  SourceArchive/               # 按版本保留采集来源、catalog/checkpoint 与来源清单
  RAWs_AI/                     # AI 版，按稳定作品/章节/话目 ID 检索
  Metadata/                    # 人类版元数据默认目录
  生肉/<章节名>/<话名.md>       # 人类版原文默认目录
  Knowledge/                   # 按作品隔离的知识
  熟肉/<章节名>/<话名.md>       # 译文默认目录
```

`祝福のネトラレラ` 当前实际使用以下目录：

```text
D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System\projects\祝福のネトラレラ\SourceArchive\
D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System\projects\祝福のネトラレラ\RAWs_AI\
D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉\
D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\熟肉\
```

第一条专用于来源及派生版本归档；第二条专用于 AI 清洗版，也是默认翻译正文读取位置；第三条专用于人类阅读版；第四条专用于译文。本书实际路径覆盖通用默认路径 `projects/<书名>/生肉` 与 `熟肉`，后两目录不是本书当前输入/输出位置。`SourceArchive/` 保存归档正文/页面、版本清单、采集 catalog/checkpoint 和不可变校验快照，不存放 AI 工作镜像或待审翻译计划/审批回执；计划与回执分别放 `Workflow/Plans/`、`Workflow/Approvals/`。人类版文件位于 `<章节名>/<话名>.md`；同章重名才追加位置或 episode ID 消歧。AI 版使用 `chapters/<序号>_<稳定章节ID>/episodes/<位置>_<episode ID>.md`，`catalog.json` 可按 episode ID 定位。目录及其书籍数据被 `.gitignore` 忽略，不纳入 Git。

其他作品的人类版原文与译文可由用户指定目标路径；未指定时用上面的项目内默认目录。`RAWs_AI`、`SourceArchive`、`Knowledge` 使用作品项目目录。当前导出 CLI 接受显式输入/输出路径；统一配置和映射仍属后续工作。

采集器将网页提取的 UTF-8 可见正文保存为 `raw_source`，并以字节保真方式生成 `normalized_source`；2026-11-17 起，Kakuyomu adapter 另把每次抓取的原始 HTTP HTML 响应精确字节保存为独立 `raw_page_html` artifact。HTML artifact 以作品话目元数据和对应 `raw_source` 版本为父版本；正文解析/清洗仍使用可见文本，HTML 归档用于保留可重新解析的页面证据，不替代既有清洗输入。AI 版和人读版从同一当前 `raw_source` 字节独立清洗；清洗器先验证其与最新 `normalized_source` 字节完全一致。AI 规则以高效识别为优先，人读规则以阅读呈现为优先；索引记录共同 raw 输入版本/哈希、规范化来源版本、profile ID 和各自输出哈希。此前未保存的历史 HTML 不能从可见文本恢复；当前采集保留页面响应仍不等于语义完整性或人工验收。未识别标记保留为文本；实际段落完整性、特殊标记逐段映射及人类阅读观感仍需验收。

### 2026-11-17 双版本清洗实施

- AI profile `ai-efficient-v1`：统一为 LF；只去除每段开头一个 U+3000 排版缩进；将 `｜基字《读音》` 转为紧凑的 `基字《读音》`；将 parser 的旁点表示 `｜文字《・・・》` 转为 Markdown 强调；保留段落和换行边界。
- 人读 profile `human-reading-v1`：统一为 LF；保留原有 U+3000、段落及换行；振假名转为原生 HTML `<ruby>/<rt>`，旁点转为 `text-emphasis: filled sesame`；源文本先 HTML escape 后写入 Markdown HTML 容器，避免源文本被解释成标签。展现效果依赖支持 HTML Ruby/CSS text-emphasis 的 Markdown 阅读器，须由用户验收。
- 两个版本均由 `source_editions.py` 从同一当前采集文本独立转换，输出内容哈希与输入 hash 分开。每话清洗产物以内容寻址版本追加到 `SourceArchive/editions/<profile>/<episode>/<version>.md`；新的 `source_editions_manifest.json` 保留采集来源历史并追加 AI `normalized_source`、人读 `export` artifact，不修改 collector 的 `source_manifest.json` 或其归档容量统计。重名消歧、危险 Windows 文件名处理、来源 manifest 校验、排他创建和冲突拒绝已有实现。
- 2026-11-17 为 88 话生成 176 个章节 Markdown 和两个索引文件；输入总计 793,183 bytes，AI 输出 774,253 bytes，人读版输出 799,293 bytes。首次增加清洗归档时新增 176 个不可变版本和 1 个清洗清单，两份旧索引经有限字段检查后刷新；两根目录的 176 个原有 Markdown 字节未变。当时基础清单为 268/268、合并清单为 444/444。随后 88 话全量正文刷新新增 88 个 `raw_page_html` 文件，索引刷新创建 0、更新 2、复用 353 个一致文件，AI/人读 Markdown 字节未变；当前基础清单为 356/356、合并清单为 532/532。幂等重跑结果只证明文件与当前 profile 一致，不证明语义无损或视觉效果通过。
- `scripts/run_kakuyomu_workflow.py` 的 `--plan-only` 和正式运行默认从 `--source-root` 同级 `RAWs_AI` 选择 AI 清洗版本；`--ai-edition-root` 仅覆盖 AI 根路径，`--edition-manifest` 指定来源归档内的清洗清单。计划从 AI 版本归档元数据选择逐话 `source_version_id` 用于来源溯源，同时以 `source_input_file`/`source_sha256` 指定 `RAWs_AI` 的实际正文输入。索引覆盖、catalog 与清洗清单 hash、AI 镜像字节 hash、归档 manifest 登记 digest、raw 父版本和 profile 均须校验；pipeline、章节对齐和知识抽取读取 AI 镜像，不读取归档章节正文。`SourceArchive` 只保存归档文件和清单，不作为 AI 正文读取源；翻译运行时读取 manifest/catalog 元数据，物理归档内容验证由显式验证命令完成。审批摘要绑定 profile、AI 索引根/路径/hash、清洗清单路径/hash、逐话输入路径/哈希和归档版本。只有显式指定 `--source-edition normalized_source` 才使用采集器规范化版本。两类版本都仍以同一份当前采集 raw 为清洗起点。
- 2026-11-17 采集联动：`run_workflow` 在完整采集、物化 `normalized_source` 后，自动调用 `prepare_source_editions` 写入 AI 与人读两版，再生成默认 AI 版翻译计划。人读根由 `workflow_paths.json` 的可选 `human_edition_root` 配置；试点配置保留原外部 `熟肉` 译文路径，并新增用户指定外部 `生肉`。旧话目清洗输出仅在字节完全相同时复用；索引刷新仅接受来源/章节/话目稳定且只在目录尾部追加的变化，其他内容编辑或旧章节来源变化时拒绝覆盖。未完整采集时不执行双版本导出。
- 定向命令 `.\.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval -q`：40 项通过。实际只读 AI `--plan-only` 返回 `ready_for_review`、88/88 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题、0 网络/Provider，stdout 模式无文件写入且不包含原文；人读镜像与版本归档的 88/88 输出 SHA-256 匹配。`py_compile`、两个 CLI `--help` 和 `git diff --check` 通过。后续把 AI edition 改为默认翻译来源后，2026-11-17 曾以默认参数生成 `projects\祝福のネトラレラ\SourceArchive\translation_plan_review_ai_default_2026-11-17.json`，摘要为 `8a5679563c376f3ed9dcfdcd5115db77149cf77189c46c5e544eb215c4dcd4d7`，状态 `ready_for_review`、88/88 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题；写入仅为该计划 JSON，不含正文。该历史计划后来迁至 `Workflow/Plans/`，并因 catalog 追加和 AI 索引刷新被新计划取代；当前审阅对象见[试点映射人工审阅](handoffs/2026-11-16-pilot-plan-review.md)。
- 后续计划因目录/index 更新及原始 HTML 全量刷新再次重建；当前 schema v2 审阅计划为 `projects\祝福のネトラレラ\Workflow\Plans\translation_plan_review_ai_raw_html_schema2_2026-11-17.json`，摘要 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`，状态 `ready_for_review`，88/88 `RAWs_AI` 正文与对应归档 provenance 有效、episode ID 与译文目标各自唯一、0 问题。先前的 `translation_plan_review_ai_raw_html_2026-11-17.json` 为 schema v1，现行审批校验器拒绝该旧格式；旧摘要不得用于当前审批。详见[当前人工审阅交接](handoffs/2026-11-16-pilot-plan-review.md)。
- 当前待办是人工检查 88 话映射/章节名称与人读 Markdown 的实际阅读器显示、ruby/旁点/缩进及逐段完整性。真实 Provider 翻译未执行；正式执行仍需要针对 AI 清洗版本生成并审核全书概要、审阅映射并创建匹配审批回执，且本地 Provider/授权配置通过检查。`raw_source` 仍是 collector 提取的 UTF-8 可见文本；最新抓取的原始页面 HTML 单独保存于 `raw_page_html`。

### 小步实施任务

下列任务细化 I0–I4 和路线图阶段 0–3，不改变现有阶段状态；每步可独立交付与验证。

| 顺序及目标 | 前置条件与主要任务 | 交付物与验收 | 验证命令 | 风险及失败处理 |
| --- | --- | --- | --- | --- |
| 1 搜索契约与可行性（I0/I2） | 核实三个入口、四种排序、结果类型、分页、编码及站点访问规则；作品结果可确认选择，用户／Tag 结果可继续进入作品列表。 | 搜索参数与结果契约、只读 synthetic fixtures；覆盖中文日文及特殊字符、空结果、分页、重复结果和结构变化。 | 新增测试模块后运行 `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_search -q`；若加端到端流程，使用 `.\.venv\Scripts\python.exe tests\run_tests.py`。 | 用户明确不要求官方澄清，不将官方答复设为门槛；页面拒绝或限流时停止并报告，不绕过限制；不把 mock 当真实验收。 |
| 2 元数据与章节完整性（I1/I2） | 本地 catalog v2 保存目录组 ID、章节 ID/标题/层级、位置范围及 episode ID 顺序；schema v3 增加主页作品元数据白名单，loader 保持 v1/v2 读取兼容。diff 比较快照并按需排他导出新增或 episode 元数据变化子集；作品级变化只报告字段名。`collect_source(work_metadata=...)` 已将主页元数据写入带记录时间和父版本的 `kind=work` manifest artifact；相同快照复用，archive limit 包含该内容。纯追加 CLI 继承已校验的完整旧 checkpoint/raw 版本并只请求新话；显式全量刷新要求相同完整目录，重取全部话目并追加有变化的不可变 raw 版本。 | 合成 fixture 验证 v2/v3 写入、旧版读取兼容、目录变化报告、纯追加时旧 ID/章节分组不变、只抓新增话、刷新时重抓全目录、正文哈希变化/复用、暂停续传、旧 raw 哈希/版本关系复核、拒绝目录变化和 checkpoint 不覆盖；work artifact 和 manifest 上限也有验证。2026-11-16 真实刷新 88/88 话、0 哈希变化；2026-11-17 纯追加复查发现/完成 88 话、追加 0、复用 88，未请求 episode 正文；同日后续显式全量刷新再次访问 88/88 话、正文哈希仍无变化并新增 88 个 `raw_page_html` artifact。最新 `source_manifest.json` 356/356 校验通过。 | `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`。 | v1 无章节结构，v1/v2 无作品元数据；目录不含正文哈希，只有显式刷新才能发现正文修订。试点基线 v1 无法比较章节分组。作品字段或正文变化不会自动重建概要/知识；快照只记录状态，不自动更改消费者数据。历史非追加目录变化不允许用纯追加/精确刷新路径续用同一基线，需重新审视并制定迁移策略。 |
| 3 原始证据与双版本（I1/I3） | `raw_source` 保存 parser 提取的 UTF-8 可见正文，`normalized_source` 保持字节保真；Kakuyomu adapter 另将原始 HTML 响应保存为独立 `raw_page_html` artifact，绑定作品话目元数据及同一话 `raw_source` 版本。2026-11-17 全量刷新为 88 话补录了 HTML；两种清洗 profile 仍从共同 `raw_source` 独立生成。`scripts/validate_source_editions.py` 可从 raw 重算并逐字节核验两版索引、归档和镜像。 | I2 当前来源、I1 manifest；按版本保留归档；人工验收段落完整性、前后记/作者话、特殊符号与阅读器显示。 | `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_kakuyomu_page_source tests.test_source_editions tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_downstream_freshness_snapshot -q`；试点命令见下方 I3 当前验证记录。 | 历史未保存 HTML 不能从可见文本恢复；原始响应完整性不代表语义无损；未知标记和人读 Ruby/CSS 效果仍需人工检查。 |
| 4 目录与映射（I1/I4） | `RAWs_AI` 稳定 ID 分层、人读版 `<章节名>/<话名.md>`、Windows 名称处理及碰撞消歧已有导出实现；Kakuyomu 编排器与通用 `pipeline.py --project` 在项目同时有 `SourceArchive/`、`RAWs_AI/` 时均默认核验 catalog 摘要、episode 全覆盖和 AI 归档来源，并生成带版本 ID 的 `CHAPTER_MAP`。`workflow_paths.json` 可配置外部人读根与译文根。 | AI 模式计划预览已实际核验 88/88 话。通用入口按 AI 索引位置生成稳定译文路径/TM 键；仍需人工验收 Kakuyomu 章节名、话名、顺序、目标译文路径与 TM 键。测试覆盖缺失/不完整索引、catalog 过期拒绝、输出路径覆盖、输出篡改、安全文件名、输出冲突拒绝和幂等，不替代人工内容映射批准。 | `.\.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts.TestTestWorkspaceConfiguration -q`；若 Kakuyomu 覆盖目录位置，再提供 `--ai-edition-root <AI版目录>`。 | 版本化来源目录缺失或不完整时阻断，不退回人读版；显式 JSON 配置仍由调用者配置映射，AI 默认选择不证明公开目录以外的完整性。 |
| 5 翻译与知识衔接（I4/阶段 1–2） | 使用已获授权的作品、数据类别和目标 Provider；按话翻译，同时将概要作为独立源版本翻译，元数据／抽取知识先进入候选审核。 | 章节与概要译文及各自来源版本；用合成数据验证映射和审核隔离，再以获准作品样本评估忠实度、术语一致性、正文格式和成本。 | `.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_kakuyomu_workflow tests.test_source_pipeline_linkage -q`；合成端到端使用 `.\.venv\Scripts\python.exe tests\run_tests.py`。真实 Provider 单话运行与人工质量验收另记独立结果。 | Provider 未配置或不可用时只做合成验证；未批准知识不作为正式知识，审核回执不证明身份或语义质量。 |

catalog 快照比较可本地执行，无站点请求：

```powershell
.\.venv\Scripts\python.exe scripts\diff_kakuyomu_catalogs.py `
  --source-root <原文根目录> `
  --previous-catalog source_catalog.previous.json `
  --current-catalog source_catalog.discovered.json
```

如要生成供 `scripts/ingest_kakuyomu_pages.py --catalog` 使用的新增话目选择清单，添加 `--export added --catalog-output source_catalog.added.json`；更新标题、顺序或 v2+ 分组信息的话目可用 `--export updated --catalog-output source_catalog.updated.json`。输出是只含所选话目的 v1 清单，需配合独立 checkpoint；其 `complete` 只代表该选集，不代表整书完成。消失话目只报告，不删除历史 artifact。章节层级比较要求旧、新快照均为 v2+；作品级元数据比较要求 v3。差异报告不含作品字段值。catalog 不含正文哈希，因此目录元数据未变化时无法发现正文修订，需操作者显式选择全量刷新；作品元数据变化也不会自动重采 episode。

显式全量刷新可直接由来源 CLI 执行；使用新 catalog 和 checkpoint 路径，保留旧快照、旧 checkpoint 及 raw 历史：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_kakuyomu_pages.py `
  --source-root <原文根目录> `
  --work-url https://kakuyomu.jp/works/<作品ID> `
  --discovered-catalog source_catalog.refresh-2026-11-16.json `
  --output-root <原文根目录> `
  --refresh-from-catalog source_catalog.previous.json `
  --refresh-from-checkpoint source_checkpoint.previous.json `
  --checkpoint source_checkpoint.refresh-2026-11-16.json
```

基线 catalog 路径相对 `--source-root`，基线/新 checkpoint 路径相对 `--output-root`。暂停后保持本次 `--discovered-catalog` 和 `--checkpoint` 路径不变，以相同基线续传。完成报告中的 `content_refresh` 只含话目 ID、旧/新版本 ID、SHA-256 和变化计数，不含正文；`downstream_review_required` 提醒人工复核，并不自动标记译文、概要、TM 或知识过期。目录不一致时须先单独审查新快照，不会在刷新模式下拼接目录版本。

纯追加更新可直接由来源 CLI 执行，不需要先导出选集；请使用新的输出文件名，保留旧快照和完整 checkpoint：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_kakuyomu_pages.py `
  --source-root <原文根目录> `
  --work-url https://kakuyomu.jp/works/<作品ID> `
  --discovered-catalog source_catalog.2026-11-16.json `
  --output-root <原文根目录> `
  --incremental-from-catalog source_catalog.previous.json `
  --incremental-from-checkpoint source_checkpoint.previous.json `
  --checkpoint source_checkpoint.2026-11-16.json
```

`--checkpoint` 必须是新路径；如需从暂停状态续传，保持本次 catalog 和 checkpoint 路径不变。报告中的 `incremental_update` 给出兼容性、追加数和复用数。来源目录、作品或章节发生非追加变化时命令在请求正文前失败关闭。纯追加模式不发现正文静默修订；要核对该情况，使用上面的显式全量刷新命令。

仍需核定的事项：各搜索入口及排序的实际行为；主页元数据字段的完整可见范围；无章节作品的展示名称；概要译文的文件格式和质量门槛。Kakuyomu 原始 HTML 响应归档已有局部实现；其覆盖范围与未来其他来源是否需保存等效原始表示仍需分别验收。AI/人读分支原则及本书具体输出路径已由用户确认，并已实现首版 profile；不再作为未决决策，人工格式与阅读器验收仍待完成。用户已明确本试点不需要 Kakuyomu 官方澄清，故不将官方答复作为实施门槛；代码继续遵守现有 robots、请求间隔、大小限制和失败关闭行为。

## 建议目标架构

```text
用户书名/URL
    -> 来源审查通过的平台适配器
    -> 不可变原始采集记录与来源清单
    -> 结构/标记规范化（保留源版本及转换映射）
    -> 每话 Markdown + 全书 Markdown + 版本清单
         -> 显式 CHAPTER_MAP -> 现有翻译流水线/TM/知识候选
         -> Notion 备份/检索副本（主要单向；规划双向编辑）
         -> Pandoc 候选工具 -> 章节 EPUB / 全书 EPUB
```

### 数据层与版本关系

建议用本地项目目录作为权威数据源，后续实现可先使用有 schema 版本的 JSON 清单及 Markdown 文件；不在需求和规模验证前引入数据库或队列。

每个作品/章节版本至少关联以下概念：

| 对象 | 规划标识/属性 | 不变量 |
| --- | --- | --- |
| 作品 | 稳定 `work_id`、来源平台/作品 ID、采集许可状态、元数据版本 | 书名不是唯一键；不同来源作品不得仅按标题合并。 |
| 话 | 稳定 `episode_id`、作品 ID、来源章节 ID/URL、原始顺序、发布状态 | 来源 ID 缺失时保存来源内可复核标识，不静默猜测。 |
| 原始采集版本 | 获取时间、原始页面/响应引用、内容哈希、采集器版本、许可审查引用 | 只追加、不覆盖；重新采集产生新版本或明确的未变更记录。 |
| 规范化版本 | 父原始版本 ID、转换器版本、输出哈希、转换差异/标记映射 | 派生文件不取代原始证据；规范化失败时保留旧版本并报告。 |
| 翻译版本 | 目标语言、模型/配置/提示词标识、原文版本 ID、输出哈希、质量状态 | 原文版本变化时标记翻译可能过期，不自动覆盖人工译文。 |
| 知识候选/批准项 | 类型、提出来源版本/话/段落、候选状态、审核记录、版本 | 模型抽取只产生候选；批准、修订和废弃需要可审计的状态转换。 |
| 备份记录 | 目标 Notion page/database ID、源对象版本/哈希、同步状态/时间 | 同步副本可检测过期；双向变更须经冲突处理后生成本地版本，不得静默覆盖。 |
| EPUB 产物 | 输入章节版本 ID、工具/配置版本、输出哈希、验证结果 | 只作为构建产物；源 Markdown 保持不变。 |

沿用现有 TM `source_provenance` 有助于追踪新翻译记忆，但它只记录部分源/译文件哈希与段落位置，不替代作品、采集、清洗和翻译版本目录。

### 原文保存与规范化

- 原始采集层保存平台返回的原始文本/结构、来源 ID、采集时间、页面元数据和内容哈希；禁止用清洗结果覆盖原始层。
- 规范化只改变表达结构，不删改原意。至少覆盖标题层级、话标题、前记、后记、作者的话、插图占位/说明、分隔线、空白段和站点标记。
- 每一类格式转换要有输入/输出 fixture、转换器版本和差异记录。不能确定语义的内容保留原文并标记待人工确认，不静默丢弃。
- 输出 `episodes/<episode_id>.md`，并按来源顺序生成全书合并 Markdown。合并文件是派生物；章节文件为逐话翻译/审阅和 Notion 批量导入的基本单元。
- 元数据至少包含稳定 ID、标题、作者（若来源明确提供）、概要、详细介绍、Tag、来源 URL/ID、采集时间、许可审查状态和元数据哈希。缺失/冲突字段显式留空或标记冲突，不由模型补成事实。

### 续传、增量与完整性

- 采集作业保存运行 ID、来源作品 ID、已完成话 ID、最近成功位置、失败类别和源版本哈希；续传只补未完成或明确变化的对象。
- 增量对比稳定来源 ID、发布状态、顺序和内容哈希，分别报告新增、更新、删除/不可见、重复、顺序变化和未知差异。
- 不把平台页面上当前可见话数直接称为全书完整；完整性报告要记录枚举时间、可见范围、分页/访问失败、已获取项目数及缺项。
- 网络错误、限流或权限拒绝应暂停/退避并保留状态；遇到访问限制、验证码或平台明确拒绝时停止，不尝试规避。
- 重新采集的内容产生版本差异；已关联译文、知识或 EPUB 的章节不可静默替换，先标记下游产物过期并请求复核。

## 来源许可与合规门禁

每个平台应形成独立审查记录，至少包含：

- `已确认（用户声明）`：用户明确确认指定作品获得授权。记录用户声明的处理范围；本计划不要求额外文件才承认该确认，也不将其扩展为公开分发授权。
- 平台当前服务条款、版权/开放许可声明、API/数据导出条款和自动化访问规则的官方来源、访问日期及适用范围。
- robots 规则或公开 API 的作用与限制；不得仅因页面可公开访问就推断允许批量采集、保存、翻译或再分发。
- 登录、付费墙、验证码、访问频控、个人数据和删除/保留要求；不得绕过访问控制或反自动化措施。
- 用户上传/Notion 备份/外部 Provider 处理是否属于额外披露；按不同目的单独授权。
- 结论应准确区分“用户/权利人声明”“平台明文规则”“技术访问观察”和“未知”，不得把未知表述为平台已允许。用户明确表示无需官方澄清；不把平台答复设成本试点前置条件，也不把用户决定改写为平台背书。硬性访问限制仍由实现遵守。

平台/法律规则可能变化，正式实现前必须重新查阅目标平台官方资料；本文件不代替法律意见或用户授权。

### Kakuyomu I0 规则核查 2026-11-14 至 2026-11-15

该段记录 2026-11-14 至早期 2026-11-15 的规则核查历史，不是后续 live 采集状态；当前结果和用户决定见下方[实时访问复核与执行记录](#kakuyomu-live-access-review-and-user-decision-2026-11-15)。

2026-11-15 复查：当前服务利用规约页显示最后更新为 2025-08-06；重新核读第 5、12–14 条，未发现自动采集 API 或针对本项目用途的明确自动化授权路径。官方 `robots.txt` 经用户配置的本地代理读取成功，仍包含下述 episode `/read` 路径 `Disallow`。该规则核查发生在本次普通 episode 页面探测/导入之前；随后按用户明确要求，仅通过用户提供的普通 episode URL 完成一次单话导入。普通页面请求成功不改变条款核查结论，也不证明平台允许批量采集或公开分发；这不是法律意见。

| 官方来源 | 核查事实 | 对本项目的含义 |
| --- | --- | --- |
| [服务利用规约](https://kakuyomu.jp/legal/tos)，2026-11-15 复查显示更新日为 2025-08-06；[2025-07-31 事前公告](https://kakuyomu.jp/info/entry/20250731_tos_update)说明计划修订，[2025-08-06 改定公告](https://kakuyomu.jp/info/entry/20250806_tos_update)确认实施。[2026-02-02 公告](https://kakuyomu.jp/info/entry/20260202_tos_update)针对付费服务相关规约，并非一般服务利用规约。 | 2026-11-15 复核的第 5 条允许平台在过量负荷等情况下限制使用或阻断访问。第 12 条规定，未经平台许可，不得将服务取得数据超出著作权法认可的私人使用范围用于复制、销售或出版；涉及第三方权利时提及经平台取得该第三方许可。第 13 条限制营利目的使用。第 14 条含服务干扰、权利侵害及其他禁止行为。条文没有在本次复核范围内明确给出本项目的自动采集 API 或许可路径。 | 指定作品已由用户明确确认获得授权；该授权事实按用户声明记录。平台访问规则仍须另行满足；条文适用不作法律结论。个人/非商业目的不能单独证明自动复制、翻译、模型处理或备份均获平台许可。 |
| [官方 `robots.txt`](https://kakuyomu.jp/robots.txt)，2026-11-14 10:42 UTC 返回 HTTP 200；2026-11-15 经本地代理复查 | `User-agent: *` 中含 `/works/*/episodes/*/read$`、登录等 `Disallow` 路径；另有单独的 `ClaudeBot` `Crawl-delay: 1`。未请求或测试任何章节路径。 | 对匹配 `Disallow` 的路径不实现抓取，也不改用其他路径绕过限制。robots 是爬虫访问指引，不是著作权许可或整体自动化访问授权；路径规则不能外推为其他路径的许可。 |
| [阅读与服务 FAQ](https://kakuyomu.jp/help/entry/faq_kakuyomu)，2026-11-14 查阅 | FAQ 说明一般浏览器可不登录阅读；这只说明普通浏览访问条件，不授予批量复制、保存、翻译或向第三方发送权利。 | 不把页面可读或无需登录推断成允许自动采集。 |
| [知识产权规约 FAQ](https://kakuyomu.jp/help/entry/faq_authors_personal_rights)，2026-11-14 查阅 | 平台解释其服务条款不将投稿作品著作权转给平台，作品著作权仍属于作者；第三方不能据此规约擅自出版。 | 该 FAQ 本身不证明本项目授权；用户已另行明确确认指定作品获得授权，本计划按该声明记录，不要求额外文件才承认此确认。 |
| [小说备份帮助](https://kakuyomu.jp/help/entry/download_works)，2026-11-15 查阅；[功能公告](https://kakuyomu.jp/info/entry/2018/11/14/162115) | 官方说明作者可从浏览器工作区下载自作小说 ZIP；示例包含 `about.txt` 与 `episode_0001.txt` 等逐话 UTF-8 文本。帮助页同时说明 App 不支持、仅可下载自作小说、下载文件没有回导功能。 | 这是作者账号发起的手动备份，不是面向普通读者的他人作品导出、程序化 API 或自动采集许可。用户已明确为普通读者，因此此路线不适用于本试点，也不要求提供 ZIP；本试点改用用户指定的普通 episode URL。 |

**初步结论**：D-13/I0 的规则资料和用户操作决定分开记录。用户已明确确认指定作品获得授权，并明确表示不需要向 Kakuyomu 官方澄清；本试点按用户决定使用普通作品主页发现公开目录，再访问普通 episode URL。2026-11-15 复核的一般规约第 12 条与 robots 规则继续作为平台风险记录，不把技术可访问或用户授权写成平台背书，也不作法律结论；官方澄清不是本试点执行前置。采集器不请求 robots 禁止的 `/read`，不登录、不跟随重定向或调用未文档化 API。88/88 主页声明的公开目录章节已按默认 2 秒（允许配置 1.5–3 秒）间隔获取并归档，不包括草稿/私有话，也不授权公开分发。官方作者备份只适用于作者账号手动下载自作小说；用户为普通读者，故该路线不适用。JOJO/JYQF 各自职责的最小数据类别已由用户授权；本地 allowlist、端点仍未验证，其他 Provider/类别、Notion 接收范围及保留边界须分别落实。

### Kakuyomu live access review and user decision 2026-11-15

- 通过项目配置的本地代理重新读取实时 `robots.txt`：HTTP 200；`User-agent: *` 允许普通 work/episode 页面路径，并禁止对应 `/read` 路径。robots 放行普通页面只说明该爬虫规则未禁止该 URL，不构成平台对批量采集、复制、翻译或模型处理的授权。
- 只请求指定作品主页、不请求章节正文，并仅统计页面 HTML 中的普通 anchor 链接：HTTP 200，164,967 字节，8 个匹配链接、7 个唯一 episode URL；页面内目录此前标明 `publicEpisodeCount=88`。因此普通 HTML anchor 列表不足以发现用户要求的完整公开目录。
- 当前 adapter 通过 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 读取嵌入页面的 Apollo 目录；章节正文抽取还依赖 `js-episode-body` 与 `widget-episodeTitle` 页面 class。实时服务条款页面标注 2025-08-06 更新，并禁止分析网站/应用的源代码、结构、想法等；本项目目录及正文解析是否落入条款范围尚未获得平台解释，不在本计划中作法律结论。
- **用户操作决定（2026-11-15）：**用户明确表示不需要官方澄清，并要求按普通作品主页发现目录、再通过公开普通 episode URL 获取原文。此决定取消“等待官方答复”作为本试点实施前置条件；它不修改平台条款，也不被记录为平台许可或法律结论。继续遵守 robots 的 URL 限制，不访问 `/read`，不登录、不伪装身份、不调用未文档化 API 或尝试绕过访问控制。
- **实际执行：**按默认 2 秒间隔重新读取 robots、作品主页并顺序请求 88 个目录 episode URL。目录唯一 ID 数与 `publicEpisodeCount=88` 一致；source-only CLI 完成 88/88 话归档，checkpoint 状态为 `complete`，没有调用 Provider。采集后 manifest 的 178 个文件通过哈希核验；随后又产生 88 个 normalized 章节 artifact 和一份 export，最终清单为 267 个文件型 artifact，全部通过 SHA-256 校验。共生成 88 个单话 Markdown 和一份 793,357 字节的有序全书 export。parser v4 将 ruby 转为 `｜基字《读音》`、旁点转为 `｜文本《・・・》`，保留 U+3000；旁点行为由合成测试覆盖，真实首话没有旁点标记。
- **剩余边界：**88/88 仅说明此次抓取覆盖该主页声明的公开目录，不含草稿/私有话或平台计数外的范围，也不保证各话属于同一时刻的原子快照。作品授权按用户明确声明记录；Provider、Notion、公开分发仍须各自遵守已记录的数据和用途边界。后续人工格式审阅、真实 Provider 翻译及质量验收尚未完成。

## 翻译、知识库与 Notion

### 接入现有翻译流程

- 每话规范化 Markdown 通过显式 `CHAPTER_MAP` 指定 `raw_file`、`translation_file` 与稳定 `tm_key`；保留来源章节 ID、顺序和原始版本 ID，禁止按数字或文件名猜配。
- 对本试点，全书预读是首话正式翻译前的必经工作流步骤，目标为基于全书生成术语、人物、世界观、视角/口癖候选；现有 `--full-book` 已支持 token 预算分批抽取和候选级分层综合，并把最终结论限制在候选携带的原文段落证据内。该能力仍需验证真实模型质量，不能替代人工核对章节覆盖及已批准知识回执。若整书超预算，不得把截断输入描述为“已通读全书”；未经核定的 Gemini/Claude 不接收试点原文。
- 人名、专名、术语、世界观、一人称代词/口癖、人物语气生成结构化候选；来源定位到原始/规范化版本和话/段落。现有抽取脚本可作为候选校验起点，但需扩展类型和来源，不直接自动发布。
- 采集的作品简介、Tag 和元数据可以成为知识候选/检索上下文，需保留来源及冲突状态；来源自述与模型推断分开标记。
- 原文、译文、知识、评测样本的外发仍服从逐 Provider 数据授权；采集和 Notion 还需各自独立的目标服务授权，不从 `PROVIDER_DATA_POLICY` 推断 Notion 许可。

### Notion 作为备份副本

- 本地版本清单与项目文件为权威；Notion 是备份/浏览和协作副本，不作为唯一副本。主要场景为单向备份，同时规划双向编辑与冲突合并；远端修改不得静默覆盖本地内容，需保留来源版本和合并记录。
- 用户指定目标为 `BOOK/Novel/Light-Novel/` 下的轻小说工作环境，希望数据库结构便于 AI 读取和人工查阅；用户表示该处部分旧内容可修改或覆盖。本轮不修改 Notion；实施前先只读核实完整页面层级、现有数据库与权限，并明确具体操作对象。此前按名称只读搜索发现 `Light-Novel` 与作品同名页面，不能据此确认完整层级或权限。
- 建议设计相关联的作品、话、译文和知识 Database：作品记录保存元数据/来源与许可状态；话记录保存稳定 ID、顺序、版本、来源链接、原文/译文哈希与同步状态；译文关联话和版本；知识区分候选、已批准、冲突、废弃及来源。具体结构与 API 能力须验证。
- 大文本可使用页面正文块，Database 属性只放稳定标识、状态和索引字段。具体 Notion API 可写字段、分页、块大小、限流、删除及权限行为需实施前复查官方 API 文档；本文不预设数值限制。
- 先用合成数据验证单向 upsert，再在 Notion 目标、权限及数据类别范围核实后试点：本地版本哈希与 Notion 记录相同时跳过；源版本变化时创建新版本或报告冲突。正文和知识的双向冲突保留双方版本并报告差异，等待处理；自动合并不重叠变更作为后续优化，须验证共同基线和格式转换。
- 记录待同步/成功/重试耗尽/冲突状态；网络和限流错误可退避重试，鉴权/权限/内容错误需停止并提示处理。同步成功需回读关键字段或用列表核对条目数、版本 ID、哈希；定期执行完整性审计。
- 凭据存储采用系统凭据库；Key/token 不写入 JSON、日志、Markdown、Notion 属性或错误输出。原文和译文是否可上传必须有人类明确批准。
- 备份验收包含恢复演练：从 Notion 备份副本恢复到隔离目录，与本地清单比对哈希和对象数量；在演练通过前不得将 Notion 宣称为可恢复备份。
- 数据按版本保留至用户显式删除；Notion 删除可提出本地删除请求，但每次须经用户显式确认才执行，记录删除目标、结果和失败状态。规划本地及获授权远端副本的删除、撤回和失败报告，同时核实适用保留义务。

## EPUB 产物

- Pandoc 是当前 Windows 主机上发现的候选工具，不是仓库依赖。2026-11-15 `Get-Command pandoc` 解析到 `C:\Program Files\Pandoc\pandoc.exe`，`pandoc --version` 返回 `3.9.0.2`；安装来源、其他环境可用性及版本锁定流程未核实。
- 首批目标为 Calibre 电子书阅读器、Apple Books 和 Thorium Reader，并辅以 EPUB 结构验证；阅读器版本、测试设备和可用性待验收前核实。目前仅个人本地阅读，未来可能在小众论坛交流 EPUB；分发前另行核实作品、译文、字体和图片的分发权利。
- 构建输入只能是选定章节/全书的规范化译文 Markdown；输出到独立 `EPUB/` 目录，保存源版本清单、构建参数和输出哈希。
- 元数据规划：书名、作者、语言、简介、出版/版本信息和章节排序；目录基于显式章节清单，而不是文件系统顺序。
- 样式规划：CSS 控制段落、标题、注释/作者话和分页；字体需确认许可与嵌入条件。日文标点、中文标点、Ruby/注音、插图标记等特性按实际样本逐类验证。
- 章节 EPUB 以一个翻译章节组为输入；全书 EPUB 仅在全部选定章节通过质量门禁后构建。任何缺章、重复、版本不一致或门禁失败都应生成失败报告，不产出看似完整的成品。
- 使用 EPUB 结构验证工具（例如候选 `EPUBCheck`，实施前确认可用性）和目标阅读器抽查；抽查目录、顺序、元数据、字体回退、特殊字符、空白及文本往返。验证失败不改写原始 Markdown。

### 离线候选构建原型（2026-11-15）

`epub_builder.py` 与 `scripts/build_epub_candidate.py` 可用 Pandoc 从显式章节 catalog 构建一个不可覆盖的候选目录：`<output-root>/<work_id>/<build_id>/candidate.epub` 和 `build.json`。catalog 为 UTF-8 JSON schema v1，必填 `schema_version`、安全的 ASCII `work_id`/`build_id`、`expected_pandoc_version`、书名/作者/语言/identifier 和按 `position` 严格递增的 `chapters`；每话含 `episode_id`、`position`、`title`、`translation_path`、`source_version_id`。章节路径必须位于显式输入根目录内，Markdown 首个非空行须为与 catalog 标题一致的 H1。catalog 上限 1 MiB，单章/总输入/EPUB 输出上限须在 CLI 显式提供；超时默认 120 秒，可显式调整，最大为 24 小时。单章、总输入和 EPUB 输出上限的最大配置值为 1 GiB。安装 Pandoc 版本必须与 catalog 的 `expected_pandoc_version` 精确一致。

该工具始终把产物标记为 `artifact_status: candidate`、`quality_gate_status: not_evaluated`、`coverage_scope: explicit_episode_selection`。它记录实际 Markdown 哈希、来源版本声明、Pandoc 版本、EPUB 哈希及字节数；构建前读取显式 source manifest，校验每个 `source_version_id` 的文件哈希、作品/episode artifact identity 和该 artifact 的最新 normalized 版本，并把 manifest 相对路径与 SHA-256 写入 sidecar。该校验不证明所选章节覆盖全书，也不代表翻译质量或分发批准。工具拒绝图片标记，因此不处理插图、字体、CSS 或依赖图片的排版；源 Markdown 不修改。内置检查限于 ZIP CRC、mimetype、container/OPF manifest/spine 和 XHTML XML 可解析性；不是完整 EPUBCheck，也不是阅读器验收。当前 `PATH` 未解析到 `epubcheck` 命令，未在 Calibre、Apple Books 或 Thorium Reader 测试。这个子项不关闭 I5。

本机合成验证命令：`.venv\Scripts\python.exe -m unittest tests.test_epub_builder -v`；静态检查：`.venv\Scripts\python.exe -m py_compile epub_builder.py scripts\build_epub_candidate.py tests\test_epub_builder.py`；CLI 帮助：`.venv\Scripts\python.exe scripts\build_epub_candidate.py --help`。catalog 的完整字段以 `tests/test_epub_builder.py` 合成 fixture 为准。

## 分阶段开发计划

`I0–I6` 是专题工作包编号，与[项目路线图](roadmap.md)的阶段编号分开维护。状态只在路线图记录；工作包整体仍为`计划`。I1 有局部合成原型；I2 有平台无关来源核心/本地导入、Kakuyomu 主页公开目录发现和普通 episode URL 获取，首话已按用户提供 URL 实际导入；主页目录解析须匹配站点声明的 `publicEpisodeCount`，并非对草稿/私有章节或站点外部目录的完整性证明。I3 有字节保真的单话 `.md` 物化、显式章节集合导出和完整 checkpoint catalog 导出子项。后者只校验当前可编辑 checkpoint 所记录条目是否可导出，不证明 checkpoint 未被改写或平台目录穷尽；I4 有显式来源版本绑定及 TM/知识草稿只读新鲜度审计子项。范围和缺项见对应行及验证记录。

| 工作包 | 目标、工作与交付物 | 前置条件/依赖 | 验收标准 | 风险与缓解 |
| --- | --- | --- | --- | --- |
| I0 来源许可与产品边界 | 评估已指定作品的 Kakuyomu 普通读者场景；记录用户已确认的作品授权、平台规则观察和用户决定，并分开核定数据类别、保留删除及目标服务范围。 | 已提供作品与拟用目的；指定作品和 JOJO/JYQF 各自职责的最小类别已由用户确认；用户明确不要求官方澄清。用户决定不等同于平台背书或法律结论；其他 Provider/Notion 接收范围仍独立处理。 | 记录官方规则来源、访问日期、技术访问限制与用户决定；采集不访问 robots 禁止路径或绕过登录/访问控制。 | 平台规则会变化，保留适用范围与操作证据；不把网页可访问、robots 放行或书籍授权外推成公开分发许可。 |
| I1 本地数据模型与版本清单 | 定义作品/话/原始/规范化/翻译/知识/导出版本 ID、哈希、关系和状态；制定目录与清单 schema。已实现 ID、哈希、父版本关系、相对路径检查及显式根目录下文件字节哈希核验的合成原型；父版本 DAG 采用迭代校验，深链不依赖 Python 递归栈。未覆盖状态流转或业务集成。 | 基础版本图可用合成数据独立验证；用于真实数据前仍依赖 I0 数据类别/保留边界及 D-16；对应路线图阶段 1、2。 | 合成 fixture 覆盖重复 ID、缺失/循环父版本、深层无环链、schema、路径和文件哈希；后续补齐版本迁移、状态规则及从译文/知识/导出到输入的端到端追溯。 | 过早引入 DB/队列；先用本地文件和版本化清单验证规模需求。 |
| I2 单平台只读采集试点 | `SourceAdapter` 分页/续传/归档核心、显式路径 `LocalFileAdapter` 与 `scripts/ingest_local_sources.py` 已实现；Kakuyomu adapter 从作品主页发现完整公开目录，并用普通 episode URL 取文。每话 HTML 精确响应字节作为独立 `raw_page_html` 版本保存，解析后的可见文本仍保存为 `raw_source`；HTML artifact 绑定话目元数据及对应正文版本。目录和正文请求均检查 robots，不登录、不跟随重定向、不访问 `/read`，请求间隔 1.5–3 秒、默认 2 秒。采集为跨时间滚动快照；纯追加只抓新增话，显式刷新要求目录匹配并重取全部话目。2026-11-17 全量刷新完成 88/88，正文哈希无变化，新增 HTML artifact 88 个；source manifest 356/356 校验通过。 | 用户已确认作品授权并要求从主页发现完整目录、使用普通页 URL；明确无需官方澄清。归档根为项目内 `SourceArchive`；外部 `生肉` 是人读清洗版、外部 `熟肉` 是译文根。旧基线 catalog v1 无章节分组，本次不能证明旧/新分组相同。采集不含草稿/私有话，也不证明主页声明外完整性、平台背书或公开分发许可。 | `tests.test_kakuyomu_page_source` 覆盖 synthetic 目录、robots/URL、限速、重定向/限流、大小、标题、续传和格式。当前采集 manifest 356/356、合并 edition manifest 532/532；默认 AI 计划 88/88、0 问题、无网络/Provider；详情见[当前验证](development.md#2026-11-17-原始-html-归档与默认-ai-计划复核)。 | 目录结构/count 变化即停止；不请求 `/read`，不登录或绕过访问控制；逐话 hash 记录正文/页面变化；不外推草稿/私有话或平台外完整性；保留限速和大小上限。 |
| I3 原始归档与双版本清洗 | `部分实现`：采集器分别归档可见文本 `raw_source`、字节保真的 `normalized_source` 和原始页面响应 `raw_page_html`；HTML 与 episode metadata、同话正文版本绑定。新采集把规范化 charset 写入 episode metadata，并由父版本关系绑定到 HTML artifact；原始 HTML bytes 不转码。`scripts/validate_kakuyomu_html_archive.py` 先预检 HTML 总字节上限，再校验全部 manifest 文件哈希；重放每话最新 HTML 时验证唯一标题/正文、当前 raw lineage 与 parser v4 输出哈希，并按记录 charset 解码。旧 metadata 缺字段时兼容 UTF-8；这不证明历史响应头字符集。默认上限 1 GiB，摘要不含正文。AI/人读版从同一 `raw_source` 独立清洗，前者以 AI 识别效率优先并作为翻译默认输入，后者以人类阅读观感优先。 | I2 当前来源、I1 manifest；按版本保留归档；人读版 Markdown/Ruby/CSS 显示及段落完整性需人工验收。 | `tests.test_source_editions` 覆盖双 profile 与 lineage；`tests.test_kakuyomu_page_source` 覆盖 charset 解析；`tests.test_kakuyomu_html_archive` 覆盖新 charset replay、legacy UTF-8 fallback 与 lineage。2026-11-19 试点 validator 返回 88/88、356 个文件哈希有效、`verified`；详见[当前工作树验证](development.md#2026-11-19-当前工作树回归与来源边界修复)。 | 历史 HTML 仅哈希校验，回放只对最新版本执行；旧档案缺 charset 时只能采用 UTF-8 兼容假设，无法恢复原始响应头；完整响应与哈希一致不证明语义无损；未知标记和阅读器视觉效果待检查。 |
| I4 翻译与知识库接入 | `部分实现`：`CHAPTER_MAP` 支持可选 `source_version_id` 并核验 manifest 中最新 normalized→raw lineage；Kakuyomu workflow 从主页发现的公开 episode ID/位置生成确定性译文路径、TM 键和章节映射。显式全书抽取会读取当前全部配置章节，依调用者提供的 tokenizer JSON、context/output/safety/message 预算按段落切分，最多 500 段/批、100 次串行调用；概要/术语审核器支持全书来源集，并保存逐批 hash/coverage 与概要结论段落指针。Kakuyomu 与通用 `pipeline.py --project` 正式入口均默认从 AI 清洗版生成翻译映射，并在创建翻译管线前要求 approved 全书概要覆盖当前 AI 章节文件名/来源版本；缺失或错配时停止。通用显式 JSON 配置仍由操作者提供，可使用兼容输入路径。TM、知识和概要审计可报告 `stale`/`invalid`；`scripts/snapshot_downstream_freshness.py` 可将 TM/知识以及已审核全书概要结果保存为绑定来源 manifest 和消费者输入哈希的只读 schema v2 快照。概要审计要求当前版本化章节映射并核对全书覆盖，只持久化哈希、状态和详情，不包含概要正文。Kakuyomu 完整编排会在计划生成后自动追加翻译前快照，成功翻译后追加翻译后快照；独立 `scripts/ingest_kakuyomu_pages.py --project <项目名>` 也会同步来源历史至 edition manifest，并记录 AI 索引和下游新鲜度状态。该独立采集模式不重跑双版本清洗；来源或 catalog 前进时记录旧 AI 索引/全书概要为 `stale`，完整编排随后生成新 AI 版本。相同快照状态幂等复用，状态变化追加新文件。通用版本化翻译入口也会阻断与当前 source version 不匹配或缺少已提交 TM 证明的既有目标，不覆盖旧译文。快照只留档，不写回消费者状态、不替代运行时新鲜度门禁或自动重建派生物。 | I2 公开目录发现、I3 来源标识与版本清单；现有翻译契约、D-01 知识审核责任和 D-02 Provider 授权；对应路线图阶段 1、2、3。 | `.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_kakuyomu_workflow -q` 覆盖快照 schema、哈希绑定、幂等追加和完整编排调用边界；`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_editions -q` 覆盖独立采集项目快照与 edition manifest 合并；更广来源/AI 选源/审批/概要回归与 `tests\run_tests.py` mock E2E 另见[开发与验证](development.md#2026-11-17-独立-kakuyomu-采集的项目新鲜度留档)。真实 Provider tokenizer/context 参数及候选质量仍未验收；Kakuyomu 用户授权及普通主页/episode URL 路径已确认，无需官方澄清。 | tokenizer 文件/模型配置不匹配或 chat template 开销低估时，估算可能偏离端点行为；分批候选确定性拼接不等于跨章叙事综合；通用配置章节集不自动证明完整目录；快照不会修改人工译文/审核数据，但也不会替代消费者运行时校验或重建下游；本地审核回执未签名且不认证身份。 |
| I5 EPUB 构建与验证 | `部分实现`：`epub_builder.py` / `scripts/build_epub_candidate.py` 提供显式有序 Markdown catalog 的离线候选构建；要求精确 Pandoc 版本，校验 source manifest 中逐话来源版本/身份/hash/新鲜度并记录 manifest hash，记录输入/输出哈希和参数；输出不可覆盖并做有限 ZIP/OPF/XHTML 结构检查。始终标记为 candidate，拒绝图片，未实现目录/字体/CSS 定制。 | 完整验收依赖 I3 格式结构、I4 译文版本/质量门禁、字体许可和目标阅读器设备；当前环境 Pandoc 3.9.0.2 可用但来源未核实，当前 PATH 未解析 EPUBCheck。对应路线图阶段 5 的本地交付子项。 | 合成 fixture 验证章节顺序、TOC/XHTML 存在、输入不变、来源版本对 manifest 绑定、manifest hash、精确版本、尺寸上限和不覆盖。完整验收还需 EPUBCheck、文本往返、特殊字符/排版及 Calibre、Apple Books、Thorium Reader 实测；candidate 标记不能作为完整性或质量批准。 | Pandoc 环境漂移、标题格式与图片缺失、阅读器渲染差异；固定 catalog 版本、限制为文本候选，并显式报告未覆盖验收。 |
| I6 Notion 备份试点与扩展 | 只读核实目标位置和权限；先用合成内容验证单向备份，再设计并验证双向编辑、冲突处理及删除传播；仅对获准项目小批量同步，交付完整性报告与恢复演练。 | I1–I4 稳定 ID/版本；Notion API 官方文档复核；保留义务、Notion 接收范围与具体数据类别核实；对应路线图阶段 5。 | 分页、限流、重试、幂等、双方版本保留、逐次确认反向删除及失败恢复均有测试；凭据不进日志；云端 ID、版本、哈希和数量与本地可核对；隔离目录恢复演练通过。 | API 变更、冲突和外发风险；先合成数据、单向试点，双向策略经验证后扩展，不静默覆盖。 |

2026-11-17 Kakuyomu 追加模式真实复查：作品主页发现/复用 88 话、追加 0、待处理 0；没有新增话，因此没有请求 episode 正文。此项验证真实无变化续跑路径，不验证新增话目的 live 抓取。索引刷新后默认 AI 版计划为 `ready_for_review`、88/88 来源有效、0 问题；详细命令和结果见[开发与验证](development.md#2026-11-17-kakuyomu-追加无变化复查与-ai-默认输入)。

### 验证方式与命令

工作包整体仍为`计划`；已实现子项按实际测试入口验证，未实现子项的命令是后续验证建议，不表示其功能或专项测试已经存在。运行现有测试只能验证已覆盖的代码。

- **I0**：记录用户对指定作品授权的明确确认；人工逐平台审查官方条款、自动化访问规则及接入方式，并记录 URL、访问日期、结论和责任人。没有能替代平台规则审查的代码测试命令。`git diff --check` 只检查文档补丁格式，不验证作品授权或平台许可。
- **I1**：当前原型入口为 `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest -q`；当前工作树 20 项合成测试通过，包含深层无环版本链及文件型 artifact 内容字节统计。使用 `.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <项目根目录> --manifest source_manifest.json` 可只读校验清单及其列出文件的字节哈希；清单路径和内容路径都限制在显式根目录内，源文件不被写入。`tests\run_tests.py` 默认启动模型 mock server 并运行 E2E，不是此单元测试的默认入口。版本状态流转、与流水线集成及授权/保留策略仍未实现。
- **I2 本地文件导入**：平台无关采集核心和 `LocalFileAdapter` 用 `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q` 验证。catalog schema v1 含 `schema_version`、`work_id`、`episodes`；每项包含 `episode_id`、`title`、`position`、`relative_path`，可选 `source_ref`；只读显式列出的根目录内文件且不修改源文件。默认 catalog 文件、单 episode 分别最多 16 MiB，episode 快照累计默认 1 GiB；可选 `--max-archive-bytes` 统计 manifest 中文件型 artifact 的历史版本内容字节，但不是物理磁盘配额。checkpoint v5 绑定来源/额度指纹、目标 manifest 和完成话的 raw 版本。详细输入限额与边界以[开发与验证](development.md)和当前实现/测试为准。本地 TXT 导入与下方 HTTP 页面 adapter 是两条独立路径；本段不再表示 Kakuyomu 页面采集尚未实现。
- **I2 输入边界**：本地空 `episodes` catalog 必须在创建 adapter 或任何输出前失败；JSON catalog 文件读取最多取配置上限 + 1 字节，超过后在解析/输出前拒绝；通用采集核心若截至终页仍未发现章节，不得报告 `complete`，complete checkpoint 至少包含一个已发现章节。空中间页可带 cursor 继续分页。单章/单批上限超出、快照后源文件增长均须失败；manifest/checkpoint 输入超限前置项不得发生章节写入。累计上限触发时不追加当前章节 metadata/raw 版本，checkpoint 标记 `archive_limit`；上限由同一 checkpoint 固定，改值需新 checkpoint。该额度只限制新增版本；若清单此前已经超限但本次仅复用既有版本，不会因没有新增而拒绝幂等重跑。`tests.test_source_ingestion` 与 `tests.test_local_source_ingestion_cli` 覆盖这些边界；当前定向运行结果和跳过原因以[开发与验证](development.md)的 2026-11-15 记录为准。
- **I2 Kakuyomu 目录发现与页面采集**：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -v` 使用本地 synthetic HTTP/HTML，不访问网络；两个 CLI 的 `--help` 可核对入口。`--work-url` 从作品主页唯一 `__NEXT_DATA__` 的 Apollo `Work.tableOfContentsV2` 按章节顺序发现 episode ID/title，验证唯一数等于 `publicEpisodeCount` 后生成普通 episode URL；不将首屏 `<a>` 链接误作完整目录。结构缺失、计数不符、重复 ID 或 robots 拒绝时 fail-closed。采集检查 robots，不登录、不跟随重定向、不访问 `/read`；请求间隔 1.5–3 秒、默认 2 秒；限制 HTML 单页 4 MiB、单话文本 16 MiB、全目录文本 128 MiB、最多 1000 话。checkpoint 保存 catalog 后逐话归档，失败后从首个未完成话续传；source fingerprint 绑定 parser/robots/catalog/限额，不绑定正文，因此这是跨时间滚动快照，不是同一时刻的原子快照。可见正文保存为 UTF-8 `raw_source`；自 2026-11-17 起，原始 HTTP 响应体另作为 `raw_page_html` 版本保存并纳入归档预算。2026-11-15 历史 live run 只保存可见正文，manifest 267 个文件通过验证；2026-11-17 显式刷新访问 88/88，正文 hash 未变，新增 88 个页面 HTML artifact，当前 manifest 356/356 通过验证。该目录范围不包含草稿/私有话或主页声明外完整性；新增话目的 live 正文采集仍需等目录出现新增话时验证。
- **I3 当前基线**：`.\.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v` 验证单话字节保真、显式 collection 和完整 checkpoint catalog 导出。手工集合命令为 `.\.venv\Scripts\python.exe scripts\merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --episode-id <章节ID> --episode-id <下一章节ID> --max-bytes <必填输出上限>`；完整检查点模式为 `.\.venv\Scripts\python.exe scripts\merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --complete-checkpoint [<checkpoint路径>] --max-bytes <必填输出上限>`。省略检查点路径时默认读取 `source_checkpoint.json`。章节次序须符合来源位置，输出在章节间插入两个 LF 字节且大小限制包含分隔符。检查点模式要求 v5 检查点完整、逐话 raw 版本绑定与当前 manifest 匹配；CLI 报告 `coverage_scope=complete_checkpoint_catalog` 和 source fingerprint。checkpoint 未签名且可编辑；模式只校验当前记录的 catalog 条目，不证明 checkpoint 未被改写或平台枚举穷尽，也不负责 Kakuyomu 的首页 URL 发现、清洗、差异映射或完整 pipeline 集成；Kakuyomu workflow 已单独提供发现与流水线接入。单话 CLI `scripts/materialize_source_markdown.py` 仍默认每话上限 16 MiB，可用 `--max-bytes` 调整。完整 I3 还需来源完整性证据、真实样本转换规则/差异映射；`tests\run_tests.py` 本身不会验证真实站点或章节格式。
- **I4 来源版本绑定与新鲜度审计子项**：`.\.venv\Scripts\python.exe -m unittest tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_tm_provenance_unit -v` 验证 TM 与知识草稿 provenance 的显式版本关联、当前/过期/损坏/缺失版本状态，以及 CRLF 字节保真样本。`SOURCE_MANIFEST_PATH` 相对 `RAW_DIR`；比较依据是 manifest 中同一 `artifact_id` 的最新 `normalized_source`。Kakuyomu 工作流可从发现的完整公开目录生成确定性 `CHAPTER_MAP`；其他通用来源仍须操作者指定映射。`scripts/snapshot_downstream_freshness.py` 可手工创建只读快照；完整 Kakuyomu 编排会在计划生成后、成功翻译后分别自动追加绑定来源 manifest 和消费者输入哈希的快照，并对相同状态幂等复用。独立 `scripts/ingest_kakuyomu_pages.py --project <项目名>` 现在也会同步来源历史到 `source_editions_manifest.json`，追加 AI 索引和 TM/知识/概要状态快照；catalog 或来源前进时将旧 AI 索引标记 `stale`，但不自动清洗双版本或重建译文/知识。未传 `--project` 的 Kakuyomu 来源 CLI 与本地导入 CLI 仍按 source-only 行为运行。快照只保存哈希、状态和详情，不回写消费者数据，也不替代运行时门禁。`tests\run_tests.py` 不直接调用审计 CLI；审计状态由定向单测覆盖。I4 仍未自动重建过期派生物，也未覆盖人工章节验收。
- **I4 知识抽取输入边界**：`scripts/auto_extract_knowledge.py` 按 `PROOFREAD_MODEL` 通过共享模型路由选择 Provider ID、URL 与 Key，在读章节前核验 `source_text` 授权，客户端创建时复检；显式 `--full-book` 与 `--chapter-position N` 均要求同一 Provider 获准接收 `book_knowledge` 候选。未知模型、缺少远端 Key 或未授权时不读取来源。默认兼容模式最多读取前三个所选章节，提示词截到 20,000 个 Unicode 字符。全书模式读取当前全部配置章节（最多 1000 章），单话模式仅选一个版本化 catalog 位置；两者都要求 verified AI bundle、字符上限及本地 tokenizer/context/output/safety/message 参数，段落按 token 预算分批并综合，原文抽取与综合共受最多 100 次串行 Provider 调用限制。provenance 包含章节/段落覆盖、tokenizer SHA-256、批次 token/hash 记录、候选 lineage 和结论级段落证据。单话概要复用现有审核器按候选哈希、当前来源和 bundle 身份人工批准；可选术语表按词审核。Kakuyomu 流水线在首个模型请求前预检全部待翻译非空章节，逐章复核并注入已批准单话概要/术语，来源或 bundle 失效、知识冲突时停止。该机制不证明配置章节映射等于主页目录，也不验证真实模型 tokenizer/template、审核者身份或候选语义。以上模式只生成待审知识草稿。合成测试及边界见[token-budgeted 全书知识预读](development.md#2026-11-17-token预算分批全书知识预读)、[跨批候选综合](development.md#2026-11-18-全书跨批候选综合)、[单话知识候选草稿（审核接入前检查点）](development.md#2026-11-18-单话知识候选草稿审核接入前检查点)和[单话审核知识接入翻译上下文](development.md#2026-11-18-单话审核知识接入翻译上下文)；历史实现见[全书知识预读](development.md#2026-11-16-全书知识预读输入模式)；路由验证见[Provider 路由对齐](development.md#2026-11-15-知识抽取-provider-路由对齐)。
- **I5**：本地候选原型入口为 `.\.venv\Scripts\python.exe -m unittest tests.test_epub_builder -v`，使用本机 Pandoc `3.9.0.2` 合成构建；`build.json` 的 `epubcheck` 明确为 `not_run`。在目标环境重新运行 `Get-Command pandoc`、`pandoc --version` 并核对安装来源，再选定并运行 EPUBCheck；随后用获准译文验证格式与文本往返，在 Calibre、Apple Books、Thorium Reader 记录版本和验收结果。当前原文/译文目录没有章节文件，故没有真实译文构建、字体/CSS/图片或阅读器验收。
- **I6**：先用 mock/合成 Notion API 响应测试分页、幂等、冲突、删除确认和恢复，并接入 `.\.venv\Scripts\python.exe tests\run_tests.py`；当前没有 Notion 集成或专项测试。任何 live Notion 验收均须先确认目标权限、接收范围和备份数据类别授权，不能由 mock 结果替代。

### 路线图阶段映射

| 项目路线图阶段 | 专题工作包映射 |
| --- | --- |
| 阶段 0 环境与安全基线 | I0、I2 的来源许可/端点条件、采集数据授权与保留边界 |
| 阶段 1 流水线契约与质量门禁 | I1、I3、I4 的版本 schema、规范化验证与翻译映射 |
| 阶段 2 书籍知识审核闭环 | I1、I4 的候选状态、来源追踪与批准后发布 |
| 阶段 3 可替换 Provider 与工作流边界 | I2 的平台适配器边界、I4 的翻译接入 |
| 阶段 4 通用化评估 | 后续第二来源平台/语言或文本场景；需独立样本和许可，不由 I2 自动扩展 |
| 阶段 5 交互与部署（条件阶段） | I5 的本地导出体验、I6 的 Notion 外部备份；均需单独确认用户/运维需求 |

## 风险、依赖与阻塞规则

- 用户已确认指定作品获得授权；该确认消除本计划中的作品权利阻塞。平台自动化访问规则仍独立适用；不得请求 `robots.txt` 禁止路径或换路径规避。JOJO/JYQF 职责所需的最小 Provider 类别已另行授权；其他 Provider/类别及 Notion 接收范围须分别遵守 D-02/D-14。
- 2026-11-15 对实时接入方法复核：当时的 `robots.txt` 允许普通作品主页和 episode URL，但禁止对应的 `/read` 路径；当前 adapter 不请求 `/read`。普通 `<a>` 链接只有 7 个唯一 episode URL，而页面声明 `publicEpisodeCount=88`，故目录解析使用页面内嵌的 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2`。同日查阅的[カクヨム服务条款](https://kakuyomu.jp/legal/tos)页面标注 2025-08-06 更新，并包含关于分析站点/应用结构的限制。用户明确表示无需官方澄清；该判断作为平台风险记录，不作为本试点等待官方许可/解释的实施前置。继续遵守 robots 与不绕过限制的实现边界，不声称平台背书或法律结论。
- Kakuyomu 官方 ZIP 仅供作者账号备份自作小说，需浏览器手动操作且无导入功能。该路线不适用于本试点的普通读者输入，不要求用户提供 ZIP；本试点按用户要求使用显式普通 episode URL。作者 ZIP 的一般功能说明不自动授予访问其他页面或扩大作品处理范围。
- Notion 外发、模型 Provider 外发属于不同接收方和目的，分别授权；不因 `PROVIDER_DATA_POLICY` 已实现就推断 Notion 上传获批。
- 同一本书的原始、清洗、翻译、知识和 EPUB 必须绑定源版本。更新原文时标记下游版本过期，不自动覆盖人工译文/审核结果。
- 现有知识/TM 审核、Provider 授权与跨文件恢复策略仍受[决策记录](decisions/README.md)中的 D-01、D-02、D-11 约束。JOJO/JYQF 各自职责的最小数据类别已由用户确认，但运行时 allowlist 仍为空、真实端点未验证；其他 Provider/类别及 Notion 接收范围未确认前，只可用合成数据验证相应路径。
- 开始实施时先检查当前 Git 状态并保留已有修改；只改动本工作包所需文件，不重置、清理、暂存或提交无关工作。
- 外部文档链接、平台规则和 API 限制会变化；复查日期与观察范围应记录在案。本次已通过普通 Kakuyomu URL 完成 88/88 source-only 采集，生成 88 个单话 Markdown 和一份全书 export，manifest 267 个文件均验证通过。正文人工格式验收、真实 Provider 翻译、Notion API、EPUB 阅读器或部署均未完成。

## 待人类决策

以下事项按各自边界记录；只有标为`需要人类决策`或`需要人类验收`的项目才是相应实施范围的未决项：

- `已确认（用户于 2026-11-15 再次明确确认）`：指定作品已获明确授权，后续按已授权处理，不再把作品权利列为阻塞。该确认不替代公开分发许可的另行确认或 Kakuyomu 自动化访问规则。JOJO/JYQF 的最小职责类别另有明确授权；其他 Provider、Notion 接收方和未覆盖类别仍分别核定。
- `已确认（用户决定）`：用户明确表示不需要 Kakuyomu 官方澄清，按指定作品授权及普通公开 URL 路径继续本试点；该决定不是平台背书或法律结论，不把官方答复设置为本试点的实施前置。
- `部分实现`：2026-11-15 source-only live 采集已从主页发现并归档 88/88 个声明的公开 episode，默认 2 秒间隔；checkpoint 为 complete。178 个 manifest artifact 文件校验通过，并生成 88 个单话 Markdown 和一份 793,357 字节有序全书 export。正文 parser v4 保留 ruby notation、旁点 notation 与全角空格，旁点输出用合成测试覆盖。实际正文/标点人工验收、真实 Provider 翻译、Provider allowlist/端点、Notion 接收范围和公开分发仍未完成。此流程不覆盖草稿/私有话，也不证明主页声明以外的完整性。
- `计划`：先人工核验已保存的段落、ruby、标点和章节标题；再按已确认的主备渠道职责将实际数据类别显式配置到本地 allowlist，之后才运行真实翻译。Notion 备份类别仍需核定。
- `需要人类验收`：EPUB 在三种目标阅读器上的版本与设备；未来向论坛交流前确认作品、译文和字体/图片的分发权利。

### I4 新鲜度门禁实施记录 2026-11-16

- 已将 normalized 当前版本校验收敛为 `source_manifest.py::verify_current_normalized_source`。它检查 normalized 文件哈希、normalized 最新版本，以及最新 raw 父版本是否仍被 normalized 引用。
- 通用章节映射加载、翻译运行前/提交前复核、章节对齐、知识审核发布及 I5 EPUB 候选构建复用该门禁；知识抽取通过通用映射加载继承检查。raw 有新版本而 normalized 尚未重建时，这些入口拒绝 stale 输入。
- 验证命令见[开发与验证](development.md#2026-11-16-i4-消费端新鲜度门禁扩展)。该增量是 fail-closed 只读门禁，不会重建派生物或持久化/传播下游 stale 状态；这些仍是 I4 后续计划。

### I4 默认项目术语表审核门禁 2026-11-17

- 发现默认 `pipeline.py --project` 原先仍把旧式 `Knowledge/Glossary.json` 加载进 RAG；该兼容格式没有审核状态或来源版本 lineage。现在项目模式固定指定 `Knowledge/Glossary_reviewed.json`，并要求 `RAGEngine` 初始化时验证 bundle schema、已批准术语、当前来源版本和 artifact 哈希。
- 文件缺失、旧式格式、损坏或来源过期时，在 RAG 初始化/翻译请求前失败关闭；不会自动退回 `Glossary.json`。显式 JSON 配置由调用者负责，兼容路径未改变。
- 定向合成回归 194 项通过；当前试点没有 `Glossary_reviewed.json`，默认项目翻译会保持阻断，直到从当前来源候选完成人工审核并发布新 bundle。该门禁不验证审核者身份或术语语义。

## 维护规则

- 逐平台、逐目的保留官方资料来源、访问日期、结论、许可边界和复核人；规则变化时重新审查。
- 方案阶段、真实实现状态和验收证据分开记录。实现完成前只可标记为`计划`；mock/合成测试只能证明本地契约。
- 工作包完成后更新[路线图](roadmap.md)，实际代码行为更新[项目现状](project-status.md)/[架构与边界](architecture.md)，知识状态更新[知识库治理](knowledge-governance.md)，人类决定更新[决策记录](decisions/README.md)。
