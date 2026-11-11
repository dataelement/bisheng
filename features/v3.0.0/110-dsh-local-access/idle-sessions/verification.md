# DSH 闲置会话 — 服务端验证与发布边界

日期：2026-11-06。分支 feat/bisheng-work-130，实施基线 d4f5503dd。客户端未修改，生产数据库/配置未操作，未推送、未部署。

## 本地验证

| 范围 | 结果 |
| --- | --- |
| DSH 生命周期、准入、HTTP、原生登录/刷新、契约、模型、工具、工作台能力和 cookie | 171 passed，2 skipped |
| 工作台统一入口、任务提交、限流、引用链 | 32 passed（原集合 30，加两项真实 LoginUser 活动钩子验证） |
| Linsight 服务端提交/重试 | 6 passed |
| 常规 JWT / token_version | 7 passed |
| Alembic 单 head | 1 passed；head=dsh_idle_sessions |
| 合计（不重复计算） | 217 passed，2 skipped |

两项跳过为 test_model_service 的专用真实 Redis 场景，没有提供隔离 Redis 配置。测试使用已有 Python 3.11 环境及空测试配置，生命周期 SQL 为临时 SQLite；不使用生产凭据或生产服务。

DSH 集合：test_idle_sessions.py、test_idle_activity.py、test_idle_sessions_http.py、test_idle_workflow_activity.py、test_native_access.py、test_foundation.py、test_model_service.py、test_model_runtime.py、test_native_responses.py、test_tool_invoke_http.py、test_work_capabilities.py、test_web_session.py。

1.2.0 解析器测试使用从发布标签 v1.2.0 导出的 packages/dsh-desktop-enterprise，已验证 contract.js 与标签内容逐字节相同；通过 Node 运行原 parseToken 接受延长后的到期时间，没有修改桌面代码。

## 验收追溯

| AC | 证据 | 仍需外部验证 |
| --- | --- | --- |
| AC-IDLE-01 | 固定时钟跨 14/30/60 天、期限固化、session_id/created_at 不变 | 实际安装包持续使用 |
| AC-IDLE-02 | 纯刷新到期、目录/鉴权不续期、工作流 check_status 不续期、到期边界拒绝 | 实际客户端后台组合 |
| AC-IDLE-03 | 模型/工具准入顺序、上游失败计活动、活动失败零用量结算/释放 lease、任务持久化前钩子 | 实际供应商与任务链 |
| AC-IDLE-04 | 更新 ACTIVE 截止时间、旧 USED 截止后恢复、既有重放回归 | 网络层丢包与跨副本 |
| AC-IDLE-05 | 双设备独立、跨人员/租户拒绝、撤销后不复活、HTTP/WS cookie 精确绑定 | 实际双设备 |
| AC-IDLE-06 | 开关关闭不转换、刷新不转换、业务触发转换、历史活动不回填 | 存量库预演 |
| AC-IDLE-07 | PKCE+浏览器确认+ticket+旧格式换证，两个认证路径、动态字段、原版 JS 解析器 | 原版 1.2.0 安装包、回调/粘贴和缓存截止后重启 |
| AC-IDLE-08 | DDL 重复执行、历史行保留、索引、单 head、500 代撤销无 token 表查询、锁后时间重检 | MySQL/DM8 行锁和 DDL |

活动时间取锁后时钟：新增两个模拟锁等待越过到期点的测试，刷新和续期均拒绝，无 token 轮换或活跃时间更新。SQLite 不能证明数据库真实行锁，不能将该测试标作 MySQL/DM8 并发通过。

## 静态检查与基线问题

所有修改/新增 Python 文件经 Ruff format。新代码无新增 Ruff 告警；受影响旧文件仍有 72 项基线问题，逐文件与 HEAD 的 code/message 计数对比无新增，不做无关清理。

arch-guard 受影响文件有 7 条既有输出（common 的历史领域/API 导入及 linsight 历史跨 API 引用等）；在未修改的基线快照中逐文件复现，新增输出为 0。diff --check 通过。

尝试更广的整个 DSH 非 e2e 集合时，存在两项既有失败和三项隔离数据库前置条件错误，因此不报告“整个模块全绿”：

- test_access.py::test_online_seat_check_and_parallel_scopes_are_restored：旧测试要求鉴权之后保留旧租户上下文，实际为 None。
- test_admin_api.py::test_management_routes_use_verified_actor_and_reject_body_spoofing：旧管理路径返回 404。
- 三项 external 参数测试缺少显式 DSH_TEST_DATABASE_URL；没有尝试连接生产库补跑。

上述两项失败已在 /private/tmp/dsh-idle-before-change 的未修改 HEAD 导出源码中再次复现，结果一致；它们不是本次新增失败。

## 七维度代码审查

| 维度 | 结论 |
| --- | --- |
| 边界 | 配置严格校验、过期不复活、锁后时间读取、期限不随全局配置重解释 |
| 权限认证 | 复用原准入，活动重新校验身份和归属；只有 LoginUser 可携带服务端绑定回调，普通 Web 无设备钩子 |
| 并发 | 同一会话锁串行刷新/续期/撤销，撤销不遍历历史；真实双数据库测试待补 |
| 信息泄漏 | 日志仅 session_id、policy、截止时间；不输出凭据、摘要或秘密配置 |
| 覆盖 | AC-IDLE-01..08 有本地证据，真实环境边界明确，不以 SQLite/JS parser 代替 Electron |
| 风格架构 | 新增代码无新 Ruff/arch-guard 问题；保持 Service→Repository，无 ORM SQL 上移 |
| 文档 | spec/design/tasks、父级设计和方案同步，客户端/发布状态未夸大 |

本地代码审查结论：PASS。发布验收状态：PARTIAL，以下检查未完成，不能据此直接宣称生产问题已解决。

## 发布与回退清单

- [ ] 隔离 MySQL/DM8 执行迁移、重复升级、字段/索引核对、并发刷新/续期/撤销。
- [ ] 原版 1.2.0 安装包：回调与粘贴、跨 14/30 天、服务端已续期但本地缓存截止后重新打开各入口。
- [ ] 实际设备：断网、代理、合盖、唤醒和丢响应；1.3.0 优化仍未实施。
- [ ] 统一服务端副本算法、持久化主密钥、有效配置和迁移 head，协调切换并排空旧 token 请求。
- [ ] 先发布新登录默认 14 天；确认后设置 session_idle_migrate_existing=true，并重启/协调所有副本，使历史有效会话在后续业务活动转换。
- [ ] 验证新登录、业务滑动、后台不滑动、设备独立、过期拒绝及日志。
- [ ] 回退预演保留字段/证据和已有截止时间；不换主密钥、不批量清空会话。

新增配置属于 dsh 内部配置，仅在支持它的新镜像上使用。session_idle_ttl_seconds=1209600；默认 session_idle_migrate_existing=false。不修改旧 session_ttl_seconds 的绝对模式含义。

没有新增自动删除会话的后台任务：有效会话历史摘要保留以检测重放；后续清理必须以会话状态/实际截止时间和确认的保留策略为准。容量观测与物理清理不得以提前丢失重放证据为代价。
