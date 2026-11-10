# F120 验证记录

2026-11-06 在 `codex/kunlian-integration` 实施 Mock 范围，基于工作区 `b870baa3f`。2026-11-10 补齐 T028 独立本地 Redis 验证，42 / 42 项 Mock 任务有本地证据。

| 证据 | 范围与命令 | 结果 |
| --- | --- | --- |
| E-001 | 实施前运行 `pytest test/workflow/test_platform_agent_repository.py test/workflow/test_platform_agent_workflow_bridge.py -q` | 6 passed。作为发布与执行桥的旧行为基线 |
| E-002 | `pytest test/workflow/test_platform_knowledge_contract.py test/workflow/test_platform_knowledge_api.py -q`，W1 首次验证 | 6 passed。覆盖实际用户裁剪、跨租户拒绝、空问题、关闭模式和超时 |
| E-003 | `pytest test/workflow/test_platform_knowledge_publication.py test/workflow/test_platform_agent_repository.py -q` | 4 passed。SQLite 验证混合发布写入和摘要冲突回滚 |
| E-004 | `pytest test/workflow/test_platform_knowledge_workflow_bridge.py -q` | 2 passed。示例图经真实本地图引擎和输出节点运行。身份、Redis 和 MinIO 使用受控夹具。另经节点试运行应用入口验证额外输入拒绝 |
| E-005 | `pytest test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/sso/test_kunlian_ws_admission.py -q --disable-warnings --tb=short --show-capture=no` | 95 passed，3 skipped。独立 API 导入通过。跳过 F120 Redis、F120 正常 API／Broker／Worker、F119 正常环境用例 |
| E-006 | 公开身份和发布错误映射调整后，运行 `pytest test/workflow/test_platform_knowledge_{entrypoints,publication,workflow_bridge}.py test/workflow/test_platform_agent_{entrypoints,workflow_bridge}.py -q` | 33 passed。复验受影响的身份、发布、试运行和旧入口 |
| E-007 | Platform Vitest 运行 `platformKnowledge.test.ts`、`workflow.test.ts`、`PlatformKnowledgeQueryItem.test.tsx`、`PlatformKnowledgeSelectItem.test.tsx`、`PlatformAgentItem.test.tsx`、`RunTest.platformKnowledge.test.tsx` | 19 passed。覆盖能力三态、身份缓存隔离、固定输出、试运行旧结果清理及 Agent 回归。修正文案测试夹具后，该组件用例再通过 |
| E-008 | Platform `pnpm --filter bisheng typecheck`、修改文件定向 ESLint、`node scripts/check-i18n.mjs`、locales 构建及生成检查 | PASS。使用已有 Node 24.14 与 pnpm 9.15.9 |
| E-009 | 新增 Python 文件 Ruff 与架构守卫、修改入口 F821 检查、`git diff --check` | PASS。Git 暂存差异校验值为 `2c02efc7a00787416da5ad7fac3ede4c3c14c539576124b8c9f46b5de59a3e91` |

后端命令在 `src/backend` 执行，复用相邻工作区已有 Python 3.11 环境，`PYTHONPATH` 指向本仓库后端，测试使用独立空配置。前端命令使用现有依赖。全库测试与全工作区 lint 不在本次定向验证范围。

| 验收项 | 状态 | 待执行条件 |
| --- | --- | --- |
| 独立 Redis 停止、重复提交和旧运行隔离 | PASS | 通过回环地址的 Redis 7.2.17 执行，见 R-06 |
| MySQL／DM8 发布锁及 OpenFGA 实际权限 | NOT_RUN | 受控中间件及非管理员测试账号 |
| 正常 API、Broker、Worker 和 Platform 浏览器 | NOT_RUN | 按 [验收清单](./e2e-checklist.md) 提供专用环境，运行 E2E 脚本与页面步骤 |
| 正式昆联接口及真实身份验证 | NOT_RUN | EXT-01 至 EXT-04 齐备后完成 T043 至 T046，并在约定环境验收 |

真实替换点仍标注 `TODO [F120][EXT-01]` 至 `EXT-03`，正式样例与环境材料依赖 EXT-04。

## 2026-11-06 Mock 代码审查与复验

对照 spec、design、tasks 检查编辑器、服务授权、发布快照、试运行、已发布入口、Worker 及事件回调。以下修复沿用已确认的 Mock 合同。

| 级别与验收 | 发现与处理 | 复验 |
| --- | --- | --- |
| P1 · AC-06、AC-09 | 问题变量的来源节点存在但未连接时，配置仍能通过预检。改为检查来源在当前节点的上游，再检查变量声明。 | R-01、R-02 |
| P1 · AC-14、AC-19 | 已发布入口先领取恢复权，后校验消息归属及输入结构。错误输入可消耗恢复权并停止原执行。改为先校验，领取后才写输入，错误可更正重提。 | R-01 至 R-03 |
| P1 · AC-14、AC-19 | 混合图读取事件时丢弃 Agent 标记而未校验，已停止或 Agent 引用已替换的 Worker 也可能进入会话消息写入。消费端复核 Agent 引用，Worker 开始持久化前复核执行和所属引用。 | R-01 至 R-03 |
| P1 · AC-14、AC-19 | 同一会话的新发布图移除检索节点后，旧检索引用可能拦截普通流程。新运行写入前清理旧引用。 | R-01 至 R-03 |
| P1 · AC-14 | 试运行成功终态未被接受时仍可返回命中。改为终态写入被接受后才返回结果。 | R-01、R-02 |
| P2 · AC-02、AC-06 | 选库详情刷新失败后仍可通过旧数据校验，目录拒绝和查询故障使用同一提示。按当前请求状态验证和展示，目录权限拒绝使用已有文案。 | R-01、R-04 |
| P2 · 验证夹具 | 旧 OpenAPI 回调替身缺少运行标识和 Redis 读取能力，扩展回归时 11 项在输入校验前中断。补齐普通运行夹具，保留 400 响应和派发断言。 | R-02、R-03 |

| 证据 | 范围与命令 | 结果 |
| --- | --- | --- |
| R-01 | 定向复现 `test_platform_knowledge_{contract,entrypoints,workflow_bridge}.py` 和 `PlatformKnowledgeSelectItem.test.tsx` 中新增或扩展的断言 | 修复前观察到断连配置放行、提前领取、陈旧消息写入／读取、残留运行引用、终态拒绝后仍返回及详情失效后仍通过。修复后对应断言纳入以下回归。 |
| R-02 | `pytest test/workflow/test_platform_knowledge*.py test/workflow/test_platform_agent*.py test/sso/test_kunlian_ws_admission.py test/workflow/test_workflow_{offline_input,auto_rerun_status,session_title}.py test/open_api/test_workflow_invoke_input_errors.py -q --disable-warnings --tb=line --show-capture=no -rs` | 140 passed，3 skipped，退出 0。包含检索和 Agent 相关回归、公开输入及普通流程。跳过独立 Redis 和两组 API／Broker／Worker 环境用例。 |
| R-03 | 补齐混合图消息持久化前的 Agent 引用检查后，运行 `pytest test/workflow/test_platform_knowledge_entrypoints.py test/workflow/test_platform_agent_entrypoints.py test/open_api/test_workflow_invoke_input_errors.py test/workflow/test_workflow_session_title.py -q --disable-warnings --tb=line --show-capture=no` | 56 passed，退出 0。复验停止或替换后拒绝写入、公开恢复、旧 OpenAPI 及会话消息。 |
| R-04 | Platform Vitest 复跑 E-007 六个测试文件 | 21 passed，退出 0。新增详情刷新失败和目录拒绝提示证据。 |
| R-05 | Platform `pnpm --filter bisheng typecheck`、选库组件及其测试定向 ESLint、`node scripts/check-i18n.mjs`、后端修改文件定向 Ruff、架构守卫和 `git diff --check` | 通过。使用原有测试环境。暂存差异校验值与 E-009 一致。 |

### 2026-11-10 独立 Redis 验证

R-06 使用监听回环地址的独立 Redis 7.2.17。首次 pytest 发现全局导入夹具预置了 `RedisClient` 替身，导致第二次领取被错误放行。直接执行真实 Lua 确认第二次领取返回 `0`。测试改用真实 `redis-py` 连接并先 `PING`，运行 `F120_TEST_REDIS_URL=<隔离地址> pytest test/workflow/test_platform_knowledge*.py -q --disable-warnings --tb=short -rs`，25 项通过、1 项跳过，退出 0。Lua 原子验证覆盖重复领取、重复提交、停止后迟到事件和提交拒绝，以及旧执行停止无法影响新执行。跳过项需要专用 API、Broker、Worker 和测试账号。

会话数据库写入前有执行检查，Redis 停止无法撤销已开始的跨存储写入。MySQL／DM8／OpenFGA、正常 API／Broker／Worker／浏览器和昆联真实接口验收保持 `NOT_RUN`，正式契约适配保持待执行。
