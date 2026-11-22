# 项目现状

本页按当前状态优先记录；较早的日期条目是其记录时点的快照，不能覆盖本节。通用验证环境、命令及边界见[开发与验证](development.md)。

## 2026-11-22 K5 输入复核与当前阻塞

- `已验证` 当前试点来源仍与 88 话计划匹配：`source_manifest.json` 为 356/356 文件通过，`source_editions_manifest.json` 为 532/532 文件通过；双版本验证状态为 `verified`，AI 版 774,253 bytes、人读版 799,293 bytes。`run_kakuyomu_workflow.py --plan-only` 返回 88/88 来源、0 issue、0 网络请求、0 Provider 调用、0 文件写入，计划 SHA-256 为 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。
- `已验证` 当前 AI bundle 经 `load_verified_ai_book_bundle` 使用其实际绑定的完整 checkpoint `source_checkpoint.raw-html-refresh-2026-11-17.json` 复核通过，覆盖 88 话；bundle-set SHA-256 为 `434b86a037c0c4f9f31a8a85b3ac482504758f63134015efae52ee9b2653f22f`，AI bundle SHA-256 为 `173666f05cb172cca71d751c161db91e33496409fac78e626356fc8623069bb0`。误用默认 `source_checkpoint.json` 会因不是该 bundle 绑定的完整 checkpoint 而失败；不能据此判断 bundle 已过期。
- `已验证` 当前项目 `Knowledge/` 根目录没有 `Glossary_reviewed.json`、`STORY_SUMMARY_reviewed.json` 或完整书知识候选三件套；`Workflow/Runs/` 不存在。`Workflow/Approvals/` 只有 2026-11-21 结构审阅回执。旧 `Glossary.json`、`STORY_SUMMARY.md` 不满足当前 bundle-bound reviewed 知识门禁。
- `未验证` 本轮没有在仓库、`D:\OWN\Programming\AI\TranslatorAI` 父目录或常见用户级 Hugging Face 缓存位置发现 `tokenizer.json`。已检查的 Provider 模型、route、allowlist、JOJO/JYQF endpoint/key、API pool 与 fallback 环境变量在 Process/User/Machine 均未设置；根 `.env` 存在且会由 `Config.load_config()` 读取，但本轮未读取其内容。`api_pool_store.default_profile_path()` 使用 `%LOCALAPPDATA%\TranslatorAI\api-pool.json`；截至本轮该路径存在，但未读取其内容；`%APPDATA%\TranslatorAI\api-pool.json` 不存在。Credential Manager 未检查。因此活动 route 仍未知，未调用真实 Provider。
- `计划` 继续 K5.2 前，需要配置所有者提供不含密钥的目标模型 ID、与该模型匹配的 tokenizer 文件路径及可验证来源、context/output/message/safety/call 上限和可接受费用预算，并在本机确认活动 route 与 `source_text`/`book_knowledge` allowlist。随后先运行只读知识预算预检；通过后才可生成候选、逐证据审核、发布 reviewed 知识并进入第 1 话受控试译。详细复现和边界见[开发记录](development.md#2026-11-22-k5-输入复核与当前阻塞)及[续接交接](handoffs/2026-11-15-translation-workflow.md#2026-11-22-k5-输入复核与当前阻塞)。

## 2026-11-22 元数据翻译 M0–M4 基线与 M1 执行器

- `已实现` 从当前 verified AI book bundle 生成作品字段、章节标题和话标题的 source-bound metadata inventory；计划写在本地项目 `Workflow/Plans/`，create-only，不调用 Provider，不包含章节正文。
- `已验证` 当前试点 103 个已采集字段（作品 12、章 3、话 88）均有源值；103 `pending_translation`、0 `missing_source`。源版本绑定经当前 manifest/bundle 重验，计划 SHA 可重复生成。定向命令、结果和 M0 边界见[开发与验证](development.md#2026-11-22-元数据翻译-m0-来源盘点)。
- `部分实现` `metadata_translation.py` 与 `scripts/import_metadata_translation_candidate.py` 可将完整的外部译文映射导入为 source-bound、`review_pending` 候选；全字段覆盖、摘要绑定、create-only 和同内容幂等均有合成测试。`scripts/plan_metadata_translation_generation.py` 可重验当前来源并按调用方 tokenizer、预算及单价分批估算；新增 `scripts/generate_metadata_translation_candidate.py` 默认只输出摘要，显式 `--execute` 才按每次调用传入的 model ID 路由、检查现有 `source_text` 授权并生成 review-pending 候选。严格逐字段响应校验、零 SDK retry、source freshness 复核、create-only intent/checkpoint/receipt、相同 run 互斥与 checkpoint 恢复均有合成测试。没有新增持久化 metadata Translator role。模型/tokenizer/endpoint 匹配、价格准确性和服务端兼容性未验证；费用估算不是服务商硬性限额。详见[执行器验证](development.md#2026-11-22-元数据翻译-m1-provider-执行器合成验证)。
- `部分实现` `metadata_translation_review.py` 与 `scripts/review_metadata_translation_candidate.py` 提供 schema v2 逐字段人工语义检查和 source-bound 回执，规则版本为 `metadata-translation-semantic-v1`。模板固定检查原意保真、完整性、适用术语、中文自然度和本地化处置；结果由这些检查派生，失败/冲突拒绝，不确定或需要独立注释时升级，任何未批准项阻止报告批准。来源摘要仍会复核。reviewer ID 未认证，术语参考未绑定 reviewed knowledge snapshot；这不是 AI 审核、身份认证或真实样本质量验收。schema v1 文件保留原样，当前 finalize 不接受旧模板。M2 仍需获准样本校准。
- `部分实现` 新增 `metadata_translation_publication.py` 和 `scripts/publish_metadata_translation.py`，仅在 M2 完整批准且 candidate/current catalog/manifest 摘要一致时，在计划所属项目已存在的 `Metadata/` create-only 写入双语 artifact。全计划字段保持原序；已批译文与 `missing_source` 状态分开表示；artifact 绑定 plan/candidate/review/rubric/source hashes。`Metadata/` 是[来源发布方案](source-ingestion-and-publication-plan.md#目标目录与版本约束)既有默认目录，本地试点该目录存在；本轮未读取目录内容或写真实试点 artifact。验证见[开发记录](development.md#2026-11-22-元数据翻译-m3-本地批准-artifact)。
- `部分实现` M4 增加 metadata-aware EPUB 入口：只消费 approved work/episode titles，先验证 M3 artifact 的原批准 lineage，再逐字段重验当前来源；只要本次使用的 source text/hash 不变，无关字段或 manifest 变化不会误使该译名 stale。变更/移除的选中字段拒绝构建。临时 EPUB catalog 不覆盖原文件；译文 Markdown 的来源标题 H1 经校验后，仅在 Pandoc 临时章节快照中替换成批准译名，原文件不变。`build.json` 同时绑定批准 snapshot、当前 source snapshot 和所用字段 version/hash，并分别记录原 Markdown 与 Pandoc 输入的哈希/字节数；要求 work ID、target locale 匹配，作者/identifier 等结构字段保持输入值。字段级 freshness 目前仅供 EPUB consumer 使用；M1/M2/M3 生成与写入仍要求全计划来源 freshness。验证见[开发记录](development.md#2026-11-22-元数据翻译-m4-freshness-与-epub-消费)。未接入 Notion/UI，也未使用真实试点 artifact/译文构建。
- `未验证` 本轮未运行真实 103 字段 Provider 生成；metadata 专属长期 role 映射、当前 route/allowlist/凭据、试点适配 tokenizer/context/template 和实际费用仍待配置所有者核验。根 `.env` 存在但未读取；本轮所查 Process/User/Machine 变量均未设置，API pool profile 与 Credential Manager 未检查，因此不能推断当前 route。未调用外部服务、未读或改试点 candidate/review/Metadata 内容。前记/后记/作者的话没有独立来源字段，未纳入 103 项。Notion/UI 消费与真实语义质量验收仍未完成。

## 2026-11-22 提交与 PR 状态

- `已验证` `183c3fe`（M0–M4 实现）、`18e8387`（Windows 路径断言修复）和 `f35817c`（交付记录）已推送到 `codex/translation-workflow-audit-20261117` 与 PR #71；提交及验证时间线见[开发与验证](development.md#2026-11-22-提交后验证与-pr-状态)。
- `已验证` 截至 hosted run `44971559503` 完成时，PR #71 为 `OPEN` 且 `MERGEABLE`，Ubuntu/Windows Python 3.14 jobs 通过；没有正式 review approval，因此未合并。
- 唯一未跟踪文件是受保护的 `downstream_freshness_ai_index_refreshed_2026-11-17.json`，保持未读、未改、未暂存和未提交。

## 2026-11-21 当前工作树综合自检

- `已验证` 起始 HEAD 为 `b0a4f3d24fc5809e133a824ff81d03d7ea773a82`。该工作树的完整非 E2E 回归为 816 项运行、5 项因 Windows 能力跳过、0 失败；loopback mock E2E 为 7 项通过。依赖、静态检查及扫描范围见[当前工作树综合自检](development.md#2026-11-21-当前工作树综合自检)。
- `部分实现` 只读安全扫描未报告发现，但范围不包含项目数据、凭据配置或运行中部署；它不是生产环境安全认证。
- `未验证` 当前试点没有 reviewed 全书知识、正式翻译 run 或译文。真实 Provider 路由/预算、语义质量、人工验收与线上部署仍缺少验证证据；项目交付形态仍是本地 Python CLI。

## 2026-11-21 K5 全书知识抽取预检

- `已实现` `scripts/plan_knowledge_extraction.py` 提供无 Provider、无 key、无文件写入的全书知识抽取预检；它重载并验证当前 AI book bundle，复用抽取器的段落编号、prompt、tokenizer 计数和分批器，给出内容无关的调用预算摘要。
- `已验证` 27 项预检/batching/book-bundle 回归及 41 项知识抽取回归通过；合成 bundle 真实经过 loader。报告确认 `provider_calls_made=0`、`files_written=0`、`source_text_included=false`，并拒绝错误来源摘要、超限输入、无效覆盖和缺少 synthesis call 预留。
- `部分实现` 模型 ID 和 tokenizer/context 参数由运行者声明，尚未证明彼此匹配或端点模板兼容；综合调用实际次数可能高于下限，价格未配置则无法估算。预检不生成真实候选或审核语义。

## 2026-11-21 K5 全书知识候选语义审核

- `已实现` `scripts/review_knowledge_candidates.py` 会重新验证当前 verified AI bundle、章节 map、候选哈希和逐段 evidence；审核决定只能是 `approved`、`rejected` 或 `escalated`，且必须覆盖所有候选；理由拒绝短证据整段复现及连续 16 个以上字母/数字字符的归一化原文片段。此文本启发式不能阻止语义改写泄漏。
- `已实现` 默认模式不加载配置、不读 key、不联网、不写文件；显式 `--execute` 才使用 `PROOFREAD_MODEL` 并检查 `source_text`/`book_knowledge` 授权。批次 checkpoint 和最终报告绑定当前候选、bundle、模型/tokenizer 和预算，支持中断后复用。
- `已实现` 复用最终报告时与当前批次 checkpoint 逐项交叉核验，验证输入摘要/token 预算和决定一致；报告被改写或 checkpoint 缺失/不匹配时失败关闭。
- `已实现` 报告不会自动转成 reviewed glossary/summary；有拒绝或升级项时要求解决，全部批准也不替代现有 `apply_knowledge_review.py`、`story_summary_review.py` 的发布门禁。
- `已验证` 审核入口、book-bundle 与 reviewed 发布器相关回归 73 项通过，含格式变化/长片段原文引文拒绝和改写报告后拒绝复用用例；完整非 E2E 与 loopback mock E2E 最新结果见[当前工作树综合自检](development.md#2026-11-21-当前工作树综合自检)。未对试点书或真实 Provider 执行语义审核。候选完整性、独立审核者身份、整书遗漏和语义质量仍未由该工具证明。

## 2026-11-21 持续集成基线

- `已实现` `.github/workflows/tests.yml` 为 push、pull request 与手动触发建立 Ubuntu/Windows Python 3.14 测试矩阵；动作按提交 SHA 固定，权限仅为 `contents: read`。安装依赖后执行 `pip check`、稳定排序的非 E2E 单测入口和仓库 loopback mock E2E runner。
- `已实现` `scripts/run_unit_tests.py` 将非 E2E 测试集合固定为除 `test_e2e.py` 外所有 `test_*.py` 模块；真实集成 E2E 仍由 `tests/run_tests.py` 自行启动 mock server。
- `已验证` 当前工作树 Windows/Python 3.14.7 非 E2E 回归 816 项运行、5 项 Windows 能力跳过、0 失败；loopback mock E2E 7 项通过。具体最新检查结果见[综合自检](development.md#2026-11-21-当前工作树综合自检)。K5 知识来源/bundle 门禁、本轮预检和候选审核分别见[开发与验证](development.md#2026-11-21-k5-全书知识-bundle-绑定与审核入口)、[全书知识抽取预检](development.md#2026-11-21-k5-全书知识抽取预检)及[全书知识候选语义审核](development.md#2026-11-21-k5-全书知识候选语义审核)；I4 扫描回归历史见[开发记录](development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)。
- `已验证` hosted run `44853150345` 对代码提交 `f6131b34396feec9d5f7145d0ace8b8a513c18d6` 的 Ubuntu/Windows Python 3.14 jobs 均通过依赖检查、非 E2E 单测和 loopback mock E2E；新 K5 审阅入口已包含在该验证中。此前 hosted run 的失败定位与修复见[开发与验证](development.md#持续集成)。
- `已验证` hosted run `44843028671` 对当前文档提交 `d569d3cecc4a4b249d1040f7c79d3a226019e9c1` 的 Ubuntu/Windows Python 3.14 jobs 均通过；该文档提交未改代码，前一实现提交 `180afdcb5f0f0b9f353819cf5ef57e445b412179` 的 CI 也通过。CI 细节见[开发与验证](development.md#持续集成)；CodeRabbit 为 `SKIPPED`。
- `未验证` 依赖仍未锁版本；该矩阵不代表其他 Python 版本/操作系统支持，也不验证真实 Provider、语义质量、K5 人审或部署。
- CI 实现、历史失败定位和复现命令见[开发与验证](development.md#持续集成)。

## 2026-11-21 K5 全书知识运行时绑定

- `已实现` glossary AI 来源与 archive normalized 来源采用分离的原始字节/规范化文本哈希核验；全书发布要求完整 AI 章节 map 与 bundle identity，严格 RAG 再核验当前映射和 bundle，Kakuyomu 项目入口传入从已验证 bundle loader 得到的身份。
- `已实现` 全书审核 CLI 从当前 catalog、checkpoint、bundle-set、AI/人读版根重载并验证 bundle，再派生来源 map 与 expected identity；CLI 不让调用者自行声明“已验证”map。
- `已验证` 相关定向回归 240 项通过；完整非 E2E 798 项运行、5 项 Windows 能力跳过、0 失败；loopback mock E2E 7 项通过（219.369 秒）。首轮 mock E2E 找到过时的合成 glossary fixture 缺字段，按当前 schema 补齐后复跑通过。
- `部分实现` 只实现候选发布与运行时来源门禁，不会生成/语义审核全书知识。回执未签名；当前试点仍无 reviewed 全书知识、run、真实译文或真实 Provider 记录。下一步按[路线图 K5](roadmap.md#2026-11-21-k5-结构审阅后续状态)继续。

## 2026-11-21 K3 正式润色失败门禁

- `已验证` 正式项目的润色阶段返回不可读响应时会阻断章节事务：不写出译文、不更新 TM，且 StageReport 将失败归属到 `polishing`。此行为有新增 `run_chapter` 集成回归覆盖。
- `部分实现` 该门禁只验证结构化响应和阶段/事务状态，不判断译文是否达到语义上的“信、达、雅”；独立语义质量阈值仍需经人工定义和验收。
- 详细测试命令、计数与边界见[开发与验证](development.md#2026-11-21-k3-正式润色失败事务门禁)。

## 2026-11-21 I4 已发布译文新鲜度审计

- `已实现` I4 freshness snapshot 新增 `published_translations` consumer：依据当前版本化话目映射，扫描对应输出根下的 K4 runs，校验历史来源 artifact、审核快照、发布回执及可见译文字节；仅当输出与有效发布证据一致时标为 `verified`，来源版本变化标为 `stale`，缺失或无有效回执按具体情况标为 `unindexed`/`unverified`/`invalid`/`mismatch`。
- `已实现` 审计还递归发现当前映射外残留的 Markdown 输出并标为 `unindexed`，熟肉根内符号链接为 `invalid`；遍历最多处理 100,000 个目录项，不跟随链接或读取正文，扫描受限时标为 `unverified`。
- `已实现` `scripts/snapshot_downstream_freshness.py --runs-root ... --project ...` 可显式请求该审计；Kakuyomu 编排和项目采集在有完整当前 AI 话目映射时自动纳入 run/output 状态。AI edition index 不是 `verified` 时，译文新鲜度会在快照构建阶段降为 `stale` 或 `unverified`，并与最终 consumer 摘要一起计算摘要。
- `已验证` 最新完整非 E2E 回归 792 项运行、787 项通过、5 项 Windows 能力跳过、0 项失败；loopback mock E2E 7 项通过（210.577 秒）。新增回归覆盖嵌套未映射 Markdown、扫描上限、符号链接拒绝和目录枚举失败；普通权限/管理员安全路径结果和用户另行报告的历史结果分别见[开发记录](development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)。
- `部分实现` 本审计只读且只核验已有 K4 证据和当前可见输出，不修复或重译 stale 译文，不写回 TM/知识库，也不替代正式运行时门禁。当前 AI 映射不可用时，若项目采集检测到非空 run 根或译文文件，会记录聚合 `current_mapping_unavailable` 的 `stale`/`unverified` finding，不声称逐话已核验；两根均为空时不生成 consumer。显式快照 CLI 的 `--runs-root` 仍要求可加载当前项目映射。
- `未验证` 当前试点已有 AI 结构审阅与匹配计划回执，覆盖 88 话映射、来源 lineage、AI/人读文件字节和清洗 profile；这不等于语义内容或阅读器视觉验收。当前仍无 reviewed 全书知识、翻译 run 或译文，也未连接真实 Provider；此功能不构成部署验收。
- 详情和当前工作树证据见[开发与验证](development.md#2026-11-21-i4-k4-已发布译文新鲜度审计)。

## 2026-11-21 K5 门禁复核

- `已验证` 当前只读预检仍返回 `ready_for_review`、88/88 来源有效、0 issue/目标冲突/网络请求/Provider 调用/文件写入，`source_text_included=false`；摘要与计划绑定值一致。
- `已验证` 当前 raw/AI/人类版 88 话经 `validate_source_editions.py` 字节与 lineage 校验通过；用户指定的 `book-ai.json` 与其 bundle-set 经正式 loader 验证通过，摘要及范围见[开发与验证](development.md#2026-11-21-k5-只读门禁复核)。
- `已实现` `scripts/create_verified_translation_plan_review.py` 只在全量双版本 validator 返回 `verified` 且话数/AI 与人读索引摘要均匹配当前计划时，才 create-only 生成结构审阅；三类决定限于映射、来源 lineage、文件字节和清洗 profile，不调用模型/API。
- `已验证` Codex AI 依据当次 88 话计划预检、raw/AI/人读版全量重算及 HTML archive replay，创建独立结构审阅，mapping/AI edition/human edition 各 88 项 `pass`、0 issue；审批 CLI 创建并复核 schema v2 回执，绑定计划 SHA `63b286ca...` 和 review SHA `92a37df0...`。原始 264 项 pending 模板保留不变。
- `部分实现` 结构审阅明确不证明逐段语义保真、第三方阅读器视觉呈现或平台公开目录以外的作品完整性。`Workflow/Runs/` 与 `Knowledge/STORY_SUMMARY_reviewed.json` 仍不存在；没有翻译 run 或译文。
- `用户报告` 部分单话与合集抽样未发现明显问题；该局部结果单独记录，不作为本次 88 话全量结构审阅的证据。抽样详情见[开发与验证](development.md#2026-11-21-用户报告的原文抽样核实)。
- `未验证` reviewed 全书知识、真实 Provider 路由/授权/预算、译文语义质量、阅读器视觉效果和部署仍未验证；创建审批回执没有触发翻译。具体命令、摘要与边界见[开发与验证](development.md#2026-11-21-k5-codex-ai-结构审阅与计划审批)。

## 2026-11-21 PR #71 自检与恢复修复

- `已实现` 非正式 pipeline 校验章节映射目标，阻止绕过审核写入正式发布目录；正式 Kakuyomu 新 run 忽略没有本次 Drafts 输出对应的孤立 TM 键，让新逐章事务提交译文及候选记忆；失败后恢复会把 `recovered` 结果补入阶段报告；create-only JSON 写入先完整落盘再原子发布。
- `已验证` 新增及扩展六项回归覆盖目标路径、孤立 TM、知识预检、阶段恢复记录幂等和原子 JSON 写入。定向 181 项通过；全量非 E2E 776 项运行、772 项通过、4 项 Windows 能力跳过；loopback mock E2E 7 项通过、402.149 秒、退出码 0。没有连接真实 Provider。
- `部分实现` `Knowledge/translation_memory.json` 仍是共享可写候选存储。新事务成功时可能替换没有当前 Drafts 输出对应的旧词对；TM 无版本历史且未实现多写入者协调。已审核快照仍是正式默认检索来源。
- `未验证` 试点 88 话映射/双版本验收、匹配计划回执、reviewed 全书知识、真实 Provider/译文质量和部署仍未完成；依赖仍未锁定，也没有 UI、容器或云部署清单。当前 hosted CI 基线见本页首节。实施和审查项归类见[开发与验证](development.md#2026-11-21-pr-71-安全与恢复缺陷修复)。

## 2026-11-21 PR #71 批量发布 bundle 校验优化

- `已实现` 批量审核/发布在首个有效发布输入时验证整书 AI bundle 一次，批次结束、run 状态协调前再校验一次；episode 级 AI 索引和来源仍逐话核验。单话发布保持原有逐次完整 bundle 校验。大 bundle 仍使用独立 512 MiB 聚合上限，不受 16 MiB run manifest 上限影响。
- `已验证` 16 MiB 以上 bundle 回归确认批次中重复输入只触发一次完整 bundle 校验，批尾再次校验可拒绝改写；翻译审核、审核状态、Kakuyomu 编排和流水线契约 271 项通过。完整非 E2E 772 项运行、768 项通过、4 项 Windows 能力跳过、0 失败；loopback mock E2E 7 项通过（367.555 秒，退出码 0）。详情见[开发与验证](development.md#2026-11-21-pr-71-批量发布-bundle-校验优化)。
- `未验证` 此优化未连接真实 Provider，也未做 88 话真实 run 性能基准；对真实书籍的 wall-clock 提升量尚无测量。K5 人工映射/双版本审阅、匹配审批和 reviewed 全书知识仍是正式翻译前置项。

## 2026-11-20 PR #71 审查跟进

- `已实现` 对终审决定链与人工仲裁增加摘要绑定、追加前链校验和并发快照一致性保护；对 AI 返工在锁内读取改用内部无锁 helper，避免文件锁重入。历史发布复用按话目来源身份校验，不要求旧发布绑定当前整本索引摘要。正式 Kakuyomu run 强制要求 reviewed glossary；配置了 API 池回退时预检不要求不可达的 Gemini 路由。
- `已验证` 依赖更新后完整非 E2E 回归 772 项运行、768 项通过、4 项 Windows 能力跳过、0 失败；普通权限安全路径模块 11 项运行、7 项通过、4 项跳过（3 项符号链接缺少权限、1 项 FIFO 不受 Windows 支持），管理员权限重跑 11 项运行、10 项通过、仅 FIFO 跳过且 3 项符号链接均通过；完整本机 mock E2E 7 项通过（368.550 秒，退出码 0）。`.venv` 的 `pip check` 无冲突，`pip-audit` 未报告已知漏洞；`compileall`、Markdown 本地链接目标及 `git diff --check` 通过。初次 E2E 暴露 reviewed glossary fixture 缺失，补齐合成审核 bundle 后复跑通过。详细环境差异见[开发与验证](development.md)。
- `未验证` 真实 Provider、译文语义质量、K5 全书人工映射/双版本审核和部署；截至本记录日期（2026-11-20），仓库尚无 CI。2026-11-21 已增加并验证 Ubuntu/Windows Python 3.14 hosted CI；依赖仍未锁定，也没有 UI、容器或云部署清单。完整边界及测试命令见[开发与验证](development.md#2026-11-20-pr-71-审查跟进与完整回归)。

## 2026-11-20 K4 AI 工作流 CLI 验证

- `已验证` 用户入口 `scripts/run_ai_translation_workflow.py` 的参数转发、配置/终审/返工静态预检、JSON 输出和预检拒绝路径均有 CLI 回归覆盖；另从此 CLI 入口以合成模型响应跑通 run 草稿的终审失败、定向返工、复审通过和 create-only 发布。
- `已验证` CLI 到审核发布合成集成及 I4 provenance/freshness 定向回归 40 项通过；完整非 E2E 764 项运行、760 项通过、4 项因 Windows symlink/FIFO 能力跳过，0 失败；本机 mock E2E 7 项通过（212.461 秒，退出码 0）。负向夹具输出不表示测试失败。
- `未验证` CLI 回归使用 mock，不证明 Provider 连通性、语义质量或部署状态；真实试点仍待 88 话人审、reviewed 全书知识及获准的 Provider 首话试译。
- 详情见[开发与验证](development.md#2026-11-20-k4-ai-workflow-cli-contract)。

## 2026-11-20 I4 TM lineage fail-closed

- `已实现` 带来源 manifest 的 TM provenance 若缺少 `source_version_id`，只读审计现标为 `unverified`，不再因来源与译文字节相同就报告完整版本验证。未配置 manifest 时的旧式 hash-only 兼容审计保持不变。
- `已验证` 36 项 freshness/provenance 定向回归、93 项采集/编排集成、完整非 E2E 760 项（756 通过、4 项 Windows 能力跳过）及本地 mock E2E 7 项（206.248 秒）通过。审计快照记录状态，不写回 TM 或译文。
- `部分实现` I4 仍未把 stale 状态自动传播写回 TM、译文、知识消费者，也不自动重建派生物；K5 计划映射/双版本人审及 reviewed 全书概要仍未完成。
- 详情见[开发记录](development.md#2026-11-20-i4-manifest-bound-tm-lineage)及[来源版本计划](source-ingestion-and-publication-plan.md#i4-manifest-bound-tm-lineage-2026-11-20)。

## 2026-11-20 K5 试点门禁复核

- `已验证` 当前试点计划 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.json` 为 `ready_for_review`，88 话、88 个来源有效、0 个 plan issue；摘要为 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`。计划绑定 `source_catalog.raw-html-2026-11-17.json`，不应替换为摘要不同的 `source_catalog.discovered.json`；后者会触发 88 个 `stale_ai_edition_catalog`，属于输入不匹配，不是当前计划失效。
- `已验证` 使用计划绑定的 catalog、manifest、AI 输入根及译文根执行 `scripts/run_kakuyomu_workflow.py --plan-only`，返回同一计划摘要、88/88 来源有效、0 issue/目标冲突/网络请求/Provider 调用/文件写入，且 `source_text_included=false`。同一来源清单下 `scripts/validate_source_editions.py` 返回 `verified`、88 话；AI/人读版输出分别为 774,253/799,293 bytes。该验证证明版本与文件一致性，不证明语义保真或人工阅读质量。
- `部分实现` 当前人审模板与计划摘要、AI 索引和人读索引均匹配；`mapping_decision`、`ai_edition_decision`、`human_edition_decision` 各 88 项仍为 `pending`。`Workflow/Approvals/` 和 `Knowledge/STORY_SUMMARY_reviewed.json` 不存在，因此尚无匹配计划审批回执或 reviewed 全书概要；没有产生知识、译文或正式产物。
- `用户报告` 2026-11-21 人类版与 AI 版的部分单话文件及大合集抽样未发现明显问题；实际检查日期、样本清单和标准未知，不代表全量验收。目录与对象路径、复核边界见[开发与验证](development.md#2026-11-21-用户报告的原文抽样核实)。
- `未验证` 真实 Provider、模型路由/计费、译文质量和部署仍未验证。下一步先由有权限的人完成模板中的映射及双版本审核并生成匹配回执，再审核当前 bundle 绑定的全书知识；之后由凭据所有者核验端点、授权、模型路由和预算，执行获准单话试译及人工质量验收。用户已确认作品授权和职责所需数据类别，不应重复列为待确认项。
- 完整命令、摘要、索引绑定和验证边界见[开发与验证](development.md#2026-11-20-k5-试点门禁复核)及[当前交接](handoffs/2026-11-15-translation-workflow.md)。

## 2026-11-20 K4 自动返工与复审

- `已实现` 新增 `scripts/run_ai_translation_workflow.py`，显式运行或恢复单话有限循环：双次终审、finding 定向返工、复审，直到通过发布或进入人工状态。不会在初译流水线中自动触发。
- `已实现` `ai_translation_rework.py` 将完整 source/candidate、阻断 findings 和命中的策略定义发送给 `PROOFREAD_MODEL`，最多 64,000 个合并字符，不发送 book knowledge；严格解析 JSON 后只替换目标译文段落，并复核候选字节、段落映射和现有日文引号契约。终审与返工路由必须是不同的规范化端点/模型身份。
- `已实现` 下一候选和内容无关 sidecar 分别 create-only 写入 `ReviewCandidates/<episode_id>/revision-NNNN.md` 与 `AIReworks/<episode_id>/revision-NNNN.json`。摘要绑定父决策/候选、来源、策略、报告、findings 与路由。重跑可复用既存候选；未配套生成记录的候选会标记 `reused_existing`，不伪称由本次模型生成。
- `已实现` 只有 `quality_failure` 的 `rework` 可自动修订；`rework_limit_reached` 必须先有人工 `increase_budget` 回执。`approve_current` 仍转入人工八项 checklist，不会由 AI 自动发布。预算回执成功结果包含 `new_max_rework_attempts`，供调用方核实获准的新预算并续跑。模型返回不合 schema、目标索引不完整、候选冲突、内容过长或授权/路由预检失败时，停止且不发布。
- `已实现` 单话 AI 终审、返工及总工作流共用 run 内 `AIWorkflowLocks/<sha256(episode_id)>.lock` 异步文件锁。同一事件循环的等待通过异步轮询让出执行权；跨进程使用操作系统文件锁。决策追加仍由独立话目锁保护，锁目录位于 `ReviewDecisions/` 外，不会因评估失败创建决策目录。
- `已实现` 终审每次结构化评估通过校验后，都会把只含规范化字段的 sidecar 原子 create-only 写入 `AIReviews/<episode_id>/`，并绑定 run、source、candidate、policy、reviewer route 和评估序号。重试先校验并复用已完成评估，只调用缺失的评估；报告与决策 schema 不变。
- `已验证` 新增两个终审恢复用例：第一份评估 sidecar 落盘后进程终止，恢复只请求第二次评估并完成发布；sidecar 身份篡改会在 Provider 调用前拒绝。原有返工/续审/发布、恢复和并发测试仍覆盖重复终审复用评估、并发只生成一份返工候选、跨进程互斥、锁恢复、快照写失败及发布过程两个认证进程终止点。终审与状态模块 106 项通过；当前工作树定向回归 269 项通过，完整非 E2E 动态发现 758 项运行、754 项通过、4 项 Windows symlink/FIFO 能力跳过；本地 loopback mock E2E 7 项通过（208.149 秒）。结构测试使用合成 assessor/generator，不调用真实 Provider 或试点正文；进程终止测试只证明指定用户态边界，不证明内核崩溃或断电持久性。完整复核命令见[开发记录](development.md#2026-11-20-当前工作树回归复核)。
- `部分实现` 定向修改依赖 reviewer findings 的完整性与准确度；代码只证明格式/版本绑定，不证明修订确实解决问题或保留所有语义。Provider 已返回但评估 sidecar 尚未原子落盘时终止，恢复仍可能重复该次请求及费用；返工候选也有对应的响应后落盘窗口。收益门仍为模型自报的定性 `none/low`，无默认质量 taxonomy 或语义阈值。
- `未验证` 真实 Provider、API profile/凭据、译文质量、试点 88 话审批和正式产物均未验证。本地应用是 CLI，无可部署服务。
- 详细契约、命令和验证见[翻译流程](translation-workflow.md#ai-终审与发布)、[逐次评估恢复记录](development.md#2026-11-20-k4-终审逐次评估持久化)和[返工续审记录](development.md#2026-11-20-k4-ai-返工续审工作流)。

## 2026-11-20 K4 AI 终审执行器

- `已实现` `scripts/review_translation_candidate.py` 显式运行一个话目的 AI 终审。它校验 run/source/candidate 与策略文件，要求原文和候选段落数对齐，默认最多发送 64,000 个合并字符且不截断；对同一候选顺序发起两次无会话的结构化评估。完整原文和候选会发送到配置的终审 Provider；代码不存储模型自由文本意见。
- `已实现` 仅当两次均通过三阶段、两次均报告 `none` 或 `low` 优化潜力、且两次均将八项检查全部判为 pass，决策 schema v4 才会记载两个最终门。AI 审核快照绑定决定和候选，并调用现有 create-only 发布器。任何失败均不发布；失败且预算尚余时返回 `rework`，冲突、不确定、终审门不满足或预算耗尽返回 `needs_human`。
- `已实现` 初审返工预算默认 2，可用 `--max-rework-attempts` 覆盖；续审须沿用决定链中预算，预算扩展须先追加人工仲裁回执。策略文件以原始字节摘要存入 `ReviewPolicies/`，新 code/门禁决定使用 schema v4；旧决策 schema 保持读取兼容。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review tests.test_translation_review_state -q`：91 项通过，含双评估发布/恢复、报告篡改拒绝、失败原因摘要、失败不发布、意见冲突、收敛不足、零返工预算、重复 JSON 字段及草稿变更拒绝。当前完整非 E2E 回归 740 项运行、736 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（212.673 秒）。`py_compile`、CLI `--help`、本地文档链接目标和 `git diff --check` 均通过。审阅测试使用合成 run 与注入 assessor，未调用真实 Provider。
- `部分实现` `none/low` 是对“继续优化边际收益降低”的定性代理，模型自报八项检查不是语义正确性的证明；两次请求走相同 reviewer route，不能证明判断在统计或语义上独立。此记录形成时 `rework` 仅返回状态；自动续接行为见本页上方 2026-11-20 增量。
- `未验证` 本机 API profile/凭据、真实 Provider 行为、模型上下文容量、语义质量和项目试点。项目 88 话映射/双版本验收、匹配计划审批与 reviewed 全书知识仍未完成；没有运行真实项目文本或启动服务。详细实现与回滚边界见[开发记录](development.md#2026-11-20-k4-ai-终审执行器)。

## 2026-11-20 K4 人工仲裁与预算续接

- `已实现` 新决策链默认最多返工 2 次，可由 CLI 覆盖。耗尽后 `scripts/resolve_translation_review.py` 可创建明确的人工 `approve_current` 或严格增加返工预算；回执绑定当前失败决定和候选版本，不将失败 verdict 改成 AI 通过。
- `已实现` 人工放行只解锁 schema v3 checklist，仍须完成现有八项检查后才可发布。增加预算可从同一决策链追加一个版本，要求候选路径、父摘要、策略摘要及新预算全部匹配。
- `已实现` 决策 schema v2 显式记录分阶段 `issue_codes_by_stage`；可选 schema v1 策略登记表启用 schema v3 决策，并按内容 SHA-256 归档到 run，校验 code 定义和阶段归属。CLI 对阶段判定 JSON 拒绝重复字段和非有限数值。v1/v2 记录仍可读取；兼容 v2 输入不验证策略语义。
- `已验证` 策略绑定和 K4 审核定向回归 81 项通过；全量非 E2E 727 项运行、723 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（209.005 秒）。`py_compile`、CLI help、修改文档链接及 `git diff --check` 均通过。结果绑定当前混合工作树，详细范围见[开发与验证](development.md#2026-11-20-k4-策略文件绑定)。
- `部分实现` 当前只有由策略维护者提供的 code 登记表契约，没有项目默认质量 taxonomy、跨话目作用范围或豁免逻辑；相同 code 不会让其他话目自动豁免或跳过人工暂停。人工仲裁 reviewer 身份不认证；AI reviewer 执行器已实现合成路径，但真实 Provider/语义质量及客观收敛阈值仍未验证。
- `未验证` 本地 API 池、真实端点、试点 88 话映射/双版本审批、reviewed 全书知识、正式翻译 run 和 `熟肉` 产物均未在本次读取或执行。

## 2026-11-20 API 池 v2/v3 与可配置 embedding

- `已实现` API 池 schema v2 保存生成配置及可选的 Gemini/OpenAI-compatible embedding 配置；embedding Key 使用单独的 Windows Credential Manager 引用，授权类别限制为 `source_text`。含终审槽的新配置使用 schema v3，并沿用 v2 embedding 字段。
- `已实现` 交互向导支持独立启用 embedding，并要求确认接收方授权后才读取 Key。API 池 v1 可加载；只有用户明确确认后才备份并迁移到 v2。替换失败保留旧配置及旧凭据引用。
- `已实现` 新配置可选绑定 `FINAL_REVIEW_MODEL`；配置后使用 schema v3，校验终审与初译使用不同的规范化端点/模型身份，并要求终审接收方授权全部三类翻译数据。v1/v2 仍按原契约读取，v1 显式迁移仍生成 v2；运行时有意清除未配置的旧终审环境值。此项不发起审核，也不证明模型在语义上独立。
- `已实现` RAG、TM 写入和章节对齐共用 embedding 适配器；OpenAI-compatible 向量身份包含模型、Provider、端点摘要与维度。未知或不兼容向量保留但不参与检索。
- `已实现` `scripts/rebuild_tm_embeddings.py` 生成 source-verified 的新 TM 候选文件；原 TM 和 reviewed snapshot 不覆盖。现有逐对审核/发布流程可接收此候选，正式切换仍由操作者审查并设置 `TM_REVIEWED_PATH`。
- `已验证` API 池 v3 角色绑定定向回归 22 项通过；相关 API 池、pipeline 和 Kakuyomu 模块 176 项通过；完整非 E2E 回归 730 项运行、726 项通过、4 项 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（206.907 秒）。覆盖 v1/v2 兼容、v3 凭据摘要往返、授权类别、路由区分及旧环境变量清理；未访问真实 Provider。详见[开发记录](development.md#2026-11-20-api-池可选终审角色)。
- `已验证` 新增迁移/授权/凭据回滚、embedding 协议和 TM 候选隔离合成测试。完整非 E2E 回归 704 项运行、700 项通过、4 项因普通 Windows symlink/FIFO 能力跳过；mock E2E 7 项通过（239.655 秒）。详见[开发与验证](development.md#2026-11-20-api-池-v2-与可配置-embedding)。
- `未验证` 本机 API 池 profile 未读取，故其版本和迁移状态未知；真实端点兼容、计费、质量、实际授权与部署未验证。本机 TM 未重建或切换。试点 88 话映射/双版本审核、计划审批回执和 reviewed 全书知识仍是正式翻译前置条件；K4 人工仲裁和 AI 终审均只有合成路径验证。API 池配置本身不发起审核；显式 reviewer CLI 会使用 `FINAL_REVIEW_MODEL`，但真实端点尚未验收。

## 2026-11-20 Gemini embedding 与 TM 身份

> 阶段快照：以下是 API 池 embedding Provider 配置接入前的状态；当前配置/迁移事实见本页上方“API 池 v2 与可配置 embedding”。

- `已实现` RAG 和章节对齐现共用 `embedding_provider.py` 的 Gemini Embedding 2 调用和向量身份定义；TM 新向量保存 schema、Provider、协议、模型、task type 与维度。
- `已实现` TM 查询和章节语义回退排除没有身份或身份不匹配的向量。旧向量和审核数据被保留，尚未自动重建；对旧 reviewed TM 的影响是可能不再返回向量匹配。
- `已验证` 当前工作树非 E2E 682 项运行、678 项通过、4 项因普通 Windows 进程的 symlink/FIFO 能力跳过；本地 mock E2E 7 项通过（235.372 秒）；RAG/对齐/TM 审核定向集 64 项通过。命令、具体身份字段和验证边界见[开发与验证](development.md#2026-11-20-gemini-embedding-与-tm-向量身份)。
- `未验证` API 池 embedding 配置、版本化配置迁移、旧 TM 重嵌入、真实端点兼容/质量及部署。没有调用真实 Provider、网络服务或项目原文。

## 2026-11-19 当前工作树续验

- `已实现` 版本化空来源通过章节事务提交空产物和 provenance，支持一致性复核及正式 run 阶段记录；重试验证后跳过。
- `已实现` 新采集的原始 HTML 响应字符集已规范化并写入 episode metadata，沿 metadata parent 关系绑定到 HTML artifact；回放按 charset 解码，旧记录缺字段时兼容 UTF-8，原始响应 bytes 不变。
- `已实现` AI 索引验证会复核索引绑定的 catalog 当前字节摘要和完整 episode 映射；catalog 原路径内容变化、重排或删项会阻断使用。
- `已验证` 当前分支最近一次非 E2E 回归 666 项运行、662 项通过、4 项跳过：普通权限下 3 项符号链接用例因 `WinError 1314` 跳过、1 项 FIFO 用例因 Windows 能力限制跳过；另一次提升权限安全路径模块运行 11 项、10 项通过，3 个符号链接用例通过、1 项 FIFO 跳过。本次 mock E2E 7 项通过，201.455 秒；试点 HTML archive validator 另有 88/88、356 文件有效、`verified` 的只读结果。命令和证据范围见[开发与验证](development.md#2026-11-19-审核决定并发与人读版身份绑定修复)。
- `未验证` Shift_JIS 仅经合成 fixture 验证，未对站点做 live 请求；真实 Provider、译文质量、人工试点映射/双版验收及线上部署仍未验证。

## 2026-11-19 续跑与结构化审批回归

- `已实现` AI 版计划审批要求绑定已完成的映射/双版本结构化审阅摘要；续跑会从待翻译输入和 run manifest 中排除已核验发布的话目，同时保留对完整计划和整书知识覆盖的校验。
- `已验证` 相关 5 个测试模块 211 项通过；完整非 E2E 回归 645 项运行、641 项通过、4 项因 Windows 符号链接权限/FIFO 能力跳过；本地 mock E2E 7 项通过。准确命令和限制见[开发记录](development.md#2026-11-19-续跑恢复与审批发布复核)。
- `未验证` 当前 runner 无符号链接创建权限，故 3 项路径边界测试未执行；FIFO 测试在 Windows 平台不适用。此次验证不调用真实 Provider、不证明译文语义质量或部署可用性。
- `未验证` 试点新计划的 88 话/264 项结构化决定仍待人类审阅和批准；用户报告的人类版与 AI 版文件抽样核实已单独记录，不能替代全量映射、清洗文本或阅读体验验收。

## 2026-11-19 K4 决策链发布门禁（历史快照）

- `部分实现` `translation_review_state.py` 要求 `fidelity`、`fluency`、`style` 三阶段均明确通过；显式预算内失败进入返工，缺报、不确定、冲突或耗尽转人工。`record_translation_review_decision` 将 run/episode/source、候选修订、run-relative 路径、父摘要、策略摘要和状态绑定为 create-only 决策链；调用者必须提供审阅时的候选 SHA-256，写入按话目串行并以完整 JSON 原子创建。审核发布还会校验人读版索引中登记的 artifact ID、版本、归档路径和摘要与已验证清单一致。
- `已实现` 发布器消费决策链：链尾未通过不能发布；链尾通过后，schema v2 人工 checklist 和回执绑定最终候选路径、版本及决策摘要。返工候选位于 `ReviewCandidates/<episode_id>/`，原始草稿不变；发布与 run 状态复核均比较批准候选的实际字节。没有决策链的旧 schema v1 checklist 仍可走原人工审核路径。
- `已验证` `.venv\Scripts\python.exe -m unittest tests.test_translation_review_state tests.test_translation_review -q`：47 项合成测试通过，覆盖旧路径、直通和返工发布、绕过拒绝、篡改、排他写入与状态恢复。该结果不证明真实 Provider、语义判定或审核身份。
- `未验证` 终审 Provider/model、语义阈值、生产返工上限、冲突/耗尽时人工响应仍未确定；`needs_human` 目前硬停止，尚无同一 run 的人类仲裁回执/恢复入口，不能把旧 checklist 当作绕过。hash 不认证审核者或策略执行。当前仅为本地 CLI，没有部署服务。当前试点尚未生成 run/译文；计划模板 88 话、264 个决定仍为 pending，未创建计划回执或 reviewed 知识。
- `已验证` 门禁接入后完整非 E2E 回归 630 项运行，626 通过、4 项因 Windows FIFO/符号链接能力跳过、0 失败；mock E2E 7 项通过（418.613 秒）。这是合成验证，不证明真实 Provider、语义质量或审核身份。完整命令与边界见[开发记录](development.md#2026-11-19-k4-决策链接入审核发布门禁)。

## 2026-11-19 K3 阶段轨迹续接

- `部分实现` 正式项目的 `StageReports` 将校对、反思重译和润色分别保存为哈希化尝试列表，并在阶段异常时记录子阶段名称。仅校对回执中保留模型给出的严重度枚举；不存批注或正文。它仍是调用轨迹，不是“信、达、雅”独立审核报告、评分、终审或质量证明。
- `已验证` 本次定向回归覆盖三类子阶段的分离、重复校对/反思尝试、Provider 异常归属及轨迹不含原文/译文/批注；完整验证命令与结果见[开发与验证](development.md#2026-11-19-正式项目校对反思润色分项轨迹)。

## 2026-11-19 K5 试点计划续接

- `已验证` 当前无网络预览核对了 88/88 `RAWs_AI` 来源和计划字段，0 问题；检测到旧计划的 88 个 TM key 仍为 `kakuyomu:`，与当前 `source-edition:` 契约不匹配。来源版本、AI 索引/manifest 与其余映射字段一致。
- `已实现` 已在 `Workflow/Plans/` create-only 新建 schema v2 计划 `translation_plan_review_ai_raw_html_schema2_2026-11-19.json`，摘要 `63b286ca64e506e467239035c779f834acdc699c5765b4988e8b2088c013a329`；状态 `ready_for_review`，88/88 来源有效、0 问题。摘要由当前 `translation_plan_approval.load_translation_plan` 复核一致。
- `已实现` 新增内容无关的结构化审阅模板：`scripts/prepare_translation_plan_review.py` 绑定当前计划与人读 `SOURCE_MAP.json` 的摘要，逐话保留映射、AI/人读文件哈希及 `mapping`、`ai_edition`、`human_edition` 三项决定；审批 CLI 可用 `--review`/`--human-index` 将已全部通过的模板摘要写入 schema v2 回执。模板与回执均 create-only，模板不保存章节正文。
- `已验证` 合成测试覆盖 pending 拒绝、三项通过后 v2 回执、索引伪报哈希/章节变化拒绝和旧回执兼容；实际试点只读核对通过 88 个章节文件，已生成待审模板 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-19.human-review.json`。264 个逐话决定仍全部 pending，审批验证按预期拒绝；`Workflow/Approvals/` 当前目录不存在，未生成回执。仍需人工审阅 88 话映射及两种清洗版本。
- `已验证` 2026-11-19 重跑双版本 validator，88 话 `verified`；从 raw 重算出的 AI/人读字节数分别为 774,253/799,293，新计划绑定的 AI 索引摘要与当前索引一致。该结果证明版本、文件哈希和确定性清洗一致，不证明文本语义或阅读观感通过。
- `未验证` 新计划尚未人工批准；当前无匹配审批回执，Knowledge 目录无 reviewed 全书概要或术语表。AI/人读版本质量、Provider 端点兼容和真实单话翻译仍未验收。详情见[开发与验证](development.md#2026-11-19-试点计划映射续接核验)与[当前交接](handoffs/2026-11-15-translation-workflow.md)。

## 2026-11-18 文档复核基线

- `已验证` 本次文档复核开始时，分支 `codex/translation-workflow-audit-20261117` 指向 `7ea8e1012878a7d9ea7ad8302b3666b5bf114115`；存在一个既有未跟踪 JSON 文件，未读取或修改其内容。本机项目虚拟环境 Python 为 3.14.7，`python -m pip check` 报告无已安装依赖冲突，且能找到 Pandoc 可执行文件。依赖未锁定；这些检查不证明全新安装、EPUB 渲染或生产部署可用。
- `部分实现` 路线图阶段 0–3 均有局部实现，阶段 4 有局部实现但未验收，阶段 5 仍为 `计划`；局部验证不等于阶段完成。当前代码具备版本化采集、双版本及三版合集、全书/单话知识候选及局部人工审核、翻译草稿、逐话审核和可恢复的批量发布；未审核 pipeline 必须显式声明 `compatibility_draft`，项目发布根仍有独立保护。当前工作树另有 OpenAI-compatible API 池向导、Windows Credential Manager 凭据保存、三个既有生成绑定和一次性授权备用路由的部分实现；仅合成验证，未测试真实端点。RAG/对齐共享 Gemini embedding 适配器但仍独立配置，旧 TM 向量尚未重建。入口契约与剩余工作见[兼容入口保护](development.md#2026-11-18-兼容入口正式目录保护)、[模型与 API 配置方案](model-provider-configuration-plan.md#2026-11-20-api-池配置)，整体门禁见[全书到单话工作流](end-to-end-workflow-target.md#当前输入输出与门禁)。
- `未验证` 本次未重新运行代码测试、采集、真实 Provider 或 Notion；未重新检查试点数据、人工验收正文与映射、模型质量、凭据状态和真实部署。历史的 88/88 公开目录及本地测试仅对其记录的时间、输入与环境有效；公开目录不包含私有或未公开内容。
- `部分实现` 审核回执绑定版本和内容，但 reviewer/独立性字段未认证；现有人工审核发布不等于 AI 独立终审或有限返工。TM 默认仅检索已配置且来源核验通过的审核快照，未配置时不检索候选；显式兼容开关是例外而非默认。来源更新的快照审计不自动完成全链路失效传播或重建。
- `部分实现` 正式项目翻译现在在 `Workflow/Runs/<run_id>/StageReports/` 追加不含原文、译文和提示词的阶段哈希轨迹，记录阶段状态、输入/输出摘要、模型标识、失败类型及重复尝试；该文件用于运行审计，不等同于“信、达、雅”独立审核报告、语义评分或终审结论。
- 引用会话：本次通过 `read_thread` 读取三条用户引用会话的近期内容；部分较早分页和过长响应未完整审阅，不推断不可见历史。会话用于识别用户目标及决策，代码和带范围的验证记录用于核对实现。

> 当前汇总（2026-11-17 原始 HTML 全量刷新后）：来源 manifest 356/356、合并 edition manifest 532/532；HTML 回放验证器对 88/88 个最新页面响应按 parser v4 重放出与当前 `raw_source` 一致的正文哈希，双版本 validator 也对同一批 raw source 返回 `verified`。默认翻译输入是从 `RAWs_AI` 直接读取的 `ai-efficient-v1`；`SourceArchive` 只保留版本归档和来源校验数据。当前映射计划为 `ready_for_review`、88/88 来源有效、0 问题；映射/清洗人工验收和真实翻译尚未完成。下方较早的日期记录保留其检查时的数字，不代表刷新后的当前计数。

> 2026-11-18 单话知识候选阶段检查点：抽取器新增互斥 `--chapter-position N`，从当前 verified AI bundle 只读取指定话，并按来源版本隔离保存带段落证据的知识草稿；复用 tokenizer/context/call 预算和 Provider 授权门禁。该检查点的抽取器单测 37 项通过、非 E2E 回归 542 项通过、4 项因 Windows 能力跳过。当时尚无审核/发布接口，翻译管线未消费这些候选；后续审核和上下文接入见下文。该检查点未重跑长时 mock E2E，也未调用真实 Provider。

> 2026-11-18 单话知识审核与上下文接入已完成本地实现：复用现有概要/术语回执发布器；Kakuyomu 翻译前预检所有待翻译非空章节的 approved 单话概要，按位置、当前来源/AI 输入哈希及同次整书 bundle 身份核验。每章上下文注入单话概要，局部术语表可选；局部/全局同词或别名译名冲突会阻断，逐章构建上下文时再次复核。跨模块定向回归 197 项、全量非 E2E 回归 551 项通过（4 项 Windows 能力跳过），mock E2E 7 项通过，详见[开发与验证](development.md#2026-11-18-最终续接验证)。未调用真实 Provider，试点 88 话仍未生成或批准知识。

> 2026-11-18 全书跨批候选综合：`scripts/auto_extract_knowledge.py --full-book` 在分批提取后，现按 tokenizer/context 预算对候选做分层 Provider 综合；综合请求只接收结构化候选，并要求 `source_text` 与 `book_knowledge` 均获授权。批次候选、每轮 lineage、token 预算和最终段落证据写入 provenance，由概要审核器复核。定向回归 63 项通过；此后的全量非 E2E 回归 551 项通过、4 项因 Windows 能力跳过，mock E2E 7 项通过。真实 Provider、目标 tokenizer/template 匹配、候选语义质量及人工审核仍未验证。该能力不等于已生成或批准本书知识草稿；详见[开发与验证](development.md#2026-11-18-全书跨批候选综合)及[最终续接验证](development.md#2026-11-18-最终续接验证)。

> 2026-11-17 默认项目知识门禁：`pipeline.py --project` 现要求来源版本有效的 `Knowledge/Glossary_reviewed.json`，与 reviewed 全书概要门禁并列。当前试点知识目录只有旧式 `Glossary.json`，尚无 reviewed glossary bundle；默认项目模式会在 RAG 初始化时失败关闭，不读取旧表。显式 JSON 配置保持调用者选择的兼容行为。合成回归 194 项通过；未读取术语正文或调用 Provider。详见[开发与验证](development.md#2026-11-17-项目模式已审核术语表门禁)。

> 2026-11-17 AI/人读清洗结果可重复验证：新增 `scripts/validate_source_editions.py`，对当前 catalog 的 88 话重读 manifest 绑定 raw 字节，分别重跑 AI 与人读清洗 profile，并逐话比较索引、不可变归档和镜像。当前结果 `verified`，输入 793,183 bytes、AI 输出 774,253 bytes、人读输出 799,293 bytes；没有输出正文或写入书籍数据。19 项双版本定向单测通过。该项证明当前文件与代码 profile 一致，不代替人工章节/语义/阅读器验收；详见[开发与验证](development.md#2026-11-17-ai-与人读版清洗产物可重复验证)。

> 2026-11-17 Kakuyomu 追加无变化复查：真实主页目录复查仍为 88 话；追加模式发现/完成 88 话、追加 0、复用 88、待处理 0，因此没有 episode 正文请求。本次只验证目录未新增时的真实路径，新增话正文抓取仍未 live 验证。安全刷新后 AI/人读索引各更新 1 个、章节 Markdown 未改写；基础 manifest 268/268 校验通过。默认参数 `--plan-only` 再次验证 `RAWs_AI` 索引对应的 `ai-efficient-v1` 版本，88/88 归档来源有效、0 问题、0 Provider/网络请求。TM 下游快照记录 19 条未索引；已审核全书概要缺失。定向采集/清洗/快照回归 56 项通过。详见[开发与验证](development.md#2026-11-17-kakuyomu-追加无变化复查与-ai-默认输入)。

> 2026-11-17 试点路径与产物复核：`workflow_paths.json` 指向的括号版外部 `生肉`/`熟肉` 目录均存在；人读版 `SOURCE_MAP.json` 加 3 个章节目录，话数为 30/40/18，共 88；AI 根有 88 个单话 Markdown，译文根为空。原始与双版本 manifest 分别通过 268/268、444/444 文件校验。当前默认 AI `--plan-only` 返回 `ready_for_review`、88/88 来源有效、0 问题且未输出正文。映射及格式仍待人工验收，未生成审批回执或译文；详见[开发与验证](development.md#2026-11-17-试点数据落点与目录复核)。

> 2026-11-16 只读复核快照：该快照记录的 `main` HEAD 为 `e2fe611`（PR #70），当时工作区干净；目录差异、纯追加、显式刷新和来源新鲜度门禁已合入该基线。Python 3.14.7 的 `pip check` 通过；试点 manifest 268/268 文件哈希通过，已有 catalog 的只读计划预览返回 `ready_for_review`，未输出正文。这些检查不证明映射已人工批准、正文格式完整或真实翻译质量。历史测试和真实刷新结果保留各自的基线及范围，未在本次续接重跑。本次续接开始时 HEAD 仍为 `e2fe611`，但 `docs/development.md`、`docs/project-status.md`、`docs/roadmap.md` 与 `docs/source-ingestion-and-publication-plan.md` 已有未提交改动，均予以保留并在其上更新。两条引用会话已在本任务较早阶段通过 `read_thread` 读取；本续接以项目代码和文档核对具体实施状态。

> 2026-11-16 Kakuyomu 显式正文刷新：在纯追加续采能力上增加按显式命令重抓完整目录正文、比较正文 SHA-256 和保留不可变 raw 历史版本。真实试点刷新重取 88/88 话，0 话变化；刷新后 manifest 268/268 文件哈希通过，计划预览 88 项、0 问题。旧 schema v1 基线不含章节分组，因此本次未验证旧/新分组相同。定向回归 109 项通过，`py_compile`、CLI `--help`、`git diff --check` 和 147 个本地 Markdown 链接目标检查通过。刷新只报告变化与下游复核提示，不会自动传播译文/概要/知识过期状态。详情见[开发与验证](development.md#2026-11-16-kakuyomu-显式正文全量刷新)。

> 2026-11-17 全书知识预读增量：显式全书抽取现依本地 tokenizer JSON 和调用者提供的模型 context/output/safety/message 预算按段落串行分批；所有配置段落恰好覆盖一次，每批最多 500 段、最多 100 次 Provider 请求。来源超限、单段超预算、响应无效、结论引用无效或中途 Provider 失败时不写草稿。批次摘要按来源顺序合并为带段落来源指针的候选集合，未做跨批模型综合。概要审核保留并校验批次预算与结论证据。定向 75 项通过、依赖检查通过；未调用真实 Provider，模型 tokenizer、服务端 chat template、context 参数与输出参数尚未验收。详见[开发与验证](development.md#2026-11-17-token预算分批全书知识预读)。

> 2026-11-17 原文双版本清洗与翻译接入：试点采集版本归档位于 `projects/祝福のネトラレラ/SourceArchive/`，AI 版位于 `projects/祝福のネトラレラ/RAWs_AI/`；用户指定外部 `D:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ(祝福的寝取系女主)\生肉` 专用于人读版，同书外部 `熟肉` 是译文根。两版都从采集器产出的同一份 88 话原文派生，只在清洗规则上按 AI 识别效率或人类阅读体验分别选择；不是不同来源或彼此复制。两版均为 88 话/3 组；人读版 88 个 Markdown + `SOURCE_MAP.json`，AI 版 88 个 Markdown + `catalog.json`。`source_manifest.json` 保留 268/268 采集 artifact；独立 `source_editions_manifest.json` 合并来源与 176 个派生版本，444/444 文件校验通过。88/88 人读版镜像与版本归档 SHA-256 匹配。Kakuyomu 编排器在完整采集后自动运行双版本清洗，默认从 `RAWs_AI` 读取 AI 清洗正文；章节映射的 `source_input_file`/`source_sha256` 指向并校验该正文，`raw_file`/`source_version_id` 只用于 `SourceArchive` 中的来源归档、版本 lineage 与溯源核验。`SourceArchive` 保存不可变归档内容及其清单/元数据，不作为 AI 正文读取源。AI 来源缺失、过期或目录缺项时停止，不改读归档文件或人读版。通用 `pipeline.py --project` 模式也默认直接从 `RAWs_AI` 读取 AI 版。试点 `workflow_paths.json` 保留外部 `熟肉` 译文根，并新增用户指定外部 `生肉` 人读根；不会改变 AI 默认输入。Kakuyomu 只有显式 `--source-edition normalized_source` 才改用采集版本；通用项目模式没有 AI 版时明确失败，旧目录必须由显式 JSON 配置指定。本轮路径实现与验证见[开发与验证](development.md#2026-11-17-raws-ai-作为默认翻译输入)。人读版观感与逐段保真、目录映射仍待人工验收；未调用真实 Provider、未生成试点译文。详见[双版本清洗实施](source-ingestion-and-publication-plan.md#2026-11-17-双版本清洗实施)。

> 2026-11-17 独立 Kakuyomu 采集新鲜度留档：`scripts/ingest_kakuyomu_pages.py --project <项目名>` 现可在明确项目边界下运行。它要求输入/输出根均为该项目 `SourceArchive/`，采集后同步来源历史到 `source_editions_manifest.json`，追加包含 AI 索引状态的只读快照；旧清洗文件和索引不被重写，索引过期时默认翻译入口仍会失败关闭。此模式不执行双版本清洗；完整采集到 AI 默认输入仍使用 `scripts/run_kakuyomu_workflow.py`。合成定向验证：来源清单 14 项、Kakuyomu 页面/CLI 33 项通过；不代表当前真实书籍目录被写入或刷新。详见[开发与验证](development.md#2026-11-17-独立-kakuyomu-采集的项目新鲜度留档)。

> 2026-11-17 试点 Provider 配置：忽略的根 `.env` 已为《祝福のネトラレラ》选择 JOJO `gpt-6-Luna` 作为三阶段主模型、JYQF `deepseek-v4.1-flash` 作为显式备用，并仅列出两方职责所需的三类翻译数据授权。配置不含凭据；Process/User/Machine 未设置 JOJO/JYQF key 或 endpoint，未调用服务。真实端点兼容、账号、账单与模型表现仍未验证；计划审批和 reviewed 全书概要门禁仍有效。

> 2026-11-16 I4 来源新鲜度审计补强（前一检查点）：TM、知识 provenance 和概要发布/运行时加载现在核对最新 normalized artifact 的 raw 父版本是否仍为 manifest 当前 raw 版本；raw 已更新但 normalized 尚未重建时报告 `stale`，父 lineage 或文件哈希无效时拒绝。该检查点 14 个相关测试模块共 295 项通过；后续当前工作集验证见下项。此项只读发现不自动重建派生物或持久化过期状态，详情见[开发与验证](development.md#2026-11-16-原文版本新鲜度审计补强)。

> 2026-11-16 合并前实现工作集验证：目录 catalog schema v2/v3 保存章节分组与主页作品元数据；离线差异工具可比较快照并导出新增/更新话目；采集器增加验证旧快照前缀的纯追加续采和显式全目录正文刷新，raw 变更会追加不可变版本。I4 将 normalized→raw 当前版本检查接入映射、翻译运行、章节对齐、知识发布、审计和 EPUB 候选入口。基于当时 `main` `a3813c3` 的工作集，22 个非 E2E 测试模块 410 项通过 406、跳过 4、失败 0；管理员路径安全复跑 11 项通过 10、跳过 1；mock E2E 7 项通过（214.086 秒）。相关实现现已合入 `e2fe611`；这些是历史测试，不是本轮重新运行的结果。详细命令和限制见[开发与验证](development.md#2026-11-16-当前实现工作集回归)。该状态不表示真实目录增量、真实 Provider 翻译、Notion、部署或人工格式验收已完成。

> 2026-11-16 Kakuyomu 纯追加增量采集（前一检查点）：在已有未提交工作基础上新增 catalog append-only 兼容检查、完整旧 checkpoint/raw 版本复核及纯追加续跑路径。增量模式会保留旧话 ID/顺序/标题/URL 与既有章节归属，只从旧目录末尾请求新增 episode，并创建新的完整 checkpoint；同一目录版本可从暂停点续跑。该阶段定向合成回归 105 项通过，`py_compile` 与 CLI `--help` 通过，本次未请求真实 Kakuyomu 页面或改写外部书籍数据。它本身不检测正文变更；后续阶段已实现显式正文刷新。原始 HTML、下游概要/知识失效传播、AI/人类双版本、人工格式验收及真实翻译仍未完成。详见[开发与验证](development.md#2026-11-16-kakuyomu-纯追加增量采集正文刷新前一阶段)。

> 2026-11-16 Kakuyomu 元数据版本归档与实时采集复核（正文刷新前的历史检查点）：`main` HEAD `a3813c3`；当时已有未提交文档、代码和测试改动并予以保留，随后继续增加来源 manifest 归档逻辑、回归测试和文档。该检查点的实现支持主页完整目录发现、普通 episode URL 采集、catalog v2 分组元数据、v3 作品元数据白名单/差异比较，以及将变化后的主页元数据写入带 UTC 记录时间、哈希和父版本的 `kind=work` artifact；旧 v1/v2 catalog 仍可读取。历史 source-only run 为主页声明的 88/88 话；当时实时重新发现 88/88 URL 并从普通 episode URL 检查一话格式，另核验既有试点 manifest 的 267/267 artifact 文件。该阶段联合合成回归 99 项通过，未重跑真实 88 话采集，因此旧试点 manifest 是否含新 artifact 未验证。该阶段尚未实现正文刷新，后续已在本页最新状态实现；原始 HTML、作品字段对概要/知识的失效传播、AI/人类双版本仍未实现，人工格式验收及真实翻译未完成。详细范围见[开发与验证](development.md#2026-11-16-kakuyomu-元数据版本归档与实时采集复核)。

> 2026-11-16 文档规划复核（前一检查点）：与最近代码变更 `ba9979e` 比较，Python 源码及依赖声明无差异。此前只读清单核验记录为 267/267 文件通过；试点计划预览为 `ready_for_review`。此前进程环境变量存在性检查未发现相关渠道变量，根目录无 `.env`；其他进程或外部配置未知。前一检查点的 127 项合成测试记录见[开发与验证](development.md#2026-11-16-文档规划复核)。

> 引用会话复核：本轮通过 `read_thread` 读取了两个引用会话的近期分页；第一个会话更早分页的响应超出工具大小限制，不能据此声称完整读取全部历史。此前记录中的 `hasMore=false` 是较早复核的读取结果。会话用于确认用户目标和决策，实施状态仍以当前代码、测试和工作树为准。

> 历史已合并代码基线为 `ba9979ed272152ee2ce3039306dfc685b4476374`（PR #67）；PR #68/#69 是后续文档同步，目录元数据、增量/刷新采集和来源新鲜度门禁后续已随 PR #70 合入 `e2fe611`。历史 source-only 采集为主页声明的 88/88 话；2026-11-16 显式刷新又请求 88/88 话，哈希均未变化。刷新后 manifest 的 268/268 文件通过校验，计划预览为 `ready_for_review`、88 项、0 问题。历史检查时译文文件仍无。未调用真实 Provider/Notion；此前本机存在性预检未发现 `.env`、Provider allowlist、JOJO/JYQF endpoint/key 或 `PROOFREAD_MODEL`，其他进程或服务商状态未知。88/88 不包含草稿/私有话，也不等于平台背书或公开分发许可。详细边界见[当前交接](handoffs/2026-11-15-translation-workflow.md)。

## 2026-11-16 历史试点计划导出

- `已验证` 在主线代码基线 `c988c4b` 上导出旧计划文件 `translation_plan_review_2026-11-16.json`；计划摘要为 `36dae9c08069ce5c66eddc1e870a0aa4aa4d1724b00589ed9a5be62ce4bc22d4`，重新计算一致。该计划生成早于 AI 版默认选源实现，不再是当前映射审阅对象。
- `已验证` 计划包含 88 个目录位置、88 个有效来源版本、0 个问题；episode ID、位置、原文文件、来源版本、译文目标和 TM key 均无重复，88 个译文目标当前均不存在。标题包含 1–87 连续编号话目，另有位置 48 的幕间。
- `未验证` 自动检查不能确认章节正文格式、内容完整性或人工认可的原文到译文路径。旧计划未获批准，也未创建审批回执或运行翻译。历史计划原先误放在 `SourceArchive/`，现统一移至 `projects/祝福のネトラレラ/Workflow/Plans/`；待审计划和审批回执不属于来源归档。该书籍数据目录由 `.gitignore` 排除。
- 本次 `--plan-only --plan-output` 仅写出该 JSON 文件；没有网络请求、Provider 调用或正文写入。配置、数据外发和真实翻译限制见[开发与验证](development.md#2026-11-16-pr-6465-合并与试点计划导出)。

## 2026-11-17 默认 AI 版翻译计划

- `已验证` 未指定 `--source-edition` 时，Kakuyomu 计划预览和正式入口直接从 `RAWs_AI` 读取 AI 清洗正文；计划中的 archive 路径只记录来源 lineage/provenance。缺少或过期的 AI 清洗索引会阻止运行，不会回退到归档正文或 collector `normalized_source`。该来源选择是用户确认的翻译输入契约。
- `已验证` 当前默认模式计划：`projects/祝福のネトラレラ/Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-17.json`，schema v2，摘要 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`。它绑定原始 HTML 刷新后的 catalog 与 AI 索引；状态 `ready_for_review`，profile `ai-efficient-v1`，88/88 `RAWs_AI` 正文及对应归档 provenance 通过校验，episode ID 和译文目标均唯一，0 问题。此前 schema v1 `ai_raw_html` 及 `ai_default`/`ai_append` 计划均不可用于当前审批。
- `已验证` 当前计划经 `translation_plan_approval.load_translation_plan` 重算摘要一致；计划不含章节正文，生成仅有 0 个网络请求、0 次 Provider 调用和 1 次文件写入（新计划 JSON）。试点计划位于 `.gitignore` 排除的书籍数据目录。
- `未验证` 映射仍需人工审阅；尚未生成审批回执、调用 Provider 或创建译文。当前审阅对象及核对项目见[试点映射人工审阅](handoffs/2026-11-16-pilot-plan-review.md)。

## 翻译计划审批门禁（PR #62）

- `部分实现` Kakuyomu 编排入口的翻译计划人工审批：计划摘要绑定原文/译文根目录、catalog/manifest 和逐话来源版本及目标映射；审批 CLI 展示映射并要求人工输入完整摘要，缺少匹配回执时在创建该入口的流水线前停止。其他直接调用流水线的路径未被此门禁覆盖。回执为本地未签名 JSON，审核者标签未认证；不构成可信身份或语义质量证明。
- `已验证` PR #62 合并前，非 E2E unittest 共 368 项、0 失败、4 项平台能力跳过；定向回归 25 项通过，审批路径 synthetic E2E 1 项通过；完整 mock E2E runner 7 项通过（253.608 秒）。用户另行提供的安全路径结果为 9 项、3 项跳过，未绑定此 checkout；管理员复跑为 11 项、10 项通过、1 项 Windows FIFO 跳过。
- `未验证` 真实 Provider/API、人工检查 88 话映射与文本格式、Notion、EPUB 阅读器及部署。
> 历史引用会话记录：较早复核曾分页读取两个引用会话至 `hasMore=false`；2026-11-16 本轮重新检查近期分页时，第一个会话的更早分页因响应超出工具大小限制未能读取。不可见的历史内容不作推断；会话仅作目标/决策线索。

> 2026-11-15 历史复核快照：分支 `codex/translation-workflow-20261115`、HEAD `c3f313b`；当时工作区包含此前的未提交修改和任务增量。两个引用会话已分页读取至 `hasMore=false`，并以当时源码交叉核对。URL adapter 增量后的相关回归和 mock E2E 见[开发与验证](development.md#2026-11-15-当前-checkout-回归验证)；来源到版本化 mock 翻译端到端路径见同日端到端记录。当前状态以本文首段及开发与验证中的最新检查点为准。

> 来源接入表述说明：Kakuyomu 主页 adapter 从 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2` 发现公开 episode ID/title 和 `Chapter` 分组元数据，要求唯一条目数等于 `publicEpisodeCount`，随后生成普通 URL。catalog schema v2 保存分组 ID、章节 ID/标题/层级、话目位置范围及 episode ID 顺序；schema v3 增加主页作品元数据白名单，v1/v2 catalog 仍可读取。`scripts/run_kakuyomu_workflow.py --work-url` 可保存发现 catalog、获取目录中全部公开 episode 页面、生成带来源版本的确定性 `CHAPTER_MAP` 并运行生产流水线；synthetic mock E2E 已验证该链路。它不发现/获取草稿或私有话，不证明站点声明外的完整性，也不代表真实 Provider 翻译或全书真实站点 E2E。

> 用户决定与试点边界：指定书籍已明确获得授权；用户是普通读者，要求从主页发现完整公开目录并通过普通 episode URL 逐话采集，不依赖作者 ZIP，也明确不需要官方澄清。Kakuyomu adapter 检查 robots，不登录、不跟随重定向、不请求 `/read`。2026-11-17 显式全量刷新再次读取 88/88 话，正文 hash 无变化，并将 88 个原始 HTML 响应体作为独立 `raw_page_html` artifact 保存；每个 artifact 均绑定 episode metadata 与同一话 `raw_source`。当前 `source_manifest.json` 356/356、合并 edition manifest 532/532；AI/人读 88 话可重算校验，默认计划使用 `ai-efficient-v1` 且 88/88 AI 来源有效。旧 catalog v1 不含章节分组，不能证明旧/新分组一致。作品授权不代表平台背书、法律结论或公开分发许可；采集范围不含草稿/私有话或主页公开计数外完整性。AI/人读人工格式与映射验收、下游过期后自动重建、真实 Provider 调用和 Notion 操作未完成。用户已授权 JOJO/JYQF 接收各自职责的最小类别；运行时 allowlist、端点/数据流和渠道兼容性仍未验证。

> 2026-11-15 平台规则观察与用户决定：robots 允许普通 work/episode URL，禁止相应 `/read`；普通 HTML anchor 只有 7/88 条目，完整目录解析读取 `__NEXT_DATA__.__APOLLO_STATE__.Work.tableOfContentsV2`。此前查阅的服务条款中有关于分析站点/应用结构的限制；该规则作为风险背景保留，不作法律结论。用户明确表示无需官方澄清并要求按普通 URL 路径继续，因此官方答复不设为本试点前置条件；实际采集已完成 88/88。此记录不称为平台背书或公开分发授权；仍遵守 robots，不访问 `/read`，不登录或绕过访问控制。

## 已实现

- `pipeline.py`：Python CLI；按章节读取 Markdown，构建上下文，依次执行上下文标注、初译、校对、润色，并写入译文和翻译记忆。
- `部分实现` 响应契约与质量门禁：标注对象与源段落保真校验、初译字段/段落检查，以及提示词和调用端 schema 对齐。显式 JSON/兼容路径保留历史回退行为；`REQUIRE_REVIEWED_PUBLICATION` 正式项目路径对无效校对/反思/润色响应及未解决的严重校对意见失败关闭，异常发生在逐章提交前，不写入本章译文或 TM。未完成 Kakuyomu run 仍可由操作者使用相同 run ID 和计划显式恢复；计划变化拒绝复用。`STRICT_REFLECTION_MODE` 仍默认关闭；当前严重度由模型返回，门禁不证明模型判断准确，也没有实现自动重试、“信、达、雅”独立审核报告、评分或语义质量验收。
- `部分实现` Provider 路由与数据类别预检：`get_primary_provider_route` 集中管理 Sakura/Qwen、DeepSeek，以及显式 JOJO (`gpt-6-luna*`) / JYQF (`deepseek-v4.1-flash`) 别名；通用 `deepseek-flash` 仍走 DeepSeek。未知模型名会在流水线读取章节及创建客户端前拒绝。标注/初译仅声明 `source_text`、`book_knowledge`，校对/润色声明三类全集；启用严格反思时初译模型也须获准三类。启动预检会按运行时可达的回退路径验证 Gemini 或 JOJO→JYQF 的数据类别与凭据；JYQF 接管的 JOJO 阶段不要求 Gemini 获准该阶段数据，JYQF 本身仍须获准同阶段类别。JYQF 回退还在每次请求前再次检查其授权，并在备用 OpenAI-compatible 客户端关闭 SDK 自动重试（`max_retries=0`）。回退默认为关闭，只适用于 JOJO 主路由的连接错误、HTTP 408/429/5xx；鉴权、请求/schema 错误和内容拦截不回退，JYQF 失败后不级联。用户已授权 JOJO/JYQF 各自职责所需最小类别；allowlist 默认拒绝，需本地显式配置。端点、模型 ID、当前凭据和协议兼容性仍未验证；通用 Provider 抽象、阶段独立模型分配、`CODING_PLAN_*` 支持和真实端点验收仍未实现。
- `rag_engine.py`：翻译记忆向量检索、术语匹配、分章指导检索及记忆写入。
- `scripts/align_chapters.py`：双语章节段落对齐、对齐结果向量化并写入翻译记忆。
- `scripts/validate_tm_provenance.py`：只读核对 TM 来源索引的文件哈希、段落引用和词对内容；配置 manifest 时还可检测同一来源 artifact 的更新版本。不修改 TM，也不判断译文质量或审核状态。
- `scripts/validate_knowledge_provenance.py`：只读核对知识候选 provenance 的来源文本哈希、版本关联及 manifest 中的最新来源；不修改或批准知识草稿。
- `scripts/apply_story_summary_review.py` 与 `story_summary_review.py`：生成哈希绑定的概要审核模板、发布明确批准的 JSON bundle，并在翻译流水线加载时复核 bundle 与 provenance 来源版本新鲜度。旧 Markdown 概要仍可加载但未经此审核门禁；回执未签名/审核者身份未认证。
- `scripts/auto_extract_knowledge.py` / `knowledge_batching.py`：读取章节正文前依据 `Config.PROOFREAD_MODEL` 解析 Provider/URL/专属 Key 并检查该 Provider 的 `source_text` 外发授权；全书及 `--chapter-position` 模式还要求 `book_knowledge` 授权，创建客户端时复检。默认模式仍只取前三章并截到 20,000 个 Unicode 字符；全书模式读取当前全部配置章节（最多 1000 章），单话模式只选一个版本化 catalog 位置。两种预算模式都要求 verified bundle、总字符上限、本地 tokenizer JSON、context/output/safety/message 参数，并按 token 预算分批和综合，最多 100 次请求。provenance 记录章节/段落覆盖、tokenizer hash、候选 lineage 和结论证据；单话输出隔离于来源版本与 bundle 目录，概要与可选术语现可人工审核后进入匹配的章节上下文。字符预算不证明目录覆盖，tokenizer/context 可信度依赖调用者提供正确的模型文件/参数；真实 Provider、综合语义质量、reviewer 身份和全局/局部知识语义冲突仍未验证。草稿排他新建且不自动批准。合成测试记录见[2026-11-17 全书知识预读增量](development.md#2026-11-17-token预算分批全书知识预读)、[2026-11-18 全书跨批候选综合](development.md#2026-11-18-全书跨批候选综合)、[单话知识候选草稿（审核接入前检查点）](development.md#2026-11-18-单话知识候选草稿审核接入前检查点)及[单话审核知识接入翻译上下文](development.md#2026-11-18-单话审核知识接入翻译上下文)。
- `scripts/apply_knowledge_review.py`：可为当前 glossary/provenance 候选排他新建绑定原始字节 SHA-256 的未完成审核回执模板（所有决定均为 `pending`，不可发布），也可消费完整回执，校验候选哈希、provenance 来源新鲜度和术语段落命中，仅将明确批准项写入新的 reviewed glossary bundle；模板模式不读章节或 manifest，也不调用审核 Provider，任何模式均不覆盖既有文件。回执 reviewer 字段未签名、未认证，是调用者声明。项目名模式固定加载 `Knowledge/Glossary_reviewed.json` 并校验来源新鲜度；显式 JSON 配置仍由调用者指定 `GLOSSARY_PATH`。
- `prompts/`：初译、逻辑校对和文风润色提示词。
- `tests/`：标准库 `unittest` 测试、独立 mock HTTP 服务、RAG/对齐/路径安全测试。
- `projects/example/`：小型示例原文、译文和书籍知识样例；不代表实际运行产物或真实书籍数据。

## 部分实现与差距

- `部分实现` 多 Agent：当前由单进程按阶段调用多个模型端点；未发现独立 Agent 运行时、队列、调度器、持久化任务状态或用户交互界面。
- `部分实现` 翻译记忆：使用 JSON 文件和嵌入向量并自动写入；新的流水线/对齐写入附带可选 `source_provenance`，记录源文/译文哈希和段落映射，可用只读脚本核验文件和词对是否仍匹配。历史条目不自动补录；审核、版本和冲突治理仍未实现。逐章恢复日志可在进程中断后校验输出与 TM 基线并恢复本章提交；日志冲突时保留待处理状态，不覆盖内容。日志明文保存在输出目录，单条上限 64 MiB；不保证多进程并发或断电持久性。
- `部分实现` 章节格式保护：已验证本地响应 schema、非空文本/段落数及引号字符序列检查；格式门禁失败不写译文或 TM。其他格式需依据获准样本进一步定义，术语和语义质量仍未成为统一硬门禁。
- `部分实现` 章节发现：未配置 `CHAPTER_MAP` 时，流水线与对齐器只扫描配置目录第一层，暂不递归；项目名模式默认不扫描人读版 `生肉/`，而是验证 `RAWs_AI/` 并生成版本映射。默认输出 `熟肉/` 若含子目录，需由 `workflow_paths.json` 指定一个已存在输出根，或由显式 JSON 配置给出路径。空扫描会失败，对齐器在没有任何可处理译文时也会以非零状态退出，不会把空运行报告为成功或保存 TM。多卷映射的通用契约已实现；真实章节和输出映射仍需核验。
- `部分实现` 显式多卷映射契约：JSON `CHAPTER_MAP` 按用户给出的顺序记录 `raw_file`、`translation_file`、`tm_key`，并可选记录 `source_version_id`；版本 ID 要求 `SOURCE_MANIFEST_PATH` 并验证 manifest artifact 类型、相对路径及字节 SHA-256。流水线、对齐器、知识抽取和 TM 来源审计共用映射；TM/知识来源记录保留版本 ID。旧三字段映射保持兼容，拒绝路径穿越、符号链接、重复路径/键及缺失源文件。用户已决定缺译文作为新任务、同名旧译文先归档后人工判定；真实书籍映射条目和章节对应仍未核定，未在忽略项目中启用。
- `部分实现` API 容错：Gemini 故障转移默认关闭；显式开启后仅连接/超时、HTTP 408/429 和 5xx 触发回退。鉴权/请求错误、响应 schema 错误及内容拦截不回退；通用 Provider 抽象、逐阶段错误策略和真实端点验证未完成。
- `部分实现` 运行日志隐私：校对严重意见不再输出；RAG embedding 失败日志、知识抽取和章节对齐 CLI 的已处理错误不输出异常正文；TM 来源审计 CLI 会转义不可打印字符，且拒绝空白 `TEST_WORKSPACE_DIR`。第三方 SDK、测试 runner 和其他外围工具仍可能产生自己的诊断输出，未做全局日志脱敏保证。
- `部分实现` 路径边界：章节映射路径拒绝绝对路径、路径穿越和符号链接，译文/草稿采用排他新建，TM 采用原子替换；显式配置根目录仍由操作者负责，平台级并发链接竞态未完全封闭。
- `部分实现` 配置：支持环境变量、项目目录及 JSON 配置路径；阶段模型可由 `INITIAL_MODEL`、`PROOFREAD_MODEL`、`STYLE_MODEL` 环境变量覆盖 JSON 配置；`API_TIMEOUT` 默认 10 秒并拒绝非有限或非正数，覆盖 OpenAI-compatible 聊天、Gemini 生成、RAG 和章节对齐 embedding。代码默认空 `PROVIDER_DATA_POLICY` 并拒绝远端数据；当前试点忽略配置已按确认职责列出 JOJO/JYQF 类别，但未配置凭据或验证端点。有基础 `requirements.txt`，但依赖未锁定，也没有完整部署配置。
- `部分实现` 默认翻译来源：Kakuyomu 编排器与通用 `pipeline.py --project` 都要求项目根存在 `SourceArchive/` 和 `RAWs_AI/`，先校验 AI 索引、其对应 catalog 摘要及 episode ID/title/position 全覆盖、清洗清单、AI 镜像字节哈希与归档 manifest lineage 元数据。章节映射以 `source_input_file`/`source_sha256` 指向 `RAWs_AI` 实际读取 AI 正文，以 `raw_file`/`source_version_id` 记录 `SourceArchive` 中的归档版本作溯源校验。翻译运行时从 `SourceArchive` 读取 manifest/catalog 元数据，不打开归档章节正文；AI 镜像文件字节哈希与归档 manifest 登记的 artifact `content_sha256` 一致。归档正文实字节核验由 `scripts/validate_source_manifest.py`、`scripts/validate_source_editions.py` 等显式验证命令执行。映射按位置生成 `episode-<位置>-<ID>.md` 译文文件名和 `source-edition:<work_id>:<episode_id>` TM 键。AI 来源目录缺失或验证失败即停止，不退回归档文件或人读版；旧目录需通过显式 JSON `RAW_DIR`/`CHAPTER_MAP` 指定。两种默认入口均要求与当前完整章节映射、AI 来源版本绑定的 approved 全书概要；Kakuyomu 另要求其计划审批回执，通用项目模式不要求 Kakuyomu 专用计划回执。显式 JSON 兼容配置可保留旧概要行为。以上不证明人工映射或译文质量。
- `部分实现` 来源版本清单：`source_manifest.py` 提供本地 JSON schema v1、版本追加、SHA-256/相对路径语法和父版本图校验；图校验使用迭代算法，不受 Python 调用栈深度限制。`verify_manifest_files` 可验证清单列出的文件；`verify_manifest_artifact` 只校验指定版本。`scripts/validate_source_manifest.py` 提供只读 CLI。`source_ingestion.py::materialize_episode_markdown` 与 `scripts/materialize_source_markdown.py` 可将显式指定的 raw artifact 校验为 UTF-8 后，按原字节派生 `.md` 并记录其父版本；这是无格式转换的 I3 基线，不等于完整规范化、差异映射或站点适配。
- `部分实现` 来源接入：`source_ingestion.py` 提供 `SourceAdapter`、显式路径 `LocalFileAdapter`、checkpoint v5 与版本化归档；本地导入只读 catalog 指定文件。Kakuyomu adapter 从作品主页解析 Apollo 目录，唯一 Episode ID 数必须等于 `publicEpisodeCount` 才产出公开 URL；主页与普通 episode 请求均检查 robots，不登录、不跟随重定向、不请求 `/read`。解析后的 UTF-8 可见文本保存为 `raw_source`，原始 HTTP HTML 响应体精确字节另存为 `raw_page_html`，后者绑定话目元数据及同一话正文版本。checkpoint 保存每话完成时的版本；append-only 只抓目录尾部新增话，全量刷新重取全部话目。采集为跨时间滚动快照；正文与页面 bytes 分别由 artifact hash 记录，不自动发现未刷新的静默正文修订。限制为页面 HTML 4 MiB、提取文本单话 16 MiB、全目录 128 MiB、最多 1000 话，请求间隔 1.5–3 秒、默认 2 秒。页面结构、目录数或正文标题不符时 fail-closed；parser v4 保留 ruby/旁点关系标记和 U+3000。2026-11-17 全量刷新完成 88/88，正文 hash 无变化，归档 `raw_page_html` 88 个版本；source manifest 356/356、合并 edition manifest 532/532 文件校验通过。采集不包括草稿/私有话或主页公开计数以外的完整性证明；未调用 Provider，正文人工格式验收仍未完成。
- `部分实现` Kakuyomu 映射预览：`scripts/run_kakuyomu_workflow.py --plan-only` 从本地 catalog/manifest 验证作品/episode 元数据、当前 raw/normalized artifact、来源父版本与目标输出路径，不加载 Provider 配置、不联网或输出章节正文；默认 stdout 模式不写文件，显式 `--plan-output` 才会排他新建计划 JSON，目标必须位于 `SourceArchive/` 之外。默认从项目 `RAWs_AI` 核验 AI 索引的完整目录覆盖、清洗版本清单/镜像 hash 和 raw lineage；翻译正文直接从 `RAWs_AI` 读取，归档版本只用于来源 provenance 与校验。计划与审批回执分别放在 `Workflow/Plans/`、`Workflow/Approvals/`，审批 CLI 也拒绝在计划绑定的来源归档根内写回执。`--ai-edition-root` 可覆盖 AI 根位置，只有显式 `--source-edition normalized_source` 才选择 collector `normalized_source`。审批摘要绑定 AI profile/索引/清单哈希，执行时 pipeline 使用清洗清单复核。当前 2026-11-17 schema v2 计划位于 `Workflow/Plans/translation_plan_review_ai_raw_html_schema2_2026-11-17.json`，为 `ready_for_review`，`ai-efficient-v1`，88/88 `RAWs_AI` 正文与对应归档 provenance 有效、0 问题；摘要 `331013b8fdaab3195d30e640bc737029cea0408adc6d7b42554ebbc8486b5d1f`，计划不含章节正文。旧 schema v1 计划不可用于审批。人工审阅、匹配回执、AI 版本绑定的已审核全书概要及 Provider 配置仍是正式翻译前置项。详见[开发与验证](development.md#2026-11-17-原始-html-归档与默认-ai-计划复核)。
- `已实现` 来源采集空输入保护：2026-11-15 修复 `source_ingestion.py` 对零章节终端结果仍可报告完成的问题；空终页在未发现章节前会失败，complete checkpoint 必须至少包含一个已发现章节。空中间页仍可继续分页。本地 `scripts/ingest_local_sources.py` 还会在创建 adapter 或输出前拒绝空 `episodes` catalog；核心和 CLI 回归测试覆盖这些边界。
- `部分实现` I3 Markdown 物化与章节导出：按显式 ID 校验 manifest 关联的 raw 版本哈希、UTF-8 和上限后，可字节保真生成不可变单话 `.md`；试点现有 88 个目录话目均已有 normalized artifact，且按完整 checkpoint v5 导出一份 88 话有序 Markdown。集合模式可显式选择递增位置的 episode ID，也可按完整 checkpoint 当前记录的 discovered/completed ID 和 raw 版本绑定选择章节，并核对 raw 版本仍与 manifest 当前版本相符。导出以 `\n\n` 分隔，要求输出字节上限，并把所有 normalized 版本作为父节点。checkpoint 未签名且可编辑；模式只验证当前所列集合，不证明记录未经改写或平台目录枚举穷尽。仍不做语义清洗、段落差异映射或真实章节人工验收。
- `部分实现` I4 来源版本衔接：人工映射可把 `source_version_id` 绑定到 manifest 中 `.md` artifact。通用章节映射加载、翻译运行前与提交前、章节对齐、知识审核发布、TM/知识/概要审计及 EPUB 候选构建都会核验 normalized 文件和 manifest 哈希，并要求其 raw 父版本仍是最新版本；旧 normalized 或 raw 更新后尚未重建 normalized 会被拒绝。损坏文件或父 lineage 报 `invalid`，过期来源报 `stale`。TM 审计仍分开验证 manifest 原始字节哈希和文本读取哈希。`scripts/snapshot_downstream_freshness.py` 可将 TM、知识来源和已审核全书概要审计结果写成绑定 manifest/消费者输入哈希的只读 schema v2 快照；概要快照校验当前版本化章节映射的全书覆盖，只保存文件哈希、状态和详情，不保存概要正文。Kakuyomu 完整编排会在计划生成后自动追加翻译前快照、成功翻译后追加翻译后快照；项目模式 `scripts/ingest_kakuyomu_pages.py --project` 会在来源采集后同步来源历史并记录 AI 索引及下游状态。相同状态幂等复用，状态变化追加新文件。版本化通用翻译入口还会校验已有译文与 TM 是否匹配当前输入，仅跳过已提交且版本一致的结果，否则保留既有字节并阻断。快照不会自动修改消费者数据或替代运行时门禁；source-only/本地导入路径仍需显式生成快照，自动重建派生物及真实章节验收未完成。
- `部分实现` I5 EPUB 候选构建：离线 builder 可消费显式排序的 Markdown catalog，要求 Pandoc 版本精确匹配且不覆盖既有输出；构建前对每个 `source_version_id` 校验来源 manifest 的文件哈希、work/episode identity 与最新版本，并在 sidecar 记录 manifest 路径/hash。只处理文本 Markdown、拒绝图片；candidate 和有限 ZIP/OPF/XHTML 检查不是完整 EPUBCheck，也不证明质量、完整选集或阅读器兼容。试点已生成 88 个原文 Markdown，但译文目录仍为空，因此没有真实译文 EPUB 输入。

## 2026-11-18 翻译工作流续接

- `部分实现` 全书数据契约：`book_bundles.py` 现生成 raw JSON、AI JSON、human Markdown 和 bundle-set marker；marker 最后写入，重跑按内容寻址复用。AI bundle contract v2 绑定逐话来源版本、AI 镜像摘要、分组和当前索引。试点 loader 对 88 话 bundle-set 返回 `verified`；source manifest 及双版本校验结果沿用本轮前已验证的 356/356 与 532/532 记录。该目录是公开 catalog 快照，不证明平台声明之外的完整性。
- `部分实现` full-book 知识抽取 CLI 需要显式 bundle-set、AI bundle 路径、catalog、checkpoint 和 human root，并在授权预检后加载经校验的 AI bundle 正文；输出 provenance 绑定快照和 AI bundle 哈希。合成集成测试通过；本轮未调用 Provider，未生成本书知识候选。
- `部分实现` Kakuyomu 编排器把当前 bundle 身份绑定到 approved 全书摘要和译文 run；项目模式流水线要求活动 run 并只把逐话草稿写进 `Workflow/Runs/<run_id>/Drafts/`。新增本地逐话 checklist 和 create-only 发布器，发布前重验来源、bundle 和译文哈希。审核者身份及独立性声明未认证，终审 AI、有限返工版本链和返工次数仍未实现/决策。
- `部分实现` K3 正式项目路径现对无效校对/反思/润色响应及未解决的严重校对意见失败关闭，并在提交章节输出/TM 前停止；Kakuyomu CLI 返回非零码，只显示固定原因与计划话目位置。相同 run ID/计划可显式续跑，已提交草稿保留，计划变更会拒绝复用。该门禁不自动重试，不证明语义质量，也不改变显式 JSON 兼容入口。完整测试和边界见[开发与验证](development.md#2026-11-18-正式项目翻译质量门禁)。
- `已验证` 编排器会在早期返回、异常和成功后恢复其显式覆盖的 `Config` 字段，避免同进程后续项目继承旧的输出目录、run ID、bundle 或质量门禁状态；这只覆盖编排器配置隔离，不改变配置文件加载或真实 Provider 状态。
- `已验证` K1 模式契约要求未审核 `TranslationPipeline` 调用明确选择 `compatibility_draft`，正式 run 则须经编排器设置 `reviewed_run_draft` 并验证活动 run；任意 JSON 输出路径只能以草稿模式使用。审核发布器现支持逐话和批量 run 发布、冲突预检、不可变审核快照及发布回执中断后的幂等补齐；整批状态在标记 `published` 前复核所有正式译文字节、批准快照和回执摘要，缺件会降回 `review_pending`，冲突不覆盖现有文件。它仍不认证审核者身份，也没有 AI 终审和有限返工版本链。细节见[兼容入口保护](development.md#2026-11-18-兼容入口正式目录保护)和[发布恢复](development.md#2026-11-18-发布回执中断恢复测试)。
- `已验证` 最新全量非 E2E 回归 594 项运行、590 项通过、4 项 Windows 能力跳过；完整本地 mock E2E 7 项通过（211.406 秒）。两者均为合成/本地验证，不证明真实 Provider 或语义质量。完整命令见[开发与验证](development.md#2026-11-18-正式项目翻译质量门禁)。
- 试点 bundle-set：`projects/祝福のネトラレラ/SourceArchive/collections/1eeeb07b599ea6f676e1bd5ec7b9d03a1af9134f47d7ea1c0a08299403d5437d/bundle-set.4b051e6b8f0ece9dee951b1c00f0a64db4f31582746bd94f88b5d9b82ba36f38.json`。本轮没有生成真实审核概要、翻译草稿或外部 `熟肉` 输出；映射/清洗质量人工验收和 Provider 端到端试译仍待处理。验证命令和限制见[开发与验证](development.md#2026-11-18-整书快照与审核发布门禁)。

## 计划

- `部分实现` 术语和概要已有本地回执校验与 approved-only bundle；TM 候选仍自动写入，但 RAG 默认只检索显式配置且来源核验通过的审核快照，未配置快照时不注入候选；`ALLOW_UNREVIEWED_TM=true` 仅兼容调用可用，正式项目 pipeline 会在读取知识前拒绝该开关。全书知识抽取已支持 tokenizer/context 预算分批及概要、世界观、叙述候选的段落级来源指针；人物与术语候选仍须纳入人工审核。审核者身份与审核质量、风险分层、低风险抽查、升级/更正/废弃仍待实现。
- `部分实现` K3 正式项目路径已有阶段响应/严重问题失败门禁；`计划` 独立终审、语义评分阈值、有限返工版本链和 reviewer 身份认证仍待定义与实现。
- `计划` 评估扩展到多语言和多文本类型；当前实现聚焦日译中轻小说，不可据长期方向宣称已支持通用翻译。

## 未知与待验证

- `未知` Sakura 服务实际部署位置、模型权重/版本和运行参数。代码默认 URL 为 `http://127.0.0.1:6006/v1`；2026-11-14 本次 `Test-NetConnection` 复核该端口不可达，其他地址未探测。
- `未验证` 用户要求将疑似旧凭据按已轮换处理；当前凭据、供应商侧审计、账户权限、配额、API 兼容性和真实端到端翻译质量。2026-11-17 最新本地检查确认：忽略的根 `.env` 仅含试点阶段模型、回退开关和类别 allowlist，不含密钥；Process/User/Machine 均未设置 JOJO/JYQF key 或 endpoint。未读取密钥，也未访问供应商控制台或调用外部 API。
- `未知` 除当前工作区外是否存在云端部署、业务自动化任务或用户界面。仓库已有[GitHub Actions CI](development.md#持续集成)，仅运行依赖检查与测试；它不是业务自动化或应用部署。仓库未发现应用部署清单。
- `未验证` 当前试点的语义与视觉验收：2026-11-21 已为当前计划生成绑定计划摘要的结构审阅和 schema v2 审批回执，88 话的映射、来源 lineage、AI/人读文件字节及清洗 profile 均通过结构检查；旧人审模板的 264 个 `pending` 值保留为历史模板，不再是结构审阅的当前阻塞。计划和哈希验证不能证明原文语义完整、AI 清洗表达无损或阅读器中的 Ruby/旁点/缩进显示合意。用户报告的部分抽样另见开发记录。试点来源/版本和历史 manifest 数量见[2026-11-21 K5 Codex AI 结构审阅与计划审批](development.md#2026-11-21-k5-codex-ai-结构审阅与计划审批)；该回执不批准全书知识，也不触发翻译。作品授权已由用户确认；Provider 和 Notion 接收范围分别处理。
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

2026-11-16 TM 默认检索门禁：`RAGEngine` 默认只使用来源核验通过的审核快照；未配置快照时不检索候选，也不生成查询 embedding。完整 TM 仍接收流水线候选写入；`ALLOW_UNREVIEWED_TM=true` 可显式启用兼容检索，审核快照始终优先。

2026-11-16 Kakuyomu 全书概要翻译前门禁：全书抽取 CLI 和概要/术语审核器支持最多 1000 个配置来源，输入字符预算超限在创建 Provider 前失败；Kakuyomu 正式编排入口要求 approved 全书概要 bundle 的来源覆盖、顺序文件名和来源版本与当次完整 `CHAPTER_MAP` 一致，否则在创建翻译管线前返回 `full_book_knowledge_required`。全书抽取仍是单请求字符预算，未校验配置映射等于主页完整目录，也未实现 tokenizer/context 预算、分批合并和逐条结论证据；通用 `TranslationPipeline` 直接调用不受该入口门禁约束。22 个相关单测模块 423 项运行、419 项通过、4 项因 Windows symlink/FIFO 能力跳过；本地 mock E2E 7 项通过（219.088 秒）。详细实现、命令及限制见[开发与验证](development.md#2026-11-16-全书知识预读输入模式)。

2026-11-17 全书知识预算分批：新增本地 tokenizer JSON 预算、段落批次规划、批次内候选来源引用和概要审核 provenance 校验；Kakuyomu 入口原有 approved 全书概要门禁不变。当前配置章节集是否覆盖作品主页公开目录、真实 tokenizer/chat template/端点预算兼容、跨批模型综合及候选语义仍未验证。23 个模块 431 项通过 427、Windows 能力跳过 4；本地 mock E2E 7 项通过（220.525 秒）。完整命令与边界见[开发与验证](development.md#2026-11-17-token预算分批全书知识预读)。

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
