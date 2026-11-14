# 开发与验证

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
- OpenAI-compatible Provider base URL 必须是带主机名的 HTTP(S) URL，端口语法有效，且不得包含用户名、密码、查询或片段；非 loopback 地址必须使用 HTTPS，HTTP 仅允许 `localhost` 或 loopback IP。流水线读取章节前预检，客户端创建时再次验证。SDK 自动重定向已关闭；端点返回重定向时请求失败，配置时应提供规范 URL。
- 仅 loopback OpenAI-compatible endpoint 与 RAG 直接调用的本地 HTTP mock 不需要外发授权；不能据此推断本地服务不会自行转发数据。Gemini SDK 调用始终执行授权检查，`MOCK_SERVER_PORT` 本身不能放行；E2E runner 只为合成 fixture 显式注入测试用 Gemini grant。`run_all` 在读取章节前按实际阶段类别预检 Provider 授权，随后仍在客户端入口重复检查。
- 无 Gemini `source_text` 授权时，RAG embedding 不会发送原文；TM 查询/更新沿用现有降级行为。`scripts/align_chapters.py` 和 `scripts/auto_extract_knowledge.py` 在缺少授权时停止；前者不保存本轮 TM 更改，后者不创建草稿。
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

# 核对显式映射章节的 TM 来源索引
python scripts/validate_tm_provenance.py --config <项目配置.json>

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
```

`validate_tm_provenance.py` 不写入 TM。退出码 `0` 表示有来源索引的条目与当前文件匹配且无未索引章节；`1` 表示索引结构、哈希或段落内容不一致；`2` 表示存在旧 TM 无索引、部分/未匹配来源或无法读取的源文件。退出码 `2` 不代表审计通过。

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

### 2026-11-14 审计续接与来源安全修复

- 审计分支 `codex/source-ingestion-audit-20261114` 的基线为 `e5c315452fdef7efa71b06adabbe3fc8ccaa23f9`，与 `origin/main` 一致；PR #56 已于 2026-11-14 10:04:56 UTC 合并为该提交。以下单测在该基线加当前未提交改动的工作树中运行。
- 十模块定向单测命令运行 174 项、170 项通过、4 项跳过、0 项失败。普通 PowerShell 下 3 个符号链接测试因 `[WinError 1314]` 跳过，POSIX FIFO 用例因 Windows 不支持 `os.mkfifo` 跳过；文件类型模拟测试通过。管理员 PowerShell 重跑 `tests.test_security_path_traversal` 后 11 项运行、10 项通过、1 项跳过、0 项失败，3 个符号链接路径行为均实际执行，FIFO 用例仍因平台能力跳过。
- 用户另行提供的普通 PowerShell 路径安全模块输出为 `Ran 9 tests ... OK (skipped=3)`。当前工作树同一模块有 11 个测试方法；该 9 项结果保留为独立运行记录，不替代当前 11 项版本的管理员运行。
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
- `.\.venv\Scripts\python.exe -m unittest tests.test_source_ingestion tests.test_local_source_ingestion_cli -v`：在代码提交 `da178bb0b48a93cd72e43860071675b23d4f27c9` 上运行 27 项合成测试，全部通过。覆盖分页/续传、快照与目标绑定、旧 checkpoint 迁移边界、输出与输入路径别名拒绝、显式本地路径、source_ref、失败恢复、幂等、路径边界和无正文 CLI 输出。
- 同一代码提交上的三模块定向回归共 38 项，34 项通过、4 项跳过、无失败；`tests.test_security_path_traversal` 的 11 项中 3 项因 `[WinError 1314]` 无法创建符号链接、1 项因 Windows 不支持 `os.mkfifo` 而跳过。`compileall` 与 `git diff --check` 通过。用户另行提供的 9 项运行/3 项跳过结果没有 SHA 和逐项 skip 原因，独立保留，不替代本次结果。
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
- 用户在普通 PowerShell 中复跑 `tests.test_security_path_traversal`：9 项运行、6 项通过、3 项仍因符号链接权限跳过；该运行未获得管理员令牌。
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
- 尚未生成或应用忽略项目 `projects/祝福のネトラレラ` 的实际映射；章节关系、数据授权及缺失译文处置仍需人类核验。

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
- Provider 路由复核：`get_primary_provider_route` 集中返回现有 Sakura/Qwen 或 DeepSeek 的 URL 与专属 Key 环境变量，请求和启动 Key 检查复用该映射。旧逻辑会在 `CODING_PLAN_BASE_URL` 配置为 loopback 地址或带显式端口的 URL 时覆盖已选择 URL；现在只有设置 `MOCK_SERVER_PORT` 时才覆盖为本地 mock URL。此项不实现 `CODING_PLAN_*` Provider 支持，真实端点仍未验证。
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

## 验证要求

- 修改后运行受影响的单元测试；改动 API/流水线时再运行 mock E2E。
- 实际 Provider/部署验收必须另行使用批准的测试项目和凭据，记录模型、端点类型、日期、输入类别、结果和失败，不记录密钥或不必要的原文。
- 测试失败必须区分代码缺陷、环境/依赖、mock 限制与外部服务问题；不得用“测试就绪”代替通过证据。
