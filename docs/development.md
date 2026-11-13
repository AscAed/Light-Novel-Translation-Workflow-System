# 开发与验证

## 环境事实

- 实现语言：Python。
- `requirements.txt` 声明 `openai`、`google-genai`、`aiohttp`、`numpy`；版本未锁定。
- 仓库没有 `pyproject.toml`、锁文件或 Python 最低版本声明。
- 本轮验证环境：Windows PowerShell、Python 3.14.7；本地 `.venv` 安装了 `openai 3.50.0`、`google-genai 3.3.0`、`aiohttp 3.14.5`、`numpy 2.5.4`。这只是本机快照，不构成项目支持版本声明。
- 仓库未发现 GitHub Actions/其他 CI、容器、进程管理器或云平台部署配置。
- `.env.example` 提供 API 配置名；真实 API 服务、凭据和模型兼容性需另行验证。

## 配置与数据

- 推荐项目数据布局：`projects/<项目名>/生肉/`、`熟肉/`、`Knowledge/`。
- 项目名模式与显式 `--config` JSON 模式均由 `Config.load_config` 处理。
- `pipeline.py` 会加载仓库根目录 `.env`，并读取相应环境变量；`.env*` 默认被忽略。
- `projects/*` 默认忽略，`projects/example/` 例外。运行前确认目标项目路径，避免写入错误书籍目录。
- 进程环境变量优先于根目录 `.env`；API key 按 Provider 专属变量读取。只有 loopback OpenAI-compatible endpoint 允许使用本地占位 key。
- `ENABLE_GEMINI_FALLBACK` 默认关闭；开启后主 Provider 调用错误会将同一请求发送到 Gemini。主 Provider 的内容拦截不会触发回退。
- Gemini embeddings 使用 `GEMINI_API_KEY`；配置了 `MOCK_SERVER_PORT` 时改走本地 mock。
- `StartUP.txt` 为被忽略的本地文件，不是受支持的配置入口。疑似凭据问题见[安全记录](security-notes.md)。

## 命令

```powershell
# 翻译项目目录
python pipeline.py --project <项目名>

# 对齐章节并生成/更新 TM
python scripts/align_chapters.py --project <项目名>

# 运行由 mock server 驱动的 E2E 测试
python tests/run_tests.py

# 只运行某个 E2E 测试组
python tests/run_tests.py tests.test_e2e.E2ETestSuite.test_tier1_feature_coverage

# 独立单元测试
python -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts
python -m unittest tests.test_align_chapters_unit
python -m unittest tests.test_rag_engine_unit
```

安装命令：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

依赖版本当前未锁定。真实 Provider 和部署验收不属于依赖安装或 mock 测试的证明范围。

## 测试解释

- `tests/run_tests.py` 分配本地端口、启动 `tests/mock_server.py`，然后运行 `tests/test_e2e.py`。可向 runner 传入 unittest 测试路径以筛选测试；直接运行 E2E 模块不会自动启动 mock server。
- `tests/run_pipeline.py` 将生产 `TranslationPipeline` 接到本地 mock Provider；它验证本地流程和请求/响应契约，不验证外部 API。
- 单元测试使用 `unittest`；RAG 测试会创建临时文件，并可能需要可写的系统临时目录。
- Mock 服务只验证本地请求/响应逻辑，不验证真实模型质量、安全策略实际效果、配额、网络部署或服务端 schema 支持。
- 当前测试数量、覆盖率和通过状态应以实际命令输出为准。`TEST_READY.md` 中历史“71”计数不可当作最新用例数或通过结果。

## 本轮验证记录

- 完整命令 `.venv\Scripts\python.exe tests\run_tests.py`：4 个 E2E 测试方法全部通过，耗时约 283 秒；请求均由本机 mock server 响应。
- 聚焦单元测试命令 `.venv\Scripts\python.exe -m unittest tests.test_security_path_traversal tests.test_pipeline_contracts tests.test_align_chapters_unit tests.test_rag_engine_unit -v`：31 项通过，2 项跳过。两个跳过项需要创建符号链接；当前 Windows 用户缺少相应权限（`WinError 1314`）。
- 本轮涉及的生产和测试 Python 文件均通过 `py_compile` 编译。
- Markdown 相对链接检查：21 份 Markdown 文件，无缺失的本地目标；`git diff --check` 无空白错误。
- 本机 `127.0.0.1:6006` 不可达；未调用 Sakura、DeepSeek 或 Gemini 外部服务。
- Codex Security 自动扫描未生成正式报告，原因和覆盖限制记录于[安全记录](security-notes.md)；不能将其解释为扫描通过。

E2E 测试创建临时工作区。本轮在受限执行环境中将 `TEMP`/`TMP` 指向仓库 `scratch/` 并通过授权运行；其他环境需保证 Python 临时目录可写。

## 验证要求

- 修改后运行受影响的单元测试；改动 API/流水线时再运行 mock E2E。
- 实际 Provider/部署验收必须另行使用批准的测试项目和凭据，记录模型、端点类型、日期、输入类别、结果和失败，不记录密钥或不必要的原文。
- 测试失败必须区分代码缺陷、环境/依赖、mock 限制与外部服务问题；不得用“测试就绪”代替通过证据。
