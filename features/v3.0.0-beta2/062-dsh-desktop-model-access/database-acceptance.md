# F062 数据库与检索验收

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

日期：2026-09-09。用户已明确授权本轮暂不执行 DM8 真库；本轮条件改为毕昇新增业务无手写 SQL、无 MySQL 专用写法，以及 Gateway SQL 兼容性审查。原实机结果保留为历史证据，不声称已跑达梦。

## 本轮 MySQL 独立库复跑

本次实际连接 **MySQL 8.0.46** 的专属隔离库 `dsh_test_quota`，配合真实 Redis 7.2.7 DB15。复跑前只读检查表数为 **0**；复跑结束再次检查表数为 **0**。没有删除任何既存表，也未操作主线测试库。

环境显式设置 `DSH_TEST_DATABASE_ISOLATED=1`、`DSH_TEST_DATABASE_URL`、`DSH_TEST_REDIS_ISOLATED=1` 和 `DSH_TEST_REDIS_URL`。凭据从受控临时配置加载，不进入命令行、文档或测试输出。fixture 要求 `dsh_test_` 库名前缀，仍拒绝已有目标表，只清理本次 fixture 创建的表。

命令范围为以下五个文件，使用 `pytest --confcutdir=test/dsh ... -q --tb=short --show-capture=no`。实际结果：**22 passed in 17.20s，无失败或跳过**。

| 测试文件 | 通过项 | 验证范围 |
|---|---:|---|
| [test_projection_worker.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_projection_worker.py) | 3 | 真实 Stream → SQL 事务投影、SQL 回滚、提交后 ACK 丢失、重放幂等、RUNNING 超时转 UNKNOWN、租户上下文恢复 |
| [test_quota_bootstrap.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_bootstrap.py) | 1 | 无策略/无审批的首次普通策略操作留下禁用占位；受控 initialize 后同操作继续完成 |
| [test_quota_shards.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_shards.py) | 8 | 10,001 条请求完整恢复、SQL epoch 更新、缺片/摘要/顺序/重复拒绝，以及分片和最终写入回执丢失续跑 |
| [test_reconciliation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_reconciliation.py) | 4 | UNKNOWN 单请求补记、保留其他冻结原因、原月份结算、SQL 投影确认、证据/权限拒绝和可信租户 header |
| [test_usage_repository.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_usage_repository.py) | 6 | 实际 SQL 事务、并发首次月份插入、批处理回滚、终态幂等、跨月 UNKNOWN 统计、恢复 epoch 与并发策略变更的 CAS |

主线此前联合回归记录为 232 passed、14 个 usage_db setup errors；错误来自隔离库选择/已有表保护，而非已经开始执行的产品断言。本次在空的专属库重跑了包含这些用例的五文件集合并全部通过。两个测试集合有重叠，不能将 232 与 22 简单相加，也不把本次分组复跑描述为再次执行了整个联合套件。

## Gateway MySQL 与五万席位检索

主线最后一次 Gateway 验证为 **45 tests，0 failures，0 errors，0 skipped**，并确认 Maven package `BUILD SUCCESS`。本轮另只读汇总了当前 Surefire XML，计数与 45/0/0/0 一致；未重复运行或累加这些测试。

较早单独执行的五万席位 scale 用例已通过一次，证据见 [gateway-progress.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/gateway-progress.md)。它属于此前的独立 scale 运行，不计入上述最新 45 项或虚构一次新运行。实际用例为 [DshManagementTest.fiftyThousandRowsPageInSqlAndProfileVersionsCannotReassign](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshManagementTest.java)，覆盖：

- 两租户共 50,000 个席位、相同排序时间戳、连续 keyset 分页不重叠；游标绑定租户及过滤条件。
- 单调资料版本更新、缺失用户不创建席位、跨租户资料投影拒绝。
- MySQL EXPLAIN 使用索引，实例最新席位查询不出现 filesort；索引为 `(installation_id,state,created_at,seat_id)`。

同一 Gateway 交付波次还验证了真实 MySQL 首次席位空范围竞争、容量上限、会话 family 唯一性、并发 refresh 轮换/重放撤销、操作幂等及终态持久化；实际测试入口包括 [DshSeatRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatRepositoryTest.java)、[DshSessionRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSessionRepositoryTest.java)、[DshSeatOperationTerminalTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatOperationTerminalTest.java)。具体执行说明仍以 gateway-progress 及对应测试报告为准。

主线还确认前端 38 项测试及 lint/typecheck/check-i18n 通过。这些是同轮交付信息，不构成数据库、检索或性能门禁的替代证据。

## 尚未通过的门禁

**DM8 真库尚未执行。** 当前没有可用于此轮验收的 DM8 连接、运行环境及执行记录。DDL 编译、方言静态检查、SQL 代码审查和 MySQL 通过都不等于 DM8 真库验证。需在配置好的 Linux/DM8 环境重跑席位/会话/操作与 Python 策略/用量事务用例，保留竞争、回滚、重试和五万级过滤分页执行计划结果，该项已按用户确认移出本轮开发完成条件；未来上线 DM 环境仍应保留实机结果。

T113 的本地七子进程、真实 Redis/MySQL/MinIO 故障样本已通过，见 [recovery-acceptance.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/recovery-acceptance.md)。独占 Redis 的真实 AOF 重启及关闭旧主后晋升已额外通过两项验证；部署环境的主切换与旧主网络隔离、两副本 50 并发、额外准入 p95≤200 ms 目标，以及验席/投影/背压时序仍待环境。该本机样本不能替代生产 SLA 或完整部署验收，T113 同样保持未勾选。

## 用户调整后的本轮验收边界

DM8 配置不再是本轮开发阻塞项。毕昇 SQL 可移植性证据见 sql-portability-review.md；Gateway 保留现有 Mapper 风格，结论见 [gateway-sql-portability-review.md](./gateway-sql-portability-review.md)。逐模型额度替换旧共享额度后，相关 ORM/事务与投影已按新代码重跑，最新结果见 [修订验收](./model-quota-revision.md)；上面的旧数字只证明原检查时点。中央 Linux/DM8 实机回归仍可后续执行，但不作为本轮用户要求的完成条件。


## T007 补充：真实 MySQL 用户资料版本迁移验证

2026-09-09 新增并单独执行 `src/backend/test/dsh/test_profile_migration_mysql.py`。使用专属空测试库 `dsh_test_quota`，实际服务版本 **MySQL 8.0.46**；执行前、fixture 清理后分别通过 SQLAlchemy inspector 检查表数，均为 **0**。

测试在 `DSH_PROFILE_MIGRATION_MYSQL_URL` 与 `DSH_PROFILE_MIGRATION_ISOLATED=1` 显式启用后执行，并校验 `mysql` 方言和 `dsh_test_` 库名前缀。未提供连接变量时明确 skip；若 `user` 表已存在则在任何创建/写入前拒绝测试。连接凭据仅从受控临时配置读入测试进程环境，不写入测试文件或文档。

通过实际 SQLAlchemy `Table.create` / insert 创建最小既有用户表及一行数据，再使用真实 `Operations.context(MigrationContext.configure(connection))` 执行 F062 `upgrade()` **两次**，确认：

- 既有行的新增 `dsh_profile_version` 由数据库 server default 填为 `0`。
- 数据库反射得到非空 `BIGINT` 列，server default 为 `0`。
- 将该行版本通过表达式更新为 `7` 后执行 `downgrade()`，独立事务重新读取仍保留列及值 `7`。
- downgrade 后插入第二行，不显式设置版本仍获得默认值 `0`。

所有测试 DDL/DML 使用 SQLAlchemy / Alembic 表达式；teardown 只删除已确认无预存且由本 fixture 成功创建的 `user` 表，没有删除其他表。

实际单文件命令为 `pytest --confcutdir=test/dsh test/dsh/test_profile_migration_mysql.py -q --tb=short --show-capture=no`。结果：**1 passed in 0.32s**，前后表数均为 0。另验证未提供环境变量的同一文件为 **1 skipped in 0.06s**，没有连接数据库。新测试 Ruff 检查通过。

这是新增的真实 MySQL 迁移证据，补足此前仅 SQLite 迁移与离线 MySQL DDL 编译的范围；不等于 DM 真库、完整 Alembic 升级链或整套数据库回归。本轮 DM 实机仍按用户授权不执行。
