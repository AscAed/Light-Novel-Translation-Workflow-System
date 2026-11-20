# 开发与验证

本文件按阶段追加验证记录；较靠前的增量优先于其后较早日期的历史快照，旧记录中的“下一步”不自动代表当前未完成状态。

## 2026-11-21 PR #71 安全与恢复缺陷修复

- 基线：分支 `codex/translation-workflow-audit-20261117`，起始 HEAD `80eb1be033cc2dbed81975c48f5a5c03832df401`。保留既有未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json`；未读取或改动试点原文、译文、bundle、API profile、凭据或 freshness 快照。
- `已实现` `pipeline.py` 的非正式兼容模式现在同时检查 `OUTPUT_DIR` 和 `CHAPTER_MAP` 中每个映射译文目标，拒绝将文件写进项目 `熟肉/` 或显式配置的正式发布目录；工作区根下的 sibling drafts 仍允许。路径按现有映射处理时的实际解析位置比较。
- `已实现` 正式 run 不再把共享 TM 中的孤立 `tm_key` 视为当前 run 已有译文。仅当本 run 的 Drafts 目标文件存在但其来源/TM 不匹配时继续 fail-closed；只有 TM 旧键且当前输出缺失时允许重新翻译，由既有逐章事务在成功提交时替换该键。章节知识预检也不会因孤立 TM 项而跳过 reviewed chapter knowledge。该行为保留其他 run 目录中的草稿，但未独立归档没有对应输出文件的旧 TM 词对。
- `已实现` `pipeline.py` 在事务恢复后遇到既有失败阶段报告时，验证 run/episode 身份并追加一次 `recovered` 尝试；既有成功或恢复记录不重复追加，失败尝试保留。`translation_plan_approval.py::write_new_json` 改用同目录临时文件完整写入、flush/fsync 后 create-only 链接发布，写入异常不暴露半截目标文件。
- `已复核` PR #71 其余活动线程所指代码当前已有相应保护：规范化来源过期异常被单独归为 `stale`；source/edition manifest 相同路径在导出前拒绝；续跑时已核验发布章节从执行 map 排除；checkpoint 路径与摘要参与 bundle snapshot 身份；loader 要求 bundle episode 集合与当前已验证索引一致；显式 schema-v3 catalog 的 work metadata 会传入归档。上述为本地实现复核，不是本轮新增修复。
- `已验证` 定向命令 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_kakuyomu_workflow tests.test_translation_plan_approval -q`：181 项通过；新增覆盖映射发布目标拦截、sibling draft 放行、孤立 TM 可续跑、知识预检不信任孤立 TM、失败后恢复报告幂等及 JSON create-only 写入中断。
- `已验证` 全部非 E2E 测试 776 项运行、772 项通过、4 项 Windows 能力跳过、0 失败（158.895 秒）；`.venv\Scripts\python.exe tests\run_tests.py` 的 loopback mock E2E 为 7 项通过（402.149 秒，runner 退出码 0）；`py_compile` 与 `git diff --check` 通过。E2E 输出中的 content-filter 与段落对齐异常来自预期负向 fixture。mock 未连接真实 Provider。
- `部分实现` 新 run 重译时，如果共享 TM 键存在而本 run 没有对应输出，成功事务会替换该键；没有版本化 TM 历史/多写入者协调。工作区中已有上一 run Drafts 的不变文件不受影响；孤立旧 TM 词对若无其他副本可能被新候选覆盖，正式发布仍以审核 TM 快照为检索来源。
- `未验证` 真实 Provider/API profile、语义质量、K5 88 话映射及双版本人工审批、reviewed 全书知识、真实试译和部署仍未完成；本地 CLI 仓库仍无 CI、锁文件或部署清单。当前没有由本地测试证明的已知失败，但以上人工、外部服务和部署门禁不因此关闭。

## 2026-11-21 PR #71 批量发布 bundle 校验优化

- 基线：分支 `codex/translation-workflow-audit-20261117`，起始提交 `86ea78a5d5888e04ef470187cb15d0f38ee951cd`。保留既有未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json`，未读取/改写试点小说正文、人读/AI合集、API profile、凭据或 freshness 快照。
- `已实现` `translation_review.py` 将 run 所绑定的 bundle-set 与 AI book bundle 内容校验提取为独立步骤。批量发布的 review/snapshot 输入通过批次级 verifier 复用一次校验结果，仍对每话重新核对当前 AI 索引和来源；批次结束后、更新 run 状态前再次核验整书 bundle，以发现批次期间的变更。单话 `publish_reviewed_translation()` 默认完整校验行为不变。
- `已验证` 在现有 16 MiB 以上 bundle 测试中增加批次调用次数断言：两次 episode 输入只进行一次整书校验；批尾变更 bundle 后，第二次完整校验拒绝该快照。原单项测试通过；`tests.test_translation_review`、`tests.test_translation_review_state`、`tests.test_kakuyomu_workflow`、`tests.test_pipeline_contracts` 共 271 项通过；完整非 E2E 动态回归 772 项运行、768 项通过、4 项 Windows 能力跳过、0 失败；`.venv\Scripts\python.exe tests\run_tests.py` 的 loopback mock E2E 7 项通过（367.555 秒，runner 退出码 0）。`py_compile` 和 `git diff --check` 通过。mock/合成测试未连接真实 Provider。
- `已复核` 当前代码已使用 bundle 聚合大小上限，而非 16 MiB run manifest 上限；对应 `test_review_input_accepts_bundle_larger_than_run_manifest_limit` 覆盖超限场景。当前 Kakuyomu 与通用项目映射使用相同 `source-edition:` TM key；tokenizer loader 调用 `no_truncation()`；正式 Kakuyomu run 强制启用 reviewed glossary；已发布章节会从待执行章节映射中排除。以上为当前代码路径复核，不是本轮各自的独立新修复。
- `部分实现` 尚无真实 88 话 bundle 批量发布的耗时/IO 基准。批次级复用只覆盖 bundle-set 与整书 AI bundle 内容哈希，不减少逐话来源核验，也不提供目录句柄级并发替换保护；单话操作仍会按原路径重复校验。
- `未验证` 真实 Provider、试点译文质量、K5 88 话映射/双版本审阅及计划回执、reviewed 全书知识、实际部署仍未完成；本仓库仍是本地 CLI，无 CI/依赖锁/部署清单。此增量不关闭这些门禁。

## 2026-11-20 依赖更新后复验

- 基线：分支 `codex/translation-workflow-audit-20261117`、HEAD `6b18579f8d3cf03b23095dcea771a589d727de50`。环境调整不改源码、依赖清单或项目数据；仅更新仓库忽略的 `.venv`。
- `已验证` `requirements.txt` 五项直接依赖都有源码或测试调用点，没有找到可安全删除的直接依赖。`uv pip install --python .venv\Scripts\python.exe --upgrade -r requirements.txt` 更新了已落后版本：`google-genai` 3.3.0 → 3.6.1、`numpy` 2.5.4 → 2.5.5、`openai` 3.50.0 → 3.57.0，以及 `filelock`、`httpcore2`、`httpx2`、`pydantic`、`pydantic-core` 五项传递依赖。升级仅作用于本机 `.venv`，没有新增或删除项目依赖声明。
- `已验证` 升级后 `.venv\Scripts\python.exe -m pip check` 为 `No broken requirements found`；全部非 E2E 动态发现 772 项运行、768 项通过、4 项 Windows 能力跳过、0 失败。依赖漏洞检查通过临时 `uvx --from pip-audit pip-audit --path .venv\Lib\site-packages` 执行，报告 `No known vulnerabilities found`；这仅覆盖本次虚拟环境和可获取的公告数据。
- `已验证` 当前普通权限下 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v` 运行 11 项、7 项通过、4 项跳过、0 失败。3 项符号链接测试因 `WinError 1314` 无创建权限而跳过，1 项 FIFO 测试因 Windows 不支持 `os.mkfifo` 而跳过。用户提供 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 的结果是 9 项、3 项跳过，但没有关联 SHA 或逐项跳过原因，按独立用户报告保留，不能与本次计数合并。
- `已验证` 按用户授权使用管理员 PowerShell 在当前 HEAD 重跑同一安全路径模块：11 项运行、10 项通过、1 项因 Windows 不支持 FIFO 跳过；3 项符号链接测试均已执行并通过。
- `已验证` 依赖更新后 `.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 运行 7 项、368.550 秒、退出码 0。输出中的内容过滤异常堆栈来自预期负向 fixture；没有真实 Provider 请求。
- `未验证` 更新后 `pip list --outdated` 仅列出安装工具 `pip` 26.2.1→26.3 和 Google SDK 传递依赖 `tenacity` 9.1.4→9.2.1；本轮未为追逐补丁版本继续升级它们。`requirements.txt` 未锁定版本，因此虚拟环境升级不形成可复现锁定；没有发现必须删改依赖声明的证据。真实 Provider、端点/模型兼容性、费用、质量和部署不由本地 mock/单元测试或依赖漏洞扫描证明。

## 2026-11-20 PR #71 审查跟进与完整回归

- 基线：分支 `codex/translation-workflow-audit-20261117`、提交 `9374fa79376c13f72f06f1e7764d732012b1436a`；在既有混合工作树上继续处理审查问题。未读取或改动书籍正文、受保护 freshness JSON、本机 API profile 或凭据。
- `已实现` 修复本轮确认的决策/仲裁链一致性校验、跨进程快照读取竞态、空锁文件初始化、评估路由区分和历史发布的章节级来源身份校验；CLI 人工仲裁要求绑定审核者实际审阅的决定摘要。AI 返工续接持锁期间改用无锁内部快照读取，避免重入同一文件锁。正式 Kakuyomu 运行强制启用 reviewed glossary 门禁；模型预检在配置了 API 池回退时不错误要求永远不可达的 Gemini 路由。
- `已验证` 定向回归：`tests.test_translation_review_state` 44 项、`tests.test_translation_review` 69 项、`tests.test_pipeline_contracts` 142 项、`tests.test_kakuyomu_workflow` 16 项通过；四组共 271 项。完整非 E2E 动态发现运行 772 项，768 项通过、4 项跳过、0 失败。普通权限路径安全模块为 11 项运行、7 项通过、4 项跳过；获准管理员 PowerShell 重跑后 11 项运行、10 项通过、1 项因 Windows 不支持 FIFO 跳过，三个符号链接用例均实际执行并通过。
- `已验证` `.venv\Scripts\python.exe -m pip check` 返回 `No broken requirements found`；`compileall` 覆盖 `pipeline.py`、`rag_engine.py`、`utils.py`、来源模块、`scripts/` 和 `tests/`；README、AGENTS.md 与 `docs/` 下 16 份 Markdown 的本地链接目标均存在；`git diff --check` 通过。该次检查确认五项 `requirements.txt` 依赖均有代码或测试调用点，且当时未发现足以支持删除依赖的证据；依赖未锁定，也未做在线漏洞公告扫描。依赖版本后续状态见本文顶部“依赖更新后复验”。
- `已实现` 完整 mock E2E 首次运行发现既有 Kakuyomu 正式流程 fixture 仍把草稿词表当正式输入，触发新增 reviewed glossary 门禁并失败。保持门禁不变，将该测试改为指向 reviewed 文件，并构造只含合成术语、绑定当前 fixture source identity 的审核 bundle。
- `已验证` 修正后的端到端单项 `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 通过（1 项，6.653 秒）；完整 `.venv\Scripts\python.exe tests\run_tests.py` 通过（7 项，384.596 秒，runner 退出码 0）。runner 输出中的 content-filter 和段落数量错配堆栈来自预期负向 fixture；没有真实 Provider 请求。mock E2E 不代表真实 Provider、模型质量或部署验收。
- `未验证` 仓库仍没有 CI 工作流、依赖锁文件、容器或部署清单；应用交付形态是本地 CLI。真实 Provider 连通性、API profile/凭据、语义质量、全书 88 话人工映射/双版本审核与正式部署仍未验证。完整测试不会替代 K5 人工审批和凭据所有者的单话试译验收。

## 2026-11-20 K4 AI workflow CLI contract

- `已验证` 新增 `tests/test_ai_translation_workflow_cli.py`，直接覆盖用户入口 `scripts/run_ai_translation_workflow.py::main`：配置加载与两条 Provider 静态预检的顺序、工作流参数转发、成功 JSON 输出；终审或返工路由预检失败时返回非零、不启动工作流，且错误详情不输出到终端。测试使用 mock，不读取凭据、不连接 Provider。
- `已验证` `tests/test_translation_review.py::TranslationReviewTests::test_workflow_cli_runs_review_rework_and_publication_end_to_end` 从 CLI 入口实际执行活动 run 草稿的双评估失败、findings 段落返工、双评估通过及 create-only 发布；只将模型响应和 Provider 静态预检替换为合成桩。另有 CLI 预检成功/失败单测。
- `已验证` CLI、该端到端合成用例与 I4 provenance/freshness 定向回归 `.venv\Scripts\python.exe -m unittest tests.test_ai_translation_workflow_cli tests.test_source_pipeline_linkage tests.test_tm_provenance_unit tests.test_downstream_freshness_snapshot tests.test_translation_review.TranslationReviewTests.test_workflow_cli_runs_review_rework_and_publication_end_to_end -q`：40 项通过。CLI 与测试 `py_compile` 通过。
- `已验证` PowerShell 动态发现并运行全部非 E2E 模块（排除 runner 专用 `test_e2e.py`）：764 项运行、760 项通过、4 项因 Windows symlink/FIFO 能力跳过，0 失败。随后 `.venv\Scripts\python.exe tests\run_tests.py` 的 loopback mock E2E 为 7 项通过（212.461 秒，退出码 0）；输出中 content-filter 和段落错配 trace 来自预期负向 fixture。
- `未验证` 未调用真实 Provider、未对真实译文做质量验收，也没有部署验证。当前 K5 仍需有权限的人完成 88 话映射/双版本审阅和匹配计划回执、审核当前 bundle 绑定的全书知识；之后由凭据所有者核验 Provider 授权、路由和预算并执行获准单话试译。

## 2026-11-20 I4 manifest-bound TM lineage

- `已实现` `scripts/validate_tm_provenance.py::audit_translation_memory` 在配置来源 manifest 时，将缺少 `source_version_id` 的 TM provenance 标为 `unverified`。没有 manifest 的旧式兼容审计仍可按来源/译文字节与段落映射验证；AI edition source map 不匹配仍按原逻辑报告 `mismatch`。
- `已验证` 新增 direct audit 与 hash-bound freshness snapshot 回归：manifest-bound 旧 TM 不会被报告为 fully verified，快照只记录状态，原 TM 字节保持不变。定向命令 `.venv\Scripts\python.exe -m unittest tests.test_source_pipeline_linkage tests.test_tm_provenance_unit tests.test_downstream_freshness_snapshot -q` 为 36 项通过；编排/采集集成命令 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_workflow tests.test_kakuyomu_page_source tests.test_source_ingestion -q` 为 93 项通过。
- `已验证` 完整非 E2E 动态发现运行 760 项、756 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py` 的 loopback mock E2E 7 项通过（206.248 秒，退出码 0）。mock 的 content-filter 与段落错配日志来自预期负向 fixture；未调用真实 Provider 或试点正文。
- `部分实现` 本增量不回写 TM/译文，不自动重建派生物；manifest-bound 其他消费者仍由各自现有来源门禁校验。I4 持久消费者状态传播和自动重建未验收。

## 2026-11-20 当前工作树回归复核

- 基线：分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；在既有混合工作树上复核，未改代码、项目数据、来源/译文、API profile、凭据或受保护 freshness JSON。
- 定向回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state tests.test_pipeline_contracts tests.test_api_pool -q`：269 项通过。完整非 E2E 动态发现（`tests/test_*.py`，排除 runner 专用 `test_e2e.py`）：758 项运行、754 项通过、4 项因 Windows symlink/FIFO 能力跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过，208.149 秒，退出码 0。输出中的 content-filter 与段落数量错误来自预期负向 fixture；未调用真实 Provider，也未运行试点正文。`git diff --check` 通过。
- 阶段状态不变：K4 本地合成实现和回归通过；K5 仍待有权限的人完成 88 话映射/双版本审阅及匹配计划回执、审核当前 bundle 绑定的全书知识，再由凭据所有者核验 Provider 配置/授权/预算并执行受控首话和人工质量验收。应用为 CLI，无部署服务。

## 2026-11-20 K5 试点门禁复核

- 基线：分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；只读验证，没有改动项目数据、来源/译文、API profile、凭据或受保护 freshness JSON。
- 当前计划 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.json` 仍为 `ready_for_review`，88 话、88 个来源有效、0 issues，摘要 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。按计划自身绑定的 `source_catalog.raw-html-2026-11-17.json`、manifest、AI edition root 和译文根运行 `scripts/run_kakuyomu_workflow.py --plan-only`，返回相同 plan digest、88/88 来源、0 issues/目标冲突、0 网络请求/Provider 调用/文件写入，`source_text_included=false`。误用 `source_catalog.discovered.json` 会得到 `stale_ai_edition_catalog:88`；该 catalog 不同于当前计划和 AI 索引绑定的 catalog，不应替换计划输入。
- `scripts/validate_source_editions.py` 对同一 catalog、当前 source/edition manifests、AI root 和配置的人读 root 返回 `verified`：88 话；读取源 793,183 bytes，AI 输出 774,253 bytes，人读输出 799,293 bytes。验证器只读并逐话按当前 profile 重算、比对镜像与归档；这证明字节/版本一致性，不证明语义保真或人类阅读体验。
- 当前人审模板与计划摘要、AI 索引 SHA-256、人读索引 SHA-256 均匹配；`mapping_decision`、`ai_edition_decision`、`human_edition_decision` 各 `pending:88`。`Workflow/Approvals/` 与 `Knowledge/STORY_SUMMARY_reviewed.json` 均不存在。没有产生审批回执、知识产物或译文；未调用真实 Provider。
- 下一步需要有权限的人审阅既有 88 话模板及双版本，并通过 `scripts/approve_translation_plan.py` 生成匹配回执；之后才可审核/生成当前 bundle 绑定的全书概要与术语。以上门槛完成后，再由凭据所有者核验端点授权/路由/预算，开展获准单话 Provider 试译和人工质量验收。用户已确认作品授权和职责所需数据类别，不应重复列为待确认项。

## 2026-11-20 用户确认的原文抽样核实

- `用户报告` 用户已抽查人类版 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 与 AI 版 `projects\祝福のネトラレラ\RAWs_AI\chapters\` 中的部分单话文件及大合集文件，均未发现明显问题。AI 版大合集对象路径为 `projects\祝福のネトラレラ\RAWs_AI\collections\1eeeb07b599ea6f676e1bd5ec7b9d03a1af9134f47d7ea1c0a08299403d5437d\a18583594b3596270b8655c7c5e6534daab686d3a47defa1fb6f0e1ea7740f27\book-ai.json`。
- 以上是用户提供的核实结论；本次没有独立读取附件或复查抽样文件。抽样清单、检查标准、全量覆盖、逐段语义保真及阅读器显示仍未验证；该结论不替代 88 话映射与双版本的结构化人工验收。`book-ai.json` 在本记录中仅为核实对象，不是仓库指令或实现证据。

## 2026-11-20 K4 终审逐次评估持久化

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；本轮在既有混合工作区上增量修改，未读取或改动受保护 freshness JSON、小说正文、本机 API profile 或凭据，也未暂存、提交、重置或清理。
- `已实现` `ai_translation_review.py` 在每次结构化评估通过验证后，将规范化结果以原子 create-only sidecar 写入 run 内 `AIReviews/<episode_id>/`。记录绑定 run/work/episode、source 版本与摘要、candidate 版本/路径/摘要、policy 摘要、reviewer route 摘要及评估序号；仅包含 verdict、登记 issue code、段落索引和检查结果，不保存模型自由文本或章节正文。
- `已实现` 重试会先校验并复用已落盘的单次评估，再请求尚缺评估；两份评估齐全后仍生成原 schema 报告、决定和发布物，旧报告与决策恢复格式不变。错配、非法或超限 sidecar 会失败关闭；没有数据库迁移。
- `已验证` 新增经父进程认证的进程终止测试：第一份 sidecar 原子落盘后、第二次评估响应前终止子进程；恢复只调用评估 2，完成发布，第二次重开文件字节稳定。另验证篡改 sidecar 身份会在调用 Provider 前拒绝。两个新增用例及原终审/状态模块共 106 项通过；完整非 E2E 动态发现 758 项运行、754 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py` 的 loopback mock E2E 7 项通过（216.520 秒，退出码 0）。均使用合成 assessor，未调用真实 Provider。
- 恢复剩余窗口：Provider 已返回但对应 sidecar 尚未原子落盘时进程终止，重试仍可能重复该次请求及费用；无 Provider 幂等键时本地无法消除此窗口。该检查点证明指定用户态进程终止恢复，不证明断电或介质持久性。
- 回滚边界：不迁移数据库、不改写报告/决策/候选/译文/TM；评估 sidecar 是 run 内追加证据，回滚代码时须保留。旧实现可能忽略这些新文件，但不能据此删除它们。
- `已验证` `.venv\Scripts\python.exe -m py_compile ai_translation_review.py tests\test_translation_review.py`、活动 Markdown 本地目标检查与 `git diff --check` 通过。E2E 中 content filter 与段落错配堆栈来自预期负向 fixture。
- 下一步：K4 本地合成恢复阶段已验证。整体试点仍须有权限的人类完成 88 话计划/双版本审批和 reviewed 全书知识，再由凭据所有者核验 Provider 授权/预算并执行获准单话试译及人工质量验收。

## 2026-11-20 K4 AI 返工续审工作流

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。在已有混合实现和文档改动上增量工作；受保护 freshness JSON、书籍正文、本机 API profile/凭据均未读取，未暂存、提交、重置或清理。
- `已实现` 新增 `scripts/run_ai_translation_workflow.py` 与 `ai_translation_workflow.py`，对一话显式执行或从已有决策继续执行终审、有限返工、复审及通过后发布。不会被初译 pipeline 后台触发。若已有 `passed` 决定，重跑走审核器已有恢复路径，不重复调用 reviewer；已生成的下一候选按摘要校验后复用。
- `已实现` `ai_translation_rework.py` 只接受 AI reviewer schema v4 的 `quality_failure`/`rework`，或 `rework_limit_reached` 且存在匹配的人工 `increase_budget` resolution。策略、来源、当前候选、AI 报告、决策摘要和阻断 findings 均重验；不能从 `approve_current` 人工放行状态启动 AI 返工。
- `已实现` 修订请求将完整 source/candidate、阻断 findings、对应策略定义和逐段可编辑标记发送给 `PROOFREAD_MODEL`，source 与 candidate 合计最多 64,000 字符。类别仅为 `source_text`、`translation_text`，不发送 `book_knowledge`。解析器拒绝重复 JSON 字段、未知字段、未覆盖/重复/非目标段落、非单段输出和非法字符；仅替换命中段落并保留未命中原字符与分段隔符，再复核候选字节上限及既有译文格式契约。
- `已实现` 终审与返工路由必须规范化 endpoint/model 身份不同；CLI 请求前校验终审授权、返工角色配置/授权及路由。候选 create-only 保存到 `ReviewCandidates/<episode_id>/revision-NNNN.md`；sidecar `AIReworks/<episode_id>/revision-NNNN.json` 只保存内容/决策/策略/报告/findings/路由摘要和生成来源，不保存小说正文。若候选已存在但 sidecar 缺失，只记录 `reused_existing`，不声称它由 AI 生成。
- `已实现` 单话终审、返工和完整工作流共享 `AIWorkflowLocks/<sha256(episode_id)>.lock` 异步文件锁；同一事件循环内等待时使用异步轮询，不阻塞持锁任务。锁跨进程有效，避免同一候选的并发调用重复消耗 Provider。锁位于决策目录之外；短时 decision append lock 仍负责序列化 create-only 决定和仲裁回执。
- 恢复边界：review decision episode lock 覆盖返工上下文读取、Provider await 和候选/sidecar 提交，防止同一话并行推进决策；候选和 sidecar 分别原子 create-only。进程若在 Provider 响应后、候选成功落盘前中断，远端调用可能重复且产生费用；若候选已落盘、sidecar 未落盘，重跑会按现有候选补建 `reused_existing` sidecar。尚无进程硬杀/远端响应丢失故障注入证明。
- 终审恢复边界：评估锁在进程退出时自动释放，已持久化的单次评估、报告/决定/发布快照按身份或摘要恢复。若 Provider 已返回但对应评估 sidecar 尚未落盘时中断，重试可能重复该次请求并重复计费；该剩余窗口见本文件顶部 `2026-11-20 K4 终审逐次评估持久化`。
- `已验证` `test_ai_pass_recovers_after_publication_snapshot_write_failure` 在快照写失败后重跑并恢复；另有两个认证检查点进程终止测试：快照写入前，以及发布审核快照/回执已存在但 run 状态仍为 running、尚未 reconciliation 时。父进程先核验检查点、passed 决策、报告/决定摘要、审核记录、译文和已有发布物，再终止子进程；新调用通过真实 episode 文件锁续跑，不重复调用 reviewer、不追加决定、不重写已有发布物，并完成 run 状态。两次重开后的 run/发布文件字节稳定。它们证明指定用户态进程终止窗口，不证明内核崩溃、断电或介质持久性。
- `已实现` 预算耗尽后的人工 `increase_budget` 回执成功结果现在返回 `new_max_rework_attempts`；新增跨模块恢复用例验证该值与下一版决策预算一致，并验证恢复后的自动复审发布路径。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state tests.test_pipeline_contracts tests.test_api_pool -q`：267 项通过。内含 13 项新增工作流用例（hash-bound rework/review/publish、候选恢复复用、预算扩展不可绕过、人工扩额后续接至发布、非法响应拒绝、严格段落边界、并发终审复用、并发完整工作流、跨进程互斥、进程退出后锁恢复、快照写失败恢复、快照前进程终止恢复及回执落盘后 run 状态更新前进程终止恢复）及向导 reviewer/rework route 分离验证；未调用真实 Provider。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_api_pool -q`：23 项通过；`scripts/run_ai_translation_workflow.py --help` 与本轮相关 Python `py_compile` 均通过。完整非 E2E 动态发现运行 756 项、752 项通过、4 项因普通 Windows symlink/FIFO 能力跳过；未发现失败。`.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 最近一次为 7 项通过，203.287 秒，退出码 0；本轮只改测试和文档，未重跑 runner。content filter/段落错配输出来自预期负向 fixture。10 份相关 Markdown 的 285 个本地链接目标存在，`git diff --check` 通过。
- 回滚边界：不迁移数据库、不改写草稿/旧候选/决策/译文/TM；新运行时只在活动 run 下 create-only 增加候选及报告，发布仍由旧门禁执行。回滚代码时必须保留 `AIReworks/` 与候选；缺少本代码的旧版本无法解释 sidecar，也可能不能理解当前策略/决策 schema。
- 下一步：K4 的本地合成回归已完成。若进入真实试点，先由人类完成 88 话映射/双版本与计划审批、reviewed 全书知识审核；再由凭据所有者安全检查 Provider 端点、授权、预算和模型路由，选择获准单话运行 CLI，并对 AI 修订、终审结果和正式产物做人工质量验收。当前没有 Web 服务或部署目标。

## 2026-11-20 K4 AI 终审执行器

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作区已有混合代码/文档修改和未跟踪文件；本轮在其上增量工作，保留受保护 freshness JSON、项目原文、API profile 和凭据。本轮未读取这些数据，未暂存、提交、重置或清理。
- `已实现` `ai_translation_review.py` 与 `scripts/review_translation_candidate.py` 提供显式单话终审。初审只接受 run 中已核验 `Drafts/`；续审必须使用 run 内版本化 `ReviewCandidates/<episode_id>/`。要求策略 schema v1，绑定 run、话目、source version/hash、候选版本/路径/hash、策略 hash 和 reviewer route hash。
- `已实现` 每次评审顺序请求两次 `FINAL_REVIEW_MODEL`，同一不可变候选；严格 JSON 解码拒绝重复键、非有限值、额外字段、未登记 code 和越界段落索引。原文与译文逐段数需相同；合并文本上限默认为 64,000 字符，超限时不截断、不发送。模型输出不允许自由文本解释；仅将阶段 verdict、登记 code 和段落索引持久化。
- `已实现` “信 > 达 > 雅”落实为 fidelity/fluency/style 三阶段均 pass 的必要条件。每次还须将八个既有 publication checks 全部判 pass，且两次 optimization potential 均为 `none` 或 `low`；最终条件以决策 schema v4 的 `final_review_gate` 绑定策略文件。冲突/不确定、收敛 gate 不足或预算耗尽均不发布并转 `needs_human`；明确失败且预算仍有余量返回 `rework`。CLI 结果返回内容无关的 issue code、段落索引及 run-relative 报告路径，供后续查看，不返回正文引文。
- `已实现` 只有 schema v4 决定状态为 `passed` 才创建候选绑定 AI publication snapshot，并复用 `publish_reviewed_translation` 的现有来源、候选、八项检查、create-only 产物及 run 状态核验。审核报告按候选/策略内容寻址并只增写；既有通过决定可校验报告后幂等恢复发布，避免重复调用模型。若模型评审中途失败，未完成的双评估不会生成决定；之后重试需重新完成两次请求。
- 返工预算在 AI 终审入口默认 2，可在初审用 `--max-rework-attempts` 覆盖；续审必须与既有链预算一致，预算耗尽后须先走人工 resolution。`rework` 只写审核/决定状态，不生成修订译文；新候选的生成器、使用 findings 的修订 prompt 和调用预算尚未实现。AI 审核及自动发布只会被显式 CLI 调用，不在初译流程中后台自动触发。
- 风险边界：每个评估请求都会将完整 source 和 candidate 发给配置 reviewer；虽校验要求全部三类授权，当前 prompt 不含 book knowledge。两个评估走相同 route，不能证明统计或语义独立；`none`/`low` 只作为用户收敛方向的定性代理，不计算边际收益，不证明翻译正确。issue code 定义由操作者维护，不是项目核准 taxonomy；reviewer 标识是摘要声明，未认证。
- `已验证` `.venv\\Scripts\\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state -q`：91 项通过。合成用例覆盖双次通过并发布、既有通过恢复不重调模型、存储报告篡改拒绝、失败原因摘要返回且不发布、评审分歧/收敛不足/零预算转人工、重复 JSON 字段拒绝和审阅期间 run 草稿改变拒绝。测试注入 assessor，不访问真实 Provider；不包含真实质量样本。
- `已验证` CLI `--help` 可解析项目/run/episode/policy/candidate/字符预算/返工预算参数。PowerShell 动态发现并排除 runner 专用 `test_e2e.py`：740 项运行、736 项通过、4 项因当前 Windows symlink/FIFO 能力跳过；`.venv\\Scripts\\python.exe tests\\run_tests.py`：mock E2E 7 项通过，212.673 秒，退出码 0。E2E 负例中的内容拦截/段落错配日志为预期。`py_compile`、CLI help、10 份相关 Markdown 的 274 个本地链接目标和 `git diff --check` 通过。
- 回滚边界：不改写候选草稿、原译文、TM 或旧决策；报告、政策副本、schema v4 决定和自动生成 checklist 均是 run 内 create-only 产物。代码回滚时须保留这些文件；旧代码不具备 v4 链消费能力，禁止删除或降级重写审阅数据。无需数据库迁移。没有可部署服务，不执行项目真文 Provider 调用。
- 下一步：K4 执行器合成验证和当前全量回归已完成。若继续 K4，先定义自动返工候选写入/不可覆盖、修订输入/输出契约、预算/故障恢复与跨话目 taxonomy 范围，再接生成模型。正式试点前必须完成人工 88 话双版本/计划审批、reviewed 全书知识、本机 API profile 与权限检查，以及由操作者显式触发的真实单话 Provider/人工质量验收。

## 2026-11-20 API 池可选终审角色

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。在已有混合工作树上增量修改；保留全部既有更改和未跟踪项，未读取受保护 freshness JSON、试点正文、本机 API profile 或凭据；未暂存、提交、重置或清理。
- `已实现` `scripts/configure_api_pool.py` 可跳过或配置可选 `FINAL_REVIEW_MODEL`。配置时要求与 `INITIAL_MODEL` 的规范化端点及实际模型 ID 均不同；向导在读取 Key 前告知并确认 reviewer 可能接收 `source_text`、`translation_text`、`book_knowledge`。激活不含 reviewer 的 API 池会清除旧 `FINAL_REVIEW_MODEL`，避免同进程误用残留路由。
- `已实现` `api_pool_store.py` 写入含 reviewer 绑定的 schema v3；原三角色 profile 继续写 v2。v1/v2 读取与 v1 显式迁移到 v2 保持兼容，v2/v3 embedding 字段均可读取。profile 校验要求终审全类别授权，并拒绝与初译相同的 endpoint/model 身份；凭据仍只保存在 Windows Credential Manager，配置摘要绑定逻辑不变。
- `已实现` `pipeline.py` 暴露独立 `validate_final_review_provider_configuration()`，校验 reviewer 路由、与初译路由的区分、数据授权、远端 Key 及当前配置的回退授权；普通翻译 preflight 不要求配置终审，也不会因此触发审核。`Config.load_config` 将未配置角色重置为 `None`。不同 endpoint/model 只是路由分离，不证明模型语义独立。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_api_pool -q`：22 项通过。`.venv\Scripts\python.exe -m unittest tests.test_api_pool tests.test_pipeline_contracts tests.test_kakuyomu_workflow -q`：176 项通过。全量非 E2E 动态发现运行 730 项、726 项通过、4 项因 Windows symlink/FIFO 能力跳过、0 失败。`.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，205.929 秒，退出码 0；其中失败日志来自预期负向夹具。相关文件 `py_compile`、9 份 Markdown 相对链接目标与 `git diff --check` 均通过；链接检查不校验锚点。
- 本阶段不调用 reviewer、不写审核决定、不影响发布门禁，也未连接真实 Provider 或启动服务。未读取真实 profile，未迁移本机配置。旧 profile 不受影响；若未来已保存 v3 profile 后回滚代码，必须保留 v3 读取能力或先显式导出兼容配置，不能直接降级/覆盖 profile。
- 下一步：当前执行器已连接既有候选版本/决策链与发布门禁。若继续 K4，先明确自动返工候选写入、修订输入/输出、失败恢复和真实 taxonomy 范围，再接生成模型；真实试点还须完成人工前置验收并记录 Provider 执行证据。

## 2026-11-20 K4 策略文件绑定

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。本轮在已有混合工作树上增量修改；未读取书籍正文、本机 API profile、凭据或受保护 freshness JSON；未暂存、提交、重置或清理。
- `已实现` 决策 CLI 增加可选 `--review-policy-file <JSON>`。schema v1 策略登记表包含 `policy_id`、正整数 `revision` 和 issue entries；每个 entry 提供稳定 code、允许的审核阶段及由策略维护者撰写的定义。拒绝重复 JSON 字段/code、未知字段、无效阶段、非 UTF-8/非有限 JSON 和超 128 KiB 文件。
- `已实现` CLI 的 `--stage-verdicts` 与 `--stage-issue-codes` 使用严格 JSON 解析；任意对象层级出现重复字段或非有限数值（`NaN`/`Infinity`）均在调用决策写入器前拒绝，避免同名阶段或 issue code 被 JSON 解码器静默覆盖。
- `已实现` 提供策略文件时，程序以其原始字节计算 SHA-256；可省略 `--policy-sha256`，若同时提供则必须匹配。写入 run 的 `ReviewPolicies/<sha256>.json`，采用排他原子写入且复用时要求字节完全一致。决策改用 schema v3，哈希绑定该相对路径、策略摘要和阶段 issue codes；每次读取决策链、续接和发布前均重新核验策略文件摘要与 code 的阶段归属。v3 链后续每条决定都必须继续提供相同策略文件；v1/v2 数据仍可读取，v1/v2 链可进入 v3，但已存在的 v2 codes 也必须符合被绑定的策略。
- `已实现` 不提供策略文件时保留 schema v2 与既有不透明 `policy_sha256` 兼容入口。该兼容路径不验证策略内容。策略登记表只定义 issue 标识和适用阶段；不增加 severity、自动处置或跨话目豁免语义。重复 code 仍不会自动放行或跳过人工暂停。
- CLI 示例：

```powershell
.\.venv\Scripts\python.exe scripts\record_translation_review_decision.py `
  --run-directory <run> --episode-id <episode> `
  --reviewer <reviewer> --reviewed-at-utc <UTC> `
  --review-policy-file <policy.json> `
  --reviewed-candidate-sha256 <sha256> `
  --stage-verdicts <JSON> --stage-issue-codes <JSON>
```

- 策略文件形状示例（code 含义由操作者撰写，本例不构成项目质量标准）：

```json
{
  "schema_version": 1,
  "policy_id": "operator-review",
  "revision": 1,
  "issue_codes": [
    {
      "code": "operator_defined_issue",
      "stages": ["fidelity"],
      "definition": "Definition supplied by the policy owner."
    }
  ]
}
```

- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：81 项通过。覆盖策略文件校验/摘要、原子只增归档、阶段归属、篡改拒绝、v1/v2 兼容与续接、CLI 参数、重复字段/非有限数值拒绝和审核发布集成。
- `已验证` PowerShell 动态发现 `tests/test_*.py` 并排除 runner 专用 `test_e2e.py`：727 项运行、723 项通过、4 项因 Windows symlink/FIFO 能力跳过，0 失败；`.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，209.005 秒，退出码 0。E2E 输出中的 content filter 与 paragraph mismatch 错误是预期负向夹具；没有真实 Provider 请求。
- `已验证` 相关 Python 文件 `py_compile`、`record_translation_review_decision.py --help` 的策略参数、6 份修改文档的本地链接目标及 `git diff --check` 均通过。
- 回滚边界：只在 run 内新增内容寻址策略文件与 schema v3 决定；不改写候选、译文、TM 或旧审核记录。回滚代码会失去 v3 链读取/发布能力，必须保留策略文件和决定数据，不得删除或降级改写。
- 下一步（该策略绑定阶段交付时）：在明确的审核规则和授权样本基础上定义真实 taxonomy、冲突/不确定处置及跨话目作用范围；当前 reviewer 执行器和自动发布路径见本文件首节。真实语义判定、reviewer 身份及试点质量仍未验证。

## 2026-11-20 K4 结构化 issue code

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。保留工作树中已有的 API/embedding、K4 及受保护未跟踪文件；未读取 freshness JSON、书籍正文、本机 API profile 或凭据；未暂存、提交、重置或清理。
- `已实现` 新决策记录使用 schema v2，在 `issue_codes_by_stage` 按 fidelity/fluency/style 保存 reviewer 显式提供的内容无关标识；这些字段随决策摘要一起哈希。旧 schema v1 决策仍可独立读取，也可作为现有决策链前缀继续接入 v2 记录。
- `已实现` 校验只检查三阶段映射完整、标识符合小写 snake_case 格式且不重复；fail verdict 至少要有一个标识，纯 pass 阶段不得带失败标识。标识集合及语义未固化为代码枚举；调用方需在受控策略材料中定义这些 code，并自行保证策略材料与 `policy_sha256` 一致。记录只哈希保存该摘要和 code 值，本程序不读取/验证策略材料，也不推断 issue code。
- `已实现` `scripts/record_translation_review_decision.py` 新增可选 `--stage-issue-codes <JSON>`。记录 fail 时必须提供失败阶段的 code；全通过记录可省略该参数。该入口保持 Provider-independent，不读取或请求 API 池。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：72 项通过。覆盖缺失/无效/重复代码拒绝、哈希绑定、v1 读取和 v1→v2 决策链续接、CLI 参数解析及现有仲裁/发布集成。
- `已验证` PowerShell 动态发现 `tests/test_*.py` 并排除 runner 专用 `test_e2e.py`：718 项运行，714 项通过、4 项因 Windows symlink/FIFO 能力跳过，0 失败；`.venv\Scripts\python.exe tests\run_tests.py`：mock E2E 7 项通过，227.490 秒，退出码 0。E2E 的内容过滤和段落不匹配堆栈来自预期负向 fixture，没有真实 Provider 请求。
- `已验证` 相关模块 `py_compile`、`scripts/record_translation_review_decision.py --help` 的 `--stage-issue-codes` 显示、`scripts/resolve_translation_review.py --help`、`git diff --check` 均通过。
- 回滚边界：新记录只追加到既有 `ReviewDecisions/<episode_id>/`，不改写旧记录、候选、译文或 TM。回滚代码会失去 v2 记录读取能力；不得删除既有决策数据。完整非 E2E 与 mock E2E 回归已通过，详见本节验证记录。
- 限制与下一步：issue code 目前是受格式约束的策略标签，不是已核准的共享 taxonomy；没有 code registry、语义审计或跨话目豁免策略，重复 code 不会自动放行或跳过人工暂停。后续仍需定义 taxonomy 版本、词汇来源、跨话目适用范围与撤回规则；当前 AI reviewer 执行器已实现，语义质量未验证。

## 2026-11-20 K4 人工仲裁与返工预算

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。继续保留已有未提交/未跟踪修改；未读取受保护 freshness JSON、试点正文、本机 API 池或凭据；未暂存、提交、重置或清理。
- `已实现` 新决策链初始最大返工次数默认 2，可由 `--max-rework-attempts` 配置。预算耗尽后，新增 `scripts/resolve_translation_review.py`：`approve_current` 写入独立、create-only、哈希绑定当前 run/话目/来源/候选/失败阶段/决策摘要及理由的人工仲裁回执；它不改写原有失败 verdict。匹配回执只解锁绑定该候选的 schema v3 人工 checklist，发布仍需独立 checklist 全部通过。
- `已实现` 仲裁动作 `increase_budget` 只可在 `rework_limit_reached` 后严格增加预算；后续决定必须从已绑定候选创建新修订、沿用同一策略摘要并使用新预算。扩预算和人工放行均保留旧记录；决策与仲裁追加共享话目锁并采用原子 create-only 写入。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：64 项通过，包含默认两次、保留失败 verdict 的人工放行、schema v3 发布/回执绑定、耗尽后扩预算续接及严格增量校验。
- `已验证` PowerShell 动态发现 `tests/test_*.py` 并排除 `test_e2e.py`：710 项运行、706 项通过、4 项因普通 Windows symlink/FIFO 能力跳过，0 失败。
- `已验证` `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，244.256 秒，退出码 0。打印的失败堆栈对应测试中的内容过滤/格式负例；无真实 Provider 请求。
- `已验证` `py_compile` 覆盖 `translation_review_state.py`、`translation_review.py` 及两个相关 CLI 和测试文件；两个 CLI `--help` 均正常；`git diff --check` 通过。以上为本地合成验证，不调用 Provider 或读取项目正文。
- 边界：仲裁记录的 reviewer 是本地声明，不认证账户或身份；schema v3 checklist 仍需人工完成。现有阶段 verdict 只有 fidelity/fluency/style 三类，缺少可安全复用的细粒度 issue taxonomy，因此“同类失败在后续其他话目自动免暂停”尚未接入；不能将一次人工放行静默扩展为宽泛的信/达/雅豁免。AI reviewer 执行器现有合成验证，终审阈值/自适应收益计算、真实 Provider 质量和试点验收仍未验证。
- 回滚：只新增 `ReviewResolutions/<episode_id>/` 回执；保留原决策链及候选，不改译文、TM 或既有审核产物。回滚代码会移除对仲裁/schema v3 的消费能力，但既有 schema v1/v2 行为保持；不得删除运行中生成的回执或候选。
- 下一步：为细粒度同类 issue 定义可审计分类及其作用范围，并设计自动返工候选契约；之后在获准配置、88 话映射/双版本验收和 reviewed 知识就绪后，开展受控 Provider 试点。

## 2026-11-20 API 池 v2 与可配置 embedding

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树原有未提交/未跟踪内容继续保留；未读取受保护的 freshness JSON、试点正文、本机 API 池文件或任何凭据值；未暂存、提交、重置或清理。
- `已实现` `api_pool_store.py` 新保存 schema v2：保留生成池与职责绑定，增加可选独立 embedding Provider；Google GenAI 配置固定 Provider `gemini`，或配置经现有 URL 校验器检查的 OpenAI-compatible endpoint/model。Key 仅写入 Windows Credential Manager，profile 存引用和授权类别，凭据绑定完整 profile 摘要。
- `已实现` v1 profile 仍可只读加载。向导检测到 v1 后须明确确认才升级；迁移先验证旧配置和 Credential Manager 绑定，创建内容不含 Key 的 v1 备份，再以新凭据引用和新摘要原子替换。旧凭据引用不自动删除；写入或替换失败会清理本次新凭据，旧 profile 保持不变。迁移失败后的 v1 备份保留。迁移成功后的自动反向恢复 CLI 尚未提供，可由操作者将备份恢复到 profile 路径后继续用旧版代码。
- `已实现` `scripts/configure_api_pool.py` 可在生成配置之外选择是否单独配置 Gemini 或 OpenAI-compatible embedding，并先确认该 Provider 对 `source_text` 的授权再索取 Key。激活时清除陈旧 embedding 环境变量，并将 embedding 授权与生成池授权合并；未配置时不授权远端 embedding，按现有拒绝策略关闭该请求。
- `已实现` `embedding_provider.py` 为 RAG、TM 写入和章节对齐共享适配器；OpenAI-compatible 响应按 `index` 重排并校验数量、索引、有限向量和维度。Gemini 默认向量身份保持 schema 1；OpenAI-compatible schema 2 另含 endpoint SHA-256，防止相同维度但不同模型、Provider 或端点的向量混用。身份不匹配的旧向量仍保留，不自动重建。
- `已实现` `scripts/rebuild_tm_embeddings.py` 可按所有 TM 章节或重复 `--chapter` 选择生成新候选，不改写源 TM 或已审核快照。生成前后都核验所选 pair 的来源/译文 provenance、来源 manifest 和源 TM 摘要；Provider 失败、输入变化或输出文件冲突时不发布候选。`configure_api_pool.py --rebuild-tm-embeddings` 复用同一 profile、Key 与 `source_text` 授权入口。候选仍须由 `scripts/apply_tm_review.py` 生成人工回执并发布 reviewed snapshot；操作者随后显式设置 `TM_REVIEWED_PATH`，切换和回退不覆盖既有 TM/快照。
- `已验证` 定向 `.venv\Scripts\python.exe -m unittest tests.test_api_pool tests.test_embedding_provider_unit tests.test_rag_engine_unit tests.test_align_chapters_unit tests.test_tm_review tests.test_pipeline_contracts -q`：235 项通过。
- `已验证` 完整非 E2E 测试动态发现（`tests/test_*.py`，排除 runner 专用 `test_e2e.py`）：704 项运行、700 项通过、4 项因普通 Windows 权限不支持创建 symlink/FIFO 跳过。
- `已验证` `.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过，239.655 秒，runner 退出码 0。内容拦截与段落不匹配堆栈来自预期负向 fixture；没有真实外网或 Provider 请求。
- `已验证` 修改 Python 文件 `py_compile` 和 `git diff --check` 通过。迁移使用临时 profile 与合成凭据存储；OpenAI SDK 另对本机 loopback HTTP fixture 请求 `/v1/embeddings`，验证 Bearer Key、模型/输入、`encoding_format=float` 和响应解析。该 fixture 不是对任何真实 Provider 的兼容性证明。
- `未验证` 当前用户本机 v1 profile 是否存在或已迁移；本轮未读取它。Gemini/OpenAI-compatible 真实 API、渠道模型能力、费用、时延和语义质量未验证；候选重建只使用合成 TM 测试，本机试点 TM 未重嵌入或切换。当前项目仍为 CLI，没有 Web 服务或部署目标。
- 回滚：迁移在替换前失败时旧 profile 和旧 Credential Manager refs 保持有效；成功后 v1 备份与旧 refs 保留。若需用旧程序回退，先保留 v2 profile，再将备份恢复到原 profile 路径；禁止删除旧凭据或 TM。代码回退会失去 v2 加载和新的 endpoint 身份隔离行为。
- 下一步：由操作者运行 `.\.venv\Scripts\python.exe scripts\configure_api_pool.py --rebuild-tm-embeddings -- --project <项目> [--chapter <TM键>]`，确认是否加载/迁移实际 profile 并授权 embedding 接收 `source_text`；候选写入现有 TM 同目录但使用独立文件名。用 `scripts/apply_tm_review.py` 为候选创建并完成逐对人工回执，再发布 reviewed snapshot；核对后才显式将 `TM_REVIEWED_PATH` 指向新快照，保留旧值以便回退。真实端点验收、试点 88 话人工映射/双版本审批、reviewed 全书知识和 K4 AI 终审策略/自动 reviewer 仍未完成。

## 2026-11-20 Gemini embedding 与 TM 向量身份

> 阶段快照：本节记录 API 池 embedding 配置接入前的基础适配器状态；当前配置/迁移状态见本页上方“API 池 v2 与可配置 embedding”。

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树含此前及本轮未提交修改，均予以保留；受保护的未跟踪 freshness JSON 未读取或修改，没有暂存、提交、重置或清理。
- `已实现` 新增 `embedding_provider.py`，统一 RAG 与章节对齐调用 Gemini Embedding 2 的批处理、授权预检、超时、响应数量/数值/维度校验及身份描述。TM 向量记录新增 `embedding_identity`，包含 schema、Provider、协议、模型、task type 和维度；RAG 新写入及 `scripts/align_chapters.py` 写入使用同一身份格式。
- `已实现` TM 检索及章节语义回退只使用身份字段完整且与当前 Gemini Provider/模型/维度完全匹配的向量。缺身份或身份不匹配的旧向量仍保留在 TM 和审核快照中，但不混入向量计算；它们需经显式对齐/重建后才能重新参与检索。没有自动重嵌入或修改项目 TM 数据。
- `已实现` 前一增量的 RAG 失败关闭保持有效：有兼容候选但查询 embedding 失败时抛出不含原始异常正文的错误；TM 更新任一 embedding 失败会整体中止，不写部分 TM。章节事务日志保留待提交状态，合成恢复测试确认重试仅恢复 TM 提交、不重复翻译。无兼容候选时返回空检索是旧向量隔离的预期状态，不等同于一次成功语义命中。
- `部分实现` TM 查询和更新的 embedding 错误按上述规则停止/保留事务；指南的语义回退仍沿用既有策略，在 embedding 失败或没有兼容章节向量时选择距离最近章节的指导。该结果是位置回退，不是语义匹配；尚未把它改成停止翻译或给调用方提供显式降级状态。
- `已验证` 定向 `.venv\Scripts\python.exe -m unittest tests.test_rag_engine_unit tests.test_align_chapters_unit tests.test_tm_review -q`：64 项通过，覆盖旧向量隔离、模型/维度身份差异、TM 新身份写入、Gemini 请求超时/批次响应、审核快照查询和对齐器身份写入。
- `已验证` 全量非 E2E 动态发现并排除 runner 专用 `test_e2e.py`：682 项运行，678 项通过、4 项跳过、0 项失败。3 项符号链接用例因普通 Windows 进程缺少 `WinError 1314` 能力跳过；1 项 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- `已验证` `.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过，235.372 秒，runner 退出码 0。测试日志中的内容拦截和段落数不匹配轨迹来自预期负向 fixture。
- `.venv\Scripts\python.exe -m py_compile embedding_provider.py rag_engine.py scripts\align_chapters.py tests\test_rag_engine_unit.py tests\test_align_chapters_unit.py tests\test_tm_review.py` 与 `git diff --check`：通过。未调用外网、真实 Provider 或部署服务；未读取项目原文。
- `未完成` API 池尚未配置 embedding Provider，当前共享适配器仍固定 Gemini；版本化 API 池配置迁移、Provider/端点/model revision 的未来身份扩展、已存 TM 向量重建和真实渠道兼容性仍待实现/验证。旧向量隔离会使依赖它们的 reviewed TM 暂时没有向量命中；这是有意的安全降级，不代表 TM 已重建完成。
- 回滚边界：新增 TM 字段是附加字段，旧读取代码可忽略；代码回滚不需数据格式迁移，但回滚后会丢失旧向量隔离及请求/身份统一行为。不要为回滚删除或覆盖现有 TM；继续使用时可通过现有 `scripts/align_chapters.py` 显式重建相应映射。
- 下一步：先设计并验证 API 池 v1 到新版本的原子迁移/凭据回滚契约，再把独立 embedding Provider 配置接入共享适配器；制定旧 TM 显式重建、核验和切换流程。所有合成服务通过后才考虑操作者明确触发的获准端点诊断。试点计划/知识审批、独立终审策略和真实 Provider 试译仍是独立前置条件。

## 2026-11-20 API 池配置阶段验证（R4 前快照）

- 当前验证基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；实现仍是未提交工作树。工作树包含既有来源未归属的修改和未跟踪文件，全部保留；受保护的本地 freshness JSON 未读取或修改，未暂存、提交、重置或清理。
- `部分实现` API 池向导现按当前调用映射显示三个生成职责：初译用 `INITIAL_MODEL`；上下文标注、校对和知识抽取用 `PROOFREAD_MODEL`；润色用 `STYLE_MODEL`。只为实际分配的主/备用端点索取 Key；激活时清除陈旧池 Key 环境变量。未分配的端点不会保存 Key。知识抽取继续只使用主校对模型。
- `已实现` 持久化现在先写入随机引用凭据，再原子替换配置文件；凭据写入或配置替换失败时，只删除本次已成功写入的新引用，并尽力删除临时文件。若回收失败，会报错提示检查凭据管理器；旧配置和旧凭据不作为回滚目标。
- `已验证` `tests.test_api_pool`：11 项通过，新增覆盖凭据写入中断时回收先前新写引用、配置替换失败时保留旧文件/回收新引用/移除暂存文件，以及清理失败时给出人工检查提示；`.venv\Scripts\python.exe -m unittest tests.test_api_pool tests.test_pipeline_contracts tests.test_kakuyomu_workflow -q`：164 项通过。集成还覆盖职责 alias 经 `Config.load_config` 进入流水线校验、未使用端点排除、活动端点 Key、陈旧环境变量清理及授权预检。
- `已验证` 当前工作树全部非 E2E 测试（动态发现 `tests/test_*.py` 并排除 runner 专用 `test_e2e.py`）：677 项运行，673 项通过、4 项跳过、0 项失败。3 项符号链接测试因普通进程的 Windows `WinError 1314` 能力限制跳过，1 项 FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。此计数对应上述未提交工作树，不替代提升权限验证。
- `已验证` `.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过，238.966 秒，退出码 0。runner 输出的 `PIPELINE RUN FAILED` 来自预期内容拦截和段落数不匹配负向夹具。没有访问外网、真实 Provider 或项目原文。
- 修改文件的 `py_compile` 与 `git diff --check` 通过。未启动服务；当前交付仍是 CLI 入口，不存在可供访问的 Web 服务。
- `未验证` 端点和模型 ID 兼容性、真实计费/延迟/质量、密钥库跨账户迁移、清理本身失败时的孤儿凭据恢复、API 池 embedding 配置、旧向量重建，以及真实试点译文和部署。此段记录的是 R4 实施前快照；RAG/对齐共享适配器及身份隔离的最新状态见[Gemini embedding 与 TM 向量身份](#2026-11-20-gemini-embedding-与-tm-向量身份)。
- 后续仍需确定版本化配置迁移与凭据回滚契约、embedding Provider 配置、向量身份扩展和旧 TM 显式重建/核验。不可据此绕过仍未完成的计划、知识与发布门禁。

## 2026-11-19 审核决定并发与人读版身份绑定修复

- `已实现` 审核决定按话目使用跨进程 append lock；链读取、连续修订/父摘要校验和 create-only JSON 发布在锁内完成。决定 JSON 先完整写入临时文件并 fsync，再通过硬链接原子创建；`.append.lock` 不计入链记录。
- `已实现` 决定链读取会忽略本工具中断后残留的隐藏 `.tmp` 暂存文件，但仍拒绝符号链接、非普通暂存项和其他未知目录项；因此进程中断不会把未完成暂存误当作决定记录。
- `已实现` `record_translation_review_decision` 和对应 CLI 要求调用方传入审阅时取得的候选 `reviewed_candidate_sha256`；程序重新读取候选后才生成决定记录，候选在审阅期间被替换时失败关闭。
- `已实现` 计划审阅逐话验证人读版 artifact ID、版本 ID、归档相对路径、文件摘要、父版本及清洗类型，均须与已验证 edition manifest 和 AI 版来源一致。
- `已实现` 正式译文发布的缺失目标统一经过 create-or-compare 原子写入；并发写入相同字节可复用，冲突字节拒绝，回执/快照不会为未发布的内容登记成功。
- 定向回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review tests.test_translation_plan_approval -q`：77 项通过。
- 关联工作流回归 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_kakuyomu_workflow tests.test_knowledge_extraction_unit tests.test_source_editions tests.test_source_pipeline_linkage tests.test_source_ingestion tests.test_translation_plan_approval tests.test_translation_review_state tests.test_translation_review -q`：347 项通过。
- 本轮完整非 E2E 动态回归（排除 `test_e2e.py`）运行 666 项、662 项通过、4 项跳过、0 项失败；3 项符号链接用例因普通进程缺少 `WinError 1314` 权限跳过，1 项 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- 本轮 `.venv\Scripts\python.exe tests\run_tests.py` 本地 loopback mock E2E 运行 7 项、全部通过，201.455 秒，退出码 0；内容拦截、认证失败、段落错配和损坏 TM 等负向输出是预期 fixture。
- `py_compile` 覆盖本次修改的生产/测试模块，`git diff --check`：通过。真实 Provider、人工审批、线上部署仍未验证。
- `未优化` 审核发布批处理仍可能在每话重复读取并摘要整本 AI bundle；这不改变完整性校验，但在大 bundle/多话 run 上会增加 I/O，后续可在单次批量校验范围内复用已验证 bundle 身份。

## 2026-11-19 返工发布续跑完整性修复

- `已实现` `write_review_decision` 在写入返工决定前，拒绝候选 SHA-256 与同话既有决定链任一候选重复；拒绝发生在文件写入前，已有决定链保持可加载。
- `已实现` 新增只读发布证明查询：仅当既有 run 的 work/episode、来源版本与 SHA-256、译文根和相对目标均匹配，且发布回执、审阅快照、最终批准候选与当前正式译文字节全部有效时，才确认该话已发布。Kakuyomu 工作流在计划标为 blocked 且译文目标已存在时，先按原 TM/provenance 规则检查；不匹配时再核验该发布证明，从而正确恢复返工候选已发布、但原始 TM 仍绑定初稿的部分计划。
- `已实现` 批量发布在可编辑审阅文件与正式译文都缺失时，可先验证发布回执、已批准审阅快照和候选摘要，再用 create-only 原子写入恢复缺失译文；目标已存在且字节不同则阻止并保留现有内容。新增回归覆盖恢复成功与冲突拒绝。
- 定向回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review tests.test_kakuyomu_workflow -q`：70 项通过，覆盖跨修订候选摘要重用拒绝、返工发布凭据与目标/来源绑定、篡改后拒绝，以及只续跑剩余话目。
- 本次修改后的定向回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review -q`：33 项通过。
- 本次修改后的非 E2E 回归：PowerShell 动态发现全部 `test_*.py` 并排除 `test_e2e.py`，663 项运行、659 项通过、4 项跳过、0 项失败。普通权限进程下 3 项符号链接用例因 `WinError 1314` 跳过，1 项 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- 获准提权后单独复跑 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、10 项通过、1 项 FIFO 能力跳过；3 项符号链接用例均实际执行并通过。该提升权限结果只覆盖安全路径模块，不与普通权限的全量回归合并计数。
- 本次修改后的 `.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过，200.376 秒，退出码 0。runner 同时打印的拦截与段落数异常来自预期负向 fixture；没有调用真实 Provider 或线上服务。
- 本次修改后的 `.venv\Scripts\python.exe -m py_compile translation_review.py tests\test_translation_review.py` 与 `git diff --check`：通过。试点书籍文件未被本轮修改。
- 验证边界：以上自动测试使用合成数据或本地 mock，不能替代试点人类/AI 原文的全量人工验收、真实 Provider 试译或部署验证；用户报告的单话与合集抽样结论另见[抽样核实记录](#2026-11-19-人类版与-ai-版原文抽样核实)。

## 2026-11-19 当前工作树回归与来源边界修复

- `已实现` 有版本来源的空 AI 章节现在通过 `commit_chapter_translation` 原子提交空译文、零段 TM 和来源 provenance；正式 run 写入仅含摘要的 `source_validation`/`commit` 阶段记录。重复运行会核验输出与 TM 后跳过，不再留下无 TM 证明的空文件。
- `已实现` `FetchedEpisode` 携带响应字符集；Kakuyomu adapter 将 charset 名规范化并在 episode metadata 中保存。metadata 作为 `raw_page_html` 的父版本，使 charset 随来源版本绑定；归档回放按该值解码，原始 HTML 响应字节仍原样保存。旧 metadata 缺少 `page_charset` 时按 UTF-8 兼容。
- `已实现` AI 索引复核现在读取索引绑定的 catalog 路径并比较当前 SHA-256、作品 ID 与逐话 ID/标题/位置；catalog 同路径被改动、重排或删项时，计划预览保留 `stale_ai_edition_catalog` 分类，导出与审校发布均失败关闭。
- 定向回归 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_kakuyomu_page_source tests.test_source_ingestion tests.test_kakuyomu_html_archive -q`：224 项通过，覆盖空章节提交/续跑、声明为 Shift_JIS 的响应解析与归档回放、旧 UTF-8 metadata 兼容。
- AI catalog 快照与发布相关定向回归 `.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_book_bundles tests.test_kakuyomu_translation_plan tests.test_translation_review -q`：85 项通过，覆盖同路径 catalog 变更、重排、删项及计划错误分类。
- 本节原记录的完整非 E2E 回归为早前工作树快照；本次代码修复后的最新计数及权限分项见[返工发布续跑完整性修复](#2026-11-19-返工发布续跑完整性修复)。
- 本节原记录的 mock E2E 与来源回放为早前工作树快照；本次代码修复后的最新 runner 结果见[返工发布续跑完整性修复](#2026-11-19-返工发布续跑完整性修复)。
- 试点 `SourceArchive` 的 HTML 回放 validator 以当前实现只读重验：88/88 页面、356 个 manifest 文件哈希有效、HTML 4,814,835 bytes、回放正文 793,183 bytes，状态 `verified`。旧档案沿用无 charset 字段时的 UTF-8 默认；没有改写试点数据。
- 非 UTF-8 响应仅由本地 Shift_JIS fixture 验证；没有重新访问 Kakuyomu、调用真实 Provider、修改试点来源数据或验证线上部署。UTF-8 以外的真实站点响应仍待 live capture 核验。

## 2026-11-19 续跑恢复与审批发布复核

- AI 版计划审批现在要求完成结构化三项审阅，并将审阅模板摘要绑定到 schema v2 回执；CLI 在缺少 `--review` 或 `--human-index` 时明确拒绝。旧 schema v1 回执只适用于未绑定 AI 版的旧计划。
- 恢复被阻断的部分发布计划时，工作流仍校验完整计划与当前 AI 索引，但已验证的正式译文不再加入待处理 `CHAPTER_MAP`；新 run manifest 仅包含剩余话目，整书摘要仍按全计划来源核验。
- 批量发布会在可编辑审阅文件缺失时复核本地审核快照、回执及正式译文；run 状态会基于降级后的实际状态重新核验。单话产物已失败时不再把同一故障重复计作 run 级失败。发布回执使用 create-only 原子写入。
- 显式 catalog 路径保留完整 catalog snapshot 元数据，合集导出校验遵循调用方提供的 AI/人读索引路径；不可变合集写入在目标创建前不会暴露部分内容。
- 后续审查修正 AI 来源边界：章节对齐只核对归档 manifest lineage 元数据，读取 `RAWs_AI` 镜像，并在 embedding 后复读镜像摘要；概要发布与可选 JSON 概要加载也绑定 AI 输入，避免从归档正文读取。定向回归 `.venv\Scripts\python.exe -m unittest tests.test_align_chapters_unit tests.test_pipeline_contracts tests.test_story_summary_review -q`：184 项通过。
- 完整非 E2E 回归：PowerShell 动态发现 `test_*.py` 并排除 `test_e2e.py`，647 项运行、643 项通过、4 项跳过、0 项失败。详细安全用例确认 3 项符号链接测试因 `WinError 1314` 缺少当前进程权限跳过；1 项 FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，244.453 秒，退出码 0。Kakuyomu 计划路径使用合成的人读索引与结构化审核模板；mock Provider 的内容拦截和段落错配属于负向测试。
- 用户于 2026-11-19 提供 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 结果：9 项运行、3 项跳过、0 项失败。`-q` 输出未列出跳过原因或 checkout SHA；该结果保留为用户报告，不与本地当前工作树的 11 项详细结果合并，也不能单独证明符号链接用例已运行。
- 本次只读复核确认人类版与 AI 版原文的抽样结果已记录于[人类版与 AI 版原文抽样核实](#2026-11-19-人类版与-ai-版原文抽样核实)；这是用户报告的部分抽查，不代表本次逐文件检查或全量内容验收。未调用真实 Provider、未批准试点 88 话映射、未生成真实译文，也未验证线上部署。

## 2026-11-19 K4 决策链接入审核发布门禁

- 决策摘要现在绑定 run-relative 候选路径。初版必须精确指向 `Drafts/<translation_file>`；返工版必须放在 `ReviewCandidates/<episode_id>/`，路径不能复用。记录只保存哈希、阶段判定和声明字段，不保存译文正文。
- `record_translation_review_decision` 续写前会重验上一候选字节；返工候选必须位于当前 run、通过路径/符号链接检查、符合现有段落/引号契约，并且内容摘要不同于父版本。返工次数与策略摘要在同一链内固定，须由调用方显式传入，没有生产默认值。
- 审核决定新增候选摘要契约：调用方必须传入审阅时取得的 `reviewed_candidate_sha256`；程序重新读取候选并在追加前比较，避免审核期间候选被替换。每个话目的决定目录使用跨进程 append lock，链校验和 create-only 原子 JSON 发布在同一锁内；锁文件不计入决定链。
- 计划审批现在把人读版每话的 `human_edition_artifact_id`、`human_edition_version_id`、`human_archive_relative_path`、父版本和文件摘要与已验证 `source_editions_manifest.json` 逐项核对，交换两个索引行的路径和摘要不会再被接受。
- 发布译文的缺失输出路径统一经过 create-or-compare 原子写入；并发创建相同字节时复用现有文件，不同字节则失败关闭后才会写入回执/快照。
- 发布路径现消费决策链：没有决策链的旧 schema v1 人工 checklist 保持兼容；存在决策链时，旧 checklist 不能绕过门禁。只有链尾 `passed` 候选可以生成 schema v2 checklist，且绑定最终修订号、路径、候选摘要和决策摘要；八项人工检查仍须全部通过、无 issues、声明独立性并填写 UTC 审核时间。
- 发布回执 schema v2 绑定最终候选和决策摘要。发布、重试与 run 完成核验会复核决策链、审核快照和候选字节，正式译文字节必须等于本次批准的最终候选；返工时原始 `Drafts/` 保持不变。`rework`、`needs_human`、候选篡改或既有输出冲突时不会写入新正式译文。
- `needs_human` 当前是终止门禁：没有同一 run 内的人类仲裁回执/恢复入口。为失败或耗尽设定可覆盖权限前，不能将人工 checklist 当作绕过方式；仲裁责任与允许结果仍需明确。
- 最大返工次数、策略摘要和阶段判定规则仍由调用方显式提供；代码没有选定终审 Provider/model、语义阈值或人工升级责任。哈希只能验证数据绑定和完整性，不能认证审核身份、策略执行或判定质量。旧人工 checklist 身份未签名认证。本增量不调用 Provider，也没有可部署的服务端或 Web 应用。
- `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：47 项通过，覆盖旧 checklist 兼容、直通/返工候选发布、链路绕过拒绝、路径约束、候选/审核快照篡改、排他发布及状态恢复。
- 门禁接入后完整回归：PowerShell 动态发现并排除 `test_e2e.py`，630 项运行、626 项通过、4 项因当前 Windows FIFO/符号链接能力跳过、0 项失败，用时 94.331 秒；`.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 7 项通过，418.613 秒，退出码 0。mock 中的 Provider 拒绝/格式异常来自预期负向 fixture，不是对真实端点的访问。
- `.venv\Scripts\python.exe -m py_compile translation_review_state.py translation_review.py scripts\record_translation_review_decision.py scripts\prepare_translation_review.py scripts\publish_reviewed_translation.py scripts\publish_reviewed_run.py tests\test_translation_review_state.py tests\test_translation_review.py`、决策脚本 `--help`、`git diff --check`：通过。无真实 Provider、Kakuyomu、Notion 请求或部署。

## 2026-11-19 试点计划映射续接核验

- 对项目 `SourceArchive/source_catalog.raw-html-2026-11-17.json` 按 `workflow_paths.json` 配置的译文根执行 provider-free `--plan-only` 预览，得到 88/88 来源有效、0 问题、`network_requests=0`、`provider_calls=0`、`filesystem_writes=0`。
- 预览与旧计划的来源版本、AI 输入路径/哈希、清洗索引/manifest、译文目标均一致；差异是 88 个 TM key 均从旧 `kakuyomu:` 命名变为当前 `source-edition:`。旧审批摘要 `331013b8...` 因映射身份变化不能沿用。
- 用 `--plan-output` create-only 新建 `projects/祝福のネトラレラ/Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.json`，摘要 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。新计划 `ready_for_review`，88/88 已验证、0 问题；`translation_plan_approval.load_translation_plan` 重算摘要一致。此次唯一文件写入是该新计划；旧计划未覆盖，未创建审批回执。
- 2026-11-19 续接时重跑 `.venv\Scripts\python.exe scripts\validate_source_editions.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.raw-html-2026-11-17.json --human-root '..\祝福のネトラレラ(祝福的寝取系女主)\生肉' --ai-root projects\祝福のネトラレラ\RAWs_AI`：`verified`、88 话；读取 raw 793,183 bytes，重算 AI 774,253 bytes、人读 799,293 bytes。验证器返回 AI index SHA-256 `09da2e6c...`、human index SHA-256 `f8ab7563...`；新计划绑定的 AI index SHA-256 与验证器一致。验证器本地读取原始来源和两版文件，不输出正文且不写文件。
- 当前 `Workflow/Approvals/` 无审批回执，`Knowledge/` 尚无 reviewed summary/glossary 产物。计划预览只验证当前映射及字节/版本绑定，不代表 88 话映射或双版本清洗已人工验收，也不代表知识语义正确。校验器在本机读取 `RAWs_AI` 字节以复算哈希；正文未显示、另存或外传。未读取密钥、未调用 Provider 或网络。
- K5 仍需人工审阅新计划与 AI/人读版、为新摘要生成匹配审批回执、审核全书概要/术语，再完成 Provider 配置与单话试点。K4 独立终审的 Provider/model、通过规则、返工上限及人工升级责任仍待用户决定。

## 2026-11-19 K5 结构化计划审阅模板

- 新增 `translation_plan_approval.create_plan_review_template` 与 `verify_plan_review_template`。模板只保存计划映射、AI/人读索引摘要、逐话文件路径/哈希和三项待审决定，不保存章节正文；创建和审批时都会按受限路径实际读取人读 Markdown 并复核其索引摘要，初始决定均为 `pending`。
- `scripts/prepare_translation_plan_review.py` 以 create-only 方式生成模板，输出必须位于 `SourceArchive/` 之外。当前试点模板为 `projects/祝福のネトラレラ/Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.human-review.json`，含 88 行、264 个待审决定。人工填写每话的 `mapping_decision`、`ai_edition_decision`、`human_edition_decision` 为 `pass` 并清空 `issues` 后，`scripts/approve_translation_plan.py --review <模板> --human-index <当前 SOURCE_MAP.json>` 才会把模板摘要写入 schema v2 审批回执。
- 验证会重算当前计划和人读索引摘要，并复核索引指向的章节文件哈希；拒绝过期映射、索引变化、缺话、文件哈希不符、字段篡改和任何未通过决定。旧 schema v1 回执仍可读取；schema v2 必须包含 `review_sha256`。回执仍是未签名的本地声明，不认证审核者身份或语义质量。
- 合成验证：`.venv\Scripts\python.exe -m unittest tests.test_translation_plan_approval -q`（15 项）和 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_workflow -q`（14 项）通过；覆盖索引伪报哈希、索引/章节变化、pending 拒绝及 CLI 生成 schema v2 回执。相关源码/脚本 `py_compile`、CLI `--help` 通过。当前试点没有生成模板或审批回执，人工审阅仍未完成。
- K5 实施时的全量非 E2E 回归动态发现 625 项，621 项通过、4 项跳过、0 项失败，用时 96.068 秒；跳过仍为 Windows FIFO 1 项和符号链接 3 项能力限制。当时的 mock E2E 未重跑；后续续接复验结果见本节末尾。
- 对当前试点计划和外部 `生肉/SOURCE_MAP.json` 的预检成功复核 88 个实际章节文件及索引摘要 `f8ab7563...`。随后 create-only 生成上述真实模板；验证器确认 264 个决定全部 pending 并以“not fully approved”拒绝审批。没有创建审批回执或输出章节正文。
- 2026-11-19 当前续接再次对既有模板执行只读验证：读取当前计划、人读 `SOURCE_MAP.json` 与其 88 个映射章节，重新构造期望模板后因 264 项仍待人工审阅而拒绝。另以随机系统临时路径运行审批 CLI 预检，退出码 1，回执文件未创建。该检查确认模板仍绑定当前索引和章节摘要，不代表人工内容审阅或计划批准。
- 2026-11-19 后续复验 `.venv\Scripts\python.exe tests\run_tests.py`：当前 checkout 的本地 mock E2E 7 项通过，337.441 秒，退出码 0。输出中的 Provider 内容过滤和段落数不匹配属于负向夹具的预期失败；测试 runner 汇总为 `OK`。这仍是合成接口验证，未调用真实 Provider、站点或部署服务。

## 2026-11-19 K4 合成审核状态转移核

- 新增 `translation_review_state.py::decide_review_transition`。它只消费 `fidelity`、`fluency`、`style` 三阶段的显式判定和调用方提供的返工次数；三阶段全部 `pass` 才返回 `passed/publishable=true`。明确失败在预算尚有余量时返回 `rework`；预算耗尽、阶段缺报、不确定或判定冲突均返回 `needs_human`。
- 新增 `create_review_decision_record` / `verify_review_decision_record`，将转移、显式预算、策略摘要、run/episode/source 身份、候选修订号和父候选/当前候选摘要绑定为可重算 SHA-256 的内容无关记录。修订号须与已用返工次数一致；初始版本不能有父摘要，返工版本须绑定不同的父候选摘要。审核者 ID 是声明，不认证身份。
- `translation_review.py::record_translation_review_decision` 和 `scripts/record_translation_review_decision.py` 可在现有 `review_pending` run 下追加 `ReviewDecisions/<episode_id>/` 记录：初版默认绑定精确的 `Drafts/<translation_file>`，返工版只能使用 `ReviewCandidates/<episode_id>/` 下 run 内候选文件；create-only 存储会验证连续修订、父摘要、候选路径、来源/策略/预算一致性和上一版 `rework` 状态。记录不复制正文。
- 最大返工次数必须由调用方显式传入，允许 `0`，没有默认值。该模块不制定评分或问题阈值，不调用 Provider，不保存译文正文；后续接入发布门禁见[决策链发布门禁](#2026-11-19-k4-决策链接入审核发布门禁)。记录摘要证明字段未被改动，不证明策略、审核者、父记录或审核质量真实。
- `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：42 项通过，覆盖状态核、链路恢复/篡改/幂等和既有人工发布器。脚本 `--help`、相关源码 `py_compile` 与 `git diff --check` 通过。未调用 Provider。
- 跨模块回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state tests.test_kakuyomu_workflow tests.test_pipeline_contracts -q`：190 项通过。随后 `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，425.782 秒，退出码 0；负向夹具的内容过滤、段落契约、鉴权和损坏 TM 日志属于预期输出。未调用真实 Provider、站点或部署服务。
- 当前完整非 E2E 动态回归（排除 `test_e2e.py`）运行 620 项，616 项通过、4 项跳过、0 项失败，用时 99.658 秒；跳过为当前 Windows 无法创建 FIFO 的 1 项和符号链接的 3 项。

## 2026-11-19 正式项目校对/反思/润色分项轨迹

- 正式 run 的既有 `StageReports` 现在把 `_run_refinement_loop` 的 `proofreading`、每次 `reflection` 和 `polishing` 分别记为尝试列表。每条只含状态、输入/输出 SHA-256、模型标识和尝试序号；校对列表另记录模型报告的 `none`/`minor`/`severe` 标签，不保存批注、原文、译文、提示词或响应正文。
- `run_chapter` 的失败记录现在标出发生异常的具体子阶段；原质量门禁、异常传播、兼容模式回退及章节提交顺序不变。该记录细分现有调用轨迹，不代表“信、达、雅”各有独立审核、评分或人工/AI 终审。
- 定向验证：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_kakuyomu_workflow -q`，180 项通过；覆盖流水线阶段契约、失败报告定位、配置恢复、RAG 门禁和 Kakuyomu 编排。
- 全量非 E2E：动态发现 `tests/test_*.py` 并排除 `test_e2e.py`，596 项运行、592 项通过、4 项跳过、0 失败，用时 47.287 秒。4 项为当前 Windows 环境无法创建 FIFO 的 1 项和符号链接的 3 项。命令：`$testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName }); .\.venv\Scripts\python.exe -m unittest @testModules -q`。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，用时 205.636 秒，退出码 0。fixture 中预期的内容过滤与段落契约负例会打印失败轨迹；runner 汇总通过。
- `.venv\Scripts\python.exe -m py_compile pipeline.py tests\test_pipeline_contracts.py` 与 `git diff --check`：通过。未调用真实 Provider、读取试点正文或部署服务。
- 本阶段只细化运行轨迹和失败定位；模型返回的 severity 不等于语义质量证明。K4 终审规则、Provider/model、返工上限及耗尽后的人工升级责任仍待用户决定，K5 真实 Provider 与人工试点验收未完成。

## 2026-11-18 正式项目翻译质量门禁

- 基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `7ea8e10`；在保留现有文档修改与受保护未跟踪索引的前提下，新增正式项目模式的局部门禁。本节记录 K3 阶段失败策略；显式 JSON/兼容入口的已知正式输出根保护见下节，其阶段回退行为仍保持兼容。
- `pipeline.py::_run_refinement_loop` 在 `REQUIRE_REVIEWED_PUBLICATION=True` 时，对无效校对 schema/段落、未解决的严重校对意见、无效反思结果及无效/不可读润色响应抛出 `TranslationQualityGateError`。`run_chapter` 在调用 `commit_chapter_translation` 前等待该阶段，因此本章输出和 TM 均不写入。provider/鉴权/传输异常仍按原异常传播，不转为回退译文。
- Kakuyomu CLI 对该专用门禁异常返回非零码并显示固定的门禁原因及计划话目位置，方便定位需要重跑的阶段；不回显文件名或输入正文。其他异常仍仅显示类型，不回显可能包含输入数据的异常正文。
- Kakuyomu 编排器不会自动把异常中的 run 标成完成或失败：未写出 `run.json` 的 run 保留 `running` 状态，操作者可用相同 `--run-id` 和同一计划重试；计划摘要改变时拒绝复用。成功写出 `run.json` 后，`run_state.json` 通过原子替换推进为 `review_pending`，与可审阅清单保持一致。流水线逐章验证并跳过已提交草稿，当前未通过质量门禁的章节没有输出/TM。CLI 对该异常返回非零状态；这不是自动重试或终审返工链。
- `run_workflow` 现在保存并恢复其显式覆盖的 `Config` 字段（包括输入/输出根、章节映射、质量门禁、run ID、bundle 和单话知识开关），覆盖早期返回、异常和成功路径；同一 Python 进程中的嵌入式调用或续跑不会继承上一次项目状态。Kakuyomu 定向测试同时断言质量门禁异常和成功续跑后的配置恢复。
- `STRICT_REFLECTION_MODE` 仍由操作者显式启用；默认不会因为进入项目模式而增加初译 Provider 的 `translation_text` 授权或额外请求。启用时沿用当前代码的两次反思重试；项目路径在预算耗尽且仍为 `severe` 时停止。该两次是既有实现细节，不构成用户已确认的最终返工次数策略。
- 本轮定向验证：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_kakuyomu_workflow -q`：178 项通过，覆盖正式项目拒绝未审核 TM 检索、run-state helper、编排续跑、review_pending 成功码、CLI 安全错误呈现和阶段报告追加/恢复/损坏保护。run-state helper 验证相同 run ID/计划可续用未完成 run、保留既有草稿，并拒绝计划摘要变化；编排测试注入一次质量门禁异常后用同一 run ID 重试，确认失败时无 `run.json`、重试成功后才生成清单；pipeline 用例覆盖失败章节不写输出/TM。
- 最新全量非 E2E：PowerShell 动态发现 `tests/test_*.py` 并排除 `test_e2e.py`，594 项运行、590 项通过、4 项因当前 Windows 符号链接/FIFO 能力跳过、0 失败，44.369 秒。此结果包含正式项目拒绝 `ALLOW_UNREVIEWED_TM=true` 的门禁用例、输出模式、阶段报告及 K4 发布产物复核/状态降级用例。命令为 `$testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName }); .\.venv\Scripts\python.exe -m unittest @testModules -q`。
- 最新完整 `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，211.406 秒，runner 退出码 0。Kakuyomu 发布链现通过批量 run 发布入口；content-filter 和段落契约异常来自预期负向 fixture。E2E 合成译文写入 `translated/`，避免将未审核测试输出命名为正式目录 `熟肉/`。
- `.venv\Scripts\python.exe -m py_compile pipeline.py translation_review.py rag_engine.py scripts\run_kakuyomu_workflow.py scripts\publish_reviewed_run.py tests\test_pipeline_contracts.py tests\test_kakuyomu_workflow.py tests\test_rag_engine_unit.py tests\test_translation_review.py tests\test_e2e.py`、`git diff --check`：通过。未调用真实 Provider、读取真实书籍正文或部署服务。
- 边界：这是基于模型提供 `severity` 的确定性流程门禁，不证明模型判断准确；尚未实现“信、达、雅”独立审核职责/语义审核报告、评分阈值、终审返工链或身份认证。当前新增的 hash-only 阶段轨迹只用于运行审计。完整验收计划见[知识库与翻译闭环实施计划](end-to-end-workflow-target.md#知识库与翻译闭环实施计划)。
- 回滚边界：该增量不改数据格式或已存数据；恢复旧兼容行为需回滚这段代码变更。不要通过关闭 `REQUIRE_REVIEWED_PUBLICATION` 回滚，因为它同时关闭项目模式其他审核与输出隔离约束。

## 2026-11-18 正式项目阶段审计报告

- `TranslationPipeline.run_chapter` 在正式项目模式成功提交章节后，或在阶段/提交异常时，向 `Workflow/Runs/<run_id>/StageReports/episode-<tm-key-sha256-prefix>.json` 原子追加一次尝试记录。报告包含 run/work/章节映射、来源版本与 AI 输入哈希，以及 `context`、`annotation`、`translation`、`proofreading_polishing`、`commit` 的状态、输入/输出 SHA-256、模型标识和有限元数据。
- 报告不保存原文、译文、提示词或模型响应正文；它是运行轨迹和失败定位证据，不是“信、达、雅”独立审核报告，也不提供语义评分或质量达标证明。`proofreading_polishing` 目前表示现有校对/润色组合阶段，不能解释为两个独立审核职责。
- 同一话目重试会保留既有 `attempts` 并追加新记录；阶段失败仍由原异常决定章节是否停止，报告写入失败只记录日志。成功提交后若报告无法持久化，正式运行返回错误并保留已写出的草稿/TM，操作者应按相同 run 继续核对和重试。
- 已提交但缺少报告的章节在后续正式续跑中只补一条 `recovered` 记录，不重新调用模型；已有报告必须匹配当前 run 和章节映射，损坏、过大或错配报告会失败关闭并保留原文件，避免静默覆盖审计证据。
- 本轮新增 `tests.test_pipeline_contracts.TestParagraphContracts.test_formal_stage_report_is_hash_only_and_attempts_are_append_only`，验证正式路径报告落点、失败/成功两次尝试、失败类型和正文不落盘。该增量仍不覆盖断电、多进程并发、独立终审或人工审核身份。

## 2026-11-18 兼容入口正式目录保护

- `TranslationPipeline` 对未审核输出强制要求 `TRANSLATION_OUTPUT_MODE="compatibility_draft"`；显式 JSON 未标记、标记非法或同时要求 reviewed publication 时失败关闭。项目加载器设置内部 `reviewed_run_draft`，Kakuyomu 编排器仅在活动 run 草稿目录中设置该模式，并由配置保护器恢复调用前状态。测试工作区使用隔离的 `test_draft`。
- `compatibility_draft` 可使用任意兼容输出路径，但明确不属于正式发布。即使标记为 draft，pipeline 仍拒绝项目默认 `熟肉/`、`workflow_paths.json` 声明的正式输出根及这些根的子目录；符号链接按解析后的目标检查。正式译文仍只能经带审核回执的 create-only 发布器创建。直接构造 `TranslationPipeline` 的 Python 调用方也必须设置兼容 draft 模式，不能只靠选择一个看起来像草稿的目录。
- JSON 迁移：旧显式配置若继续使用未审核兼容流水线，增加 `"TRANSLATION_OUTPUT_MODE": "compatibility_draft"`；项目正式 run 不添加该字段，由 Kakuyomu 编排器设置 reviewed 模式。现有显式 JSON 配置的解析/路径读取不受影响；仅直接执行未审核翻译的旧配置需要显式声明。
- 验证命令：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_kakuyomu_workflow -q`，覆盖未标记 JSON 拒绝、draft 标记通过、兼容/正式模式冲突、正式目标拒绝及 Kakuyomu run 模式恢复；本轮最新结果见下方当前验证记录。
- 回滚边界：移除模式校验会重新允许未审核调用者把任意输出目录默认为可写目标；正式目录保护仍独立生效，但不再足以证明任意输出仅作草稿。

## 2026-11-18 发布回执中断恢复测试

- 对现有逐话审核发布器做故障注入：正式译文 create-only 写入成功后，模拟 `Published/<episode_id>.json` 回执写入失败。首次调用留下与已审批草稿字节一致的目标且不留下回执；以相同 run 和审核文件重试时，发布器识别目标字节一致、不覆盖目标并补写已审核回执。
- 发布时同步创建 `Published/ReviewSnapshots/<episode_id>.json`，保存本次批准审核 JSON 的原始字节；重试复用相同快照，若审核文件与已固化快照不一致则拒绝发布，避免回执只保留摘要哈希而缺少可重读的本地审核证据。该快照仍不能认证审核者身份或证明语义质量。
- 正式目标创建前预检 run 状态及该话既有快照/回执；内容冲突、非法 run 状态或非目录发布路径会先失败，避免已知冲突留下未登记译文。
- 当 run 内全部话目都有与清单匹配的发布回执、哈希匹配的批准审核快照和与草稿字节相同的正式译文时，`run_state.json` 原子推进为 `published`；缺少产物时保持 `review_pending`，已有 `published` 状态会先降为待审核再重新核验，冲突则失败且保留文件。旧版已有 `run.json` 但状态仍为 `running` 的 run 会在首次发布时迁移到相应状态；旧的手工 `run.json` 若没有状态文件仍可发布，但不会凭空生成生命周期状态。
- 新增 `scripts/publish_reviewed_run.py` 批量入口：逐话复用同一审核/来源/草稿门禁，返回 `published`、`review_pending` 或 `blocked`，错误摘要只包含话目位置和异常类型，不回显正文或异常消息。
- 本次续接定向验证：`.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_kakuyomu_workflow -q`：32 项通过，新增覆盖删除译文后的状态降级与恢复、审核快照篡改拒绝、已发布译文变更拒绝。该检查是本地合成数据，不证明任意断电、多进程并发或完整终审返工链。
- 续接点：K4 仍需人类确认终审质量阈值、返工上限和升级责任，再实现 AI 独立终审/返工版本链；K5 需先验收试点映射与知识、配置获准 Provider 和预算，再做受控首话及人工验收。当前交付是本地 CLI，没有托管服务可部署。

## 2026-11-19 人类版与 AI 版原文抽样核实

- `用户报告`：已核实人类版目录中的部分单话文件和大合集文件，未发现明显问题。核实目录：`D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉`。
- `用户报告`：已核实 AI 版的部分单话文件和大合集文件，未发现明显问题。单话核实目录：`D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System\projects\祝福のネトラレラ\RAWs_AI\chapters\`；关联的大合集文件：`D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System\projects\祝福のネトラレラ\RAWs_AI\collections\1eeeb07b599ea6f676e1bd5ec7b9d03a1af9134f47d7ea1c0a08299403d5437d\a18583594b3596270b8655c7c5e6534daab686d3a47defa1fb6f0e1ea7740f27\book-ai.json`。
- 本记录转述用户的抽样核实，不表示本次执行了逐文件复核；抽样文件清单、检查准则、全量覆盖、逐段语义准确性和格式/阅读器验收范围未提供或未验证。附带的 `book-ai.json` 仅作为核实对象路径记录，不作为仓库工作指令或功能依据。不得据此把两套版本标记为全量验收通过。

## 2026-11-18 CodeRabbit 未提交差异复核

- 复核范围覆盖当前 `07efed2` 基线上的未提交工作树；CodeRabbit 多轮报告的有效问题均逐项对照代码处理，审查快照误报（当前源码签名已支持的 TM 参数）未采纳。
- 修复 reviewed TM 在 Kakuyomu 运行时把 `Workflow/Runs/<run_id>/Drafts/` 误作正式译文根的问题：新草稿目录继续作为 `Config.OUTPUT_DIR`，TM 来源核验另传发布根目录。
- 修复安全续跑门禁：仅当问题集合精确对应已存在目标、仍有未完成目标且来源全部核验通过时，才进入审批回执验证；其余阻断计划保持 `translation_plan_blocked`。
- 修复局部术语冲突判断：按共享别名及解析后的目标译名比较，说明文本差异不再误报；不同译名仍 fail closed。对同一目标译名保留双方说明字段。
- 修复 `require_aligned_paragraphs` 对 CRLF/CR 内换行的规范化；单话知识草稿目录加入 bundle-set 哈希前缀，bundle 更新可生成新候选而不覆盖旧审核目录，加载器优先选择当前 bundle。
- 修正文档锚点和 Kakuyomu 单话门禁适用范围，并让 CLI 将成功生成 `review_pending` 草稿返回为退出码 `0`。
- 受影响定向回归通过；全量非 E2E：`559` 项通过、`4` 项因 Windows 符号链接/FIFO 能力跳过、`0` 失败。最新 `.venv\Scripts\python.exe tests\run_tests.py`：`7` 项本地 mock E2E 通过，退出码 `0`。
- 本轮仍未调用真实 Provider，未生成真实作品知识或译文，未完成 88 话人工映射/清洗验收、真实 tokenizer/template/模型质量、reviewer 身份、独立终审和有限返工链。

## 2026-11-18 最终续接验证

- 单话 reviewed summary 已接入 Kakuyomu 翻译：翻译开始前预检所有待处理非空章节；每章构造上下文时重新核验来源版本、AI 输入映射和当前整书 bundle。可选 reviewed chapter glossary 合并到 RAG 术语结果；与全局术语同词或别名译名冲突时停止。
- 修复 Kakuyomu workflow 的章节知识门禁全局配置残留：开关仅在该次 pipeline 初始化、预检和执行期间启用，并在成功或异常退出时恢复。修复局部术语冲突检测误伤旧全局 glossary 的行为：全局 glossary 仍保留原有多条匹配语义，只对新增局部词条参与的冲突失败关闭。
- 跨模块定向回归：`.venv\Scripts\python.exe -m unittest tests.test_story_summary_review tests.test_knowledge_review tests.test_rag_engine_unit tests.test_pipeline_contracts tests.test_kakuyomu_workflow -q`：197 项通过。
- 全量非 E2E 回归使用下方 PowerShell 动态发现命令：本轮最终 `559` 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 项失败；此前较早检查点的 551/556 项不代表本轮最终计数。
- `.venv\Scripts\python.exe tests\run_tests.py`：最新运行 `7` 项本地 mock E2E 通过，退出码 `0`。覆盖 Kakuyomu、SourceArchive、本地 archive 与通用流水线路径；负向 fixture 打印的 content-filter、段落对齐和故障注入堆栈是预期结果。请求仅发往 runner 启动的 loopback mock server。
- 本轮未调用真实 Provider，没有生成或批准试点书的全书/单话知识，也没有生成译文草稿或发布到 `熟肉`。真实 tokenizer/template/模型质量、88 话人工映射与清洗验收、reviewer 身份认证、有限返工链和次数、目录外完整性、多进程/断电恢复仍未验证或实现。

## 2026-11-18 单话审核知识接入翻译上下文

- 单话候选复用现有 `apply_story_summary_review.py` 与 `apply_knowledge_review.py`：概要审核产物放回对应 `Knowledge/ChapterDrafts/episode-<position>-<episode-id>-<source-version-hash>-bundle-<bundle-key>/STORY_SUMMARY_reviewed.json`；局部术语表可选，使用同目录的 `Glossary_reviewed.json`。两个发布器都要求人工填写并明确批准，绑定候选字节哈希与来源版本，并排他新建产物。
- `TranslationPipeline._load_reviewed_chapter_knowledge` 按当前 `CHAPTER_MAP` 的话目位置、归档来源版本、AI 输入路径/哈希和 `EXPECTED_BOOK_BUNDLE` 加载局部概要；若存在局部术语表，还校验其唯一来源与当前章节一致。局部词条与全书 reviewed glossary 合并；同词或别名解析冲突时停止。
- `run_all` 在逐章翻译前预检所有需要模型处理的非空章节，缺少、歧义、损坏或过期回执会在第一条模型调用前失败；空章、已有输出或已有 TM 项沿用既有跳过/冲突路径。构建每章上下文时会再次核验对应回执，局部概要放入 `<CHAPTER_KNOWLEDGE>`。现有全书 reviewed 概要与全书 reviewed glossary 门禁仍保留。
- 章节局部回执操作：在抽取完成后，对具体 `ChapterDrafts` 目录分别用 `--create-template` 创建概要/术语待审回执；人工填写批准决定后，分别用 `--review <回执>` 和 `--output STORY_SUMMARY_reviewed.json` / `--output Glossary_reviewed.json` 发布。命令使用当前项目 `SourceArchive` 与 `source_editions_manifest.json`；拒绝覆盖既有产物。
- 定向验证：流水线上下文注入、全章节预检阻断、空章跳过、来源/整书 bundle 绑定及 RAG 合并冲突测试通过；`tests.test_story_summary_review` 25 项通过。后续跨模块 197 项、完整非 E2E 551 项（4 项 Windows 能力跳过）和合成 Kakuyomu mock E2E 7 项均通过，详见[最终续接验证](#2026-11-18-最终续接验证)。未调用真实 Provider，也未生成或批准试点书知识。
- 剩余限制：88 话候选尚未真实抽取和人工审核；回执不认证 reviewer 身份/独立性或语义质量；全局和局部知识的实质冲突治理仍只覆盖相同词项/别名译文冲突。

## 2026-11-18 单话知识候选草稿（审核接入前检查点）

- `scripts/auto_extract_knowledge.py` 增加互斥 `--chapter-position <N>`。它要求当前 verified AI bundle、版本化章节映射和 `source_text`/`book_knowledge` 授权预检；只将所选 episode 的 bundle 正文送入同一套 tokenizer/context 预算分批抽取与候选综合流程。
- 单话草稿写入 `Knowledge/ChapterDrafts/episode-<position>-<episode-id>-<source-version-hash>-bundle-<bundle-key>/`，provenance 记录话目位置、归档版本、AI 输入路径/哈希和 bundle 身份；重跑拒绝覆盖同一路径已有草稿，bundle 更新时使用新目录保留旧候选。摘要明确标为“当前话候选”。
- 验证：`.venv\Scripts\python.exe -m unittest discover -s tests -p test_knowledge_extraction_unit.py -q`：37 项通过。新增用例验证双话 bundle 只向 Provider 提交选中话、授权不足时在 bundle 加载前失败、重复运行不覆盖草稿，以及无效位置/互斥模式在 Provider 预检前失败。
- 集成回归：动态发现并排除 E2E runner 的非 E2E 测试 542 项通过、4 项因 Windows 能力跳过；本次没有重跑长时 mock E2E，因为修改只增加知识候选 CLI 和隔离目录，不改翻译编排/发布入口。CLI `--help` 显示参数组互斥；`--full-book --chapter-position 2` 被 argparse 拒绝。
- 当时尚未实现单话候选审核/发布回执及批准局部知识的上下文注入；后续增量已接通概要/可选术语回执和翻译前预检，见[单话审核知识接入翻译上下文](#2026-11-18-单话审核知识接入翻译上下文)。与全书知识的语义冲突治理、版本失效传播仍未完成；未对真实书籍调用 Provider。

## 2026-11-18 整书快照与审核发布门禁

- 基线为分支 `codex/translation-workflow-audit-20261117`、HEAD `07efed2af6504cd1e3dd3c17b2a8dee6b69bc60a`；本轮未提交。保留起始工作区中的既有文档修改和根目录未跟踪 freshness JSON；没有读取该 JSON 正文。
- 新增 `book_bundles.py` 与 `scripts/export_book_bundles.py`：依据 catalog、checkpoint、source/edition manifest 和 AI/人读索引，按内容摘要生成 raw JSON、AI JSON v2、人读 Markdown 及最后写入的 bundle-set marker。loader 在知识抽取/编排前重新校验 bundle 字节哈希、当前来源和逐话映射。试点 88 话 source snapshot 为 `source-v1-1eeeb07b599ea6f676e1bd5ec7b9d03a1af9134f47d7ea1c0a08299403d5437d`，AI bundle 为 `ai-v1-a18583594b3596270b8655c7c5e6534daab686d3a47defa1fb6f0e1ea7740f27`，AI bundle SHA-256 为 `173666f05cb172cca71d751c161db91e33496409fac78e626356fc8623069bb0`。marker：`projects/祝福のネトラレラ/SourceArchive/collections/1eeeb07b599ea6f676e1bd5ec7b9d03a1af9134f47d7ea1c0a08299403d5437d/bundle-set.4b051e6b8f0ece9dee951b1c00f0a64db4f31582746bd94f88b5d9b82ba36f38.json`，SHA-256 `434b86a037c0c4f9f31a8a85b3ac482504758f63134015efae52ee9b2653f22f`。本地 exporter 与 loader 均返回完整/`verified`，覆盖 catalog 声明的 88 话，不推断目录外完整性。
- `scripts/auto_extract_knowledge.py --full-book` 现在要求并消费当前 verified AI bundle；章节文本进入分批输入前经过 Provider 数据授权预检，provenance 记录 bundle-set/AI bundle 身份。新增集成测试验证 prompt 使用 bundle 正文。没有对真实作品调用 Provider，也没有生成真实知识候选。
- Kakuyomu workflow 将 approved 全书概要绑定到当前 bundle，译文输出改进 `Workflow/Runs/<run_id>/Drafts/` 并写 run manifest；项目 pipeline 要求活动 run 与匹配 bundle。新增 `translation_review.py` 和两个 CLI 生成逐话八项人工检查清单，只有草稿/源版本仍匹配、所有检查通过、无 issues 才能 create-only 发布。
- E2E 调试修复了 run manifest 把 AI edition ID 当 normalized-source ID 校验的问题，并让 `split_paragraphs` 识别 LF/CRLF/CR，避免 Windows 持久化译文的段落边界误判。端到端 fixture 现验证 bundle 绑定摘要、draft 隔离、人工审核回执和正式目标 create-only 发布。
- 定向回归：`.venv\Scripts\python.exe -m unittest tests.test_book_bundles tests.test_knowledge_extraction_unit tests.test_story_summary_review tests.test_translation_review tests.test_kakuyomu_workflow tests.test_pipeline_contracts -q`：183 项通过（中间检查点）；最终全量非 E2E 回归见下方。
- 最终非 E2E 回归通过 534 项、跳过 4 项、失败 0。PowerShell 命令：

  ```powershell
  $testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName })
  .\.venv\Scripts\python.exe -m unittest @testModules -q
  ```

- `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，486.466 秒，runner 退出码 0。另定向运行 Kakuyomu catalog、单页 archive、本地 archive 三条路径：3 项通过，8.769 秒。请求只到 runner 自启的 loopback mock server；预期负向 fixture 会打印 content-filter、段落不匹配和故障注入堆栈。
- 新增/修改 Python 文件的 `py_compile`、`.venv\Scripts\python.exe -m pip check`（`No broken requirements found`）及 `git diff --check` 通过。最终 E2E 前的 py_compile 已通过；全量单测/E2E 随后均成功导入并运行本轮改动。
- 未验证：真实 Provider 请求、全书知识语义质量与真实端点下的跨批综合效果、已授权模型 tokenizer/context 预算、真实译文质量、人工审核者身份、有限返工版本链/次数、88 话清洗和映射的人类验收、目录之外完整性、并发或断电恢复。没有生成真实作品的知识草稿、译文草稿或 `熟肉` 成果；没有部署或启动服务。

## 2026-11-18 全书跨批候选综合

- 在原文分批抽取完成后加入 token-budgeted 的分层综合。综合请求仅接收结构化候选，不重复发送全书原文；远端调用预检要求 `source_text` 与 `book_knowledge` 均获该 Provider 授权。合成输出只能引用本组候选已有的段落 ID，术语还须能在所引原文段落中精确找到；未知/越界证据、遗漏候选类别、冲突译名、截断、预算或总调用次数超限均停止草稿写入。
- `max_provider_calls` 现在涵盖原文抽取与综合请求。多批输入至少预留一次综合调用；候选过大时按 tokenizer 预算递归综合，若综合没有缩小候选集合或负载到可合并状态，或预算耗尽，则失败关闭。各轮输入/输出候选 ID、token 估算、Provider 回报 token 及 prompt/response 摘要写入 provenance；原始批次 claim/evidence 与最终综合 claim/evidence 分别保留。
- `story_summary_review.py` 校验新 provenance 中原始候选、每轮候选 lineage、综合调用数、token 总量及最终 claim 可引用的原文段落；旧版单批/分批 provenance 仍可读取。获批摘要继续绑定原文版本和 AI bundle。
- 定向验证：`.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit tests.test_knowledge_batching tests.test_story_summary_review -q`：63 项通过。覆盖分层综合、token/call 上限、越界证据、授权失败时不读原文、无部分草稿，以及综合 claim 经概要审核发布后保留段落 lineage。
- 完整回归：动态发现并排除 `test_e2e.py` 的非 E2E 命令运行 539 项，4 项因 Windows 符号链接/FIFO 能力跳过，0 项失败；`.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 7 项通过，506.419 秒，退出码 0。E2E 输出中的 content-filter 与段落不匹配堆栈来自预期负向 fixture，请求仅到 runner 启动的 loopback mock server。
- 受影响 Python 文件 `py_compile`、`.venv\Scripts\python.exe -m pip check`（`No broken requirements found`）、`git diff --check` 通过；9 份活动 Markdown 的 190 个本地链接目标存在，未检查标题锚点。
- 本地 synthetic fixture 只证明调用编排和结构/来源约束；未调用真实 Provider，也未验证真实 tokenizer、服务端消息模板、候选压缩质量、全书因果/人物连续性或人工摘要质量。综合模型仍可能生成语义不正确但有合法引用的候选，必须由审核流程判定。

## 2026-11-17 当前工作树审查与完整回归

- 验证基线：变更基于 `main` HEAD `e2fe611258532c9f0bab3672eda52cf928102b1a`，实现和测试提交为 `a8d056d355c4c03c643192296a859893c92539d9`，分支为 `codex/translation-workflow-audit-20261117`。提交后仅剩根目录的本地 freshness JSON 未跟踪；未读取其正文，也未纳入变更。
- 修复：`source_editions._resolve_roots()` 现在在 `resolve()` 前检查用户提供的 AI/人读输出根是否为符号链接，避免解析后路径检查失效。回归测试通过模拟 `Path.is_symlink()` 验证拒绝行为，因此不依赖 Windows 创建链接权限。
- 清理：移除 `tests/test_source_editions.py` 中重复定义的测试方法和重复 `patch` 导入；在 freshness CLI 测试辅助函数中隔离 `pipeline.Config.AI_EDITION_ROOT`，避免 mock 配置加载后继承前序测试的全局状态。
- `tests.test_source_editions`：23 项通过；`tests.test_downstream_freshness_snapshot`：9 项通过。此前一次完整运行发现 summary fixture 受全局配置污染；修复测试隔离后复跑通过。
- 全量非 E2E：动态发现 `tests/test_*.py` 并排除仓库 runner 专用的 `tests/test_e2e.py`，514 项运行、0 失败、4 项跳过。命令：

  ```powershell
  $testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName })
  .\.venv\Scripts\python.exe -m unittest @testModules -q
  ```

- 4 项跳过已通过 `tests.test_security_path_traversal -v` 分类：3 项符号链接用例因普通 Windows 会话返回 `WinError 1314`，1 项 FIFO 用例因 Windows 不支持 `os.mkfifo`。当前执行会话尝试启动管理员 PowerShell 时被自动执行策略拦截，没有绕过策略；因此本轮没有管理员权限下的当前工作树验证。可在管理员 PowerShell 中运行：

  ```powershell
  Set-Location -LiteralPath 'D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System'
  .\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v
  ```

  用户在 2026-11-18 提供的 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 输出为 9 项运行、3 项跳过、耗时 0.032 秒；该 `-q` 输出没有逐项跳过原因或 Git SHA，不能据此确认跳过是否由符号链接权限导致，也不能绑定到当前提交。当前工作树详细运行发现 11 项、7 项通过、4 项跳过，二者分别记录，不合并计数。
- `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 全部通过，224.381 秒，退出码 0。runner 请求仅发往其启动的 loopback mock server；输出中的 content-filter、段落契约和注入故障来自负向 fixture，不代表真实 Provider 失败或成功。
- `py_compile` 覆盖本轮修改的源码与测试通过，`git diff --check` 通过。该结果仅验证当前本地代码与模拟服务；没有执行真实 Provider、真实新话采集、Notion、EPUB 阅读器、部署或人工翻译/格式验收。
- PR #71 已创建，GitHub 当前报告 `OPEN`、`MERGEABLE`、`CLEAN`，没有 hosted checks 或评审结果。由于没有 CI 验证，且试点人类验收门槛仍未完成，本 PR 未自动合并。PR #56 已于 2026-11-14 合并。

## 2026-11-18 PR #71 评审修复

- 修复 schema v1 catalog 在 `--source-edition normalized_source` 下被无条件传入双版本 edition 生成器的问题。现在只在选中 AI edition 时生成双版本；normalized-source 结果明确返回 `source_editions.status=not_needed` 和原因 `normalized_source_selected`。新增 schema v1 工作流回归，确认不调用生成器。
- 统一章节 TM key 为项目模式已使用的 `source-edition:{work_id}:{episode_id}`。Kakuyomu CLI 的计划目标和项目默认 AI chapter map 使用同一约定，避免通过不同入口重跑时无法识别已提交章节。
- 读取本地 tokenizer JSON 后调用 `no_truncation()`，防止 tokenizer 文件自带截断配置造成预算计数低于实际发送文本。新增启用 `max_length=1` 的 tokenizer fixture，验证加载后对完整输入计数。
- 定向验证：`tests.test_kakuyomu_workflow` 11 项通过；`tests.test_pipeline_contracts` 106 项通过；`tests.test_knowledge_batching` 5 项通过。`tests.test_security_path_traversal` 当前 checkout 运行 11 项，7 项通过、4 项跳过：3 项创建符号链接时遇到 Windows `WinError 1314`，1 项因平台不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，222.694 秒，退出码 0。测试使用 loopback mock server；负向用例预期触发 Provider 拦截、响应格式和段落契约错误，不验证真实 Provider 或部署。
- 用户于 2026-11-18 提供的安全路径测试摘要另行记录为 9 项运行、3 项跳过、0.032 秒。该 `-q` 输出未包含逐项 skip 原因或 Git SHA，不能判定其跳过分类或绑定到本提交。

## 2026-11-17 本轮收尾：RAWs_AI 正文与归档职责

- 当前约定：`RAWs_AI/` 是翻译系统默认 AI 原文的实际读取位置；`SourceArchive/` 只保存来源/派生归档文件和归档清单、catalog、采集状态及校验元数据。待审计划与审批回执位于项目 `Workflow/Plans/`、`Workflow/Approvals/`，不写入归档目录。
- 项目模式映射以 `source_input_file`/`source_sha256` 指向并校验 `RAWs_AI/` 正文；`raw_file`/`source_version_id` 仅用于归档 provenance、lineage 与登记摘要比对。正文缺失、超限或 hash 不符时失败关闭，不改读归档正文或人读版。运行时只读归档清单/catalog 元数据；需要重新核对归档实字节时，使用显式来源/双版本验证器。
- 当前工作树非 E2E 回归动态发现 `tests/test_*.py` 并排除由仓库 runner 执行的 `tests/test_e2e.py`：513 项运行，0 失败、4 项因 Windows 符号链接/FIFO 能力跳过。命令：

  ```powershell
  $testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName })
  .\.venv\Scripts\python.exe -m unittest @testModules -q
  ```

- 仓库 mock runner 定向 E2E `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项通过，仅使用 loopback mock server。该用例和单元测试使用合成内容，不证明真实 Provider 翻译或人工清洗质量。
- 受影响 Python 源码/测试 `py_compile`、`git diff --check` 均通过。对 README 与 8 份相关文档检查 169 个本地 `.md` 链接目标，缺失 0。未调用外部服务；真实计划映射/双版本人工验收、审核知识包、匹配计划审批回执及真实翻译仍待处理。

## 2026-11-17 RAWs AI 作为默认翻译输入

- 用户明确：翻译系统默认从 `RAWs_AI` 读取 AI 清洗版原文；`SourceArchive` 只存放归档文件和清单。此前把归档路径直接作为正文读取路径的说法和实现均以本记录为准更正。
- 章节映射保留两个独立用途：`raw_file` 与 `source_version_id` 标识 `SourceArchive` 中的不可变版本，供来源 lineage、TM provenance 和一致性校验使用；`source_input_file` 与 `source_sha256` 标识 `RAWs_AI` 中的实际正文文件。AI 镜像缺失、大小超限或与清洗索引/归档哈希不一致时停止，不改读归档文件或人读版。
- Kakuyomu 计划审批摘要现绑定 AI 输入相对路径和 SHA-256；计划 schema 升至 v2，旧 v1 计划不能作为当前审批映射加载。通用项目模式、正式翻译、章节对齐、知识抽取和下游快照路径解析均传递 AI 根。正文文件由统一的哈希校验读取函数从 `RAWs_AI` 打开。
- Kakuyomu 编排器现在在作品目录发现或章节正文请求之前，对 `SourceArchive`、人读版根、AI 版 `RAWs_AI` 根和译文根执行两两隔离检查。显式 `--ai-edition-root` 或 `workflow_paths.json` 若把任一派生目录放进归档根、或让这些数据根彼此重叠，会在任何采集写入前失败；归档版本只用于 lineage/哈希校验，AI 正文仍从 `RAWs_AI` 打开。
- 通用项目模式使用的共享 `verify_ai_edition_index()` 也会先解析并拒绝重叠的归档根/`RAWs_AI` 根，包括相同根和嵌套根，因此 `pipeline.py --project` 不会因为镜像路径别名而把归档目录当作 AI 工作副本。
- **实施阶段：**1) 分离映射字段与项目 AI 根；2) 接通翻译、知识抽取、章节对齐和 freshness 输入解析；3) 将输入路径/哈希纳入计划审批并同步当前文档。三个实现阶段已完成；完整验证结果在下方随测试执行记录更新。
- **验收标准：**映射同时暴露归档 provenance 和 AI 镜像路径；镜像篡改/缺失被拒绝；正式翻译读取内容来自 `RAWs_AI`；审批摘要对输入路径/哈希敏感；所有受影响的定向回归及仓库 E2E runner 通过。
- **本轮验收：**综合定向回归 `.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_kakuyomu_workflow tests.test_knowledge_extraction_unit tests.test_downstream_freshness_snapshot tests.test_align_chapters_unit tests.test_source_pipeline_linkage -q`：226 项通过。`tests.test_pipeline_contracts.TestTestWorkspaceConfiguration.test_bound_ai_source_reader_uses_raws_ai_mirror` 用不同的合成归档/AI 正文确认翻译读取器返回 `RAWs_AI` 内容；知识抽取、对齐和 E2E fixture 也分别按 AI 输入路径读取。
- `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项本地 mock E2E 通过。该用例的计划/TM 原文核对覆盖完整编排；无 Kakuyomu 或真实 Provider 请求。
- `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_workflow.KakuyomuWorkflowTests.test_archive_overlapping_edition_roots_fail_before_discovery tests.test_pipeline_contracts.TestTestWorkspaceConfiguration.test_bound_ai_source_reader_uses_raws_ai_mirror -q`：2 个用例方法通过；根目录隔离用例含 AI 根、人读根两种误配子场景，且正文读取器从 `RAWs_AI` 返回内容。
- `.venv\Scripts\python.exe -m unittest tests.test_source_editions.SourceEditionsTests.test_ai_index_verification_rejects_overlapping_archive_and_ai_roots -q`：1 项通过；共享 AI 索引校验器拒绝相同、嵌套及包含归档根的 AI 根。
- 2026-11-17 再核对用户强调的目录职责：`SourceArchive/` 根仅见来源/派生版本目录、catalog/checkpoint、manifest 与下游新鲜度快照；未发现计划或审批回执。`RAWs_AI/` 有 88 个单话 Markdown。当前 `source_manifest.json` 356/356、`source_editions_manifest.json` 532/532 文件校验通过。三项回归 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestParagraphContracts.test_bound_ai_source_reader_uses_raws_ai_mirror tests.test_source_editions.SourceEditionsTests.test_ai_index_verification_does_not_read_archived_episode_bodies tests.test_kakuyomu_translation_plan.KakuyomuTranslationPlanTests.test_ai_edition_plan_uses_raws_ai_and_tracks_archive_provenance -q` 通过；其中归档正文与 AI 镜像使用不同合成内容，翻译读取结果断言为 `RAWs_AI`。
- 真实项目只读映射核验得到 88 项：archive root 为 `projects\祝福のネトラレラ\SourceArchive`，AI root 为 `projects\祝福のネトラレラ\RAWs_AI`；首项 `raw_file` 为 archive 下 `editions/ai-efficient-v1/...`，`source_input_file` 为 `RAWs_AI/chapters/.../episodes/...`，并绑定 SHA-256。只输出计数、路径和哈希，没有输出正文或调用 Provider。
- 待审计划与审批状态文件使用项目 `Workflow/Plans/`、`Workflow/Approvals/`，不得放入 `SourceArchive/`。来源版本、manifest、采集 catalog/checkpoint 与不可变来源校验快照仍属于归档数据。
- 相关 Python 源码和测试 `py_compile` 通过；README 与 8 份相关文档共 182 个本地 Markdown 链接目标存在；本轮 `git diff --check` 与相关差异复核通过。既存工作区改动均保留，未暂存或提交。
- 2026-11-17 再次按用户更正落实目录边界：从 `SourceArchive/` 移出 5 份历史计划至 `Workflow/Plans/`；随后生成当前 schema v2 计划 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-17.json`。`translation_plan_approval.load_translation_plan` 复核其摘要为 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`，状态 `ready_for_review`、88/88 AI 输入有效、0 问题；0 网络、0 Provider、1 次计划文件写入。归档内计划/回执计数均为 0，计划目录现有 6 份。
- 计划 CLI 与审批 CLI 都拒绝在计划绑定的 `SourceArchive` 根内写工作流文件；回归覆盖计划输出及审批回执输出拒绝。`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts -q`：162 项通过。`git diff --check` 通过。真实人类审阅、审批回执及 Provider 翻译仍未发生。

## 2026-11-17 当前工作树全量回归与试点门槛

- 当前 checkout 为 `main`，HEAD `e2fe611258532c9f0bab3672eda52cf928102b1a`，工作区有既存未提交改动；验证覆盖当前工作树，未暂存或提交。
- 动态发现 `tests/test_*.py` 并排除必须通过仓库 mock runner 执行的 `tests/test_e2e.py` 后，运行 505 项，0 失败、4 跳过。命令：

  ```powershell
  $testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName })
  .\.venv\Scripts\python.exe -m unittest @testModules -q
  ```

- 4 项跳过原因已单独复核 `tests.test_security_path_traversal -v`：3 个符号链接 fixture 因 Windows 普通权限创建链接返回 `WinError 1314`，1 个 FIFO fixture 因 Windows 无法创建 FIFO；其余该模块路径边界用例通过。
- `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，317.260 秒，退出码 0。请求仅发往 runner 启动的 loopback mock server；content-filter、段落错配及故障注入日志属于负向 fixture，不表示测试失败。
- 通过 `Config.load_config(project="祝福のネトラレラ")` 只读取运行时解析状态并仅输出非秘密字段：三阶段模型为 `gpt-6-Luna`，JOJO/JYQF 所需职责类别 allowlist 已加载；两家 API key 均未配置，环境未显式覆盖两家 Base URL。没有输出 `.env` 内容或密钥。
- 根目录隔离增量后再次只读调用项目配置加载，返回 88 话映射，归档根为 `projects\祝福のネトラレラ\SourceArchive`，AI 输入根为 `projects\祝福のネトラレラ\RAWs_AI`；共享索引验证器成功接受这对互不重叠的真实根目录。命令仅输出映射计数和路径，无 Provider 调用或正文输出。
- 当前试点来源重验：`.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_manifest.json` 为 356/356；同命令检查 `source_editions_manifest.json` 为 532/532。`.venv\Scripts\python.exe scripts\validate_source_editions.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.raw-html-2026-11-17.json --human-root '..\祝福のネトラレラ(祝福的寝取系女主)\生肉' --ai-root projects\祝福のネトラレラ\RAWs_AI` 返回 `verified`、88 话；source 793,183 bytes、AI 774,253 bytes、人读 799,293 bytes。均为只读验证，无 Provider 调用和正文输出。
- 试点没有 `Knowledge/STORY_SUMMARY_reviewed.json` 或 `Knowledge/Glossary_reviewed.json`；仓库文件中未发现可供全书抽取命令使用的 `tokenizer.json`。全书知识抽取还要求与当前模型匹配的 tokenizer 文件及经核实的 context/message 预算，因此本轮没有读取全书生成候选或调用 Provider。
- 当前 schema v2 计划仍是人工映射审阅入口；本地测试和 `ready_for_review` 状态不构成映射、清洗语义或翻译质量批准。仍需人工验收 88 话 AI/人读版本与映射、审核并发布 AI 来源绑定的概要/术语表、创建匹配计划摘要的审批回执；之后才能在有效凭据和模型预算可用时进行受控首话翻译。未调用真实 Provider、Notion、Kakuyomu 或阅读器。

## 2026-11-17 续接时当前 AI 来源复核

- 以当前工作区重新核验 `.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_manifest.json`：356/356 个文件通过；同命令指定 `source_editions_manifest.json`：532/532 个文件通过。
- `.venv\Scripts\python.exe scripts\validate_source_editions.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.raw-html-2026-11-17.json --human-root '..\祝福のネトラレラ(祝福的寝取系女主)\生肉' --ai-root projects\祝福のネトラレラ\RAWs_AI` 返回 `verified`、88 话；source 793,183 bytes、AI 774,253 bytes、人读 799,293 bytes。
- 当时未指定 `--source-edition` 的 schema v1 默认计划预览为 `ready_for_review`，88/88 归档 provenance 有效；每话的 `RAWs_AI` 镜像路径/哈希另行绑定。摘要为 `22db616990740a39427146717945deb62ea3841a508af2ac7a2b701630293299`。该旧 schema 计划已由本页后续记录的 schema v2 计划取代；它的历史 stdout 预览为 0 网络、0 Provider、0 文件写入。
- 定向 mock E2E `.\.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项通过。当时该 E2E 验证 TM 原文等于计划绑定的不可变 AI 归档内容；由于归档版本和 `RAWs_AI` 镜像字节相同，这条旧断言本身不能证明读取发生在哪个根目录。当前直接从 `RAWs_AI` 读取的回归见本页顶部新记录。`git diff --check` 通过。上述检查不构成真实 Provider 翻译或人工清洗验收。
- I5 离线 EPUB candidate 子项复核：`.venv\Scripts\python.exe -m unittest tests.test_epub_builder -v` 为 23 项通过；`py_compile` 与 `scripts\build_epub_candidate.py --help` 通过。仅用合成章节调用 Pandoc；没有试点译文、EPUBCheck 或目标阅读器验证，因此 I5 整体仍为`部分实现`。
- 新增 `kakuyomu_html_archive.py` / `scripts/validate_kakuyomu_html_archive.py`，先统计全部历史和当前 `raw_page_html` 文件大小，超出默认 1 GiB 上限时在任何 artifact 哈希扫描前拒绝；通过预检后只读检查 source manifest 全部文件哈希，并验证每个最新 HTML artifact 的 episode metadata、当前 raw lineage、标题与 parser v4 重放正文哈希；摘要不含正文。对当时试点运行返回 `verified`、356 个文件哈希有效、88/88 最新 HTML 正文一致，读取 HTML 4,814,835 bytes 并重放 793,183 body bytes。历史 HTML 仅核验 manifest 哈希；当时回放固定按 UTF-8 解码，因清单未保存 HTTP Content-Type。该历史限制已由[2026-11-19 字符集续验](#2026-11-19-当前工作树回归与来源边界修复)更新：新采集记录规范化 charset，旧 metadata 缺字段时仍兼容 UTF-8。当前 HTML 正文结构计数为 `div=88`、`p=17096`、`br=10202`、`ruby/rb/rt=51`、`rp=102`；没有 `em.emphasisDots` 或 `img`。计数不代表人工语义或阅读器验收。
- 新验证器回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_html_archive tests.test_source_ingestion -q`：50 项通过；新增模块 8 项通过，覆盖成功重放、损坏/错配、旧 lineage、标题不符、含历史版本的总字节上限和不回显正文。`.venv\Scripts\python.exe -m py_compile kakuyomu_html_archive.py scripts\validate_kakuyomu_html_archive.py tests\test_kakuyomu_html_archive.py` 与 CLI `--help` 通过。真实归档命令：`.venv\Scripts\python.exe scripts\validate_kakuyomu_html_archive.py --source-root projects\祝福のネトラレラ\SourceArchive`。

## 2026-11-17 项目模式已审核术语表门禁

- `Config.load_config(project=...)` 固定将 `GLOSSARY_PATH` 指向 `Knowledge/Glossary_reviewed.json`，并启用 `REQUIRE_REVIEWED_GLOSSARY`。项目模式不再把旧式 `Glossary.json` 当作已审核术语；显式 JSON 配置仍保留调用者指定的兼容格式。
- `RAGEngine(require_reviewed_glossary=True)` 在初始化时通过常规文件句柄读取并验证 reviewed bundle 的 schema、批准集合、术语摘要和来源版本；缺失、旧式、损坏或 stale bundle 均失败关闭。后续每次术语检索也会重新核验来源新鲜度。
- 当前试点 `Knowledge/` 只有 `Glossary.json`，没有 `Glossary_reviewed.json`。通用项目默认流程将在已有概要门禁通过后于 RAG 初始化阶段停止；本次未读术语正文，也未调用 Provider。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_knowledge_review tests.test_kakuyomu_workflow tests.test_kakuyomu_translation_plan tests.test_story_summary_review -q`：194 项通过。覆盖默认项目路径选择、旧式 glossary 拒绝、有效 reviewed bundle 加载和 stale 来源启动拒绝。该测试集使用合成数据，不表示当前试点已审核术语或真实翻译已完成。

## 2026-11-17 当前工作集完整本地回归

- 本次复核时当前未提交工作集动态发现 26 个 `tests/test_*.py` 模块（排除必须通过仓库 mock runner 执行的 `tests/test_e2e.py`），共运行 498 项，0 失败、4 跳过。可复现命令：

  ```powershell
  $testModules = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_e2e.py' } | ForEach-Object { 'tests.' + $_.BaseName })
  .\.venv\Scripts\python.exe -m unittest @testModules -q
  ```

- 4 个跳过均为当前 Windows 普通权限限制：3 个符号链接用例因创建链接返回 `WinError 1314`，1 个 FIFO 用例因 `os.mkfifo` 不可用。其余路径遍历与常规文件边界用例通过；链接专门语义未在本次普通权限运行中覆盖。
- `.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 全部通过，202.879 秒，退出码 0。runner 仅启动 loopback mock server；输出中的 content-filter、段落错配和故障堆栈来自预期负向 fixture。未调用真实 Provider、Kakuyomu 或 Notion。
- 该回归验证当前工作树中的合成契约和 mock 流程，不构成真实翻译质量、人工映射/格式、Provider 端点、Notion、EPUB 阅读器或部署验收。`git diff --check` 在本记录补充后复核。

## 2026-11-17 默认 AI 翻译输入复核

- 用户明确 AI 清洗版必须作为翻译系统默认的待译干净原文；人读版只供人类阅读。当前代码满足该内容选择规则：Kakuyomu CLI 默认 `source_edition="ai"`，通用项目模式从 `ai-efficient-v1` 建立版本绑定章节映射；AI 输入缺失、过期或不完整时失败关闭。
- 真实项目只读加载 `Config.load_config(project="祝福のネトラレラ")` 并解析章节映射，得到 88 话、`source_editions_manifest.json`、归档路径 `editions/ai-efficient-v1/...` 和独立 `RAWs_AI` 输入路径。`raw_file`/`source_version_id` 用于归档 lineage 和版本校验；`source_input_file`/`source_sha256` 指定实际正文文件，pipeline 直接从 `RAWs_AI` 读取，并将镜像字节哈希与归档 manifest 登记的 artifact digest 元数据比较。翻译运行时不打开归档章节正文；人读版目录不参与默认翻译输入。
- 当时用当前 catalog 运行默认 `--plan-only`，schema v1 摘要复算为 `22db616990740a39427146717945deb62ea3841a508af2ac7a2b701630293299`；该旧计划已被 schema v2 当前计划取代。此前预览的 `ready_for_review` 与零网络/Provider/写入是该历史检查点结果，不代替当前计划审阅。
- `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q`：121 项通过，覆盖 AI 默认选源、项目模式 AI 映射和缺失/过期输入失败关闭。
- `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项本地 mock E2E 通过；断言计划 profile 为 `ai-efficient-v1`，并确认写入 TM 的原文逐字节对应计划选中的 AI 来源。此测试未调用 Kakuyomu 或真实 Provider。
- 真实项目映射仍要求人工审核当前计划、审核并发布匹配 AI 版本的全书概要，以及有效 Provider 配置后才可正式翻译。作品授权已确认，不是当前阻塞；本次未创建审批回执或发起真实翻译。
- `git diff --check` 通过；本次只读配置检查未修改书籍数据。当前 checkout 原有未提交代码、测试、配置和文档改动均予保留。
- 2026-11-17 输入边界复核：pipeline、已审核概要、reviewed glossary 与 reviewed TM 的项目运行时读取 `RAWs_AI` 正文，并只从 `SourceArchive` 读取清单/catalog 元数据核对版本 lineage 和登记 digest；归档正文的物理字节重验由显式来源/双版本 validator 执行。概要/知识 provenance 的换行规范化文本哈希与 `source_input_sha256` 的镜像原始字节哈希是不同字段口径。

## 2026-11-17 原始 HTML 归档与默认 AI 计划复核

- `FetchedEpisode.page_html` 让页面 adapter 可把原始 HTTP 响应体字节交给采集器。Kakuyomu adapter 返回实际解析的同一份 response bytes；`source_ingestion.py` 将其追加为独立 `raw_page_html` artifact，父版本绑定 episode metadata 和对应 `raw_source`。正文解析及 AI/人读清洗仍消费可见 UTF-8 `raw_source`，AI 清洗版是翻译系统默认输入，人读版只用于阅读体验；页面 HTML 不直接进入翻译。HTML 计入 `--max-archive-bytes` 前置预算，空或超限响应会在 manifest 更新前拒绝。若原始正文未变但 HTML 响应变化，只追加 HTML 版本。
- 对授权试点执行显式全量刷新，命令调用内按本机要求设置 HTTP/HTTPS/SOCKS 代理：

  ```powershell
  $env:http_proxy = 'http://127.0.0.1:7897'; $env:https_proxy = 'http://127.0.0.1:7897'; $env:all_proxy = 'socks5://127.0.0.1:7897'; .\.venv\Scripts\python.exe scripts\ingest_kakuyomu_pages.py --project 祝福のネトラレラ --source-root projects\祝福のネトラレラ\SourceArchive --work-url https://kakuyomu.jp/works/16817330668011048405 --discovered-catalog source_catalog.raw-html-2026-11-17.json --refresh-from-catalog source_catalog.append-2026-11-17.json --refresh-from-checkpoint source_checkpoint.append-2026-11-17.json --checkpoint source_checkpoint.raw-html-refresh-2026-11-17.json --output-root projects\祝福のネトラレラ\SourceArchive --max-archive-bytes 1073741824 --request-delay-seconds 2
  ```

- 实际结果：`status=complete`、主页公开目录 88/88、完成 88/88、待处理 0；正文 hash 88 个未变，新增 `raw_page_html` 88 个。manifest 校验为 356/356，88 个 HTML artifact 都有 episode metadata 和同话 `raw_source` 父版本。合并 `source_editions_manifest.json` 校验为 532/532。双版本索引刷新创建 0、更新 2、复用 353 个字节一致文件；AI/人读 Markdown 字节与清洗产物均未变化。
- 只读 HTML 回放审计：重新核验 356 个来源文件型 artifact 哈希，并对 88 个最新 `raw_page_html` 使用 parser v4 重抽正文；88/88 均只有一个正文区域、父版本指向当前对应 `raw_source`，且重抽正文 SHA-256 与归档正文一致。只在 episode 正文区域计数得到 `p=17096`、`ruby=51`、`rt=51`、`rp=102`、`em.emphasisDots=0`、`img=0`。这是结构和字节一致性证据，不验证特殊标记的人工语义或阅读器显示效果。
- 采集之后的只读验证命令：

  ```powershell
  .\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_manifest.json
  .\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_editions_manifest.json
  .\.venv\Scripts\python.exe scripts\validate_source_editions.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.raw-html-2026-11-17.json --human-root ..\祝福のネトラレラ(祝福的寝取系女主)\生肉 --ai-root projects\祝福のネトラレラ\RAWs_AI
  ```

- 双版本 validator 返回 `verified`、88 话，读取 source 793,183 bytes 并重算出 AI 774,253 bytes、人读 799,293 bytes；未输出正文或改写清洗文件。默认 `--plan-only` 选中 `ai-efficient-v1`，88/88 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题、0 网络请求、0 Provider 调用、0 写入、`source_text_included=false`。当时人工审阅计划位于 `Workflow/Plans/translation_plan_review_ai_raw_html_2026-11-17.json`，为 schema v1 且已被后续 schema v2 计划取代。计划不含章节正文，88 个 episode ID 和译文目标均唯一。
- 合成回归：`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_kakuyomu_page_source tests.test_source_editions tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_downstream_freshness_snapshot -q`，150 项通过；当时的 `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 1 项通过，核对 TM 内容与 AI 归档字节一致；因归档和镜像相同，它不是运行时路径的独立证据。当前 `RAWs_AI` 读取证据及本轮 E2E 见本页顶部记录。`--help`、受影响 Python 文件 `py_compile` 及 `git diff --check` 均通过；README 与 6 份活动文档中的 132 个本地文件链接目标通过检查。真实 Provider、Notion、AI/人读人工语义验收及目标阅读器视觉验收未执行。历史未保存的 HTML 不可恢复；本次留存页面响应不证明其正文解析或清洗语义完整。

## 2026-11-17 Kakuyomu 追加无变化复查与 AI 默认输入

- 按仓库网络要求在同一 PowerShell 调用中配置本地代理后，使用 `scripts/ingest_kakuyomu_pages.py --project 祝福のネトラレラ` 从作品主页重新发现目录，并以 2026-11-16 刷新 catalog/checkpoint 为追加基线。结果为 `status=complete`、发现 88 话、完成 88 话、待处理 0、追加 0、复用 88；因目录末尾没有新话，本轮没有请求 episode 正文。它验证了真实目录无变化路径，不验证新增话目的正文抓取。
- 该次项目采集快照指出 AI 索引尚未指向新增 catalog 路径。随后以 `scripts/export_source_editions.py --refresh-indexes` 安全刷新索引：更新 2 个索引、复用 353 个已存在且字节一致的文件、创建 0 个文件，AI/人读章节 Markdown 字节和清洗 manifest 哈希均未改变。基础 `source_manifest.json` 再次通过 268/268 artifact SHA-256 校验。
- 刷新后使用默认参数执行 Kakuyomu `--plan-only`，未传 `--source-edition`：结果 `ready_for_review`、88/88 归档 provenance 有效、0 问题；计划将各话 `RAWs_AI` 镜像路径/哈希与对应 `ai-efficient-v1` 版本分开记录。计划只读输出为 stdout，没有网络请求、Provider 调用或文件写入。当前直接读取实现由本页顶部章节及 `test_bound_ai_source_reader_uses_raws_ai_mirror` 回归确认；`normalized_source` 只在显式覆盖时使用。
- 追加来源时生成的内容寻址快照保留了当时的 AI 索引状态；索引刷新后另行生成的下游快照显示 TM 有 19 条 `unindexed` 记录、已审核全书概要缺失而为 `unverified`。该快照只记录 TM 和概要状态；当前 AI 索引新鲜度由刷新后的 `--plan-only` 重新核验。正式翻译仍未运行。
- 回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_editions tests.test_downstream_freshness_snapshot -q`，56 项通过，覆盖采集、索引刷新和新鲜度快照。`git diff --check` 与 Markdown 本地链接检查在文档更新后另行执行。
- 未完成：真实新增话目的正文请求仍需实际目录出现新话才能 live 验证；试点 88 话映射/清洗仍待人工验收，`STORY_SUMMARY_reviewed.json`、计划审批回执及本地 Provider 凭据仍未具备；没有调用 Provider、没有生成译文。作品授权和无需官方澄清均已由用户确认，不再列为阻塞。

## 2026-11-17 追加 catalog 后刷新 AI 审阅计划

- 追加复查和索引刷新后，旧计划 `translation_plan_review_ai_default_2026-11-17.json` 仍绑定 `source_catalog.refresh-2026-11-16.json` 与旧 AI 索引摘要，已不适合作为当前审批对象；文件保留作历史记录。
- 以当前 `source_catalog.append-2026-11-17.json` 和 AI 索引生成新计划：`projects\祝福のネトラレラ\Workflow\Plans\translation_plan_review_ai_append_2026-11-17.json`。`translation_plan_approval.load_translation_plan` 验证摘要为 `1d7ae1cef2a318d79fccb9948b4e2de79799b9d087978922f08592a4b7a79283`；状态 `ready_for_review`，88 话/88 个 AI 正文及对应归档 provenance 有效，profile 为 `ai-efficient-v1`，0 问题，计划不含正文。
- 本次计划写入 1 个仅含映射/来源元数据的 JSON 文件；0 网络请求、0 Provider 调用。新摘要仍需人工审阅，未经明确批准不得创建回执或执行翻译。当前人工审阅入口见[试点映射人工审阅](handoffs/2026-11-16-pilot-plan-review.md)。

## 2026-11-17 试点数据落点与目录复核

- 只读解析 `projects/祝福のネトラレラ/workflow_paths.json`，确认 `human_edition_root` 和 `output_dir` 解析到用户指定的括号版外部 `生肉`、`熟肉` 目录；两个路径均存在。人读根包含 `SOURCE_MAP.json` 和 3 个章节目录，Markdown 话数分别为 30、40、18，共 88；译文根当前为空。
- `RAWs_AI/` 当前有 88 个单话 Markdown 与 `catalog.json`。该历史检查点中 `SourceArchive/` 下的 `source_manifest.json` 校验为 268/268，`source_editions_manifest.json` 校验为 444/444；当时目录文件计数还包含后来迁出的计划 JSON 与其他非 Markdown artifact。计划迁出后，`SourceArchive/` 不存计划或审批回执；文件总数不替代 manifest 校验结果。
- 使用当前 `source_catalog.append-2026-11-17.json` 执行默认 AI `--plan-only`，没有指定 `--source-edition` 或 `--plan-output`：退出码 0，`ready_for_review`，88 话/88 个来源有效，0 问题；stdout JSON 不含原文。此项只读核验未生成译文或审批回执。
- 命令：`.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_manifest.json` 与同路径的 `--manifest source_editions_manifest.json`，分别返回 268/268 和 444/444。只读 plan-only 命令为 `scripts\run_kakuyomu_workflow.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.append-2026-11-17.json --translation-root <用户指定熟肉路径> --plan-only`。

## 2026-11-17 AI 与人读版清洗产物可重复验证

- 新增只读入口 `scripts/validate_source_editions.py`，以当前 catalog 和 manifest 中的 raw_source 字节重新运行 AI/人读两套 cleaning profile，再比较两份索引、不可变 edition archive 与 AI/人读镜像文件。它验证的内容比 manifest 哈希更完整：可发现清洗器输出与当前 profile 不一致，即使索引、归档和镜像文件彼此哈希一致。
- 对当前试点执行 88 话核验，结果 `status=verified`，`episode_count=88`，累计 raw 输入 793,183 bytes，AI 输出 774,253 bytes，人读输出 799,293 bytes。所有 raw lineage、目录映射、索引字段、归档/镜像字节与重算清洗结果一致；stdout 仅有计数和摘要哈希，无原文，未写入项目或书籍数据。
- 随后不传 `--source-edition` 重跑默认 Kakuyomu `--plan-only`：`ready_for_review`，88/88 来源有效；计划绑定 `ai-efficient-v1`，首话 `source_file` 位于 `editions/ai-efficient-v1/`。网络请求、Provider 调用、文件写入均为 0，计划没有原文内容。
- 复现命令（从仓库根目录运行）：

  ```powershell
  .\.venv\Scripts\python.exe scripts\validate_source_editions.py `
    --source-root projects\祝福のネトラレラ\SourceArchive `
    --catalog source_catalog.append-2026-11-17.json `
    --human-root ..\祝福のネトラレラ(祝福的寝取系女主)\生肉 `
    --ai-root projects\祝福のネトラレラ\RAWs_AI
  ```

- 合成回归：`.venv\Scripts\python.exe -m unittest tests.test_source_editions -q`，19 项通过；另有本脚本及关联模块的 `py_compile` 与 CLI `--help` 通过。该检查确认 profile 的逐字节可重复性，不替代章节语义、目录映射或目标阅读器视觉效果的人工验收，也不验证真实 Provider 翻译。

## 2026-11-17 试点 Provider 阶段模型配置

- `pipeline.py::Config.load_config` 现支持 `INITIAL_MODEL`、`PROOFREAD_MODEL`、`STYLE_MODEL` 环境变量覆盖；环境变量优先于 JSON 配置，未设置时保留既有代码默认值。`.env.example` 给出可选模型字段，不启用任何授权或网络请求。
- 当前被 `.gitignore` 排除的根 `.env` 已按用户既有决定配置试点：三阶段主模型为 JOJO `gpt-6-Luna`，JOJO 阶段失败时允许一次 JYQF `deepseek-v4.1-flash` 回退；类别 allowlist 仅含两者职责所需的 `source_text`、`translation_text`、`book_knowledge`。未授权 `evaluation_samples`、Gemini 或 Notion。配置不含 API key。
- 本地只读 `Config.load_config(project="祝福のネトラレラ")` 解析出上述模型、回退和类别策略，并得到 88 条经 AI 版本清单绑定的章节映射。Process/User/Machine 与 `.env` 均未配置 JOJO/JYQF key 或 `BASE_URL` 覆盖；代码中存在候选默认 URL。模型 ID、服务账号、端点连通性/协议兼容、费用和真实质量仍未验证，没有调用 Provider。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts -q`：105 项通过，覆盖新环境变量优先于 JSON 配置及现有 provider/model 路由契约。另行只读加载试点项目得到 88 条 AI 映射和预期模型/allowlist；调用 provider preflight 后按预期以 `Missing required provider credentials: JOJO_API_KEY, JYQF_API_KEY` 停止，没有发出请求。真实翻译仍受缺少凭据、人工计划审批和 AI 版本绑定的已审核全书概要限制。
- 后续合并回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q`：121 项通过，覆盖 AI 版默认计划、项目模式归档 provenance/输入映射和 Provider 配置/路由；该历史检查点的正文读取仍使用归档路径，当前镜像读取由本页顶部更新。预期故障注入日志不代表真实服务请求。未调用 Provider。

## 2026-11-17 独立 Kakuyomu 采集的项目新鲜度留档

- `scripts/ingest_kakuyomu_pages.py` 新增显式 `--project <项目名>`。该模式在发出请求前校验 `--source-root` 与 `--output-root` 都是所选项目的 `SourceArchive/`，且只接受默认 `source_manifest.json`；路径不匹配时不创建 adapter、不请求页面。未传 `--project` 时保持原有 source-only 行为。
- 项目模式在采集返回后，将当前 `source_manifest.json` 的全部历史合并到 `source_editions_manifest.json`，保留已有 AI/人读 edition artifacts，不重跑清洗器、不改写清洗 Markdown 或 `RAWs_AI/catalog.json`。随后以合并清单为锚，追加内容寻址的 downstream freshness schema v2 快照；报告只含 manifest/输入哈希、状态和详情，不含正文。
- 快照新增 `ai_edition_index` consumer：对照当前 source manifest、edition manifest、catalog 路径/摘要和完整话目映射。清单或 catalog 前进后将旧索引记为 `stale`；首次采集或缺少索引记为 `unverified`；索引结构/归档校验失败记为 `invalid`。若 AI 索引过期，已审核全书概要同时记为 `stale`。旧 TM/知识记录仍按其已归档的 AI 版本核验；AI 索引状态明确表示默认翻译输入尚未刷新，项目翻译配置本身也会因过期索引失败关闭。
- 该入口不自动运行 AI/人读双版本清洗，也不更新索引或重建译文/知识/概要。需要完成整条采集到双版本清洗和 AI 默认翻译输入时，使用 `scripts/run_kakuyomu_workflow.py`；来源变更后旧译文仍保留，待新的 AI 版本及审核映射就绪后再按现有门禁处理。
- 合成验证：`.venv\Scripts\python.exe -m unittest tests.test_source_editions -q`，14 项通过；`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source -q`，33 项通过。覆盖来源历史合并/幂等、现有 AI 索引在来源前进后变为 stale、无索引的首次项目采集快照，以及错误项目根在请求前失败。`.venv\Scripts\python.exe -m py_compile source_editions.py scripts\ingest_kakuyomu_pages.py tests\test_source_editions.py tests\test_kakuyomu_page_source.py` 与 `git diff --check` 通过。未访问真实站点、Provider、Notion 或真实书籍数据。

## 2026-11-17 采集后双版本自动清洗与 AI 默认输入

- `scripts/run_kakuyomu_workflow.py::run_workflow` 在来源采集完整且所有话目 `normalized_source` 物化后，先调用 `prepare_source_editions` 生成 AI/人读两版，再生成默认 AI 版计划。采集未完成时不清洗、不生成计划。正式执行同样使用这次生成并通过索引/清单/哈希/lineage 校验的 AI 版。
- 项目 `workflow_paths.json` schema v1 保留必需 `output_dir` 并允许 `human_edition_root`。相对路径按项目根解析；没有该项时人读根默认为 `<项目>/生肉`。试点本地忽略配置继续指向用户指定外部 `熟肉`，并新增外部 `生肉` 人读根；两者与 AI 目录/SourceArchive 分离。实书只读配置核验得到 88 条 AI 映射，首话输入为 `editions/ai-efficient-v1/`，两个用户指定外部路径匹配且人读/译文根不重叠；未写入书籍目录或调用 Provider。
- `source_editions.py::_index_refresh_is_safe` 允许索引在来源/清洗清单哈希更新、catalog 路径变化、作品公开话数递增时刷新，但要求旧话目逐项元数据/来源版本保持一致，旧章节顺序与边界保持稳定，变化只能是原末卷尾部扩展或追加新卷。既有清洗文件仍须逐字节匹配，用户改写的 Markdown 或旧话来源变化会拒绝刷新。
- 回归：`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`：177 项通过。仓库 E2E runner 定向命令 `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项通过，使用合成 Kakuyomu 页面和本地 mock Provider；TM 中逐段原文与 AI 版归档内容一致。未访问 Kakuyomu 或真实 Provider。
- 未完成：真实目录增量采集、试点 88 话 AI/人读结果的人工内容/阅读器验收、真实 Provider 单话翻译仍待独立验证。

### 2026-11-17 历史代码审阅项复核

- 复核此前 PR #58 快照中记录的两个实现风险。当前工作树中的 `kakuyomu_page_source.py` 将 `http.client.IncompleteRead` 映射为可暂停的 `SourceUnavailable`；采集器持久化 checkpoint 后可重试续跑。当前 `epub_builder.py` 同时把带目录的相对路径解析为绝对路径，并在版本探测前用 `shutil.which` 将裸命令名固定为绝对路径，保证切换到临时 `cwd` 后仍调用同一 Pandoc executable。
- 定向回归命令 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source.KakuyomuPageAdapterTests.test_incomplete_response_and_timeout_pause_collection_and_can_resume tests.test_epub_builder.PandocExecutableResolutionTests tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts.TestTestWorkspaceConfiguration -q`：43 项通过。
- CLI `--help` 明确显示默认输入为 AI 清洗版，`normalized_source` 是显式兼容覆盖。当前试点只读 `--plan-only` 复核为 `ready_for_review`、`ai-efficient-v1`、88/88 来源有效、0 问题、0 网络请求、0 Provider 调用、0 文件写入，且报告不含原文。复核仅读取当前 catalog、manifest、清洗索引及版本文件；未生成计划文件或译文。
- 以上只验证本地实现、合成回归和当前文件一致性，不验证站点新增正文、翻译质量或人读版视觉效果。88 话映射/清洗验收、AI 来源绑定的全书概要审核、有效 Provider 凭据及受控首话翻译仍待完成。

### 2026-11-17 当前工作树补充

- 重跑历史审查项的精确聚焦集合：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source.KakuyomuPageAdapterTests.test_incomplete_response_and_timeout_pause_collection_and_can_resume tests.test_epub_builder.PandocExecutableResolutionTests tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts.TestTestWorkspaceConfiguration -q`，45 项通过。另单跑 `tests.test_epub_builder` 为 24 项通过。Pandoc 回归覆盖裸命令名 PATH 解析和相对 executable 的预检/转换一致性；HTTP 回归覆盖不完整响应暂停及恢复。
- 本次完整非 E2E 回归动态发现测试模块运行 513 项，0 失败、4 项因 Windows 符号链接/FIFO 能力跳过。测试使用本地合成数据；未调用真实 Provider、Notion 或站点。
- 本次仅追加 Pandoc 可执行文件解析用例和代码修复，并更新本交接与验证记录；其余工作区变更保留，未暂存、提交或清理。

## 2026-11-17 Kakuyomu 编排自动记录下游新鲜度

- 完整采集、双版本清洗和计划生成后，`scripts/run_kakuyomu_workflow.py` 会审计当前项目已存在的 TM、`KNOWLEDGE_PROVENANCE_draft.json` 和已审核 JSON 概要，并在 `SourceArchive/` 下以内容寻址方式追加只读快照。成功完成翻译后再审计一次，记录运行后状态；如果没有下游文件，则报告 `not_needed`。审计无法安全完成时，工作流报告 `unavailable`，不伪称已记录。
- 快照 schema v2 绑定 source manifest SHA-256、TM/知识 JSON 的规范化内容 SHA-256、已审核概要 SHA-256 和状态详情；不写入原文、译文或概要正文。相同来源和消费者状态重跑会复用既有快照；状态变化会创建新文件，不覆盖旧快照或消费者数据。`scripts/ingest_kakuyomu_pages.py --project` 也会在项目采集后自动记录来源及下游状态；source-only Kakuyomu 模式与本地导入 CLI 仍需显式调用快照命令。快照不替代消费者自己的运行时来源门禁，也不自动重建下游。
- `.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_kakuyomu_workflow tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`：186 项通过。`.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过（226.138 秒）。E2E 覆盖原有主页到翻译链路；本轮新快照侧车同时由单测覆盖。未请求真实 Kakuyomu 或 Provider。相关源码/测试 `py_compile`、`git diff --check` 和 8 份主要文档本地链接检查均通过，后者不校验锚点。
- 2026-11-17 I4 当前工作集复核：`.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_pipeline_contracts tests.test_story_summary_review tests.test_tm_provenance_unit tests.test_tm_review tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_kakuyomu_workflow tests.test_source_editions -q`，200 项通过。覆盖 TM/知识/概要/AI 索引审计、manifest 绑定快照追加与复用、损坏快照拒绝、审计期间 manifest 变化拒绝及采集/编排接入；仅运行合成单测，没有访问 Kakuyomu 或真实 Provider。

## 2026-11-17 默认 AI 清洗版翻译输入

- 本节记录的早期接入检查点中，Kakuyomu 与通用项目模式都将不可变 AI 归档版本作为实际正文读取路径；这一实现与用户后续明确的目录职责不符，已由本页顶部“RAWs_AI 作为默认翻译输入”记录更正。当前模式仍验证 AI 索引、对应 catalog 摘要、完整 episode 元数据、清洗清单、归档哈希和来源 lineage，但翻译正文必须从 `RAWs_AI` 读取。
- 若没有选中项目且未提供 JSON 配置，通用流水线现直接报错，不再静默退回仓库根目录的 `生肉/`。显式 JSON 配置仍是旧项目指定其他来源的兼容入口。
- 当时工作树的默认参数 `--plan-only` 预览曾生成 `projects\祝福のネトラレラ\SourceArchive\translation_plan_review_ai_default_2026-11-17.json`。计划摘要 `8a5679563c376f3ed9dcfdcd5115db77149cf77189c46c5e544eb215c4dcd4d7` 重算一致；状态 `ready_for_review`，88/88 话的 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题，episode ID/位置/译文目标/TM key 各自唯一，88 个译文目标均不存在。计划不含正文；生成时 0 网络请求、0 Provider 调用、1 次文件写入（仅计划 JSON）。该计划后来因 catalog 追加和 AI 索引刷新而过期；历史计划文件已移至 `Workflow/Plans/`，当前审阅计划见本页“追加 catalog 后刷新 AI 审阅计划”。`SourceArchive/` 只存来源归档和校验材料。
- 回归：`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`，166 项通过。覆盖默认选 AI、AI 不可用时阻断、显式 normalized_source 兼容覆盖、参数冲突拒绝、审批摘要绑定和 pipeline 来源版本复核。
- 默认输入 fail-closed 回归：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestTestWorkspaceConfiguration -q`，23 项通过。新增测试确认没有可选项目时不回退仓库根 `生肉/`；唯一项目下无参数自动发现、AI 索引失效阻断和显式 JSON 兼容均有独立覆盖。
- 默认输入修复后的完整非 E2E 回归：

  ```powershell
  .\.venv\Scripts\python.exe -m unittest `
    tests.test_align_chapters_unit tests.test_epub_builder tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source `
    tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_knowledge_batching tests.test_knowledge_extraction_unit `
    tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_local_source_ingestion_cli tests.test_pipeline_contracts `
    tests.test_rag_engine_unit tests.test_scratch_filter tests.test_security_path_traversal tests.test_source_ingestion `
    tests.test_source_manifest tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_story_summary_review `
    tests.test_tm_provenance_unit tests.test_tm_review tests.test_translation_plan_approval -q
  ```

  449 项运行、445 项通过、4 项跳过、0 项失败；3 个符号链接用例因普通 Windows 权限下创建链接返回 `WinError 1314` 而跳过，1 个 FIFO 用例因 Windows 不支持 `os.mkfifo` 而跳过。输出中的磁盘写入、Provider 错误和无效响应日志来自预期负向 fixture。该回归使用合成数据，不代表真实 Provider 或翻译质量验收。
- E2E：`.venv\Scripts\python.exe tests\run_tests.py`，本地 mock runner 7 项通过（229.541 秒，退出码 0）。该历史检查点的端到端 fixture 覆盖主页目录发现、归档、双版本清洗、默认 AI 输入、AI 来源概要/计划审批及 mock 翻译；TM 保存的原文与计划绑定的 AI 归档内容一致，但因归档与镜像相同，该断言不单独证明运行时读取根目录。其他错误/拦截日志来自预期负向 fixture。
- CLI `--help` 显示 `--source-edition` 默认 AI，`--plan-only` 默认核验并选用 AI；计划摘要绑定 AI profile、索引和版本清单哈希。未生成译文或调用真实 Provider。当前计划需人工审阅，后续正式执行仍需 AI 版本对应的已审核全书概要、匹配的审批回执和本地 Provider 授权/配置。
- 通用项目模式早期回归使用合成 `SourceArchive/RAWs_AI` 项目验证 AI 版本映射、catalog 摘要、完整 episode 元数据、译文路径/TM 键和 AI 版本 ID；该旧测试检查点读取归档文件，不等同于当前 `RAWs_AI` 直接读取契约。AI 索引、catalog 过期或 AI 版缺失时均不回退到人读版。显式 JSON 配置仍可指定其他输入目录。
- 2026-11-17 通用入口早期验证：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow -q`：131 项通过。只读配置解析返回 88 项版本映射，核验了 archive root 和 `editions/ai-efficient-v1/` provenance；该记录未分别输出 `RAWs_AI` 输入路径，不能作为直接读取位置的证据。译文根解析为用户指定外部 `熟肉`；没有调用 Provider 或写出译文。
- 通用入口变更后的 `.venv\Scripts\python.exe tests\run_tests.py`：7 个本地 mock E2E 测试通过，240.957 秒，退出码 0；negative fixture 的 content filter/段落契约日志属于预期失败覆盖。`.venv\Scripts\python.exe -m py_compile pipeline.py tests\test_pipeline_contracts.py`、`git diff --check` 均通过；14 份 Markdown 检查 183 个本地文件链接，0 个目标缺失。验证未调用真实 Provider、Kakuyomu、Notion 或阅读器。
- 2026-11-17 项目默认翻译入口的全书概要门禁：`Config.load_config(project=...)` 固定启用 `REQUIRE_REVIEWED_STORY_SUMMARY` 并将路径设为 `Knowledge/STORY_SUMMARY_reviewed.json`。`TranslationPipeline` 先按默认 AI `CHAPTER_MAP` 构造完整有序文件名/`source_version_id` 集，再验证 approved bundle 的全书覆盖和版本；概要缺失、未批准、过期或映射不符时，在读取作品信息、构造 RAG 或调用 Provider 前停止。显式 JSON 配置仍保留旧 Markdown 概要兼容路径。
- 回归：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_story_summary_review tests.test_kakuyomu_workflow tests.test_source_editions -q`：142 项通过。新增配置断言确认 `--project` 同时选择 AI 清洗来源并强制 reviewed 全书概要。
- 真实项目只读复核：`Config.load_config(project="祝福のネトラレラ")` 解析为 `SourceArchive`、88 条 AI 映射，首话位于 `editions/ai-efficient-v1/`；当前 `Knowledge/` 仅有旧 `STORY_SUMMARY.md`，无 `STORY_SUMMARY_reviewed.json`。创建 `TranslationPipeline` 按预期以“requires an approved full-book story summary”失败，尚未加载知识、构造 RAG 或调用 Provider。当前不能开始正式翻译；需先按 AI 版完整映射生成概要候选、人工审核并发布匹配 bundle。
- 代码改动后的 `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，221.968 秒，runner 退出码 0。runner 中可见的内容拦截和段落数量异常来自预期负向 fixture；没有连接真实 Provider。`.venv\Scripts\python.exe -m py_compile pipeline.py tests\test_pipeline_contracts.py`、`git diff --check` 与 9 份更新 Markdown 的 128 个本地文件链接目标检查均通过。
- 该历史复核点曾把 `raw_file` 指向 `SourceArchive/editions/ai-efficient-v1/` 并直接读取归档文件；用户之后明确 AI 版实际文件应从 `RAWs_AI` 读取。当前映射字段已拆分：`raw_file`/`source_version_id` 只记录归档来源，`source_input_file`/`source_sha256` 指向镜像正文。`--ai-edition-root` 覆盖 AI 根；仅显式 `--source-edition normalized_source` 才切换为采集器规范化文本。
- 无参数项目选择现仅在存在唯一非示例项目时自动发现；同时存在多个项目时 fail-closed，要求 `--project` 或 `TRANSLATOR_PROJECT`，避免按文件系统顺序选错书。回归覆盖多项目拒绝和排除 `example/`。
- 本次历史复核：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_pipeline_contracts tests.test_source_pipeline_linkage -q`，137 项通过；指定本地 mock E2E 1 项通过。E2E 验证 TM 原文与当时计划绑定的 AI 归档字节一致；该相等性没有区分相同字节的 `RAWs_AI` 镜像路径。此后的直接镜像读取契约见本页顶部。
- 用户再次强调：AI 版原文就是翻译系统默认读取的干净原文，双版本清洗的 AI 分支直接服务后续翻译。2026-11-17 该历史回归 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q` 为 120 项通过；当时覆盖计划预览默认选择 AI 版、项目模式读取已验证 AI 归档，以及 AI 版不可用时失败关闭。当前 `RAWs_AI` 实读由单独使用不同合成归档/镜像内容的回归验证；没有调用 Provider 或写出译文。

## 2026-11-17 I4 版本化译文复用保护

- 通用版本化翻译入口之前会在目标文件存在时直接跳过，无法区分当前来源版本的有效译文与旧版/未索引译文。现在 `pipeline.py::run_chapter` 对带 `source_version_id` 的章节检查既有输出和 TM：只有原文版本、输出字节、TM 段落配对和来源 provenance 全部吻合当前映射时才跳过；任何已有输出或 TM 不匹配时抛出 `FileExistsError` 并保留原字节，不覆盖人工译文或 TM。
- `chapter_transaction.py::is_chapter_translation_committed` 复用逐章提交所用的规范化段落和 provenance 结构执行该检查。无版本 ID 的旧式显式目录保持原兼容行为；Kakuyomu 计划和正式入口本已有自己的既有译文冲突门禁。
- 回归新增当前 source version 匹配时跳过、来源版本过期时保留并阻断两项；正向复用测试含多段译文，在 Windows CRLF 写盘后验证按统一换行读取仍可正确识别已提交结果。`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_downstream_freshness_snapshot -q`：139 项通过。`.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，223.785 秒、退出码 0。`.venv\Scripts\python.exe -m py_compile chapter_transaction.py pipeline.py tests\test_pipeline_contracts.py` 和 `git diff --check` 通过。
- 本书只读 `Config.load_config(project="祝福のネトラレラ")` 返回 88 条 AI 归档映射，首条带 AI `source_version_id`。没有生成译文或调用真实 Provider。
- 在本增量形成时，`scripts/snapshot_downstream_freshness.py` 需要显式运行，尚未接入原文刷新路径。后续 Kakuyomu 编排和 `ingest_kakuyomu_pages.py --project` 已自动追加 manifest 绑定快照；这只持久化独立审计结果，不把 `stale` 写回译文、TM、知识或概要，也不自动重建派生物。source-only 与本地导入路径仍需显式审计；其他路径是否需要自动触发及是否需要消费者状态写回，需按其数据契约另行定义，不能由快照代替。

## 2026-11-17 I4 已审核全书概要新鲜度

- `scripts/snapshot_downstream_freshness.py` 新增 `--story-summary`，并要求同时传入 `--project` 或 `--config`。脚本通过当前版本化章节映射核对来源根目录、manifest 和全书文件/版本覆盖，再验证概要已批准、全书覆盖完整，且每个来源版本仍然有效。
- 快照只记录概要文件名、SHA-256、状态和校验详情，不写入摘要正文；当前概要可记为 `verified`，来源 raw 版本推进后可记为 `stale`。原始 manifest 在审计期间变化时仍拒绝生成快照，输出文件已存在时不覆盖。
- `.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot -v`：7 项通过，包含概要 verified/stale、正文不进入快照和既有消费者审计回归。
- 合并定向回归 `.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_pipeline_contracts tests.test_story_summary_review tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow -q`：163 项通过。只读解析真实项目默认配置得到 88 条映射，来源根为 `SourceArchive`，清单为 `source_editions_manifest.json`，首话来自 `editions/ai-efficient-v1/` 并绑定 AI 版本 ID；默认译文根为指定外部 `熟肉`。未调用 Provider、未生成译文。
- 该增量验证的是操作者显式运行的只读审计快照。后续 Kakuyomu 完整编排与 `ingest_kakuyomu_pages.py --project` 已自动追加快照，但快照仍不修改译文、TM、知识或概要，也不重建派生物；这些消费者通过自己的运行时来源门禁阻断过期输入。

## 2026-11-17 双版本原文清洗与试点导出

- 试点归档库位于 `projects\祝福のネトラレラ\SourceArchive`；该位置只保留 catalog、checkpoint、metadata、raw/normalized/清洗版本 artifacts、manifest 和来源校验快照。AI 清洗版位于项目 `projects\祝福のネトラレラ\RAWs_AI`，是翻译正文的实际读取位置。计划报告与审批回执分别放在 `Workflow/Plans/`、`Workflow/Approvals/`，不得放入归档库；此前误放的 5 份计划已迁出。用户指定的外部 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 专用于人类阅读版，译文根为同书外部 `熟肉`。旧的仓库内默认 `生肉`、`熟肉` 不作为本书目标。
- `scripts\export_source_editions.py` 直接读取当前 manifest 验证过的 `raw_source`；每话先核验 normalized→raw lineage，再要求 normalized bytes 与 raw bytes 完全一致，之后才分别执行 `ai-efficient-v1` 和 `human-reading-v1`。同一份完整采集原文因此只采集一次、清洗分成两路：AI 版优先提高识别效率，统一 LF、去除每段一个 U+3000、ruby 转为 `基字《读音》`、旁点转 Markdown 强调；人读版优先改善阅读呈现，统一 LF、保留 U+3000，以 HTML Ruby 和 CSS `text-emphasis` 呈现振假名/旁点。人读文件路径为 `<章节名>\<话名.md>`；AI 版按章节序号/ID 与 episode ID 分层。两种索引记录共同 raw 输入版本、normalized 来源版本、输入哈希、profile 与输出哈希。归档源文件只读，既有不匹配导出文件会导致停止，不会覆盖。
- 实际命令使用 `--edition-manifest source_editions_manifest.json --refresh-indexes`。完成 88 话、3 个章节分组；新增 176 个不可变 AI/人读归档版本和独立版本清单，按白名单更新 `catalog.json` 与 `SOURCE_MAP.json`。首次导出报告 `created_files=177`、`reused_files=176`、`updated_files=2`；两根目录原有 176 个 Markdown 均与生成字节一致。输入 793,183 bytes，AI 版 774,253 bytes，人读版 799,293 bytes。基础采集清单 `source_manifest.json` 保持 268 个文件型 artifact；`source_editions_manifest.json` 合并来源历史和 176 个派生版本，共 444 个文件型 artifact。
- `.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`：162 项通过，覆盖导出/幂等、AI 计划选源、目录缺话与文件篡改拒绝、pipeline 版本绑定、运行入口选用 AI 清单、审批摘要绑定 profile/索引/清单哈希，以及来源链接和全书概要门禁。
- `.venv\Scripts\python.exe scripts\validate_source_manifest.py --root projects\祝福のネトラレラ\SourceArchive --manifest source_manifest.json`：268/268 文件通过；同命令校验 `source_editions_manifest.json` 为 444/444。实际 AI `--plan-only` 返回 `ready_for_review`、88/88 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题、0 网络/Provider/文件写入且不含正文；人读索引、镜像和版本归档 88/88 哈希匹配。幂等重跑 `created_files=0`、`updated_files=0`、`reused_files=355`。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，236.923 秒，runner 退出码 0。请求只发送到 runner 启动的 loopback mock server；输出中的内容拦截和段落契约错误来自预期负向 fixture。
- `py_compile`、编排器和导出器 CLI `--help`、`git diff --check` 通过。翻译入口现在默认从 `--source-root` 同级 `RAWs_AI` 使用 AI 清洗版本；`--ai-edition-root` 仅覆盖目录，只有显式指定 `--source-edition normalized_source` 才选择采集器规范化版本。AI 计划摘要绑定 profile、索引哈希、版本清单哈希及逐话归档路径/版本，pipeline 从 `source_editions_manifest.json` 再校验文件。没有创建译文或调用 Provider。映射/输出路径仍待人工审阅，全文概要需绑定 AI 版本后才能通过正式运行门禁；HTML/Ruby 在目标阅读器中的实际渲染、全书人工逐段保真仍待用户验收。`raw_source` 是 collector 提取的 UTF-8 可见文本，不是原始 HTML。

## 2026-11-17 Token预算分批全书知识预读

- `scripts/auto_extract_knowledge.py --full-book` 现在要求显式提供 `--tokenizer-json`、`--context-window-tokens`、`--max-output-tokens`、`--safety-margin-tokens` 和 `--message-overhead-tokens`，并保留全书 `--max-input-characters` 总字符上限。tokenizer JSON 必须对应 `Config.PROOFREAD_MODEL`；代码不猜测模型的 tokenizer 或上下文容量。`requirements.txt` 增加 `tokenizers`，本机 `.venv` 安装并验证的版本为 0.23.3。
- 本地预算按 system/user 两段文本分别计 tokenizer tokens，再加调用者给定的消息开销；每请求输入上限为 `context_window_tokens - max_output_tokens - safety_margin_tokens`，且请求显式设置 `max_tokens`。若服务返回 `usage.prompt_tokens` 且超出上限，则拒绝生成草稿。未验证端点 tokenizer、服务端 chat template/开销、context 参数或 `max_tokens` 兼容性；这些必须与实际 `Config.PROOFREAD_MODEL` 配套核定。
- 全部章节按配置顺序拆分成段落，给每段分配本地稳定 ID（章节序号+段落序号；不是 Kakuyomu DOM 的 `p` ID），每段只进入一个请求。每批最多 500 段，最多 100 次 Provider 调用；单段超预算、批次数超限、超大响应或任一请求失败时不写知识草稿。全书字符预算、每章 16 MiB 读取上限及 16 MiB 草稿文件上限仍生效。
- 每批只允许输出当前批次引用的 glossary、summary、worldbuilding、narrative_voice 候选；缺少来源 ID、跨批引用、术语未出现在引用段落、冲突译名、被截断的响应均失败关闭。全部批次成功后按源顺序确定性合并，并记录 tokenizer SHA-256、每批输入/响应哈希与估算/Provider 回报 token、逐段覆盖和结论级来源位置。概要审核规范会保留这些字段，并核对段落覆盖、批次归属、位置与候选文本哈希。
- 跨批汇总目前是按来源顺序排列的候选集合，不调用第二次模型做全书综合，不能称为具备完整跨章因果梳理的连贯概要。Kakuyomu 正式翻译入口仍要求 approved 全书概要来源与当前 `CHAPTER_MAP` 一致；本增量未修改该门禁，也未调用真实 Provider、Kakuyomu、Notion 或真实书籍正文。
- 定向验证：`.venv\Scripts\python.exe -m unittest tests.test_knowledge_batching tests.test_knowledge_extraction_unit tests.test_story_summary_review tests.test_knowledge_review tests.test_kakuyomu_workflow -q`，75 项通过；覆盖 tokenizer 文件解析、预算边界、完整段落分批、跨批 claim 证据、审核保留与失败不写草稿。
- 完整回归：23 个模块 `.venv\Scripts\python.exe -m unittest tests.test_align_chapters_unit tests.test_epub_builder tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_knowledge_batching tests.test_knowledge_extraction_unit tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_local_source_ingestion_cli tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_scratch_filter tests.test_security_path_traversal tests.test_source_ingestion tests.test_source_manifest tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_story_summary_review tests.test_tm_provenance_unit tests.test_tm_review tests.test_translation_plan_approval -q`：431 项运行、427 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，220.525 秒，退出码 0。请求只发送到 runner 启动的 loopback mock server；输出中 content-filter、段落契约和 Provider 失败堆栈来自负向 fixture。
- 修改文件 `py_compile`、知识抽取/概要审核 CLI `--help`、`.venv\Scripts\python.exe -m pip check`、`git diff --check` 通过；对 9 份改动 Markdown 的本地链接目标检查均存在（不校验标题锚点）。验证未调用真实 Provider、Notion、Kakuyomu 或真实书籍正文；未验证真实 tokenizer 与目标模型/端点匹配、全书候选语义或人工质量。

## 2026-11-17 试点来源与运行配置复核

- 本节较早的路径检查按 `生肉`/`熟肉` 命名暂记录为原文根/译文根。用户后续明确：外部 `生肉` 专用于人类阅读版，外部 `熟肉` 专用于译文；采集归档已搬至项目 `SourceArchive`，AI 清洗版位于项目 `RAWs_AI`。因此不能把外部生肉目录当采集版本归档根。最终目标与导出结果见[双版本原文清洗与试点导出](#2026-11-17-双版本原文清洗与试点导出)。
- `.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <活动来源根> --manifest source_manifest.json` 返回 `schema_version=1 artifacts=268 files_verified=268`。只读计划命令 `scripts\run_kakuyomu_workflow.py --source-root <活动来源根> --catalog source_catalog.discovered.json --translation-root <活动译文根> --plan-only` 返回 `ready_for_review`、88 episodes、88 verified sources、0 issues，网络/Provider/写入计数均为 0，`source_text_included=false`。这两个命令读取源文件以核对哈希，但没有输出正文；计划预览不是人工批准或文本格式验收。
- 本节的 Provider 存在性检查发生在本机试点 `.env` 创建前，是该先前检查点的历史快照：当时根 `.env` 不存在且 Process/User/Machine 未配置相关变量。当前模型/allowlist 设置及最新 key/endpoint 状态见[试点 Provider 阶段模型配置](#2026-11-17-试点-provider-阶段模型配置)。
- 迁移前 plan-only 曾使用外部 `生肉` 作为 `--source-root`；该路径角色已被用户后续明确为人读版。当前 plan-only 以项目 `SourceArchive` 为来源、外部 `熟肉` 为译文根，最终结果见本节首段链接。

## 2026-11-16 全书知识预读输入模式

- `scripts/auto_extract_knowledge.py` 增加显式全书运行参数：`.\.venv\Scripts\python.exe scripts\auto_extract_knowledge.py --full-book --max-input-characters <正整数>`。脚本依当前 `CHAPTER_MAP` 顺序或目录扫描顺序读取全部配置章节，最多 1000 章；任一章节超过 16 MiB 或整份提示词样本超过字符预算时，在 Provider 客户端创建及草稿写入前停止，不截断后继续调用。
- 全书提示要求返回 `glossary`、`summary`、`worldbuilding`、`narrative_voice`。provenance `input_coverage` 记录 `all_configured_chapters`、配置/实际覆盖章节数、Unicode 字符数和显式上限；`source_files` 覆盖每个配置章节（包括空章节），列出源哈希、实际输入范围/哈希和段落数。语义证据仍限于术语精确子串定位，不为概要、世界观或叙述习惯逐条归因。
- 下游知识/概要审核现支持最多 1000 个来源；逐源校验仍受每文件 16 MiB、累计 128 MiB 上限约束。provenance 的全书计数在审核发布前会与实际 source_files 数核对，空正文话目可作为 0 字符/0 段落来源保留。该实现不自动证明配置章节集等于完整公开目录；输入上限不等于 tokenizer token 数或 Provider 上下文容量，且没有系统提示/回复预算计算、分批抽取或跨章合并。首个试点翻译第 1 话前仍须人工确认 88 话映射覆盖，并核定实际模型容量。未执行真实 Provider、Notion、Kakuyomu 请求或真实正文抽取。
- Kakuyomu 正式翻译入口 `scripts/run_kakuyomu_workflow.py` 现要求已批准的全书概要 bundle，并核对其全书覆盖及有序文件名/来源版本与本次完整 `CHAPTER_MAP` 一致；缺失或不匹配时返回 `full_book_knowledge_required`，在创建翻译管线或调用 Provider 前停止。直接调用通用 `TranslationPipeline` 的路径不受此入口门禁约束。
- 第 1 话正式翻译前仍须人工确认 88 话映射覆盖，并核定实际模型容量。尚未实现目录完整性证明、tokenizer-aware 预算、分批抽取、结论级证据和跨章合并。没有执行真实 Provider、Notion、Kakuyomu 请求或真实正文抽取。
- 定向回归：`.venv\Scripts\python.exe -m unittest tests.test_story_summary_review tests.test_kakuyomu_workflow -q`：27 项通过，覆盖全书 bundle 校验、Kakuyomu 入口在缺少/不匹配审核概要时阻断，以及审核概要通过后继续执行。
- 相关单测：22 个模块运行 423 项，419 项通过、4 项因 Windows 普通权限无法创建符号链接/不支持 FIFO 跳过，0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，219.088 秒，退出码 0。Kakuyomu 首页→目录→普通 episode URL→归档→来源版本化概要审批→mock 翻译路径通过；所有网络请求仅发往本机 loopback mock server。负向 fixture 输出的拦截/段落异常是预期行为。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py scripts\auto_extract_knowledge.py scripts\apply_knowledge_review.py scripts\run_kakuyomu_workflow.py story_summary_review.py tests\test_e2e.py tests\test_kakuyomu_workflow.py tests\test_knowledge_extraction_unit.py tests\test_knowledge_review.py tests\test_pipeline_contracts.py tests\test_rag_engine_unit.py tests\test_story_summary_review.py tests\test_tm_review.py`、两个 CLI 的 `--help` 与 `git diff --check`：通过。验证使用合成 fixture，未调用真实 Provider、Notion 或 Kakuyomu。

## 2026-11-16 TM 默认审核门禁

- `RAGEngine` 默认只使用显式配置且通过当前 manifest、原文、译文来源核验的 TM 审核快照。未配置快照时，检索集合为空，不请求 embedding；流水线仍把合格的新原译对写入完整 `TM_PATH` 候选库，便于后续审核。
- 兼容配置 `ALLOW_UNREVIEWED_TM` 默认关闭，可由环境变量或配置 JSON 显式开启；环境变量优先。测试工作区只接受显式环境变量。`TM_REVIEWED_PATH` 有值时审核快照始终优先，即使兼容开关开启。该开关不改变审核状态，也不追溯批准旧条目。
- 定向验证：`.venv\Scripts\python.exe -m unittest tests.test_rag_engine_unit tests.test_pipeline_contracts tests.test_tm_review -q`，122 项通过。覆盖默认不检索/不生成 embedding、环境变量和 JSON 配置覆盖、候选写入保持、以及审核快照高于兼容开关。
- 完整回归：22 个模块的 `.venv\Scripts\python.exe -m unittest tests.test_align_chapters_unit tests.test_epub_builder tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_knowledge_extraction_unit tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_local_source_ingestion_cli tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_scratch_filter tests.test_security_path_traversal tests.test_source_ingestion tests.test_source_manifest tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_story_summary_review tests.test_tm_provenance_unit tests.test_tm_review tests.test_translation_plan_approval -q`：413 项运行、409 项通过、4 项跳过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，232.976 秒，runner 退出码 0。输出中的 content-filter 与段落契约异常为负向 fixture；请求只发往 runner 启动的 loopback mock server。本轮没有访问 Kakuyomu、真实 Provider 或 Notion。
- 采集需求复核：主页目录发现、`publicEpisodeCount` 对账、普通 episode URL、1.5–3 秒串行延迟、ruby/旁点/NBSP/U+3000 parser fixture 和有序全书正文导出已有代码/测试/历史运行证据；本轮没有重新抓取站点。原文中的 U+3000 保留，不原地 `lstrip`。
- 当时记录的后续计划为翻译前全书预读；2026-11-17 已实现本地 tokenizer/context 预算分批、段落覆盖和批次内结论引用。配置章节集与公开目录的一致性、tokenizer/template 与真实端点容量匹配、跨批模型级综合、候选语义和人工审核质量仍待核验。Gemini/Claude 示例不代表已授权接收方。详见[采集与出版计划](source-ingestion-and-publication-plan.md#kakuyomu-页面结构与文本提取2026-11-16)及[路线图阶段 2](roadmap.md#阶段-2书籍知识审核闭环)。

## 2026-11-16 合并后文档复核

- 该只读复核快照的 `main` HEAD 为 `e2fe611`（PR #70），当时工作区干净。当前续接开始时 HEAD 仍为 `e2fe611`，但四份项目文档已有未提交改动，均予以保留。下节合并前工作集的测试属于历史记录，本续接未重跑；不能用依赖检查替代真实服务或测试验收。
- 本地 `.venv\Scripts\python.exe --version` 为 Python 3.14.7，`-m pip check` 返回 `No broken requirements found.`，不代表服务或部署就绪。
- 对试点原文根目录执行 `scripts\validate_source_manifest.py --root <原文根目录> --manifest source_manifest.json`：`schema_version=1 artifacts=268 files_verified=268`。仅验证清单引用文件的当前字节哈希，不验证来源许可、文本语义或站点目录完整性。
- 使用现有 catalog 和译文根目录运行 `scripts\run_kakuyomu_workflow.py --source-root <原文根目录> --catalog source_catalog.discovered.json --translation-root <译文根目录> --plan-only`，未指定输出文件，返回 `ready_for_review`、88 项、88 项来源验证、0 问题、`source_text_included=false`，报告网络请求、Provider 调用和文件写入均为 0。这不是人工审批，也不是翻译质量验收；本轮未访问站点、Provider 或 Notion。

## 2026-11-16 当前实现工作集回归

- 复核基线：实现前 `main` 为 `a3813c3`；以下验证针对该基线上的当前工作集，覆盖目录 schema v2/v3、作品元数据版本归档、catalog 差异/纯追加/正文刷新、normalized 来源新鲜度门禁及其消费端。
- `.venv\Scripts\python.exe -m unittest tests.test_align_chapters_unit tests.test_epub_builder tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_knowledge_extraction_unit tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_local_source_ingestion_cli tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_scratch_filter tests.test_security_path_traversal tests.test_source_ingestion tests.test_source_manifest tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_story_summary_review tests.test_tm_provenance_unit tests.test_tm_review tests.test_translation_plan_approval -q`：22 个非 E2E 模块运行 410 项，406 项通过、4 项跳过、0 项失败。普通权限下 3 个符号链接用例因 `WinError 1314` 跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- 按用户授权在隐藏的管理员 PowerShell 中重跑 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、10 项通过、1 项跳过、0 项失败；3 个符号链接用例均实际执行并通过，FIFO 用例仍因平台能力跳过。用户另行提供的 `-q` 结果为 9 项、3 项跳过；当前工作树该模块定义 11 个测试方法，因此该结果保留为独立快照，不与本次结果合并。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，214.086 秒，退出码 0。输出中的 provider content-filter 与段落契约异常来自预期负向 fixture；请求只发往 runner 启动的本地 mock server。
- 本次涉及的 24 个源码/测试 `.py` 文件通过 `.venv\Scripts\python.exe -m py_compile`。`.venv\Scripts\python.exe -m pip check` 返回 `No broken requirements found.`；`git diff --check` 通过。
- README 与 `docs/` 下 14 份 Markdown 的 151 个相对文件链接和 60 个标题锚点通过本地检查；锚点检查使用简化 slug 规则，不是完整 CommonMark/GitHub 渲染器。
- 本次没有调用真实 Kakuyomu、Provider 或 Notion，也没有验证部署、译文质量、人工映射批准或正文格式验收。

## 2026-11-16 Kakuyomu 显式正文全量刷新

- 用户已确认指定作品授权、普通读者 URL 采集路径，并明确不需要官方澄清。刷新仍由操作者显式启动，不会自动定期请求。
- `scripts/ingest_kakuyomu_pages.py` 新增 `--refresh-from-catalog` 与 `--refresh-from-checkpoint`。命令重新从作品主页发现公开目录，要求与基线 catalog 的完整 episode 顺序、ID、标题、位置、URL 和可比较的章节分组完全一致；需要完整基线 checkpoint、基线 catalog SHA-256 和一个新 checkpoint 路径。刷新期间逐话请求所有 episode URL，串行使用现有 1.5–3 秒延迟。
- 每话新正文与最新 raw 版本相同则复用原版本；正文变化则追加不可变 raw 版本并保留旧版。完成后 `content_refresh` 报告变化话目的旧/新 version ID 与 SHA-256、变化/未变数量，并提示下游复核；报告不包含正文。刷新 checkpoint 对基线 catalog/checkpoint 绑定，失败后可用相同输出路径续传。
- 变更检测只覆盖与完整基线相同的目录；旧目录发生增删、重排、改名或可比较的章节结构变化时拒绝刷新。旧版 catalog 缺章节结构时不具备分组比较证据。`downstream_review_required` 是提示，不会自动将译文、概要、TM 或知识标为过期；下游失效状态传播仍未实现。
- 真实刷新：2026-11-16 从试点作品主页重新发现 88 个 URL，并以 2 秒请求间隔逐话请求全部 88 个普通 episode URL。CLI 返回 `status=complete`、`completed_count=88`、`content_refresh.changed_count=0`、`unchanged_count=88`。基线 catalog 为 schema v1，故话目 ID/标题/位置/URL 可核对，但旧章节分组对比状态不可用；新 catalog 为 schema v3。刷新输出写入试点生肉根目录的 `source_catalog.refresh-2026-11-16.json` 与 `source_checkpoint.refresh-2026-11-16.json`；原基线 catalog/checkpoint 仍单独保留为刷新输入。刷新前基线 checkpoint 仍为 complete/88；刷新后两个 checkpoint 的话目顺序和 88 个 raw version ID 绑定一致。刷新后 `scripts/validate_source_manifest.py --root <试点生肉根目录> --manifest source_manifest.json` 返回 `schema_version=1 artifacts=268 files_verified=268`，其中含 1 个 `kind=work` artifact。这次刷新没有生成新的 raw 正文版本；artifact 数从刷新前记录的 267 增至 268。
- 刷新后的只读翻译计划预览返回 `ready_for_review`、88 项、0 问题；没有写审批回执、译文或 TM，没有调用 Provider。它仍待人工检查映射及文本格式。
- 验证命令：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`（109 项通过）。合成集成测试覆盖全目录请求、正文未变复用、变化时追加新哈希/版本、基线不覆盖及暂停续传。`py_compile` 涉及的六个源码/测试文件、ingestion CLI `--help`、`git diff --check` 均通过；自定义只读 Markdown 链接检查核对 147 个本地目标，均存在。
- 下一步：人工抽查当前归档格式与 88 话映射；之后处理版本变化后的下游失效状态传播，再评估原始 HTML/等效表示及 AI/人类派生版。额度状态无法通过当前接口准确核实。

## 2026-11-16 原文版本新鲜度审计补强

- 背景：正文刷新可在 raw 内容变化时追加新版本，但刷新不会自动物化新的 normalized artifact。此前 TM、知识候选与概要审核主要比较引用版本是否为最新 normalized；在 raw 已更新、normalized 尚未重建的间隙，仍可能误判为新鲜。
- `source_manifest.py::latest_raw_parent_for_normalized` 现在定位 normalized artifact 直接引用的 raw artifact，并取得该 raw artifact 的最新版本。TM/知识只读审计和概要发布/运行时加载都会验证当前 raw 文件哈希，并要求最新 normalized 的父版本包含该 raw 版本；缺失/损坏 lineage 报 `invalid`，raw 更新但 normalized 未重建报 `stale`。
- 该补强只增加发现与拒绝门禁，不物化 normalized、不修改 TM/知识/概要、不写持久化过期标记，也不自动重跑刷新。2026-11-16 真实全量刷新没有正文变化；新增 stale 窗口由 synthetic tests 覆盖。
- 验证：`.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_story_summary_review tests.test_tm_review tests.test_tm_provenance_unit tests.test_rag_engine_unit tests.test_pipeline_contracts tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_epub_builder -q`：295 项通过。输出中的 disk-full、mock 请求及 Provider 异常为测试故障注入日志；最终汇总为 `OK`。
- Kakuyomu 目录与正文格式专项回归：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`：49 项通过，覆盖主页 catalog 完整性计数、普通 episode URL、ruby/旁点标记、NBSP、U+3000 与段落结构。
- 下一步仍是人工抽查 88 话归档格式与映射，再设计显式失效状态/重建流程。Provider、Notion、原始 HTML 及人工格式验收仍未完成。

### 2026-11-16 I4 消费端新鲜度门禁扩展

- `source_manifest.py::verify_current_normalized_source` 集中验证所选 normalized artifact：文件与哈希有效、版本是该 artifact 的最新 normalized，且唯一 raw 父 artifact 的最新版本仍在其 parent lineage 中。
- 通用 `CHAPTER_MAP` 加载和 `TranslationPipeline` 运行前/提交前复核、`scripts/align_chapters.py`、`scripts/apply_knowledge_review.py`、EPUB 候选构建现复用此门禁。知识抽取经 `get_chapter_specs` 继承同一检查。raw 更新而 normalized 尚未重建时，各入口拒绝 stale 输入。
- 本次补齐相关 synthetic manifest fixture 的 raw→normalized lineage，并新增 EPUB stale raw parent 回归。统一验证命令：`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_pipeline_linkage tests.test_pipeline_contracts tests.test_epub_builder tests.test_align_chapters_unit tests.test_knowledge_review tests.test_knowledge_provenance_audit tests.test_story_summary_review tests.test_tm_review tests.test_tm_provenance_unit tests.test_kakuyomu_translation_plan tests.test_knowledge_extraction_unit tests.test_rag_engine_unit tests.test_local_source_ingestion_cli -q`：14 个模块退出码 0。先行验证暴露知识抽取旧 fixture 缺少 raw parent；补齐后统一回归通过。
- 门禁只在读取/处理边界发现并拒绝 stale 输入，不自动重建 normalized/TM/知识/概要、不写持久化过期状态，也不覆盖未绑定 `source_version_id` 的旧数据。验证使用合成输入；没有调用 Provider、Notion 或真实 EPUB 阅读器。额度状态无法通过当前接口核实。

## 2026-11-16 Kakuyomu 纯追加增量采集（正文刷新前一阶段）

- 用户要求从作品主页发现完整目录并按普通 episode URL 获取原文；试点书授权已确认，用户明确不需要官方澄清。本次实现只扩展已发现 catalog 的续跑方式，不改变原有按 URL 逐话采集、串行限速和访问失败关闭行为。
- `kakuyomu_catalog_diff.py::append_only_catalog_status` 判断当前目录是否严格保留旧 episode ID 顺序、标题、位置和 URL；两份 v2+ catalog 还要求旧 episode 的章节归属不变、已有章节 ID/标题/层级不变且原章节成员只能保留为前缀。章节末尾新增成员允许通过。v1 旧 catalog 无章节分组时，会标注章节比较不可用；来源核心仍会对 manifest 中每话旧标题、位置、URL 和 raw 版本做实际校验。
- `scripts/ingest_kakuyomu_pages.py` 新增 `--incremental-from-catalog` 和 `--incremental-from-checkpoint`。增量模式必须同时使用 `--work-url` 和新 `--checkpoint`；发现快照也必须写到不同于基线 catalog 的新路径。基线要求完整 checkpoint v5、ID 顺序与旧 catalog 相同、manifest 身份一致，且每条 raw SHA-256、最新 metadata 关系均可验证。新 checkpoint 继承旧完整章节 ID 与 raw version bindings，从已有章节数量作为目录分页偏移开始采集；只请求新增话，最终 checkpoint 仍覆盖当前完整 catalog。主页作品元数据照常写入可追溯的 `kind=work` artifact。
- 同一目录快照下若采集暂停，可保留相同 catalog/checkpoint 路径重新运行，从已完成的新话之后续传。旧 catalog、旧 checkpoint 和已归档 raw 不覆盖。旧话改名、移动、删除、重排或既有章节归属/元数据改变时停止，不自动重抓或改写历史。若暂停期间来源目录再次变化，需另选新 snapshot/checkpoint；不自动拼接两个不同目录版本。
- 纯追加模式本身不能发现主页目录未变但正文被静默修订的情况：catalog 不保存正文哈希，既有话不会被重新请求。正文显式刷新和 hash 差异现已在上节实现；下游概要/知识失效传播仍未实现。
- 验证命令 `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`：105 项通过。新增合成覆盖纯追加及已有章节末尾追加、旧章节元数据变更拒绝、仅请求新增 URL、旧 checkpoint 保持不变、暂停后从 pending 话续传，以及 baseline manifest/raw 绑定校验。`.venv\Scripts\python.exe -m py_compile source_ingestion.py kakuyomu_catalog_diff.py scripts\ingest_kakuyomu_pages.py tests\test_source_ingestion.py tests\test_kakuyomu_catalog_diff.py tests\test_kakuyomu_page_source.py` 和 `scripts\ingest_kakuyomu_pages.py --help` 通过。没有执行真实 Kakuyomu 增量采集；此前 88/88 live run 是独立历史证据。
- 当时的下一步是显式正文刷新与章节正文哈希差异，现已由上节完成；后续仍需规划原始 HTML 或等效表示与 AI/人类派生版。额度状态无法通过当前接口准确核实。

## 2026-11-16 Kakuyomu 元数据版本归档与实时采集复核

- 用户确认指定作品已获授权，要求从作品主页发现完整公开目录，并按发现的普通 episode URL 获取正文；用户为普通读者，明确不需要官方澄清。该决定不是平台背书、法律结论或公开分发授权。
- 当前源码从唯一 `__NEXT_DATA__` Apollo 状态按 `tableOfContentsV2` 顺序读取目录分组，要求 episode ID 唯一且数量等于 `publicEpisodeCount`，通过后才生成普通 episode URL。采集请求串行，默认间隔 2 秒、允许 1.5–3 秒；checkpoint 按来源快照绑定，暂停后只重抓未完成话。章节归档是跨时间滚动快照。
- 2026-11-16 按仓库规定的代理重新访问试点作品主页：发现 88 个唯一普通 episode URL，与公开计数 88 相等，目录有 3 个分组。随后从发现的首个 URL 获取一话；解析文本保留 ruby 标记、U+3000 和段落边界。该话不含旁点或 NBSP，因此这两项仍由 synthetic HTML fixture 验证。响应正文未输出到日志。
- 对现有试点原文根运行 `scripts/validate_source_manifest.py --root <原文根目录> --manifest source_manifest.json`：`schema_version=1 artifacts=267 files_verified=267`。现有 checkpoint 为 schema v5、complete、88/88；本地 discovered catalog 仍为 schema v1。此次未重抓全书，也未改写外部书籍数据；旧目录/检查点与当前发现解析器 fingerprint 的兼容性需按显式新快照策略处理。现有 267 个文件哈希只证明已归档字节未变，不证明来源正文格式或站点计数以外的完整性。
- `source_ingestion.py::_persist_work_metadata` 已将主页元数据实现为 `kind=work` 不可变 artifact：写入 UTC 记录时间、内容 SHA-256 和前版本关系；相同元数据复用当前版本，变化时追加版本，并纳入 manifest 累计字节上限。`--work-url` 路径在章节正文前归档元数据。该逻辑由 synthetic tests 覆盖；现有外部 267-artifact manifest 尚未包含它，本次未重跑全目录以更新该文件。
- 验证命令 `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`：99 项通过。覆盖 catalog schema v1/v2/v3、完整目录计数门禁、特殊标记解析、恢复、元数据版本/父关系/去重/字节上限及 manifest 校验；除上面明确列出的单话检查外，不代表真实全书采集或 Provider/Notion 验收。
- 本节记录的下一步在后续的“显式正文全量刷新”阶段已完成其刷新/hash 部分；刷新报告仅提示下游复核，尚未传播概要/知识失效状态。原始 HTML 归档和人工格式验收仍未实现。

## 2026-11-16 Kakuyomu 主页发现与逐话采集复核

> 较早检查点，记录 catalog schema v2/v3 与 snapshot diff 增量；后续 source manifest 元数据归档和实时单话复核见本文首节。

- 用户已明确指定作品获得授权，并要求采集器从作品主页发现完整公开目录 URL，再逐话访问普通 episode URL 获取正文；用户明确表示无需官方澄清。该用户决定不表述为平台背书或公开分发授权。
- 当前 `kakuyomu_page_source.py::discover_kakuyomu_work_catalog` 从作品页 `__NEXT_DATA__` 的 Apollo state 读取 `Work.tableOfContentsV2`，按分组顺序解析 episode ID/title 和 `Chapter` 引用的 ID、标题、层级；唯一 ID 数与 `publicEpisodeCount` 不一致时停止。通过后构造普通 episode URL，随后逐话解析唯一 `widget-episodeBody` 或 `js-episode-body` 正文区域。请求间隔代码限定为 1.5–3 秒，默认 2 秒；source ingestion checkpoint 支持从未完成话续传。
- 本轮新增 discovered catalog schema v2，保存目录组 ID、章节元数据、连续位置范围及 episode ID 顺序；schema v3 增加主页作品元数据白名单；catalog loader 继续接受旧 schema v1/v2。v3 字段为主页 URL、作品标题、作者名称/用户名、catchphrase、introduction、genre、tag labels、serial status、发布时间、最近话目发布时间和公开话数。原始 HTML 响应仍未归档，作品元数据也尚未作为独立版本写入 source manifest；现有 raw artifact 仍是解析后的 UTF-8 可见文本。
- catalog parser/fingerprint 现包含分组元数据；旧 `--work-url` 发现快照 checkpoint 与新 fingerprint 不匹配时会拒绝复用（包括原先已 complete 的 checkpoint）。保留旧 checkpoint 和 manifest；需要重新发现/抓取时先核对既有输出，再选用独立 catalog/checkpoint 路径，不覆盖旧检查点。
- 新增 `scripts/diff_kakuyomu_catalogs.py` 比较本地 v1/v2/v3 快照，报告新增、消失、标题修改、位置变化及 v2+ 章节归属/元数据变化，并绑定两份 catalog 文件 SHA-256。两份 v3 快照间还比较作品字段，但报告只列变化字段名，不输出字段值。可排他导出 `added` 或 episode `updated` 的 v1 选择清单，并在报告记录导出清单 SHA-256，供 `scripts/ingest_kakuyomu_pages.py --catalog` 逐项采集；它不删除消失话目，也不自动刷新。旧快照缺少对应结构时将比较状态标为不可用；catalog 不含正文哈希，因此正文静默修订须由操作者显式全量刷新。单独作品字段变化不会改变 episode source fingerprint。
- parser v4 和 synthetic fixtures 覆盖段落边界、ruby、`emphasisDots`、HTML entity 与 U+3000 保留。另对 Kakuyomu 作品主页做过一次带代理的只读请求，用于核对 Apollo 元数据键名和类型；未请求任何 episode 页面。live 88/88、manifest 267/267 是既有历史采集/校验记录，不是本轮全书网络运行，也不证明主页声明外的完整性。
- `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`：43 项通过。合成测试验证 v1/v2/v3 比较、改名/重排/分组变化、作品字段变化只报字段名、删除报告、新增清单拒绝覆盖并可由现有来源 CLI 完成选集导入；正文 fixture 覆盖 `p` ID、ruby、旁点、NBSP 与首段/后续段的 U+3000 缩进。episode 采集和 Provider/Notion 均未在本轮执行。
- 下一阶段仍需将作品字段保存为 manifest 版本并记录抓取时间，定义作品元数据变化对下游概要/知识的失效传播；再设计显式正文刷新与正文哈希、原始 HTML 或等效可追溯表示及父子版本，实施 AI/人类双版本及转换映射，并人工验收段落、ruby、旁点和空白。具体步骤和验收见[原文采集与成果归档方案](source-ingestion-and-publication-plan.md#搜索与双版本需求复核2026-11-16)。

## 2026-11-16 文档规划复核

- 基线：`main` HEAD `a3813c3`；本轮开始时工作区已有五份未提交 Markdown 修改，未回滚或覆盖。`git diff --stat ba9979e HEAD -- '*.py' 'requirements*.txt'` 无输出，说明所比较提交之间这些源码和依赖声明未变，不证明环境或真实服务状态未变。
- 当前 PowerShell 的 `.venv` 为 Python 3.14.7，`python -m pip check` 报告无依赖约束冲突；`requirements.txt` 未锁定版本。本机可找到 Pandoc 可执行文件，未核验版本、EPUBCheck 或阅读器。
- 对用户指定试点根目录只读检查：原文根目录存在且含 273 个文件，译文根目录存在且文件数为零；`source_manifest.json` 和既有计划 JSON 存在。`.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <试点原文根目录> --manifest source_manifest.json` 报告 `artifacts=267 files_verified=267`；检查的是清单中列出的文件，不代表正文格式或平台目录之外的完整性。
- 使用已有 catalog、manifest 和译文根目录运行 `scripts\run_kakuyomu_workflow.py --plan-only`，未指定 `--plan-output`，返回 `ready_for_review`、`source_text_included=false`；这是未写入计划文件的预览，不能代替人工审核。尝试提取不存在的 `summary` 字段失败，因此本轮不据此报告问题数；既有 88 项及零问题数字仍属于下方历史导出记录。
- `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts tests.test_tm_review tests.test_epub_builder -q`：前一同日检查点记录为 127 项通过、无跳过。输出含预期故障注入日志；仅覆盖相应合成测试，不代表真实模型或阅读器验收。
- 该前一检查点仅核对当前进程环境变量是否存在：`PROVIDER_DATA_POLICY`、JOJO/JYQF endpoint/key 及 `PROOFREAD_MODEL` 均未设置，仓库根目录无 `.env`；不排除其他进程或外部配置，也不证明端点不可用。该检查点未读取秘密、直接请求 Kakuyomu 作品页或 Provider、修改 Notion、审批计划或写入书籍数据。

## 2026-11-16 JOJO→JYQF 显式回退与当前验证

- 代码基线：最近一次代码变更为 `ba9979ed272152ee2ce3039306dfc685b4476374`，来自已合并 PR #67；后续 PR #68 仅同步 Markdown。本节完整回归记录来自 PR #67 验证阶段；本轮针对 `ba9979e` 代码基线单独复跑安全路径模块，结果见下方。根目录 `.env` 不存在，当前进程未发现 Provider allowlist、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`；未调用真实 Provider、Notion 或部署服务。
- 新增 `ENABLE_JYQF_FALLBACK`，默认关闭，可由环境变量或 JSON 配置显式打开。只有主模型路由到 JOJO 的阶段才可回退到固定 `deepseek-v4.1-flash`；仅连接错误、HTTP 408/429/5xx 触发。鉴权、400/403/404、响应契约错误和内容拦截不回退，JYQF 请求失败后直接返回错误，不级联到 Gemini。
- 开始章节扫描前，启动预检会逐 JOJO 阶段核验 JYQF URL、同阶段数据类别授权和远端凭据；本地 loopback 依项目的本地端点规则处理。若同时启用 Gemini 回退，只有运行时仍会回退到 Gemini 的阶段才检查该阶段的 Gemini 数据授权；JYQF 已接管的 JOJO 阶段不要求 Gemini 授权。实际创建备用 Provider 客户端前再次核验类别授权。备用调用可能产生额外费用；每次仅调用一次备用，不自动重试。真实模型 ID、端点协议与费用仍未验证。
- PR #67 自动审查发现三项问题：JOJO 已由 JYQF 接管时仍要求 Gemini 阶段授权、JYQF SDK 客户端会自动重试、README 将未覆盖回退路径的 mock E2E 写成该回退的验证证据。现已修正预检、只对 JYQF 备用客户端设置 `max_retries=0`，并将 README 限定为契约单测覆盖。回归覆盖“樱花初译、JOJO 校对/润色、JYQF 接管 JOJO 失败、Gemini 仅获初译所需类别”及备用 SDK 重试参数。`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -q`：38 项通过；`tests.test_pipeline_contracts`：91 项通过。
- 全部非 E2E：PR #67 验证阶段对 21 个 `tests.test_*.py` 模块共运行 380 项、376 项通过、4 项跳过、0 项失败。普通权限下 3 项 symlink 用例因 `WinError 1314` 跳过，1 项 FIFO 用例因 Windows 不提供 `os.mkfifo` 跳过；此前获准的管理员 PowerShell 复跑该模块为 11 项运行、10 项通过、仅 FIFO 用例跳过，3 项 symlink 用例通过。本轮针对 `ba9979e` 代码基线运行 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、7 项通过、4 项跳过；详细输出确认 3 项因当前执行账户缺少符号链接权限而跳过，1 项因 Windows 不提供 `os.mkfifo` 跳过。用户本次提供的 `-q` 汇总为 9 项、3 项跳过，未列测试名；由于当前源码定义 11 个测试方法，该结果不能归属到当前代码基线。
- 完整 mock E2E：`.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项、全部通过，199.765 秒，退出码 0；请求只发送给本地 mock server。该 E2E 未启用或断言 JOJO→JYQF 回退；回退配置与请求行为由合成契约单测覆盖。当前 OpenAI SDK loopback 客户端检查确认显式参数生效为 `max_retries=0`，未发起网络请求。`.venv\Scripts\python.exe -m compileall -q .` 与 `.venv\Scripts\python.exe -m pip check` 均通过。
- 首次、改动前的非 E2E 回归曾有一项 `test_cli_escapes_nonprintable_chapter_key_characters` 得到退出码 1 而非 2；该测试单独运行、整个模块运行及随后完整重跑均通过。未复现原因，作为一次性异常记录，不计入本次改动后的失败数。
- 管理员 PowerShell 复跑命令（此前获准运行结果为 11 项中 10 项通过、仅 FIFO 跳过；3 项符号链接用例均通过）：

  ```powershell
  Set-Location -LiteralPath 'D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System'
  .\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v
  ```

  若管理员终端仍报告 `WinError 1314`，可在 Windows 设置中开启“开发者模式”后重开终端，或让管理员在本机安全策略中为该账户授予“创建符号链接”用户权限并重新登录。管理员复跑由用户授权，仅用于本地测试；未更改 Windows 系统策略。
- `.venv\Scripts\python.exe -m pip list --outdated`（2026-11-16，只读查询）报告 `numpy 2.5.4→2.5.5`、`openai 3.50.0→3.51.0`、`tenacity 9.1.4→9.2.1` 和工具 `pip 26.2.1→26.3`。`requirements.txt` 未锁定版本；更新提示本身不足以证明兼容性或安全收益，因此本次未安装/升级依赖。`pip check` 仅确认当前环境依赖约束无冲突，不是漏洞审计。

## 2026-11-16 PR #64/#65 合并与试点计划导出

- 沿革：PR #64 文档同步合并提交为 `16899a1f55a798a440157b5c2265211c953ea0d9`；后续 PR #65 也只修改 Markdown，并于 2026-11-16 合并为 `fe74916662843fca79bd09915b98b89c96377a5f`。代码与测试基线仍为 `c988c4b749a9972a89edffe9bc2c4bc867ebb3da`；此处记录合并沿革，不作为持续更新的 `main` HEAD 指针。
- 对试点运行的 PowerShell 命令如下；执行时目标计划文件尚不存在。CLI 对 `--plan-output` 采用排他新建，重跑需指定一个新文件名：

  ```powershell
  $sourceRoot = 'D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉'
  $translationRoot = 'D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\熟肉'
  $planOutput = Join-Path $sourceRoot 'translation_plan_review_2026-11-16.json'
  .\.venv\Scripts\python.exe scripts\run_kakuyomu_workflow.py --source-root $sourceRoot --catalog source_catalog.discovered.json --translation-root $translationRoot --manifest source_manifest.json --plan-only --plan-output $planOutput
  ```

  退出码 0，`status=ready_for_review`，88/88 来源通过核验、0 问题；摘要 `36dae9c08069ce5c66eddc1e870a0aa4aa4d1724b00589ed9a5be62ce4bc22d4` 与独立重算一致。计划文件在仓库外的原文根目录，未纳入 Git。
- 结构化核对确认 88 个位置中的 ID、位置、来源文件/版本、译文目标和 TM key 唯一；目录标题有 1–87 连续编号话目，位置 48 是一条幕间。88 个译文目标均不存在。该核对不代替人工确认正文格式、来源完整性或映射是否符合预期。
- 本次报告记载 0 网络请求、0 Provider 调用、`source_text_included=false`、1 次文件写入（计划 JSON）。未创建审批回执，未执行 Provider 翻译；运行时配置仍需单独核验。
- PR #64 的合并及计划的人工审阅边界见[审阅交接](handoffs/2026-11-16-pilot-plan-review.md)。本轮只修改 Markdown 文档；未因文档同步重复运行代码测试。

## 2026-11-16 主线复核（PR #63 后）

- 基线：`main` HEAD `fe43ea3fb9ff6ac3a901e4c73641bcb9c6af38e6`；该提交只同步 Markdown，代码基线为 `c988c4b749a9972a89edffe9bc2c4bc867ebb3da`。本轮基于该主线创建 PR #64 文档分支，代码未变更。
- 当前 checkout 普通权限运行 `.\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、7 项通过、4 项跳过；3 项符号链接测试因 `WinError 1314` 缺少创建权限，1 项 FIFO 测试因 Windows 不提供 `os.mkfifo` 跳过。
- 经用户授权在管理员 PowerShell 下重跑同一模块：11 项运行、10 项通过、1 项因 Windows FIFO 能力跳过；3 项符号链接测试均执行并通过。管理员运行命令为 `.\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`。
- 2026-11-16 再次在管理员上下文运行同一模块：11 项运行、10 项通过、1 项 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过；3 项符号链接用例均执行并通过。该次运行位于 PR #65 合并后的文档基线 `fe749166`，被测代码仍与 `c988c4b` 一致。
- 用户另行提供的 `-q` 结果为 9 项、3 项跳过；该汇总不含测试名称/原因，且测试数与当前 checkout 的 11 个测试方法不符，因此不将其归属到当前 SHA。当前 checkout 的普通权限和管理员结果以上述 verbose 运行记录为准。
- GitHub 复核确认 PR #56、#58、#62、#63 均已合并；创建本次 PR #64 前，`gh pr list --state open` 返回空列表。PR #62 合并提交为 `c988c4b`，PR #63 文档同步提交为 `fe43ea3`。
- 当前代码基线完整非 E2E 回归：按 `tests/test_*.py` 扫描并排除 `test_e2e.py`，发现 21 个模块；运行 368 项、0 失败、4 项跳过（3 项符号链接权限限制、1 项 Windows FIFO 能力限制）。该结果运行于 PR #64 的文档分支，代码未偏离 `c988c4b`。
- 当前完整 mock E2E：`.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项、全部通过，242.450 秒，退出码 0。输出中的内容过滤和段落错配异常来自预期负向 fixture；请求只发往本机 mock server。
- `.venv\Scripts\python.exe -m compileall -q pipeline.py rag_engine.py utils.py source_manifest.py source_ingestion.py chapter_transaction.py story_summary_review.py tm_review.py epub_builder.py scripts tests` 与 `.venv\Scripts\python.exe -m pip check` 通过；后者输出 `No broken requirements found.`。
- 本次只检查配置是否存在，没有读取任何密钥值：仓库根 `.env` 不存在，当前进程未设置 `PROVIDER_DATA_POLICY`、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`。本次没有调用真实 Provider、Notion 或部署环境。
- 试点本地数据只读复核：`scripts/validate_source_manifest.py --root <试点生肉目录> --manifest source_manifest.json` 返回 `schema_version=1 artifacts=267 files_verified=267`。同一原文根和译文根运行 `scripts/run_kakuyomu_workflow.py --catalog source_catalog.discovered.json --manifest source_manifest.json --plan-only` 返回 `ready_for_review`，88/88 来源通过核验、0 问题；报告记录 0 网络请求、0 Provider 调用、0 文件写入，且 `source_text_included=false`。当前译文根文件数为 0。映射摘要 `36dae9c08069ce5c66eddc1e870a0aa4aa4d1724b00589ed9a5be62ce4bc22d4` 尚未人工批准，不等于翻译执行许可。

## 2026-11-16 翻译计划审批门禁（PR #62 已合并）

- 基线：PR #62 分支 `codex/translation-workflow-next-20261116` 基于 `origin/main` HEAD `3abc69eb5c13cc2c86780cd08748d5ecc7ba82d2`；PR 于 2026-11-16 squash 合并，当前 `main` HEAD 为 `c988c4b749a9972a89edffe9bc2c4bc867ebb3da`。
- 新增 `translation_plan_approval.py` 和 `scripts/approve_translation_plan.py`。稳定摘要绑定工作 ID、解析后的源/译文根目录、catalog/manifest 路径及每话 ID、位置、标题、源文件/版本、目标路径和 TM 键；不绑定目标是否已存在等运行状态，以支持相同映射的安全续跑。审批命令展示映射并要求输入完整 SHA-256，成功后排他新建回执。
- `scripts/run_kakuyomu_workflow.py` 的翻译执行现在要求 `--approval-receipt`。计划或来源身份改变时摘要不匹配并拒绝；只因目标译文已存在而阻塞时，可核验原回执后续跑，但仍检查输出、TM 与本章事务是否一致。无回执时返回 `approval_required`，不创建 `TranslationPipeline`。`--plan-only` 默认 stdout 零写入；显式 `--plan-output` 才会排他新建计划 JSON。
- 回执是本地普通 JSON，没有签名、身份认证或防篡改证明；`approved_by` 是调用者声明。它只证明本地流程记录了一次摘要确认，不证明操作者身份、人工审阅质量或翻译质量。真实 Provider 未调用。
- 验证：`python -m unittest tests.test_translation_plan_approval tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow -q` 运行 25 项、全部通过；当前全部非 E2E unittest 运行 368 项、0 失败、4 项因普通权限下符号链接创建及 Windows FIFO 能力跳过；管理员专项覆盖所有符号链接路径。`python tests/run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation` 运行 1 项、通过；完整 `.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项、通过，耗时 253.608 秒，退出码 0。E2E 通过本地 mock HTTP 服务；负向 fixture 的内容拦截/段落错配输出是预期行为，不代表真实 Provider 测试。
- Python `py_compile` 覆盖新增审批模块、CLI、编排器和对应测试，通过；`git diff --check` 通过。管理员 PowerShell 下当前安全路径模块 11 项运行、10 项通过、1 项因 Windows 不支持 FIFO 跳过；3 个符号链接用例实际运行并通过。用户另行提供的 9 项/3 项跳过输出计数不同，单独保留，不替代当前 checkout 结果。
- E2E 修复轨迹：首次完整运行发现待审批结果缺少已发现 catalog 路径；第二次发现二阶段 fixture 未复用 discovery checkpoint/adapter，导致流程在建流水线前退出。修正返回字段和 fixture 后，目标 E2E 及最终完整 runner 均通过。
- GitHub PR #56 已处于 `MERGED`；PR #62 也已合并，没有配置状态检查。真实 Provider/API、88 话映射与原文格式人工验收、Notion、EPUB 阅读器和部署仍未验证。

## 2026-11-16 PR 60 合并后基线

- 当前主分支：`main`，HEAD `df4e3ed84aee8616e10dafde4f6608017bd7b3e2`。PR #60 将只读 Kakuyomu 章节映射预览 squash 合并；合并树与已验证分支 `codex/translation-plan-preview-20261116` 的 tree `a3cef677a0407d24392fafd81eb9b87c8ba05c0c` 一致。
- 当前代码树完整非 E2E unittest：20 个模块运行 358 项，0 失败、4 项按 Windows 符号链接权限/FIFO 能力跳过。管理员权限安全路径复跑 11 项，10 项通过、仅 FIFO 跳过；3 项符号链接用例均执行通过。
- 当前代码树本地 mock E2E：`.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项，245.766 秒，退出码 0。负向 fixture 的 content-filter 与段落错配异常是预期输出；未调用真实 Provider。
- GitHub PR #60：Codex 自动审查完成且无 findings；CodeRabbit 在合并时仍为 `in_progress`；commit status 列表为空，未发现 CI 检查结果。PR 已合并，不把仍运行的 CodeRabbit 检查称为通过。
- 本机 `--plan-only` 对 88 话试点返回 `ready_for_review`，88/88 个来源通过文件哈希/版本关系核验，0 问题、0 目标冲突、0 网络请求/Provider 调用/写入。人工映射与原文格式验收仍未完成；摘要不是签名审批回执，也未被正式运行强制校验。
- 真实 Provider/API 调用、翻译质量、Notion、EPUBCheck/目标阅读器和部署仍未验证；最近一次本机 Provider 配置存在性检查未发现 `.env`、Provider allowlist、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`。

## 2026-11-16 PR #58/#59 检查点（历史）

- 当前主分支：`main`，HEAD `75305937a6b8020ab2dfc515c720f4fa871c5dce`。PR #58 于 2026-11-16（Asia/Shanghai）以 squash 合并；实现/测试提交为 `8f1f89fb62a221fffd8415489fff82cbf4248116`，PR #59 随后同步项目状态文档。
- 完整非 E2E unittest：按仓库既有模块选择运行 351 项，0 失败、4 项跳过。定向 Kakuyomu adapter/workflow 与 EPUB builder 回归运行 52 项，全部通过。
- 完整本地 mock E2E：`.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项，266.420 秒，退出码 0。输出中的 content-filter 与段落错配异常来自预期负向 fixture；未调用真实 Provider 或 Notion。
- 安全路径专项：普通权限运行 11 项时，3 个符号链接用例因 `WinError 1314` 跳过，FIFO 用例因 Windows 不支持跳过。随后依用户授权以管理员 PowerShell 重跑：11 项中 10 项通过、仅 FIFO 用例跳过；3 个符号链接用例均实际执行并通过。
- Python `compileall` 与 `git diff --check` 通过。synthetic/mock 测试不代表真实 Provider、翻译质量、出版文件、阅读器或部署已验收。
- PR #58 所有 inline review threads 均已解决；没有 review submission 为 `APPROVED`，CodeRabbit check 为 `skipped`。合并前检查得到 `main` 未启用 branch protection，仓库 rulesets 查询为空，未发现 required-check/审批门禁。用户明确要求合并后已合并；跳过的 CodeRabbit 检查不记为通过。
- 最近一次本机 Provider 配置存在性检查未发现根目录 `.env`，Process/User/Machine 环境也未设置 `PROVIDER_DATA_POLICY`、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`。没有读取密钥值；真实 Provider 单话翻译仍受配置缺失阻塞。
- 仍未验证：获准 Provider 的真实端点调用及单话翻译、人工原文/译文格式与质量验收、Notion、EPUBCheck/目标阅读器，以及部署。下一步依赖安全提供 Provider 配置与 allowlist，再执行受控单话翻译并人工验收。

## 2026-11-16 Kakuyomu 本地映射预览验证

- 实现分支：`codex/translation-plan-preview-20261116`，基于 `origin/main` `75305937a6b8020ab2dfc515c720f4fa871c5dce`；已由 PR #60 squash 合并至 `main`，合并提交 `df4e3ed84aee8616e10dafde4f6608017bd7b3e2`。新增 `scripts/run_kakuyomu_workflow.py --plan-only`，可对已有 catalog 做只读计划检查，不需要项目 Provider 配置。
- `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow -q`：15 项通过。覆盖只读行为、JSON CLI、不泄露原文/译文、目标文件冲突、catalog 元数据错配、来源更新后的 normalized 过期、normalized 文件缺失及 manifest 缺少 normalized artifact。
- 当前分支完整非 E2E unittest：按 `tests/test_*.py` 逐模块运行并排除 `test_e2e.py`，20 个模块共 358 项，0 失败、4 项跳过。跳过项为 3 个普通权限下无法创建符号链接的用例及 1 个 Windows 不支持的 FIFO 用例；随后管理员权限复跑安全路径模块，11 项中 10 项通过、仅 FIFO 跳过，3 个符号链接用例均执行通过。用户提供的同名测试输出为 9 项、3 项跳过；因该计数与当前 checkout 中的 11 项不同，分开记录，不将其当作本分支基线。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 运行 7 项，245.766 秒，退出码 0。输出中的 content-filter 和段落错配异常来自预期负向 fixture；仅访问本机 mock server，不代表真实 Provider 已验证。
- `.venv\Scripts\python.exe -m py_compile scripts\run_kakuyomu_workflow.py tests\test_kakuyomu_translation_plan.py` 通过；`.venv\Scripts\python.exe -m pip check` 未发现依赖冲突。跟踪中的 84 个 Markdown 文件本地链接目标存在性检查通过；扫描仅核对目标路径，不验证外链可访问性或锚点语义。
- 试点本地 source manifest 只读核验：`schema_version=1 artifacts=267 files_verified=267`。以已有 `source_catalog.discovered.json` 和空译文目录运行 `--plan-only`：退出码 0，`status=ready_for_review`，88/88 个来源版本通过核验，问题数和目标冲突数均为 0；`plan_sha256=9bd9579eb95956b17d08ff3142ac51973fd14612b0a91246fb55fa58141db4a2`。报告不含章节正文，记录 0 次网络请求、Provider 调用和文件写入。
- `ready_for_review` 仅表示本地映射与来源快照可供人工核对，不表示人工批准；摘要不是签名回执，正式翻译命令目前不强制校验它。当前没有检测到 `.env`、Provider allowlist、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`，所以本轮未调用真实 Provider。

## 2026-11-16 7135904 基线验证（历史快照）

- 当前 checkout：分支 `codex/translation-workflow-20261115`；已验证的代码/测试基线为 `71359040b88434a37ac379247674a6155e614f86`。本地工作区干净。PR 和审查状态见[续接交接](handoffs/2026-11-15-translation-workflow.md#2026-11-16-7135904-后续复核)。
- 完整非 E2E 单测命令：

  ```powershell
  $targets = rg --files tests | Where-Object { $_ -match '^tests[\\/]+test_.*\.py$' -and $_ -notmatch 'test_e2e\.py$' } | ForEach-Object { ($_ -replace '[\\/]', '.') -replace '\.py$', '' }
  & .\.venv\Scripts\python.exe -m unittest @targets -q
  ```

- 在代码/测试提交 `7135904` 上运行 350 项，0 失败、4 项跳过。当前普通 Windows 会话的 `tests.test_security_path_traversal` 为 11 项运行、7 项通过、4 项跳过；3 个符号链接用例因 `WinError 1314` 无创建权限跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。当前执行会话未能以管理员权限运行。
- 两个聚焦回归集合：`tests.test_epub_builder tests.test_pipeline_contracts tests.test_kakuyomu_workflow` 为 108 项通过；`tests.test_kakuyomu_page_source tests.test_source_ingestion tests.test_kakuyomu_workflow` 为 62 项通过。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，348.780 秒，退出码 0；content-filter 与段落错配异常来自预期负向 fixture。未调用真实 Provider 或 Notion。
- Python `compileall`、`git diff --check` 及提交前 Markdown 本地链接目标检查通过。上述测试为本地 synthetic/mock 验证，不代表真实 Provider、Notion、翻译质量、出版文件或部署已验收。
- 用户另外提供 `.\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 输出：9 项运行、3 项跳过、0 失败。该计数与 `7135904` 基线的 11 项测试不同，且输出未含 HEAD、逐项跳过原因或权限状态，不绑定到该基线。该时点若需验证符号链接用例，可在管理员 PowerShell 中运行下方命令；FIFO 在 Windows 仍可能正常跳过：

  ```powershell
  Set-Location -LiteralPath 'D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System'
  ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  .\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v
  ```

  第二行应返回 `True`。
- 代码/测试基线 `7135904` 之后，PR #58 的 Markdown 状态同步 head 为 `854bd861f532675cf293b844e90bd26cdbd677d2`。该 head 上新增两条尚未解决的 Codex review：chunked HTTP 响应 `IncompleteRead` 未转为可恢复暂停，以及相对 `pandoc_executable` 在切换 `cwd` 后失效。代码未在本次 Markdown-only 工作中修改。review submissions 仍只有 `COMMENTED`，没有 `APPROVED`；该 head 的唯一 check-run 是 CodeRabbit `skipped`。`main` 分支保护读取因集成返回 403，正式审批/required-check 门槛未知。详见[续接交接](handoffs/2026-11-15-translation-workflow.md#2026-11-16-合并前状态复核-854bd86)。
- 2026-11-16 本机 Provider 配置存在性预检只输出布尔状态：根目录 `.env` 不存在；`PROVIDER_DATA_POLICY`、`JOJO_BASE_URL`、`JOJO_API_KEY`、`JYQF_BASE_URL`、`JYQF_API_KEY` 和 `PROOFREAD_MODEL` 在 Process/User/Machine 环境均未设置。未读取或输出任何配置值或密钥；该检查点无法执行真实 Provider 单话翻译。
- 真实 Provider/Notion、人工译文与来源格式验收、EPUBCheck/阅读器和部署仍未验证。

## 2026-11-16 PR 审查回归工作区（历史快照）

- 基线为分支 `codex/translation-workflow-20261115`、HEAD `bd9f4f3996c0117d7d69af6389029092b146808c`；本节结果覆盖该基线上的未提交修复与回归测试，不代表远端 PR head 已包含这些改动。
- 本增量修复审查确认的边界：Kakuyomu 重跑只跳过与来源版本/TM/译文一致的已提交章节；章节位置显式传入摘要与指导选择；来源抽取校验实际读取字节；RAG 以原子二进制写入的字节快照计算 TM 指纹；对齐复用统一段落拆分；跨 Windows 盘符的根目录视为互不包含；EPUB 禁用正文 YAML 元数据、按 OPF spine 正文顺序映射章节，并用同一 manifest 字节快照完成解析、验证和哈希。
- 完整非 E2E unittest 选择运行 348 项，0 失败、4 项跳过。3 项符号链接用例在普通权限会话中因 `WinError 1314` 跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- 之后以 `Start-Process -Verb RunAs` 启动 PowerShell 重跑 `tests.test_security_path_traversal -v`：11 项运行，10 项通过、1 项跳过、0 失败；三个符号链接用例均通过，FIFO 用例仍因平台能力跳过。用户此前提供的 9 项/3 项跳过输出未提供 HEAD 与跳过原因，仍作为独立历史结果，不替代本次专项结果。
- `.venv\Scripts\python.exe tests\run_tests.py` 完整本地 mock E2E：7 项通过，230.911 秒，退出码 0。测试输出中的 content-filter 和段落错配异常来自预期负向 fixture。
- 当前工作区的 `compileall`、`git diff --check` 和 Markdown 本地链接目标检查通过。此记录不表示真实 Provider/Notion 调用、人工译文/版式验收、EPUBCheck/阅读器或部署已通过。
- GitHub PR 状态的 `bd9f4f3` 与未推送工作区内容均为本历史检查点快照；当前 PR 状态以本文开头的 `e9adc8d` 实现基线及[续接交接](handoffs/2026-11-15-translation-workflow.md#2026-11-16-提交与-pr-状态复核)中的后续记录为准。

## 2026-11-15 当前工作区定向验证

- 基线：分支 `codex/translation-workflow-20261115`、当前 HEAD `c3f313b`；工作区包含续接开始前的未提交修改和本任务增量，完整保留清单见 handoff。Provider 环境为本机 `.venv` Python 3.14.7。
- 当前 source-only 真实采集状态：Kakuyomu 作品主页目录发现 88 个公开 episode ID，与 `publicEpisodeCount=88` 相等；采集完成 88/88，生成 88 个 normalized 单话 Markdown 和一份 793,357 字节的有序全书 export。未调用 Provider。source manifest `schema_version=1` 的 267 个文件型 artifact 经 `scripts/validate_source_manifest.py` 全部 SHA-256 核验通过。
- parser v4 支持 `widget-episodeBody`/`js-episode-body`，保留段落边界、ruby 与 emphasisDots 表示、U+3000。真实首话结构检查观察到段落/ruby/U+3000，emphasisDots 由 synthetic fixture 覆盖。保存的是抽取后的 UTF-8 可见文本，不保留原始 HTML。请求间隔默认 2 秒，adapter 与 CLI 均限制为 1.5–3 秒。
- 指定试点书籍已按用户明确确认记录为已授权；用户也已授权 JOJO/JYQF 各自职责所需的最小数据类别。阶段预检和别名路由通过合成测试，但 `PROVIDER_DATA_POLICY` 仍默认为空，实际 allowlist 尚未本地配置；其他 Provider、Gemini 和 Notion 不在该授权范围。疑似旧凭据按用户指示视为已轮换。平台访问规则观察与用户“不需要官方澄清”的决定分开记录；不称平台背书或法律结论。
- 本轮未调用真实 Provider 或 Notion，也未验证翻译质量、EPUB 阅读器或部署。译文目录仍为空，正文段落/ruby/标点人工验收尚未完成。用户指定书籍授权和 JOJO/JYQF 最小职责类别已确认；运行时 Provider allowlist 仍为空。测试跳过项不能记为通过。
- 本次相关模块定向单测 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_epub_builder -q`：114 项通过；后续 U+3000 流水线修复后的合并相关回归为 195 项通过，完整 mock E2E 为 7 项通过，详见[全目录采集与最终回归](#2026-11-15-kakuyomu-公开目录全量采集与-i3-导出)。
- 完整 mock E2E runner 会在最终 `OK` 汇总前打印若干 pipeline 失败栈；这些来自 runner 的预期负向 fixture（content filter、段落错配等），不能单独视为 suite 失败。

### 2026-11-15 Kakuyomu 公开目录全量采集与 I3 导出

- 用户确认试点作品已获得明确授权；用户是普通读者，要求从作品主页发现全部公开目录，再逐话通过普通 episode URL 获取正文，并明确表示不需要官方澄清。按此用户决定实施；平台规则观察保留为风险背景，不表述为平台背书或法律结论，也不设为本试点等待官方答复的前置条件。采集遵守 `robots.txt`，不登录、不跟随重定向、不访问 `/read`，不调用未文档化 API。请求间隔默认 2 秒，adapter 与 CLI 将其限制为 1.5–3 秒。
- 真实 source-only 运行发现主页声明的 88 个公开 episode，与 `publicEpisodeCount=88` 一致；逐话采集完成 88/88。最终 source manifest `schema_version=1` 的 267 个文件型 artifact 全部通过 SHA-256 验证；生成 88 个 normalized 单话 Markdown 与一份 793,357 字节的有序全书 export。保存抽取后的 UTF-8 可见文本，不保存原始 HTML；未调用 Provider 或 Notion。该目录范围不包含草稿/私有话，不证明站点声明范围外的完整性，也不是同一时刻的原子快照。
- Parser v4 处理 `widget-episodeBody`/`js-episode-body`，保留段落边界、将 ruby 转为 `｜基字《读音》`、将 emphasisDots 转为 `｜文本《・・・》`，并保留 U+3000；真实首话可见段落/ruby/U+3000，旁点由 synthetic fixture 覆盖。随后 mock E2E 暴露 `utils.split_paragraphs` 及 pipeline 额外 `.strip()` 会剥除 U+3000；已改为只裁剪 ASCII 空白，并在 annotation/translation 段落拆分时复用此函数。新增 `TestParagraphContracts.test_split_paragraphs_preserves_fullwidth_and_nonbreaking_indent`。
- 修复后 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestParagraphContracts tests.test_source_pipeline_linkage -q`：36 项通过；Kakuyomu 两项 URL 到 mock 翻译 E2E 定向运行：2 项通过；相关模块合并回归（Kakuyomu adapter/workflow、manifest/ingestion/materialization、EPUB builder、pipeline contracts、source linkage）195 项通过；`.venv\Scripts\python.exe tests\run_tests.py`：7 个本地 mock E2E 测试方法通过，210.940 秒，退出码 0。首次 U+3000 修复前的 E2E 暴露了上述缺陷，修复后定向与完整 E2E 均通过。
- Python `py_compile`（`utils.py`、`pipeline.py` 和新增/修改的对应测试）及两个 Kakuyomu CLI `--help` 通过。真实来源根目录 `source_manifest.json` 只读检查：`schema_version=1 artifacts=267 files_verified=267`。人工正文/ruby/标点验收、真实 Provider 翻译、Notion、EPUBCheck/阅读器与部署仍未验证；译文目录仍为空。

### 历史检查点：Kakuyomu 主页目录发现与逐话续传

以下内容是 parser v4 和真实全目录采集前的阶段记录；与当前状态不一致之处以本节首部和[全目录采集记录](#2026-11-15-kakuyomu-公开目录全量采集与-i3-导出)为准。

- 用户明确要求普通读者场景从作品主页发现完整公开目录，再逐话通过普通 episode URL 获取正文；不依赖作者 ZIP。`discover_kakuyomu_work_catalog()` 读取主页 Next.js Apollo `Work.tableOfContentsV2`，按目录组顺序展开 episode ID/title，校验唯一条目数与 `publicEpisodeCount` 相等后生成普通 episode URL。解析缺字段、重复 ID、计数不符、robots 拒绝或站点结构变化时 fail-closed，不请求章节正文。
- `scripts/ingest_kakuyomu_pages.py --work-url` 可单独发现、排他保存 `source_catalog.discovered.json`、将目录交给 checkpoint 后逐话请求并即时归档；此来源采集模式不需要 Provider 配置。`scripts/run_kakuyomu_workflow.py --work-url` 先预检 Provider，再将发现/采集、来源版本物化、确定性路径/TM 键/`CHAPTER_MAP` 与生产翻译流水线串接。robots 和目录元数据/限额快照保持 fingerprint；每话 raw 正文独立保存哈希并记录到 checkpoint。暂时失败后从首个未完成话继续，已完成正文不重抓；累计正文限额从 manifest 中校验后的已完成 raw 版本恢复。该流程是跨时间滚动采集，不是同一时刻的原子全书快照；目录未变的完整 checkpoint 不自动更新正文。两个入口均不登录、不跟随重定向、不访问 `/read`，默认请求间隔 2 秒；主页公开目录不包括草稿/私有话，也不证明站点声明范围外的作品完整性。
- `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`：23 项通过，包含临时 503 后只续取未完成话和恢复累计文本限额。相关回归命令（包括来源、审核、Provider 契约、RAG 与安全模块）309 项运行、305 项通过、4 项 Windows 能力限制跳过、0 项失败。跳过为 3 项符号链接 fixture（`WinError 1314`）和 1 项 FIFO fixture（Windows 不支持 `os.mkfifo`）；故障注入错误日志是预期测试输出。
- `.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`：1 项通过，由 runner 启动本地 mock server。该 synthetic E2E 从主页目录 fixture 贯通到所有目录页面、归档、版本化物化、确定性章节映射和 mock 翻译/TM；不访问 Kakuyomu 或真实 Provider。完整 `.venv\Scripts\python.exe tests\run_tests.py` 的最新结果另见本节后续记录。
- `.venv\Scripts\python.exe tests\run_tests.py`：7 个本地 mock E2E 测试方法通过，261.806 秒，退出码 0。输出中的 content-filter、段落数量不匹配等失败堆栈来自预期负向 fixture；runner 最终 unittest 汇总为 `OK`。未调用真实 Kakuyomu、Provider 或 Notion。此前 235.228 秒结果是主页发现实现但逐话续传改造前的历史检查点。
- 2026-11-15 经配置代理进行一次真实主页结构探测：发现 88 个唯一 episode 条目，与页面 `publicEpisodeCount=88` 相符；只检查目录结构，没有批量请求章节正文。第一话的真实导入是单话独立证据，不能视为全书下载或格式人工验收。
- `scripts/ingest_kakuyomu_pages.py --help` 与 `scripts/run_kakuyomu_workflow.py --help` 可执行并显示 `--work-url`。全目录真实正文抓取、真实 Provider 翻译、段落/ruby/标点人工验收、公开分发范围及平台批量访问规则仍未由这些验证证明。

### 2026-11-15 Kakuyomu 显式 URL 单话导入

- 用户明确指定普通读者场景直接通过其提供的普通 episode URL 获取原文，并确认试点作品已获授权；作者专用 ZIP 不作为本试点输入或阻塞。此前针对页面做过一次结构探测；本次 adapter 使用显式 JSON catalog 再次请求 `robots.txt` 和该单一页面，不遍历作品目录、不请求 `/read`、不登录、不跟随重定向，默认请求间隔 2 秒。
- 导入前复核用户指定原文根目录为空，且 `source_catalog.json`、`source_manifest.json`、`source_checkpoint.json` 均不存在；以 `CreateNew` 新建只含一话 URL/ID/顺序的 catalog，再将归档写入原文根目录。该目录位于仓库外，保留原样，不将书籍内容纳入版本控制或日志。
- `.venv\Scripts\python.exe scripts\ingest_kakuyomu_pages.py --source-root <原文根目录> --catalog source_catalog.json --output-root <原文根目录> --request-delay-seconds 2`：退出码 0，报告 `status=complete`、`discovered_count=1`、`completed_count=1`、`pending_count=0`。命令输出不含正文。用户原文根目录中的 manifest 记录 episode metadata 与 raw text 两个文件型 artifact；raw artifact 为 9,841 字节。
- `.venv\Scripts\python.exe scripts\materialize_source_markdown.py --root <原文根目录> --work-id 16817330668011048405 --episode-id 16817330668011089189 --manifest source_manifest.json --max-bytes 16777216`：创建 normalized artifact `v-49f52b5057a5317e202b57b6f01ffadd3d86ae2f5603474ce6dbb93796274d9d`，其父版本为 raw `v-aa5bcc437805cce5805e2b5e61cce32478e1a8efd09702f9f03beaa7e76550be`。两份文件均为 9,841 字节且 SHA-256 均为 `46a3b70f4f514be3f86396d477cae7bcc89f45f4ea23d2773f1e5657ea1f393f`；字节序列比较相同。本步骤不清洗或展示正文。
- `.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <原文根目录> --manifest source_manifest.json`：`schema_version=1`、3 个 artifact、3 个文件校验通过。`tests.test_kakuyomu_page_source` 的 HTTP/HTML 均为 synthetic fixture，不访问网络。
- 专项单测 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q`：74 项通过；`.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -q`：16 项通过。新 adapter、CLI 和测试 `py_compile`、CLI `--help`、`git diff --check` 通过。
- 人工正文/段落/ruby 标点验收、后续章节 URL 清单、`CHAPTER_MAP`/TM 键以及真实 Provider 翻译仍未完成。用户授权指定作品不等于平台对批量抓取或公开分发的许可；本次只访问用户指明的普通 episode URL，且遵守 robots 和请求间隔。

## 2026-11-15 当前 checkout 回归验证

- Kakuyomu URL adapter 增量后的相关回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_story_summary_review tests.test_tm_review tests.test_epub_builder tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit tests.test_scratch_filter -q`：298 项运行，294 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败。跳过为 3 项符号链接创建权限限制（`WinError 1314`）和 1 项 Windows 不支持 FIFO；故障注入错误日志是预期 fixture。
- URL adapter 首次实现后的历史 `.venv\Scripts\python.exe tests\run_tests.py`：5 个本地 mock E2E 测试方法通过，251.047 秒，退出码 0；该历史批次尚未包含下方新增的 URL 到翻译链路测试。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_story_summary_review tests.test_tm_review tests.test_epub_builder tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit tests.test_scratch_filter -q`：加入来源到版本化 mock 翻译端到端用例后，286 项运行、282 项通过、4 项按 Windows 能力跳过、0 项失败。跳过为 3 项符号链接创建权限限制（`WinError 1314`）和 1 项 Windows 不支持 FIFO；故障注入中的错误日志属于预期测试场景。
- Kakuyomu 作者 ZIP/TXT 边界增量后，`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q`：62 项通过；新增 UTF-8 `.txt` 用例仅使用合成内容。未因该测试变更生产代码，因此未重跑完整 mock E2E。
- `.venv\Scripts\python.exe tests\run_tests.py`：5 个本地 mock E2E 测试方法通过，231.163 秒，退出码 0。新增用例贯通显式本地 catalog 导入、normalized 来源版本物化、`CHAPTER_MAP.source_version_id`、真实 `TranslationPipeline.run_all()` 的本地 mock 四阶段请求、译文写入和 TM 来源版本记录。该路径使用合成日文、mock embedding 与本机 HTTP mock；未调用真实 Provider、Notion、Kakuyomu 或读取书籍正文。
- `.venv\Scripts\python.exe -m py_compile tests\test_e2e.py`、`git diff --check`：通过。路由改动前的 `compileall`、`pip check` 及 Markdown 链接结果见各自检查点；本轮全仓 Markdown 链接检查结果记录于当前 handoff，链接检查不等价于完整 CommonMark/GitHub 渲染器验收。
- 该回归只证明当前代码在合成数据和本地 mock 上的契约行为；不证明 JOJO/JYQF 端点、模型 ID、当前凭据、平台自动采集、真实译文质量、EPUB 阅读器兼容性或部署可用。

## 2026-11-15 Kakuyomu URL 到 mock 翻译端到端验证

- 新增 `tests.test_e2e.E2ETestSuite.test_kakuyomu_page_archive_flows_through_versioned_mock_translation`。使用 `tests.test_kakuyomu_page_source` 的 synthetic `robots.txt`/HTML 和 FakeOpener，不发出 Kakuyomu 网络请求；调用生产 `KakuyomuPageAdapter` 与 `collect_source` 将显式普通 episode URL 的可见文本写入 manifest，再物化 normalized Markdown。
- 测试显式构造含 normalized `source_version_id` 的 `CHAPTER_MAP`，调用生产 `TranslationPipeline.run_all()`，由仓库本地 mock server 响应四个阶段请求；校验请求仅含 robots 与 catalog 页面、归档文本、译文写入及 TM `source_provenance` 版本绑定。多段原文按段落进入 TM，测试逐段拼接核对完整源文。
- 定向命令 `.\.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_page_archive_flows_through_versioned_mock_translation`：1 项通过。完整 `.venv\Scripts\python.exe tests\run_tests.py`：6 个 mock E2E 测试方法通过，285.752 秒，退出码 0。
- 同一工作树相关回归命令见上方：298 项运行、294 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败。该验证仅证明 synthetic 页面和本地 mock 链路；真实首话 URL 导入是独立的人工执行证据，真实 Provider 翻译、章节映射、格式人工验收和平台批量访问许可均未由本测试证明。

## 2026-11-15 来源到版本化翻译端到端验证

- 新增 `tests.test_e2e.E2ETestSuite.test_local_source_archive_flows_through_versioned_mock_translation`：合成 UTF-8 TXT 经显式 catalog 导入到 source manifest，按 raw 版本物化 normalized Markdown，再用显式 `CHAPTER_MAP` 和 `source_version_id` 执行实际 `TranslationPipeline.run_all()`；OpenAI-compatible 四阶段请求连接 `tests/mock_server.py`，embedding 使用确定性 mock。
- 验收检查包括：导入报告不回显源文且输入字节不变；翻译输出写入指定目标并通过末段格式检查；TM 记录原译对且 `source_provenance.source_version_id` 与 manifest normalized 版本一致。
- 定向命令：`.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_local_source_archive_flows_through_versioned_mock_translation`，1 项通过。完成后运行当前 checkout 全量相关单测 286 项（282 通过、4 项 Windows 能力跳过）和 `.venv\Scripts\python.exe tests\run_tests.py` 的 5 个 mock E2E 测试方法（231.163 秒），均无失败。
- 该测试证明操作者显式提供/映射的本地来源可以穿过现有版本系统进入翻译流水线；它不实现 ZIP 解压、自动生成 `CHAPTER_MAP`、平台目录完整性、真实 Kakuyomu 访问、真实 Provider、真实翻译质量或部署验收。

## 环境事实

- 实现语言：Python。
- `requirements.txt` 声明 `openai`、`google-genai`、`aiohttp`、`numpy`；版本未锁定。
- 仓库没有 `pyproject.toml`、锁文件或 Python 最低版本声明。
- 本机环境快照：Windows PowerShell、Python 3.14.7（2026-11-14 复核）；本地 `.venv` 中依赖版本于 2026-11-13 记录为 `openai 3.50.0`、`google-genai 3.3.0`、`aiohttp 3.14.5`、`numpy 2.5.4`。2026-11-14 `pip check` 未发现损坏依赖。这只是本机快照，不构成项目支持版本声明或干净环境安装验收。
- 仓库未发现 GitHub Actions/其他 CI、容器、进程管理器或云平台部署配置。
- 仓库没有配置独立的 linter、类型检查器或构建后端；`unittest` 是当前自动化测试入口。
- `.env.example` 提供 API 配置名；真实 API 服务、凭据和模型兼容性需另行验证。
- 2026-11-14 在一次性 Python 3.14.7 venv 中按 `requirements.txt` 做了干净安装并通过 `pip check`；解析版本为 `aiohttp 3.14.5`、`google-genai 3.3.0`、`numpy 2.5.4`、`openai 3.51.0`。本地标准 `venv` 的 `ensurepip` 未成功；使用既有 pip 的 `--python <venv>` 目标模式完成安装。此结果验证当日单一 Windows/Python 环境，不定义受支持版本范围，也不替代锁文件。

## 配置与数据

显式 JSON 配置可通过 `CHAPTER_MAP` 为每章指定原文相对路径、译文相对路径及唯一 TM 键。映射使用 `/` 分隔，只接受根目录内 Markdown 文件；源文件与输出父目录必须存在。流水线、对齐、知识抽取和 TM 溯源核验共用此清单；没有清单时保留平铺扫描，不创建目录或推测卷/章节关系。

- 推荐项目数据布局：`projects/<项目名>/生肉/`、`熟肉/`、`Knowledge/`。
- 项目名模式与显式 `--config` JSON 模式均由 `Config.load_config` 处理。项目名模式要求成对的 `SourceArchive/` 与 `RAWs_AI/`，从归档 manifest 核验来源版本，从 `RAWs_AI/catalog.json` 生成完整映射；`raw_file`/`source_version_id` 保留 archive provenance，实际 AI 正文由 `source_input_file`/`source_sha256` 指向 `RAWs_AI`。目录缺失或清单/索引核验失败即停止，绝不扫描人读版 `生肉/`。项目根可选 `workflow_paths.json`（schema v1）设置已存在的 `output_dir` 和可选 `human_edition_root`，路径可相对项目根或使用绝对路径，且不能覆盖原文根/章节映射或令译文根与来源目录重叠；没有该配置时，默认 `熟肉/` 含子目录仍要求显式 JSON 配置。显式 `--config` 可指定自己的 `RAW_DIR`、`OUTPUT_DIR` 和 `CHAPTER_MAP`。
- `pipeline.py` 会加载仓库根目录 `.env`，并读取相应环境变量；`.env*` 默认被忽略。
- `projects/*` 默认忽略，`projects/example/` 例外。运行前确认目标项目路径，避免写入错误书籍目录。
- 进程环境变量优先于根目录 `.env`；API key 按 Provider 专属变量读取。只有 loopback OpenAI-compatible endpoint 允许使用本地占位 key。
- 设置 `TEST_WORKSPACE_DIR` 时，`Config.load_config` 不读取仓库 `.env`，避免测试继承本地真实凭据。
- `API_TIMEOUT` 以秒配置请求超时，默认 10 秒；必须是有限正数，应用于 OpenAI-compatible 聊天及 Gemini 生成、RAG embedding 和章节对齐 embedding 请求。慢速端点可在本地 `.env` 中调高；Gemini SDK 的毫秒参数由代码换算。
- `PROVIDER_DATA_POLICY` 为 JSON 对象，键为 Provider ID，值为允许接收的数据类别数组；默认 `{}`，拒绝所有远端书籍内容请求。有效类别为 `source_text`（原文）、`translation_text`（译文）、`book_knowledge`（术语/概要/指导/TM/标注上下文）、`evaluation_samples`（评测样本）。每次请求要求的全部类别都必须获准；未声明类别、无授权或无效策略均拒绝。进程环境变量优先于根 `.env` 和 JSON 项目配置。
- OpenAI-compatible Provider base URL 必须是带主机名的 HTTP(S) URL，端口语法有效，且不得包含用户名、密码、查询或片段；非 loopback 地址必须使用 HTTPS，HTTP 仅允许 `localhost` 或 loopback IP。流水线在读取章节前预检，客户端创建时再次验证。知识抽取在读取章节正文前复用同一 URL、Provider 数据类别授权和 API key 检查，客户端创建时再次验证。SDK 自动重定向已关闭；端点返回重定向时请求失败，配置时应提供规范 URL。
- 仅 loopback OpenAI-compatible endpoint 与 RAG 直接调用的本地 HTTP mock 不需要外发授权；不能据此推断本地服务不会自行转发数据。Gemini SDK 调用始终执行授权检查，`MOCK_SERVER_PORT` 本身不能放行；E2E runner 只为合成 fixture 显式注入测试用 Gemini grant。`run_all` 在读取章节前按实际阶段类别预检 Provider 授权，随后仍在客户端入口重复检查。
- 无 Gemini `source_text` 授权时，RAG embedding 不会发送原文；TM 查询/更新沿用现有降级行为。`scripts/align_chapters.py` 和 `scripts/auto_extract_knowledge.py` 在缺少授权时停止；前者不保存本轮 TM 更改，后者在读取章节正文及创建草稿前停止。
- `ENABLE_GEMINI_FALLBACK` 默认关闭；显式开启后，仅连接/超时错误、HTTP 408/429 和 5xx 会将同一请求发送到 Gemini。鉴权/请求错误、响应 schema 错误及内容拦截不触发回退。
- Gemini embeddings 使用 `GEMINI_API_KEY`；配置了 `MOCK_SERVER_PORT` 时改走本地 mock。
- `StartUP.txt` 为被忽略的本地文件，不是受支持的配置入口。疑似凭据问题见[安全记录](security-notes.md)。

## 命令

多卷项目的 JSON 清单形状示例：

```json
{
  "WORKSPACE_DIR": "D:/books/example",
  "RAW_DIR": "D:/books/example/生肉",
  "OUTPUT_DIR": "D:/books/example/Workflow/LegacyDrafts",
  "TRANSLATION_OUTPUT_MODE": "compatibility_draft",
  "INFO_PATH": "D:/books/example/Knowledge/作品基本信息.json",
  "GLOSSARY_PATH": "D:/books/example/Knowledge/Glossary.json",
  "GUIDELINES_PATH": "D:/books/example/Knowledge/guidelines.txt",
  "STORY_SUMMARY_PATH": "D:/books/example/Knowledge/STORY_SUMMARY.md",
  "TM_PATH": "D:/books/example/Knowledge/translation_memory.json",
  "CHAPTER_MAP": [
    {
      "raw_file": "Volume 1/第1話.md",
      "translation_file": "Ntera/第1話.md",
      "tm_key": "Volume1/第1話.md"
    }
  ]
}
```

实际条目和顺序须经维护者核验；不能仅凭章节号自动对应不同卷的文件。

若要把来源清单中的特定规范化版本绑定到翻译章节，配置 `SOURCE_MANIFEST_PATH`（相对 `RAW_DIR`），并在对应 `CHAPTER_MAP` 条目加 `source_version_id`：

```json
{
  "SOURCE_MANIFEST_PATH": "source_manifest.json",
  "CHAPTER_MAP": [
    {
      "raw_file": "normalized/<episode-key>/<version>.md",
      "translation_file": "Ntera/第1話.md",
      "tm_key": "Volume1/第1話.md",
      "source_version_id": "<exact version_id from source_manifest.json>"
    }
  ]
}
```

`RAW_DIR` 必须指向该 manifest 的数据根目录。选定版本须是 `normalized_source` artifact，且其 manifest 路径和文件 SHA-256 必须与映射一致；`chapter_position` 可选，用于源文件名/TM key 不含可解析章节号时选择剧情摘要窗口和章节指导。未配置新增字段时，旧三字段 `CHAPTER_MAP` 保持兼容。

```powershell
# 翻译项目目录
python pipeline.py --project <项目名>

# 使用显式多卷映射
python pipeline.py --config <项目配置.json>

# 对齐章节并生成/更新 TM
python scripts/align_chapters.py --project <项目名>

# 对齐显式映射章节
python scripts/align_chapters.py --config <项目配置.json>

# 只读核对 TM 来源索引
python scripts/validate_tm_provenance.py --project <项目名>

# 只读核对知识草稿来源新鲜度
python scripts/validate_knowledge_provenance.py --root <原文数据根目录> --manifest source_manifest.json --provenance <Knowledge目录/KNOWLEDGE_PROVENANCE_draft.json>

# 创建绑定当前候选哈希的未完成审核回执模板
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --create-template review_receipt.json

# 将经人工/外部流程审核的完整回执发布为 approved-only 术语表
python scripts/apply_knowledge_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review <回执文件名> --output Glossary_reviewed.json

# 核对显式映射章节的 TM 来源索引
python scripts/validate_tm_provenance.py --config <项目配置.json>

# 从已归档的指定原始版本生成 UTF-8 `.md` 派生 artifact
python scripts/materialize_source_markdown.py --root <数据根目录> --work-id <作品ID> --episode-id <章节ID>

# 按 manifest 来源顺序合并显式章节集合；不证明集合等于完整作品
python scripts/merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --episode-id <章节ID> --episode-id <下一章节ID> --max-bytes <必填字节上限>

# 从完整检查点导出其记录的全部章节；不证明平台目录枚举穷尽
python scripts/merge_source_markdown.py --root <数据根目录> --work-id <作品ID> --complete-checkpoint [source_checkpoint.json] --max-bytes <必填字节上限>

# 运行由 mock server 驱动的 E2E 测试
python tests/run_tests.py

# 只运行某个 E2E 测试组
python tests/run_tests.py tests.test_e2e.E2ETestSuite.test_tier1_feature_coverage

# 独立单元测试
python -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts
python -m unittest tests.test_align_chapters_unit
python -m unittest tests.test_rag_engine_unit
python -m unittest tests.test_knowledge_extraction_unit
python -m unittest tests.test_tm_provenance_unit
python -m unittest tests.test_source_manifest
python -m unittest tests.test_source_pipeline_linkage
python -m unittest tests.test_knowledge_provenance_audit
python -m unittest tests.test_knowledge_review
```

`validate_tm_provenance.py` 不写入 TM。退出码 `0` 表示有来源索引的条目与当前文件匹配且无未索引章节；`1` 表示索引结构、哈希或段落内容不一致；`2` 表示存在旧 TM 无索引、部分/未匹配来源或无法读取的源文件。退出码 `2` 不代表审计通过。

`validate_knowledge_provenance.py` 是显式输入的只读 CLI；`--manifest` 相对 `--root`，provenance 路径由调用者明确提供。退出码 `0` 表示所有来源条目均匹配当前来源版本，`1` 表示 stale/mismatch/invalid 或输入错误，`2` 表示存在缺少版本 ID 的 `unverified` 条目。它只审计 `KNOWLEDGE_PROVENANCE_draft.json`，不批准或修改知识草稿。

`apply_knowledge_review.py` 仅处理 `Glossary_draft.json` 与 `KNOWLEDGE_PROVENANCE_draft.json`。`--create-template <文件名>` 会校验候选结构并排他新建未完成回执：按当前输入的原始字节绑定两项 SHA-256，为所有术语生成 `pending` 决定和空理由。它不读取章节正文或来源 manifest，也不作审核决定；模板不能直接发布，候选文件发生任何字节变化后旧模板会因摘要不匹配被拒绝。

填写 reviewer、UTC 审核时间、每项最终决定和非空理由后，以 `--review <文件名>` 运行来源/证据核验，并在 `--output` 排他新建 reviewed bundle。回执 schema v1 的字段如下；生成的模板尚未填完这些字段：

```json
{
  "schema_version": 1,
  "candidate_glossary_sha256": "<64 位小写 SHA-256>",
  "candidate_provenance_sha256": "<64 位小写 SHA-256>",
  "reviewer": {
    "provider_id": "<Provider ID>",
    "model_id": "<模型标识>",
    "review_id": "<审核记录标识>"
  },
  "reviewed_at_utc": "2026-11-15T00:00:00Z",
  "decisions": [
    {
      "src": "<候选原词>",
      "decision": "approved",
      "rationale": "<非空理由>"
    }
  ]
}
```

每个候选词条必须恰有一个 `approved`、`rejected` 或 `escalated` 决定；只有明确批准且来源位置可验证的术语进入 bundle。脚本不调用审核 Provider；`reviewer` 字段不签名、不认证，不能证明所填人员/模型实际作出审核。运行时 RAG 使用 reviewed bundle 需显式配置 `GLOSSARY_PATH`、`RAW_DIR` 和 `SOURCE_MANIFEST_PATH`，并会重新核验来源版本新鲜度。

安装命令：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

依赖版本当前未锁定。真实 Provider 和部署验收不属于依赖安装或 mock 测试的证明范围。

## 测试解释

- `tests/run_tests.py` 分配本地端口、启动 `tests/mock_server.py`，然后运行 `tests/test_e2e.py`。可向 runner 传入 unittest 测试路径以筛选测试；直接运行 E2E 模块不会自动启动 mock server。
- `tests/run_pipeline.py` 使用 `tests/mock_genai.py` 将生产 `TranslationPipeline` 接到本地 mock Provider；E2E 不含缺少生产模块时的模拟流水线分支。
- E2E 对齐用例直接运行 `scripts/align_chapters.py`；不存在另一个模拟对齐 runner。
- 单元测试使用 `unittest`；RAG 测试会创建临时文件，并可能需要可写的系统临时目录。
- Mock 服务只验证本地请求/响应逻辑，不验证真实模型质量、安全策略实际效果、配额、网络部署或服务端 schema 支持。
- 应从仓库 runner 启动 E2E，以确保 mock server 生命周期和动态端口配置一致；直接运行 `tests/test_e2e.py` 不会自动启动服务。不能把 runner 的 mock 成功报告成生产流程或 Provider 验收。
- 测试临时目录必须可写。历史 Windows 执行曾遇到沙盒临时目录写入受限；需要时将 `TEMP`/`TMP` 指向经授权的可写临时目录，并记录环境限制，不要因此改写测试结论。
- 符号链接用例可能因 Windows 未授予创建链接权限而跳过。跳过不等于通过；报告时分别记录运行、通过、失败和跳过数量，并注明未覆盖的行为。
- 当前测试数量、覆盖率和通过状态应以实际命令输出为准。`TEST_READY.md` 中历史“71”计数不可当作最新用例数或通过结果。
- 运行诊断避免输出生成的校对意见和异常消息正文：RAG embedding 失败日志以及知识抽取/章节对齐 CLI 错误只报告异常类型。该约束降低运行记录意外包含章节内容的风险，不控制第三方 SDK 或调用外围工具自身的日志。

## 最近一次验证记录

2026-11-15 初始静态复核基线为本地 `main` 的 `d7e2afd`；后续续接在同一工作区完成实现与验证。以下每项记录单独绑定其代码/工作树基线；未注明的历史结果不能视为本次回归，也不能合并不同命令的计数或权限条件。

### 2026-11-15 完整回归与源文快照校验

- 在 `d7e2afd` 加本轮工作树改动上，`pipeline.py::run_chapter` 于事务恢复、空章节发布和翻译/TM 提交前复读原文；若源文已变化则拒绝继续。配置 `source_version_id` 时还会重新读取 manifest，验证对应文件 SHA-256、`normalized_source` 类型与章节相对路径。该检查不提供并发锁，无法消除最后一次校验之后的外部写入竞态。
- 新增合成回归：润色阶段修改原文后，章节输出和 TM 均不提交；版本映射测试现提供真实哈希匹配的临时 manifest。定向 3 项通过。
- 17 个非 E2E 测试模块合计 280 项，10.996 秒，失败 0、跳过 4。详细复核 `tests.test_security_path_traversal` 与 `tests.test_source_ingestion` 时共 41 项、跳过 4：3 个符号链接用例因 Windows `WinError 1314` 缺少创建权限跳过，1 个 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。这些行为没有在本执行上下文中覆盖。
- 用户另行提供的 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 输出为 9 项、3 项跳过、整体 `OK`；未附 commit SHA 或逐项 skip reason，不与该历史检查点的 11 项/4 项测试快照合并计数。该记录只反映当时检查点；后续 2026-11-16 工作集的权限受限与管理员复跑结果见本文首节。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 4 项通过，220.165 秒，runner 退出码 0。负向 fixture 会在控制台打印预期的拦截/契约失败堆栈；这些不是测试失败。E2E 不访问真实 Provider/Notion/站点，也不读取书籍正文。
- `.venv\Scripts\python.exe -m compileall -q pipeline.py rag_engine.py scripts tests source_ingestion.py source_manifest.py chapter_transaction.py story_summary_review.py tm_review.py epub_builder.py utils.py`、`.venv\Scripts\python.exe -m pip check`（`No broken requirements found.`）与 `git diff --check` 均通过。
- 只读目录复核：用户指定原文/译文根目录、仓库忽略项目下的 `生肉/`、`熟肉/` 均为空；7 个 EPUB 工具/配置文件位于旁边的 `projects/祝福のネトラレラ/EPUB/`。未读取章节正文。真实 Provider、Notion、站点自动化、部署及实际翻译质量仍未验证。

### 2026-11-15 I2 空输入与字节上限

- 在本地 `main` HEAD `d7e2afd` 的工作树上，修复空 catalog 被报告为 `complete` 的边界：CLI 在创建 adapter/输出前拒绝空 catalog；核心拒绝未发现章节的终端空页和零章节 complete checkpoint，同时允许空中间页继续分页。显式本地导入限制单文件 16 MiB、episode 源文件合计 1 GiB，并新增默认 16 MiB 的 JSON catalog 文件上限；三项均可由 CLI 调整。episode 上限在构造 adapter 时流式检查并绑定来源指纹，归档读取时再次限制单文件字节数。catalog 文件先以“上限 + 1”字节有界读取，超限不进入 JSON 解析或归档输出。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_security_path_traversal -q`：66 项运行、62 项通过、4 项跳过、0 项失败。3 项符号链接用例因普通 Windows 用户缺少创建权限（`WinError 1314`）跳过；1 项 FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。`.venv\Scripts\python.exe -m unittest tests.test_source_ingestion tests.test_local_source_ingestion_cli -v`：37 项通过。回归覆盖 catalog JSON、单章/整批超限、扫描后源文件扩容、超限不产生 manifest/checkpoint、空输入和中间空页。
- `.\.venv\Scripts\python.exe -m py_compile source_ingestion.py scripts\ingest_local_sources.py tests\test_source_ingestion.py tests\test_local_source_ingestion_cli.py`、`.\.venv\Scripts\python.exe scripts\ingest_local_sources.py --help` 和 `git diff --check`：通过；CLI 帮助列出 `--max-episode-bytes`、`--max-catalog-bytes`、`--max-catalog-file-bytes`。
- 只读文件名/目录库存检查：用户指定原文与译文根目录均存在但文件数为 0；仓库忽略项目的 `生肉/`、`熟肉/` 均为空，7 个 EPUB 工具/配置文件位于同级 `EPUB/` 目录。相邻书籍工作区有知识库、Agent 和 EPUB 工具文件，未发现章节文件；未读取正文。11 月 14 日观察到的 48/19/19 章文件计数仅作为历史快照，不用于当前输入判断。
- 未重跑完整 mock E2E；来源导入仍未接入生产翻译路径。以上上限只限制单次本地导入 catalog，不是整个归档目录的累计容量，也不为未来网络 adapter 提供流式响应大小控制。未访问作品页面、Provider、Notion 或真实章节内容。

### 2026-11-15 I2 清单内容累计上限

- `source_manifest.py::verified_manifest_content_bytes` 校验清单中所有文件型 artifact 的 SHA-256，并累计其内容字节数；同一 artifact 的历史版本均计入，无文件路径的元数据节点不计。
- `collect_source(..., max_archive_bytes=...)` 与 `scripts/ingest_local_sources.py --max-archive-bytes` 增加显式可选上限，没有默认值。每话写入前会一次性预检 episode metadata 与 raw source 两个新增版本；超限时两者均不追加，checkpoint 保留待处理章节并暂停为 `archive_limit`。同一 checkpoint 绑定上限；改变额度须使用新 checkpoint 路径，重新扫描时沿用清单的版本幂等性。
- 该上限是新增写入门禁，不会清理或拒绝只复用既有版本的幂等重跑；已有清单总量即使高于配置值，后续新增版本仍会因投影总量超限而暂停。
- 上限按清单登记的逻辑内容字节计，不是物理磁盘配额：不含清单/checkpoint JSON、文件系统分配开销或未登记孤儿/临时文件；后续不经该导入器写入的 artifact 不受此参数持续约束。计数在一次采集启动时校验，此后在进程内递增；并发写同一清单不受支持。未来 HTTP adapter 仍需单独的流式响应字节限制。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli -q`：60 项通过。覆盖历史版本累计、内容不变时恰好达到上限仍可幂等完成、超限前不写新章节版本、暂停/同额度重试/更换 checkpoint 额度绑定及 CLI 返回状态。
- 加入本地来源、版本链接、知识/TM 来源、翻译契约、对齐、知识抽取及路径安全的 12 模块回归后，212 项运行、208 项通过、4 项跳过、0 项失败。3 个符号链接测试因 Windows `WinError 1314` 无创建权限跳过，1 个 FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m py_compile source_manifest.py source_ingestion.py scripts\ingest_local_sources.py tests\test_source_manifest.py tests\test_source_ingestion.py tests\test_local_source_ingestion_cli.py`、`.venv\Scripts\python.exe scripts\ingest_local_sources.py --help`：通过；帮助列出可选 `--max-archive-bytes`。`git diff --check` 通过；README 与 `docs/` 共 13 个活动 Markdown 的 75 个本地文件链接目标存在。
- 未重跑完整 mock E2E；此前 4 项 E2E 早于该子项，不覆盖本次上限代码。上述验证使用临时合成数据，不涉及真实来源、Provider、Notion 或书籍正文。

### 2026-11-15 I3 UTF-8 Markdown 物化基线

- 新增 `source_ingestion.py::materialize_episode_markdown` 与 `scripts/materialize_source_markdown.py`。命令要求显式 `--work-id`/`--episode-id`，只从 manifest 中选择与最新 episode metadata 关联的最新 raw artifact；检查原始内容的 SHA-256、严格 UTF-8 解码和默认 16 MiB 字节上限，生成不可变 `.md` artifact 并记录 raw parent。相同来源重跑幂等；非 UTF-8、哈希不匹配、超限、未登记的占用输出路径均拒绝，不回显正文。
- 该基线把合法 UTF-8 字节原样写入 `.md`，包括 BOM、换行和空白；不处理标题、前后记、作者话、插图标记、站点格式，也没有段落差异映射、全书合并、`CHAPTER_MAP` 生成或翻译流水线接入。故只关闭 I3 的物化前置子项，不宣称已完成规范化。
- `.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v`：4 项通过。覆盖字节保真/哈希/父版本/幂等、非 UTF-8 拒绝、字节上限及 CLI 不回显正文。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_security_path_traversal -q`：70 项运行、66 项通过、4 项跳过、0 项失败。3 项符号链接用例因 Windows `WinError 1314` 跳过；FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m py_compile source_ingestion.py scripts\ingest_local_sources.py scripts\materialize_source_markdown.py tests\test_source_ingestion.py tests\test_local_source_ingestion_cli.py tests\test_source_markdown_materialization.py`、`.\.venv\Scripts\python.exe scripts\materialize_source_markdown.py --help` 与 `git diff --check`：通过。README 与 `docs/` 下 12 份活动 Markdown（共 13 份）本地链接目标检查无缺失；未验证标题锚点。
- 截至这条 I3 记录形成时，尚未重跑完整 mock E2E；当时来源导入与物化未接入生产翻译路径。后续 I4 续接及 E2E 状态见下列记录。该阶段未读取真实章节内容或调用 live 来源、Provider、Notion。试点原文/译文目录仍为空；I3 格式转换/差异映射和 I4 来源变化后的持久过期治理仍待实现。

### 2026-11-15 I3 显式章节集合导出

- 新增 `source_ingestion.py::materialize_episode_collection_markdown` 和 `scripts/merge_source_markdown.py`。CLI 要求显式重复提供有序 `--episode-id` 和必填 `--max-bytes`；校验 ID 不重复、manifest 元数据位置严格递增、所选 normalized artifact 仍关联各自最新 raw 版本、文件哈希和 UTF-8。内容按输入顺序以 `\n\n` 分隔，输出作为不可变 `export` artifact，父版本逐项记录 normalized 版本；来源更新后生成新的 export 版本，完全相同输入重跑幂等。
- 此导出是显式章节集合，不推断 catalog/站点枚举完整，不得称为完整全书；不做站点格式转换、标题注入、差异映射、章节映射生成或翻译流水线接入。输出大小包括分隔符，未设默认额度，CLI 调用者必须明确给定；失败在写入 output/manifest 前拒绝。
- `.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization -v`：11 项通过。覆盖顺序与父版本、幂等、来源更新后的新 export、raw 父文件损坏及过期/重复/乱序输入拒绝、字节上限、失败前置无写入以及 CLI 正文不回显。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：219 项运行、215 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败。3 个符号链接测试因 `WinError 1314` 跳过，1 个 FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- 本次涉及生产/测试 Python 文件 `py_compile`、合并 CLI `--help`、`git diff --check` 通过；README 与 `docs/` 下 13 份活动 Markdown 的 75 个本地文件链接目标和 9 个本地标题锚点均解析。锚点检查使用简化 slug 规则，不是完整 CommonMark/GitHub 渲染器。完整 mock E2E 未重跑：新工具不接入生产流水线；试点原文/译文目录仍为空，未用真实章节验收。

### 2026-11-15 I3 完整检查点目录导出

- checkpoint schema 升为 v5，逐话保存采集完成时绑定的 raw artifact version ID；`complete` 现在要求 discovered/completed episode 集合相同。已完成的 v3/v4 检查点缺少该版本绑定，拒绝自动迁移；未完成且无已完成章节的旧检查点仍按来源指纹和 manifest 身份规则迁移。
- `source_ingestion.py::materialize_complete_checkpoint_catalog_markdown` 与 `scripts/merge_source_markdown.py --complete-checkpoint [PATH]` 可从完整 checkpoint 按 catalog 顺序导出全部 normalized 章节。不传 `PATH` 时默认读取 `source_checkpoint.json`。导出在同一 manifest 快照中核对当前 checkpoint JSON 记录的章节、每个 raw version 当前性，并复用现有 UTF-8、哈希和输出上限门禁。CLI 报告 `coverage_scope=complete_checkpoint_catalog` 和来源指纹。
- checkpoint 是未签名、可编辑的本地 JSON；此模式只验证其当前记录的 catalog 条目及版本绑定，不证明记录未经改写或平台/来源目录枚举穷尽；不做站点格式规范化、段落差异映射或生产翻译流水线接入。没有读取真实章节或访问来源页面。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：224 项运行、220 项通过、4 项跳过、0 项失败。跳过 3 个因 Windows `WinError 1314` 无法创建的符号链接 fixture，以及 1 个 Windows 不支持的 FIFO fixture。完整 mock E2E 未重跑，因为改动仅触及隔离的来源 checkpoint/导出路径。
- `.venv\Scripts\python.exe -m py_compile source_ingestion.py scripts\merge_source_markdown.py tests\test_source_ingestion.py tests\test_source_markdown_materialization.py`、`.venv\Scripts\python.exe scripts\merge_source_markdown.py --help` 和 `git diff --check`：通过。

### 2026-11-15 I4 来源版本绑定子项（首次验证）

- 扩展 `CHAPTER_MAP`：可选 `source_version_id` 需要 `SOURCE_MANIFEST_PATH`（相对 `RAW_DIR`），并验证目标版本存在、属于 `normalized_source`、路径与 `raw_file` 一致且文件 SHA-256 有效；不带该字段的既有三字段映射保持兼容。
- `CHAPTER_MAP.chapter_position` 可选，必须是大于零的整数；有目录序号但原文路径为内容寻址名称时，流水线用它选择剧情摘要窗口和章节指导，不从哈希或平台 ID 推断章节号。
- `pipeline.py` 和 `scripts/align_chapters.py` 将版本 ID 写入 TM 来源记录；`scripts/auto_extract_knowledge.py` 将版本 ID 写入章节输入/来源清单；`scripts/validate_tm_provenance.py` 在配置 manifest 时复核版本、路径及哈希，未配置时将版本关联报告为 `unverified`。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：182 项运行，178 项通过、4 项跳过、0 项失败。3 项符号链接测试因 Windows `WinError 1314` 跳过，FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，527.593 秒，退出码 0。runner 控制台中负向 fixture 的内容拦截、格式异常 traceback 是预期断言输入；不代表 E2E 失败或真实 Provider 调用。
- `.venv\Scripts\python.exe -m py_compile pipeline.py source_manifest.py source_ingestion.py utils.py scripts\align_chapters.py scripts\auto_extract_knowledge.py scripts\ingest_local_sources.py scripts\materialize_source_markdown.py scripts\validate_tm_provenance.py tests\test_align_chapters_unit.py tests\test_knowledge_extraction_unit.py tests\test_local_source_ingestion_cli.py tests\test_pipeline_contracts.py tests\test_source_ingestion.py tests\test_source_manifest.py tests\test_source_markdown_materialization.py tests\test_source_pipeline_linkage.py`：通过。
- `scripts\ingest_local_sources.py --help`、`scripts\materialize_source_markdown.py --help`：通过。README 与 `docs/` 共 13 份活动 Markdown 检查 73 个本地文件链接目标及 8 个本地标题锚点，均存在；`git diff --check`：通过。标题锚点检查使用本地 Markdown 标题 slug 规则，不是完整 CommonMark/GitHub 渲染器。
- 该组验证只证明合成数据的版本绑定和当时的只读核验契约；当时尚未自动比较最新 manifest 版本或持久化译文/知识的过期状态。也没有真实章节、真实 Provider、站点、Notion 或部署验收。指定作品授权按用户明确确认记录为已确认；该确认不替代平台访问规则及 Provider/Notion 各自的数据接收范围。

### 2026-11-15 I4 新来源版本只读审计增量（CRLF 修复前）

- `scripts/validate_tm_provenance.py` 现在按 manifest 追加顺序确定每个 `artifact_id` 最新的 `normalized_source`。TM 引用版本仍会先单独验证；若该 artifact 有更新且最新版本可验证，审计报告 `stale`；若最新版本文件无法通过哈希/路径核验，报告 `invalid`。审计只读，不修改 TM、译文或知识清单。
- `tests.test_source_pipeline_linkage` 新增端到端合成回归：建立初始来源和 TM 记录、导入并物化同一 artifact 的新来源版本、验证旧 TM 报告 `stale`，再篡改最新物化文件并验证报告 `invalid`。
- `.venv\Scripts\python.exe -m unittest tests.test_source_pipeline_linkage tests.test_tm_provenance_unit -v`：21 项通过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：此增量在 CRLF 修复前运行 183 项，179 项通过、4 项跳过、0 项失败。3 项符号链接测试因 Windows `WinError 1314` 跳过；FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- 上一节记录的 `.venv\Scripts\python.exe tests\run_tests.py` 4 项本地 mock E2E（527.593 秒）是在本次只读 TM 审计增量之前运行；本次没有重跑该长时 E2E。此增量只改 TM 审计和其合成测试，但不声称本次 E2E 覆盖它。
- `.venv\Scripts\python.exe -m py_compile scripts\validate_tm_provenance.py tests\test_source_pipeline_linkage.py`、`.venv\Scripts\python.exe scripts\validate_tm_provenance.py --help`：通过。
- README 与 `docs/` 共 13 份活动 Markdown 检查 75 个本地链接目标和 8 个本地标题锚点，均存在；`git diff --check`：通过。锚点使用本地 Markdown 标题 slug 规则，不是完整 CommonMark/GitHub 渲染器。
- 无真实章节、Provider、站点、Notion 或部署验收。
- I4 仍未自动生成章节映射或持久化/传播翻译与知识过期状态；这项只读审计不等于下游全链版本治理。

### 2026-11-15 I4 原始字节与 TM 文本哈希对齐

- 修复 `scripts/validate_tm_provenance.py` 对 manifest artifact `content_sha256` 与 TM `raw_sha256` 的直接比较。前者覆盖物化文件的原始字节；后者与流水线一致，覆盖读取后 Unicode 文本重新编码的 UTF-8。文本模式会统一 CRLF/LF，因此两种摘要不可直接比较。审计现在分别由 manifest 校验原始字节哈希，并用 TM 文本哈希核对读取的文本及来源路径/版本 ID。
- `tests.test_source_pipeline_linkage.SourcePipelineLinkageTests.test_tm_audit_verifies_byte_preserving_crlf_source_version` 构造 CRLF 原文、字节保真的 normalized artifact 和匹配 TM provenance，确认审计结果为 `verified`；fixture 同时确认物化文件仍保留 CRLF 原始字节。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：184 项运行、180 项通过、4 项跳过、0 项失败。3 项符号链接测试因 Windows `WinError 1314` 跳过；FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m py_compile scripts\validate_tm_provenance.py tests\test_source_pipeline_linkage.py` 与 `git diff --check`：通过。E2E 未在本次只读审计修复后重跑；没有真实章节、Provider、站点、Notion 或部署验收。

### 2026-11-15 I4 知识草稿新鲜度审计

- 新增 `scripts/validate_knowledge_provenance.py`，通过显式 `--root`、相对 `--manifest` 和 `--provenance` 路径只读审计完整的知识候选 provenance v1。它流式计算文本哈希、核对来源版本 ID、manifest artifact 类型/路径/字节哈希，并比较同一 `artifact_id` 的最新追加版本；状态为 `verified`、`stale`、`mismatch`、`invalid` 或 `unverified`，不输出正文、不将完整源文本载入内存，也不修改草稿或 manifest。
- `source_manifest.latest_artifacts_by_kind` 提取由 manifest 追加顺序定义的最新 artifact 选择逻辑，供 TM 与知识草稿审计共用。
- `tests.test_knowledge_provenance_audit` 的 5 个合成用例覆盖当前 CRLF 来源、来源更新、最新文件篡改、旧 provenance 缺失版本 ID 和 CLI 输出不含正文。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：189 项运行、185 项通过、4 项跳过、0 项失败。3 项符号链接测试因 Windows `WinError 1314` 跳过；FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_provenance_audit tests.test_source_pipeline_linkage tests.test_tm_provenance_unit -v`：27 项通过。`py_compile` 涵盖本次修改的 source manifest、TM/知识审计器及两组审计测试：通过；知识审计 CLI `--help`：通过。
- mock E2E 4 项通过的记录早于来源版本审计；本次没有重跑 E2E，因为增量限于只读审计入口及其共享 latest-selector helper。本地测试不验证真实章节、知识质量、站点、Provider、Notion 或部署。

### 2026-11-15 D-11 TM 持久化失败后的进程内状态

- `RAGEngine.update_translation_memory` 现在基于原 TM 构造候选 JSON，并通过既有原子替换写盘；只有写盘成功后才替换 `self.tm_data` 并清除该章节 embedding 缓存。序列化或落盘失败时，磁盘和进程内 TM 状态均保持旧值，同一 `RAGEngine` 实例可以重试，不会叠加尚未持久化的失败更新。
- `tests.test_rag_engine_unit` 增加失败后状态保持、缓存保持和同实例重试成功覆盖。单模块 19 项通过；`.venv\Scripts\python.exe -m py_compile rag_engine.py tests\test_rag_engine_unit.py` 通过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：208 项运行、204 项通过、4 项跳过、0 项失败。3 项符号链接测试因 Windows `WinError 1314` 跳过；FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 方法通过，231.440 秒，退出码 0。负向 fixture 的内容拦截和格式异常输出是预期测试内容；未调用真实 Provider。
- 截至该检查点，生产流水线仍先创建译文再写 TM；若 TM 写入失败，译文保留，命令报错，重跑会跳过已有译文。跨文件日志和自动对账尚未实现；该检查点状态已由下方逐章恢复日志记录更新。

### 2026-11-15 I2-I4 本地 catalog 闭环合成验证

- `tests.test_source_markdown_materialization.SourceMarkdownMaterializationTests.test_local_catalog_flows_through_export_and_versioned_chapter_map` 新增合成联测：通过本地 catalog 导入两个虚构章节，按原字节物化 normalized artifact，调用完整 checkpoint 导出 CLI，再将两个 `source_version_id` 输入生产 `pipeline.get_chapter_specs` 并核对版本映射和 manifest artifact。测试只用临时目录与虚构文本，不读取试点作品。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：225 项运行、221 项通过、4 项因 Windows 符号链接/FIFO 能力限制跳过、0 项失败。3 项符号链接 fixture 因 `WinError 1314` 跳过，1 项 FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_markdown_materialization.SourceMarkdownMaterializationTests.test_local_catalog_flows_through_export_and_versioned_chapter_map -v`：1 项通过；测试文件 `py_compile`、`scripts/ingest_local_sources.py --help`、`scripts/merge_source_markdown.py --help` 和 `git diff --check`：通过。
- 完整 mock E2E 未重跑；此测试验证 I2 本地导入、I3 checkpoint 导出与 I4 版本映射的合成数据衔接，不验证平台采集完整性、真实章节格式、Provider/Notion、翻译质量或部署。

### 2026-11-15 阶段 2 知识草稿输入保护

- 新增 `utils.reject_knowledge_draft_path`，按候选生成器的固定 basename 拒绝 `Glossary_draft.json` 与 `STORY_SUMMARY_draft.md` 作为翻译输入。`TranslationPipeline` 在读取项目信息/RAG 知识前检查两项路径；独立 `RAGEngine` 初始化也拒绝 glossary 草稿。现有正式文件名和旧项目格式保持兼容。此项只防止直接误配约定文件名，改名可绕过，不是批准状态模型。
- 新增 `tests.test_rag_engine_unit` 与 `tests.test_pipeline_contracts` 拒绝用例：RAG 不读取 glossary 草稿；summary 草稿配置在任何知识文件读取或 RAG 创建前失败。`.venv\Scripts\python.exe -m unittest tests.test_rag_engine_unit tests.test_pipeline_contracts tests.test_knowledge_extraction_unit -q`：92 项通过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：227 项运行、223 项通过、4 项跳过、0 项失败；3 项 Windows 符号链接 fixture 因 `WinError 1314` 跳过，1 项 FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，231.377 秒，退出码 0。runner 中内容拦截、schema 和段落异常日志来自预期负向 fixture；未调用真实 Provider。
- `.venv\Scripts\python.exe -m py_compile utils.py rag_engine.py pipeline.py tests\test_rag_engine_unit.py tests\test_pipeline_contracts.py` 与 `git diff --check`：通过。未读取真实作品正文或调用 Notion；批准 schema、风险分层和重命名候选防护仍未实现。

### 2026-11-15 阶段 2 审核回执与术语发布

- 新增 `scripts/apply_knowledge_review.py`：有界读取候选 glossary、provenance 和显式回执；绑定候选原始字节 SHA-256，要求 provenance 所有来源为 `verified`，重新校验 manifest `normalized_source` 版本、文件/文本/样本哈希、段落计数及候选术语实际位置。每个术语必须有唯一决定与理由；仅有证据的 `approved` 项进入新的 bundle，输出排他创建、不覆盖既有文件。输入 JSON 和单个来源章节上限均为 16 MiB。
- Reviewed bundle 含批准术语、所有决定/理由、来源版本/段落位置及候选/回执/术语哈希。`RAGEngine` 校验 bundle schema、批准集合和术语摘要；需要 `source_root` 与 manifest 配置，并在首次解析时复查来源新鲜度。只有显式将 `GLOSSARY_PATH` 指向 bundle 才会使用；旧 `Glossary.json` 路径不自动切换。
- 回执是本地 JSON 声明：reviewer Provider/model/review ID、时间与理由均未签名或认证；发布器不连接 AI，也不证明任何审核者/模型真实参与或术语语义正确。该机制不覆盖 summary、人物知识、TM 历史治理、风险升级、纠错/废弃、质量评测或 TM 入检索门禁。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_review tests.test_knowledge_provenance_audit tests.test_rag_engine_unit tests.test_pipeline_contracts tests.test_knowledge_extraction_unit -q`：106 项通过，0 项失败。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：236 项运行、232 项通过、4 项跳过、0 项失败。3 项符号链接 fixture 因 Windows `WinError 1314` 无创建权限跳过；FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，237.034 秒，退出码 0；仅连接测试 mock 服务，未调用真实 Provider。负向 fixture 的错误输出属于预期用例。
- `.venv\Scripts\python.exe -m py_compile scripts\apply_knowledge_review.py rag_engine.py pipeline.py tests\test_knowledge_review.py tests\test_pipeline_contracts.py`、`.venv\Scripts\python.exe scripts\apply_knowledge_review.py --help` 与 `git diff --check`：通过。README 与 `docs/` 共 13 份 Markdown 中的 83 个本地文件链接和 11 个标题锚点均通过简化检查；锚点算法不是完整 CommonMark/GitHub 渲染器。额度状态不可见，未估算额度阈值。

### 2026-11-15 阶段 2 审核回执模板

- `scripts/apply_knowledge_review.py --create-template <文件名>` 为现有术语候选生成未完成回执，排他新建并绑定当前 `Glossary_draft.json` 与 `KNOWLEDGE_PROVENANCE_draft.json` 的原始字节 SHA-256；各决定初始为 `pending`，模板不含审核结论，不能直接发布。模板模式仅读取候选文件，不读取章节正文或来源 manifest，也不调用 Provider；候选内容有任何字节变化时，旧回执不能用于发布。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：239 项运行，235 项通过、4 项跳过、0 项失败。3 项符号链接 fixture 因 Windows `WinError 1314` 无创建权限跳过；FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe -m py_compile scripts\apply_knowledge_review.py tests\test_knowledge_review.py` 与 `.venv\Scripts\python.exe scripts\apply_knowledge_review.py --help`：通过。`.venv\Scripts\python.exe tests\run_tests.py` 未在模板 CLI 增量后重跑；最近一次 4 项本地 mock E2E 结果属于上一增量（237.034 秒），不覆盖模板分支。该增量没有调用真实 Provider/Notion/站点或读取作品正文。
- 试点作品授权已由用户明确确认为已授权，不再列作阻塞；平台自动化规则、Provider/Notion 接收方与数据类别仍各自独立。

### 2026-11-14 审计续接与来源安全修复

- 审计分支 `codex/source-ingestion-audit-20261114` 的基线为 `e5c315452fdef7efa71b06adabbe3fc8ccaa23f9`，与 `origin/main` 一致；PR #56 已于 2026-11-14 10:04:56 UTC 合并为该提交。以下单测在该基线加当前未提交改动的工作树中运行。
- 十模块定向单测命令运行 174 项、170 项通过、4 项跳过、0 项失败。普通 PowerShell 下 3 个符号链接测试因 `[WinError 1314]` 跳过，POSIX FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过；文件类型模拟测试通过。管理员 PowerShell 重跑 `tests.test_security_path_traversal` 后 11 项运行、10 项通过、1 项跳过、0 项失败，3 个符号链接路径行为均实际执行，FIFO 用例仍因平台能力跳过。
- 用户另行提供的普通 PowerShell 路径安全模块输出为 `Ran 9 tests ... OK (skipped=3)`。当前工作树同一模块有 11 个测试方法；该 9 项结果保留为独立运行记录，不替代当前 11 项版本的管理员运行。
- 2026-11-15 在 HEAD `5ada9462244375010c38a16a9198edd9c2fc76f5` 的普通 PowerShell 会话中运行 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、7 项通过、4 项跳过、0 项失败。逐项输出确认 3 个符号链接创建测试因 `[WinError 1314]` 跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。此前管理员运行的测试代码基线为 `a71e8ee149f7d20858e8334d8456ade74c7fa7e7`；`5ada946` 仅更新 Markdown，路径安全测试和实现代码未变，因此可作为该代码版本的补充普通权限结果，但不是对 `5ada946` 重新执行的管理员结果。
- 较早的来源原型/manifest/CLI 三模块验证运行 38 项、全部通过。回归覆盖恢复快照错配拒绝、本地文件变化检测、旧 checkpoint 的 fail-closed 行为、非法状态类型及 1,200 节点无环版本链。
- `.\.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 4 个方法通过，324.564 秒，退出码 0。负向 fixture 输出的 Provider 拦截和格式错误堆栈是预期结果；不是生产 API 调用或失败测试。
- `.\.venv\Scripts\python.exe -m compileall -q pipeline.py rag_engine.py utils.py source_manifest.py source_ingestion.py scripts tests` 与 `.\.venv\Scripts\python.exe -m pip check` 均通过；后者报告 `No broken requirements found`。
- 来源验证还修复两项终端/资源风险：普通文件 helper 使用非阻塞打开及 `fstat` 拒绝 FIFO；`scratch/test_filter.py` 移除本地绝对工作区路径和摘要/词条正文输出，改用 `--workspace` 或 `TRANSLATOR_WORKSPACE`，只打印计数。`tests.test_scratch_filter` 用合成目录验证无路径、摘要或原文内容泄露。
- 未安装 `pip-audit`，本轮未运行依赖漏洞公告扫描；`pip check` 只检查已安装依赖的版本约束一致性，不能替代 CVE/advisory 检查。没有为此安装新工具或联网解析依赖。
- 上述测试只使用合成输入和本地 mock；没有调用真实 Provider、平台、Notion，没有访问被忽略的书籍项目内容，也没有检查真实凭据或仓库外部署。依赖仍未锁定；CI/部署和真实模型质量未验证。

### 2026-11-14 历史任务分支复核（`684dea2`）

- 基线：`codex/translation-workflow-20261114`，HEAD `684dea245b91ebbb4b9998935d8eb1e044c3035f`；本次执行的是该提交的本地工作区。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：133 项运行、130 项通过、3 项因 Windows 未授予符号链接创建权限跳过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个本地 mock E2E 方法通过，213.837 秒，退出码 0。
- 生产与相关测试 Python 文件 `py_compile` 通过。README 与 `docs/` 下 12 份活动 Markdown 的 65 个本地目标链接均存在；此检查不验证标题锚点。
- 仅使用合成 fixture 和本地 mock；没有调用真实 Provider、访问作品页面、读取/改写书籍正文，或测试 Notion、采集、EPUB 集成。3 项符号链接行为仍未覆盖。
- 本次复核额度信息不可见，未判断是否达到任何额度阈值。

### 2026-11-14 I1 来源版本清单原型

- 新增 `source_manifest.py`、只读 CLI `scripts/validate_source_manifest.py` 与 `tests/test_source_manifest.py`。schema v1 校验逻辑/版本 ID、内容 SHA-256、相对路径语法、唯一文件路径、父版本存在性及无环关系；追加操作使用既有原子替换 helper。`verify_manifest_files(root, manifest)` 仅核验显式清单列出文件的字节 SHA-256，使用 `utils.resolve_relative_path` 限定范围，不扫描目录。
- `.\.venv\Scripts\python.exe -m unittest tests.test_source_manifest -v`：当前 18 项合成测试通过。覆盖清单 schema/父版本、1,200 节点深层无环链、正确和错误文件哈希、无路径元数据项、路径穿越与缺失文件拒绝、CLI 成功/失败、失败不打印正文和不修改源文件。
- `.\.venv\Scripts\python.exe -m py_compile source_manifest.py scripts\validate_source_manifest.py tests\test_source_manifest.py`：通过；`.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --help`：通过。
- I2 编排核心完成前，将 I1 加入六个既有定向单元模块后运行 150 项，147 项通过、3 项因 Windows 符号链接权限跳过、0 项失败；这是当时的阶段记录，不是当前合并测试总数。
- 首轮单测发现夹具把 `raw_source` 与 `normalized_source` 错用为同一逻辑 ID，并且重复版本 ID 的断言先遇到路径冲突；已拆分逻辑 ID 并调整校验顺序，复跑通过。
- 此原型只在显式调用文件核验函数/CLI 且给出根目录时读取被清单列出的文件字节；不扫描或修改目录，不实现状态生命周期/旧 schema 迁移/流水线集成/采集。完整 mock E2E 未因该隔离模块改动而重跑；真实作品内容未访问。
- 用户于 2026-11-14 明确确认指定作品已获授权。该用户声明记录为人类确认；Kakuyomu 自动化访问方式与 Provider/Notion 的接收方/数据类别边界仍分别处理，见专题方案。

### 2026-11-14 I2 无网络采集编排核心

- 新增 `source_ingestion.py`：平台适配器通过 `SourceAdapter` 注入目录页与原文 bytes，并提供稳定的 `source_fingerprint`；核心负责编排分页、checkpoint 续传、metadata/raw 版本写入、父版本关系、相同内容幂等、访问拒绝/限流/暂时不可用暂停及分页循环停止。checkpoint v4 同时绑定来源指纹与目标 manifest 相对路径，恢复前核对两者。artifact ID 来自作品 ID、artifact kind 和章节 ID 的规范化 JSON 元组哈希。没有 HTTP 客户端、站点解析器、重试/退避策略、删除差分、并发锁或翻译流水线集成。
- 原文 bytes 先写入同目录临时文件、刷新并 `fsync`，再以不覆盖的硬链接发布；metadata、原文和 checkpoint 路径受显式根目录限制。该机制在本地 Windows 临时目录测试通过；其他文件系统对硬链接的支持仍需确认。意外 I/O 异常可能留下未引用文件，但不会把未完整写入的目标文件当作有效 artifact；重跑按内容寻址路径复用并核对哈希。
- 新增 `LocalFileAdapter` 和 `scripts/ingest_local_sources.py`：根据显式 JSON catalog 只读指定本地文件；拒绝越界/符号链接路径、重复 episode 和重复文件路径。每个 episode metadata 保存 `source_ref`；未指定时使用 source-root 相对路径。输入 catalog 不被复制；metadata 记录 catalog 中的逐话来源字段。命令不联网、不打印原文；完成返回 0、暂停返回 2、输入/处理错误返回 1。写入前拒绝 manifest/checkpoint 输出路径与 catalog 或章节输入文件别名。checkpoint v4 绑定适配器快照指纹和规范化目标 manifest 路径；本地指纹覆盖目录顺序、元数据、相对路径和源文件 SHA-256，读取时再次校验内容。缺少目标身份且已有已完成条目的旧 checkpoint 拒绝迁移；v1/v2 因缺少可核验来源指纹一律拒绝自动迁移；v3 仅在指纹匹配且没有已完成条目时可补齐目标身份。
- 来源恢复回归覆盖同一 `work_id` 下 catalog/源文件快照或目标 manifest 变化时拒绝续传、已完成 checkpoint 不能切换 manifest、旧 checkpoint 迁移边界、artifact ID 分隔符碰撞、文件初始化后变化时拒绝读取及非法 checkpoint 状态类型。
- 在代码提交 `a71e8ee149f7d20858e8334d8456ade74c7fa7e7` 上，来源与本地 CLI 模块运行 28 项合成测试，全部通过。覆盖分页/续传、快照与目标绑定、旧 checkpoint 迁移边界、输出与输入路径别名拒绝（含文件系统身份比较）、显式本地路径、`source_ref`、失败恢复、幂等、路径边界和无正文 CLI 输出。
- 同一代码提交上的三模块定向回归共 39 项，35 项通过、4 项跳过、无失败；普通权限的 `tests.test_security_path_traversal` 中 3 项因 `[WinError 1314]` 无法创建符号链接、1 项因 Windows 不支持 `os.mkfifo` 而跳过。管理员 PowerShell 对同一提交复跑路径安全模块，11 项运行、10 项通过、仅 FIFO 用例因平台不支持而跳过，3 个符号链接用例均通过。`compileall` 与 `git diff --check` 通过。
- 用户另行提供过路径安全模块 9 项运行、3 项跳过的输出；该输出未绑定 SHA，也未包含逐项跳过原因，作为独立运行记录保留，不替代上述当前提交结果。
- 最小 catalog 示例（路径和标识均为合成值，不含书籍正文）：

  ```json
  {
    "schema_version": 1,
    "work_id": "sample-work",
    "episodes": [
      {
        "episode_id": "sample-episode-001",
        "title": "Sample Episode",
        "position": 1,
        "relative_path": "volume-1/episode-001.md",
        "source_ref": "local:volume-1/episode-001.md"
      }
    ]
  }
  ```

  CLI 示例：`.\.venv\Scripts\python.exe scripts\ingest_local_sources.py --source-root "D:\path\to\source" --catalog source_catalog.json --output-root "D:\path\to\archive"`。catalog schema v1 根对象字段为 `schema_version`、`work_id`、`episodes`；episode 字段为 `episode_id`、`title`、`position`、`relative_path`，`source_ref` 可选。catalog 和每个 source file 都必须位于 `--source-root` 下；`--output-root` 必须是已存在目录。成功只表示显式本地文件已归档，不证明文件来源获取方式获平台许可。
- 原来源原型阶段在 `684dea2` 基线上运行 166 项、163 项通过、3 项因 Windows 符号链接创建权限跳过；这是历史结果，当前审计续接后的 174 项结果见本节顶部。I1 清单当前 18 项、I2 adapter/CLI 当前 20 项通过。
- Python 编译：`.\.venv\Scripts\python.exe -m py_compile source_manifest.py source_ingestion.py scripts\validate_source_manifest.py scripts\ingest_local_sources.py tests\test_source_manifest.py tests\test_source_ingestion.py tests\test_local_source_ingestion_cli.py`。CLI 入口检查：`.\.venv\Scripts\python.exe scripts\ingest_local_sources.py --help` 和 `.\.venv\Scripts\python.exe scripts\validate_source_manifest.py --help`；以上命令均通过。
- 当时未因 I1/I2 与生产翻译路径隔离而重跑 mock E2E；后续审计续接已重跑，结果见本节顶部。没有访问作品页、真实书籍正文、真实 Provider 或 Notion。作品授权已按用户明确确认记录；平台自动化访问方式、Provider/Notion 接收方和数据类别仍分别处理。
- 作品授权已按用户 2026-11-14 明确确认记录，不再列作阻塞。Kakuyomu 官方规则核查见[专题方案](source-ingestion-and-publication-plan.md#kakuyomu-i0-规则核查-2026-11-14-至-2026-11-15)：具体自动化接入方式仍未知，因此 I2 仅提供本地显式文件导入与平台无关核心，不实现 Kakuyomu live 适配器。

### 2026-11-14 PR #56 复审修复

- 段落校验先去除模型输出的首尾空白，再用 `split_paragraphs` 拒绝会被保存格式拆分成多个段落的项目；回归确认拒绝发生在译文和 TM 落盘前。
- `extract_chapter_num` 仅解析路径最后的文件名，兼容 `/` 和 `\`；多卷映射中的 `Volume 2/chapter10.md` 会选择第 10 章的故事摘要窗口及分章指导。
- 反思重译和润色将无效 JSON 归类为 `ResponseContractError` 并保留上一版译文；401 等鉴权错误、传输错误不吞掉。TM 溯源审计先校验章节值是否为数组，再区分畸形结构 `invalid` 与合法旧章节 `unindexed`。知识抽取测试显式 mock API key，不依赖宿主环境变量。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：133 项运行、130 项通过、3 项因 Windows 未授予符号链接创建权限跳过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个本地 mock E2E 方法通过，221.997 秒，退出码 0。修改涉及的 Python 文件 `py_compile`、`git diff --check` 通过。
- 用户在普通 PowerShell 中另行提供 `tests.test_security_path_traversal` 输出：9 项运行、3 项跳过；该输出没有 SHA 或逐项跳过原因，不能据此确定该运行所测代码与当前提交的关系。当前提交上的权限受限和管理员运行结果见本节“I2 无网络采集编排核心”。
- PR 自动审查报告段落来源索引、嵌套路径章节号、可选阶段解析失败回退、TM 畸形章节分类和 API key 测试隔离；以上修改和回归覆盖这些问题。验证只使用合成 fixture 与本地 mock，未调用真实 Provider 或部署服务。

### 2026-11-14 TM 来源审计 CLI 输出边界

- `scripts/validate_tm_provenance.py` 在 CLI 输出章节键、审计详情和异常消息前，将不可打印字符转成可见 `\uNNNN` / `\UNNNNNNNN` 文本；普通可打印 Unicode 保持原样，审计 findings API 不变。
- CLI 拒绝空白 `TEST_WORKSPACE_DIR`，并在加载配置前退出，避免配置层把空路径解析成系统临时目录。
- 合成回归覆盖 ESC、BEL、C1 OSC/ST、CR/LF、双向文本控制字符及异常消息；检查输出无原始控制字符且 TM 未改变。空工作区测试确认配置加载器不会被调用。
- `.\.venv\Scripts\python.exe -m unittest tests.test_tm_provenance_unit -q`：14 项通过。
- 六模块定向单测：125 项运行、122 项通过、3 项因 Windows 未授予符号链接创建权限跳过、0 项失败。
- `.\.venv\Scripts\python.exe tests\run_tests.py`：4 个 mock E2E 测试方法通过，222.269 秒，runner 退出码 0。负向 fixture 打印的异常堆栈是预期测试输出。
- 修改涉及的 Python 文件 `py_compile` 通过，`git diff --check` 通过。验证使用合成数据和本地 mock；未在真实终端验证 OSC 客户端行为，未调用真实 Provider，也未验证部署。

### 2026-11-14 requirements 干净环境验证

- 一次性 venv 按 `requirements.txt` 安装当日解析版本；`pip check` 返回 `No broken requirements found.`。
- 在该 venv 中运行 `python -m unittest tests.test_pipeline_contracts -q`：55 项通过、0 项失败；`python tests/run_tests.py`：4 个 mock E2E 方法通过，203.436 秒，退出码 0。
- E2E 使用本地 mock 与合成 fixture；没有调用真实 Provider 或读取真实项目书籍数据。venv 和临时文件已清理。
- 依赖声明仍无版本范围或锁文件；单一 Python 3.14.7 Windows 安装不能证明其他 Python 版本、操作系统或未来解析集兼容。

### 2026-11-14 Provider 路由与 URL 校验

- `.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -q`：23 项通过。覆盖现有 Sakura/Qwen/DeepSeek 路由、未知模型名在流水线章节扫描及客户端创建前拒绝、空名/首尾空格拒绝，以及 URL 协议、主机、端口和凭据约束。
- `.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts -q`：55 项通过，0 项失败；覆盖全部流水线响应/失败契约及新 Provider URL 和 HTTP 客户端策略。
- `.\.venv\Scripts\python.exe tests\run_tests.py`：4 个 mock E2E 测试方法通过，202.829 秒，runner 退出码为 0。测试使用工作区专用临时目录；输出中的内容拦截和格式校验异常来自预期负向 fixture。
- 路由只接受 `sakura`、`sakura-`、`qwen3.6-plus` 和 `deepseek-` 名称；新增模型前缀须先明确 Provider 端点与凭据映射。非 loopback HTTP、无效 URL、URL 内凭据/查询/片段均在章节扫描或客户端创建前拒绝；loopback HTTP 保持可用，OpenAI-compatible 客户端不自动跟随重定向。未调用 Provider。

### 2026-11-14 显式章节映射最终验证

- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：116 项运行、113 项通过、3 项因 Windows 符号链接权限跳过、0 项失败。合成用例覆盖多卷清单、嵌套输出、TM 键、知识抽取、溯源读取和路径边界。
- `.venv\Scripts\python.exe tests\run_tests.py`：最终工作区的 4 个 E2E 测试方法通过，205.064 秒，退出码 0；由仓库 runner 启动的本地 mock 服务响应。负向 fixture 的拦截/格式异常日志是预期行为，不代表生产 Provider 验收。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit -q`：9 项通过；验证嵌套源章节的候选来源记录同时保留原文相对路径和 TM 键。
- 真实书籍映射未生成或应用；未读取章节正文、调用 Provider 或写入忽略项目数据。五小时额度信息不可见，不能确认剩余额度阈值。

### 2026-11-14 显式章节映射

- 新增 JSON `CHAPTER_MAP` 契约：每项指定 `raw_file`、`translation_file`、`tm_key`；只接受根目录内 `.md` 路径，拒绝绝对路径、路径穿越、Windows 备用数据流语法、符号链接、重复源/目标/TM 键、缺少源文件及缺少输出父目录。旧平铺扫描保持可用。
- 流水线按清单顺序写入映射译文、TM 键和包含原/译相对路径的溯源记录；章节对齐、知识候选抽取和只读溯源审计使用同一清单/路径约定。RAG 分章指导回退使用流水线已读取的当前原文。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：116 项运行、113 项通过、3 项因 Windows 未授予符号链接创建权限而跳过、0 项失败。用例只使用合成多卷目录和 mock；没有读取真实书籍章节或调用 Provider。
- 本机 Windows 沙箱拒绝系统和工作区临时目录写入；在授权的工作区临时目录外运行后通过。首次两次沙箱内运行失败属于临时文件权限限制，不能记为代码测试失败。
- 尚未生成或应用忽略项目 `projects/祝福のネトラレラ` 的实际映射；章节关系、Provider/Notion 的目标数据类别范围及缺失译文处置仍需人类核验。指定作品授权已确认；这里未决的是数据来源/接收范围，不是作品权利。

### 2026-11-14 运行日志内容边界

- 校对严重意见不再输出到控制台；RAG embedding 错误日志和知识抽取/章节对齐 CLI 的已处理错误只报告异常类型，不输出异常消息正文。合成敏感标记回归测试确认这些输出不包含异常文本。该检查不控制第三方 SDK、E2E runner 或其他外围工具自身捕获/输出的诊断。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_align_chapters_unit -q`：84 项通过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法通过，245.423 秒，退出码为 0；仅连接本地 mock server。负向 fixture 会在 runner 汇总中显示预期失败堆栈，不是 runner 失败。
- 相关 Python 文件 `py_compile` 通过；`git diff --check` 通过。

### 2026-11-14 本地项目 TM 来源审计

- 只读枚举忽略项目 `projects/祝福のネトラレラ`：`生肉/` 下有 48 个 Markdown（39 个文件名符合 `第 N 话`）；`熟肉/` 下有 19 个 Markdown，其中 18 个章节文件与原文同名，另有 EPUB `README.md`。两个根目录第一层均没有 Markdown。
- 原文位于 `生肉/1.神んてらの世界`（18 个 Markdown）与 `生肉/2.小学五年生`（30 个）；译文位于 `熟肉/Ntera神的世界`（18 个），`熟肉/EPUB` 下的 Markdown 只有 README。此前 `Config.load_config(project=...)` 会分别取两个根目录 `os.listdir` 的首个子目录，可能漏掉一个原文卷或选中 EPUB；现已改为发现任何子目录就报错，要求显式配置 `RAW_DIR`/`OUTPUT_DIR`。本次没有调用真实项目 CLI，也没有生成/修改项目文件。
- 使用 PowerShell JSON 解析器只比较 TM 章节键与文件名，未输出 TM 正文：TM 有 19 个章节键，19/19 有同名原文，18/19 有同名译文，缺失项为 `第19話.md`。
- `.venv\Scripts\python.exe scripts\validate_tm_provenance.py --project 祝福のネトラレラ`：19 章全部 `UNINDEXED`，无来源索引；退出码 2 表示来源证据不完整。审计只读，不证明原文来源授权或译文质量。
- 只读调用现有 `align_chapter` 和段落索引辅助函数，对 18 组递归同名章节做本地启发式诊断：生成 1,376 个精确位置映射；另有 31 个原文段落、1 个译文段落没有映射。只输出计数，不调用 embedding/Provider、不写入文件；不能据此批准 TM 或自动回填来源索引。
- 项目目录被 `.gitignore` 的 `projects/*` 规则排除；对齐诊断在本地内存中读取匹配的原文/译文段落，只输出映射计数，未打印、记录或发送正文；知识文件没有打开，也没有调用 Provider。此前检查的外侧同名工作区仍只有 `.gitattributes` 和 `.gitignore`。

### 2026-11-14 空章节扫描失败保护

- `pipeline.py::TranslationPipeline.run_all` 在 Provider 授权/凭据预检后发现章节列表为空时抛出错误，不再打印“Pipeline complete”。
- `scripts/align_chapters.py` 在根目录没有 Markdown 章节，或所有原文章节都没有匹配译文时以退出码 1 结束，不保存 TM。
- 项目名模式发现 `生肉/` 或 `熟肉/` 子目录时不再选择任意首项；必须通过显式 JSON 配置确定工作目录。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_align_chapters_unit -q`：65 项通过、0 项失败。新增用例覆盖项目模式的嵌套目录拒绝、平铺布局保留、流水线空章节列表、仅嵌套原文章节和全部缺译文时不写 TM。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：105 项运行，103 项通过、2 项因 Windows 符号链接权限（`WinError 1314`）跳过、0 项失败。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法通过，204.662 秒，runner 退出码为 0；仅连接本地 mock server。负向 fixture 的预期失败堆栈由 runner 打印，不代表 runner 失败。
- 上述测试使用合成临时目录；沙箱首次拒绝 Windows 临时目录写入，获批后重跑通过。未调用真实项目 CLI、Provider 或书籍数据。
- 这些保护没有启用递归发现；本地忽略项目卷目录映射仍待 D-12 决策。

### 2026-11-14 TM 来源索引

- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：97 项运行、95 项通过、2 项因 Windows 符号链接权限（`WinError 1314`）跳过、0 项失败；覆盖旧索引清理、重复/倒序引用拒绝、CLI 成功/不一致/证据不完整退出码，以及只读审计的有效、过期、不一致、未索引、空 TM、部分来源和路径穿越场景。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法通过，221.755 秒，runner 退出码为 0；仅连接本地 mock server。负向 fixture 会打印预期错误堆栈；未调用真实 Provider。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py scripts\align_chapters.py scripts\auto_extract_knowledge.py scripts\validate_tm_provenance.py utils.py tests\test_align_chapters_unit.py tests\test_e2e.py tests\test_knowledge_extraction_unit.py tests\test_rag_engine_unit.py tests\test_tm_provenance_unit.py tests\test_pipeline_contracts.py tests\test_security_path_traversal.py`：通过。
- 审计 CLI 的 `--help` 和合成 TM 调用测试通过；合成调用返回已核实状态且 TM 文件字节未改变。`projects/example/Knowledge/translation_memory.json` 不存在，因此没有对仓库样例数据执行审计。
- 这些验证覆盖 TM 文件哈希和段落映射格式、旧 TM 读取兼容、对齐器在合并段落后的来源映射、覆盖写入时清理失效索引、重复/倒序引用拒绝、只读核验及抽取草稿来源清单；核验工具不验证模型质量、人工审核或部署。

### 2026-11-14 知识抽取候选校验

- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit -v`：7 项通过。使用合成响应和 mock client；验证结构拒绝、三份草稿排他写入、术语段落匹配/未命中、提示词截断范围、部分写入失败标记，以及无章节时不创建客户端。没有调用外部 Provider。
- 术语来源清单只报告原词的精确文本命中和段落序号；样本哈希可核对模型输入范围，但不证明生成概要的逐句事实正确。
- 多文件草稿逐项写入而非事务提交；缺少或无法解析 `artifact_status: complete` 的来源清单表示本轮候选不完整，需人工检查残留文件。
- `.venv\Scripts\python.exe -m py_compile scripts\auto_extract_knowledge.py tests\test_knowledge_extraction_unit.py` 与 `git diff --check`：通过。
- README 与 `docs/` 下 11 份活动 Markdown 的 38 个本地链接目标均存在；未检查标题锚点或仓库其他示例/历史 Markdown。
- 抽取结果在创建输出目录或文件前完成 schema/字段校验；这只验证本地候选数据形状，不验证模型内容准确性、来源可追溯性或人工批准/发布。

### 2026-11-14 外发数据授权门禁

- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit -v`：77 项运行，75 项通过、2 项跳过、0 项失败。跳过项需要 Windows 符号链接创建权限（`WinError 1314`）；新增覆盖默认拒绝、逐类别授权、环境/JSON 配置优先级、缺少授权时不创建客户端/不读取章节、设置 mock 端口仍拒绝 Gemini、RAG 与章节对齐 embedding 门禁。
- `.venv\Scripts\python.exe tests\run_tests.py`：安全复核后完整复跑，4 个 E2E 测试方法通过，218.843 秒，runner 退出码为 0；由本地 mock server 响应。输出包含负向 fixture 的内容拦截、响应契约、401 和 TM 错误等预期日志。
- `PROVIDER_DATA_POLICY` 现覆盖主请求、显式 Gemini 回退、RAG embedding、章节对齐 embedding 和自动知识抽取。该配置默认为 `{}`，没有任何真实 Provider 获得授权；本地 loopback/mock 路径与远端 Provider 授权是不同执行路径，本地服务仍可能继续转发数据。
- 安全复核发现并修复 `MOCK_SERVER_PORT` 曾被当作 Gemini 授权豁免条件的问题：生产 Gemini SDK 请求与章节对齐 embedding 现在无条件执行 Provider 授权；E2E runner 仅在合成 fixture 环境中显式注入 Gemini 测试 grant。回归测试验证即使设置 `MOCK_SERVER_PORT`，未授权 Gemini 调用仍会被拒绝。
- 以上测试验证本地门禁与 mock 行为；没有真实 Provider 请求、数据传输或部署验收。两个符号链接用例未覆盖。

### 2026-11-14 响应契约与质量门禁

- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit -v`：67 项运行、65 项通过、2 项跳过；跳过项因 Windows 未授予符号链接创建权限（`WinError 1314`）。覆盖模型路由、回退错误分类、Provider 请求超时传递及校验、TM 写入失败重跑和空译文边界。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -v`：12 项通过；覆盖 Sakura/Qwen/DeepSeek 路由映射、OpenAI 请求超时、显式开关、连接错误及 HTTP 408/429/5xx 回退，和 400/401/403/404、响应契约错误、内容拦截不回退。
- `.venv\Scripts\python.exe tests\run_tests.py`：Provider 超时配置及章节对齐 SDK mock 更新后复跑，4 个 E2E 测试方法通过，耗时 221.299 秒，runner 退出码为 0；请求由本地 mock server 响应。包含 Case 29 引号顺序门禁和 Case 59 的 401 不回退/不落盘断言。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py scripts/align_chapters.py utils.py tests/test_pipeline_contracts.py tests/test_align_chapters_unit.py tests/test_rag_engine_unit.py tests/test_e2e.py tests/mock_genai.py tests/mock_server.py`：通过。
- `.venv\Scripts\python.exe --version`：Python 3.14.7；`.venv\Scripts\python.exe -m pip check`：`No broken requirements found`。
- `Test-NetConnection 127.0.0.1 -Port 6006`：不可达；只检查了代码默认 Sakura 地址，本次没有探测其他地址或调用外部 Provider。
- Provider 路由复核：`get_primary_provider_route` 集中返回 Sakura/Qwen、DeepSeek 或显式 JOJO/JYQF 别名的 URL 与专属 Key 环境变量，请求和启动 Key 检查复用该映射。`gpt-6-luna*` 路由到 `JOJO_BASE_URL`/`JOJO_API_KEY`，精确别名 `deepseek-v4.1-flash` 路由到 `JYQF_BASE_URL`/`JYQF_API_KEY`，通用 `deepseek-flash` 仍路由到原 DeepSeek Provider；这只是配置路由，不证明端点、模型 ID 或协议兼容。`run_all` 对标注/初译预检 `source_text` + `book_knowledge`，校对/润色预检三类全集，`STRICT_REFLECTION_MODE` 开启时还要求初译 Provider 获得三类授权；显式 Gemini 回退按对应阶段复核。旧逻辑会在 `CODING_PLAN_BASE_URL` 配置为 loopback 地址或带显式端口的 URL 时覆盖已选择 URL；现在只有设置 `MOCK_SERVER_PORT` 时才覆盖为本地 mock URL。此项不实现 `CODING_PLAN_*` Provider 支持。
- 超时配置复核：`API_TIMEOUT` 默认 10 秒且必须为有限正数，现用于 OpenAI-compatible 聊天、Gemini 生成、RAG 和章节对齐 embedding；Gemini SDK 使用毫秒，HTTP mock 使用秒。慢速真实 Provider 需要操作者按本地服务特征调高，当前未做真实延迟/超时验收。
- 输出/TM 持久化故障复核：译文先创建，TM 原子写入失败会使章节调用报错但保留译文；重跑会跳过现存译文。现在仅当非空输出缺少 TM 记录时警告，并提示先确认原译对齐后人工运行章节对齐工具；空章节合法地不写 TM，不会触发告警。跨文件事务和自动恢复尚未实现，策略见 D-11。
- 2026-11-14 检查相邻书籍工作区 `..\祝福のネトラレラ_祝福的寝取系女主`：一级没有子目录或 Markdown 文件，有 2 个文件未打开；其他位置未检查，不能据此判断原文或译文不存在。
- `git diff --check`：通过。README 与 `docs/` 下 11 份活动 Markdown 的本地文件链接目标检查通过；不检查标题锚点或仓库其他示例/历史 Markdown。
- E2E 首次复跑发现 mock 校对响应缺少既有 schema 必填的 `severity`/`critique`，补齐 fixture 后通过；这不是生产 schema 的变更。
- 普通沙盒拒绝系统临时目录和仓库 `scratch/` 中测试 fixture 的访问；获批后将 `TEMP`/`TMP` 指向被忽略的 `scratch/` 并在沙盒外运行，测试通过。所有 E2E 均为本地 mock；未调用真实 Provider、未验证部署或翻译质量。

### 2026-11-14 Provider 超时配置收敛

- 新增有限正数校验，阻止 `API_TIMEOUT` 为 0、负数、非有限数或非数字；重复加载配置时无 override 会恢复 10 秒默认值。
- 环境变量和 JSON 配置中的 `API_TIMEOUT` 均传入 RAG；章节对齐的 Gemini embedding 也收到配置超时，且统一按秒配置、按 SDK 要求转换为毫秒。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestTestWorkspaceConfiguration tests.test_align_chapters_unit.TestParagraphAlignmentUnit.test_embedding_client_receives_configured_timeout tests.test_rag_engine_unit.TestRAGEngineUnit.test_gemini_embedding_client_uses_configured_request_timeout tests.test_rag_engine_unit.TestRAGEngineUnit.test_mock_embedding_uses_validated_timeout_in_seconds -v`：7 项通过；完整单元和 E2E 复跑结果见上一节。

### 2026-11-13 历史验证

- 以下结果来自 2026-11-13 的历史执行记录，不是本次新跑的测试。
- 完整命令 `.venv\Scripts\python.exe tests\run_tests.py`：历史记录为 4 个 E2E 测试方法通过，耗时约 225 秒；请求均由本机 mock server 响应。
- 聚焦单元测试命令 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit -v`：历史记录为 39 项运行，37 项通过、2 项跳过。两个跳过项需要创建符号链接；当时 Windows 用户缺少相应 OS 权限（`WinError 1314`），提升进程权限后仍无法创建。
- 当时涉及的生产和测试 Python 文件通过 `py_compile` 编译。
- 当时活动 Markdown 链接检查为 20 份文档、44 个本地链接，无缺失目标；`.agents/` 历史记录不纳入活动文档检查。最终暂存差异 `git diff --cached --check` 通过。
- 本机 `127.0.0.1:6006` 不可达；未调用 Sakura、DeepSeek 或 Gemini 外部服务。可访问的书籍数据目录没有预期章节文件。
- 此前一次 Codex Security 自动扫描未生成正式报告；2026-11-14 后续 Standard 扫描已生成 `partial` 报告，覆盖与限制见[安全记录](security-notes.md)。此前失败记录不能解释为扫描通过。

当时的 E2E 测试将 `TEMP`/`TMP` 指向仓库 `scratch/` 后运行；普通沙盒曾对临时文件创建返回 `Access denied`。其他环境需保证 Python 临时目录可写。运行期间的预期负向用例会打印 Provider 拦截或格式校验失败日志；以 unittest 最终退出码和汇总为准。

### 2026-11-15 D-11 逐章恢复日志

- 新增 `chapter_transaction.py`。每章先在输出文件同目录排他创建 JSON 恢复日志，再排他写入译文、以 TM 基线哈希保护并原子更新翻译记忆；提交成功后删除日志。重跑时在“输出已存在则跳过”前检查日志，校验 `CHAPTER_MAP`、源文/译文 SHA-256、段落及引号门禁、当前输出和 TM 基线后继续提交。已存在的匹配 TM 可识别为前次已提交；源文、输出或 TM 基线冲突时中止并保留日志，不覆盖人工更改。
- 日志会保存完整译文明文，限制为 64 MiB；哈希只验证当前内容一致性，不认证作者或审核状态。若进程在日志硬链接发布前中断，可能留下临时文件；不支持硬链接的文件系统可能拒绝创建日志。零字节/非前缀的既有输出会按冲突处理。该机制是单写入者的进程中断恢复，不承诺多进程协调、断电后的目录项持久性或自动解决冲突；无效日志或冲突需要人工检查，不能直接删除日志后重试。
- 定向用例覆盖 TM 持久化失败后从日志恢复、真实 `RAGEngine` 重试、部分输出恢复、变更源文/输出拒绝覆盖，以及外部 TM 变更不被覆盖。D-11 生产代码增量后运行完整 mock E2E：`.venv\Scripts\python.exe tests\run_tests.py`，4 项通过，232.043 秒，退出码 0；这是 D-11 检查点结果，不覆盖后续知识抽取资源限制变更。
- D-11 检查点的相关 13 模块回归：`.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：244 项运行、240 项通过、4 项跳过、0 项失败。后续章节读取上限检查点为 247 项运行、243 项通过；Provider 预检后的最新 249 项结果见下节。3 项符号链接测试因 Windows `WinError 1314` 跳过，FIFO 测试因 Windows 不支持 `os.mkfifo` 跳过。TM 写入失败日志来自预期故障注入。
- `.venv\Scripts\python.exe -m py_compile chapter_transaction.py pipeline.py rag_engine.py tests\test_pipeline_contracts.py tests\test_rag_engine_unit.py`：通过。完整回归不覆盖真实 Provider、真实章节、部署、断电、多进程或平台访问。

### 2026-11-15 知识抽取章节读取上限

- `scripts/auto_extract_knowledge.py` 先复用共享 OpenAI-compatible 设置预检，确认 base URL、`source_text` Provider 授权及远端 API key 后才读取章节正文；真正创建客户端时再次检查。最多读取前三个所选章节，逐文件有界读取最多 16 MiB；超限在创建 Provider 客户端前失败，不生成候选。映射模式继续通过安全的相对路径解析；字节读取后按 UTF-8 解码并统一 CRLF/CR 为 LF，保持原文本读取语义。现有提示词样本仍截断到 20,000 个 Unicode 字符。
- 新增回归覆盖：远端 Provider 未获 `source_text` 授权，以及已授权但缺少远端 API key 时，均在章节读取器和客户端工厂调用前失败；本地 loopback/mock 继续使用已有豁免语义。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit -v`：15 项通过；`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts -q`：66 项通过。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：249 项运行、245 项通过、4 项跳过、0 项失败。3 项符号链接 fixture 因 Windows `WinError 1314` 跳过，1 项 FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个本地 mock E2E 测试方法通过，227.106 秒，runner 退出码 0。runner 打印的内容拦截和段落契约异常来自预期负向 fixture；未调用真实 Provider。
- `.venv\Scripts\python.exe -m py_compile pipeline.py scripts\auto_extract_knowledge.py tests\test_knowledge_extraction_unit.py tests\test_pipeline_contracts.py` 与 `git diff --check`：通过。没有调用真实 Provider、Notion、站点或读取真实书籍正文。
- 16 MiB 是单文件读取硬上限；最多三章使单次源文件读取量上界为 48 MiB。超限路径的 CLI 专用提示只描述限制，不回显文件名或异常文本。20,000 字符不是 token 预算；全书预读预算、分批候选抽取和上下文质量评估仍待实现。

### 2026-11-15 知识抽取 Provider 路由对齐

- 修正 `scripts/auto_extract_knowledge.py` 的模型/Provider 不一致：脚本此前以 `Config.PROOFREAD_MODEL` 填充请求模型，却固定使用 DeepSeek URL、Key 和 `deepseek` 数据授权身份。现在通过 `get_primary_provider_route(Config.PROOFREAD_MODEL)` 解析 Provider ID、URL 和该 Provider 专属 Key；模型类别授权预检和实际客户端创建共用此结果。
- 不支持的模型名在读取章节正文前失败。模型别名只决定路由，不启用 Provider，也不改变 `PROVIDER_DATA_POLICY` 默认拒绝；知识抽取仍单独要求实际路由 Provider 的 `source_text` 已获本地 allowlist 放行。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit -q`：17 项通过；`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -q`：28 项通过。
- `.venv\Scripts\python.exe -m py_compile scripts\auto_extract_knowledge.py tests\test_knowledge_extraction_unit.py`：通过。上述验证只使用合成响应，无真实 Provider、Notion、站点或书籍正文调用。
- 路由增量后的整组回归 285 项运行、281 项通过、4 项 Windows 能力跳过；仓库 mock E2E 4 项通过（281.415 秒）；对应命令和边界见本文顶部当前工作区定向验证。全书 token/context 预算和分批抽取不在此增量内。

### 历史检查：Kakuyomu 官方作者 ZIP/TXT 备选路径

- 查阅 Kakuyomu 官方[备份帮助](https://kakuyomu.jp/help/entry/download_works)与[功能公告](https://kakuyomu.jp/info/entry/2018/11/14/162115)：作者可通过浏览器工作区将自作小说下载为 ZIP，示例包含 `about.txt` 与逐话 UTF-8 文本；仅限自作小说，不支持 App，且平台没有将下载数据重新导入的功能。
- 现有 `LocalFileAdapter`/`scripts/ingest_local_sources.py` 根据显式 catalog 路径读取普通文件，不限制 `.txt` 后缀。新增 `test_cli_archives_explicit_utf8_txt_source_byte_for_byte`，以合成日文文本验证 `.txt` 原文件不被修改、归档 raw artifact 与输入字节完全一致，CLI 不回显正文。
- 该合成测试不读取真实作品、不处理 ZIP，也不验证官方 ZIP 的实际成员/章节标题。作者 ZIP 不是当前普通读者输入路径，用户无需提供；当前 URL adapter 与真实单话导入证据见上方 I2 记录。作品授权已由用户明确确认，平台自动化访问规则仍独立适用。
- 验证命令：`.venv\Scripts\python.exe -m unittest tests.test_local_source_ingestion_cli -v`。

### 2026-11-15 阶段 2 概要审核与运行时来源核验

- 新增 `story_summary_review.py` 和 `scripts/apply_story_summary_review.py`。模板模式读取 `STORY_SUMMARY_draft.md` 与 `KNOWLEDGE_PROVENANCE_draft.json`，校验结构后排他新建包含 `pending` 决定的模板，并绑定两份候选的原始字节 SHA-256；模板创建不读章节正文、不读 manifest、不调用 Provider。
- 发布模式要求回执字段完整、候选哈希匹配、决定为 `approved`、理由非空，并且 `summary_source_chapters` 顺序与 provenance 来源一致。最多 3 个来源（与当前抽取器所选章节数相同），每个来源最多 16 MiB；每个都须具有 `source_version_id`，指向 manifest 中最新的 `normalized_source`，并同时校验 manifest 原始字节哈希和文本读取哈希。单次来源验证最多读取 48 MiB。发布 bundle 排他新建，不覆盖既有文件。
- `TranslationPipeline` 在读取项目信息和构造 RAG 前识别 `.json` 概要路径并加载审核 bundle；校验 schema/状态、摘要内容哈希、来源证明摘要、review 记录和 manifest 当前来源版本。旧 Markdown 手工概要路径保持兼容，但没有该审核/来源新鲜度证明；固定名 `STORY_SUMMARY_draft.md` 仍在初始化早期直接拒绝。bundle 内嵌哈希和本地回执均未签名，无法认证 reviewer、证明实际审核或知识语义正确。
- 使用命令：`.venv\Scripts\python.exe scripts\apply_story_summary_review.py --knowledge-root <Knowledge目录> --create-template summary_review.json`；审核后运行 `.venv\Scripts\python.exe scripts\apply_story_summary_review.py --knowledge-root <Knowledge目录> --source-root <原文数据根目录> --manifest source_manifest.json --review summary_review.json --output STORY_SUMMARY_reviewed.json`，并将 `STORY_SUMMARY_PATH` 指向该 JSON bundle。
- `.venv\Scripts\python.exe -m unittest tests.test_story_summary_review tests.test_pipeline_contracts -q`：82 项通过。完整相关回归（14 模块：来源 manifest/ingestion/materialization/linkage、知识/TM 溯源与审核、安全、pipeline、对齐及抽取/RAG）运行 265 项、261 项通过、4 项跳过、0 项失败；3 项符号链接 fixture 因 Windows `WinError 1314` 跳过，1 项 FIFO fixture 因 Windows 不支持 `os.mkfifo` 跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，236.142 秒，退出码 0。它验证普通生产流水线的 mock 路径，不单独触发 reviewed JSON 概要分支；该分支由上述概要审核与 pipeline 单测覆盖。输出中的内容拦截、schema 和段落错配失败堆栈属于预期负向 fixture；最终 unittest 汇总为 `OK`，没有调用真实 Provider。
- 涉及 Python 文件 `py_compile`、概要 CLI `--help` 与 `git diff --check` 通过。验证使用合成章节与本地 mock；未调用真实 Provider、Notion 或站点，未读取真实书籍正文。该增量不实现 AI 审核服务、reviewer 身份认证、人物/TM 审核、风险升级、更正/废弃或 Markdown 兼容路径治理。

### 2026-11-15 TM 审核回执与显式检索快照

- 新增 `tm_review.py` 和 `scripts/apply_tm_review.py`。`--create-template` 按显式 `--chapter` 列表或全部 TM 章节生成 `pending` 回执，绑定完整 TM 字节 SHA-256、manifest 字节 SHA-256 和逐原译对哈希。所选章节必须能通过当前 `validate_tm_provenance` 审计，含当前 manifest `source_version_id`、新鲜的源/译文件与哈希、完整 `matched` 段落映射；pair embedding 必须是有限数值，所选条目维度一致。
- 发布时要求回执逐对覆盖候选且每项均为 `approved`、`rejected` 或 `escalated`，并填写理由、UTC 时间和 reviewer 声明字段。发布重新核验 TM、回执、manifest 和源/译文件；只保留明确批准的 pair 和对应 `matched` 映射，重排 pair 索引，输出在 TM 所在目录排他新建。无批准项、过期来源、候选变化、待定/重复/缺漏决定或同名输出均拒绝。
- `.env`/配置可选设置 `TM_REVIEWED_PATH`。翻译流水线将它与译文根目录传入 `RAGEngine`；显式启用时初始化加载快照并对当前 manifest、原文和译文重做来源核验，TM 查询只使用快照。完整 `TM_PATH` 仍为运行时写入目标，批准快照不自动同步更新；未设置 `TM_REVIEWED_PATH` 时仍按旧行为检索完整可写 TM。该功能是 opt-in 局部门禁，不表示旧 TM 获得追溯批准，也不自动强制所有项目启用。
- 命令示例：`.venv\Scripts\python.exe scripts\apply_tm_review.py --tm <Knowledge\translation_memory.json> --source-root <原文数据根目录> --translation-root <译文数据根目录> --manifest source_manifest.json --chapter 第1話.md --create-template tm_review.json`；编辑回执后运行 `.venv\Scripts\python.exe scripts\apply_tm_review.py --tm <Knowledge\translation_memory.json> --source-root <原文数据根目录> --translation-root <译文数据根目录> --manifest source_manifest.json --review tm_review.json --output translation_memory_reviewed.json`，并显式配置 `TM_REVIEWED_PATH` 指向快照。
- `.venv\Scripts\python.exe -m unittest tests.test_tm_review tests.test_rag_engine_unit tests.test_pipeline_contracts -q`：94 项通过。覆盖 pending/哈希绑定、approved-only pair 过滤与映射重排、陈旧候选拒绝、运行时来源更改拒绝、显式 RAG 快照使用、pipeline 路径注入、测试路径注入，以及 JSON 配置与环境变量优先级。该优先级测试发现并修复 `TM_REVIEWED_PATH` 曾被后续 JSON 属性赋值覆盖的问题。
- `.venv\Scripts\python.exe -m unittest tests.test_source_manifest tests.test_source_ingestion tests.test_local_source_ingestion_cli tests.test_source_markdown_materialization tests.test_source_pipeline_linkage tests.test_knowledge_provenance_audit tests.test_knowledge_review tests.test_story_summary_review tests.test_tm_review tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit tests.test_rag_engine_unit -q`：15 个相关模块运行 270 项，266 项通过、4 项跳过、0 项失败；跳过原因为 3 项 Windows 符号链接创建限制和 1 项 Windows 不支持 FIFO。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 项本地 mock E2E 通过，204.831 秒，退出码 0。负向 fixture 的内容拦截和响应契约堆栈是预期日志；此 runner 未直接加载 reviewed TM 快照，快照路径由上述合成单测覆盖。没有调用真实 Provider、Notion 或站点，也没有读取真实书籍正文。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py tm_review.py scripts\apply_tm_review.py tests\test_tm_review.py tests\test_pipeline_contracts.py`、`.venv\Scripts\python.exe scripts\apply_tm_review.py --help` 和 `git diff --check`：通过。
- reviewer/provider/model/review ID 是操作者填写的声明；回执和 bundle 均未签名，哈希只检查输入一致性，不认证身份或证明 AI 审核真实发生。工具不调用审核 AI，不实现风险分层、escalated 后续状态流、更正/废弃、质量评估或审核历史；快照发布后不会随完整 TM 自动更新。未配置 `TM_REVIEWED_PATH` 时不存在运行时审核门禁。测试使用合成章节，不验证真实作品映射、Provider 或译文质量。

### 2026-11-15 I5 EPUB 离线候选构建

- 新增 `epub_builder.py` 与 `scripts/build_epub_candidate.py`。工具消费严格 schema v1 的显式有序章节 catalog；每话路径须在输入根目录内、位置严格递增，Markdown 首个非空行须与 catalog 标题相同的 H1。每话 `source_version_id` 必须对应相同 work/episode 的最新 `normalized_source` artifact，且文件哈希须匹配 source manifest；sidecar 记录 manifest 相对路径及 SHA-256。
- Pandoc 精确版本必须匹配 catalog 的 `expected_pandoc_version`。本机 `Get-Command pandoc` 解析到 `C:\Program Files\Pandoc\pandoc.exe`，`pandoc --version` 返回 `3.9.0.2`；安装来源没有核实，Pandoc 不是仓库依赖。当前 PATH 没有解析到 `epubcheck`。
- CLI 要求显式设置单章、总输入、输出 byte 上限，最大值为 1 GiB，超时最大 24 小时；catalog 限制 1 MiB。工具拒绝图片标记，暂不支持插图、字体和 CSS；源 Markdown 保持原字节不变。新建输出目录包含 `candidate.epub` 与 `build.json`，已存在的同名 build 不覆盖。
- 每个构建始终记录 `artifact_status: candidate`、`quality_gate_status: not_evaluated`、`coverage_scope: explicit_episode_selection`。内置检查覆盖 ZIP CRC、首位未压缩 `mimetype`、container、OPF manifest/spine 和引用 XHTML 的 XML 可解析性；不是完整 EPUBCheck，亦不证明章节选集覆盖全书、译文质量或阅读器兼容。
- `.venv\Scripts\python.exe -m unittest tests.test_epub_builder -v`：11 项通过。测试实际调用本机 Pandoc，用合成章节核对文本顺序、来源版本/manifest 哈希和 Markdown 不变，并覆盖 CLI 成功输出不回显正文、版本过期/身份错配/文件篡改、标题/清单错配、重复 JSON 字段、图片拒绝、输出超限及禁止覆盖。
- `.venv\Scripts\python.exe -m py_compile epub_builder.py scripts\build_epub_candidate.py tests\test_epub_builder.py`：通过；`.venv\Scripts\python.exe scripts\build_epub_candidate.py --help`：通过。测试未触发作品文件、外部 Provider、EPUBCheck 或阅读器。

## 验证要求

- 修改后运行受影响的单元测试；改动 API/流水线时再运行 mock E2E。
- 实际 Provider/部署验收必须另行使用批准的测试项目和凭据，记录模型、端点类型、日期、输入类别、结果和失败，不记录密钥或不必要的原文。
- 测试失败必须区分代码缺陷、环境/依赖、mock 限制与外部服务问题；不得用“测试就绪”代替通过证据。
