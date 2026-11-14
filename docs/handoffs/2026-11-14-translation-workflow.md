# 翻译工作流续接交接

> 状态基准：2026-11-14。目标仍在进行；本文件记录本轮可复用证据和下一步，不表示整条路线已完成。五小时执行额度的剩余额度不可见，本轮在自然阶段边界记录状态。

> 后续更新：2026-11-14 用户已选择审核 AI、远端 Provider、恢复策略及 `CODING_PLAN_*` 暂不支持等方向；下文相应“待决”措辞保留为交接时的历史记录。最新决策及仍需确认的具体输入见[决策记录](../decisions/README.md)。

## 目标与资料

- 目标：从既有会话、项目文档和当前实现中整理翻译工作流需求与计划，并按阶段实施可完成的改动。
- 已读取会话：`thread://01a1d41d-9f87-74b1-9589-421496c452ed`（翻译工作流文档体系）；`thread://01a1d5a2-a18a-7381-b24a-82fc4d5d4894`（翻译工作流计划方案）。两者均可访问。第一条记录 AI 优先的文档结构及证据约束；第二条最近补充模型/API 候选、配置、安全和 M0–M6 计划。
- 当前权威文档：`README.md`、`docs/project-status.md`、`docs/architecture.md`、`docs/translation-workflow.md`、`docs/knowledge-governance.md`、`docs/development.md`、`docs/roadmap.md`、`docs/decisions/README.md`、`docs/model-provider-configuration-plan.md`。
- `.agents/` 下的 context/progress/handoff 属历史记录；其中旧模型名、“71 项测试”以及“引号重试已实现”等表述与当前实现不一致。不要把它们作为当前事实。

## 已核实的现状

- 当前场景是日语轻小说译为简体中文；“信 > 达 > 雅”是质量顺序。通用多语言/多文本类型和多 Agent 服务编排仍是目标。
- `pipeline.py` 在一个 Python 进程中顺序执行上下文标注、初译、校对和润色；`rag_engine.py` 提供 TM、术语和指导检索。配置使用环境变量、项目路径或 JSON 配置路径。
- `tests/run_tests.py` 启动本地 mock server 后运行 E2E；mock 通过不证明真实 Provider、部署、模型质量或配额可用。
- 2026-11-14 本机快照：`.venv` 为 Python 3.14.7，`pip check` 无损坏依赖；代码默认 Sakura 地址 `127.0.0.1:6006` 不可达。实际数据目录已定位为被 `.gitignore` 排除的 `projects/祝福のネトラレラ`；目录/文件清单与 TM 键核对只使用元数据。之后的只读启发式诊断将 18 组同名原译章节载入本地内存计算映射；正文没有打印、写入日志或传输，知识文件未打开。外侧同名工作区 `..\祝福のネトラレラ_祝福的寝取系女主` 只有 `.gitattributes` 和 `.gitignore`。
- TM 通过现有格式门禁后仍自动写入。人工审核方式和写入责任尚未决策，见 `docs/decisions/README.md` 的 D-01；逐 Provider、逐数据类别的外发授权见 D-02。
- 当前代码的 Gemini 回退默认关闭；显式启用后仅连接/超时、HTTP 408/429 和 5xx 会触发。鉴权/请求错误、响应 schema 错误和内容拦截不回退。不要把旧 handoff 中“拦截后自动切 Gemini”当作现状。
- 真实 Provider 状态、数据来源/授权、凭据轮换状态和真实翻译质量仍未知；本轮未访问或修改密钥文件、未调用外部 Provider。
- 本地忽略项目有 48 个原文 Markdown（`生肉/1.神んてらの世界` 18 个、`生肉/2.小学五年生` 30 个；39 个匹配“第 N 话”命名）、19 个译文 Markdown（`熟肉/Ntera神的世界` 18 个章节，另一个是 EPUB README）和 19 个 TM 章节键。两个根目录第一层均没有 Markdown；此前 `Config.load_config(project=...)` 会分别依 `os.listdir` 首项选择 RAW_DIR/OUTPUT_DIR，可能漏掉原文卷或选择 EPUB。现已改为项目模式遇到任一子目录就要求显式 JSON 配置。TM 的 19 个键都能对应原文，但 `第19話.md` 没有同名译文；来源审计对 19 章全部报告 `unindexed`，退出码 2。18 组递归同名章节的只读启发式映射产生 1,376 个精确位置映射，仍有 31 个原文段落和 1 个译文段落未映射。该结果不说明内容质量或数据来源授权。
- 主请求按模型名选择 Sakura/DeepSeek 专属 URL 和 API key。旧 `get_base_url` 会在 `CODING_PLAN_BASE_URL` 配置为 loopback 地址或带显式端口 URL 时覆盖已选 Provider URL；仓库默认 DashScope URL 本身没有显式端口。现已移除这项非 mock 覆盖，回归测试用带显式端口配置验证旧行为；`CODING_PLAN_*` 字段是否应成为受支持 Provider 仍待 D-10 决策。

## 本轮已完成

- 空输入及目录歧义保护：`pipeline.py` 在授权预检后拒绝空章节列表；`scripts/align_chapters.py` 对空根目录扫描及全部译文缺失都以退出码 1 停止、不保存 TM。`Config.load_config(project=...)` 遇到 `生肉/` 或 `熟肉/` 子目录时要求显式 JSON 配置 `RAW_DIR`、`OUTPUT_DIR`，不再依 `os.listdir` 顺序选择首项。合成回归覆盖流水线空列表、嵌套原文章节、全部缺译文、平铺目录和项目模式歧义拒绝。定向两模块 65 项通过；六模块 105 项运行、103 项通过、2 项因 Windows 符号链接权限跳过、0 项失败；`tests/run_tests.py` 的 4 个本地 mock E2E 测试方法通过（204.662 秒，退出码 0）。没有调用真实项目 CLI、Provider 或书籍数据；首次单测运行因 Windows 临时目录沙箱权限失败，获批后的重跑通过。
- `已实现` 阶段 1 子项：各模型阶段要求段落数组与原文对齐，并拒绝空或非文本段落；校对无效数据保留上一版有效译文，润色无效结果回退到校对结果。
- `已实现` 阶段 1 子项：保存前逐段比较 `「」『』` 的字符数量和顺序。门禁失败时章节报错，译文文件和 TM 均不写入。
- 修复标注对象被通用字符串段落校验器误拒绝的问题；新增标注专用结构校验，要求字段类型正确、顺序/数量对齐且 `paragraph` 与源段落逐字相同，异常时回退到未标注源段落。
- 初译缺少 `translated_paragraphs` 时显式失败；校对缺字段、错误严重度/类型/数组项时保留上一版有效译文；反思响应无效时保留校对结果；润色响应无效时回退到校对译文。
- 移除仅在 `TEST_WORKSPACE_DIR` 下替换无效 JSON 和空结果的占位逻辑，避免测试环境隐藏 schema 失败。
- 已核实并改进持久化失败可见性：译文创建后 TM 写入失败时章节会报错但译文保留；此前重跑会静默跳过。现在仅对非空译文缺少 TM 记录的情况警告，不会自动重建；空原文产生的空译文文件不会误报。跨文件提交/恢复策略记为 D-11。
- 修正三个生产提示词的输出格式，使其匹配调用端的 `translated_paragraphs`、`corrected_text`、`polished_paragraphs` schema；上下文标注提示词也明确要求字段及源段落保真。
- 日志隐私复核发现校对严重意见和异常消息正文可能进入运行输出。现已移除校对意见正文打印，并将 RAG embedding 失败日志、知识抽取及章节对齐 CLI 的已处理错误限制为异常类型；合成敏感标记测试通过。第三方 SDK、E2E runner 和其他外围工具日志不受此改动控制。
- Mock 校对响应补齐既有 schema 的 `severity`/`critique` 字段；新增提示词字段防回归、契约异常回退测试，以及正向 E2E 对最终译文和 TM 原译对的断言。
- 修复 Provider URL 选择：正常请求保留模型路由选出的端点；mock 环境仍通过 `MOCK_SERVER_PORT` 指向本地 mock server。回归 fixture 使用 `https://coding.example:8443/v1`，使旧实现确实会错误覆盖所选 URL。
- `已验证` 阶段 3 路由子项：`get_primary_provider_route` 集中 Sakura/Qwen/DeepSeek URL 与专属 Key 映射，调用和启动检查共用路由结果；没有新增 Provider 或更改默认目标。
- `已验证` 阶段 3 错误分类子项：显式 Gemini 回退仅对 SDK 连接/超时异常和 HTTP 408/429/5xx 开放；鉴权/请求错误、响应 schema 错误和内容拦截不触发备用 Provider。通用 Provider 接口、按阶段绑定和计费责任仍未实现/决定；D-02 默认拒绝门禁已实现，但用户授权矩阵尚未确认。
- `已验证` 超时配置子项：`API_TIMEOUT` 默认 10 秒且必须为有限正数；环境变量/JSON 配置均生效，重复加载缺省恢复默认值。设置已传至 OpenAI-compatible 聊天、Gemini 生成、RAG 和章节对齐 embedding；Gemini SDK 参数由秒换算为毫秒。默认时长可能不足以覆盖慢速真实模型，端点延迟及合适阈值未实测。
- `已实现` D-02 默认拒绝子项：新增 `PROVIDER_DATA_POLICY` 按 Provider/数据类别 allowlist，默认 `{}`。远端主请求、Gemini 回退、RAG embedding、章节对齐和知识抽取均在请求边界检查；流水线启动前还预检生成阶段授权。无 Gemini 原文 embedding 权限时沿用既有 RAG 降级，不发送文本；对齐/知识抽取因其结果需要外部调用而拒绝执行。当前没有配置任何真实 Provider 授权，尚未解决 D-02 的用户决策。
- `部分实现` 阶段 2 候选抽取子项：`scripts/auto_extract_knowledge.py` 在落盘前校验响应对象、术语条目、概要文本和冲突译名，并排他新建 `Glossary_draft.json`、`STORY_SUMMARY_draft.md`、`KNOWLEDGE_PROVENANCE_draft.json`。来源清单记录提示词样本哈希、各输入章节的哈希/实际字符范围，以及术语在输入段落中的精确文本命中；未命中项标为空来源。清单最后写入并含 `artifact_status: complete`；逐文件写入不是事务，若标记缺失或无效，先人工核对残留草稿。7 项合成测试覆盖有效草稿、畸形/冲突响应拒绝写入、既有来源清单保护、无章节、未命中、20,000 字符截断和部分写入故障。它不证明概要逐句有据；其他知识/TM 的来源追踪、置信度、审核状态、正式知识发布和 TM 审核规则仍未实现。
- `部分实现` TM 来源索引：`pipeline.py` 的新译文写入记录原文/译文哈希及 1:1 段落序号；`scripts/align_chapters.py` 记录两侧文件哈希及对齐后的原文/译文段落序号，包括合并或跳过译者注的映射。索引经 `utils.py` schema 校验后作为可选顶层 `source_provenance` 原子写入；每一侧段落引用必须严格递增且不重叠，重复/倒序映射在写入前拒绝。RAG 检索忽略该元数据，缺少索引的旧 TM 仍可读。RAG 覆盖章节时若未提供新索引会清除该章旧索引并保留其他章节记录，避免来源错配。新增只读审计工具 `scripts/validate_tm_provenance.py` 可检查哈希、段落映射和词对文本，但不修复或审核语义。
- 生成阶段类别按 `source_text`、`translation_text`、`book_knowledge` 全部声明，因为共享上下文可能含有既有 TM 译文；章节对齐和 RAG embedding 只发送原文，因此只要求 `source_text`。loopback OpenAI-compatible endpoint 与 RAG 直接调用本地 HTTP mock 不需远端授权；Gemini SDK 始终要求 grant，E2E runner 只为合成 fixture 显式授予测试类别。不能据此推断本地代理不会转发数据。
- 安全复核发现 `MOCK_SERVER_PORT` 曾使生产 Gemini SDK 和章节对齐 embedding 跳过授权检查，但它本身不能证明这些调用已经接入本地 mock。现已移除该豁免；`tests/run_tests.py` 只为 E2E 子进程显式配置合成 fixture 的 Gemini grant，并增加带该端口变量的拒绝断言。
- 配置入口：根 `.env`/进程环境变量使用 `PROVIDER_DATA_POLICY` JSON 对象；显式 JSON 配置也可声明同名字段。例：`{"deepseek":["source_text","translation_text","book_knowledge"]}`。`.env.example` 保持空策略，避免将示例误作真实授权。
- 已同步 `docs/translation-workflow.md`、`docs/architecture.md`、`docs/knowledge-governance.md`、`docs/project-status.md`、`docs/roadmap.md`、`docs/development.md`，并补充各项目阶段的验证命令。
- 关键实现位置：`utils.py::require_aligned_paragraphs`、`utils.py::require_aligned_annotations`、`pipeline.py::TranslationPipeline._run_context_annotation`、`pipeline.py::TranslationPipeline._run_refinement_loop`、`pipeline.py::TranslationPipeline.run_chapter`。

## 验证记录

- 对 `projects/祝福のネトラレラ` 运行 `.venv\Scripts\python.exe scripts\validate_tm_provenance.py --project 祝福のネトラレラ`：只读核验返回 19 个 `UNINDEXED`，退出码 2；没有哈希/段落不一致项，因为这 19 章都没有来源索引可核对。
- 本地数据目录元数据核对：48 个原文 Markdown、19 个译文 Markdown、18 个同名章节文件；TM 有 19 章，均存在同名原文，`第19話.md` 缺少同名译文。独立的只读对齐诊断在本地内存中读取 18 组原译章节；没有打印/记录正文或调用 Provider。
- 本地只读调用现有 `align_chapter` 和索引函数检查 18 组同名章节：1,376 个 TM 段对成功映射到原文/译文段落；31 个原文段落和 1 个译文段落未映射。该 one-off 诊断未写文件、未调用 embedding/Provider，不能作为自动来源回填或人工验收证据。
- 日志隐私改动后的 `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_align_chapters_unit -q`：84 项通过、0 项失败；包含校对意见、RAG 异常消息、知识抽取 CLI 与章节对齐 CLI 的合成敏感标记检查。
- 日志隐私改动后的 `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法通过，245.423 秒，runner 退出码为 0；使用本地 mock server。负向 fixture 的捕获堆栈是预期输出。
- 同次 `py_compile` 与 `git diff --check`：通过。
- `.venv\Scripts\python.exe -m unittest tests.test_knowledge_extraction_unit -v`：7 项通过；仅使用合成数据和 mock client，没有调用外部 Provider。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q`：最新聚焦运行 97 项、95 项通过、2 项因 Windows 未授予符号链接创建权限（`WinError 1314`）而跳过、0 项失败；包含审计 CLI 成功、来源不一致返回 1、旧 TM 证据不完整返回 2 的回归。
- `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法通过，221.755 秒，runner 退出码为 0；只使用本地 mock server，负向 fixture 的错误堆栈为预期输出。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py scripts\align_chapters.py scripts\auto_extract_knowledge.py scripts\validate_tm_provenance.py utils.py tests\test_align_chapters_unit.py tests\test_e2e.py tests\test_knowledge_extraction_unit.py tests\test_rag_engine_unit.py tests\test_tm_provenance_unit.py`：通过。`git diff --check` 通过；README 与 `docs/` 下 11 份活动 Markdown 的 38 个本地链接目标均存在，未检查锚点。
- 审计 CLI `--help` 与合成 TM 调用测试通过；测试核对成功后 TM 文件字节不变。`projects/example/Knowledge/translation_memory.json` 不存在，未对仓库样例 TM 执行审计。
- `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit -v`：D-02 与 Gemini mock 端口回归完成后最新复跑为 77 项运行、75 项通过、2 项因 Windows 未授予符号链接创建权限（`WinError 1314`）而跳过、0 项失败；覆盖默认拒绝、逐类别授权、环境/JSON 配置优先级、设置 mock 端口仍拒绝 Gemini、启动预检、直接客户端/回退/RAG/对齐门禁，以及此前的路由、超时、契约和 TM 行为。
- `.venv\Scripts\python.exe -m unittest tests.test_pipeline_contracts.TestProviderRouting -v`：12 项通过；覆盖 Sakura/Qwen/DeepSeek 路由、OpenAI 请求超时、连接/超时、408/429/5xx 回退和鉴权/请求/schema/内容拦截不回退。
- `.venv\Scripts\python.exe tests\run_tests.py`：Gemini mock 授权复核后完整复跑，4 个 E2E 测试方法通过，218.843 秒，runner 退出码为 0；仅使用本地 mock server。包含 Case 29 引号顺序门禁和 Case 59 的 401 不回退/不落盘断言。控制台的失败堆栈来自断言负向用例，不代表 runner 失败。
- `.venv\Scripts\python.exe -m py_compile pipeline.py rag_engine.py scripts/align_chapters.py utils.py tests/test_pipeline_contracts.py tests/test_align_chapters_unit.py tests/test_rag_engine_unit.py tests/test_e2e.py tests/mock_genai.py tests/mock_server.py`：通过。
- `.venv\Scripts\python.exe --version`：Python 3.14.7；`.venv\Scripts\python.exe -m pip check`：无损坏依赖。`Test-NetConnection 127.0.0.1 -Port 6006`：不可达。
- 2026-11-14 检查相邻书籍工作区 `..\祝福のネトラレラ_祝福的寝取系女主`：一级没有子目录或 Markdown 文件，有 2 个文件未打开；未搜索其他本地/云端数据位置，也未探测其他 Provider 地址。
- `git diff --check`：通过。
- README 与 `docs/` 下 11 份活动 Markdown 的本地文件链接目标检查通过，无缺失文件目标；未检查标题锚点或仓库其他示例/历史 Markdown。未验证真实 Provider、部署或翻译质量。
- 普通沙盒拒绝系统 temp 与仓库 `scratch/` 中临时 fixture 的访问。获批后将 `TEMP/TMP` 指向 ignored `scratch/` 并在沙盒外运行，上述测试通过。

## 需要保留的工作区改动

任务开始时已有以下用户/先前任务文档改动；本轮保留并在必要位置合并，没有重置或覆盖其他内容：

- 已修改：`README.md`、`docs/decisions/README.md`、`docs/development.md`、`docs/knowledge-governance.md`、`docs/project-status.md`、`docs/roadmap.md`。
- 未跟踪：`docs/model-provider-configuration-plan.md`。

本轮新增/修改还包括 `.env.example`、`pipeline.py`、`rag_engine.py`、`scripts/align_chapters.py`、`scripts/auto_extract_knowledge.py`、`scripts/validate_tm_provenance.py`、`utils.py`、三个 `prompts/*_skill.md`、`tests/run_tests.py`、`tests/test_pipeline_contracts.py`、`tests/test_align_chapters_unit.py`、`tests/test_rag_engine_unit.py`、`tests/test_security_path_traversal.py`、`tests/test_knowledge_extraction_unit.py`、`tests/test_tm_provenance_unit.py`、`tests/test_e2e.py`、`tests/mock_genai.py`、`tests/mock_server.py`、`README.md`、`docs/architecture.md`、`docs/development.md`、`docs/knowledge-governance.md`、`docs/project-status.md`、`docs/roadmap.md`、`docs/translation-workflow.md` 和本交接文件。所有这些工作区变更都应保留。

## D-12 显式映射续接（2026-11-14）

- 目标：为多卷、不同译文目录和 TM 键提供可审查的映射入口，同时保持平铺扫描兼容。
- 已实现：显式 JSON `CHAPTER_MAP`；每项包含 `raw_file`、`translation_file`、`tm_key`。安全路径工具验证根相对路径、文件类型、符号链接、重复路径/键及已存在输出父目录。流水线按清单顺序翻译，输出到映射位置并以 TM 键写记忆；对齐器和知识抽取读取同一映射；TM 溯源审计支持嵌套路径；RAG 分章指导使用已经读取的原文。项目模式仍拒绝任意选择嵌套目录。
- 依据：忽略项目的根目录没有 Markdown，原文和译文位于多个子目录；过去按 `os.listdir` 首项选择目录会漏卷或选中 EPUB。项目当前文件分布、审计状态和不完整段落对应详见本文件的“已核实的现状”；实现 schema/示例见 `docs/development.md` 与 D-12。
- 验收：`.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit tests.test_knowledge_extraction_unit tests.test_tm_provenance_unit -q` 为 116 项运行、113 项通过、3 项因 Windows 符号链接权限跳过；知识来源键追加测试 9 项通过；`.venv\Scripts\python.exe tests\run_tests.py` 为 4 个 mock E2E 方法通过（最终运行 205.064 秒，退出码 0）。最终 Python 文件 `py_compile`、`git diff --check` 通过；README 与 `docs/` 下共 11 份 Markdown 的本地链接目标全部存在。链接目标检查不验证标题锚点。
- 未完成：尚未用忽略项目真实文件生成或运行映射清单。原文/译文章节配对、TM 键映射、缺失第 19 话的处理、数据来源授权及任何 Provider 使用均需确认；合成测试不能替代这些确认。本轮没有读取章节正文、写入真实项目或调用模型。
- 下一步：在获得项目映射和数据使用授权后，由维护者逐项复核 `CHAPTER_MAP`，先运行只读 TM 来源审计；只有清单、章节对应、缺译文处理和授权都已确认，才考虑对齐或翻译。当前不要运行真实项目的翻译/知识抽取或写入 TM。
- 五小时额度状态不可见；没有判断是否触及 10% 阈值。

## 下一步

1. 当前工作区最终核对已完成：起始时已有的文档改动和未跟踪的模型配置方案仍保留；本轮代码、提示词、测试及文档改动均在工作区，`git diff --check` 通过。继续工作前先重新运行 `git status --short --branch`，不要清理这些未提交变更。
2. 阶段 1 的当前代码/提示词 schema 契约和 mock 正反向文件/TM 检查已完成并通过本地验证。下一步如需扩展非引号格式门禁，先取得获准的代表性章节及明确格式标准；仓库现有实现/活动文档没有定义更多硬规则，不要自行推定。
3. 阶段 2 的抽取草稿和新 TM 来源索引已有本地实现，但阶段整体仍需处理 `D-01`：决定 TM 采用逐条人工审核、抽样审核或明确的自动门禁，并确认正式知识审核责任。当前实际项目 TM 的 19 章全部缺少来源索引；`第19話.md` 也缺少同名译文。来源索引不代表批准，历史 TM 未回填；不要对其自动重建或发布。
4. 阶段 0 已定位忽略项目 `projects/祝福のネトラレラ` 的原文、译文和 TM 目录；D-12 的通用 `CHAPTER_MAP` schema 已实现，但真实章节映射、缺失译文处理、数据来源/授权、凭据轮换状态、Provider 数据范围及端点部署仍待确认。先由维护者逐项核对真实清单；不得按章节号自动猜测、改写或搬动项目数据。未获 D-02 授权前，不要将真实书籍数据发送给任何 Provider。阶段 0 的这些门槛不阻止合成 fixture 的本地验证。
5. Provider 配置按 `docs/model-provider-configuration-plan.md` 的 M0/M1 先定义契约；D-10 确认 `CODING_PLAN_*` 是否代表待支持 Provider。UI、真实 API、账户额度和模型默认值仍需决策/授权/实测，不因文档方案而视为已实现。
6. D-11 决定译文文件和 TM 跨文件写入失败后的恢复责任；当前做法是保留译文、对非空译文缺失 TM 条目发出警告，不自动发布或重建 TM。若采用人工恢复，明确章节对齐脚本和验收步骤；若采用自动恢复，先定义审核状态与可恢复的提交记录。
7. 阶段 3 下一步实现通用 Provider/能力接口前，先处理 M0/M1 与 D-02/D-09/D-10：明确获准 Provider 和数据类别、回退目标/重复计费策略、`CODING_PLAN_*` 的用途及配置契约。默认拒绝门禁已经实现，但当前无真实 Provider 授权；错误分类改进不解除真实 Provider 数据授权和兼容性验收门槛。

## 路线图状态同步（2026-11-14）

- 本轮重新核对了阶段状态及现有实现；阶段 0/1/2 统计已在 `docs/roadmap.md` 更新为章节映射最终验证的 116 项（113 项通过、3 项因权限跳过）、知识抽取定向验证的 9 项及 4 个 mock E2E 方法。详细命令和限制仍以 `docs/development.md` 为准。
- 阶段 3 路由复核发现未知模型名此前默认进入 DeepSeek 路由。本轮已改为只接受 `sakura`/`sakura-`、`qwen3.6-plus` 和 `deepseek-` 名称；空白、未知或首尾带空格名称在流水线章节扫描及客户端创建前拒绝。OpenAI-compatible base URL 也在流水线预检和客户端创建处校验，只允许公网 HTTPS 与 loopback HTTP，拒绝无效 URL 及 URL 内认证信息/查询/片段；客户端关闭自动重定向。`pipeline.py` 与 `tests/test_pipeline_contracts.py` 已更新，路由/URL 定向测试 23 项、完整流水线契约模块 55 项通过；随后 `tests/run_tests.py` 的 4 个 mock E2E 方法通过（202.829 秒，退出码 0）。端点需提供规范 URL，新增模型前缀需先配置明确 Provider 映射。
- 阶段 0 干净安装复核：在一次性 Python 3.14.7 venv 中按未锁定的 `requirements.txt` 安装当日解析版本，`pip check` 无损坏依赖；55 项流水线契约和 4 项 mock E2E 通过（203.436 秒）。标准 `venv` 的 `ensurepip` 未成功，使用既有 pip 的 `--python <venv>` 目标模式安装；因此只证明本机单一 Python/Windows 解析集可运行，不证明版本范围或其他平台兼容。临时 venv 已清理，未修改依赖清单。
- 文档一致性复核：修正阶段 3 路由/URL 定向测试数为 23；决策索引新增状态列，明确 `未知`、`部分实现`、`未验证` 与所需的人类决策，不将默认建议写成已确认决策。
- 本轮代码/测试验证使用合成 fixture，未调用真实 Provider，也未由测试读取真实书籍章节；同日另有一项只读启发式诊断将 18 组原译章节载入本地内存，未打印、写入日志或传输，详见“已核实的现状”。`git diff --check` 通过；README 与 `docs/` 下 11 份活动 Markdown 的 40 个本地链接目标均存在，未检查标题锚点。
- 尚无不依赖外部决策且已确认的后续代码改动：阶段 0 的真实映射/授权/凭据，阶段 2 的 D-01 知识审核责任和 D-11 写入恢复策略，阶段 3 的 D-02/D-09/D-10 Provider 范围与回退政策，及真实 Provider/质量验收均未关闭。五小时额度仍不可见；此状态不是额度阈值判断。

## 安全差异审查续接（2026-11-14）

- 使用 Codex Security Diff Scan 检查当前未提交差异；工作台清单中的 6 个生产 Python 文件均已审阅，另检查了改动的示例配置、提示词和测试辅助代码。`README.md` 与 `docs/**` 作为非执行文档排除在运行时攻击路径审查之外。委派审查不可用，由主审完成；未调用真实 Provider、未使用真实书籍正文。
- 确认 1 项低严重性问题：`scripts/validate_tm_provenance.py` 将 TM JSON 中的章节键未经转义直接写入终端输出。只用合成内存输入执行 CLI 路径，确认 ANSI/OSC 控制字节到达捕获 stdout；没有运行真实终端，因此未证明剪贴板修改、代码执行或远程攻击。
- 安全报告：`C:\Users\AscAed\.codex\state\plugins\codex-security\scans\Light-Novel-Translation-Workflow-System\5b6f7f5c9cd0644f11ffb200321cd6842ec6d451_20261114T013507Z_fxsrmhyb\report.md`。该封存扫描对应审查时的工作区快照；本节是扫描完成后新增的文档记录，源码未变化。若后续改动生产源码，应重新审查相应差异。
- 已修复：`scripts/validate_tm_provenance.py` 仅在 CLI 输出边界将不可打印字符转为可见转义文本；普通 Unicode 输出保持不变，审计 findings API 不变。异常消息同样经过净化。合成回归覆盖 ANSI/OSC、BEL、C1、CR/LF、双向控制字符及异常消息，确认 stdout/stderr 不含原始控制字符。
- 同一 CLI 拒绝空白 `TEST_WORKSPACE_DIR`，并在调用 `Config.load_config` 前返回错误；回归测试确认配置加载器不会被调用，避免空值被解析为系统临时目录。
- 修复后 `tests.test_tm_provenance_unit` 14 项通过；六模块定向单测 125 项运行、122 项通过、3 项因 Windows 符号链接权限跳过、0 项失败；mock E2E 4 项通过（222.269 秒，退出码 0）；Python 编译及 `git diff --check` 通过。具体命令见 `docs/development.md`。
- 剩余不确定性：支持的终端及 OSC 行为、真实部署是否配置转发代理/Provider gateway、真实凭据与 `PROVIDER_DATA_POLICY` 的变更权限均未检查。扫描用量遥测不代表 5 小时额度余量；额度状态仍不可见。
