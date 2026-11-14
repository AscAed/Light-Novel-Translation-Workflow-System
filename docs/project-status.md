# 项目现状

> 状态基准：2026-11-14。审查分支 `codex/source-ingestion-audit-20261114` 起点为 `e5c315452fdef7efa71b06adabbe3fc8ccaa23f9`，与 `origin/main` 一致；该提交包含已合并的 PR #56。本轮审查 I1/I2 原型、补充修复与文档，最终版本状态见[续接交接](handoffs/2026-11-14-translation-workflow.md)。已有主流程包括本地响应契约、章节格式门禁、Provider 路由/超时与数据授权检查、知识候选来源记录、TM 来源核验及审计 CLI 输出净化。来源原型只使用合成适配器/临时目录，未连接网络或读取作品内容。验证证据见[开发与验证](development.md)。

## 已实现

- `pipeline.py`：Python CLI；按章节读取 Markdown，构建上下文，依次执行上下文标注、初译、校对、润色，并写入译文和翻译记忆。
- `已实现` 响应契约：标注对象与源段落保真校验；初译必需字段/段落数组检查；校对 schema 不合格时保留上一版；反思重译和润色响应异常时回退；三种生产提示词的输出字段与调用端 schema 对齐。
- `部分实现` Provider 路由：`get_primary_provider_route` 集中管理现有 Sakura/Qwen 与 DeepSeek 的 URL/Key 映射，供请求和启动 Key 检查共用；未知、空白或首尾带空格的模型名会在流水线读取章节及创建客户端前拒绝，避免静默落到 DeepSeek。OpenAI-compatible base URL 拒绝无效协议/主机/端口、URL 内凭据/查询/片段及非 loopback HTTP；loopback HTTP 保留用于本地服务，客户端关闭自动重定向以避免重定向转发认证信息，端点需提供规范 URL。修复了 `CODING_PLAN_BASE_URL` 配置为 loopback 地址或带显式端口时意外覆盖已选端点的问题，只有 E2E 的 `MOCK_SERVER_PORT` 会显式覆盖为本地 mock。`PROVIDER_DATA_POLICY` 已按 Provider/数据类别默认拒绝远端书籍数据，通用 Provider 抽象、`CODING_PLAN_*` 支持和真实端点验收仍未实现。
- `rag_engine.py`：翻译记忆向量检索、术语匹配、分章指导检索及记忆写入。
- `scripts/align_chapters.py`：双语章节段落对齐、对齐结果向量化并写入翻译记忆。
- `scripts/validate_tm_provenance.py`：只读核对 TM 来源索引的文件哈希、段落引用和词对内容；不修改 TM，也不判断译文质量或审核状态。
- `scripts/auto_extract_knowledge.py`：从最多前三章生成术语表、概要及来源清单草稿；响应会先做结构、必填字段和冲突译名校验，草稿采用排他新建。来源清单记录实际输入范围/哈希及可精确匹配术语的章节段落序号，并最后写入 `artifact_status: complete` 标记；写入失败可能遗留部分文件，缺少有效标记时不得视为完整候选。它不能证明概要逐句有据，且尚无审核状态或发布流程。
- `prompts/`：初译、逻辑校对和文风润色提示词。
- `tests/`：标准库 `unittest` 测试、独立 mock HTTP 服务、RAG/对齐/路径安全测试。
- `projects/example/`：小型示例原文、译文和书籍知识样例；不代表实际运行产物或真实书籍数据。

## 部分实现与差距

- `部分实现` 多 Agent：当前由单进程按阶段调用多个模型端点；未发现独立 Agent 运行时、队列、调度器、持久化任务状态或用户交互界面。
- `部分实现` 翻译记忆：使用 JSON 文件和嵌入向量并自动写入；新的流水线/对齐写入附带可选 `source_provenance`，记录源文/译文哈希和段落映射，可用只读脚本核验文件和词对是否仍匹配。历史条目不自动补录；审核、版本和冲突治理仍未实现。译文先写、TM 后原子写入；TM 失败时译文保留，重跑仅在非空译文缺少 TM 记录时警告，不自动恢复。
- `部分实现` 章节格式保护：已验证本地响应 schema、非空文本/段落数及引号字符序列检查；格式门禁失败不写译文或 TM。其他格式需依据获准样本进一步定义，术语和语义质量仍未成为统一硬门禁。
- `部分实现` 章节发现：未配置 `CHAPTER_MAP` 时，流水线与对齐器只扫描配置目录第一层，暂不递归；项目名模式遇到 `生肉/` 或 `熟肉/` 子目录会拒绝自动选择首项，要求显式配置路径。空扫描会失败，对齐器在没有任何可处理译文时也会以非零状态退出，不会把空运行报告为成功或保存 TM。多卷映射的通用契约已实现；真实章节和输出映射仍需核验。
- `已实现` 显式多卷映射契约：JSON `CHAPTER_MAP` 按用户给出的顺序记录 `raw_file`、`translation_file`、`tm_key`；流水线、对齐、知识抽取和来源审计共用它，并拒绝路径穿越、符号链接、重复路径/键及缺失源文件。旧平铺扫描不变。上一项所述 D-12 未决仅指真实书籍的映射条目、章节对应和缺失译文处理；这些内容尚未核定，未在忽略项目中启用。
- `部分实现` API 容错：Gemini 故障转移默认关闭；显式开启后仅连接/超时、HTTP 408/429 和 5xx 触发回退。鉴权/请求错误、响应 schema 错误及内容拦截不回退；通用 Provider 抽象、逐阶段错误策略和真实端点验证未完成。
- `部分实现` 运行日志隐私：校对严重意见不再输出；RAG embedding 失败日志、知识抽取和章节对齐 CLI 的已处理错误不输出异常正文；TM 来源审计 CLI 会转义不可打印字符，且拒绝空白 `TEST_WORKSPACE_DIR`。第三方 SDK、测试 runner 和其他外围工具仍可能产生自己的诊断输出，未做全局日志脱敏保证。
- `部分实现` 路径边界：章节映射路径拒绝绝对路径、路径穿越和符号链接，译文/草稿采用排他新建，TM 采用原子替换；显式配置根目录仍由操作者负责，平台级并发链接竞态未完全封闭。
- `部分实现` 配置：支持环境变量、项目目录及 JSON 配置路径；`API_TIMEOUT` 默认 10 秒并拒绝非有限或非正数，覆盖 OpenAI-compatible 聊天、Gemini 生成、RAG 和章节对齐 embedding；远端数据按 `PROVIDER_DATA_POLICY` 最小类别授权，默认拒绝。有基础 `requirements.txt`，但依赖未锁定，也没有完整部署配置。
- `部分实现` 来源版本清单：`source_manifest.py` 提供本地 JSON schema v1、版本追加、SHA-256/相对路径语法和父版本图校验；图校验使用迭代算法，不受 Python 调用栈深度限制。`verify_manifest_files` 使用显式根目录和仓库现有安全路径解析，只读取清单列出的文件并核对原始字节哈希；`scripts/validate_source_manifest.py` 提供只读 CLI。目录扫描、生命周期状态/迁移、清单与流水线集成、采集和外部同步均未实现。
- `部分实现` 来源接入核心：`source_ingestion.py` 定义注入式 `SourceAdapter` 和显式路径 `LocalFileAdapter`，`scripts/ingest_local_sources.py` 按 JSON catalog 只读归档指定本地文件。checkpoint v4 同时绑定适配器 `source_fingerprint` 和目标 manifest 相对路径；本地指纹包含 catalog 顺序、元数据、相对路径和源文件 SHA-256，读取时复核文件未变化。快照或目标不匹配均拒绝恢复；缺少目标身份的旧 checkpoint 仅在无已完成条目时迁移，未完成 v1/v2 因缺少来源指纹拒绝恢复。artifact ID 由作品、类型和章节标识的规范化元组派生。source_ref 写入 episode metadata。无 HTTP 客户端、具体站点解析器、缺失/删除差分或 live 采集；未接入流水线。

## 计划

- `计划` 建立书籍级知识审核、候选/已批准状态及可追踪写入。
- `计划` 明确各阶段输入/输出契约、最终质量门禁和可复现验收。
- `计划` 评估扩展到多语言和多文本类型；当前实现聚焦日译中轻小说，不可据长期方向宣称已支持通用翻译。

## 未知与待验证

- `未知` Sakura 服务实际部署位置、模型权重/版本和运行参数。代码默认 URL 为 `http://127.0.0.1:6006/v1`；2026-11-14 本次 `Test-NetConnection` 复核该端口不可达，其他地址未探测。
- `未知` DeepSeek/Gemini 凭据是否已轮换、账户权限、配额、API 兼容性和真实端到端翻译质量。本次未调用外部 API。
- `未知` 除当前工作区外是否存在云端部署、自动化任务或用户界面；仓库未找到相关部署清单或 CI 工作流。
- `未知` 数据位置、章节完整性及其与授权作品的对应关系：已定位被 `.gitignore` 排除的 `projects/祝福のネトラレラ`；有 48 个原文 Markdown，其中 39 个文件名匹配“第 N 话”；译文目录有 19 个 Markdown，其中 18 个章节与原文同名，另有 EPUB `README.md`。原文分在两个卷目录，译文分在正文和 EPUB 两个目录，根目录没有 Markdown。此前项目模式按各自 `os.listdir` 首项选子目录，可能只覆盖一个原文卷或选择 EPUB；现已改为遇到子目录时拒绝自动选择，需通过 JSON 明确路径。TM 有 19 个章节键，均对应原文，其中 `第19話.md` 没有同名译文；其余 18 组递归同名章节经现有启发式映射后，仍有 31 个原文段落和 1 个译文段落未映射。只读来源审计返回 19 个 `unindexed`、退出码 2；以上数据与用户已确认获得授权的试点作品是否为同一数据集尚未核对。作品授权已由用户明确确认；Kakuyomu 自动化访问方式及 Provider/Notion 的逐目标范围见专题方案。
- `未知` `TEST_READY.md` 中历史“71”计数与当前测试的对应关系；最近一次测试报告按实际 unittest 方法和命令记录，不沿用该计数。
- `未知` 不同操作系统对无符号链接打开标志和目录并发修改的实际保证；最近一次回归测试状态见[开发与验证](development.md)。

## 历史需求差异

- `ORIGINAL_REQUEST.md`（2026-06-08）要求 Provider 内容拦截后将请求转发到 Gemini 并设置 `BLOCK_NONE`；当前代码和测试将 Provider 内容拦截视为终止状态。本次自检保留该终止边界并移除了显式放宽的安全设置。
- 原始需求列出 `text-embedding-004`，当前代码请求 `gemini-embedding-2`。2026-11-13 的历史复核未能访问真实 Gemini 端点，模型 ID 与向量兼容性均待确认。
- `.agents/` 中的旧计划、handoff 和测试结论来自不同工作阶段，含旧路径和过期“71 项”状态，只作历史记录，不作为当前运行、部署或验收证据。

## 最近一次验证记录

2026-11-14 审计续接（基线 `e5c315452fdef7efa71b06adabbe3fc8ccaa23f9` 加当前工作树）：十模块定向单测 174 项运行、170 项通过、4 项跳过、0 项失败；管理员 PowerShell 的路径安全模块运行 11 项、10 项通过、1 项因 Windows 不支持 FIFO 跳过。用户另行提供的普通 PowerShell 输出为 9 项运行、3 项跳过，与当前模块 11 个测试方法不是同一测试数量，单独保留。来源原型/manifest/CLI 测试 38 项通过；本地 mock E2E 4 项通过（324.564 秒）；`compileall` 和 `pip check` 通过。均未验证真实 Provider、作品内容或部署。Codex Security Standard 报告针对精确基线 `e5c3154`，覆盖为 partial，审阅 31/121 个跟踪文件并报告两项低严重性发现；当前工作树已有独立修复和回归。详见[开发与验证](development.md)、[安全记录](security-notes.md)及[续接交接](handoffs/2026-11-14-translation-workflow.md)。

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
