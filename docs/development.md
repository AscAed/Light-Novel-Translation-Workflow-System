# 开发与验证

## 2026-11-16 JOJO→JYQF 显式回退与当前验证

- 基线：当前 `main` HEAD 为 `ba9979ed272152ee2ce3039306dfc685b4476374`，PR #67 的 JOJO→JYQF 回退已合并。本节完整回归记录来自 PR #67 验证阶段；本轮在合并后的 HEAD 单独复跑安全路径模块，结果见下方。根目录 `.env` 不存在，当前进程未发现 Provider allowlist、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`；未调用真实 Provider、Notion 或部署服务。
- 新增 `ENABLE_JYQF_FALLBACK`，默认关闭，可由环境变量或 JSON 配置显式打开。只有主模型路由到 JOJO 的阶段才可回退到固定 `deepseek-v4.1-flash`；仅连接错误、HTTP 408/429/5xx 触发。鉴权、400/403/404、响应契约错误和内容拦截不回退，JYQF 请求失败后直接返回错误，不级联到 Gemini。
- 开始章节扫描前，启动预检会逐 JOJO 阶段核验 JYQF URL、同阶段数据类别授权和远端凭据；本地 loopback 依项目的本地端点规则处理。若同时启用 Gemini 回退，只有运行时仍会回退到 Gemini 的阶段才检查该阶段的 Gemini 数据授权；JYQF 已接管的 JOJO 阶段不要求 Gemini 授权。实际创建备用 Provider 客户端前再次核验类别授权。备用调用可能产生额外费用；每次仅调用一次备用，不自动重试。真实模型 ID、端点协议与费用仍未验证。
- PR #67 自动审查发现三项问题：JOJO 已由 JYQF 接管时仍要求 Gemini 阶段授权、JYQF SDK 客户端会自动重试、README 将未覆盖回退路径的 mock E2E 写成该回退的验证证据。现已修正预检、只对 JYQF 备用客户端设置 `max_retries=0`，并将 README 限定为契约单测覆盖。回归覆盖“樱花初译、JOJO 校对/润色、JYQF 接管 JOJO 失败、Gemini 仅获初译所需类别”及备用 SDK 重试参数。`.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -q`：38 项通过；`tests.test_pipeline_contracts`：91 项通过。
- 全部非 E2E：PR #67 验证阶段对 21 个 `tests.test_*.py` 模块共运行 380 项、376 项通过、4 项跳过、0 项失败。普通权限下 3 项 symlink 用例因 `WinError 1314` 跳过，1 项 FIFO 用例因 Windows 不提供 `os.mkfifo` 跳过；此前获准的管理员 PowerShell 复跑该模块为 11 项运行、10 项通过、仅 FIFO 用例跳过，3 项 symlink 用例通过。本轮在当前 `ba9979e` HEAD 运行 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -v`：11 项运行、7 项通过、4 项跳过；详细输出确认 3 项因当前执行账户缺少符号链接权限而跳过，1 项因 Windows 不提供 `os.mkfifo` 跳过。用户本次提供的 `-q` 汇总为 9 项、3 项跳过，未列测试名；由于当前源码定义 11 个测试方法，该结果不能归属到当前 HEAD。
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
- 项目名模式与显式 `--config` JSON 模式均由 `Config.load_config` 处理。项目名模式只接受 `生肉/`、`熟肉/` 直接包含章节文件的布局；若这两个目录含子目录，程序拒绝按枚举顺序自动选择，并要求 JSON 显式设置 `RAW_DIR`、`OUTPUT_DIR`。这避免把任意卷目录或 EPUB 目录当作工作路径。
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
  "OUTPUT_DIR": "D:/books/example/熟肉",
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
- 用户另行提供的 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal -q` 输出为 9 项、3 项跳过、整体 `OK`；未附 commit SHA 或逐项 skip reason，不与当前工作区的 11 项/4 项测试快照合并计数。当前执行策略不开放提权入口，因此未提升权限重跑符号链接用例。
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
- 作品授权已按用户 2026-11-14 明确确认记录，不再列作阻塞。Kakuyomu 官方规则核查见[专题方案](source-ingestion-and-publication-plan.md#kakuyomu-i0-规则核查-2026-11-14)：具体自动化接入方式仍未知，因此 I2 仅提供本地显式文件导入与平台无关核心，不实现 Kakuyomu live 适配器。

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
