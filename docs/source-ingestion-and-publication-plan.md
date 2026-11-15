# 原文采集、翻译衔接与成果归档方案

> 状态：`计划`。代码基线为任务提交 `c6f7176`（父提交 `d7e2afd`）；当前工作区另有未提交实现，范围与验证边界见[项目现状](project-status.md)和[开发与验证](development.md)。I1 来源清单、I2 平台无关核心及 Kakuyomu 主页目录发现/普通 URL 采集、I3 UTF-8 Markdown 物化/全书导出和 I5 离线 EPUB 候选构建器均有局部实现；指定试点的 88/88 公开目录话目已 source-only 归档并物化。格式人工验收、真实翻译、平台公开目录之外的完整性证明、完整 EPUB/阅读器验收和 Notion 同步仍未完成。
> 证据边界：现状以当前仓库代码、配置和活动文档为准；历史会话只提供需求背景。本地被忽略的书籍数据不作为授权、来源或质量证据。

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
- `用户输入`：当前拟作个人非商业读取、保存、翻译、发送模型、Notion 备份和阅读，暂不公开分发。用户于 2026-11-14、2026-11-15 明确确认指定作品已获得授权；本方案按已授权记录。用户是普通读者，不具备作者 ZIP 导出权限，并要求从作品主页发现完整公开目录 URL、再用普通 episode URL 获取原文。用户明确表示不需要官方澄清；该决定不改写为平台许可或法律结论。JOJO/JYQF 各自职责所需的最小 Provider 数据类别另已授权；Notion 接收范围仍单独核定。初始 live 页面结构复核见[I0 核查记录](#kakuyomu-i0-规则核查-2026-11-14)，88/88 实际采集结果见下方 I2 记录。
- `用户输入与数据目录快照`：原文根目录为 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉`，译文根目录为 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\熟肉`；用户说明两者目录结构一一对应。初始只读检查时两者为空；截至 2026-11-15 当前记录，原文根目录已归档主页声明的 88 话、生成 88 个单话 Markdown 和一份有序全书 export，来源 manifest 中 267 个文件型 artifact 均通过 SHA-256 核验；译文根目录仍为空。该数据在仓库外，不纳入版本控制。仓库忽略项目 `projects/祝福のネトラレラ` 的 `生肉/`、`熟肉/` 目录和相邻工作区资料均不作为试点章节映射证据；此前 2026-11-14 的 48/19 章文件库存是历史快照。
- `用户输入`：用户没有本地原文或译文，希望系统从 Kakuyomu 获取原文后翻译生成译文；不要求用户提供本地章节。用户于 2026-11-15 明确要求从作品主页发现完整公开目录 URL，再逐话访问普通 episode 页面获取正文；首话已通过显式 URL adapter 导入，主页目录到全目录 URL 的发现/抓取编排已实现。单话导入与主页公开话数核对均不构成对批量访问或公开分发许可的判断。
- `不适用的条件路径`：Kakuyomu 官方作者 ZIP 只供作者账号备份自作小说，且无导入功能。用户已明确自己是普通读者，因此本试点不能依赖作者 ZIP；不要求用户另行提供，也不把它作为当前阻塞。
- `已实现（局部）`：`kakuyomu_page_source.py` 与两个 Kakuyomu CLI 支持显式 JSON catalog 或从作品主页发现公开目录。`discover_kakuyomu_work_catalog` 从唯一 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 依序读取分组及 episode ID/title，核验唯一条目数等于 `publicEpisodeCount` 后生成普通 episode URL。目录和正文请求均检查 robots；每页间隔限制为 1.5–3 秒（默认 2 秒）；不登录、不跟随重定向、不访问 `/read`。正文可从 `div.widget-episodeBody` 或 `js-episode-body` 唯一区域提取，并与目录标题交叉核对。parser v4 保留段落边界、ruby (`｜基字《读音》`)、旁点 (`｜文本《・・・》`) 和 U+3000 全角空格；HTML entity 按 HTML 解析规则解码。保存的是 UTF-8 可见文本，不是原始 HTML 响应；原始 HTML 不落盘。页面大小默认 4 MiB、单章文本 16 MiB、全目录文本 128 MiB、最多 1000 话。checkpoint 先记录 catalog，再逐话请求并即时归档；失败后从首个未完成话续传。每话正文由 raw artifact 哈希绑定；批次是跨时间滚动采集，不是同一时刻的原子全书快照，完整 checkpoint 不自动刷新旧正文。结构/计数异常及 robots 拒绝均 fail-closed。
- `部分实现`：2026-11-15 source-only live 采集已从主页发现并获取主页声明的 88/88 话；生成 88 个单话 Markdown 和一份有序全书 export。完成后来源 manifest 的 267 个文件型 artifact 均通过 SHA-256 核验。真实首话结构检查观察到段落、ruby 标签和 U+3000；旁点由 synthetic fixture 覆盖，不将未出现于样本的标记说成 live 验收。`scripts/run_kakuyomu_workflow.py --work-url` 还可按目录 ID/顺序生成确定性 `CHAPTER_MAP` 并调用生产流水线，但本次没有运行真实 Provider。人工格式/标点/ruby 验收、译文和质量验收未完成。

## 仓库现状与证据等级

### 已实现且有本地验证记录

- `pipeline.py` 提供 Python CLI 章节翻译，单进程顺序执行上下文标注、初译、校对、润色。
- `CHAPTER_MAP` 支持逐话显式指定原文路径、译文路径和 TM 键；不根据章节名自动猜测真实映射。
- 新 TM 写入可包含源文件哈希和段落映射；`scripts/validate_tm_provenance.py` 提供只读来源核验。
- `scripts/auto_extract_knowledge.py` 可生成经过结构校验的知识候选草稿及来源清单；不等于知识已审核或批准。
- `PROVIDER_DATA_POLICY` 默认拒绝向远端 Provider 发送书籍数据；用户已授权 JOJO/JYQF 接收各自职责所需的最小类别。代码默认 allowlist 仍为空，尚未为真实阶段绑定显式启用，真实端点和请求数据未验收；Gemini embedding 与 Notion 接收范围不在此授权内。
- 上述验证是仓库合成测试/mock 证据，不证明真实 Provider、平台访问权或翻译质量。验证记录见[路线图](roadmap.md)和[开发与验证](development.md)。

### 未实现或未知

- 已实现平台无关的分页采集核心、checkpoint 续传、本地 catalog adapter 和 Kakuyomu 主页目录 discovery；未实现其他小说站点 adapter、站点增量差分或独立于站点公开话数声明的完整性证明。续传只在来源快照与目标 manifest 身份匹配时适用；目录 parser 依赖站点服务端页面结构，变化时 fail-closed。
- 仓库未发现 Notion API/数据库同步集成；依赖清单未声明 Notion 客户端。
- 本机能解析到 Pandoc 可执行文件，但本次未核实其版本、EPUB 配置或输出兼容性。其存在不代表项目集成或构建已验证。
- Kakuyomu 为用户选定的平台；指定作品授权按用户明确声明记录。用户明确表示无需官方澄清，并要求普通主页目录发现和普通 episode URL 路径；平台条款及 robots 观察保留为风险记录，不表述为平台背书、许可结论或停止本试点的官方答复门槛。真实 88/88 source-only 采集已执行；其他平台和 Notion 接收范围仍需分别核定。
- 本地忽略目录包含书籍数据且结构复杂；项目现状文档记录了目录/来源审计限制。不得由本计划推断数据合法来源，不得自动上传、改写或生成其映射。

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
- 全书预读是翻译前的可选任务。先估算 token/context；若整书超预算，按有重叠上下文的章节分批提取并做汇总复核，不能把截断输入描述为“已通读全书”。
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
| I2 单平台只读采集试点 | `SourceAdapter` 分页/续传/归档核心、显式路径 `LocalFileAdapter` 与 `scripts/ingest_local_sources.py` 已实现；Kakuyomu adapter 支持普通 episode URL。`discover_kakuyomu_work_catalog` 解析作品页 Next.js `__APOLLO_STATE__.Work.tableOfContentsV2`，按目录顺序发现 episode ID/title，验证唯一数等于 `Work.publicEpisodeCount` 后派生 URL；`scripts/run_kakuyomu_workflow.py --work-url` 可将发现、排他创建 catalog、逐话获取、版本归档、物化与确定性章节映射/现有流水线串联。chapter body request 在 checkpoint 记录目录后逐话发出；失败恢复只请求未完成话，已完成 raw 版本按 manifest 校验。逐次读取 robots 并 fail-closed；不登录、不跟随重定向、不访问 `/read`。请求间隔限制为 1.5–3 秒、默认 2 秒。页面可见正文归档为 UTF-8 文本，原始 HTML 不落盘；解析器 v4 保留段落边界、ruby、旁点 notation 与 U+3000。来源指纹绑定 parser/robots/目录/限额而非正文哈希；逐话内容由 manifest raw 哈希追溯，因此批次是滚动快照而非原子全书快照，目录未变的完整 checkpoint 也不会自动刷新正文。 | 用户已确认作品授权并要求普通页路径，且明确无需官方澄清；本次 live checkpoint 对主页声明的 88 话完成 88/88。它不包括草稿/私有话，不独立证明主页声明以外的完整性，也不代表平台背书或公开分发许可；Provider/Notion 边界独立适用。 | `tests.test_kakuyomu_page_source` 覆盖 synthetic 目录、计数拒绝、robots/URL、限速边界、重定向/限流、大小、标题、续传和格式标记；mock E2E 贯通主页到本地翻译。主页 count 与 88 话抓取结果一致；最终 manifest 的 267 个文件型 artifact 通过 SHA-256 验证。88 个 normalized 章节和有序全书 export 已生成，详细结果见[开发与验证](development.md#2026-11-15-kakuyomu-公开目录全量采集与-i3-导出)。 | 主页结构或 count 变化即停止；不请求 `/read`，不登录或绕过访问控制；滚动抓取可能跨时间，各话独立 hash/版本；不把主页声明范围外推为草稿/私有话或平台外完整性；限速和页面/章节/批次上限持续生效。 |
| I3 原始归档与规范化 Markdown | `部分实现`：`source_ingestion.py::materialize_episode_markdown` / `scripts/materialize_source_markdown.py` 按显式 work/episode ID 读取 manifest 选定的最新原始版本，校验哈希、UTF-8 和字节上限，按原字节创建不可变 `.md` 派生物并记录 raw parent。`materialize_episode_collection_markdown` / `scripts/merge_source_markdown.py` 支持显式递增位置 ID 集合，另支持 `--complete-checkpoint [PATH]`：要求 checkpoint v5 状态完整、发现/完成 ID 顺序一致、manifest 身份一致，且完成时绑定的每个 raw version 仍是 manifest 最新版本；两种方式均选择当前 normalized artifact，以 `\n\n` 分隔，记录所有 normalized 父版本并要求输出字节上限。checkpoint 是未签名、可编辑的 JSON；完整模式只校验当前所列 catalog 条目及版本绑定，不证明 checkpoint 未被改写或平台枚举穷尽；不执行格式清洗或差异映射。待实现平台目录完整性证据、站点格式转换、段落差异映射和 Notion 批量导入字段。 | I2 的来源标识及 v5 checkpoint；I1 版本清单；对应路线图阶段 1、3、5。真实站点接入另依赖 I0 平台访问规则。 | 合成 fixtures 验证单话字节保真、显式集合顺序/位置检查、完整 checkpoint 章节覆盖和 raw 版本新鲜度、父版本追溯、幂等、来源更新后追加 export 版本、缺章/旧 checkpoint/过期 raw/重复/乱序输入拒绝、输出上限及失败不写 manifest。完整验收仍需平台目录覆盖证据与样本格式规则；样本覆盖标题、前后记、作者话、插图/标记、空白和特殊符号；每段映射到原始版本；完整清单合并顺序一致。 | 把 checkpoint catalog 完整误称为平台全集会掩盖来源枚举缺项；把 pass-through 误称清洗会掩盖格式问题。未实现的变换不得自动删除内容，歧义保留原文并标记。 |
| I4 翻译与知识库接入 | `部分实现`：`CHAPTER_MAP` 支持可选 `source_version_id`，并要求 `SOURCE_MANIFEST_PATH` 相对 `RAW_DIR`；解析时验证版本存在、artifact 为 `normalized_source`、路径匹配且文件哈希有效。通用显式 catalog 由操作者给出映射；Kakuyomu workflow 可按主页发现的公开 episode ID/位置自动生成确定性译文路径和 TM 键，并绑定物化来源版本。流水线/章节对齐把版本 ID 写入 TM 来源索引，知识抽取来源清单记录版本 ID；TM 和知识草稿 provenance 均可只读核验所选版本、文本摘要及同一 `artifact_id` 在 manifest 中的最新 `normalized_source`，发现旧引用报告 `stale`，最新版本无法校验则报告 `invalid`。TM 审计分别核对 manifest 原始字节哈希与 TM 读取文本哈希，以支持字节保真的 CRLF Markdown。仍待持久化译文/知识过期状态及传播、全书预读预算/分批候选抽取、更多元数据及审核状态闭环。 | I2 发现目录、I3 来源标识与版本清单；现有翻译契约、D-01 知识审核责任和 D-02 Provider 授权；对应路线图阶段 1、2、3。 | 合成 fixtures 验证主页目录数量/唯一性/顺序与生成映射；来源版本映射、文件篡改/路径错配拒绝、TM/知识草稿审计状态、CRLF 哈希分离，以及流水线记录版本 ID。完整验收仍需每话来源 ID/原始版本/规范化版本/译文/TM 全链一致；预算超限时明确分批；未审核候选不能进入批准知识检索集合；未授权 Provider 请求被拒绝。 | 来源变化可能使译文或知识过期；只读审计可发现 TM 和知识草稿的旧来源引用，但不持久化或传播译文/知识过期状态。全书上下文超限、候选污染；强制预算检测、来源追踪、审核状态隔离。 |
| I5 EPUB 构建与验证 | `部分实现`：`epub_builder.py` / `scripts/build_epub_candidate.py` 提供显式有序 Markdown catalog 的离线候选构建；要求精确 Pandoc 版本，校验 source manifest 中逐话来源版本/身份/hash/新鲜度并记录 manifest hash，记录输入/输出哈希和参数；输出不可覆盖并做有限 ZIP/OPF/XHTML 结构检查。始终标记为 candidate，拒绝图片，未实现目录/字体/CSS 定制。 | 完整验收依赖 I3 格式结构、I4 译文版本/质量门禁、字体许可和目标阅读器设备；当前环境 Pandoc 3.9.0.2 可用但来源未核实，当前 PATH 未解析 EPUBCheck。对应路线图阶段 5 的本地交付子项。 | 合成 fixture 验证章节顺序、TOC/XHTML 存在、输入不变、来源版本对 manifest 绑定、manifest hash、精确版本、尺寸上限和不覆盖。完整验收还需 EPUBCheck、文本往返、特殊字符/排版及 Calibre、Apple Books、Thorium Reader 实测；candidate 标记不能作为完整性或质量批准。 | Pandoc 环境漂移、标题格式与图片缺失、阅读器渲染差异；固定 catalog 版本、限制为文本候选，并显式报告未覆盖验收。 |
| I6 Notion 备份试点与扩展 | 只读核实目标位置和权限；先用合成内容验证单向备份，再设计并验证双向编辑、冲突处理及删除传播；仅对获准项目小批量同步，交付完整性报告与恢复演练。 | I1–I4 稳定 ID/版本；Notion API 官方文档复核；保留义务、Notion 接收范围与具体数据类别核实；对应路线图阶段 5。 | 分页、限流、重试、幂等、双方版本保留、逐次确认反向删除及失败恢复均有测试；凭据不进日志；云端 ID、版本、哈希和数量与本地可核对；隔离目录恢复演练通过。 | API 变更、冲突和外发风险；先合成数据、单向试点，双向策略经验证后扩展，不静默覆盖。 |

### 验证方式与命令

工作包整体仍为`计划`；已实现子项按实际测试入口验证，未实现子项的命令是后续验证建议，不表示其功能或专项测试已经存在。运行现有测试只能验证已覆盖的代码。

- **I0**：记录用户对指定作品授权的明确确认；人工逐平台审查官方条款、自动化访问规则及接入方式，并记录 URL、访问日期、结论和责任人。没有能替代平台规则审查的代码测试命令。`git diff --check` 只检查文档补丁格式，不验证作品授权或平台许可。
- **I1**：当前原型入口为 `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest -q`；当前工作树 20 项合成测试通过，包含深层无环版本链及文件型 artifact 内容字节统计。使用 `.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <项目根目录> --manifest source_manifest.json` 可只读校验清单及其列出文件的字节哈希；清单路径和内容路径都限制在显式根目录内，源文件不被写入。`tests\run_tests.py` 默认启动模型 mock server 并运行 E2E，不是此单元测试的默认入口。版本状态流转、与流水线集成及授权/保留策略仍未实现。
- **I2 本地文件导入**：平台无关采集核心和 `LocalFileAdapter` 用 `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q` 验证。catalog schema v1 含 `schema_version`、`work_id`、`episodes`；每项包含 `episode_id`、`title`、`position`、`relative_path`，可选 `source_ref`；只读显式列出的根目录内文件且不修改源文件。默认 catalog 文件、单 episode 分别最多 16 MiB，episode 快照累计默认 1 GiB；可选 `--max-archive-bytes` 统计 manifest 中文件型 artifact 的历史版本内容字节，但不是物理磁盘配额。checkpoint v5 绑定来源/额度指纹、目标 manifest 和完成话的 raw 版本。详细输入限额与边界以[开发与验证](development.md)和当前实现/测试为准。本地 TXT 导入与下方 HTTP 页面 adapter 是两条独立路径；本段不再表示 Kakuyomu 页面采集尚未实现。
- **I2 输入边界**：本地空 `episodes` catalog 必须在创建 adapter 或任何输出前失败；JSON catalog 文件读取最多取配置上限 + 1 字节，超过后在解析/输出前拒绝；通用采集核心若截至终页仍未发现章节，不得报告 `complete`，complete checkpoint 至少包含一个已发现章节。空中间页可带 cursor 继续分页。单章/单批上限超出、快照后源文件增长均须失败；manifest/checkpoint 输入超限前置项不得发生章节写入。累计上限触发时不追加当前章节 metadata/raw 版本，checkpoint 标记 `archive_limit`；上限由同一 checkpoint 固定，改值需新 checkpoint。该额度只限制新增版本；若清单此前已经超限但本次仅复用既有版本，不会因没有新增而拒绝幂等重跑。`tests.test_source_ingestion` 与 `tests.test_local_source_ingestion_cli` 覆盖这些边界；当前定向运行结果和跳过原因以[开发与验证](development.md)的 2026-11-15 记录为准。
- **I2 Kakuyomu 目录发现与页面采集**：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -v` 使用本地 synthetic HTTP/HTML，不访问网络；运行 `.\.venv\Scripts\python.exe scripts\ingest_kakuyomu_pages.py --help` 与 `.\.venv\Scripts\python.exe scripts\run_kakuyomu_workflow.py --help` 核对 CLI。两个 CLI 都可接收 `--work-url https://kakuyomu.jp/works/<work>`；`ingest_kakuyomu_pages.py` 直接发现并归档全部公开话目，不依赖 Provider 配置，`run_kakuyomu_workflow.py` 另可继续物化、生成映射并调用翻译。解析器读取作品页唯一 `__NEXT_DATA__` script 中 Apollo state 的 `Work.tableOfContentsV2`，按分组顺序读取每个 `Episode` ID/title，再校验唯一性以及条目数与 `Work.publicEpisodeCount` 相等。通过后才生成普通 episode URL；不把首屏 `<a>` 链接数当完整目录。结构缺失/改变、count mismatch、重复 ID 或 robots 不允许时停止，不发 episode body 请求。发现结果保存为新建或内容完全相同的 `source_catalog.discovered.json`，不覆盖不同旧内容；章节正文在 checkpoint 记录目录后逐话请求并立即归档。source fingerprint 绑定 parser、robots、目录元数据与限额而非全书正文；逐话 raw artifact 哈希绑定实际获取的字节。暂停后从首个未完成话续传，测试确认不会重抓此前已完成话，并从已验证 raw 版本重建累计 128 MiB 预算。该工作流是跨时间滚动采集，不是同一时刻的原子全书快照；使用新 checkpoint 路径可主动重抓目录未变的作品，调整来源指纹中的限额/参数也需要新 checkpoint 路径。页面 HTML 默认 4 MiB、单话文本 16 MiB、所选文本累计 128 MiB、最多 1000 话，请求间隔限定为 1.5–3 秒、默认 2 秒；source-only discovered mode 默认使用独立 `source_checkpoint.discovered.json`。原始 HTML 不落盘；外网命令代理须按仓库 PowerShell 规则在同一命令调用中设置。2026-11-15 首次 live 主页探测确认 88 条唯一目录记录与 `publicEpisodeCount=88` 相符；之后 source-only 运行已从这些 URL 获取 88/88 话。最终 manifest 267 个文件型 artifact 均通过 SHA-256 核验；生成 88 个 normalized 单话 Markdown 与一份有序全书 export。Synthetic homepage-to-mock-translation E2E 不访问真实站点或 Provider。完整公开计数不包含草稿/私有话，也不独立证明平台声明外的作品完整性。
- **I3 当前基线**：`.\.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v` 验证单话字节保真、显式 collection 和完整 checkpoint catalog 导出。手工集合命令为 `.\.venv\Scripts\python.exe scripts\merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --episode-id <章节ID> --episode-id <下一章节ID> --max-bytes <必填输出上限>`；完整检查点模式为 `.\.venv\Scripts\python.exe scripts\merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --complete-checkpoint [<checkpoint路径>] --max-bytes <必填输出上限>`。省略检查点路径时默认读取 `source_checkpoint.json`。章节次序须符合来源位置，输出在章节间插入两个 LF 字节且大小限制包含分隔符。检查点模式要求 v5 检查点完整、逐话 raw 版本绑定与当前 manifest 匹配；CLI 报告 `coverage_scope=complete_checkpoint_catalog` 和 source fingerprint。checkpoint 未签名且可编辑；模式只校验当前记录的 catalog 条目，不证明 checkpoint 未被改写或平台枚举穷尽，也不负责 Kakuyomu 的首页 URL 发现、清洗、差异映射或完整 pipeline 集成；Kakuyomu workflow 已单独提供发现与流水线接入。单话 CLI `scripts/materialize_source_markdown.py` 仍默认每话上限 16 MiB，可用 `--max-bytes` 调整。完整 I3 还需来源完整性证据、真实样本转换规则/差异映射；`tests\run_tests.py` 本身不会验证真实站点或章节格式。
- **I4 来源版本绑定与新鲜度审计子项**：`.\.venv\Scripts\python.exe -m unittest tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_tm_provenance_unit -v` 验证 TM 与知识草稿 provenance 的显式版本关联、当前/过期/损坏/缺失版本状态，以及 CRLF 字节保真样本。`SOURCE_MANIFEST_PATH` 相对 `RAW_DIR`；比较依据是 manifest 中同一 `artifact_id` 的最新 `normalized_source`。Kakuyomu 工作流可从发现的完整公开目录生成确定性 `CHAPTER_MAP`；其他通用来源仍须操作者指定映射。`tests\run_tests.py` 不直接调用两个审计 CLI；审计状态由定向单测覆盖。I4 仍不写入译文/知识的持久过期状态，也不覆盖全书预算、审核隔离或真实章节。
- **I4 知识抽取输入边界**：`scripts/auto_extract_knowledge.py` 按 `PROOFREAD_MODEL` 通过共享模型路由选择 Provider ID、URL 与 Key，在读章节前核验 `source_text` 授权，客户端创建时复检；未知模型、缺少远端 Key 或未授权时不读取来源。最多读取前三个所选章节，每章 16 MiB 有界读取，超限在创建客户端前拒绝，CLI 不回显文件路径或异常正文。样本文本最多 20,000 个 Unicode 字符，但这不是 tokenizer 计数或全书 context 预算；没有全书抽取预算和超限分批能力。最新路由增量验证见[开发验证记录](development.md#2026-11-15-知识抽取-provider-路由对齐)；更早 15 项抽取测试和 13 模块整组结果仍是历史检查点。
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

## 维护规则

- 逐平台、逐目的保留官方资料来源、访问日期、结论、许可边界和复核人；规则变化时重新审查。
- 方案阶段、真实实现状态和验收证据分开记录。实现完成前只可标记为`计划`；mock/合成测试只能证明本地契约。
- 工作包完成后更新[路线图](roadmap.md)，实际代码行为更新[项目现状](project-status.md)/[架构与边界](architecture.md)，知识状态更新[知识库治理](knowledge-governance.md)，人类决定更新[决策记录](decisions/README.md)。
