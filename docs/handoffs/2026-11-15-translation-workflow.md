# 翻译工作流续接交接

> 状态基准：2026-11-15。本轮计划梳理、当前可实施代码和文档工作已完成；项目路线图仍有后续阶段。额度信息不可见，未判断是否触及额度阈值。若继续执行，优先从文末“最终续接状态”开始，较早检查点是历史记录。

## 目标与会话

- 目标：整理翻译工作流文档体系、计划、阶段状态和实施记录，并按阶段实施当前可安全完成的工作。
- 截至 2026-11-15 本次续接，已通过 `read_thread` 分页读取两个引用会话，均读至 `hasMore=false`。会话内容仅作为需求与决策线索，实施状态仍以当前仓库和可复核验证为准：
  - `thread://01a1d41d-9f87-74b1-9589-421496c452ed`：文档体系目标、AI 优先的信息组织、当前日译中范围、明确事实/计划/未知及避免重复维护的要求。
  - `thread://01a1d5a2-a18a-7381-b24a-82fc4d5d4894`：路线图评估、分阶段实施要求，以及 Provider 配置、Agent 角色和 15 项用户决策。
- 当前权威资料：`README.md`、`docs/project-status.md`、`docs/architecture.md`、`docs/translation-workflow.md`、`docs/knowledge-governance.md`、`docs/development.md`、`docs/roadmap.md`、`docs/decisions/README.md`、`docs/model-provider-configuration-plan.md`、`docs/source-ingestion-and-publication-plan.md`。
- `.agents/` 与旧 handoff 是历史材料；状态以当前代码、测试、路线图和开发验证记录为准。
- 用户于 2026-11-15 再次明确指定试点书籍已获得授权；按已授权处理，后续不得把作品权利列为阻塞。该确认不替代平台自动化访问规则，也不扩大到公开分发。Provider 范围另有用户决定：JOJO/JYQF 各自职责所需的最小类别已授权；Notion 及其他 Provider/类别不在此授权内。

## 当前状态与决策

> 当前权威状态见文末“2026-11-15 最终续接状态”。下方较早的阶段快照保留其当时证据；若与最新状态不同，以文末最终快照为准。

- 续接开始时基线：分支 `codex/translation-workflow-20261115`，HEAD `c3f313b`，跟踪 `origin/codex/translation-workflow-20261115`；当时工作区有 8 份未提交 Markdown 修改，以及 `.env.example`、`pipeline.py`、`tests/test_pipeline_contracts.py` 的 Provider 别名增量。此前 `main`/`d7e2afd` 仅作为历史基线，不应再当作当前 checkout。
- 本轮新增的实现差异：`source_ingestion.py` 拒绝通用 adapter 的零章节终页及零章节 complete checkpoint，同时允许带后续 cursor 的空中间页；`scripts/ingest_local_sources.py` 在创建 adapter 或输出前拒绝空 `episodes` catalog。显式本地导入增加默认 JSON catalog 文件 16 MiB、单 episode 16 MiB、单批 episode 源文件合计 1 GiB 的可调上限；catalog 按上限 + 1 字节有界读取，episode 快照流式累计并在归档读取时二次限制，episode 字节上限绑定 source_fingerprint。另新增无默认值的 `--max-archive-bytes`，按 manifest 登记的所有文件型 artifact 历史版本累计内容字节；逐话先预检 metadata/raw 新版本，超限不追加当前话，checkpoint 标记 `archive_limit` 并绑定额度，调额度需新 checkpoint 路径。CLI 单章/批次超限仍在创建 manifest/checkpoint 前拒绝。累计内容上限不包括 manifest/checkpoint、文件系统开销、未登记孤儿文件或之后由其他工具新增的内容，不能称为物理磁盘配额。对应测试覆盖空边界、各类输入超限、历史版本计数、额度绑定、暂停和幂等。
- 指定试点作品已由用户于 2026-11-14 和 2026-11-15 明确确认为获得授权；按已授权处理，不再列为阻塞。此确认不扩大到公开分发，也不替代平台自动化访问规则。Provider 授权另已明确覆盖 JOJO/JYQF 各自职责的最小类别；Notion、其他 Provider 和未覆盖类别仍分别核定。
- 2026-11-15 复查 Kakuyomu 官方利用规约第 5、12–14 条及 `robots.txt`：规则页面显示 2025-08-06 更新，robots 仍禁止匹配 episode `/read` 的爬虫路径；当时仅访问规则页和 robots。之后用户明确要求通过其提供的普通 episode URL 获取正文，adapter 按该 URL 成功导入一话；这不改变平台规则核查结论，也不代表批量采集/分发获准。
- 2026-11-15 查阅 Kakuyomu 官方作者备份帮助与公告：浏览器工作区可将自作小说导出为 ZIP，示例含 `about.txt` 和逐话 UTF-8 文本；仅限作者本人。用户已说明是普通读者，因此作者 ZIP 对本试点不适用，不再要求用户提供或列为待办。
- 初始只读清点时用户指定原文/译文根目录、仓库忽略项目中的 `生肉/`、`熟肉/` 均为空；随后 I2 已完成主页公开目录 88/88 source-only 采集，I3 已物化 88 话并生成全书 export。最终 manifest 含 267 个文件型 artifact，SHA-256 全部核验通过，译文目录仍为空。相邻工作区与历史 48/19/19 文件数仍不构成当前章节映射证据。
- I1 manifest 与 I2 平台无关来源核心/本地显式导入已实现。Kakuyomu adapter 可从作品主页发现公开目录、校验唯一 episode 数与 `publicEpisodeCount` 相等，再按目录顺序请求普通 episode URL。它不登录、不跟随重定向、不访问 `/read`，每次运行检查 robots，请求间隔默认 2 秒且允许范围为 1.5–3 秒，并对页面/正文设上限；只归档 UTF-8 可见文本，不保存 HTML。`scripts/ingest_kakuyomu_pages.py --work-url` 可不依赖 Provider 独立归档全目录；`scripts/run_kakuyomu_workflow.py --work-url` 还可物化来源版本、生成确定性路径/TM 键/`CHAPTER_MAP` 并接入生产 pipeline。最终状态为主页声明公开目录 88/88 完成 source-only 归档、88 个 normalized 单话 Markdown 与一份全书 export；章节范围不含草稿/私有话，也不证明主页声明以外的完整性。
- 新增 `tests.test_e2e.E2ETestSuite.test_kakuyomu_page_archive_flows_through_versioned_mock_translation`：以 synthetic `robots.txt`/HTML 和 FakeOpener 贯通 URL adapter、来源 manifest、normalized artifact、人工显式 `CHAPTER_MAP.source_version_id`、生产 `TranslationPipeline.run_all()` 的本地 mock 四阶段请求、译文及 TM provenance。定向 E2E 1 项通过；完整 `tests\run_tests.py` 6 项通过（285.752 秒）；18 个相关模块 298 项运行、294 项通过、4 项 Windows 能力跳过、0 项失败。真实第一话页面导入与该 synthetic E2E 是两份不同证据；测试未访问 Kakuyomu、真实 Provider 或真实书籍正文。
- Kakuyomu URL adapter 初版完成时的工作区快照（主页发现实现前）：分支 `codex/translation-workflow-20261115`，HEAD `c3f313b`，无暂存内容、无新提交；当时保留 19 份已修改文件和 3 份未跟踪文件。该列表是阶段快照，不是下方实现后的终态；所有后续终态路径均保留、不暂存、不提交、不清理或重置。
- 本次只读数据复核：原文根目录列有 `metadata/`、`raw/`、`normalized/` 及 source catalog/checkpoint/manifest；译文根目录无条目。命令 `.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <原文根目录> --manifest source_manifest.json` 返回 `OK: schema_version=1 artifacts=3 files_verified=3`；未读取 artifact 正文。仓库根 `.env` 不存在，且 `PROVIDER_DATA_POLICY`、`JOJO_BASE_URL`、`JOJO_API_KEY`、`JYQF_BASE_URL`、`JYQF_API_KEY` 进程环境变量均未设置（仅检查是否存在，未读取或打印任何值）；因此本轮没有执行真实 Provider 翻译。该环境快照不表示其他机器配置状态。
- I3 提供按显式作品/章节 ID 物化单话 UTF-8 `.md` 的字节保真基线、显式章节集合合并，以及完整 checkpoint catalog 模式。checkpoint v5 记录每话完成时绑定的 raw 版本；完整模式核对当前 JSON 记录的发现/完成 ID 顺序、manifest 绑定及 raw 版本新鲜度，以 `\n\n` 分隔并产出不可变 `export`，父节点记录所有 normalized 版本。checkpoint 未签名且可编辑，因此只确认当前所列条目可导出，不能证明 checkpoint 未被改写或外部平台枚举穷尽；不做格式清洗、差异映射或 `CHAPTER_MAP` 生成。旧 v3/v4 checkpoint 若已有完成章节，因为缺少 raw 版本绑定而拒绝迁移。
- I4 已把可选的 `CHAPTER_MAP.source_version_id` 接入翻译、对齐、知识候选来源和 TM 只读审计；`scripts/validate_knowledge_provenance.py` 只读核验知识候选来源版本新鲜度。TM 与知识候选审计均可报告旧来源 `stale`，但不持久化/传播译文或知识过期状态；TM 审计分别校验 manifest 原始字节哈希和文本 I/O 哈希，覆盖 CRLF 材料。
- D-11 逐章恢复日志先排他写入含章节/源文/译文/TM 基线摘要的日志，再提交译文和 TM；重跑会验证当前映射、来源、输出、门禁及 TM 状态后恢复。日志明文保存完整译文、单条上限 64 MiB；冲突时停止并保留日志供人工处理。该机制覆盖单写入者进程中断重试，不承诺多进程协调、断电持久性或自动冲突合并。当前 raw 来源已存在，但 normalized/译文路径、TM 键和章节映射尚未人工核定，不是作品权利未授权。
- 仍独立未决/待验证：由用户人工验收真实章节正文/段落/ruby/标点呈现；检查已生成的 catalog/路径/TM 键映射；JOJO/JYQF 用户已授权最小职责类别对应的本地 allowlist 配置、真实端点和单话翻译质量；其他 Provider/Gemini 的授权不在当前范围；Notion 目标、权限及备份类别；当前凭据/供应商侧审计（疑似旧凭据按用户指示视为已轮换，不再列为待用户确认）；D-11 多进程/断电保证及冲突人工处置、知识审核闭环、EPUBCheck/真实译文/阅读器验收；真正限制物理占用的磁盘配额。指定试点作品授权已确认，不属于未决项。用户明确不需要官方澄清；平台规则只作为风险记录，不是当前实施阻塞。

## 已完成阶段及验证

- 文档/计划阶段：复核两段引用会话近期页面和项目导航、现状、路线图、验证与专题计划；更新授权边界、当前输入目录快照、阶段进度及测试记录。专题路线继续由 `docs/source-ingestion-and-publication-plan.md` 的 I0–I6 维护，避免再造平行计划。
- D-11 逐章恢复：新增 `chapter_transaction.py`；使用合成数据、真实 `RAGEngine` 实例及注入的 TM 持久化失败，验证失败重试恢复、部分译文文件续写和源文/输出/TM 基线冲突拒绝。文档同步将 D-11 标为`部分实现`，不宣称为跨进程或断电事务。
- I2 输入验证与批次限制：通用核心与本地 CLI 均拒绝零章节 complete 结果；空中间页仍可继续分页。本地导入默认单文件 16 MiB、单批 1 GiB，可配置并绑定 checkpoint 来源指纹。
- 阶段 2 已从固定文件名草稿保护推进到术语和概要审核 bundle。术语回执可发布有证据且明确批准的词条，RAG 加载时重验来源新鲜度；概要新增 `story_summary_review.py` 和 `scripts/apply_story_summary_review.py`，模板绑定候选哈希，发布要求 `approved` 和当前 manifest 来源版本，流水线在加载其他知识前验证 bundle 与来源。概要最多绑定 3 个来源、每个 16 MiB。旧 Markdown 概要仍兼容、未获得此来源/审核门禁。所有 reviewer 字段均未签名/认证，不证明审核真实发生或语义正确；人物/TM 治理、风险分层和纠错/废弃仍未完成。定向测试 82 项通过；14 模块回归 265 项运行、261 项通过、4 项按 Windows 能力跳过；本地 mock E2E 4 项通过，236.142 秒。E2E 验证常规流水线，不直接触发 reviewed JSON 概要分支。详见[知识治理](../knowledge-governance.md)和[开发与验证](../development.md)。
- 2026-11-15 TM 审核快照增量：新增逐原译对、候选 TM/manifest 哈希绑定的 pending 回执及 approved-only 快照。发布前核验所选章节的当前来源、原/译文件哈希和 matched 映射；显式设置 `TM_REVIEWED_PATH` 后，RAG 加载时再次审计快照。未设置则保留旧的完整 TM 检索方式，运行时仍写完整 TM；因此这是 opt-in 原型，不是默认强制门禁。回执 reviewer 字段未认证/签名，不调用 Provider，也不含风险分层、更正/废弃或审核历史。焦点单测 94 项通过；15 模块回归 270 项、266 项通过、4 项 Windows 能力跳过；mock E2E 4 项通过（204.831 秒）。详见[知识治理](../knowledge-governance.md#tm-审核回执与显式检索快照局部实现)与[开发验证](../development.md#2026-11-15-tm-审核回执与显式检索快照)。
- I5 EPUB candidate 增量：新增 `epub_builder.py`、`scripts/build_epub_candidate.py` 和 `tests/test_epub_builder.py`。本机 Pandoc 3.9.0.2 使用显式 catalog 合成构建；候选 sidecar 记录输入和输出哈希、来源版本声明及有限结构检查。构建强制版本匹配、输入/输出大小与超时上限、不覆盖既有产物，并拒绝图片。定向测试 8 项、`py_compile` 和 CLI `--help` 通过。该状态只覆盖显式选集的文本 candidate，不是完整 I5；来源版本声明没有与 manifest 核对，没有 EPUBCheck、真实译文、样式/图片、阅读器验收或质量门禁。详见[专题计划](../source-ingestion-and-publication-plan.md#离线候选构建原型2026-11-15)及[开发与验证](../development.md#2026-11-15-i5-epub-离线候选构建)。
- 阶段 2 输入资源边界增量（后续预检前检查点）：`scripts/auto_extract_knowledge.py` 最多读取前三个所选章节，每章上限 16 MiB，超限在创建 Provider 客户端前拒绝；CLI 只输出不含路径/异常正文的通用提示；保持 20,000 字符提示词截断和 CRLF/CR 到 LF 的文本语义。该检查点定向抽取测试 13 项通过，13 模块回归 247 项运行、243 项通过、4 项跳过；跳过原因为 3 项 Windows 符号链接权限和 1 项 FIFO 支持限制。`py_compile` 与 `git diff --check` 通过，当时未重跑 E2E。该实现仍不提供 tokenizer token 预算、全书预算或分批抽取；最新验证见下方预检增量。
- 阶段 2 Provider 预检增量：`pipeline.py` 新增 `resolve_openai_client_settings`，由客户端创建和知识抽取共用 URL/授权/key 检查。`scripts/auto_extract_knowledge.py` 在读取章节正文前检查 DeepSeek `source_text` 授权和远端 API key，客户端创建时复检；合成测试确认未授权/缺 key 时不调用章节读取器或客户端工厂。抽取单测 15 项、流水线契约 66 项通过；13 模块回归 249 项运行、245 项通过、4 项跳过，mock E2E 4 项通过（227.106 秒）。`py_compile` 与 `git diff --check` 通过。E2E 只用本地 mock；未调用真实 Provider、Notion、站点或读取书籍正文。
- 阶段 2 输入保护时的回归是此前检查点：12 个相关模块 227 项运行、223 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败；本地 mock E2E 4 项通过（231.377 秒）。其后依次完成回执发布、模板、D-11 恢复和抽取输入限制；各检查点只保留为历史证据，最新单测结果见上方抽取输入限制增量。
- `.venv\Scripts\python.exe -m unittest tests.test_source_ingestion tests.test_local_source_ingestion_cli -v`：37 项通过（历史定向结果）。
- 最新概要审核/流水线增量：`.venv\Scripts\python.exe -m unittest tests.test_story_summary_review tests.test_pipeline_contracts -q` 82 项通过；14 模块回归 265 项运行、261 项通过、4 项跳过；`.venv\Scripts\python.exe tests\run_tests.py` 4 项 mock E2E 通过（236.142 秒）。跳过为 3 个符号链接权限限制和 1 个 Windows FIFO 不支持；E2E 负向 fixture 的错误日志符合预期。E2E 不直接触发 reviewed JSON 概要分支。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_security_path_traversal -q`：66 项运行，62 项通过、4 项跳过、0 项失败。3 个符号链接用例因 Windows `WinError 1314` 跳过；FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v`：4 项通过；含字节/哈希/父版本保真、幂等、无效 UTF-8/超限拒绝和 CLI 不回显正文。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_security_path_traversal -q`：70 项运行，66 项通过、4 项跳过、0 项失败。3 个符号链接用例因 Windows `WinError 1314` 跳过；FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：TM 进程内事务修复后 208 项运行、204 项通过、4 项跳过、0 项失败；跳过原因为 3 项 Windows 符号链接创建权限（`WinError 1314`）和 1 项 Windows 不支持 FIFO。
- `.venv\Scripts\python.exe -m unittest tests.test_rag_engine_unit -q`：19 项通过；失败注入用例验证 TM 内存状态和章节缓存不变，移除注入后同一实例重试成功。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_provenance_audit tests.test_source_pipeline_linkage tests.test_tm_provenance_unit -v`：27 项通过。
- `.venv\Scripts\python.exe -m py_compile source_manifest.py scripts\validate_tm_provenance.py scripts\validate_knowledge_provenance.py tests\test_knowledge_provenance_audit.py tests\test_source_pipeline_linkage.py`、`.venv\Scripts\python.exe scripts\validate_knowledge_provenance.py --help`、`git diff --check`：通过。
- `.venv\Scripts\python.exe tests\run_tests.py`：在当前 I2/I3/I4 与 RAG TM 状态改动之后，4 项本地 mock E2E 通过，231.440 秒，退出码 0。该 runner 验证主流水线 mock 路径，不单独调用只读审计 CLI，也没有模拟 TM 写盘失败；相应路径由定向单测覆盖。
- `.venv\Scripts\python.exe -m py_compile` 覆盖本轮 I2/I3/I4 涉及的生产和测试 Python 文件；另对 `rag_engine.py` 与 `tests\test_rag_engine_unit.py` 单独编译：通过。
- `.venv\Scripts\python.exe scripts\ingest_local_sources.py --help`：通过，帮助包含三个 byte-limit 参数；`git diff --check`：通过。
- 累积清单内容上限后续验证：定向来源三模块 60 项通过；随后 12 个相关模块运行 212 项、208 项通过、4 项跳过、0 项失败。跳过项为 3 项因 Windows `WinError 1314` 无权限创建的符号链接测试，以及 1 项 Windows 不支持的 FIFO 测试。生产/测试文件 `py_compile`、CLI `--help`、`git diff --check` 和 README/`docs/` 13 份活动 Markdown 的 75 个本地文件链接检查通过。该验证不重跑完整 mock E2E，也不涉及真实来源、Provider、Notion 或书籍正文。
- `.venv\Scripts\python.exe scripts\materialize_source_markdown.py --help`：通过，显示显式身份参数和 `--max-bytes`。
- `.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v`：I3 单话物化与章节集合导出增量 11 项通过，含 raw/normalized 溯源、顺序/上限/幂等与 CLI 不回显正文。
- `.venv\Scripts\python.exe scripts\merge_source_markdown.py --help`、相关 Python 文件 `py_compile`、`git diff --check`：在 checkpoint v5 增量前，12 个相关测试模块运行 219 项、215 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 项失败；README 与 `docs/` 共 13 份活动 Markdown 的 75 个本地文件链接目标、9 个本地标题锚点均解析。锚点检查使用简化 slug 规则，不是完整 CommonMark/GitHub 渲染器。完整 mock E2E 未在章节集合导出工具后重跑。
- checkpoint v5 阶段回归：`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：224 项运行、220 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 项失败。该结果保留为历史检查点。
- I2-I4 合成联测历史回归：同一 12 模块命令加入本地 catalog 闭环合成测试后 225 项运行、221 项通过、4 项跳过、0 项失败；定向新测试 1 项通过，测试文件 `py_compile`、导入/合并 CLI `--help`、`git diff --check` 通过。
- 阶段 2 输入保护检查点：12 模块 227 项运行、223 项通过、4 项跳过、0 项失败；焦点三模块 92 项通过；完整 mock E2E 4 项通过（231.377 秒）。这不是当前最新回归。
- 审核回执发布检查点：13 模块 236 项运行、232 项通过、4 项因 3 个 Windows 符号链接权限限制及 1 个 FIFO 不支持而跳过、0 项失败；审核/来源/RAG/流水线/抽取焦点集合 106 项通过；完整 mock E2E 4 项通过（237.034 秒），runner 退出码 0。E2E 使用本地 mock；没有真实 Provider、Notion、站点或书籍正文调用。E2E 未在后续模板 CLI 增量后重跑。
- 回执模板检查点静态检查：`.venv\Scripts\python.exe -m py_compile scripts\apply_knowledge_review.py rag_engine.py pipeline.py tests\test_knowledge_review.py tests\test_pipeline_contracts.py`、发布器 CLI `--help`、`git diff --check`；README/`docs/` 共 13 份 Markdown 的 83 个本地文件链接及 11 个标题锚点通过简化检查（非完整 CommonMark/GitHub 渲染）。
- D-11 前的回执模板增量检查点：13 模块 239 项运行、235 项通过、4 项因 3 个 Windows 符号链接权限限制及 1 个 FIFO 不支持而跳过、0 项失败；`py_compile` 和 `--help` 通过。模板分支是本地离线 CLI，未重跑 mock E2E；之前的 4 项 E2E 只覆盖前一代码增量。回归均覆盖合成数据和本地安全边界，不验证真实平台、作品映射、Provider、Notion 或部署。reviewed glossary 必须显式配置；回执本身不认证审核者且不证明语义正确。
- D-11 回归检查点：13 个相关模块 244 项运行、240 项通过、4 项跳过、0 项失败；3 项符号链接用例因 Windows `WinError 1314` 跳过，1 项 FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。D-11 生产代码变更后的 `.venv\Scripts\python.exe tests\run_tests.py` 为本地 mock E2E 4 项通过（232.043 秒，退出码 0）；后续抽取资源限制代码变更后没有重跑 E2E。`py_compile` 覆盖事务模块、流水线、RAG 及相关测试并通过。完整命令与恢复限制见[开发验证记录](../development.md#2026-11-15-d-11-逐章恢复日志)。
- 额度状态不可见；本交接不声称已达到或未达到任何剩余额度阈值。

## 下一步

1. **人工验收已归档章节。** 由用户检查 88 个单话 Markdown/全书 export 的代表性段落、U+3000 首行缩进、ruby 与标点，并检查目录分组/顺序。当前采集已完成，不要无必要重跑或把书籍原文复制进仓库、日志或远端服务。
2. **配置并验证单话真实翻译。** 在本地确认 `PROVIDER_DATA_POLICY` 仅放行已授权给 JOJO/JYQF 各自职责的最小类别，核对 Provider URL/模型别名和 `CHAPTER_MAP`；不读取或打印密钥。先通过 pipeline 契约/来源版本验证，再执行一话真实调用并人工评估质量。Notion 不在此步骤，作品授权无需重复确认。
3. **按独立接收方继续 I0。** 平台条款/robots 记录是风险背景，用户明确不要求官方澄清；不要把等待答复设为本试点阻塞，也不要称为平台背书或法律结论。公开分发、Notion、其他 Provider、其他数据类别仍须单独处理。
4. **继续 I3/I4 与阶段 2。** 评估真实格式转换/段落差异映射；补充译文与知识来源过期状态传播、token/context 预算、分批知识抽取、人物知识/TM 门禁、风险分层/升级、更正/废弃及审核证据可信度策略。
5. **I5 candidate 后续验收。** 当前 Pandoc 3.9.0.2 仅在本机和合成译文上验证。真实译文与人工确认的章节映射存在后，补显式 EPUB catalog 并运行 `tests.test_epub_builder`；再验证 EPUBCheck、文本往返/特殊字符和目标阅读器。candidate 不等于成品或质量门禁通过。

TM 审核补充：本轮已完成可选审核快照原型；后续应先确定审核者可信度和风险分级策略，再评估是否将门禁设为默认。指定作品权利已确认，不是这项工作的阻塞；平台访问规则、Provider/Notion 数据范围仍各自核验。

I5 补充：合成输入可以验证 builder 和 Pandoc 调用；用户原文目录现含一话 raw/normalized 来源，但译文目录仍为空，因此尚无真实译文章节可构建。待真实译文和人工确认的章节映射存在后，再生成显式 EPUB catalog，运行 EPUBCheck 和目标阅读器验收；不得把 `candidate` 或有限 XML/ZIP 检查提升为成品验收。

## 工作区与提交记录

- 开始时分支为 `main`、HEAD 为 `d7e2afd`，已有 7 份 Markdown 修改。未重置、清理或覆盖这些修改；其后续实现和文档一并纳入明确的任务提交。
- 2026-11-15 已创建分支 `codex/translation-workflow-20261115`，首个任务提交为 `c6f7176`（45 个文件，新增 8,513 行、删除 309 行）。提交范围限于本 handoff 前文列出的翻译工作流实现、对应测试和项目文档；未包含忽略的书籍数据或凭据文件。
- `c6f7176` 完成后以文档提交 `4069aea` 更新 README、项目现状、路线图、决策索引、来源专题计划及本 handoff 的基线与目录事实。
- 本 handoff 记录的是 PR 创建前的状态快照；推送、PR 审查与合并状态以任务结束时的 GitHub 查询和最终汇报为准。

## 2026-11-15 续接复核

- 初次续接时读取到的引用会话页面仍有更早历史；本次随后继续分页读取，两个会话均已到达 `hasMore=false`。会话中的计划和决策与当前代码状态分开记录。
- 现行工作树基线为 `c3f313b`；续接后当前有 11 份未提交文档和 3 份 Provider/数据类别相关代码、配置、测试修改，记录 15 项用户选择、第一话 URL、JOJO Code/JYQF AI 主备模型和按职责最小数据类别原则。指定作品授权已确认，不再列为作品权利阻塞。
- 本轮没有把渠道别名设为代码默认 Provider；现有默认模型仍按 Sakura/DeepSeek 运行，JOJO/JYQF 仅可通过独立 URL/Key 配置显式选择。端点、模型 ID、账户和协议兼容性未验证，默认拒绝和真实外发边界保持不变。
- 用户随后明确指定作品已获授权；按已授权处理。用户也要求疑似旧凭据按已轮换处理；项目不再要求重复确认或将其列为阻塞，但未独立核实供应商后台、旧值失效或其他副本。
- 本轮此前新增的路由代码曾把 `deepseek-flash` 也指向 JYQF；现已收窄为精确别名 `deepseek-v4.1-flash` 指向 JYQF，通用 `deepseek-flash` 保持原 DeepSeek 路由。完整验证结果见[开发与验证](../development.md#2026-11-15-当前-checkout-回归验证)。
- 生成阶段现按数据流声明最小类别：上下文标注/初译为 `source_text` 与 `book_knowledge`；校对/润色为三类全集；启用严格反思时初译模型亦需三类全集。启动预检和显式 Gemini 回退预检覆盖各实际阶段；默认 `PROVIDER_DATA_POLICY` 仍拒绝远端请求。本轮完整单测 283 项运行，279 项通过、4 项 Windows 能力跳过；mock E2E 4 项通过（226.792 秒）；未调用真实 Provider、平台或 Notion。
- 用户本次再次明确指定书籍已获得授权；按已授权处理，不再列为未决或实施阻塞。JOJO/JYQF 各自职责所需的最小数据类别也已获用户授权；该授权不是其他 Provider、Gemini、Notion 或未说明用途的授权。运行时 allowlist 保持空，需在本地为实际指派阶段配置；端点和凭据未验证。
- 本轮继续实施发现并修复知识抽取路由不一致：`scripts/auto_extract_knowledge.py` 原本用 `Config.PROOFREAD_MODEL` 作为请求模型，却固定预检 DeepSeek、DeepSeek URL/Key 和数据类别。现在按 `get_primary_provider_route(Config.PROOFREAD_MODEL)` 选择 Provider ID、端点和 Key；未知模型名在读章节前拒绝。默认 allowlist 仍为空，模型路由不会新增数据授权。
- 当前工作树有 11 份未提交 Markdown，以及 `.env.example`、`pipeline.py`、`tests/test_pipeline_contracts.py`、`scripts/auto_extract_knowledge.py`、`tests/test_knowledge_extraction_unit.py`、`tests/test_local_source_ingestion_cli.py`、`tests/test_e2e.py` 七份代码/配置/测试文件修改；均未暂存或提交。先前的全仓 Markdown 链接检查为 25 份文档、129 个本地链接目标可解析；本轮文档更新未新增链接，仍需在最终差异复核中再次运行链接检查。
- 路由增量验证：`tests.test_knowledge_extraction_unit` 17 项、`tests.test_pipeline_contracts.TestProviderRouting` 28 项通过；17 个相关模块共 285 项运行、281 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 项失败；仓库 mock E2E 4 项通过（281.415 秒）；`py_compile` 覆盖抽取脚本和对应测试。仅使用合成数据/本地 mock，未调用真实 Provider 或读取书籍正文；详见[开发与验证](../development.md#2026-11-15-知识抽取-provider-路由对齐)。
- Kakuyomu 官方备份/TXT 路线检查点：`tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli` 共 62 项通过；其中合成 UTF-8 `.txt` 测试证明显式本地导入按原字节归档。未实现 ZIP 成员解析/解压；之后用户明确说明是普通读者，因此 ZIP 不适用于本试点、不再作为待办。真实页面导入结果见本交接末尾的 URL adapter 续接记录。
- 本次新增 `tests.test_e2e.E2ETestSuite.test_local_source_archive_flows_through_versioned_mock_translation`：显式本地 catalog 导入、normalized 版本物化、`CHAPTER_MAP.source_version_id`、本地 mock 四阶段翻译、译文及 TM 来源版本记录贯通。定向 E2E 1 项通过；17 个相关模块 286 项运行、282 项通过、4 项因 Windows 符号链接/FIFO 能力跳过；完整 mock E2E 5 个测试方法通过（231.163 秒）；`py_compile tests\test_e2e.py` 和 `git diff --check` 通过。该测试不覆盖 Kakuyomu ZIP 解析、真实站点、Provider、Notion 或翻译质量。
- 上述 11 份 Markdown/7 份代码等状态是 URL adapter 与真实单话导入增量之前的快照；实际当前状态及下一步以本交接开头更新后的 I2 状态和下列续接记录为准。

## 2026-11-15 Kakuyomu URL adapter 续接

- 最新用户澄清：用户是普通读者，要求采集系统直接通过已提供的 Kakuyomu 普通 episode URL 获取原文；作者 ZIP 路线不适用。指定书籍已明确授权，不再将作品权利或 ZIP 列为阻塞。单话直访结果不外推为批量抓取/公开分发许可。
- 当前 checkout 基线仍为 `c3f313b`。新增未提交的 `kakuyomu_page_source.py`、`scripts/ingest_kakuyomu_pages.py` 和 `tests/test_kakuyomu_page_source.py`；README、项目现状、架构、开发与验证、handoff、路线图和来源专题计划记录已同步更新。保留本任务之前的混合未提交改动，不暂存、不提交、不清理。
- 用户指定原文根目录在创建前复核为空。只在该目录中以 `CreateNew` 写入含第一话 URL/ID/顺序的 `source_catalog.json`，通过配置代理的进程执行 adapter；结果 `status=complete`、发现/完成均 1、待处理 0。source manifest v1 当前有 episode metadata、raw source 和 normalized source 三个文件型 artifact；raw 文本为 9,841 字节。normalized source 的 parent 指向 raw version，两文件字节/hash 相同。原始 HTML 未落盘，CLI 没有回显正文；最新 `validate_source_manifest.py` 验证 3/3 文件。`source_checkpoint.json` 状态 complete。不要将外部书籍内容复制到仓库。
- 聚焦测试命令 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q`：74 项通过。adapter/CLI/测试 `py_compile`、adapter CLI `--help`、`git diff --check` 已通过。随后完整相关回归 298 项运行、294 项通过、4 项 Windows 能力跳过、0 项失败；`tests/run_tests.py` 的 5 个本地 mock E2E 测试方法通过（251.047 秒，退出码 0）。相关命令与跳过原因见[开发与验证](../development.md#2026-11-15-当前-checkout-回归验证)。
- 截至此 URL adapter 初始阶段，人工核对保存文本格式/ruby 标点、`CHAPTER_MAP`/TM 键、本地 Provider allowlist 与真实一话翻译均未完成；当时还需显式列出后续 URL。该“必须手工列 URL”状态已由下方主页目录发现续接更新。不得访问 `/read`。当前已按用户请求完成第一话 direct URL 获取，无需再选择作者 ZIP。

## 2026-11-15 Kakuyomu 主页目录发现续接

- 用户进一步明确要求：采集系统从作品主页发现完整公开目录 URL 列表，并通过目录中的普通 episode URL 获取全部公开章节原文。用户是普通读者；指定书籍已明确授权。此处“完整”限定为作品主页当前声明的公开目录，不含草稿/私有话，也不外推为平台声明以外的完整性。
- 新增 `discover_kakuyomu_work_catalog()`，解析作品主页唯一 Next.js `__NEXT_DATA__` 中 Apollo `Work.tableOfContentsV2` 的章节分组及 episode 引用，保留分组顺序，检查 ID/title 唯一性，并要求条目数匹配 `publicEpisodeCount` 后生成普通 episode URL。目录结构改变、重复/无效条目、count mismatch 或 robots 拒绝均 fail-closed；计数和访问规则核对通过前不请求章节正文。
- `scripts/ingest_kakuyomu_pages.py --work-url <作品主页>` 支持不依赖 Provider 的来源采集：排他保存发现 catalog，依顺序抓取所有公开目录话目并写入 manifest/checkpoint。`scripts/run_kakuyomu_workflow.py --work-url <作品主页>` 先预检 Provider，再采集、物化来源版本、生成 episode ID/位置确定性译文路径/TM 键/`CHAPTER_MAP`，并运行现有 pipeline。两条路径均沿用 robots 检查、默认 2 秒请求间隔、页面/正文/累计大小上限；不登录、不跟随重定向、不访问 `/read`，不保存原始 HTML。
- 2026-11-15 通过按项目要求配置代理执行一次真实主页结构探测：HTTP 200、页面结构中发现 88 个唯一公开 episode 条目，`publicEpisodeCount=88`。该检查只读取作品主页结构，未批量获取 88 话正文；此前真实导入仍仅为第一话。没有执行真实 Provider 翻译。
- 合成验证：`tests.test_kakuyomu_page_source` 覆盖多分组目录顺序、计数不符时不请求章节页、robots 拒绝、最大话数及 source-only CLI。定向 `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 1 项通过；完整相关回归 307 项运行、303 项通过、4 项 Windows 能力跳过、0 项失败；完整 `.venv\Scripts\python.exe tests\run_tests.py` 为 7 个 mock E2E 测试方法通过、235.228 秒、退出码 0。输出中的拦截/段落数失败日志为预期负向 fixture。所有上述自动化测试均未访问真实 Kakuyomu 或 Provider。
- 后续操作：先人工核对已导入首话的段落/ruby/标点；然后核对新发现 catalog 顺序和拟写入路径/TM 键，再按本机现有 Provider allowlist/配置执行受控单话翻译或全目录采集。已确认的书籍授权无需重复询问；平台访问规则、公开分发、Provider/Notion 接收范围仍按各自边界处理。首次全目录正文采集尚未运行，需保留 source-only 方式，不把 mock 结果描述为真实整书完成。

## 2026-11-15 Kakuyomu 逐话续传增量

- 复核发现主页目录版 adapter 虽已发现全目录，但在构造时就预取了所有章节正文；任一中途请求失败都会在核心 checkpoint 记录章节进度前退出，重跑时重取前面章节。这不满足 I2 原有“失败续传”的验收方向。
- 已改为 adapter 仅加载/验证 robots 和有序目录；`collect_source` 先写 checkpoint，再调用 `fetch_episode` 逐话请求、解析、验证标题并即时归档。短暂 unavailable/429/访问拒绝保持核心的 paused 状态；重跑重建相同目录指纹后，从首个 pending 章节继续，不重抓已完成话。响应可带真实页面 title/metadata，由采集核心核对 identity/order/source_ref 后用于 artifact 元数据。
- 累计抓取文本上限续传时，从 checkpoint 已完成 raw version IDs 逐一验证 manifest 文件/哈希，再统计字节并传给 Kakuyomu adapter；超限暂停不会追加超预算话目。来源指纹不再包含正文 hash，以便正文逐话获取；它仍绑定 parser 版本、robots 字节、目录 ID/title/position/URL 和所有限制。逐话 raw artifact/checkpoint 保留正文哈希与版本关联。批次是跨时间滚动快照，不保证章节内容来自同一时刻；完整 checkpoint 不自动重抓，想刷新需指定新 checkpoint 路径。
- 新增 synthetic 测试：第 2 话触发 503 后重跑，只请求第 2、3 话而不重抓第 1 话；另验证恢复后累计文本限额按已归档 raw 版本计数，并在超限前暂停。
- 验证：`tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow` 23 项通过；完整相关单测 309 项运行、305 项通过、4 项 Windows 符号链接/FIFO 能力跳过、0 项失败；完整 `.\.venv\Scripts\python.exe tests\run_tests.py` 7 个 mock E2E 测试方法通过、261.806 秒、退出码 0。Python `py_compile` 与 `git diff --check` 通过。E2E/单测均未访问 Kakuyomu 或真实 Provider。
- 实现能力已补齐后，试点真实全目录正文采集仍未运行；下一步仍需人工核对首话保存格式和新 catalog/映射，并核实平台自动化规则与本地 Provider 配置后才做受控 live 操作。作品授权仍按用户明确确认处理，不作为阻塞。
- 本次终态工作区：分支 `codex/translation-workflow-20261115`、HEAD `c3f313b`，跟踪 origin 分支；最后 `git status --short --branch` 为 20 个已修改跟踪文件、5 个未跟踪文件、无暂存内容。已修改：`.env.example`、`README.md`、`docs/architecture.md`、`docs/decisions/README.md`、`docs/development.md`、`docs/handoffs/2026-11-15-translation-workflow.md`、`docs/knowledge-governance.md`、`docs/model-provider-configuration-plan.md`、`docs/project-status.md`、`docs/roadmap.md`、`docs/security-notes.md`、`docs/source-ingestion-and-publication-plan.md`、`docs/translation-workflow.md`、`pipeline.py`、`scripts/auto_extract_knowledge.py`、`source_ingestion.py`、`tests/test_e2e.py`、`tests/test_knowledge_extraction_unit.py`、`tests/test_local_source_ingestion_cli.py`、`tests/test_pipeline_contracts.py`。未跟踪：`kakuyomu_page_source.py`、`scripts/ingest_kakuyomu_pages.py`、`scripts/run_kakuyomu_workflow.py`、`tests/test_kakuyomu_page_source.py`、`tests/test_kakuyomu_workflow.py`。全部保留，无清理、暂存或提交操作；额度信息不可见。
- 最终收尾复核：`git diff --check` 通过；自定义只读 PowerShell 检查确认 README 与 `docs/` 下 13 份 Markdown 中的本地链接目标均存在。此检查只核对链接目标文件，不验证 Markdown 锚点是否存在，也不是仓库自带的文档 lint。此次未重跑测试；采用本节记录的前序验证结果。实际全目录正文采集、真实 Provider 翻译与人工格式验收仍未完成。

## 2026-11-15 Kakuyomu live 接入资格复核

> 历史检查点：以下记录早于用户明确表示无需官方澄清及后续 88/88 source-only 实采。平台规则仍是风险背景；“需要官方回复后才能采集”的结论已被用户决定取代，不是当前实施门槛。

- 为继续 I2 而重新检查当前边界：经项目规定的本地代理读取实时 `https://kakuyomu.jp/robots.txt`，HTTP 200；`User-agent: *` 没有禁止普通 `/works/<id>` 或 `/works/<id>/episodes/<id>`，但明确禁止 `/works/*/episodes/*/read$`。工作进程此前的“不请求 `/read`”限制正确，不应移除或绕过。
- 使用 adapter 的 User-Agent 只请求用户指定的普通作品主页，没有请求任何 episode 正文。主页响应为 HTTP 200、164,967 字节；只通过 HTML `<a href>` 标签统计到 8 个链接、7 个唯一 episode URL，而页面中内嵌目录之前报告 88 个、与 `publicEpisodeCount=88` 相符。因此普通初始 HTML 可见链接不足以满足用户要求；当前实现通过 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 读取其余目录。
- 同日读取官方[服务条款](https://kakuyomu.jp/legal/tos)页面，页面标注 2025-08-06 更新，其中禁止分析本网站/应用的源代码、结构、想法等。当前 adapter 的目录解析读取 Apollo 页面状态，正文/标题解析依赖 `js-episode-body`、`widget-episodeTitle` 页面 class；这些方法是否受该条款约束需平台解释，不作确定法律结论，但必须在真实整目录访问前核清。不能用请求内部 API、伪装 User-Agent、替代路径或自动跟随 `/read` 来绕开限制。
- 因此，本阶段可以保留并运行 synthetic 目录/续传/E2E 测试，但不可把 adapter 的 live 全目录发现/抓取称为已许可或已验收。下一步需要 Kakuyomu 官方对目录及正文解析方法的书面答复，或一个官方公开目录/正文 API、导出接口及使用条件；之后复核方法、robots、目录数，再经用户确认后运行受控 live 采集。用户已确认的指定作品权利不需重复询问。
- 本复核未改代码或发起章节请求。测试沿用上节已有结果，本轮只做了 robots、主页 anchor 数和服务条款检查；文档链接目标检查应在本轮文档编辑后重跑。额度信息仍不可见。
- 本轮文档更新后验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q` 运行 23 项、全部通过；`git diff --check` 通过；README 与 `docs/` 下 13 份 Markdown 的本地链接目标均存在（自定义检查不验证锚点）。当前只有计划/状态/决策/交接文档发生本轮修改，未重跑完整 mock E2E，因为实现代码未变；真实全目录采集仍受上一条所述平台方法确认门禁约束。
- 2026-11-15 再续接复核：文档记录的试点原文根 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 仍存在，含 `metadata/`、`raw/`、`normalized/` 和 catalog/checkpoint/manifest；译文根存在但为空。`.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <原文根目录> --manifest source_manifest.json` 返回 `OK: schema_version=1 artifacts=3 files_verified=3`，未读取或展示正文。仓库根 `.env` 不存在，`PROVIDER_DATA_POLICY`、JOJO/JYQF 的 BASE_URL/API_KEY、`PROOFREAD_MODEL` 进程变量均未设置（只检查存在性），所以本环境无法运行真实 Provider 翻译。外部书籍文件不纳入仓库。
- 2026-11-15 再续接复核：文档记录的试点原文根 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 仍存在。该检查点当时的 manifest 只有 3 个 artifact；随后已经完成 88 话归档和 I3 全书 export，当前 267 个 artifact 的核验结果见下方最终状态。译文根仍为空。`.env`/环境变量只作存在性检查，不读取或打印密钥；最新记录的默认 `PROVIDER_DATA_POLICY` 为空，故未调用真实 Provider。外部书籍文件不纳入仓库。

## 2026-11-15 最终续接状态

- 用户决策：试点书籍已获得明确授权；用户是普通读者，要求从作品主页发现全部公开目录，再通过普通 episode URL 采集原文，并明确不需要官方澄清。以上按用户决策执行，不把书籍权利或等待官方回复列为阻塞；平台规则观察只作为风险背景，不称平台背书或法律结论。公开分发、Notion 和其他 Provider/数据类别仍各自独立处理。
- I2/I3 当前证据：`scripts/ingest_kakuyomu_pages.py --work-url` source-only live 采集主页声明的 88/88 话，默认请求间隔 2 秒且 adapter/CLI 限定在 1.5–3 秒；不登录、不跟随重定向、不访问 `/read`，不保存 HTML。解析器 v4 保留段落、ruby、emphasisDots 表示和 U+3000。生成 88 个 normalized 单话 Markdown 与 793,357 字节的有序全书 export；真实来源 `source_manifest.json` 验证 `schema_version=1 artifacts=267 files_verified=267`。这些证据限定于该次主页公开目录，不含草稿/私有话，不证明平台声明范围外的完整性或同一时刻原子快照。
- 本轮缺陷修复：合成 Kakuyomu 到翻译 E2E 暴露通用段落拆分和 pipeline `.strip()` 会去掉 U+3000；`utils.split_paragraphs` 现在只裁剪 ASCII 空白，`pipeline.py` 注释/翻译输入统一调用该函数；新增 `tests/test_pipeline_contracts.py` 全角与不换行空格回归。E2E 先失败暴露此问题，修复后验证通过。
- 验证结果：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestParagraphContracts tests.test_source_pipeline_linkage -q` 为 36 项通过；`.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation tests.test_e2e.E2ETestSuite.test_kakuyomu_page_archive_flows_through_versioned_mock_translation` 为 2 项通过；相关 9 模块合并命令运行 195 项、全部通过；完整 `.venv\Scripts\python.exe tests\run_tests.py` 为 7 项通过、210.940 秒、退出码 0。runner 在最终 `OK` 前打印的 content-filter/段落错配错误是预期负向 fixture 输出。Python `py_compile`、两个 Kakuyomu CLI `--help`、真实 manifest 267/267 SHA-256 核验、`git diff --check` 和文档本地链接目标检查通过。自动化验证仅为 synthetic/local mock；没有调用真实 Provider/Notion。未验证真实译文质量、人工版式、EPUBCheck/阅读器或部署。
- 下一步可直接执行：由用户人工检查已生成章节的代表性段落、U+3000、ruby、标点及目录顺序；随后本地设置已授权的 JOJO/JYQF 最小数据类别 allowlist 与端点/模型配置（不提交或打印密钥），核对确定性 `CHAPTER_MAP`/TM 键，先通过现有契约检查，再运行受控单话真实 Provider 翻译并人工验收。配置缺失时停留在当前 source-only 状态，不要转向其他 Provider 或 Notion。
- 当前代码/文档工作区按 `git status --short --branch`：分支 `codex/translation-workflow-20261115`，HEAD `c3f313b`，无暂存内容；24 个已修改跟踪文件为 `.env.example`、`README.md`、`docs/architecture.md`、`docs/decisions/README.md`、`docs/development.md`、`docs/handoffs/2026-11-15-translation-workflow.md`、`docs/knowledge-governance.md`、`docs/model-provider-configuration-plan.md`、`docs/project-status.md`、`docs/roadmap.md`、`docs/security-notes.md`、`docs/source-ingestion-and-publication-plan.md`、`docs/translation-workflow.md`、`epub_builder.py`、`pipeline.py`、`scripts/auto_extract_knowledge.py`、`scripts/build_epub_candidate.py`、`source_ingestion.py`、`tests/test_e2e.py`、`tests/test_epub_builder.py`、`tests/test_knowledge_extraction_unit.py`、`tests/test_local_source_ingestion_cli.py`、`tests/test_pipeline_contracts.py`、`utils.py`；5 个未跟踪文件为 `kakuyomu_page_source.py`、`scripts/ingest_kakuyomu_pages.py`、`scripts/run_kakuyomu_workflow.py`、`tests/test_kakuyomu_page_source.py`、`tests/test_kakuyomu_workflow.py`。均保持原样，不暂存、不提交、不清理或重置；忽略目录中的原文/译文不纳入 Git。
- 额度状态不可见，未判断剩余额度阈值。以上状态可供后续 Codex 直接续接，无需重新调查已完成的目录发现、采集、I3 导出或 U+3000 修复。
