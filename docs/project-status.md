# 项目现状

> 状态基准：2026-11-15，代码基线为分支 `codex/translation-workflow-20261115` 的 `c3f313b`；当前工作树包含本任务之前的未提交修改及本任务增量，保留边界见[当前交接](handoffs/2026-11-15-translation-workflow.md)。Kakuyomu source-only 采集已完成主页声明的 88/88 话；88 个单话 Markdown 与有序全书 export 均从 manifest 版本物化。当前 manifest 267 个 artifact 文件校验通过；本次未调用真实 Provider/Notion。实际正文/标点/ruby 仍待人工格式验收，88/88 不包含草稿/私有话，也不等于平台背书或公开分发许可。
> 引用会话范围：本次续接已分页读取两个引用会话至 `hasMore=false`；会话仅作目标/决策线索，当前能力以工作树、测试及文档记录为准。

> 2026-11-15 本次复核：分支 `codex/translation-workflow-20261115`、HEAD `c3f313b`；工作区包含此前的未提交修改和本任务增量，具体以 `git status --short --branch` 为准。两个引用会话已分页读取至 `hasMore=false`，并以当前源码交叉核对。URL adapter 增量后的相关回归和 mock E2E 见[开发与验证](development.md#2026-11-15-当前-checkout-回归验证)；来源到版本化 mock 翻译端到端路径见同日端到端记录。

> 来源接入表述说明：Kakuyomu 主页 adapter 从 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 发现公开 episode ID/title，要求唯一条目数等于 `publicEpisodeCount`，随后生成 URL。`scripts/run_kakuyomu_workflow.py --work-url` 可保存发现 catalog、获取目录中全部公开 episode 页面、生成带来源版本的确定性 `CHAPTER_MAP` 并运行生产流水线；synthetic mock E2E 已验证该链路。它不发现/获取草稿或私有话，不证明站点声明外的完整性，也不代表真实 Provider 翻译或全书真实站点 E2E。

> 用户最新决定：试点书籍已获得明确授权；用户是普通读者，要求采集系统从作品主页发现完整公开目录，再通过普通 episode URL 逐话获取原文，不依赖作者 ZIP，并明确表示不需要官方澄清。`KakuyomuPageAdapter` 已实现目录发现与显式 URL catalog 采集并运行时遵守 robots；不登录、不跟随重定向、不请求 `/read`。2026-11-15 live 采集已发现并获取主页声明的 88/88 话，checkpoint 为 complete；parser v4 将 ruby 和旁点转换为明确文本标记并保留 U+3000。88 个单话 Markdown、全书 export 与全部来源 artifact 均通过 manifest 哈希检查。该用户决定不代表平台背书/法律结论；完整性仅限本次主页公开目录，不含草稿/私有话，也不包含公开分发授权。人工格式验收、真实 Provider 调用、Notion 操作仍未完成。用户已授权 JOJO/JYQF 接收各自职责所需的最小数据类别；运行时 allowlist、端点/数据流与渠道兼容性仍未验证。

> 2026-11-15 平台规则观察与用户决定：robots 允许普通 work/episode URL，禁止相应 `/read`；普通 HTML anchor 只有 7/88 条目，完整目录解析读取 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2`。此前查阅的服务条款中有关于分析站点/应用结构的限制；该规则作为风险背景保留，不作法律结论。用户明确表示无需官方澄清并要求按普通 URL 路径继续，因此官方答复不设为本试点前置条件；实际采集已完成 88/88。此记录不称为平台背书或公开分发授权；仍遵守 robots，不访问 `/read`，不登录或绕过访问控制。

## 已实现

- `pipeline.py`：Python CLI；按章节读取 Markdown，构建上下文，依次执行上下文标注、初译、校对、润色，并写入译文和翻译记忆。
- `已实现` 响应契约：标注对象与源段落保真校验；初译必需字段/段落数组检查；校对 schema 不合格时保留上一版；反思重译和润色响应异常时回退；三种生产提示词的输出字段与调用端 schema 对齐。
- `部分实现` Provider 路由与数据类别预检：`get_primary_provider_route` 集中管理 Sakura/Qwen、DeepSeek，以及显式 JOJO (`gpt-6-luna*`) / JYQF (`deepseek-v4.1-flash`) 别名；通用 `deepseek-flash` 仍走 DeepSeek。未知模型名会在流水线读取章节及创建客户端前拒绝。标注/初译仅声明 `source_text`、`book_knowledge`，校对/润色声明三类全集；启用严格反思时初译模型也须获准三类。启动预检和显式 Gemini 回退预检使用相同阶段矩阵。用户已授权 JOJO/JYQF 各自职责所需最小类别；allowlist 默认拒绝，需本地显式配置。端点、模型 ID、当前凭据和协议兼容性仍未验证；通用 Provider 抽象、自动 JOJO→JYQF 回退、`CODING_PLAN_*` 支持和真实端点验收仍未实现。
- `rag_engine.py`：翻译记忆向量检索、术语匹配、分章指导检索及记忆写入。
- `scripts/align_chapters.py`：双语章节段落对齐、对齐结果向量化并写入翻译记忆。
- `scripts/validate_tm_provenance.py`：只读核对 TM 来源索引的文件哈希、段落引用和词对内容；配置 manifest 时还可检测同一来源 artifact 的更新版本。不修改 TM，也不判断译文质量或审核状态。
- `scripts/validate_knowledge_provenance.py`：只读核对知识候选 provenance 的来源文本哈希、版本关联及 manifest 中的最新来源；不修改或批准知识草稿。
- `scripts/apply_story_summary_review.py` 与 `story_summary_review.py`：生成哈希绑定的概要审核模板、发布明确批准的 JSON bundle，并在翻译流水线加载时复核 bundle 与 provenance 来源版本新鲜度。旧 Markdown 概要仍可加载但未经此审核门禁；回执未签名/审核者身份未认证。
- `scripts/auto_extract_knowledge.py`：读取章节正文前依据 `Config.PROOFREAD_MODEL` 通过 `get_primary_provider_route` 解析 Provider、URL 和专属 Key，再检查该 Provider 的 `source_text` 外发授权；创建客户端时再次检查。未知模型名在读取章节前拒绝。最多读取前三章，每个所选文件最多 16 MiB，超限在创建客户端前拒绝，提示词样本另截到 20,000 个 Unicode 字符。响应会先做结构、必填字段和冲突译名校验，草稿采用排他新建。来源清单记录实际输入范围/哈希及可精确匹配术语的章节段落序号，并最后写入 `artifact_status: complete` 标记；写入失败可能遗留部分文件，缺少有效标记时不得视为完整候选。流水线与 RAG 现在按约定文件名拒绝直接加载 `Glossary_draft.json` / `STORY_SUMMARY_draft.md`；这不防重命名，也不构成审核状态或发布流程。全书 token 预算与分批抽取尚未实现。
- `scripts/apply_knowledge_review.py`：可为当前 glossary/provenance 候选排他新建绑定原始字节 SHA-256 的未完成审核回执模板（所有决定均为 `pending`，不可发布），也可消费完整回执，校验候选哈希、provenance 来源新鲜度和术语段落命中，仅将明确批准项写入新的 reviewed glossary bundle；模板模式不读章节或 manifest，也不调用审核 Provider，任何模式均不覆盖既有文件。回执 reviewer 字段未签名、未认证，是调用者声明；RAG 加载 bundle 时会再校验 manifest 来源新鲜度，且必须显式配置 `GLOSSARY_PATH`。
- `prompts/`：初译、逻辑校对和文风润色提示词。
- `tests/`：标准库 `unittest` 测试、独立 mock HTTP 服务、RAG/对齐/路径安全测试。
- `projects/example/`：小型示例原文、译文和书籍知识样例；不代表实际运行产物或真实书籍数据。

## 部分实现与差距

- `部分实现` 多 Agent：当前由单进程按阶段调用多个模型端点；未发现独立 Agent 运行时、队列、调度器、持久化任务状态或用户交互界面。
- `部分实现` 翻译记忆：使用 JSON 文件和嵌入向量并自动写入；新的流水线/对齐写入附带可选 `source_provenance`，记录源文/译文哈希和段落映射，可用只读脚本核验文件和词对是否仍匹配。历史条目不自动补录；审核、版本和冲突治理仍未实现。逐章恢复日志可在进程中断后校验输出与 TM 基线并恢复本章提交；日志冲突时保留待处理状态，不覆盖内容。日志明文保存在输出目录，单条上限 64 MiB；不保证多进程并发或断电持久性。
- `部分实现` 章节格式保护：已验证本地响应 schema、非空文本/段落数及引号字符序列检查；格式门禁失败不写译文或 TM。其他格式需依据获准样本进一步定义，术语和语义质量仍未成为统一硬门禁。
- `部分实现` 章节发现：未配置 `CHAPTER_MAP` 时，流水线与对齐器只扫描配置目录第一层，暂不递归；项目名模式遇到 `生肉/` 或 `熟肉/` 子目录会拒绝自动选择首项，要求显式配置路径。空扫描会失败，对齐器在没有任何可处理译文时也会以非零状态退出，不会把空运行报告为成功或保存 TM。多卷映射的通用契约已实现；真实章节和输出映射仍需核验。
- `部分实现` 显式多卷映射契约：JSON `CHAPTER_MAP` 按用户给出的顺序记录 `raw_file`、`translation_file`、`tm_key`，并可选记录 `source_version_id`；版本 ID 要求 `SOURCE_MANIFEST_PATH` 并验证 manifest artifact 类型、相对路径及字节 SHA-256。流水线、对齐器、知识抽取和 TM 来源审计共用映射；TM/知识来源记录保留版本 ID。旧三字段映射保持兼容，拒绝路径穿越、符号链接、重复路径/键及缺失源文件。用户已决定缺译文作为新任务、同名旧译文先归档后人工判定；真实书籍映射条目和章节对应仍未核定，未在忽略项目中启用。
- `部分实现` API 容错：Gemini 故障转移默认关闭；显式开启后仅连接/超时、HTTP 408/429 和 5xx 触发回退。鉴权/请求错误、响应 schema 错误及内容拦截不回退；通用 Provider 抽象、逐阶段错误策略和真实端点验证未完成。
- `部分实现` 运行日志隐私：校对严重意见不再输出；RAG embedding 失败日志、知识抽取和章节对齐 CLI 的已处理错误不输出异常正文；TM 来源审计 CLI 会转义不可打印字符，且拒绝空白 `TEST_WORKSPACE_DIR`。第三方 SDK、测试 runner 和其他外围工具仍可能产生自己的诊断输出，未做全局日志脱敏保证。
- `部分实现` 路径边界：章节映射路径拒绝绝对路径、路径穿越和符号链接，译文/草稿采用排他新建，TM 采用原子替换；显式配置根目录仍由操作者负责，平台级并发链接竞态未完全封闭。
- `部分实现` 配置：支持环境变量、项目目录及 JSON 配置路径；`API_TIMEOUT` 默认 10 秒并拒绝非有限或非正数，覆盖 OpenAI-compatible 聊天、Gemini 生成、RAG 和章节对齐 embedding；远端数据按 `PROVIDER_DATA_POLICY` 最小类别授权，默认拒绝。有基础 `requirements.txt`，但依赖未锁定，也没有完整部署配置。
- `部分实现` 来源版本清单：`source_manifest.py` 提供本地 JSON schema v1、版本追加、SHA-256/相对路径语法和父版本图校验；图校验使用迭代算法，不受 Python 调用栈深度限制。`verify_manifest_files` 可验证清单列出的文件；`verify_manifest_artifact` 只校验指定版本。`scripts/validate_source_manifest.py` 提供只读 CLI。`source_ingestion.py::materialize_episode_markdown` 与 `scripts/materialize_source_markdown.py` 可将显式指定的 raw artifact 校验为 UTF-8 后，按原字节派生 `.md` 并记录其父版本；这是无格式转换的 I3 基线，不等于完整规范化、差异映射或站点适配。
- `部分实现` 来源接入：`source_ingestion.py` 提供 `SourceAdapter`、显式路径 `LocalFileAdapter`、checkpoint v5 与版本化归档；`scripts/ingest_local_sources.py` 只读 catalog 指定文件。显式本地导入默认限制 JSON catalog 16 MiB、单 episode 16 MiB、单批 1 GiB，可分别调整；可选 `--max-archive-bytes` 限制清单登记 artifact 历史版本累计内容字节，但不构成物理磁盘配额。`kakuyomu_page_source.py::discover_kakuyomu_work_catalog` 从普通作品主页解析 Next.js Apollo 目录；唯一 Episode ID 数必须等于 `publicEpisodeCount` 才产出公开 URL 清单。`KakuyomuPageAdapter`/`scripts/ingest_kakuyomu_pages.py` 对显式 catalog URL 及发现 URL 运行时检查 robots，不使用 cookie/login、不跟随重定向、不请求 `/read`。`scripts/run_kakuyomu_workflow.py --work-url` 在 Provider 授权/凭据预检、发现目录与译文冲突检查后，保存 discovered catalog，逐话请求正文并即时归档/物化版本，生成 episode ID/位置确定的 `CHAPTER_MAP`/TM 键并运行现有翻译流水线。checkpoint 保存每话完成时的 raw version；暂停后只重抓未完成话，并从 manifest 核验已完成原文用于继续累计 128 MiB 上限。来源指纹绑定 parser、robots、目录与限额，不绑定正文哈希；各话正文哈希单独保存在 raw artifact，因此续传是跨时间滚动快照，不是同一时刻的原子全书快照，完整 checkpoint 也不会自动刷新正文，刷新需新 checkpoint 路径。默认单页面 HTML 4 MiB、单 episode 提取文本 16 MiB、单次文本累计 128 MiB、最多 1000 话，请求间隔限定为 1.5–3 秒、默认 2 秒。页面结构变化、目录数不符或章节正文标题不符均失败关闭；parser v4 保留 ruby/旁点关系标记和 U+3000。用户不要求官方澄清并要求按普通 URL 路径继续；live source-only 采集已完成主页声明的 88/88 话，不调用 Provider。当前不涵盖草稿/私有话、站点计数以外的完整性证明、真实 Provider 翻译及正文人工格式/标点/ruby 验收。
- `已实现` 来源采集空输入保护：2026-11-15 修复 `source_ingestion.py` 对零章节终端结果仍可报告完成的问题；空终页在未发现章节前会失败，complete checkpoint 必须至少包含一个已发现章节。空中间页仍可继续分页。本地 `scripts/ingest_local_sources.py` 还会在创建 adapter 或输出前拒绝空 `episodes` catalog；核心和 CLI 回归测试覆盖这些边界。
- `部分实现` I3 Markdown 物化与章节导出：按显式 ID 校验 manifest 关联的 raw 版本哈希、UTF-8 和上限后，可字节保真生成不可变单话 `.md`；试点现有 88 个目录话目均已有 normalized artifact，且按完整 checkpoint v5 导出一份 88 话有序 Markdown。集合模式可显式选择递增位置的 episode ID，也可按完整 checkpoint 当前记录的 discovered/completed ID 和 raw 版本绑定选择章节，并核对 raw 版本仍与 manifest 当前版本相符。导出以 `\n\n` 分隔，要求输出字节上限，并把所有 normalized 版本作为父节点。checkpoint 未签名且可编辑；模式只验证当前所列集合，不证明记录未经改写或平台目录枚举穷尽。仍不做语义清洗、段落差异映射或真实章节人工验收。
- `部分实现` I4 来源版本衔接：人工映射可把 `source_version_id` 绑定到 manifest 中 `.md` artifact。流水线与对齐写入 TM 来源版本，知识候选清单记录版本；TM 与知识候选均有只读审计，可比对同一 artifact 的最新 `normalized_source`，报告旧版本 `stale` 或损坏的最新版本 `invalid`。TM 审计分开验证 manifest 原始字节哈希和文本读取哈希。审计不写回 TM/知识、不自动生成映射，也不持久化/传播译文或知识的过期状态；没有真实章节验收。
- `部分实现` I5 EPUB 候选构建：离线 builder 可消费显式排序的 Markdown catalog，要求 Pandoc 版本精确匹配且不覆盖既有输出；构建前对每个 `source_version_id` 校验来源 manifest 的文件哈希、work/episode identity 与最新版本，并在 sidecar 记录 manifest 路径/hash。只处理文本 Markdown、拒绝图片；candidate 和有限 ZIP/OPF/XHTML 检查不是完整 EPUBCheck，也不证明质量、完整选集或阅读器兼容。试点已生成 88 个原文 Markdown，但译文目录仍为空，因此没有真实译文 EPUB 输入。

## 计划

- `部分实现` 术语和概要已有本地回执校验与 approved-only bundle，TM 有可显式配置的审核快照；人物设定的完整治理、审核者身份与审核质量、风险分层、升级/更正/废弃及默认强制 TM 检索门禁仍待实现。
- `计划` 明确各阶段输入/输出契约、最终质量门禁和可复现验收。
- `计划` 评估扩展到多语言和多文本类型；当前实现聚焦日译中轻小说，不可据长期方向宣称已支持通用翻译。

## 未知与待验证

- `未知` Sakura 服务实际部署位置、模型权重/版本和运行参数。代码默认 URL 为 `http://127.0.0.1:6006/v1`；2026-11-14 本次 `Test-NetConnection` 复核该端口不可达，其他地址未探测。
- `未验证` 用户要求将疑似旧凭据按已轮换处理；当前凭据、供应商侧审计、账户权限、配额、API 兼容性和真实端到端翻译质量。本项目未访问供应商控制台或调用外部 API。
- `未知` 除当前工作区外是否存在云端部署、自动化任务或用户界面；仓库未找到相关部署清单或 CI 工作流。
- `未知` 当前可用章节映射：2026-11-14 曾在被 `.gitignore` 排除的 `projects/祝福のネトラレラ` 观察到 48 个原文 Markdown、19 个译文 Markdown、19 个 TM 章节键及未索引来源；这是历史库存快照。2026-11-15 初始只读复核时，用户指定的原文/译文根目录及仓库忽略项目下的 `生肉/`、`熟肉/` 均为空。之后第一话已从用户提供的普通 URL 导入：原文根目录现在含 metadata、raw、normalized artifact 及 catalog/checkpoint/manifest；刚复核的 manifest 有 3 个文件型 artifact 且全部通过哈希验证。译文根目录和仓库忽略项目下的章节目录仍为空；7 个 EPUB 工具/配置文件位于旁边的 `projects/祝福のネトラレラ/EPUB/`，不是书籍译文。没有足够信息确定真实 `CHAPTER_MAP` 的输出路径与 TM 键；本记录未读取正文。历史 48/19/19 统计不能作为当前可用输入。指定作品已由用户于 2026-11-14、2026-11-15 明确确认为获得授权；平台访问与 Provider/Notion 接收范围仍分别处理。
- `未知` `TEST_READY.md` 中历史“71”计数与当前测试的对应关系；最近一次测试报告按实际 unittest 方法和命令记录，不沿用该计数。
- `未知` 不同操作系统对无符号链接打开标志和目录并发修改的实际保证；最近一次回归测试状态见[开发与验证](development.md)。

## 历史需求差异

- `ORIGINAL_REQUEST.md`（2026-06-08）要求 Provider 内容拦截后将请求转发到 Gemini 并设置 `BLOCK_NONE`；当前代码和测试将 Provider 内容拦截视为终止状态。本次自检保留该终止边界并移除了显式放宽的安全设置。
- 原始需求列出 `text-embedding-004`，当前代码请求 `gemini-embedding-2`。2026-11-13 的历史复核未能访问真实 Gemini 端点，模型 ID 与向量兼容性均待确认。
- `.agents/` 中的旧计划、handoff 和测试结论来自不同工作阶段，含旧路径和过期“71 项”状态，只作历史记录，不作为当前运行、部署或验收证据。

## 历史验证与本次证据边界

2026-11-15 文档复核只检查 Git 工作区与源码；`git diff --stat a71e8ee d7e2afd -- '*.py' requirements.txt` 无差异，说明下述 `a71e8ee` 验证涉及的 Python 源码和依赖清单与本次基线一致，但不是在 `d7e2afd` 上重新执行测试，也不覆盖环境变化。

2026-11-14 最新代码验证：代码提交 `a71e8ee149f7d20858e8334d8456ade74c7fa7e7` 的来源/本地 CLI 两模块 28 项通过；连同路径安全模块共运行 39 项，35 项通过、4 项跳过。普通权限下 3 个符号链接用例因 `[WinError 1314]` 跳过、FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过；管理员 PowerShell 对同一代码提交运行路径安全模块 11 项，10 项通过、仅 FIFO 用例跳过，符号链接用例均通过。`compileall` 与 `git diff --check` 通过。用户提供的 `Ran 9 tests ... OK (skipped=3)` 没有 SHA 或逐项跳过信息，作为独立证据保留；该计数与旧版 9 用例模块相符，不替代当前 11 用例版本的管理员运行。验证只使用本地合成数据，不覆盖真实 Provider、站点或部署。更早的十模块 174 项与 mock E2E 4 项结果属于 `e5c3154` 基线工作树，不能替代当前代码提交验证。

历史 GitHub 状态快照（2026-11-14 15:50 UTC，非当前 PR 状态）：PR #57 当时为 open，head 为 `5ada9462244375010c38a16a9198edd9c2fc76f5`，检查列表为空；读取分支保护设置返回 403。该快照不说明此后 PR 是否合并或检查是否变化；当时本地 `main` 为 `d7e2afd`。Codex Security Standard 报告仅针对 `e5c3154`，覆盖为 partial，不覆盖本次基线。历史审查细节见[开发与验证](development.md)、[安全记录](security-notes.md)及[续接交接](handoffs/2026-11-14-translation-workflow.md)。

2026-11-15 补充验证：在 HEAD `5ada9462244375010c38a16a9198edd9c2fc76f5` 普通权限运行路径安全模块，11 项中 7 项通过、4 项跳过、0 项失败；`-v` 输出明确显示 3 个符号链接用例因 `[WinError 1314]` 跳过、FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。该提交仅包含 Markdown 更新，相关测试/实现代码与 `a71e8ee` 相同。管理员 PowerShell 在 `a71e8ee` 上的 11 项结果为 10 项通过、仅 FIFO 跳过；因此三个符号链接行为已有管理员运行覆盖，但未在 `5ada946` 这一文档提交上再次提权运行。

2026-11-15 当前工作区续接验证：代码基线为本地 `main` HEAD `d7e2afd`。I2 对空 catalog/零章节终页 fail-closed，并为本地 catalog/章节输入增加有界读取；本轮后续新增可选 `--max-archive-bytes`，按 manifest 所有文件型 artifact 历史版本的内容字节和预检每话新增项，额度绑定 checkpoint，无默认值。该限制不是物理磁盘配额，不覆盖未登记文件、清单/断点文件及其他写入工具。I3 可校验原始 manifest artifact 并按原 UTF-8 字节物化 `.md`，但尚无格式转换。I4 新增可选 `CHAPTER_MAP.source_version_id` 到 `normalized_source` manifest artifact 的显式绑定，贯通翻译、对齐、知识来源记录和 TM/知识候选只读审计；两种审计均可比较同一 artifact 的最新版本并报告旧引用 `stale`、最新 artifact 校验失败 `invalid`。TM 审计分别验证 manifest 原始字节哈希和 TM 读取文本哈希，避免 CRLF 字节/文本摘要混淆；旧映射保持兼容。D-11 后续新增 `chapter_transaction.py` 逐章恢复日志，重跑时核验当前映射、源文/译文、输出和 TM 基线后恢复；冲突停止且保留日志。它不提供多进程锁、断电持久性或自动冲突合并；详见[开发验证记录](development.md#2026-11-15-d-11-逐章恢复日志)。

2026-11-15 I2 清单内容累计上限增量：定向 `source_manifest`、`source_ingestion`、本地 CLI 三模块 60 项通过；加入来源链接、知识/TM 来源、翻译契约和路径安全模块后，12 个模块共 212 项运行、208 项通过、4 项跳过、0 项失败。涉及 Python 文件 `py_compile`、CLI `--help`、`git diff --check` 和 13 份活动 Markdown 的 75 个本地文件链接检查通过。未重跑完整 mock E2E。额度超限时当前 episode 不追加 metadata/raw artifact，checkpoint 暂停；改变额度需新 checkpoint 路径。物理磁盘配额及未来 HTTP adapter 的流式响应限制仍待设计。

2026-11-15 I0/I3 续接历史检查点：当时复核 Kakuyomu 官方规约第 5、12–14 条和 `robots.txt`，并未访问作品/章节页面；随后用户明确要求普通读者路径直接读取指定 episode URL，第一话已在下方更新记录的 I2 增量中导入。I3 增加显式章节集合 Markdown 导出及完整检查点目录模式：checkpoint v5 记录每话完成时的 raw 版本，导出核对当前 JSON 记录的发现集/完成集、manifest 绑定和 raw 版本新鲜度。checkpoint 未签名且可编辑；该校验不能证明记录未经改写或来源平台目录穷尽，也不执行格式清洗。初始时原文/译文目录为空；当前第一话 raw 来源已归档，译文目录仍为空。

2026-11-15 I3 集合导出验证更新：11 项 `tests.test_source_markdown_materialization` 通过；加入其他 11 个相关测试模块后，12 模块共运行 219 项、215 项通过、4 项因 Windows 符号链接/FIFO 支持跳过、0 项失败。`py_compile`、合并 CLI `--help`、README/`docs/` 13 个活动 Markdown 的 75 个本地文件链接、9 个本地标题锚点和 `git diff --check` 通过。未重跑 mock E2E；集合导出尚未接入翻译流水线。

2026-11-15 I3 checkpoint v5 增量：12 个相关单测模块运行 224 项、220 项通过、4 项因 3 个 Windows 符号链接创建权限限制和 1 个 FIFO 不支持而跳过、0 项失败；Python 编译、`scripts/merge_source_markdown.py --help`、`git diff --check` 通过。完整 mock E2E 未重跑。验证含完整 catalog 导出、缺失完成项/旧 raw 版本/已完成 v4 checkpoint 拒绝；没有真实作品内容或平台/Provider/Notion 调用。导出只校验当前 checkpoint 所记录 catalog 条目及其 raw 版本，不证明 checkpoint 未被改写或上游枚举穷尽。

2026-11-15 I2-I4 本地 catalog 合成联测增量：原测试从两个虚构本地章节贯通 catalog 导入、normalized 物化、完整 checkpoint 导出和生产章节映射来源版本读取。后续新增 `tests.test_e2e.E2ETestSuite.test_local_source_archive_flows_through_versioned_mock_translation`，另以一个合成 UTF-8 TXT 贯通显式 catalog 导入、normalized 物化、带来源版本的 `CHAPTER_MAP`、本地 mock 四阶段翻译和 TM provenance。当前相关 17 模块运行 286 项、282 项通过、4 项因 Windows 能力跳过、0 项失败；完整 mock E2E 5 个测试方法通过，231.163 秒。两组均未调用真实平台/Provider/Notion或读取书籍正文，不代表平台目录完整、真实章节格式合格或真实翻译质量。

2026-11-15 阶段 2 知识草稿输入保护增量：新增启动期文件名门禁，直接阻止 `Glossary_draft.json` 进入 RAG，或 `Glossary_draft.json`/`STORY_SUMMARY_draft.md` 作为翻译正式输入；精确针对生成器固定文件名，不检测重命名文件，不能替代候选/批准 schema。12 个相关模块运行 227 项、223 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败；4 项本地 mock E2E 于本增量后通过。未调用真实 Provider/Notion，未读取作品正文。

2026-11-15 阶段 2 术语审核回执发布增量：新增 `scripts/apply_knowledge_review.py`，用本地 schema v1 回执将按原始字节哈希绑定的候选术语表和来源清单核对后，发布仅含 `approved` 项的新 bundle；发布前重新审计 manifest 版本、源文本/样本摘要及术语段落位置，RAG 加载 bundle 时再次核验来源新鲜度。13 个相关单测模块 236 项运行、232 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败；审核/来源/RAG/流水线/抽取定向集合 106 项通过；完整本地 mock E2E 4 项通过（237.034 秒）。回执不签名、不认证审核者字段，也不证明模型实际审阅或语义正确；需显式配置 `GLOSSARY_PATH` 才使用 reviewed bundle。未调用 Provider/Notion/站点，未读取作品正文。

2026-11-15 阶段 2 审核回执模板增量：新增 `--create-template` 模式，为当前候选术语表及来源 provenance 生成排他新建、SHA-256 绑定的未完成回执；模板决定为 `pending`，不能直接发布，且不读取章节或 manifest。13 个相关单测模块 239 项运行、235 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败；完整 mock E2E 未在此 CLI 增量后重跑，最近一次结果见上一条。当前没有调用 Provider/Notion/站点或读取作品正文。指定试点作品已由用户明确确认获得授权，不列为阻塞；平台自动化访问规则和 Provider/Notion 接收方范围分别处理。

此前 I2 累计内容上限实现前：`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：208 项运行、204 项通过、4 项跳过、0 项失败。3 项符号链接用例因 `WinError 1314` 跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。随后 `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，231.440 秒，runner 退出码 0；runner 验证当时的 mock 流水线成功路径，不单独调用 I4 审计 CLI 或模拟 TM 磁盘写失败。真实章节目录当前为空，未调用真实 Provider、站点、Notion 或访问作品正文；E2E 的负向 fixture 日志不代表真实服务调用。I3 仍待样本驱动的格式规则/差异映射和合并；I4 仍无持久化/传播译文及知识过期状态。D-11 在该验证检查点尚无跨文件日志，后续实现和最新测试见上文。此前 1 GiB 是单次本地导入上限；当前可选清单内容预算及其物理磁盘配额边界见上方 2026-11-15 增量记录。

2026-11-15 D-11 验证检查点：13 个相关单测模块 244 项运行、240 项通过、4 项跳过、0 项失败；完整 mock E2E 在 D-11 生产代码变更后 4 项通过（232.043 秒）。当时 E2E 之后只增加了测试用例；后续知识抽取资源限制变更后的单测结果见下方最新增量。`py_compile` 覆盖 `chapter_transaction.py`、`pipeline.py`、`rag_engine.py` 和两份测试文件，通过。跳过原因为 3 个 Windows 符号链接权限限制与 1 个 FIFO fixture 不支持。测试只用本地合成数据。

2026-11-15 阶段 2 知识抽取授权预检与输入限制：共享 `resolve_openai_client_settings` 统一检查 OpenAI-compatible URL、Provider 数据类别授权和远端 API key；知识抽取在读取章节正文前预检，创建客户端时再次检查。未获 `source_text` 授权或缺少远端 key 时均验证为不读取章节、不创建客户端。每个最多前三个所选章节仍限制读取 16 MiB，保留 UTF-8 文本解码、通用换行归一化和 20,000 字符提示词截断。抽取单测 15 项、流水线契约 66 项通过；最新 13 模块回归 249 项运行、245 项通过、4 项跳过、0 项失败；共享客户端增量后的本地 mock E2E 4 项通过（227.106 秒）。跳过原因为 3 项 Windows `WinError 1314` 符号链接权限限制和 1 项 Windows FIFO 不支持。相关 `py_compile` 与 `git diff --check` 通过。全书 token/context 预算和分批抽取未实现；未调用真实 Provider/Notion/站点或读取作品正文。
2026-11-15 阶段 2 概要审核：新增本地回执模板和 approved-only JSON bundle。发布时绑定概要/provenance 候选字节哈希，并要求来源版本与 manifest 最新 normalized artifact 一致；翻译流水线在加载项目信息和 RAG 前重验 bundle 状态、概要/provenance 摘要与当前来源版本。旧 Markdown 概要兼容路径未审核，回执不签名且 reviewer 身份只是声明。定向、全回归、mock E2E 与剩余限制详见[开发与验证](development.md#2026-11-15-阶段-2-概要审核与运行时来源核验)。指定试点书籍权利已由用户明确确认；平台自动访问、Provider 与 Notion 范围仍分开处理。

2026-11-15 阶段 2 TM 审核快照：新增逐原译对回执模板和只含批准项的来源核验快照。RAG 只有在显式设置 `TM_REVIEWED_PATH` 时才使用快照；完整可写 TM 仍是运行时写入目标，未配置时维持旧检索行为。JSON 配置/环境变量覆盖顺序已由测试验证。15 个相关模块回归 270 项运行、266 项通过、4 项跳过，mock E2E 4 项通过（204.831 秒）；reviewer 字段未认证、未调用 Provider。完整限制及复现命令见[开发与验证](development.md#2026-11-15-tm-审核回执与显式检索快照)。指定作品已由用户确认获得授权；平台自动访问与 Provider/Notion 接收方数据范围仍独立核定。

以下为各自提交基线下的历史验证记录，不表示当前工作树的验证结果：

2026-11-14 PR 复审修复后，六模块定向单测 133 项运行、130 项通过、3 项因 Windows 符号链接权限跳过、0 项失败；mock E2E 4 项通过（221.997 秒）；Python 编译和 `git diff --check` 通过。覆盖段落来源映射、多卷章节号、可选阶段解析回退、TM 畸形结构分类和测试 API key 隔离；均使用合成数据。细节见[开发与验证](development.md)。

2026-11-14 显式映射改动的 116 项定向单测运行、113 项通过、3 项因 Windows 符号链接权限跳过、0 项失败；知识抽取来源键定向测试 9 项通过；Provider 路由/URL 校验定向测试 23 项通过；在一次性 Python 3.14.7 venv 中干净安装当日解析依赖后，`pip check` 通过、完整流水线契约模块 55 项通过、mock E2E 4 项通过（203.436 秒）。合成 fixture 覆盖，未运行真实项目数据或 Provider。细节见[开发与验证](development.md)。

2026-11-14 本地契约、Provider 路由回归和 mock E2E 验证结果记录在[开发与验证](development.md)；没有调用真实 Provider 或部署服务。

以下证据来自 2026-11-13 的历史执行记录，不是本次新跑的测试。

- 2026-11-13 的历史检查记录工作区干净；本任务开始时分支为 `main...origin/main`，但已有本轮需保留的文档修改，具体见[续接交接](handoffs/2026-11-14-translation-workflow.md)。
- `StartUP.txt` 被 `.gitignore` 忽略；`git ls-files` 与 `git log --all -- StartUP.txt` 未发现版本控制/历史记录。该检查不能证明凭据未曾在其他位置泄露。
- 本机快照：Python 3.14.7；`.venv` 中安装 `openai 3.50.0`、`google-genai 3.3.0`、`aiohttp 3.14.5`、`numpy 2.5.4`。依赖声明未锁定版本。
- 完整 mock E2E runner 与单元测试结果见[开发与验证](development.md)；符号链接测试因 Windows 权限未授予而可能跳过。
- 当时涉及的 Python 文件 `py_compile` 通过；活动 Markdown 链接检查和暂存差异检查结果见[开发与验证](development.md)。
- 当时本机 `127.0.0.1:6006` 连通性检查失败。
- E2E 只连接本机 mock server；没有真实 Provider、生产部署或翻译质量验收证据。
- 2026-11-13 的一次历史 Codex Security 扫描未生成正式报告；2026-11-14 后续 Standard 扫描已形成 `partial` 报告，覆盖限制见[安全记录](security-notes.md)。
