# 内置技能权限初始化并发修复与审查记录

日期：2026-11-23（UTC+8）。独立分支 `codex/beta1-builtin-skill-permission-race-20261123`，从实时核实的远端 `origin/feat/3.1.0-beta1` 提交 `63a34a9aae17ee40ec57631f47d601bf0a3504d5` 创建。采用 SDD Guide 的 Hotfix 流程。本轮未连接或操作 165 环境，没有部署、恢复权限数据或改动发行 tag。

## 问题与最终行为

两个 API worker 在启动时同时初始化同一内置技能权限。共用幂等键的第二个调用可进入原执行者尚在进行的 STAGING 恢复路径，将中间状态误判为失败；原执行者随后提交 SQL 状态发生 CAS 冲突。

修复只改变内置技能权限初始化的执行范围：业务 Repository 使用数据库 `SELECT FOR UPDATE` 锁住对应技能行，Service 在锁内重新验证租户、builtin 来源及非个人技能身份，然后运行原有权限初始化/恢复流程。锁覆盖状态检查到权限收尾，退出 session 自动释放。等待者复查 CURRENT 后不重放写入；不同技能各自持锁，可独立推进。

权限模块的冻结计划、原始账本、CAS、失败恢复及 CURRENT 授权保持规则均保留；没有将失败状态直接修改为 CURRENT，也没有改为单 Uvicorn worker 来规避竞争。无接口、表结构、镜像入口或依赖变更。

## 回归证据

修改前，现有五组相关用例基线为 **66 passed**。随后在未修复代码上执行新增的 `test_two_startups_wait_for_the_same_skill_and_recheck_current`，暂停第一个调用的 STAGE 写入，再让第二个初始化进入，原生 F048 服务返回：

```text
[PermissionVersionConflictError(None), PermissionProjectionFailedError(None)]
1 failed
```

这与现场两种错误吻合，测试没有 mock 掉权限 Service、SQL 操作账本、状态 CAS 或恢复流程；仅替代外部 FGA 传输和 SQLite 不支持的行锁。

修复后最终相关回归：**136 passed，3 skipped**。覆盖 14 个测试文件，包含 Owner 创建、系统资源初始化/恢复、CLI、权限投影及 SQL 适配器、F118 技能可见性/授权语义、技能 seeder 和新并发用例。

新增 9 个本地通过场景：

1. 同技能双启动等待并复查 CURRENT，仅产生一份 FINALIZED 账本、一个 ACTIVE Grant、两次 STAGE/COMMIT 写入。
2. 一个技能投影暂停时，另一个技能仍可完成初始化。
3. 首个调用失败，等待者通过原账本恢复，未创建第二份操作。
4. 首个调用取消，业务行锁释放。
5. builtin 来源已变为 manual 时拒绝旧快照初始化。
6. 业务行已变为个人技能时拒绝初始化。
7. 业务行租户不匹配时拒绝初始化。
8. 技能业务行不存在时不创建权限资源。
9. 管理员已撤销的租户授权在重启后保持撤销。

Ruff format/check、`git diff --check` 及变更文件的 arch-guard 均通过。只使用本地临时 SQLite 配置，未读取现场数据库配置作为测试目的地。

## 原生数据库验证范围

`test/linsight/test_builtin_skill_permission_database.py` 新增 3 个原生多连接行锁场景：正常完成、异常、取消。用例先确认等待者已经发送 `FOR UPDATE`，再检查同技能不能进入、另一技能可以进入，最后确认锁被释放。

本机 OrbStack Docker daemon 未运行，也未提供隔离 MySQL/DM8 DSN，故这 3 项跳过。**本轮没有完成真实数据库或多主机验证**；不能把 SQLite 锁替身当作数据库锁已实测通过。DM8 真实验证仍需 Linux 环境。

执行条件：

- `SKILL_BOOTSTRAP_TEST_DSN` 为 `mysql+aiomysql` 或 `dm+dmAsync` URL；库名或用户名须含 `skill_bootstrap_test`。
- `SKILL_BOOTSTRAP_EPHEMERAL_ACK=1`，且目标 schema 必须为空。用例仅创建并清理本测试的 `linsight_skill` 表；拒绝已有表的 schema。
- 从 `src/backend/` 执行：`python -m pytest -q --disable-warnings test/linsight/test_builtin_skill_permission_database.py`。不应以任何业务环境连接配置代替独立测试库。

## Code Review Report

Review scope：2 个生产逻辑文件、5 个测试文件及本次设计/审查文档；base 为上述最新发布线。按 `sdd-code-review` 七个维度自审，没有额外派发 agent。

| Dimension | High | Medium | Low | Status |
| --- | ---: | ---: | ---: | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

MEDIUM：原生 MySQL/DM8 锁用例尚未执行；发布前应在独立测试库补跑。实现使用项目已有的数据库行锁方式，未引入单数据库专用 SQL 或进程内互斥作为生产锁。

Overall：**PASS_WITH_WARNINGS**。既有 165 失败账本的数据恢复与镜像部署不属于本次操作，须在后续获准维护时单独执行并验证。
