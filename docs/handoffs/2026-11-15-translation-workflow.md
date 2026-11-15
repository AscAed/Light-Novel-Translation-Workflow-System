# 翻译工作流续接交接

> 状态基准：2026-11-15。目标仍在进行；额度信息不可见，未判断是否触及额度阈值。本交接记录当前任务边界和验证，不代表路线图阶段整体完成。

## 目标与会话

- 目标：整理翻译工作流文档体系、计划、阶段状态和实施记录，并按阶段实施当前可安全完成的工作。
- 已读取两个引用会话的当前可访问历史分页；本轮两次 `read_thread` 均返回 `hasMore=false`：
  - `thread://01a1d41d-9f87-74b1-9589-421496c452ed`：文档体系目标、AI 优先的信息组织、当前日译中范围、明确事实/计划/未知及避免重复维护的要求。
  - `thread://01a1d5a2-a18a-7381-b24a-82fc4d5d4894`：路线图评估、分阶段实施要求，以及 Provider 配置、Agent 角色和 15 项用户决策。
- 当前权威资料：`README.md`、`docs/project-status.md`、`docs/architecture.md`、`docs/translation-workflow.md`、`docs/knowledge-governance.md`、`docs/development.md`、`docs/roadmap.md`、`docs/decisions/README.md`、`docs/model-provider-configuration-plan.md`、`docs/source-ingestion-and-publication-plan.md`。
- `.agents/` 与旧 handoff 是历史材料；状态以当前代码、测试、路线图和开发验证记录为准。
- 用户于 2026-11-15 再次明确指定试点书籍已获得授权；按已授权处理，后续不得把作品权利列为阻塞。该确认不替代平台自动化访问规则，也不推定公开分发或 Provider/Notion 接收方与数据类别已获授权；本轮实施没有把作品权利作为前置条件。

## 当前状态与决策

- 检查基线：分支 `main`，HEAD `d7e2afd`；开始续接前工作区已有 7 份 Markdown 修改。该批修改未被重置或覆盖。
- 本轮新增的实现差异：`source_ingestion.py` 拒绝通用 adapter 的零章节终页及零章节 complete checkpoint，同时允许带后续 cursor 的空中间页；`scripts/ingest_local_sources.py` 在创建 adapter 或输出前拒绝空 `episodes` catalog。显式本地导入增加默认 JSON catalog 文件 16 MiB、单 episode 16 MiB、单批 episode 源文件合计 1 GiB 的可调上限；catalog 按上限 + 1 字节有界读取，episode 快照流式累计并在归档读取时二次限制，episode 字节上限绑定 source_fingerprint。另新增无默认值的 `--max-archive-bytes`，按 manifest 登记的所有文件型 artifact 历史版本累计内容字节；逐话先预检 metadata/raw 新版本，超限不追加当前话，checkpoint 标记 `archive_limit` 并绑定额度，调额度需新 checkpoint 路径。CLI 单章/批次超限仍在创建 manifest/checkpoint 前拒绝。累计内容上限不包括 manifest/checkpoint、文件系统开销、未登记孤儿文件或之后由其他工具新增的内容，不能称为物理磁盘配额。对应测试覆盖空边界、各类输入超限、历史版本计数、额度绑定、暂停和幂等。
- 指定试点作品已由用户于 2026-11-14 和 2026-11-15 明确确认为获得授权；按已授权处理，不再列为阻塞。此确认不扩大到公开分发，也不替代平台自动化访问规则或 Provider、Notion 接收方及数据类别边界。
- 2026-11-15 复查 Kakuyomu 官方利用规约第 5、12–14 条及 `robots.txt`：规则页面显示 2025-08-06 更新，robots 仍禁止匹配 episode `/read` 的爬虫路径；未访问作品/章节 URL。平台自动化访问路径仍未确定，作品授权不是该事项的阻塞原因。
- 当前可用输入仍不足：2026-11-15 只读目录清点显示用户指定原文/译文根目录均为空；仓库忽略项目下的 `生肉/`、`熟肉/` 也均为空，7 个 EPUB 工具/配置文件位于同级 `EPUB/` 目录。相邻工作区未发现章节文件。没有读取作品正文；2026-11-14 的 48/19/19 文件数是历史快照，不能用于当前映射。
- I1 来源 manifest 与 I2 无网络 adapter/本地导入 CLI 已有合成原型；I2 尚无 HTTP/HTML 站点 adapter，也未接入翻译流水线。CLI 与核心空目录 fail-closed 已补齐。I3 提供按显式作品/章节 ID 物化单话 UTF-8 `.md` 的字节保真基线、显式章节集合合并，以及完整 checkpoint catalog 模式。当前 checkpoint v5 记录每话完成时绑定的 raw 版本；完整模式核对当前 JSON 记录的发现/完成 ID 顺序、manifest 绑定及 raw 版本新鲜度，以 `\n\n` 分隔并产出不可变 `export`，父节点记录所有 normalized 版本。checkpoint 未签名且可编辑，因此这里只能确认当前所列条目可导出，不能证明 checkpoint 未被改写或外部平台枚举穷尽；也不做格式清洗、差异映射或 `CHAPTER_MAP` 生成。旧 v3/v4 checkpoint 若已有完成章节，因为缺少 raw 版本绑定而拒绝迁移。I4 已把可选的 `CHAPTER_MAP.source_version_id` 接入翻译、对齐、知识候选来源和 TM 只读审计；新增 `scripts/validate_knowledge_provenance.py` 只读核验知识候选来源版本新鲜度。TM 与知识候选审计均可报告旧来源 `stale`，但不持久化/传播译文或知识过期状态。TM 审计现分别校验 manifest 原始字节哈希和文本 I/O 哈希，覆盖 CRLF 保真材料。D-11 现有逐章恢复日志：先排他写入含章节/源文/译文/TM 基线摘要的日志，再提交译文和 TM；重跑会验证当前映射、来源、输出、门禁及 TM 状态后恢复。日志明文保存完整译文、单条上限 64 MiB；冲突时停止并保留日志供人工处理。该机制覆盖单写入者的进程中断重试，不承诺多进程协调、断电持久性或自动冲突合并。具体真实作品映射仍无法建立，原因是本轮检查到的输入目录没有章节文件，不是作品权利未授权。
- 仍独立未决/待验证：Kakuyomu 符合现行规则的自动化访问方式；各 Provider 的具体数据类别授权与真实端点/质量；Notion 目标、权限及备份类别；凭据轮换状态；真实章节的路径配对和 TM 键；D-11 多进程/断电保证及冲突人工处置、知识审核闭环、EPUBCheck/真实章节/阅读器验收；真正限制物理占用的磁盘配额及未来网络 adapter 的流式大小限制。指定试点作品授权已确认，不属于未决项。

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

1. **先定位当前试点章节文件。** 由用户提供或指出原文和译文实际文件位置；验收为文件清单与逐话配对可读、未读取/复制正文到日志，并有人工确认的 `raw_file`、`translation_file`、`tm_key`。不要用旧库存计数或文件名推测映射。
2. **再运行本地 I2 导入。** 在隔离的显式 source/output 根目录建立非空 catalog；先用合成 fixture 运行 `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -v`，再以获准的本地章节输入运行 CLI。验收为仅归档 catalog 指定文件、默认或显式单章/批次/清单内容上限生效、输出路径不别名源文件、checkpoint 可复核且重复运行行为通过验证。作品授权已确认；仍须遵守平台访问规则。物理磁盘配额和网络响应流限制仍不属于本次实现。
3. **分渠道推进 I0。** 记录符合平台规则的访问方式；核对 Provider 名称/端点及其原文、译文、知识、评测类别范围；对 Notion 单独核实目标和备份类别。作品授权不再重复作为前置阻塞。
4. **继续 I3/I4 与阶段 2。** I3 现在支持完整 checkpoint catalog 导出，但平台级目录枚举是否穷尽仍无证据；还需来源完整性证明、真实样本转换规则和段落差异映射。当前没有真实章节可据实定义站点转换，先等待用户定位或提供可用章节；不得从空目录或想象中的页面结构推导清洗规则。I4 的 TM 与知识候选来源版本绑定和只读新鲜度审计已由合成 fixtures 验证；剩余包括译文/知识的持久过期标记与传播。抽取器已有前三章/每章 16 MiB/提示词 20,000 字符的本地上限；下一步若继续抽取预算，应设计 tokenizer token 预算、全书范围估算与超限分批，不要把字符数视为 token 保证。阶段 2 的术语和概要本地审核发布原型已实现；概要 Markdown 兼容路径未受审核门禁。接下来优先处理人物知识/TM 门禁、风险分层/升级、更正/废弃及审核者身份/证据可信度策略。真实 AI 审核调用须先核对对应 Provider 数据类别授权。
5. **实际样本收口。** 文档链接/锚点和 `git diff --check` 已通过；简化 slug 检查不是完整 CommonMark/GitHub 渲染器。真实章节目录重新核对仍为空，格式转换、差异映射和第一话人工映射仍待可用文件及人工核定。
6. **I5 candidate 后续验收。** 当前 Pandoc `3.9.0.2` 仅在本机和合成文本上验证。获得已确认映射的真实译文章节后，先补齐显式 catalog 并运行 `tests.test_epub_builder`；随后在目标环境核对 Pandoc 安装来源，选择 EPUBCheck 并执行文本往返/特殊字符检查，再记录 Calibre、Apple Books、Thorium Reader 版本和实际阅读器验收。candidate 仍不得描述为完整书籍或质量门禁通过。

TM 审核补充：本轮已完成可选审核快照原型；后续应先确定审核者可信度和风险分级策略，再评估是否将门禁设为默认。指定作品权利已确认，不是这项工作的阻塞；平台访问规则、Provider/Notion 数据范围仍各自核验。

I5 补充：合成输入可以验证 builder 和 Pandoc 调用，但真实原文/译文目录当前为空。待用户定位真实译文章节后，先人工确认映射并生成显式 catalog，再做 EPUBCheck 和目标阅读器验收；不得把 `candidate` 或有限 XML/ZIP 检查提升为成品验收。

## 工作区与提交记录

- 开始时分支为 `main`、HEAD 为 `d7e2afd`，已有 7 份 Markdown 修改。未重置、清理或覆盖这些修改；其后续实现和文档一并纳入明确的任务提交。
- 2026-11-15 已创建分支 `codex/translation-workflow-20261115`，首个任务提交为 `c6f7176`（45 个文件，新增 8,513 行、删除 309 行）。提交范围限于本 handoff 前文列出的翻译工作流实现、对应测试和项目文档；未包含忽略的书籍数据或凭据文件。
- `c6f7176` 完成后更新了 README、项目现状、路线图、决策索引、来源专题计划及本 handoff 的基线与目录事实；这些仅 Markdown 的同步正在形成后续提交。
- 本 handoff 记录的是 PR 创建前的状态快照；推送、PR 审查与合并状态以任务结束时的 GitHub 查询和最终汇报为准。
