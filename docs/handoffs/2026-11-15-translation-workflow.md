# 翻译工作流续接交接

## 2026-11-20 K4 AI workflow CLI 验证续接

- 当前基线仍为分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；工作树已有混合未提交改动，本轮只新增 `tests/test_ai_translation_workflow_cli.py` 和同步验证文档，未暂存、提交、重置或清理。未读取受保护 freshness JSON、试点正文、本机 API profile 或凭据。
- 新增 3 项 CLI 测试，验证配置加载、终审/返工静态预检、参数转发和 JSON 成功输出；预检拒绝时确保工作流不启动且错误详情不泄漏。另新增 CLI 到真实工作流编排函数的合成集成测试，完成双评估失败、finding 定向返工、复审通过及正式发布。CLI/I4/集成定向回归 40 项通过；完整非 E2E 动态发现 764 项运行、760 项通过、4 项 Windows symlink/FIFO 能力跳过。
- `.venv\Scripts\python.exe tests\run_tests.py`：本轮 loopback mock E2E 7 项通过（212.461 秒，退出码 0）。content-filter 与段落数错配 trace 来自预期负向夹具。未调用真实 Provider、未验收翻译质量、未部署。
- 继续点仍是 K5 人审：由有权限的人完成当前 88 话映射与双版本决定并生成绑定计划摘要的回执，再审核 bundle 绑定的全书知识；之后由凭据所有者核验端点授权/路由/预算，执行获准单话试译及人工质量验收。K4 仍是单话显式 CLI，不会自动批量调用或发布。
- 定向复验命令：`.venv\Scripts\python.exe -m unittest tests.test_ai_translation_workflow_cli tests.test_source_pipeline_linkage tests.test_tm_provenance_unit tests.test_downstream_freshness_snapshot tests.test_translation_review.TranslationReviewTests.test_workflow_cli_runs_review_rework_and_publication_end_to_end -q`。全量非 E2E PowerShell 命令：

```powershell
$modules = Get-ChildItem -LiteralPath tests -Filter 'test_*.py' -File |
  Where-Object { $_.Name -ne 'test_e2e.py' } |
  ForEach-Object { 'tests.' + $_.BaseName }
.\.venv\Scripts\python.exe -m unittest -q @modules
```

mock E2E 使用仓库 runner。当前应用仍为 CLI，无部署地址。

## 2026-11-20 I4 TM 版本审计续接

- 基线仍为 `codex/translation-workflow-audit-20261117` / `9374fa79376c13f72f06f1e7764d732012b1436a`。新增规则：配置 manifest 的 TM 审计若缺少 `source_version_id` 返回 `unverified`；无 manifest 的 hash-only 兼容路径不变；审计只追加快照，不写回 TM/译文。
- 验证：TM provenance/freshness 36 项、Kakuyomu 编排/采集/source ingestion 93 项、完整非 E2E 760 项（756 通过、4 项 Windows 能力跳过）、mock E2E 7 项（206.248 秒，退出码 0）。未调用真实 Provider或运行试点正文。
- I4 消费者 stale 写回与自动重建仍未实现；后续如继续该项，应先定义不可变 consumer/status 记录如何被入口读取及过期状态如何解除，避免与内容版本/审核回执形成双重权威。K5 仍需有权限的人完成计划映射/双版本决定及回执，再进行 reviewed 全书知识和获准单话试点。细节见[开发记录](../development.md#2026-11-20-i4-manifest-bound-tm-lineage)。

## 2026-11-20 当前工作树回归复核

- 基线仍为分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；工作树包含混合未提交实现/文档修改。本次只运行验证并追加文档，未暂存、提交、重置或清理。
- 验证结果：四模块定向回归 269 项通过；动态发现并排除 runner 专用 `test_e2e.py` 后，758 项运行、754 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py` 本地 mock E2E 7 项通过（208.149 秒，退出码 0）。E2E 的 content-filter/段落错配错误为预期负向 fixture。未调用真实 Provider、未运行试点正文。
- K5 状态没有变化：计划 88/88 来源有效，但 mapping/AI edition/human edition 三类人审各 88 项仍 pending；计划回执与 reviewed 全书概要仍缺失。下一步由有权限的人完成审阅并生成匹配回执，再审核 bundle 绑定知识；之后由凭据所有者核验 Provider 配置/授权/预算，执行获准首话并人工验收质量。
- 续接前先检查 `git status --short --branch`；保留混合工作树。不得读取受保护 freshness JSON、API profile/凭据或不必要的书籍正文；不得提交、重置或清理。应用仍为本地 CLI，无部署地址。完整验证命令见[开发与验证](../development.md#2026-11-20-当前工作树回归复核)。

## 2026-11-20 K5 试点门禁复核续接

- 基线：分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。当前工作树已有混合代码/文档修改；本次只读检查并更新文档，未暂存、提交、重置或清理。受保护 freshness JSON、本机 API profile/凭据及书籍正文未读取或修改。
- 当前计划 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.json` 为 `ready_for_review`，88/88 来源有效、0 issue，摘要 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。该计划绑定 `source_catalog.raw-html-2026-11-17.json`；不得用不同摘要的 `source_catalog.discovered.json` 替代。一次错误 catalog 的 plan-only 诊断返回 88 个 `stale_ai_edition_catalog`，换回计划绑定的 catalog 后为 88/88 verified、0 issue/冲突。
- 使用正确 catalog 的 `scripts/run_kakuyomu_workflow.py --plan-only` 只读返回相同摘要、0 网络请求/Provider 调用/文件写入，且 `source_text_included=false`。`scripts/validate_source_editions.py` 返回 88 话 `verified`，AI/人读重算输出为 774,253/799,293 bytes。以上不证明语义质量。
- 人审模板的计划摘要与 AI/人读索引绑定均匹配；`mapping_decision`、`ai_edition_decision`、`human_edition_decision` 各 88 项仍 `pending`。`Workflow/Approvals/` 与 `Knowledge/STORY_SUMMARY_reviewed.json` 不存在；没有生成审批、知识或译文。完整证据见[开发与验证](../development.md#2026-11-20-k5-试点门禁复核)。
- 下一步由有权限的人审阅 88 话映射和双版本，完成模板并通过 `scripts/approve_translation_plan.py` 生成与当前计划匹配的回执；再审核当前 AI bundle 绑定的全书概要/术语。之后由凭据所有者安全核验 Provider 端点、授权、路由和预算，再显式执行获准单话工作流并人工验收候选、审核结论与发布产物。用户已确认作品授权和职责所需数据类别，不要重复请求该确认。
- 不运行真实 Provider、不创建计划回执/知识/译文，不读取 API profile/凭据或 freshness JSON。当前应用是 CLI，没有服务地址；此前 K4 全量非 E2E/mock E2E 结果记录在下方，未在本次文档续接中重跑。

## 2026-11-20 K4 自动返工续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树有既有知识/RAG、embedding/API pool、K4 及文档混合改动，均保留；受保护 freshness JSON、项目原文、本机 API profile/凭据未读取，未暂存、提交、重置或清理。
- 当前状态：`scripts/run_ai_translation_workflow.py` 显式运行/恢复一话有限审核、自动定向返工、复审与通过后发布。调用 `FINAL_REVIEW_MODEL` 做双次审核，`PROOFREAD_MODEL` 只修改 blocking findings 指定的段落，二者路由静态要求 endpoint/model 不同。没有接到翻译 pipeline 自动触发。
- 并发边界：单话 reviewer、rework 与完整 workflow 共用 run 内 `AIWorkflowLocks/<sha256(episode_id)>.lock` 异步锁，同事件循环及跨进程重复调用都串行化并复用已存决策/报告/候选；进程终止后系统锁可重新获取，decision append lock 仍独立保护链式写入。若在报告或候选持久化前进程退出，重试仍可能重新调用 Provider 并产生费用。
- 数据契约：终审和修订均发送完整原文及译文，单次各自默认合计不超过 64,000 字符；返工额外发送 blocking findings 和策略定义，不发送 book knowledge，类别为 `source_text`/`translation_text`。候选写入 run 的 `ReviewCandidates/<episode_id>/revision-NNNN.md`，摘要 sidecar 在 `AIReworks/<episode_id>/revision-NNNN.json`。候选和报告 create-only；重跑先核验并恢复已持久化候选。
- 人工边界：初始预算默认 2。`rework_limit_reached` 必须先用 `scripts/resolve_translation_review.py --action increase_budget` 增加预算；`approve_current` 仍需绑定候选的人工八项 checklist，不会由 AI 工作流代替。格式/哈希测试不证明模型真正修复语义问题；`none/low` 仍为定性收敛代理，reviewer 未认证。
- 本轮验证：10 项新增自动返工、恢复与并发集成测试通过；合并终审/状态/Provider/API-pool 定向回归 264 项通过；API pool 单测 23 项通过；完整非 E2E 753 项运行、749 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（213.512 秒）；CLI help/编译通过。未调用真实 Provider，无部署服务。
- 下一步：本地合成验证已完成。真实试点前仍需人工完成 88 话映射/双版审批及计划回执、reviewed 全书知识；之后由凭据所有者检查当前 profile、端点、授权、预算和模型路由，再显式运行单话工作流并人工验收质量与发布产物。
- 初次启动命令：`.\.venv\Scripts\python.exe scripts\run_ai_translation_workflow.py --project <项目目录名> --run-directory <Workflow\Runs\run_id> --episode-id <话目ID> --review-policy-file <review-policy.json> --max-rework-attempts 2`。同一预算下可重跑续接；增加预算后，续接时省略 `--max-rework-attempts` 以读取决策链预算，或传入预算回执 `new_max_rework_attempts` 的值。无 Web 服务/部署地址。

## 2026-11-20 K4 AI 终审执行器续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树包含本轮之前的 API/embedding、知识/RAG、K4 与文档未提交/未跟踪变更；本轮仅增量修改，未暂存、提交、重置或清理。受保护 freshness JSON、试点正文、本机 API profile/凭据均未读取或改写。
- 历史阶段快照：当时只实现 K4 双次终审，`scripts/review_translation_candidate.py` 的失败返回 `rework`/`needs_human`，还没有自动候选生成；当前自动续接状态见本文件顶部。
- 涉及核心文件：`ai_translation_review.py`、`translation_review_state.py`、`translation_review.py`、`scripts/review_translation_candidate.py`、`tests/test_translation_review.py`、`tests/test_translation_review_state.py`；状态/路线图/架构/决策/模型方案/README 同步更新。审阅结果绑定 policy/source/candidate/route 摘要；schema v4 只追加 run 内记录，旧决定和候选不改写。
- 验证：`.venv\\Scripts\\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state -q`：91 项通过；完整非 E2E 740 项运行、736 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\\Scripts\\python.exe tests\\run_tests.py`：mock E2E 7 项通过，212.673 秒，退出码 0；相关 `py_compile`、CLI `--help`、本地文档链接目标、`git diff --check` 通过。mock 使用合成数据/loopback，没有真实 Provider、Kakuyomu、试点正文或部署验证。
- 必须保留的风险：两次评估走同一 reviewer route；none/low 只是模型自报的定性收敛代理；八项检查也是模型输出，不证明语义质量；reviewer 未认证。完整 source/candidate 会发送到 reviewer，不能直接在未检查授权和端点状态时对真实项目 run 调用。
- 下一步：先定义自动返工候选生成契约（候选路径 create-only、模型输入/输出、提示词/策略来源、失败和重复执行、预算耗尽展示/人工恢复），再实现修订 Agent 并用合成故障测试；不要将模型 finding code 升格为默认 taxonomy。正式试点还需人工完成 88 话双版/计划审批、reviewed 全书知识，再由操作者安全核对本机配置并显式进行真实单话 Provider/质量验收。
- 试运行入口（仅在上述门槛完成后）：`.\.venv\\Scripts\\python.exe scripts\\review_translation_candidate.py --project <项目目录名> --run-directory <Workflow\\Runs\\run_id> --episode-id <话目ID> --review-policy-file <策略JSON> --max-rework-attempts 2`。返工续审另加 `--candidate-file ReviewCandidates/<episode_id>/revision-0001.md` 并沿用链上预算。当前无 Web 服务/部署地址。

## 2026-11-20 K4 决策 CLI 输入校验续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。保留工作树既有混合修改和未跟踪文件；未读取受保护 freshness JSON、试点正文、本机 API profile 或凭据；未暂存、提交、重置或清理。
- 已实现：`scripts/record_translation_review_decision.py` 对 `--stage-verdicts` 与 `--stage-issue-codes` 使用严格 JSON 解码，拒绝任意层级重复字段以及 `NaN`/`Infinity`，保证在调用决策写入器前不接受有歧义输入。新增测试覆盖重复 verdict 字段、重复 issue-code 字段和非有限值。
- 验证：定向审核模块 81 项通过；完整非 E2E 727 项运行、723 项通过、4 项因 Windows symlink/FIFO 能力跳过、0 失败；mock E2E 7 项通过（209.005 秒，runner 退出码 0）；相关文件 `py_compile` 通过。
- 文档同步：README、开发记录、路线图、项目现状与端到端目标均记载严格解析行为和当前验证计数；6 份活动 Markdown 的 218 个本地链接目标均存在，`git diff --check` 通过，工作树既有修改和受保护未跟踪文件保持不变。
- 下一步：自动 AI reviewer 仍需要有来源和版本的质量 taxonomy、冲突/不确定处置及跨话目作用范围；不能从操作者自定义 issue code 推导这些规则。试点仍需人工完成 88 话映射/双版验收、计划审批和 reviewed 全书知识；真实 Provider、生产终审与产物验收未完成。

## 2026-11-20 K4 策略文件绑定续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树已有 API/embedding、K4 和受保护文件的混合修改，全部保留；未读取受保护 freshness JSON、试点正文、本机 API profile 或凭据；未暂存、提交、重置或清理。
- 已实现：`translation_review_state.py` 接受可选策略 schema v1（`policy_id`、正整数 `revision`、code/阶段/定义列表）。`--review-policy-file` 让 CLI 按原始文件字节计算摘要并将文件 create-only 保存为 `ReviewPolicies/<sha256>.json`；新记录为 schema v3，摘要、路径与 `issue_codes_by_stage` 均绑定。读链、续接、发布会重新校验登记表摘要和 code 阶段归属。schema v1/v2 读取兼容；既有 v2 链可以进入 v3，但必须由同一策略登记表覆盖已有 codes。进入 v3 后续写必须继续提供匹配策略文件。
- 兼容边界：不提供策略文件时仍生成 schema v2，既有 `policy_sha256` 继续是 opaque digest、不验证语义。登记表没有预置业务质量标准，不包含严重度或自动处置，不实现跨话目豁免。策略文件为操作者自定义输入，不构成项目统一 taxonomy 或身份认证。
- 验证：定向 `.venv\\Scripts\\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：80 项通过。全量非 E2E 动态发现运行 726 项、722 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\\Scripts\\python.exe tests\\run_tests.py` mock E2E 7 项通过、205.893 秒、退出码 0。相关 Python `py_compile`、CLI `--help` 策略选项、6 份修改文档本地链接和 `git diff --check` 通过。负向 fixture 的 content filter/paragraph mismatch 日志为预期；没有真实 Provider 请求。
- 涉及文件：`translation_review_state.py`、`translation_review.py`、`scripts/record_translation_review_decision.py`、`tests/test_translation_review_state.py`、`tests/test_translation_review.py`，及本交接对应的开发/路线图/状态/目标/决策文档。
- 下一步：完成全量非 E2E 与仓库 mock E2E，核对其余相关发布/状态链回归；更新本记录实际结果。之后继续 K4 的已授权工作：在不臆造业务标准的前提下，等待/使用人类确认的 taxonomy 与跨话目作用范围，再接独立 reviewer。总体工作流仍未完成：88 话映射/双版与 reviewed 知识验收、AI reviewer/终审质量与身份、受控真实 Provider 试译、真实产物验收均未关闭。

## 2026-11-20 K4 结构化审核记录续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。保留本工作树全部既有修改和未跟踪文件；未读受保护 freshness JSON、试点正文、本机 API profile 或密钥；未暂存、提交、重置或清理。
- 已实现：`translation_review_state.py` 新写 schema v2 决策，按 stage 存 reviewer 显式提供的 `issue_codes_by_stage` 并纳入 `decision_sha256`；旧 v1 继续可读，v1 决策链可由 v2 候选续接。fail 阶段缺少 code、code 格式错误/重复、pass 阶段含 code 时拒绝。`scripts/record_translation_review_decision.py` 接受可选 `--stage-issue-codes <JSON>`；fail 时必须提供。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：72 项通过；全量非 E2E 718 项运行、714 项通过、4 项 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py`：mock E2E 7 项通过，227.490 秒、退出码 0。相关 `py_compile`、CLI `--help`、`git diff --check` 通过。真实 Provider、API 池配置、reviewer 身份与语义质量均未验证。
- 关键边界：issue code 只是与 `policy_sha256` 并存的受格式约束标识。当前不读取/校验策略文件或共享 taxonomy，不推断其业务含义，不基于重复 code 跨话目跳过返工/人工暂停；API 池 schema 与授权未变更。
- 最终核验：7 份当前/交接文档扫描 250 个本地链接目标，缺失 0；新开发记录标题锚点存在；`git diff --check` 通过。没有触碰 API 池 schema/授权或受保护试点文件，也未启动服务。
- 下一步：定义有版本、来源和作用范围的共享 issue taxonomy；跨话目例外必须另有显式策略和测试，不能从当前 `approve_current` 或重复 code 推导。之后实现 AI reviewer 与收敛/质量策略，并完成 88 话人工验收、reviewed 知识审批及操作者确认后的受控 Provider 试译。

## 2026-11-20 K4 仲裁与完整回归续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。工作树含既有 API/embedding 实施及本次 K4 实施的未提交修改，全部保留；未读取受保护 freshness JSON、试点正文、本机 API profile 或凭据；未暂存、提交、重置或清理。
- K4 新增：决策链默认最多返工 2 次，可通过 `--max-rework-attempts` 配置；`scripts/resolve_translation_review.py` 支持 `approve_current` 人工放行当前候选和 `increase_budget` 严格增量续跑。仲裁事件在 `ReviewResolutions/<episode_id>/` create-only 保存，绑定当前 run/source/candidate/失败阶段/decision 摘要及理由；人工放行不改写失败 verdict，只能生成 schema v3 checklist，仍须八项检查全部通过才能发布。预算扩展可续接到新候选修订，历史候选与决定不改写。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q` 64 项通过；完整非 E2E 动态发现 710 项运行、706 项通过、4 项因 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py` mock E2E 7 项通过，244.256 秒、退出码 0。相关 `py_compile`、CLI `--help`、`git diff --check` 通过。E2E 负例堆栈为预期内容过滤/格式 fixture，没有真实 Provider 请求。
- 未完成边界：自动 AI reviewer、终审 Provider/model、语义阈值和“连续两次无明显收益”的自适应规则仍未实现/验证。当前只有 fidelity/fluency/style 三类 verdict，跨话目“同类问题不重复暂停”尚无细粒度 issue taxonomy，不扩散一次人工放行。reviewer 身份仍是本地声明、不受认证。试点 88 话映射/双版本审批、reviewed 全书知识、真实 API profile/TM 操作及首话真实 Provider 试译未完成。
- 继续点：先为可审计的细粒度 issue taxonomy 与跨话目豁免范围建立测试契约，再实现 AI reviewer 与策略；之后核验 88 话计划模板、人工映射/清洗审批及 reviewed 知识，操作者安全确认 API pool/profile 和数据授权后才开展受控首话试译。TM 重建仍建议使用 `.\.venv\Scripts\python.exe scripts\configure_api_pool.py --rebuild-tm-embeddings -- --project <项目> [--chapter <TM键>]`，人工审核候选后再切换 `TM_REVIEWED_PATH`。当前无可部署服务或 Web 地址。

## 2026-11-20 API 池 v2 与 embedding Provider 续接

- 当前基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`；本轮修改仍未提交。保留所有既有工作树修改；未读取受保护 freshness JSON、试点正文、本机 API profile 或任何 Key；未暂存、提交、重置或清理。
- 已实现：`api_pool_store.py` 生成 schema v2，支持可选独立 Gemini/OpenAI-compatible embedding 配置、Credential Manager 凭据引用和 profile 摘要绑定。v1 可继续加载；`scripts/configure_api_pool.py` 仅在操作者确认后做 v1 备份及原子迁移，旧 credential refs 不删除。迁移失败保留 v1 profile；孤儿新 refs 仅在异常返回路径尽力清理，进程硬中断仍可能留下不被引用的 Credential Manager 项。
- 已实现：统一 `embedding_provider.py` 为 Gemini/OpenAI-compatible embedding 发送调用；校验来源授权、超时、响应数量/顺序/有限向量/维度。Gemini 默认向量身份保持 schema 1；OpenAI-compatible schema 2 增加 endpoint SHA-256，阻止同维度的不同模型/provider/端点混用。RAG、TM 写入、章节对齐调用同一适配器；旧向量保留但不自动重建。
- 已实现：`scripts/rebuild_tm_embeddings.py` 通过现有逐对 TM 审核流程生成来源绑定候选并接受人工回执，不改写源 TM 或旧 reviewed snapshot。API 池向导增加 `--rebuild-tm-embeddings` 模式；Provider 失败、来源漂移或输出冲突时不创建候选。仍未在本机 TM 上执行。
- 验证：定向 235 项通过；完整非 E2E 704 项运行、700 项通过、4 项 Windows symlink/FIFO 能力跳过；本地 mock E2E 7 项通过、239.655 秒、退出码 0；`py_compile` 与 `git diff --check` 通过。迁移和候选重建使用合成 profile/TM/凭据；OpenAI SDK 对本机 loopback `/v1/embeddings` fixture 验证请求和解析，不代表真实服务兼容。详细证据见[开发与验证](../development.md#2026-11-20-api-池-v2-与可配置-embedding)。
- 尚未完成：本机 profile 版本和迁移状态未知；真实 endpoint/model/账单/语义质量未验证；本机 TM 候选未生成、人工审批未完成、`TM_REVIEWED_PATH` 未切换；真实试点仍待 88 话计划/双版本人工审阅、审批回执及 reviewed 全书知识。K4 人工仲裁/预算续接现已实现合成版本；AI reviewer、终审 Provider/model、语义阈值及跨话目同类失败策略仍未实现或验证。项目是本地 CLI，没有部署目标或 Web 地址。
- 下一步：由操作者在 `source_text` 授权明确后运行 `.\.venv\Scripts\python.exe scripts\configure_api_pool.py --rebuild-tm-embeddings -- --project <项目> [--chapter <TM键>]`；确认是否加载/迁移本机 profile。使用独立候选文件，通过 `scripts/apply_tm_review.py` 创建并完成逐对人工回执，再发布 reviewed snapshot；核验后才显式将 `TM_REVIEWED_PATH` 指向新快照，保留旧 TM/快照以便回退。之后才在获准条件下做真实小样本诊断。人工审批和 K4 决策不可由 mock 测试替代。

## 2026-11-20 Gemini embedding 续接

- 当前断点：RAG 与章节对齐已共用 Gemini embedding 适配器，TM 新向量保存明确身份；检索忽略没有身份或不匹配的旧向量，但现存旧向量尚未重建。HEAD 仍为 `9374fa79376c13f72f06f1e7764d732012b1436a`，新增实现和相关文档均未提交。
- 实现位置：`embedding_provider.py` 负责 Provider 请求、授权、超时、批量响应校验和身份 schema；`rag_engine.py` 的 TM 查询、章节语义回退和 TM 写入按身份过滤/登记；`scripts/align_chapters.py` 复用相同适配器并记录身份。身份为 schema 1、provider `gemini`、protocol `google-genai`、model `gemini-embedding-2`、task type `default` 和向量维度。
- 验证：RAG/对齐/TM 审核定向 64 项通过；完整非 E2E 682 项运行、678 通过、4 项因普通 Windows symlink/FIFO 能力跳过；loopback mock E2E 7 项通过，235.372 秒，退出码 0。未调用真实 Provider、网络服务、部署或读取项目原文；详细命令和边界见[开发与验证](../development.md#2026-11-20-gemini-embedding-与-tm-向量身份)。
- 恢复与风险：TM 更新 embedding 失败不会部分写入；章节事务日志保留，可在相同 run/事务条件下重试。旧向量被保留而非删除；由于身份未知，依赖旧向量的 reviewed TM 当前可能无检索命中。对齐器只会在操作者显式运行并通过来源校验后重建对应映射，不应自动批量触碰试点 TM。
- 指南语义回退的既有降级仍在：embedding 失败或没有身份兼容向量时，改按章节距离选最近指导。这不是语义命中，也没有变成硬错误；后续应明确是否继续允许及如何向 run 报告降级。
- 下一步：先设计 API 池 v1 到新版本的原子迁移和凭据恢复，再把独立 Gemini/OpenAI-compatible embedding 配置接入适配器，固定 endpoint/model revision/参数身份契约；随后增加显式旧 TM 重建、摘要核验和切换步骤。最后才能进行合成端点兼容性与由操作者显式触发的获准样本验收。
- 其他未完成条件保持不变：88 话人工映射与双版本验收、匹配计划审批回执、reviewed 全书知识、K4 终审/返工/仲裁政策、真实 Provider 单话试译均未完成。当前项目交付仍为本地 CLI，没有可部署 Web 服务。

## 2026-11-20 API 池配置续接（R4 前快照）

- 当前断点：阶段 0–3 已有分散的局部实现，但整条工作流仍未通过阶段验收；阶段 4–5 及真实试点质量验收仍未完成。当前分支 `codex/translation-workflow-audit-20261117`，HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`，修改均未提交。
- 现有 API 池是当前工作树上的 OpenAI-compatible 生成端点入口：初译绑定 `INITIAL_MODEL`；上下文标注、校对、知识抽取绑定 `PROOFREAD_MODEL`；润色绑定 `STYLE_MODEL`。主/备用只在 UnifiedAgent 生成调用中有限回退，知识抽取不使用备用。Key 可临时进入进程环境，或由当前 Windows 用户 Credential Manager 保存；不支持独立审核 Agent、embedding Provider 配置或真实服务诊断。
- 本轮边界修订：职责文字与实际调用一致；只向实际分配的主/备用端点索取 Key，未使用端点不取 Key；激活新池时移除陈旧 `TRANSLATORAI_POOL_KEY_*` 环境变量；配置写入失败时只回滚本次已创建的新凭据，保留旧 profile/凭据；测试验证 `Config.load_config` 和启动预检使用对应模型 alias。相关入口、实现和测试见[向导](../../scripts/configure_api_pool.py)、[API 池](../../api_pool.py)、[存储](../../api_pool_store.py)、[凭据适配器](../../windows_credentials.py)、[测试](../../tests/test_api_pool.py)。
- 验证：`tests.test_api_pool` 11 项通过；`tests.test_api_pool tests.test_pipeline_contracts tests.test_kakuyomu_workflow -q` 164 项通过；全量非 E2E 677 项运行、673 项通过、4 项 Windows 能力跳过；本地 mock E2E 7 项通过，238.966 秒；`py_compile` 与 `git diff --check` 通过。所有接口测试为合成/本地 mock，没有真实 Provider 请求。
- 当前工作树另有既有未提交和未跟踪文件，必须全部保留；受保护 freshness JSON 未读写。没有暂存、提交、推送、重置或清理。README、开发记录和模型方案的本轮补充只记录当前证据，不将历史测试计数冒充当前结果。
- 不可声称已完成：API 端点适配/质量、API 池 embedding 配置、版本化配置迁移、旧 TM 重建、回滚清理本身失败后的人工恢复、全流程自动终审、真实试译或部署。RAG 与章节对齐的 Gemini 调用和新向量身份已在上方最新续接中统一，但 Gemini 仍单独授权/配置。
- 后续先实施并验证版本化配置迁移/失败回滚，再把 embedding Provider 配置接入共享适配器，扩展身份契约并制定旧 TM 显式重建/核验流程；随后才进行合成服务兼容性测试。真实试点仍须人工批准 88 话计划及相关知识、明确终审/返工/仲裁政策，并由操作者显式选择端点和获准样本。

## 2026-11-19 K5 mock E2E 续接复验

- 当前 checkout：`codex/translation-workflow-audit-20261117` / `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`。保留已有 tracked 与 untracked 修改；未读取或改动受保护的 `downstream_freshness_ai_index_refreshed_2026-11-17.json`，没有提交、重置或清理。
- `.venv\Scripts\python.exe tests\run_tests.py`：本地 mock E2E 7 项通过，337.441 秒，退出码 0。`PIPELINE RUN FAILED` 日志对应内容过滤与段落对齐负向夹具，属于预期行为；真实 Provider 未调用。
- 当前试点仍无计划审批回执、reviewed 全书知识、正式 run 或译文。88 话审阅模板的 264 个决定仍为 `pending`；`needs_human` 没有同 run 仲裁/恢复机制，不能自行增加失败覆盖发布策略。无托管服务可部署。
- 继续点：先由人类完成 88 话映射和 AI/人读版审阅并生成匹配回执；审核全书概要/术语；另需确定终审质量规则、Provider/model、返工上限、仲裁权限和失败恢复政策。获准这些条件后再做受控单话真实试点。

## 2026-11-19 K4 发布门禁续接

- 当前 checkout：`codex/translation-workflow-audit-20261117` / `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`。本任务开始时已存在多处 tracked 修改及未跟踪实现；均予以保留。受保护未跟踪文件 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 未读取或改动；没有提交、重置或清理。
- 当前代码完成了 K4 决策链与发布器的连接。`ReviewDecisions/<episode_id>/` 保存 hash-only create-only 链；初版必须绑定原始 `Drafts/<translation_file>`，返工候选须在 `ReviewCandidates/<episode_id>/`，且决策摘要固定候选相对路径。写下一版前会重验上一候选文件。
- 链尾 `passed` 后生成 schema v2 人工 checklist，绑定候选修订、路径、候选 SHA-256 和决策 SHA-256；八项人工检查仍需全部通过。发布回执 v2 同样绑定候选，run 完成核验比较发布文件与最终候选字节。没有决策链的旧 schema v1 人工审核保留。决策状态失败/需人工、链路篡改、候选变动和不同内容输出冲突均不能发布新文件。`needs_human` 当前硬停止，尚无人类仲裁回执或同 run 恢复入口。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`，47 项通过。全量非 E2E 动态回归 630 项运行、626 通过、4 项因 Windows FIFO/符号链接能力跳过、0 失败（94.331 秒）；`.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 7 项通过（418.613 秒，退出码 0）。`py_compile`、脚本 `--help` 与 `git diff --check` 通过。详细边界见[开发与验证](../development.md#2026-11-19-k4-决策链接入审核发布门禁)。
- 本地试点仍未形成 run 或译文。计划 `translation_plan_review_ai_raw_html_schema2_2026-11-19.json` 的 88 话映射仍需人工确认；其 human review 模板 264 项仍为 pending，尚无审批回执。reviewed 全书概要/术语、终审语义阈值、Provider/model、生产返工上限及人工升级责任未确认；未调用 Provider，也没有可部署的服务端/Web 应用。
- 当前续接重新运行模板验证：计划与人读索引/88 话章节摘要仍匹配，验证因 264 个待审决定拒绝审批；随机临时回执探测路径未创建文件。验证没有显示章节正文或产生书籍数据写入。
- 下一步是人工审阅当前 88 话映射/双版本并完成计划回执和 reviewed 全书知识；生产终审还需明确维度判定政策、Provider/model、返工上限、失败/耗尽后的仲裁权限与恢复流程、预算及人工责任。随后才可在获准渠道上开展受控单话试点。不得把显式 `pass` fixture 或本地 mock 写成真实质量验收。

## 2026-11-19 K4 合成状态转移续接

- 新增 `translation_review_state.py::decide_review_transition`。`fidelity`、`fluency`、`style` 三阶段全部明确通过才标为可发布；失败在调用方显式预算内进入返工，缺失/不确定/冲突或次数耗尽转 `needs_human`。
- `create_review_decision_record` 绑定源/候选版本、父摘要、策略摘要、审核者声明及状态转移；`verify_review_decision_record` 可拒绝字段或转移篡改。摘要不认证真实审核、策略或父记录；决策链已能在 run 内持久化，但尚未成为正式发布门禁。
- `record_translation_review_decision` 已接入 `review_pending` run 的 `ReviewDecisions/<episode_id>/` create-only 链；初版绑定 Drafts，返工候选必须位于 run 内，并要求上一版明确为 `rework`。定向验证 `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：42 项通过；`py_compile`、脚本 `--help` 与 `git diff --check` 通过。没有 Provider；现有发布器仍未强制消费该链。
- 跨模块回归 `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state tests.test_kakuyomu_workflow tests.test_pipeline_contracts -q`：190 项通过；`.venv\Scripts\python.exe tests\run_tests.py`：7 项本地 mock E2E 通过，425.782 秒，退出码 0。E2E 的负向 Provider/格式/TM 夹具为预期日志，未访问真实外部服务。
- 当前完整非 E2E 动态回归运行 620 项，616 项通过、4 项跳过、0 项失败（Windows FIFO 1 项、符号链接 3 项能力限制）；mock E2E 仍为 7 项通过。
- 后续需先取得终审 Provider/model、维度阈值、返工次数与人工升级责任，再将该转移核接入版本化审核与发布流程；在此之前它不能批准或发布译文。

## 2026-11-19 K5 试点计划映射续接

- 当前 checkout 仍为分支 `codex/translation-workflow-audit-20261117`、HEAD `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`；既有工作区修改和未跟踪文件继续保留。
- 对项目配置的译文根运行本地 `scripts/run_kakuyomu_workflow.py --plan-only`，当前 `source_catalog.raw-html-2026-11-17.json` 返回 `ready_for_review`、88/88 来源有效、0 问题、0 网络、0 Provider、0 写入。预览不输出章节正文。
- 对照旧计划 `translation_plan_review_ai_raw_html_schema2_2026-11-17.json`，来源版本、AI 输入路径/哈希、AI 索引/manifest 和其余映射字段一致；88 个 `tm_key` 从旧 `kakuyomu:` 前缀变为当前 `source-edition:`，所以旧审批摘要不能代表当前计划。
- 用 preview CLI 的 `--plan-output` create-only 新建 `projects/祝福のネトラレラ/Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.json`，摘要 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。新计划经 `translation_plan_approval.load_translation_plan` 校验：`ready_for_review`、88 话、88 个来源有效、0 问题。旧计划保留；该操作写入 1 个新 JSON，没有网络或 Provider 调用。
- 续接时重跑 `scripts/validate_source_editions.py`：当前 raw、AI、人读三方 `verified`，88 话；raw/AI/human 读取量分别为 793,183/774,253/799,293 bytes。计划记录的 AI index SHA-256 与双版本验证输出相同；校验器只在本机重算字节和映射，不输出正文、不写文件。
- 当前 `Workflow/Approvals/` 没有回执，`Knowledge/` 没有 reviewed 全书概要/术语产物。此次未创建审批回执或读取密钥；预览校验器在本机读取 `RAWs_AI` 字节以复算哈希，但没有显示、另存或外传正文。计划预览只证明当前版本映射和哈希契约，不是人工映射/清洗验收。
- 下一步需人工审阅新计划的 88 话映射与两种清洗版本，再为该新摘要生成匹配审批回执；还需审核 full-book summary/glossary。K4 终审 Provider/model、通过规则、返工上限和耗尽/冲突的人工升级责任未确认；在这些前置齐备前不做真实单话调用。

## 2026-11-19 K5 结构化审阅模板续接

- 新增 `scripts/prepare_translation_plan_review.py` 和审批模块的 `create_plan_review_template`/`verify_plan_review_template`。模板只绑定当前计划、人读 `SOURCE_MAP.json` 摘要及逐话映射/输出哈希；创建和审批都会复核索引指向的实际 Markdown 字节，三项决定初始均为 `pending`，输出必须在 `SourceArchive/` 外排他新建。
- 人工填写全部话目的 `mapping_decision`、`ai_edition_decision`、`human_edition_decision` 为 `pass` 且 `issues=[]` 后，使用 `scripts/approve_translation_plan.py --review <review.json> --human-index <SOURCE_MAP.json>` 校验当前索引并生成 schema v2 回执；回执新增 `review_sha256`，旧 schema v1 仍兼容读取。
- 验证：`tests.test_translation_plan_approval` 15 项、`tests.test_kakuyomu_workflow` 14 项通过；完整非 E2E 回归 625 项运行，621 项通过、4 项因 Windows 能力跳过、0 项失败（96.068 秒）。相关 `py_compile`、CLI `--help`、`git diff --check` 通过。模板构造器复核真实试点 88 个章节文件及人读索引，然后在 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.human-review.json` create-only 生成 88 行模板；验证器确认 264 个决定均 pending 并拒绝审批。未显示正文或调用 Provider；`Workflow/Approvals/` 不存在，未生成回执。K5 增量后的 E2E 未重跑；最近一次 K4 增量后的 mock E2E 为 7 项通过、425.782 秒。
- 断点：当前仍停在人工审阅前；下一步是人工检查 88 话计划与双版本，再在模板中填写决定。随后需生成匹配回执、审核 reviewed 全书概要/术语，并在 K4 决策（终审 Provider/model、阈值、返工上限、升级责任）明确后做受控单话试点。

## 2026-11-19 K3 分项轨迹续接

- 当前基线仍为 `codex/translation-workflow-audit-20261117` / `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`；续接前的未提交修改和未跟踪文件全部保留。
- `pipeline.py` 正式 run 的 `StageReports` 现在分别追加 `proofreading`、每次 `reflection` 和 `polishing` 哈希尝试；失败报告使用当前失败子阶段名。尝试不包含原文、译文、批注或提示词；K3 未因此变成独立“信、达、雅”审核。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_kakuyomu_workflow -q`，180 项通过；全量非 E2E 动态发现测试 596 项运行、592 项通过、4 项因 Windows 无法创建 FIFO/符号链接跳过、0 失败，47.287 秒；`.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 7 项通过、205.636 秒、退出码 0；`py_compile` 和 `git diff --check` 通过。详细命令见[开发与验证](../development.md#2026-11-19-正式项目校对反思润色分项轨迹)。
- 本阶段未请求真实 Provider、未读取试点正文，且没有托管服务可部署。K4 终审 Provider/model、通过规则、返工上限、冲突/耗尽后的人工升级责任仍待用户决定；K5 仍需映射与清洗人工验收及获准 Provider 的受控真实试点。
- 下一步仍是用户决定 K4 的终审 Provider/model、终审通过规则、返工上限和耗尽/冲突时的人工升级责任；依决定实现终审与版本化返工。K5 仍需人工验收映射/清洗和合格的真实单话试点。

## 2026-11-18 K4 发布状态一致性续接

- 当前 checkout：`codex/translation-workflow-audit-20261117`，代码 HEAD `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`；保留已有全部未提交/未跟踪文件，没有暂存、提交或清理。受保护的 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 未读取或修改。
- 本次修改 `translation_review.py` 的 run 完成核验：`published` 状态先原子退回 `review_pending`，然后逐话核验发布回执 schema/UTC 时间、已批准审核快照及其 `review_sha256`、当前来源与草稿哈希、正式译文与草稿字节一致。缺少产物保持待审核；篡改/冲突报错，不改动用户文件。重试可重建缺失译文或快照，再重新完成核验。
- 新增 `tests/test_translation_review.py` 覆盖：已发布译文缺失后降级并由批量发布恢复、审核快照更改拒绝并降级状态、已发布译文被改动时保留现场且拒绝确认。定向命令 `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_kakuyomu_workflow -q`：32 项通过。
- 最终验证：全量非 E2E 动态发现测试 594 项运行、590 项通过、4 项因 Windows symlink/FIFO 能力跳过、0 失败，44.369 秒；`.venv\Scripts\python.exe tests\run_tests.py` 7 项本地 mock E2E 全部通过，211.406 秒，退出码 0；`py_compile`、`pip check` 与 `git diff --check` 通过。未调用真实 Provider、Kakuyomu、Notion 或部署服务。
- 下一步：继续 K4 终审报告和版本化返工链的实现前，需确定终审维度/严重问题阈值、返工次数上限、耗尽后的人工升级责任，以及终审模型/Provider。现有方案将初始“两次”仅记作待确认建议，不应把它写成默认生产规则。上述本地状态核验不替代这些决策。

> 状态基准：2026-11-17。较早的续接与审查章节均为历史快照；当前工作树状态和下一步见“2026-11-17 工作树续接”。项目路线图仍有后续阶段，额度信息不可见。

## 2026-11-17 工作树续接

- 当前 checkout 为 `main`，HEAD `e2fe611258532c9f0bab3672eda52cf928102b1a`；工作区有大量未提交/未跟踪改动。它们来自此前持续实施，全部保留；本次仅在其上修改 Pandoc 路径解析、对应合成测试及本交接/开发记录，没有暂存或提交。
- 复核旧 PR #58 审查快照中的两个问题：当前工作树已将 HTTP `IncompleteRead` 转为可恢复的来源暂停，checkpoint 重跑能够继续；Pandoc 可执行文件在版本探测前解析为绝对路径，覆盖带目录的相对路径以及经 `PATH` 查找的裸命令名，转换时切换 `cwd` 不会改变 executable 解析结果。
- 本次新增的 Pandoc 行为测试验证裸命令名经 `shutil.which` 解析为绝对路径；既有测试验证带目录相对路径在版本探测与转换阶段保持相同 executable。HTTP 合成测试验证不完整响应导致 `paused/unavailable`，修复响应后可从 checkpoint 完成。
- 验证：完整非 E2E 回归 513 项运行、0 失败、4 项因 Windows 符号链接/FIFO 能力跳过；受影响聚焦集合 45 项通过；`tests.test_epub_builder` 25 项通过。命令见[开发与验证](../development.md#2026-11-17-历史代码审阅项复核)。
- 2026-11-17 用户再次强调 AI 版与归档职责：翻译直接从 `projects/祝福のネトラレラ/RAWs_AI/` 读取，`SourceArchive/` 只保存归档及其清单/采集与审计快照，不存计划或审批回执。当前现场 88 个 AI 单话 Markdown；两份归档 manifest 分别 356/356、532/532 校验通过；三项定向回归确认 pipeline 从 RAWs_AI 读正文而非归档副本。细节见[开发与验证](../development.md#2026-11-17-raws-ai-作为默认翻译输入)。
- 下一步继续 I0–I6 的未完工作：人工审阅 88 话 AI/人读版与映射计划，生成并审核绑定当前 AI 版本的全书概要/术语表，批准当前计划摘要后创建审批回执，再进行受控真实 Provider 单话翻译。Notion、EPUBCheck/阅读器和来源变化后的下游处理仍按路线图执行；作品授权已确认，不是阻塞。
- 本轮额度状态不可见，未声称达到额度阈值。

## 2026-11-16 Kakuyomu 正文全量刷新续接

- 当前 checkout：`main`，HEAD `a3813c356bc9c8f27f71ebe9b4fd7fa60bd6c8a3`。本任务开始前已有多份未提交代码、测试和文档修改；全部保留，未暂存或提交。当前完整改动以 `git status --short --branch` 和工作树 diff 为准。
- 用户决定：指定书籍已获明确授权；用户是普通读者，要求从作品主页发现完整公开目录，再访问目录中的普通 episode URL 获取正文；不需要官方澄清。平台规则风险记录不作为本试点的答复门槛，也不构成平台背书或法律结论。
- 本阶段已实现显式全量正文刷新：来源 CLI 的 `--refresh-from-catalog`、`--refresh-from-checkpoint` 需要 `--work-url`、新 `--checkpoint` 和新的发现 catalog 路径。重新发现的目录必须与完整基线目录完全一致；基线 checkpoint、catalog 哈希、manifest 和逐话 raw 关系须可核验。刷新逐话重取普通 episode URL，未变正文复用最新 raw 版本，变化正文新增不可变版本；完成报告列出旧/新 version ID 与 SHA-256，不输出正文。暂停后使用同一刷新 checkpoint 续传。
- 验证：聚焦回归 `.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q` 共 109 项通过；`py_compile` 六个源码/测试文件、ingestion CLI `--help`、`git diff --check` 通过；只读 Markdown 检查确认 147 个本地链接目标存在。2026-11-16 真实刷新以 2 秒间隔重取 88/88 话，报告 88 未变、0 变化；新旧 checkpoint 的话目顺序和 raw version ID 绑定一致。新 catalog/checkpoint 为 `source_catalog.refresh-2026-11-16.json` 与 `source_checkpoint.refresh-2026-11-16.json`，旧输入保留；刷新后 manifest 268/268 文件验证通过，`--plan-only` 预览为 88 项、0 问题、`ready_for_review`。旧基线 catalog v1 不含章节分组，不能声称验证了分组未变。
- 当前仍未实现：正文变化自动使译文、概要、TM 或知识进入持久化过期状态；原始 HTML 归档；AI/人类派生版本与转换差异映射；人工正文/ruby/旁点格式验收；真实 Provider 翻译、Notion 和 EPUB 阅读器验收。此次真实刷新没有发现正文变化；刷新报告只提示 `downstream_review_required`，不能替代这些下游操作。
- 下一步：对当前归档代表性章节和 88 话映射做人工核对；实现下游来源变化失效传播；再设计原始表示与双版本。上述工作均未由本轮完成。
- 额度信息无法从当前接口准确核实；保留本阶段的实现和验证状态，不声称达到额度阈值。

## 2026-11-16 I4 来源新鲜度审计续接

- 当前 checkout 仍为 `main`；本工作区有本任务和此前的未提交改动，均保留且未暂存/提交。先用 `git status --short --branch` 确认当前清单，不要重置或覆盖。
- 已实现：`source_manifest.py::latest_raw_parent_for_normalized` 沿 normalized 的直接 raw 父版本查找 manifest 当前 raw。`scripts/validate_tm_provenance.py`、`scripts/validate_knowledge_provenance.py` 与 `story_summary_review.py` 的只读审计/概要发布和运行时加载会校验最新 raw 文件哈希，并在 normalized 未基于当前 raw 重建时拒绝并报告 `stale`；缺失/损坏 lineage 报 `invalid`。
- 新增 synthetic regression 覆盖 raw 已更新、尚未物化新的 normalized artifact 的间隙：TM、知识 provenance 报 stale，概要发布不生成 bundle。14 个相关 unittest 模块运行 295 项、全部通过；命令和故障注入日志说明见[开发与验证](../development.md#2026-11-16-原文版本新鲜度审计补强)。
- 此改动只补只读新鲜度识别，不写持久化过期标记、不自动重建 normalized/TM/知识/概要。2026-11-16 全目录实时刷新发现正文 88/88 未变，因此未发生真实正文变化后的下游验收；用户要求的主页目录发现和普通 episode URL 路径已实现，且用户明确表示无需官方澄清。
- 下一步：人工核查 88 话来源格式和 `CHAPTER_MAP`；再设计可追踪的 stale 状态与派生物重建/复核流程；之后评估原始 HTML/等效证据与 AI/人类双版本。真实 Provider、Notion、EPUB 阅读器和人工格式验收仍待完成。额度状态不可见，不声称达到阈值。

## 2026-11-16 Kakuyomu 纯追加目录更新续接

- 当前 checkout：`main` HEAD `a3813c356bc9c8f27f71ebe9b4fd7fa60bd6c8a3`。本轮开始前工作区已有多份代码、测试和文档未提交修改；均予以保留，没有暂存或提交。本次新增实现涉及 `source_ingestion.py`、`kakuyomu_catalog_diff.py`、`scripts/ingest_kakuyomu_pages.py` 及其测试；同步更新路线图、决策记录、专题方案、开发验证、项目状态和本交接。当前准确脏文件以续接时 `git status --short --branch` 为准。
- 目标与决定：用户确认指定书籍已获授权，是普通读者，要求采集器从作品主页发现完整公开目录，再从普通 episode URL 获取全部公开话目；用户明确不需要官方澄清。该决定不是平台背书、法律结论或公开分发授权。实现保持普通页面、robots、串行限速和既有正文 parser 行为；不登录、不访问 `/read`。
- 已实现纯追加续采：新命令路径使用 `--incremental-from-catalog`、`--incremental-from-checkpoint`、`--work-url` 和新的 `--checkpoint`/发现 catalog 路径。基线要求完整 checkpoint v5；核验旧 catalog 与 checkpoint 的 work/manifest/episode ID 顺序、每话 metadata 与 raw artifact 最新版本/哈希。仅当旧话顺序、标题、位置、URL 和已有章节归属/元数据保持不变且新话追加在末尾时接受；变化或消失会 fail-closed。新 checkpoint 继承经核验的旧 raw 绑定，从基线话数处继续分页采集，checkpoint 仍描述当前全目录。旧 catalog、checkpoint 和 raw artifact 不覆盖。
- 同一目录快照的暂停更新可用相同新 catalog/checkpoint 重跑，从第一个 pending 新话续传；若恢复时目录已再次变化，应改用新 snapshot/checkpoint，不能把不同目录版本拼接。旧 checkpoint 的完成状态不会跳过 manifest/raw 校验。
- 合成验证：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`，105 项通过。集成测试确认更新请求只包含 robots、作品主页和新 episode URL；旧 episode URL 不再请求。覆盖新增话、已有章节末尾追加、旧话/章节变化拒绝、旧 checkpoint 保持不变、暂停后续传、manifest/raw 版本核验。`py_compile` 与 ingestion CLI `--help` 检查通过。未执行真实 Kakuyomu 增量请求，未改外部书籍数据、Provider、Notion 或凭据。
- 剩余：此路径只发现目录纯追加，不会发现旧 episode 正文在目录不变时被修订；显式刷新、正文 hash 差异和历史 raw 新版本策略仍待实现。原始 HTML 归档、AI/人类派生版本映射、人工来源格式验收、真实 Provider 翻译与 Notion 验收亦未完成。历史 88/88 live 采集与本轮 synthetic 验证是不同证据；不能将本轮称为真实增量采集。
- 下一步可直接执行：为既有 episode 增加显式 refresh 模式及不可变 raw 版本 hash diff；验收需证明无变化正文可复用、变化正文产生新版本且旧版本保持不变、checkpoint 在失败时可续传，并报告关联翻译/概要/知识待复核。随后再设计原始 HTML 或等效表示及 AI/人类版本映射。
- 五小时额度状态无法从当前接口准确核实；本次在纯追加续采阶段形成自然检查点，不声称达到额度阈值。

## 2026-11-16 PR #58 已合并与当前阶段

- 当前主分支：`main` HEAD `b1048a31dad00497c8807d8cbf5570f2c0795e38`。PR #58 于 2026-11-16（Asia/Shanghai）以 squash 合并；经验证的实现/测试提交为 `8f1f89fb62a221fffd8415489fff82cbf4248116`。本地核对两提交的文件树一致。
- 本轮修复两项最后未解决 review：`kakuyomu_page_source.py` 将 `http.client.IncompleteRead` 转为可恢复 `SourceUnavailable`；`epub_builder.py` 在 Pandoc 预检前将带目录的相对 executable 解析为绝对路径，同时保留裸名称的 PATH 查找。回归覆盖不完整响应暂停/续传，以及版本预检和转换使用同一 executable。
- 验证：完整非 E2E 351 项通过、4 项跳过；Kakuyomu adapter/workflow 与 EPUB builder 定向集合 52 项通过；本地 mock E2E 7 项通过、266.420 秒；`compileall` 和 `git diff --check` 通过。依用户授权以管理员 PowerShell 重跑路径安全模块，11 项中 10 项通过，3 个符号链接用例全通过，FIFO 因 Windows 平台限制跳过。
- PR 所有 inline review threads 均已解决；review submissions 没有 `APPROVED`，CodeRabbit check 为 `skipped`。GitHub 检查显示 `main` 没有 branch protection，rulesets 查询为空，未报告 required checks。按用户要求完成 squash 合并；CodeRabbit 的 skipped 状态不作为测试通过证据。
- 真实 Provider/Notion 未调用；最近一次本机存在性预检没有发现 `.env`、Provider endpoint/key 或 `PROVIDER_DATA_POLICY`。真实单话翻译、人工译文与来源格式验收、EPUBCheck/阅读器和部署仍未完成。
- 下一步：安全配置经授权的 JOJO/JYQF endpoint、模型与最小数据类别 allowlist；复核指定章节映射和 TM 键；运行一话真实翻译并人工验收忠实度、段落、U+3000、ruby、标点与前后一致性。配置未就绪时继续 synthetic/mock 验证，不调用未授权 Provider。

## 目标与会话

- 目标：整理翻译工作流文档体系、计划、阶段状态和实施记录，并按阶段实施当前可安全完成的工作。
- 截至 2026-11-15 本次续接，已通过 `read_thread` 分页读取两个引用会话，均读至 `hasMore=false`。会话内容仅作为需求与决策线索，实施状态仍以当前仓库和可复核验证为准：
  - `thread://01a1d41d-9f87-74b1-9589-421496c452ed`：文档体系目标、AI 优先的信息组织、当前日译中范围、明确事实/计划/未知及避免重复维护的要求。
  - `thread://01a1d5a2-a18a-7381-b24a-82fc4d5d4894`：路线图评估、分阶段实施要求，以及 Provider 配置、Agent 角色和 15 项用户决策。
- 当前权威资料：`README.md`、`docs/project-status.md`、`docs/architecture.md`、`docs/translation-workflow.md`、`docs/knowledge-governance.md`、`docs/development.md`、`docs/roadmap.md`、`docs/decisions/README.md`、`docs/model-provider-configuration-plan.md`、`docs/source-ingestion-and-publication-plan.md`。
- `.agents/` 与旧 handoff 是历史材料；状态以当前代码、测试、路线图和开发验证记录为准。
- 用户于 2026-11-15 再次明确指定试点书籍已获得授权；按已授权处理，后续不得把作品权利列为阻塞。该确认不替代平台自动化访问规则，也不扩大到公开分发。Provider 范围另有用户决定：JOJO/JYQF 各自职责所需的最小类别已授权；Notion 及其他 Provider/类别不在此授权内。

## 当前状态与决策

> 当前权威状态见上方“2026-11-16 PR #58 已合并与当前阶段”。以下较早快照保留其当时证据；若与最新状态不同，以该段和开发验证文档为准。

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
- 当时查阅官方[服务条款](https://kakuyomu.jp/legal/tos)页面（页面标注 2025-08-06 更新），并基于其关于分析网站/应用结构的文字，提出需要平台解释 Apollo/page-class 解析方式的顾虑。该顾虑属于当时评估，后来用户明确决定无需官方澄清，且按普通 URL 路径完成了主页声明的 88/88 话采集；它不再构成实施门槛，也不代表对条款作出法律判断。实现仍不调用未文档化 API、不伪装 User-Agent、不请求 `/read` 或绕过访问限制。
- 当时提出的下一步曾要求官方答复后再运行 live 采集；该门槛已被用户明确决定取代。用户确认无需官方澄清，并要求按普通主页/episode URL 继续；随后已完成历史 88/88 source-only 采集。此段保留为历史风险评估，不作为当前实施条件，也不构成平台背书或法律结论。
- 本复核未改代码或发起章节请求。测试沿用上节已有结果，本轮只做了 robots、主页 anchor 数和服务条款检查；文档链接目标检查应在本轮文档编辑后重跑。额度信息仍不可见。
- 本轮文档更新后验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q` 运行 23 项、全部通过；`git diff --check` 通过；README 与 `docs/` 下 13 份 Markdown 的本地链接目标均存在（自定义检查不验证锚点）。当时未重跑完整 mock E2E，因为实现代码未变；随后已按用户决定完成真实全目录采集，见本交接后续 2026-11-15 与 2026-11-16 检查点。
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

## 2026-11-16 续接与 PR 状态

- 当前实现提交：`3ffb7f1eada063095ae9e7d4485977ecd8b597ce`，分支 `codex/translation-workflow-20261115`，已推送到 `origin`。本次提交 41 个文件，包含翻译工作流修复、Kakuyomu 来源 adapter/CLI、回归测试及文档更新；未提交书籍原文、译文或凭据。
- 验证：完整非 E2E unittest 333 项运行、0 失败、4 跳过；3 项符号链接用例因 Windows `WinError 1314` 无创建权限，1 项 FIFO 因 Windows 不支持 `os.mkfifo`。完整 `tests\run_tests.py` mock E2E 为 7 项通过（229.307 秒），`compileall` 与提交前 `git diff --check` 通过。
- 符号链接专项：用户提供的历史命令输出为 9 项运行、3 项跳过、0 失败。对当前 checkout 重新运行 `.\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v` 得到 11 项运行、7 项通过、4 项跳过；三个 symlink 用例分别报告 `WinError 1314`，FIFO 用例为平台不支持。结果计数差异说明两次测试使用的测试集合不同；均没有测试失败。
- 用户明确批准提权尝试，但当前执行器阻止启动管理员 PowerShell；未尝试绕过。若需补跑，请在开始菜单以“管理员身份”打开 PowerShell、批准 UAC，然后执行：

  ```powershell
  Set-Location -LiteralPath 'D:\OWN\Programming\AI\TranslatorAI\Light Novel Translation Workflow System'
  ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  .\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v
  ```

  第二行应返回 `True`。FIFO 用例在 Windows 上仍可能因 `os.mkfifo` 不可用而正常跳过。
- GitHub 状态复核：PR #56 已合并；PR #58 指向 `3ffb7f1`，状态仍为 open，虽标记 mergeable，但 review threads 尚未清理且该提交的 workflow-runs 查询为空，因此本轮未合并 PR #58。PR #58 描述已同步当前测试数字和限制；评论的修复状态仍待审阅确认。
- 剩余人类工作：管理员环境补跑 symlink 用例；人工验收已归档章节的段落、U+3000、ruby、标点及顺序；本地确认 Provider allowlist/端点后执行获授权的单话真实翻译并人工验收。真实 Provider、Notion、EPUB 阅读器和部署未在本轮验证。

## 2026-11-16 路径测试结果续记

- 用户提供的命令输出：`.\.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q`，`Ran 9 tests ... OK (skipped=3)`。输出未包含运行时 HEAD、逐项跳过原因或管理员权限状态；该 9 项结果不归属到本交接记录中的任何特定 SHA。后续当前 checkout 的管理员结果见本文件最新状态段，[开发与验证](../development.md#2026-11-16-pr-60-合并后基线)记录了已合并代码树的复核。
- 当前 GitHub 快照：PR #58 仍为 open，head `a10926b`、base `d7e2afd`；对该 head 的 GitHub Actions workflow-runs 查询为空。PR #56 已合并，和仍开放的 PR #58 是不同变更。PR #58 未合并；合并前须重新核对审查意见并满足必要验证。

## 2026-11-16 审查回归与最新状态

- 当前 checkout 分支 `codex/translation-workflow-20261115`，基线 HEAD `bd9f4f3996c0117d7d69af6389029092b146808c`。基线上有 20 个已修改文件，包含 Kakuyomu 重跑与根目录校验、章节位置和来源版本绑定、段落对齐、RAG 磁盘指纹、EPUB YAML 元数据与 OPF spine 映射、manifest 单快照处理、README 代理说明，以及对应回归测试和文档；增量尚未提交或推送。用户原文、译文和凭据未纳入 Git。
- 完整非 E2E unittest 运行 348 项，0 失败、4 项因普通 Windows 会话能力限制跳过；完整 mock E2E 7 项通过，230.911 秒。Python `compileall`、`git diff --check` 和文档本地链接目标检查通过。测试过程与限制见[开发与验证](../development.md#2026-11-16-pr-审查回归工作区历史快照)。
- 用户同意对权限受限用例提权后，已用 `Start-Process -Verb RunAs` 重跑路径安全模块：11 项运行、10 项通过、仅 FIFO 用例跳过；此前普通权限跳过的 3 个符号链接用例均通过。用户提供的 9 项/3 项跳过结果仍不绑定到此 checkout。
- PR #56 已合并。PR #58 仍开放，远端 head 为 `bd9f4f3996c0117d7d69af6389029092b146808c`，`mergeable=true`，但该 head 的 Actions 查询为空，且 Codex/CodeRabbit review threads 仍有未解决意见。本地未提交增量不属于该远端 head；未执行合并。
- 本地增量已针对 PR #58 已知的 EPUB YAML 元数据读取、OPF spine 身份映射和 manifest 快照、RAG TM 指纹、来源读取绑定、章节对齐空白规范化、跨盘根路径判定、README 代理前置条件等意见补齐实现和回归测试；尚未推送，不能据此关闭远端 review threads。真实 Provider/Notion、人工译文验收、EPUBCheck/阅读器和部署仍未验证。

## 2026-11-16 提交与 PR 状态复核

- 当前分支 `codex/translation-workflow-20261115`。代码/测试实现提交 `e9adc8d83ce4887e0eee52ae466f7846e8574bab` 已推送至 PR #58；其后 `92c9095` 及本次后续提交只更新 Markdown 状态，不改变经验证的代码/测试树。书籍原文、译文和凭据没有纳入这些提交。
- 验证：提交前同一代码树完整非 E2E unittest 348 项运行、0 失败、4 项普通 Windows 权限/平台限制跳过；管理员 PowerShell 下路径安全模块 11 项运行、10 项通过、1 项 FIFO 跳过，全部 3 个符号链接用例通过；当前 HEAD 聚焦回归 225 项通过；同一代码树 mock E2E 7 项通过（230.911 秒）。`compileall`、提交前 `git diff --check` 和文档链接检查通过。mock/synthetic 结果不代表真实 Provider、Notion、人工翻译质量或部署验收。
- 用户提供的路径测试输出为 9 项运行、3 项跳过，但没有运行时 HEAD 或逐项跳过原因，不绑定到当前 commit。管理员运行的 11 项结果是当前代码测试方法集合的权限复核。
- 本节首次远端复核时 PR #58 为 open、`mergeable=true`，head `92c9095`；该文档提交的 workflow-runs 查询为空。11 个此前未解决的 inline review threads 均已回复并解决。PR review submissions 只有 `COMMENTED`，没有 `APPROVED`；读取 `main` 分支保护规则因 GitHub 集成返回 403，所需审批/检查门槛未知，因此未合并。之后的提交仅限 Markdown，精确 head 和重新查询结果以 PR 页面为准。PR #56 已独立合并，不能与 #58 混为一谈。
- 2026-11-16 本机 Provider 配置存在性复核：根目录 `.env` 不存在；`PROVIDER_DATA_POLICY`、`JOJO_BASE_URL`、`JOJO_API_KEY`、`JYQF_BASE_URL`、`JYQF_API_KEY`、`PROOFREAD_MODEL` 在 Process/User/Machine 环境均未设置。只检查是否存在，未读取密钥或配置值；真实 Provider 单话翻译目前受此阻塞。配置应由凭据所有者通过本机安全方式提供，并在运行前再次验证 allowlist 与目标 Provider。
- PR #58 描述已更新为当前代码/测试基线、文档 head 和限制。仍待独立 reviewer 审阅/审批及仓库门槛确认；真实 Provider 的 allowlist/端点、单话翻译与人工验收、Notion、EPUBCheck/阅读器、部署仍未验证。额度状态不可见。

## 2026-11-16 7135904 后续复核

- 代码/测试基线为 `71359040b88434a37ac379247674a6155e614f86`；工作区复核时干净。`b3f8047` 修复 EPUB POSIX 路径/自链接、Unicode 段落缩进、提交译文字节校验和空输出冲突处理；`7135904` 将响应体读取超时转为可恢复的来源暂停。
- 对该实现树的完整非 E2E unittest 为 350 项、0 失败、4 跳过；完整 mock E2E 为 7 项通过、348.780 秒。聚焦 EPUB/契约/Kakuyomu 工作流回归 108 项通过；来源 adapter/ingestion/workflow 回归 62 项通过。`compileall` 与 `git diff --check` 通过。均为合成/mock 或本地验证，未调用真实 Provider/Notion。
- 本轮当前普通 Windows 会话重跑 `tests.test_security_path_traversal -v`：11 项运行、7 项通过、4 项跳过；3 个 symlink 用例因 `WinError 1314` 跳过，FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过。未取得管理员执行会话。用户另行提供的 `-q` 结果为 9 项运行、3 项跳过，但没有 SHA、逐项跳过原因或权限状态，且与当前文件的 11 个测试方法数不符，因此只作为独立用户提供快照，不归属到本代码基线。
- 合并前远端快照：PR #58 为 open，head `71359040b88434a37ac379247674a6155e614f86`、base `d7e2afda43add0a75cf6d720cfb9a8079d6333a6`，`mergeable=true`。所有 inline review threads 已回复并解决；review submissions 仍无 `APPROVED`。GitHub Actions runs 与 commit statuses 为空；唯一 check-run 是 CodeRabbit `skipped`。读取 `main` 分支保护规则仍因 GitHub 集成 403 而不可验证。因此 `mergeable` 只表明无冲突，不证明审批或检查门槛已满足；是否可合并须以随后的 GitHub 合并结果为准。
- 本机 Provider 配置存在性预检仍显示根目录 `.env` 不存在，且 `PROVIDER_DATA_POLICY`、JOJO/JYQF endpoint/key、`PROOFREAD_MODEL` 未设置；未读取密钥。真实 Provider 单话翻译、人工译文与来源格式验收、Notion、EPUBCheck/阅读器及部署均未验证。

## 2026-11-16 合并前状态复核 854bd86

- 最新代码/测试实现仍为 `71359040b88434a37ac379247674a6155e614f86`；`854bd86` 只更新 Markdown 验证与交接状态，不改代码或测试。用户提供的路径测试结果仍为 9 项运行、3 项跳过；没有 SHA/逐项原因，不能归属到该实现提交。当前普通会话实测为 11 项、7 项通过、4 项跳过，3 项 symlink 因 `WinError 1314`、FIFO 因 Windows 平台限制跳过。
- PR #58 在 `854bd86` 上仍为 open 且 `mergeable=true`，但新 review 添加两项未解决意见：`kakuyomu_page_source.py` 未捕获 chunked response 的 `http.client.IncompleteRead`，失败会使采集 checkpoint 留在 `in_progress`；`epub_builder.py` 在 `cwd=input_dir` 下使用未经解析的相对 Pandoc 可执行文件路径，可能通过版本检查后在转换阶段找不到程序。已核对相关代码，尚未修复或关闭意见。
- 当前 PR review submissions 只有 `COMMENTED`，没有 `APPROVED`；head 的 CodeRabbit check-run 为 `skipped`，不能作为通过。分支保护读取仍因集成 403 不可验证。由于原任务范围为 Markdown-only，未修改上述代码；PR 未合并。若继续合并工作，需要先明确允许扩展到代码修复与针对性回归，再重新检查审查和 GitHub 门槛。
- `854bd86` 文档同步只覆盖当时的远端快照；若其后 PR head 或 review 状态变化，以 GitHub 当前状态为准。真实 Provider/Notion、人工翻译验收、EPUBCheck/阅读器、部署及额度仍未验证。

## 2026-11-16 PR #63 后主线复核

- 当前主线为 `main`，HEAD `fe43ea3fb9ff6ac3a901e4c73641bcb9c6af38e6`；PR #63 只同步 Markdown，代码基线是 `c988c4b749a9972a89edffe9bc2c4bc867ebb3da`。本轮检查开始时工作区干净；PR #64 是基于此主线创建的文档更新。
- GitHub API 确认 PR #56、#58、#62、#63 均已合并。创建 PR #64 前，`gh pr list --state open` 返回空列表。旧小节中 PR #58 仍 open 的状态是当时快照，不是当前状态。
- 当前代码树路径安全模块普通权限运行 11 项、7 项通过、4 项跳过；3 项符号链接因 `WinError 1314` 跳过，1 项 FIFO 因 Windows 不提供 `os.mkfifo` 跳过。经用户授权的管理员运行 11 项、10 项通过、1 项 FIFO 跳过；3 项符号链接用例均通过。用户另行提供的 9 项/3 项 `-q` 输出未绑定到当前 SHA。
- 当前完整非 E2E 回归按 21 个测试模块运行 368 项、0 失败、4 项跳过；3 项符号链接用例因普通权限下 `WinError 1314` 跳过，1 项 FIFO 因 Windows 不提供 `os.mkfifo` 跳过。经用户授权管理员复跑路径安全模块 11 项、10 项通过、1 项 FIFO 跳过，3 个符号链接用例通过。
- 完整 mock E2E runner 运行 7 项、全部通过，242.450 秒，退出码 0。故障注入产生的内容过滤和段落错配输出属于负向 fixture。`compileall` 和 `pip check` 通过。
- 真实 Provider 配置仍待本机安全配置和验证；真实翻译与人工质量/来源格式验收、Notion、EPUBCheck/阅读器、部署仍未完成。下一步可在配置好 JOJO/JYQF 端点、密钥和最小数据授权后，执行单话真实翻译并由用户验收；不要将 mock 结果视为真实模型质量证明。
- 详细测试基线见[开发与验证](../development.md#2026-11-16-主线复核pr-63-后)；现状摘要见[项目现状](../project-status.md)。

## 2026-11-16 PR #64 合并后续接

- PR #64 已于 2026-11-15T22:52:31Z 合并，squash commit 为 `16899a1f55a798a440157b5c2265211c953ea0d9`；PR 只同步文档，代码/测试基线仍是 `c988c4b749a9972a89edffe9bc2c4bc867ebb3da`。此前过时的 CodeRabbit review thread 已解决，其摘要问题已由后续提交修正。
- 使用 `--plan-only --plan-output` 将 88 话计划导出到试点生肉根的 `translation_plan_review_2026-11-16.json`。报告 88/88 来源有效、0 问题、0 网络/Provider 请求、0 正文内容、1 次写入（计划文件）；摘要 `36dae9c08069ce5c66eddc1e870a0aa4aa4d1724b00589ed9a5be62ce4bc22d4` 重算一致。
- 计划包含位置 1–88；87 个编号话目为第 1–87 话且顺序连续，位置 48 是幕间。各 episode ID、来源路径/版本、目标译文路径和 TM key 均唯一；所有目标译文当前不存在。这些是元数据一致性检查，不表示原文正文和映射已被人审。
- 下一步为用户审阅[试点映射审阅说明](2026-11-16-pilot-plan-review.md)和仓库外计划 JSON。未明确批准前，不创建审批回执、不执行真实 Provider 翻译。原文格式、译文路径/TM key、当前端点与运行时 allowlist 仍分别待验收/核验。
- 用户报告的 `tests.test_security_path_traversal -q` 结果仍按独立快照记录为 9 项运行、3 项跳过；未提供 SHA 或逐项跳过原因。该数字不替代当前代码基线 11 项的普通权限/管理员 verbose 结果。

## 2026-11-16 Kakuyomu 全目录采集需求续接

- 当前 checkout：`main`，HEAD `a3813c3`；本轮开始时有五份未提交 Markdown 修改：`docs/development.md`、`docs/project-status.md`、`docs/roadmap.md`、`docs/source-ingestion-and-publication-plan.md`、`docs/translation-workflow.md`。这些初始修改均保留；本轮未修改产品 Python 源码、书籍数据或凭据，新增一条 synthetic parser regression test，没有暂存或提交。
- 用户明确指定试点作品已获得授权；用户是普通读者，要求从作品主页发现完整公开目录 URL，再用普通 episode URL 获取全部公开话目，并明确不需要官方澄清。按此用户决定继续，不依赖作者 ZIP，也不把官方答复列为前置条件。平台规则观察仅作风险背景；该决定不等同平台背书、法律结论或公开分发授权。
- 当前代码已具备用户要求的发现/采集路径：`kakuyomu_page_source.py::discover_kakuyomu_work_catalog` 解析作品页 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 中的 episode ID/title，检查唯一话目数等于 `publicEpisodeCount` 后生成普通 URL；CLI 可从 `--work-url` 获取所有目录话目。正文 parser v4 支持唯一 `widget-episodeBody`/`js-episode-body`、段落边界、ruby、`emphasisDots` 和 U+3000。请求间隔为 1.5–3 秒、默认 2 秒；checkpoint 可续传未完成话。
- 已有历史 live 记录：主页声明 88 话，source-only 获取 88/88；manifest 267 个文件型 artifact 的 SHA-256 校验通过。该事实只对应当时主页公开计数；不证明公开计数外完整性，也不是本轮真实网络采集。解析器归档 UTF-8 可见正文，未保存原始 HTML；截至本续接记录前的 catalog 版本未保存分组章节名/范围，后续 schema v2 状态见下节。
- 本轮验证：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`，增加 `&nbsp;`/U+3000 回归后 31 项通过。它使用 synthetic HTTP/HTML fixture；本轮没有请求 Kakuyomu、Provider 或 Notion。
- 本轮文档更新涉及上述已修改文档中的 `development.md`、`project-status.md`、`roadmap.md`、`source-ingestion-and-publication-plan.md`，并追加本交接；`translation-workflow.md` 原有修改保留未动。另修改 `tests/test_kakuyomu_page_source.py` 增加空白字符 fixture。更新校正旧的单话描述、过时的 read_thread 工具说明、I3 目录证据表述和专题方案历史基线。
- 下一步：
  1. 若继续用户给出的完整元数据目标，先扩展 synthetic Apollo fixture 与 catalog schema，捕获分卷/章节名、位置范围及作品元数据；定义 catalog 快照差异和只抓新增/明确刷新的策略，并验证新增、改名、重排、消失、重复/缺失/空分组及结构变化。
  2. 设计原始 HTML 保存与当前 UTF-8 可见正文的父子版本关系；若确认实施，需增加输入大小上限、独立哈希、敏感正文不进日志、断点续传和失败恢复测试。不可从现有提取正文重建未保存 HTML。
  3. 分别物化 AI 版与人类版，逐段记录转换规则和来源映射；覆盖 ruby、旁点、NBSP、U+3000、前后记、作者话、插图占位和未知标记，并安排真实样本人工验收。
  4. 真实 Provider 翻译仍须先完成 88 话映射人工审阅、匹配审批回执和本机 allowlist/端点预检；配置缺失时保留 source-only 状态。Notion、EPUB 阅读器和发布仍单独验收。
- 计划、阶段依赖、范围及可验证验收见[原文采集与成果归档方案](../source-ingestion-and-publication-plan.md#搜索与双版本需求复核2026-11-16)。五小时额度状态不可见，本记录不声称达到额度阈值。

## 2026-11-16 Kakuyomu catalog v2 分组元数据续接

- 继续时工作树仍为 `main`，HEAD `a3813c3`。保留前一阶段已有的 5 份未提交文档修改；本轮在 `kakuyomu_page_source.py`、两个 Kakuyomu CLI、合成测试及现有状态/计划文档上继续修改。未暂存、提交、清理书籍数据或读取/输出章节正文。
- 用户已确认试点书籍获得明确授权；用户为普通读者，要求从作品主页发现完整公开目录 URL 并逐话请求普通 episode URL，也明确表示不需要官方澄清。该决定持续按用户决定处理，不改写成平台背书、法律结论或公开分发授权。
- 已实现的增量：`KakuyomuChapterGroup` 从 Apollo `TableOfContentsChapter.chapter -> Chapter` 读取分组 ID、章节 ID/标题/层级，并保存连续位置范围和该组 episode ID 顺序；发现 fingerprint 现绑定这些字段。discovered catalog 写出 schema v2；`scripts/ingest_kakuyomu_pages.py::_load_catalog` 仍接受旧 schema v1，并对 v2 严格校验字段、位置连续性、ID 唯一性及所有 episode 的目录顺序完整覆盖。`scripts/ingest_kakuyomu_pages.py` 与 `scripts/run_kakuyomu_workflow.py` 均传入并保存分组。CLI 已发现 catalog 路径继续排他新建，不覆盖不同内容。
- fingerprint 因包含分组元数据而变化；旧 `--work-url` checkpoint（包括 complete 状态）会与当前快照不匹配，不能直接复用。已有 88/88 采集不需在本轮重跑；未来若明确刷新，先审阅旧 catalog/checkpoint/manifest，再用新的 catalog 和 checkpoint 路径，保留旧证据。
- synthetic fixture 覆盖两组分卷映射、v2 写入再读取、v1 兼容、v2 缺组与重排拒绝。验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`，33 项通过。仅使用 synthetic HTTP/HTML，无站点、Provider 或 Notion 请求。
- 本轮未实现或验证：作品标题/作者/简介等作品级字段；目录新旧快照的新增/改名/重排/消失报告和刷新策略；原始 HTML 响应及其与现有可见文本 artifact 的版本关系；AI/人类双版本和转换差异映射；真实正文格式人工验收。已有 source-only 88/88 和 manifest 267/267 是先前 live/本地检查点，不是本轮复验，也不证明主页计数外完整性。
- 下一步建议：先在 `tests/test_kakuyomu_page_source.py` 为缺失/错误 `Chapter` 引用、空目录组和混合无章节组补合成 fixture，确认站点允许的结构契约；再为 catalog snapshot diff 定义只报告、不自动删除的新增、改名、重排和消失状态，决定显式刷新如何绑定 checkpoint/source version；之后单独设计原始 HTML 的内容上限、hash、artifact 类型和失败恢复，再做转换双版本。每一子项均运行该模块与 workflow 模块；若改 source manifest/checkpoint，另跑 `tests.test_source_ingestion`、`tests.test_source_manifest` 和 project runner。
- 当前 dirty worktree 中的所有用户及本任务修改均须保留。五小时额度状态不可见，本记录不声称达到额度阈值。

## 2026-11-16 Kakuyomu catalog snapshot diff 续接

- 起点仍为 `main` / `a3813c3`，保留上一阶段 10 个已修改文件及其全部未提交内容。本阶段新增 `kakuyomu_catalog_diff.py`、`scripts/diff_kakuyomu_catalogs.py` 和 `tests/test_kakuyomu_catalog_diff.py`，并扩展来源 catalog loader 与现有文档；本阶段没有站点/Provider/Notion请求，没有读取或写入实际书籍正文，没有暂存或提交。
- 新 CLI 只读加载并校验旧/新 v1/v2 catalog，比较 episode 新增、消失、标题变化、位置变化；两份均为 v2 时，还比较章节归属、章节 ID/标题/层级、范围、成员和空分组变化。JSON 报告绑定输入 catalog SHA-256，不输出标题或正文。若带 `--export added|updated --catalog-output <新路径>`，会排他新建只包含相应 episode 的 v1 catalog，并报告导出文件 SHA-256；可传给 `scripts/ingest_kakuyomu_pages.py --catalog`。既有文件不会被覆盖，消失项只报告，不删除 artifact。
- 本阶段已补上前一节计划中的空目录组、无章节组和坏 `Chapter` 引用 fixture；差异报告及子集导出完成了前一节待办中要求的“只报告、不自动删除”基础行为，自动刷新编排仍未完成。
- 子集 catalog 的 episode 位置沿用完整目录位置；合成集成测试已证明单话位置为 3 的新增子集能由现有 source-ingestion core 采集完成。所得 checkpoint `complete` 只代表该选集，不能当作全书完成；导入时必须使用独立 checkpoint。`updated` 仅表示目录元数据/分组变化；目录无变化的正文修订无法被该 diff 发现，需显式全量刷新。v1 旧快照不包含分组，章节比较为 `unavailable_v1_snapshot`。旧 `--work-url` checkpoint 仍受 schema v2 新 fingerprint 不匹配影响，继续保留旧证据。
- 新增合成验证覆盖 v1/v2 对比、章节空分组变化、标题修改、重排、成员/章节变化、删除报告、新增子集写出哈希及拒绝覆盖，并使用现有 ingestion CLI 完成选集采集。最终命令：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`，40 项通过。没有真实站点运行证据。
- 用户随后补充当前页面结构观察：主页初始 HTML 内嵌目录状态；正文常用 `div.widget-episodeBody`、带 ID 的 `p` 段落、`ruby/rb/rt/rp` 和 `em.emphasisDots`；应保留旁点、NBSP 与 U+3000。当前标准库 parser 已覆盖这些表示；本轮另将首段 U+3000 与 `p id="p1"` 纳入 synthetic fixture。该结构说明按用户提供的信息记录，历史 88/88 live 采集不是本轮复验，且没有原始 HTML 可供重新检查。
- 更新后的验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`，41 项通过；未访问 Kakuyomu、Provider 或 Notion。
- 计划和复现入口见[原文采集与成果归档方案](../source-ingestion-and-publication-plan.md#搜索与双版本需求复核2026-11-16)，实现与验证边界见[开发与验证](../development.md#2026-11-16-kakuyomu-主页发现与逐话采集复核)。
- 下一阶段：补齐作品标题/作者/简介等主页元数据契约；明确目录无变化时如何按用户命令刷新正文，以及新 snapshot/full refresh 应如何绑定新 checkpoint；然后设计原始 HTML/等效原始表示的大小上限、manifest artifact 类型、正文哈希和恢复语义，再实现 AI/人类双版本转换映射。所有现有脏文件必须原样保留。额度状态不可见，不声称达到阈值。

## 2026-11-16 Kakuyomu 作品元数据 schema v3 续接

- 用户补充并确认：指定书籍有明确授权；采集系统须从作品主页发现完整公开目录 URL，再通过普通 episode URL 获取全部公开话目；用户是普通读者且明确不需要官方澄清。此前记录中的“等待官方澄清”已按用户决定修正为非阻塞事项。该决定不代表平台背书、法律结论或公开分发授权。
- 延续起点仍为 `main` / `a3813c3`。保留本阶段前已存在的五份 Markdown 未提交修改；当前仍未暂存或提交，也未清理任何书籍数据或凭据。
- 用户提供的页面结构信息与实现目标：作品主页服务端 HTML/Apollo 状态用于完整目录发现；episode 正文经普通 URL 获取；正文 parser 应保留 ruby、旁点、段落、NBSP 和 U+3000。当前实现按公开目录计数核对所有 episode ID/title，生成普通 episode URL；限速默认 2 秒且范围为 1.5–3 秒，遵守 robots，不登录、不访问 `/read`，不尝试绕过拒绝。
- 本阶段对 Kakuyomu 作品主页进行了一次代理配置下的只读结构请求，响应 HTTP 200；只检查 Apollo 字段名、类型及引用形状，没有输出字段内容，也没有访问 episode 正文。观察到的作品字段与实现白名单一致：title、author name/screenName、catchphrase、introduction、genre、tagLabels、serialStatus、publishedAt、lastEpisodePublishedAt、publicEpisodeCount。该观察是单次页面快照，不证明网站所有作品/字段恒定。
- 已实现 schema v3：`kakuyomu_page_source.py` 提取白名单作品元数据并随 discovered catalog 写入；`scripts/ingest_kakuyomu_pages.py` 校验 v3 并继续读取 v1/v2；两个 Kakuyomu CLI 均将发现元数据写入 catalog。`kakuyomu_catalog_diff.py` 对比两个 v3 快照时仅报告变化字段名，不将简介、标签等值写入报告。元数据变化不改变 episode source fingerprint。
- 局部能力和限制：作品元数据当前保存在 discovered catalog，不是 source manifest 中独立版本化的 artifact；未记录独立抓取时间；未保存原始 HTML；元数据变化不会自动刷新 episode 正文、概要或知识。旧 schema v1/v2 缺少作品元数据时标记为不可比较。章节/episode 子集导出不因仅作品字段变化而触发。
- 验证：`.\.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow -q`，43 项通过。覆盖 v1/v2/v3 catalog、元数据字段校验、元数据变动报告不回显字段值、元数据单独变化不修改 episode fingerprint，以及先前章节差异/选集导入行为。该命令使用 synthetic fixtures；没有真实 episode 抓取、Provider、Notion 或真实翻译。
- 本阶段更新：`kakuyomu_page_source.py`、`scripts/ingest_kakuyomu_pages.py`、`scripts/run_kakuyomu_workflow.py`、`kakuyomu_catalog_diff.py`、`scripts/diff_kakuyomu_catalogs.py`、`tests/test_kakuyomu_page_source.py`、`tests/test_kakuyomu_catalog_diff.py`，以及专题计划、开发验证、项目现状、路线图和本交接文档。未暂存或提交。此前 v2/41 项等记录保留作历史，不冒充 v3 结果。
- 下一步建议按专题计划阶段 2 继续：为作品元数据设计 source manifest artifact 与抓取时间；明确其更新如何使概要/知识候选过期；增加正文显式刷新和 hash 变更检测，并规定新 checkpoint/保留历史的行为。随后再实现原始 HTML 或等效来源表示的版本关系，以及 AI/人类版转换映射。每项均须增加离线 fixture、跑对应 unittest 和 `git diff --check`；真实页面结构复核只在必要时进行并保持低频。
- 当前未完成：完整作品元数据可见范围、元数据 manifest 版本/抓取时间、正文 refresh/diff、原始 HTML 归档、AI/人类双版本、人工正文格式验收、88 话映射人工审批和真实 Provider 翻译、Notion、EPUB 阅读器。历史 88/88 和 manifest 267/267 均是更早检查点，不是本阶段复验。额度信息不可见，本记录不声称达到任何额度阈值。
- 续接时需保留本工作区全部任务及用户改动；具体路径以 `git status --short --branch` 为准。

## 2026-11-16 Kakuyomu 元数据版本归档与实时采集复核

- 本阶段继续自 `main` / `a3813c3`，保留工作区原有文档、代码、测试修改；没有暂存、提交或覆盖外部试点原文。用户确认指定作品已获授权，并明确要求无需官方澄清；采集路径是主页发现完整公开目录后访问普通 episode URL。
- 按仓库代理要求实时访问作品主页，发现 88 个唯一普通 episode URL，匹配主页公开数 88，共 3 个目录分组；随后访问首个普通 episode URL 获取并解析一话。输出只记录计数与格式特征，不包含标题或正文。该话保留 ruby 表示、U+3000 和段落边界，但未包含旁点/NBSP；后二者仍由 synthetic fixture 覆盖。
- 对本机试点原文根运行 manifest validator，结果 `schema_version=1 artifacts=267 files_verified=267`。已有 checkpoint 为 schema v5、complete、88/88；现有 discovered catalog 为 schema v1。未重新请求其余 87 个正文页，因此此记录不把本次称为全书 live replay；manifest 通过只证明登记字节与哈希一致。
- 新增的 `_persist_work_metadata` 将 homepage metadata 作为 source manifest `kind=work` artifact 按 UTC 时间、SHA-256 和 parent version 追加；同一 metadata 去重，累计字节纳入 archive limit，synthetic tests 覆盖去重/版本链/大小限制。已有 267-artifact 试点 manifest 尚未包含此新 artifact；旧 catalog/checkpoint 与当前 parser fingerprint 的升级策略仍待设计，不能直接覆盖旧目录或盲目重抓全书。
- 定向联合回归：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_catalog_diff tests.test_kakuyomu_page_source tests.test_kakuyomu_workflow tests.test_source_ingestion tests.test_source_manifest -q`，99 项通过。实时主页与一话复核另行记录；无 Provider、Notion 或真实翻译调用。
- 下一阶段：制定保留旧快照的 catalog/checkpoint 升级和续跑策略；增加显式正文刷新及 hash 差异；设计原始 HTML/等效可追溯表示及 AI/人类版本映射。后续仍需人工格式验收、88 话映射确认、真实 Provider 试译及独立 Notion/EPUB 验收。额度状态不可见，不声称达到阈值；续接时保留当前所有 dirty 文件，以最新 `git status` 为准。

## 2026-11-16 I4 消费端新鲜度门禁续接

- 当前 checkout 仍为 `main` / `a3813c3` 基线；工作区原有 Kakuyomu、审计和文档修改继续保留。不要暂存、提交、重置或覆盖用户已有改动，具体脏文件以最新 `git status --short --branch` 为准。
- 新增 `source_manifest.py::verify_current_normalized_source`，并接入 `pipeline.py` 的通用映射解析、翻译前与提交前复核，`scripts/align_chapters.py`，`scripts/apply_knowledge_review.py` 和 `epub_builder.py`。自动知识抽取通过 `get_chapter_specs` 使用同一门禁。raw 出现新版本、normalized 未重建时，这些入口会在处理前失败关闭。
- 合成夹具已补全 raw→normalized lineage；新增 EPUB raw-parent stale 回归。统一验证命令及限制见[开发与验证](../development.md#2026-11-16-i4-消费端新鲜度门禁扩展)：14 个相关模块退出码 0。最初知识抽取专测因旧 fixture 缺少 raw parent 失败；补齐有效 lineage 后统一回归通过。
- 门禁只识别并拒绝 stale 输入；没有自动重建 normalized/TM/知识/概要、持久化或传播 stale 状态，也未覆盖未绑定 `source_version_id` 的旧映射。验证使用 synthetic source 和 mock，没有调用 Provider、Notion、站点或真实 EPUB 阅读器。
- 下一步可直接执行：先按[路线图](../roadmap.md)继续规划 stale 状态持久化和显式重建/复核流程；并完成 88 话映射与来源格式人工验收。真实 Provider/Notion/EPUB 阅读器验收仍待后续。额度状态无法通过当前接口核实。

## 2026-11-17 全书知识翻译前门禁续接

- 当前 checkout 为 `main`，HEAD `e2fe611`；工作区含多份已修改的代码、测试和文档，所有改动均须保留。没有暂存、提交、重置或清理数据。
- 用户决策：指定书籍已获明确授权；用户是普通读者，要求从作品主页发现完整公开目录 URL，再通过普通 episode URL 获取全部公开话目；用户明确不需要官方澄清。用户补充 Kakuyomu 初始 HTML/Apollo 目录、正文节点与 ruby/旁点/空白结构的采集观察。此决定作为项目操作边界，不表述为平台背书、法律结论或公开分发许可。已有采集器沿用普通 URL、主页目录计数核验、robots 检查、1.5–3 秒串行间隔（默认 2 秒）及失败关闭行为。
- 来源实施已具有 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 完整公开 episode 发现、与 `publicEpisodeCount` 对账、episode URL 生成、续传、显式纯追加和正文刷新。历史 source-only 采集及 2026-11-16 刷新均覆盖各自主页声明的 88/88 话；最近刷新正文哈希 88 未变，manifest 268/268 文件通过校验。以上数据只覆盖公开主页声明范围；旧基线 catalog v1 不含章节分组，刷新不能证明新旧分组相同。具体来源证据见[开发与验证](../development.md#2026-11-16-kakuyomu-显式正文全量刷新)和[专题计划](../source-ingestion-and-publication-plan.md)。
- 本阶段实现显式全书抽取预算与来源 coverage、概要/术语审核器的 1000 来源支持，以及 Kakuyomu 正式编排入口的全书概要门禁。入口在创建 `TranslationPipeline` 前校验 approved summary 的全书覆盖和有序来源文件名/版本必须与本次完整 `CHAPTER_MAP` 一致；不满足时返回 `full_book_knowledge_required`。普通 `TranslationPipeline` 直接调用尚不受此门禁约束。
- E2E 初次运行捕获到 Kakuyomu 合成成功夹具缺少 approved whole-book summary；夹具已改为从该次合成归档版本生成 provenance，并通过现有 summary reviewer 发布 approved bundle。修复后 `.venv\Scripts\python.exe tests\run_tests.py` 运行 7 项全部通过，219.088 秒。定向 `.venv\Scripts\python.exe -m unittest tests.test_story_summary_review tests.test_kakuyomu_workflow -q` 运行 27 项全部通过；22 模块回归运行 423 项、419 项通过、4 项因当前 Windows symlink/FIFO 能力跳过。编译、两个相关 CLI `--help` 与 `git diff --check` 通过。验证只使用 synthetic fixture 和本地 mock；本轮没有访问 Kakuyomu、Notion、真实 Provider 或真实书籍正文。
- 已同步[全书知识预读输入模式](../development.md#2026-11-16-全书知识预读输入模式)、[项目现状](../project-status.md)、[路线图](../roadmap.md)、[知识治理](../knowledge-governance.md)、[决策索引](../decisions/README.md)和[原文采集与成果归档计划](../source-ingestion-and-publication-plan.md)。
- 下一步直接执行：先在 `docs/roadmap.md` 阶段 2 与 `docs/source-ingestion-and-publication-plan.md` I4 中拆出 tokenizer/context-aware 预算、分批抽取/跨章合并和结论级来源证据的可验证设计；确认 Kakuyomu 入口是否也要强制已审核全书 glossary bundle，以及通用流水线是否应采用相同门禁。然后补这些契约的 synthetic tests，再接入实际批准的 Provider/数据范围。其他优先待办仍有 88 话映射/正文格式人工验收、变化后下游 stale 持久化与传播、原始 HTML/等效表示、AI/人类双版本、EPUB 阅读器验收和 Notion 范围/恢复验证。
- 真实 Provider、Notion 及真实章节翻译未验证。当前运行 allowlist 默认空；JOJO/JYQF 授权仅覆盖各自职责内最小数据类别。五小时额度状态当前不可见，因此不声称达到任何阈值；按阶段记录续接，不将额度不可见写成阻塞。

## 2026-11-17 全书知识 token 分批续接

- 本阶段承接上节“全书知识翻译前门禁续接”，不重复调查 Kakuyomu 来源采集。用户确认试点书籍已获授权，要求普通读者路径：从作品主页发现全部公开 episode URL，再访问普通 episode URL；用户明确不需要官方澄清。该决策已落实于 D-13 和专题计划。当前采集器已实现主页 Apollo 目录、`publicEpisodeCount` 对账、ruby/旁点/空白保留及 1.5–3 秒串行请求；历史 live source-only 证据仍为主页声明的 88/88，不含未公开章节。页面结构与服务规则观察不是平台背书或法律结论。
- 已实现 `knowledge_batching.py` 与 `scripts/auto_extract_knowledge.py --full-book` 的本地 tokenizer 预算路径：需明确给出 tokenizer JSON、context/output/safety/message 参数和总字符上限；段落分批最多 500 段、100 次顺序 Provider 调用。批次响应校验严格 JSON、批内段落证据、术语来源命中和冲突译名；全批成功前不写最终三份草稿。provenance 记录 tokenizer 哈希、每批预算/消息/响应哈希、段落 coverage 和候选引用。汇总只是按源顺序收集分批候选，不是跨章模型综合；本地段落 ID 不是 HTML DOM `p` ID。
- Kakuyomu 编排原有 approved 全书概要门禁保持生效；批次概要引用和 token metadata 会经过 `story_summary_review.py` 校验和发布。没有扩展为术语 bundle 的强制门禁，也没有给直接调用通用 `TranslationPipeline` 增加新门禁。
- 本阶段验证：定向 75 项通过；23 个模块完整回归 431 项运行、427 项通过、4 项 Windows symlink/FIFO 能力跳过、0 项失败；`.venv\Scripts\python.exe tests\run_tests.py` 的 7 项本地 mock E2E 全部通过（220.525 秒）。修改文件 `py_compile`、知识抽取/概要审核 CLI `--help`、`pip check` 和 `git diff --check` 通过。E2E 输出中的 content-filter、段落契约和 Provider 错误堆栈是负向 fixture 预期；测试未请求真实 Kakuyomu、Provider 或 Notion。
- 最终记录：`py_compile`、知识抽取/概要审核 CLI `--help`、`pip check`、`git diff --check` 均通过；9 份改动 Markdown 的本地链接目标存在，检查未核对锚点。完整回归为 431 项运行、427 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 为 7 项通过（220.525 秒）。当前分支仍为 `main`、基线 HEAD `e2fe611`，本任务和先前阶段增量均保持未提交；不得清理或回滚。保留的实现/文档/test 修改以 `git status --short --branch` 为准。
- Provider 元数据检查已完成：当前本机没有 `.env` 或 JOJO/JYQF endpoint/key、allowlist、`PROOFREAD_MODEL` 配置，因此下一步不执行真实 Provider 请求。真实运行前按已确认的最小数据类别，在本机安全设置配置并核对模型对应 tokenizer/context 参数；届时记录实际模型、费用和人工候选审核，不把合成结果写成真实运行。独立可推进的代码工作仍包括来源变化后的 stale 状态持久化/传播；试点前还须人工核对 88 话映射及 ruby/旁点/空白格式。原始 HTML/等效表示、AI/人类双版本、EPUB 阅读器验收及 Notion 范围/恢复验证继续待办。

## 2026-11-17 试点输入复核续接

- 本节记录双版本路径确认前的输入检查。用户随后明确：归档应放项目 `SourceArchive`，AI 版放项目 `RAWs_AI`，外部 `生肉` 专用于人读版，外部 `熟肉` 是译文目录。迁移前曾以外部 `生肉` 作为来源根的命令不代表当前归档位置。
- 迁移前 `.venv\Scripts\python.exe scripts\validate_source_manifest.py --root <当时来源根> --manifest source_manifest.json` 返回 `schema_version=1 artifacts=268 files_verified=268`；相关 plan-only 为 `ready_for_review`、88 episodes、88 verified sources、0 issues。当前归档与路径验证见下方最新续接。
- 本地凭据检查只验证存在性：根 `.env` 不存在，Provider policy、JOJO/JYQF URL/key 和 `PROOFREAD_MODEL` 的 Process/User/Machine 环境变量均未设置；未读取密钥。真实 Provider/tokenizer 匹配试运行当前没有配置条件，不请求模型。后续可执行工作仍包括人工目录/格式验收、知识治理风险分层、更改后 stale 状态持久传播、原始 HTML/等效表示、EPUB 阅读器验证及 Notion 范围/恢复设计。
- 该历史检查点曾把第二处 `熟肉` 路径作为译文根记录；用户之后已确认该目录角色。本交接中不再将其列为待更正事项。

## 2026-11-17 AI/人类原文双版本与归档续接

- 用户确认 AI 版和人读版均以采集系统产生的同一份完整原文为输入；原文只采集一次，之后按识别效率与人类阅读体验分别选择清洗转换。AI profile `ai-efficient-v1` 将每段一个 U+3000 排版缩进移除、ruby 转为紧凑 `基字《读音》`、旁点转 Markdown 强调；human profile `human-reading-v1` 保留缩进，以 HTML Ruby/CSS `text-emphasis` 呈现振假名和旁点。两版各自记录共同 raw input version、normalized source version、输入 SHA-256、profile ID、输出 SHA-256。
- 版本归档位于 `projects\祝福のネトラレラ\SourceArchive`。AI 文件位于 `projects\祝福のネトラレラ\RAWs_AI`；人读文件位于 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉\<章节名>\<话名>.md`；译文目标是同书外部 `熟肉`。人读根有 88 个 Markdown + `SOURCE_MAP.json`；AI 根有 88 个 Markdown + `catalog.json`。人读文件名没有位置数字前缀，只有同章重名时才为消歧添加位置/ID。
- 导出命令：`.venv\Scripts\python.exe scripts\export_source_editions.py --source-root projects\祝福のネトラレラ\SourceArchive --catalog source_catalog.refresh-2026-11-16.json --manifest source_manifest.json --human-root <用户指定外部生肉目录> --ai-root projects\祝福のネトラレラ\RAWs_AI`；生成 88 话、3 组、178 个文件。输入 793,183 bytes；AI 输出 774,253 bytes；人读版输出 799,293 bytes。
- `.venv\Scripts\python.exe -m unittest tests.test_source_editions -v`：8 项合成测试通过。manifest 268/268 与 refresh catalog `--plan-only` 的 88/88 来源核验通过；88 对索引共同 raw input/version/hash、normalized source lineage 和 176 个输出 SHA-256 均核对通过，两版每话的输出 hash 不同。重复导出创建 0 个文件并复用 178 个一致文件。初次重跑因两个旧索引缺少新增 raw-input provenance 字段而按冲突规则停止；先验证 176 个章节 Markdown 与当前代码生成字节完全一致，再只刷新 `SOURCE_MAP.json` 与 `catalog.json`，来源归档和正文文件未改写。
- `py_compile`、导出器 CLI `--help`、`git diff --check`、manifest validator 与只读 plan-only 均通过；plan-only 为 `ready_for_review`、88 个已验证来源、0 问题且不含原文，网络/Provider/文件写入计数为 0。全量 README/`docs/` 本地 Markdown 链接与锚点检查覆盖 14 份文档、185 个链接，0 个缺失目标。人类逐段保真、章节/话名、Ruby/旁点/缩进在用户目标阅读器中的实际观感仍待人工验收。不得将书籍正文复制到日志或文档。当前额度不可核实，不作阈值判断。

## 2026-11-17 AI 清洗版翻译入口续接

- 当前工作树仍以 `main` / `e2fe611` 为基线，续接开始时已有多份代码、测试和文档未提交修改；全部保留，没有暂存、提交、清理或覆盖。项目原文路径职责：`projects\祝福のネトラレラ\SourceArchive` 是采集版本归档；项目 `RAWs_AI` 是 AI 清洗镜像；用户指定外部 `生肉` 是人类阅读版；同书外部 `熟肉` 是译文根。
- 已完成版本化导出：collector `source_manifest.json` 未改动，仍为 268/268；新增 `source_editions_manifest.json`，保留全部采集来源历史并追加 176 个 AI/人读 artifact，共 444/444 文件 hash 通过。首次增加 176 个不可变版本文件和清洗清单；已有 176 个镜像 Markdown 字节相同，只刷新两份索引。幂等重跑 `created_files=0`、`updated_files=0`、`reused_files=355`。
- 已完成 AI 翻译输入接入：`scripts/run_kakuyomu_workflow.py` 的 plan-only 和正式入口默认从 `--source-root` 同级 `RAWs_AI` 选择并读取 AI 正文；`--ai-edition-root` 仅覆盖该目录，`--edition-manifest` 指定归档中的清洗来源清单。AI 模式核验 AI 索引覆盖完整 catalog、catalog/source/edition 清单摘要、RAWs_AI 镜像与归档输出 hash、raw 父版本和 profile；plan 的逐话来源路径/版本用于归档 lineage 与校验，不能据此把归档目录当成翻译正文源。正式入口将 `CHAPTER_MAP` 与 `SOURCE_MANIFEST_PATH` 交给 pipeline 再验证。审批 plan 摘要绑定 profile、AI 索引根/路径/hash 与清洗清单路径/hash。采集器 `normalized_source` 仅通过显式 `--source-edition normalized_source` 选择。
- 本机只读 AI plan-only：`ready_for_review`，88/88 话均从 `RAWs_AI` 读取正文，且其对应 `ai-efficient-v1` 归档 provenance 有效；0 问题、0 网络/Provider/文件写入，JSON 不含正文。人读版镜像/归档 hash 88/88 匹配。未生成译文，也未调用 Provider。
- 默认 AI 输入回归后，以未指定 `--source-edition` 的 CLI 参数生成历史审阅计划：`projects\祝福のネトラレラ\SourceArchive\translation_plan_review_ai_default_2026-11-17.json`，摘要 `8a5679563c376f3ed9dcfdcd5115db77149cf77189c46c5e544eb215c4dcd4d7`。计划为 `ready_for_review`、88/88 `RAWs_AI` 正文及其归档 provenance 有效、0 问题，位置/episode ID/译文目标/TM key 唯一，目标均不存在；摘要重算一致，正文未包含，网络/Provider 调用均为 0。此历史计划后来因 catalog 追加及 AI 索引刷新而过期，并已迁出归档目录至 `Workflow/Plans/`；当前计划见本交接末尾的刷新记录。
- 默认 AI 选源增量后的当前定向验证：`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`，166 项通过，覆盖 AI 版默认输入、显式兼容覆盖、审批摘要、pipeline 来源版本及全书概要门禁。
- 之后进一步发现通用流水线在没有可选项目时会退回仓库根目录 `生肉/`；现已改为失败关闭，只有显式 JSON 配置能继续指定旧来源。`TestTestWorkspaceConfiguration` 23 项通过。修复后的当前 23 模块完整非 E2E 回归为 449 项运行、445 项通过、4 项 Windows 符号链接/FIFO 能力跳过、0 项失败，详见[开发与验证](../development.md#2026-11-17-默认-ai-清洗版翻译输入)。
- 仓库规定的 E2E runner：`.venv\Scripts\python.exe tests\run_tests.py`，7 项本地 mock E2E 通过，236.923 秒，退出码 0。请求只到 runner 启动的 loopback mock server；控制台内容拦截与段落契约错误来自预期负向 fixture，不表示真实 Provider 或本书翻译执行。
- AI 默认选源增量后的历史 E2E：`.venv\Scripts\python.exe tests\run_tests.py`，7 项本地 mock E2E 通过，229.541 秒，退出码 0。Kakuyomu fixture 验证采集后清洗、默认 AI 计划、对应 AI 版概要/计划审核和 mock 翻译；当时的断言仅比较相同字节，不能单独证明读取根目录。当前直接从 `RAWs_AI` 读取的路径契约由后续回归覆盖。其余安全拦截/段落契约失败日志是负向 fixture 预期。
- Python `py_compile`、编排器/导出器 CLI `--help`、`git diff --check` 及活动 Markdown 本地文件链接目标检查均通过；链接检查覆盖 README 和 `docs/` 共 14 份文档、184 个本地链接，不校验标题锚点。
- 下一步可直接执行：先按[当前计划审阅交接](2026-11-16-pilot-plan-review.md)人工核对上述默认 AI 版计划；用目标阅读器验收人读 Ruby、旁点、U+3000 和段落视觉效果；将 reviewed 全书概要绑定到 AI 版本清单内的版本 ID，并创建匹配此计划摘要的审批回执，再按已授权类别配置本地 Provider 并做受控单话翻译。以上均未由本续接完成。用户已明确作品授权与无需官方澄清，不能再把二者列为阻塞；Provider 配置、计划人工审阅和全文概要审核是独立运行条件。
- 本次续接已重新读取两条规划会话的近期页；项目资料仍以仓库和本交接为实施证据。无参数 `Config.load_config()` 在当前 checkout 选择试点项目的 `SourceArchive`/`source_editions_manifest.json`，构造 88 条 AI 归档映射；无项目且无显式 JSON 配置的路径已由合成回归确认停止。真实概要 bundle、计划人工审批和 Provider 配置仍未具备；没有生成译文或调用 Provider。
- 当前额度信息不可见，无法核实 5 小时额度比例；自然阶段已记录。书籍正文不得复制到日志/文档，当前工作树未提交状态须保留。

## 2026-11-17 采集后双版本自动清洗续接

- 用户再次明确翻译系统默认输入就是清洗系统产出的 AI 识别优化版。当前 Kakuyomu 编排器默认从 `RAWs_AI` 读取正文，并从不可变归档核验 provenance；本次进一步把完整采集后的 `normalized_source` 物化与双版本清洗连接起来：采集不完整时不导出，完整时先调用 `prepare_source_editions`，再生成默认 AI 计划。TM E2E 回归确认落库原文对应 `RAWs_AI` 输入；归档副本用于内容寻址与来源校验。
- `workflow_paths.json` schema v1 继续保留现有 `output_dir`，新增可选 `human_edition_root`；未设置时默认为项目 `生肉/`。试点本地忽略配置中的用户指定外部 `熟肉` 路径保留，并加入用户指定外部 `生肉` 人读根。实际项目只读解析得到 88 条带 AI 版本映射；人读根、译文根均匹配用户指定目录且互不重叠。该只读检查未写入书籍文件，也未调用 Provider。
- 索引有限刷新允许发现 catalog 路径变化和目录末尾追加；要求旧话目 ID/位置/标题/来源版本不变、旧章节保持顺序且只能扩展末章或追加新章、公开话数等于索引话目数。其他元数据/章节变更或现有 Markdown 不同均停止并保留原文件。
- 改动文件包括 `scripts/run_kakuyomu_workflow.py`、`source_editions.py`、`pipeline.py`、相关 workflow/source-edition/pipeline/E2E 测试和 README、架构、流程、路线图、开发记录及本交接；`projects/祝福のネトラレラ/workflow_paths.json` 为 gitignored 本地路径配置，已有译文根保留并新增人读根。其余在续接前已脏的 `.env.example`、知识模块、RAG、TM 和审批改动未回滚或清理。
- 本轮最终验证：`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`，177 项通过；`.venv\Scripts\python.exe tests\run_tests.py tests.test_e2e.E2ETestSuite.test_kakuyomu_catalog_runs_archive_to_versioned_mock_translation`，1 项通过。E2E 使用合成页面和本地 mock Provider，并验证 TM 原文与 AI 版归档逐段一致；未访问 Kakuyomu 或真实 Provider。相关源码/测试 `py_compile`、8 份本轮主要文档的本地链接目标检查、`git diff --check` 均通过。未运行全仓完整回归；额度信息不可见。
- 后续可直接执行：对完整来源完成一次受控的正式采集运行后，确认 `source_editions` 报告和默认 AI 计划中的 profile/版本；不要把既有试点目录作为写入验证目标，除非显式选择 catalog/hash 已核对且所有镜像文件字节一致的运行。再人工验收 88 话目录映射与人读 Ruby/旁点/缩进。真实 Provider 单话翻译仍要有符合当前授权类别的本地配置、当前 approved 全书概要和匹配计划审批回执；Provider/API 及人类阅读效果都未在本续接验证。

## 2026-11-17 Kakuyomu 编排自动记录下游新鲜度续接

- 本阶段从 I4 下游 stale 留档缺口继续。检查确认 AI 清洗归档版本也以 `normalized_source` kind 登记在合并清单中，并有独立 artifact ID 与当前 raw 父版本；TM、知识和概要审核器对该版本类型的判断与翻译输入契约相符，本阶段未修改这一契约。
- `scripts/run_kakuyomu_workflow.py` 现于计划生成后审计已存在的 TM、知识来源 provenance 和已审核 JSON 概要，并将翻译前快照追加到 `SourceArchive/`；成功翻译后再次生成翻译后快照。无下游文件时报告 `not_needed`，无法安全完成审计时报告 `unavailable`。快照 schema v2 绑定 source manifest 与消费者输入 SHA-256，不含正文；按内容寻址，重跑相同状态复用既有文件，状态变化追加新文件。任何快照都不改写消费者文件，也不取代其运行时门禁。
- 新增/更新实现：`scripts/snapshot_downstream_freshness.py`、`scripts/run_kakuyomu_workflow.py`、对应 freshness/workflow tests，以及开发记录、项目现状、路线图、翻译流程、I4 专题计划和本交接。所有工作树中其他未提交文件均保留；没有触碰真实书籍正文、译文或凭据，没有调用站点/Provider/Notion。
- 最终验证：`.venv\Scripts\python.exe -m unittest tests.test_downstream_freshness_snapshot tests.test_kakuyomu_workflow tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_translation_plan_approval tests.test_pipeline_contracts tests.test_source_pipeline_linkage tests.test_story_summary_review -q`，186 项通过；`.venv\Scripts\python.exe tests\run_tests.py`，7 项本地 mock E2E 通过（226.138 秒）。持久化测试覆盖内容寻址、同状态重跑不覆盖、状态变化追加；工作流测试覆盖消费者配置发现和前/后快照调用边界。相关源码/测试 `py_compile`、`git diff --check` 和 8 份主要文档本地链接检查均通过；链接检查不校验锚点。没有访问站点/真实 Provider/Notion。
- 范围限制：自动快照仅接在完整 `scripts/run_kakuyomu_workflow.py` 编排中；`scripts/ingest_kakuyomu_pages.py` 和本地导入 CLI 单独运行时不自动审计。快照是带版本的状态记录，不会把 stale 写回译文、TM、知识或概要，不会自动重建派生物；消费者运行时校验仍是实际阻断门禁。后续可继续将此审计接入直接采集入口，并设计明确消费新鲜度快照的跨工具状态登记/恢复契约。

## 2026-11-17 AI 默认翻译输入复核

- 用户再次明确：AI 版是清洗系统为 AI 识别效率生成的干净原文，也是翻译系统默认且实际使用的输入。此前“默认仍用 `normalized_source`”的说法与当前需求和代码不符，应以本节核验为准。
- 本检查点记录的实现曾由流水线直接读取 `SourceArchive/editions/ai-efficient-v1/` 中的不可变 AI 清洗归档版本；该运行时路径已按用户后续更正废止。当前 `RAWs_AI` 提供实际正文，归档只保留版本和来源 provenance 并用于校验；`--ai-edition-root` 覆盖 AI 索引/镜像根，只有显式 `--source-edition normalized_source` 才改用采集器规范化文本。
- 通用项目模式无参数时现仅在恰好一个非示例项目时自动发现；若有多个项目则在来源加载前失败，要求 `--project` 或 `TRANSLATOR_PROJECT`，避免按目录顺序把翻译输入接到错误书籍。回归同时验证 `example/` 不参与候选项目计数。
- 本阶段历史验证：Kakuyomu 计划测试、工作流测试、pipeline 契约和来源映射测试共 137 项通过；指定本地 mock E2E 1 项通过，并验证 TM 实际写入原文与当时计划选中的 AI 归档字节相同。因两份字节相同，该断言不是实际读取根目录的路径证据。没有调用 Kakuyomu 或真实 Provider。
- 仍需人工审核 88 话计划映射及 AI/人读清洗效果；试点缺少绑定完整 AI 映射的 `STORY_SUMMARY_reviewed.json` 和匹配审批回执，因此尚未执行真实 Provider 翻译。额度余量不可见，本次只记录实际验证结果，不推断额度阈值。

## 2026-11-17 独立 Kakuyomu 采集项目快照续接

- 背景：此前 `scripts/run_kakuyomu_workflow.py` 会在完整采集/清洗后自动追加翻译前与翻译后新鲜度快照；单独运行 `scripts/ingest_kakuyomu_pages.py` 仍没有项目级下游状态留档。用户已明确 AI 清洗版是默认翻译输入。两个原始规划会话已由本轮 `read_thread` 读取；更早分页和项目事实仍以当前仓库、历史记录和代码为证据。
- 已实现：独立 Kakuyomu CLI 新增显式 `--project <项目名>`。它要求 `--source-root`、`--output-root` 都精确指向选定项目的 `SourceArchive/`，并使用默认 `source_manifest.json`；错误路径在 adapter/网络前拒绝。采集返回后同步当前来源历史到 `source_editions_manifest.json`，保留既有 AI/人读 artifact，并追加 schema v2 内容寻址快照。AI 索引的来源 manifest、edition manifest、catalog 路径/哈希或目录映射过期时记为 `stale`；缺少 AI 索引时记为 `unverified`；AI 索引过期时 reviewed full-book summary 也标记 `stale`。
- 限制：独立采集项目模式不运行双版本清洗、不更新 `RAWs_AI/catalog.json`、不重建译文/知识/概要；默认翻译入口继续在 AI 索引过期时失败关闭。需要完整采集、AI/人读清洗与 AI 默认翻译计划时继续使用 `scripts/run_kakuyomu_workflow.py`。未传 `--project` 时采集 CLI 保持 source-only 行为。本阶段未访问真实站点、Provider、Notion 或真实书籍目录。
- 变更文件：`scripts/ingest_kakuyomu_pages.py`、`source_editions.py`、`tests/test_kakuyomu_page_source.py`、`tests/test_source_editions.py`，以及 `README.md`、项目现状、路线图、翻译流程、I4 专题方案、开发验证和本交接。原有其他工作区改动均保留，无提交、重置或清理。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_source_editions -q`，14 项通过；`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source -q`，33 项通过。覆盖来源历史合并/幂等、AI 索引 stale 检测、首次项目采集无索引快照和根路径错配前置拒绝。相关源码/测试 `py_compile` 与 `git diff --check` 通过。未运行全仓回归或 mock E2E。
- 续接时先运行快照/采集/清洗相关定向回归，检查 Markdown 链接与差异，再核对 `git status --short --branch`。当前工作区有大量本任务之前已存在的未提交改动；必须全部保留，不提交、不回滚、不清理。下一步可评估是否要在独立采集模式提供显式的后续清洗操作；若涉及旧话来源变化，先设计 index/AI edition 的版本刷新策略，不能覆盖旧 edition 或既有译文。

## 2026-11-17 Provider 阶段配置续接

- 完成配置入口：`Config.load_config` 支持 `INITIAL_MODEL`、`PROOFREAD_MODEL`、`STYLE_MODEL` 环境变量，优先于 JSON；单测验证覆盖关系。当前被忽略的根 `.env` 已写入 `TRANSLATOR_PROJECT`、三阶段 JOJO 主模型、JYQF 显式备用开关，以及两方仅接收 `source_text`、`translation_text`、`book_knowledge` 的 allowlist；未包含凭据或 `evaluation_samples`，也未授权 Gemini/Notion。
- 只读运行核验：配置加载选择试点项目的 88 条 AI 归档映射，显示主/备模型、回退开关及类别策略正确。Process/User/Machine 未设置 JOJO/JYQF key 或 `BASE_URL` 覆盖；代码候选默认 URL 未做连通性/协议验收；未调用 Provider。真实单话翻译仍需安全配置可用凭据、人工确认 88 话映射、为完整 AI 映射生成并审核概要、并创建匹配计划摘要的审批回执。
- 本阶段代码测试：`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts -q`，105 项通过。`git check-ignore .env` 确认本地运行配置被忽略；项目只读加载返回 88 条 AI 映射；无密钥 preflight 明确缺少 `JOJO_API_KEY`、`JYQF_API_KEY` 后停止，没有发出请求。测试尚未证明模型/端点真实兼容。
- 后续顺序：无密钥 Provider 预检已明确报告缺少 `JOJO_API_KEY`、`JYQF_API_KEY`；等待本地凭据配置后，先对代码候选默认 URL 做安全的非书籍连通性检查，再按路线图的审批门禁运行单话并记录质量/用量。不要从代码默认 URL 推断中转端点已连通或协议兼容。
- 终态只读复核：该历史检查点解析出 88 条 AI 版本映射，首条 archive provenance 位于 `SourceArchive/editions/ai-efficient-v1/` 并绑定 `source_version_id`；当时未分别核对实际正文根。当前 `RAWs_AI` 输入路径及本次独立验证记录见本交接更新内容。译文根解析为用户指定外部 `熟肉`。路线图当时已更正为“无 key/URL 环境覆盖，代码有候选默认 URL，连通性和协议未验收”。`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q`：121 项通过；预期故障注入日志不代表真实服务调用。历史 `git diff --check` 与 7 份活动文档链接目标检查通过；链接检查不校验锚点。工作区保留所有未提交更改、不暂存或提交；额度信息不可见，无法核实 5 小时额度比例。

## 2026-11-17 Kakuyomu 追加无变化复查续接

- 背景与决策：用户再次明确 AI 清洗版是翻译系统默认且实际使用的干净原文输入。当前 `scripts/run_kakuyomu_workflow.py` 默认 `source_edition="ai"`，通用项目 `pipeline.py` 从已校验的 `RAWs_AI` 索引建立版本绑定映射；只有 Kakuyomu CLI 显式传 `--source-edition normalized_source` 才改用采集器规范化文本。`--ai-edition-root` 仅覆盖 AI 索引根。两条原始规划会话此前已读取；当前实施状态以本仓库代码、测试和文档为准。
- 本阶段完成：通过同一 PowerShell 调用注入 `http_proxy`、`https_proxy`、`all_proxy` 到 `127.0.0.1:7897` 后，以 `scripts/ingest_kakuyomu_pages.py --project 祝福のネトラレラ` 对作品主页执行真实追加复查。结果发现/完成 88 话、追加 0、复用 88、待处理 0；没有新话，因此未请求 episode 正文。该结果只证明真实无变化续跑，不证明新增话正文抓取。
- 该运行快照报告 AI 索引尚未指向新 catalog。随后运行 `scripts/export_source_editions.py --refresh-indexes`：只更新 `RAWs_AI/catalog.json` 与人读 `SOURCE_MAP.json` 两个索引；0 章内容创建/更新，353 个一致文件复用，章节 Markdown 字节未改变。来源 `source_manifest.json` 为 268/268。刷新后默认参数 `--plan-only` 再核验 88/88 `RAWs_AI` 正文和对应归档 provenance，状态 `ready_for_review`、0 问题、0 网络/Provider 调用或文件写入；计划分别绑定 `RAWs_AI` 镜像输入路径和 `ai-efficient-v1` 归档 provenance。
- 下游快照记录 TM 有 19 条 `unindexed`，`STORY_SUMMARY_reviewed.json` 缺失并标记 `unverified`。本续接末尾再次只读检查确认该概要仍不存在、SourceArchive 下没有计划或审批文件、外部译文根仍为空；计划和审批回执分别归入 `Workflow/Plans/` 与 `Workflow/Approvals/`。这些不会改变 AI 默认输入契约，但在概要获审、匹配计划回执与凭据配置前仍不能执行真实翻译。真实 Provider 尚未调用、译文尚未生成。作品授权与无需官方澄清均由用户确认，不得重新列为阻塞。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_page_source tests.test_source_editions tests.test_downstream_freshness_snapshot -q`，56 项通过；另运行 `.venv\Scripts\python.exe -m unittest tests.test_kakuyomu_translation_plan tests.test_pipeline_contracts -q`，121 项通过。默认 AI `--plan-only` 真实项目复核为 88/88。最终 `git diff --check` 通过；README 与 6 份相关 Markdown 的本地链接目标检查通过，不校验锚点。
- 下一步：新增话目出现后，再用 append-only live 路径验证新增 episode 正文请求、版本归档、双版增量清洗和默认 AI 计划；在此之前保留“新增话 fetch 仅有合成测试”的限制。人工审阅 88 话映射及清洗效果，生成并审核 AI 版本绑定的完整概要，创建计划匹配回执，安全配置本地 Provider 后再进行受控单话翻译。
- 工作区与资产：checkout 仍为 `main` / HEAD `e2fe611258532c9f0bab3672eda52cf928102b1`，存在大量此前未提交改动，全部保留且未暂存、提交、回滚或清理。此次新增的忽略数据包括 `source_catalog.append-2026-11-17.json`、`source_checkpoint.append-2026-11-17.json` 和两份内容寻址 freshness snapshot。索引刷新只改变双版索引文件，不改章节 Markdown 或版本 archive。额度状态不可见，无法核实 5 小时额度阈值。

## 2026-11-17 追加 catalog 后刷新人工审阅计划

- 发现并处理：交接文档中的 `translation_plan_review_ai_default_2026-11-17.json` 摘要 `8a567956...` 仍绑定旧 `source_catalog.refresh-2026-11-16.json` 和旧 AI 索引，不能用于追加后的人工批准。旧文件保留为历史记录，没有覆盖或删除。
- 当时新建的审阅计划：`projects\祝福のネトラレラ\Workflow\Plans\translation_plan_review_ai_append_2026-11-17.json`，绑定 `source_catalog.append-2026-11-17.json` 和 AI 索引摘要 `7d45a2e2b1a88ccf334c2fda9c5ae9f4890ac3bc1d4bcda7c82de3b8093ef636`。计划状态 `ready_for_review`，88/88 `RAWs_AI` 正文与来源 provenance 有效，profile `ai-efficient-v1`，0 问题；无正文、0 网络请求、0 Provider 调用。
- 历史验证：`translation_plan_approval.load_translation_plan` 当时加载该计划并复算摘要成功，摘要 `1d7ae1cef2a318d79fccb9948b4e2de79799b9d087978922f08592a4b7a79283`。该计划曾被移入 `SourceArchive/`，后已迁至 `Workflow/Plans/`；未覆盖目标文件。`SourceArchive/` 不再保存计划或审批回执。
- 当时同步：文档曾将此计划作为当前审阅对象；本交接后续的“归档与 AI 正文输入边界”已记录 schema v2 新计划，并将本计划保留为历史文件。此前摘要不可用于当前回执。
- 当时下一步：人工检查该计划的 88 个 episode ID/位置/AI 来源版本/目标路径/TM key，并验收清洗结果。此待办已由顶部当前审阅计划更新；仍须取得新计划摘要的明确批准、审核全书概要并确认 Provider 配置，才可执行受控单话翻译。

## 2026-11-17 归档与 AI 正文输入边界

- 用户再次明确：翻译正文必须直接从项目 `RAWs_AI/` 读取；`SourceArchive/` 只保存来源及派生版本归档和来源校验材料。计划与审批是工作流记录，分别放入 `Workflow/Plans/` 与 `Workflow/Approvals/`。
- 已将 5 份误放于 `SourceArchive/` 的 `translation_plan_review*.json` 移至 `Workflow/Plans/`。迁移当时核对为归档目录内同名计划数 0、计划目录中 5；随后新增 schema v2 当前计划，现目录共 6 份。没有覆盖目标文件。计划和审批 CLI 均拒绝把工作流文件写入 `SourceArchive/`。
- 路径实现核查：`pipeline.py::_read_chapter_source_text` 和 Kakuyomu `_is_committed_translation` 使用 `read_verified_ai_edition_bytes` 从 AI 输入根读取正文；归档路径用于来源版本/hash/provenance 核验。定向合约回归通过。
- 验证：`.venv\Scripts\python.exe -m unittest tests.test_source_editions tests.test_kakuyomu_translation_plan tests.test_kakuyomu_workflow tests.test_translation_plan_approval tests.test_pipeline_contracts -q`，162 项通过；`git diff --check` 通过。测试使用本地合成数据，无 Kakuyomu 或真实 Provider 请求。
- 随后发现旧待审计划是 schema v1，现行校验器仅接受 schema v2；保留旧计划并生成 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-17.json`。当前摘要 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f` 已由现行 loader 复核，状态 `ready_for_review`，88/88 `RAWs_AI` 正文及对应归档 provenance 有效；0 网络、0 Provider、1 次计划 JSON 写入。当前归档内计划/回执均为 0，计划目录共 6 份。
- 当前未提交工作区的其他既有改动继续保留。下一步审阅当前 schema v2 计划中的 88 话映射并验收人读版显示；正式翻译仍需匹配审批回执、AI 版本绑定的 reviewed 全书概要和可用 Provider 配置。

## 2026-11-18 输出模式契约续接

- 断点基线：分支 `codex/translation-workflow-audit-20261117`，HEAD `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`。本次已重新读取“翻译工作流文档体系”“翻译工作流计划方案”“翻译工作流开发实施（旧）”三条引用会话；会话内容作为历史上下文，当前能力仍以此 checkout 的代码、测试及日期化验证为准。
- K1 输出入口边界已实现：未审核 `TranslationPipeline` 必须显式设置 `compatibility_draft` 或隔离测试用 `test_draft`；项目/Kakuyomu 活动 run 使用内部 `reviewed_run_draft`。显式 JSON 缺少兼容草稿标记、模式冲突或输出落入已识别正式译文根时，在创建 pipeline 前失败。兼容草稿没有正式发布资格；发布仍走带审核快照与回执的 create-only 发布器。迁移方式、路径边界及回滚影响见[开发与验证](../development.md#2026-11-18-兼容入口正式目录保护)。
- K2 增量已实现：正式项目 `TranslationPipeline` 在读取概要、术语或构造 `RAGEngine` 前拒绝 `ALLOW_UNREVIEWED_TM=true`，避免环境变量覆盖默认审核检索门禁；兼容 draft 仍可显式选择未审核 TM。对应测试确认拒绝发生在知识加载和 RAG 构造之前。该增量不实现审核者认证、风险分层、变更队列或语义质量证明。
- 关键变更位于 `pipeline.py`、`scripts/run_kakuyomu_workflow.py`、`scripts/publish_reviewed_run.py`、`translation_review.py` 及对应 pipeline、workflow、review、E2E 测试；工作流和验收矩阵更新于 `docs/end-to-end-workflow-target.md`、`docs/development.md`、`docs/project-status.md`、`docs/architecture.md`、`docs/translation-workflow.md`、`README.md` 等文档。
- 最新全量非 E2E 回归：589 项运行、585 项通过、4 项因 Windows 符号链接/FIFO 能力跳过、0 失败，42.855 秒；包含正式项目拒绝未审核 TM 检索、CLI 子进程拒绝未标记 JSON 和 hash-only 阶段报告持久化的测试。完整本地 mock E2E：7 项通过，214.208 秒，退出码 0。`git diff --check` 通过；本轮专用 `py_compile` 命令见续接记录。以上均不证明真实 Provider 可用或译文语义质量。
- 仍未闭合：K2 的知识审核身份可信度、语义质量与风险分层；K3 的“信、达、雅”独立审核职责、版本化报告和质量阈值；K4 的独立终审、有限返工版本链及耗尽后的升级责任；K5 的 88 话映射/双版本清洗人工验收，以及本地 Provider/tokenizer/预算匹配和受控首话验收。真实 Provider 尚未调用、没有真实审核概要或译文；不得用本地回执或 mock 结果替代这些验收。
- 下一步：先由有权限的审核者完成 88 话计划映射与 AI/人读清洗抽样/全量验收，并按当前来源版本生成、审核全书概要和术语表及匹配计划回执；实施者只读核验本地 Provider 配置是否完整（不输出密钥），再依既有授权和预算做单话试译。涉及质量阈值、自动返工上限、审核异常升级责任的部分需形成明确决策后再实现，不能猜定。
- 工作区状态：以上 tracked 文件仍处于未提交修改；受保护的未跟踪 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 保持原样，未读取或修改。本次未暂存、提交、推送、回滚或清理。

## 2026-11-18 K3 阶段审计轨迹续接

- 在 K1 输出模式和 K2 正式项目拒绝未审核 TM 检索的基础上，正式 `TranslationPipeline.run_chapter` 现在为每个实际进入模型处理的章节追加 `Workflow/Runs/<run_id>/StageReports/episode-<tm-key-sha256-prefix>.json`。报告只保存章节映射、来源/AI 输入哈希、阶段状态、输入/输出摘要、模型标识、失败类型和 attempts，不保存原文、译文、提示词或响应正文。
- 轨迹覆盖 `context`、`annotation`、`translation`、`proofreading_polishing` 和 `commit`；当前校对/润色仍是组合阶段，不能宣称三阶段独立审核职责、评分阈值或“信、达、雅”达标。失败报告尽力保留原异常；成功提交后报告持久化失败会让正式运行返回错误并保留草稿/TM，便于同一 run 继续核对。
- 续跑已提交但缺少报告的章节时，只追加一次 `recovered` 记录，不重新调用模型；已有报告必须匹配当前 run/章节，损坏、超大或错配文件会 fail closed 且不覆盖原文件。
- 新增 `tests.test_pipeline_contracts.TestParagraphContracts.test_formal_stage_report_is_hash_only_and_attempts_are_append_only`，验证正式路径报告落点、失败/成功尝试追加及正文不落盘。变更涉及 `pipeline.py`、`tests/test_pipeline_contracts.py`、`docs/architecture.md`、`docs/development.md`、`docs/end-to-end-workflow-target.md`、`docs/project-status.md`、`docs/translation-workflow.md`、`README.md` 和本交接。
- 验证命令：三个阶段报告契约测试（3 项通过）；`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_kakuyomu_workflow -q`（178 项通过）；全量非 E2E 591/587/4，42.100 秒；`.venv\Scripts\python.exe tests\run_tests.py`（7 项 mock E2E，209.081 秒，退出码 0）；受影响源码/测试逐文件 `py_compile`、`pip check` 和 `git diff --check` 通过。未调用真实 Provider、Kakuyomu、Notion 或部署服务。
- K3 仍未闭合：独立“信/达/雅”审核输出、语义质量规则和责任人、终审报告、有限返工版本链与人工升级均未实现。K5 的 88 话映射/清洗人工验收、真实 Provider/tokenizer/预算匹配和受控首话仍是后续前置。
- 当前增量单测已通过；续接时需重跑本节列出的定向、全量非 E2E 和 mock E2E 命令，并检查 `git diff --check`。不要读取或修改受保护的未跟踪 freshness JSON，不要提交、回滚或清理工作区。

## 2026-11-20 API 池终审角色续接

- 当前基线仍为 `codex/translation-workflow-audit-20261117` / `9374fa79376c13f72f06f1e7764d732012b1436a`，且工作树包含此前 API/embedding、K4 及文档工作。最新增量新增 API 池可选 `FINAL_REVIEW_MODEL`：含该角色新保存 profile 为 v3；无该角色仍为 v2；v1/v2 可读，v1 明确迁移仍落到 v2。终审与初译必须采用不同规范化 endpoint/model identity，并获准全部三类翻译数据。旧 profile、凭据、试点文件未读取或变更。
- 当前实现只包含配置、运行时清理和静态 preflight；没有审核调用器、AI 决策记录或自动发布。不同模型路由不证明语义独立。K4 的 issue registry 仅登记 code 和阶段，不足以推导“信达雅”判定或“连续两轮低收益”的数值/判定合同。
- 验证：API 池 22 项；API 池 + pipeline contracts + Kakuyomu workflow 176 项；非 E2E 总回归 730 项运行、726 通过、4 项 Windows symlink/FIFO 跳过；mock E2E 7 项通过、205.929 秒。相关 Python `py_compile`、9 份 Markdown 相对链接目标与 `git diff --check` 通过。均未调用真实 Provider。细节见[开发记录](../development.md#2026-11-20-api-池可选终审角色)。
- 下一阶段从设计并实现审核执行器开始：将 reviewer 结构化结果绑定 run、episode、source/bundle、候选字节、阶段策略和修订链；保留原候选并失败关闭；重试限定默认 2 次且沿用现有 `resolve_translation_review.py` 预算仲裁；只有已有发布门禁接受的 `passed` 链可继续。先验证 mock 成功/失败/异常/重复执行和发布拒绝，再核对真实 endpoint/Key 的配置状态（不输出秘密）；获准样本与 Provider 的真实执行状态仍须独立记录。
- 继续工作前执行 `git status --short --branch`、定向读取现有 `translation_review.py`、`translation_review_state.py`、`scripts/record_translation_review_decision.py`、`scripts/resolve_translation_review.py` 与相关测试；不要读取 `downstream_freshness_ai_index_refreshed_2026-11-17.json`、本机 API profile、凭据或不必要的书籍正文。保留全部既存修改，不提交、重置或清理。

## 2026-11-20 K4 工作流与试点门禁复核

- 当前基线仍为 `codex/translation-workflow-audit-20261117` / `9374fa79376c13f72f06f1e7764d732012b1436a`。本次开始时工作区已有 23 个 tracked 修改和 15 个 untracked 项；均为此前工作，未覆盖或清理。受保护的 `downstream_freshness_ai_index_refreshed_2026-11-17.json` 未读取或修改。
- 较早的“API 池终审角色续接”将终审执行器列作下一阶段，现已过时。当前源码已有 `ai_translation_review.py`、`ai_translation_rework.py`、`ai_translation_workflow.py` 及对应 CLI：终审双次结构化评估；失败时按 finding 对齐段落进行有限返工；预算耗尽由人工仲裁；通过后复用 create-only 发布器。终审、返工和总工作流共用单话异步锁，跨进程互斥及进程退出后的锁恢复有测试。
- 当前代码验证证据见[项目现状](../project-status.md#2026-11-20-k4-自动返工与复审)：综合定向回归 264 项通过；完整非 E2E 动态发现 753 项运行、749 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（213.512 秒）。验证用合成 assessor/generator；未调用真实 Provider、未运行试点正文。本次只改文档，没有重跑测试；`git diff --check` 与本地 Markdown 链接检查在本次修改后复核。
- 只读复核当前试点元数据：计划 `translation_plan_review_ai_raw_html_schema2_2026-11-19.json` 状态 `ready_for_review`、88 话；对应人审模板 88 话，`mapping_decision`、`ai_edition_decision`、`human_edition_decision` 均为 pending 88。`Workflow/Approvals/` 目录不存在，`Knowledge/STORY_SUMMARY_reviewed.json` 不存在。读取仅统计状态与数量，未显示或复制话目标题、正文或摘要。
- 审批目录疑点已从代码核实为非阻塞：`write_new_child_text` 会创建父目录，审批 CLI 只在完整计划 SHA-256 确认后调用 create-only 写入。错误摘要不写回执；本次未创建目录或回执。
- 下一步是由有权限的审核者完成 88 话映射及 AI/人读版决定，并按[翻译流程](../translation-workflow.md)的审批 CLI 生成与当前计划匹配的回执；随后生成并审核绑定当前 AI bundle 的全书概要/术语，再只读核验 Provider 配置与模型/tokenizer/预算，最后按现有授权做单话受控试译。以上人审与真实服务前置未完成前，不启动真实 Provider 或声称端到端试点通过。
- K4 的代码阶段已完成当前合成验证；K5 试点阶段仍未完成。项目是 CLI，没有需要启动的开发服务。续接时先运行 `git status --short --branch`，保护现有混合工作区；测试命令与文档检查入口见[开发与验证](../development.md)，不要读取受保护 freshness JSON、本机凭据或不必要的章节正文。

## 2026-11-20 K4 发布快照前进程终止恢复续接

- 基线仍为分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。本轮只增补合成恢复测试和当前状态文档，没有修改生产代码；保留既有混合工作树及受保护 freshness JSON，未读取书籍正文、本机 API profile 或凭据。
- 新增 `tests.test_translation_review.TranslationReviewTests.test_ai_pass_recovers_after_process_termination_before_publication_snapshot`。子进程先在发布快照写入边界持锁等待，并以 flush/fsync 后原子改名写检查点；父进程验证检查点 PID/边界、passed 决策链、报告摘要与 reviewer 身份、AI 发布审核记录、译文准确字节以及 run 仍为 running 且快照/回执不存在，随后才终止子进程。
- 新调用经现有 episode 文件锁恢复，复用审核结果而不调用 assessor，创建审核快照/发布回执并将 run 置为 published；决策链仍只有一条。第二次重开后状态仍为 published，run 与译文根下全部文件字节保持不变。它证明此处的合成用户态进程终止窗口，不证明内核崩溃、断电、介质写入顺序或真实 Provider 响应丢失。
- 验证：单项进程终止测试 1 项通过（2.704 秒）；四模块定向回归 266 项通过（32.791 秒）；完整非 E2E 动态发现 31 个模块、755 项运行、751 项通过、4 项因 Windows symlink/FIFO 能力跳过（75.385 秒）；`.venv\Scripts\python.exe -m py_compile tests\test_translation_review.py`、10 份活动 Markdown 的 285 个本地链接目标和 `git diff --check` 通过。本轮只改测试/文档，未重跑 mock E2E；最近同一生产代码的本地 mock E2E 为 7 项通过、203.287 秒，未调用真实 Provider。
- K5 门槛没有变化：88 话 mapping/AI edition/human edition 审批各仍需人类完成；计划审批回执、reviewed 全书概要/术语、Provider endpoint/model/tokenizer/预算检查与监督单话试译仍未通过。继续前检查状态并保护本地数据；不要提交、重置、清理、调用真实 Provider 或读取受保护 freshness JSON。

## 2026-11-20 K4 回执落盘后状态恢复续接

- 基线仍为分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。本轮只增加合成测试及文档记录；未改生产代码，保留混合工作区和受保护 freshness JSON，未读取书籍正文、API profile 或凭据。
- 新增 `tests.test_translation_review.TranslationReviewTests.test_ai_pass_recovers_after_process_termination_before_run_state_published`。子进程在审核快照、create-only 发布回执和译文都已持久化后、更新 `run_state.json` 前停住。父进程认证检查点 PID/边界、通过决策链、AI 报告摘要/审核身份、发布快照与回执绑定、译文精确字节、来源身份有效和 run 仍是 `running`，再终止子进程。
- 恢复调用重新取得 episode 文件锁，复用已通过决策和审核记录；发布器确认译文、快照与回执已存在且一致，不重写它们，只把 run 状态推进至 `published`。决策链仍只有一项；第二次重开时 run、快照、回执及译文字节保持不变。该测试证明指定合成用户态进程终止窗口，不证明内核崩溃、断电、介质持久性或真实 Provider 响应丢失。
- 验证：该边界单测 1 项通过（2.647 秒）；四模块定向回归 267 项通过（34.355 秒）；完整非 E2E 动态发现 31 个模块、756 项运行、752 项通过、4 项因 Windows symlink/FIFO 能力跳过（78.501 秒）。本轮未重跑 mock E2E；最近同一生产代码的本地 mock E2E 为 7 项通过（203.287 秒），未调用真实 Provider。`py_compile`、活动文档链接检查与 `git diff --check` 应在续接收尾复核。
- K5 仍待有权限的人类完成 88 话映射/AI 版/人读版决策、匹配计划回执及 reviewed 全书概要/术语审核；之后由凭据所有者核验 Provider endpoint/model/tokenizer/预算并执行获准的单话试译。不要读取受保护 JSON、本机凭据或不必要的章节正文。

## 2026-11-20 K4 发布快照异常恢复续接

- 当前基线仍为 `codex/translation-workflow-audit-20261117` / `9374fa79376c13f72f06f1e7764d732012b1436a`。本轮保留所有原有混合修改；新增测试及文档差异未暂存或提交。受保护 freshness JSON、小说正文、本机 API profile 和凭据均未读取。
- 新增 `tests.test_translation_review.TranslationReviewTests.test_ai_pass_recovers_after_publication_snapshot_write_failure`：模拟 AI 终审已持久化 `passed` 决策、正式译文已写入后，审核快照写入抛出 `OSError`。首次运行保留决定/译文但没有发布快照与回执；同一 run 重试不再次调用 reviewer，复用绑定的 AI 审核快照并补齐发布快照、回执和 `published` run 状态。该异常注入不等同于进程硬杀、内核崩溃或断电持久性证明。
- 验证：单项故障恢复测试通过；`.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state tests.test_pipeline_contracts tests.test_api_pool -q` 为 265 项通过；完整非 E2E 动态发现 754 项运行、750 项通过、4 项 Windows symlink/FIFO 能力跳过；`.venv\Scripts\python.exe tests\run_tests.py` 的本地 mock E2E 7 项通过（203.287 秒）。未调用真实 Provider。
- 当前只读试点复核：计划仍为 `ready_for_review`、88 话；`mapping_decision`、`ai_edition_decision`、`human_edition_decision` 各 88 项 pending；`Workflow/Approvals/` 和 `Knowledge/STORY_SUMMARY_reviewed.json` 仍不存在。只统计状态和数量，未输出话目、正文或哈希。
- 下一步仍由有权限的审核者完成三类 88 话审阅与匹配计划批准，再审核当前 AI bundle 绑定的全书知识；此后由凭据所有者核验 endpoint/model/tokenizer/预算并执行获准单话试译。代码侧可继续补充进程中断窗口的故障注入，但不以异常注入替代真实试点验收。

## 2026-11-20 K4 终审逐次评估持久化续接

- 基线：分支 `codex/translation-workflow-audit-20261117`、HEAD `9374fa79376c13f72f06f1e7764d732012b1436a`。继续在混合工作区增量修改；未读取或改动受保护 freshness JSON、书籍正文、本机 API profile/凭据；未暂存、提交、重置或清理。
- 变更：`ai_translation_review.py` 为每个通过结构校验的评估写入原子、create-only、内容受限 sidecar，绑定 run/work/episode、source、candidate、policy、reviewer route 和评估序号。重试验证并复用已有评估，只请求缺失的一次；最终报告与决策 schema 保持不变。`tests/test_translation_review.py` 新增两个测试：单次评估已落盘后认证并终止子进程，验证恢复只调用评估 2 且发布后重开字节稳定；修改 sidecar 身份后验证 Provider 不会被调用且恢复失败关闭。
- 验证：新增两项定向用例 2/2 通过（2.926 秒）；`.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state -q`：106 项通过（33.855 秒）；动态发现全部非 E2E：758 项运行、754 项通过、4 项因 Windows symlink/FIFO 能力跳过（82.547 秒）；`.venv\Scripts\python.exe tests\run_tests.py`：本地 loopback mock E2E 7 项通过（216.520 秒，退出码 0）；`.venv\Scripts\python.exe -m py_compile ai_translation_review.py tests\test_translation_review.py` 及 `git diff --check` 通过。活动 Markdown 本地目标复核在本记录追加后执行。合成测试未调用真实 Provider；E2E 负向 fixture 的 content filter 和段落错配日志为预期结果。
- 剩余风险：Provider 已返回、对应 sidecar 尚未原子落盘时仍可能重复该次调用并计费；本地代码无法代替 Provider 幂等键消除该窗口。测试覆盖指定用户态进程终止点，不证明内核崩溃或断电持久性。
- 回滚与续接：不迁移数据库，不改候选、报告、决定、译文或 TM；若回滚代码，保留新建的 `AIReviews/<episode_id>/assessment-*.json` 证据。K4 本地合成恢复路径已通过；整体工作流仍停在 K5 人工前置：有权限的人审 88 话映射和双版本并创建计划回执，审核 reviewed 全书知识；随后由凭据所有者核验 Provider 授权/路由/预算并执行获准的一话试译及人工质量验收。项目是本地 CLI，无 Web 服务部署步骤。
