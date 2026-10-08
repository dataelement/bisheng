# F062 gateway SQL / DM8 兼容性复核

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

日期：2026-09-09。Gateway 工作区 `/Users/zhangguoqing/works/bisheng-gateway`，分支 `feat/dsh-access`。范围为新增 DSH Mapper、Repository、MyBatis 分页与 MySQL / DM 建表脚本；沿用 gateway 既有 Mapper SQL 风格。本轮按用户要求不连接 DM 实机。

## 结论与本次修复

复核发现并修复两处具体差异，没有把毕昇侧“新增业务禁止手写 SQL”的要求扩展成 gateway 全面改写。

### 1. DM 设备名称容量

`DshAuthorizationService.create()` 接受最多 100 个 Unicode code point 的 `device_name`，`DshTokenService` 将其传入会话 `device_label`。MySQL `VARCHAR(128)` 可容纳该字符数；原 DM `VARCHAR(128)` 在字节长度语义下不能存储 100 个 emoji 所需的 400 个 UTF-8 字节。

已将 **DM 脚本的 `device_label` 调整为 `VARCHAR(400)`**，保留 MySQL 列定义、Mapper 及冻结的 100 字符接口上限。达梦官方类型文档展示了 `VARCHAR` 的字节容量与字符集关系；该修复没有通过截断或收紧接口回避问题。依据：[DM 数据类型](https://eco.dameng.com/document/dm/zh-cn/sql-dev/dmpl-sql-datatype.html)。

该脚本是尚未交付的独立增量建表脚本；已手工执行旧脚本的环境需要先检查并扩容已有列，重复执行整个建表脚本不会自动修改现存表。

### 2. DM 空席位范围的并发容量保护

原 `DshSeatRepository` 对所有数据库使用 `SERIALIZABLE`，并把 MySQL 索引范围保护当作空实例容量保证。DM 的事务快照和写冲突机制不能直接当作该范围锁机制的证明；两个不同新用户只插入不同唯一键，需要明确的共同串行化边界。

现实现按既有 `mybatis-plus.db-type` 配置分支：

- **MySQL**：保持原 `SERIALIZABLE`、`REQUIRES_NEW`、5 秒事务超时与既有冲突重试。
- **DM**：`READ_COMMITTED`、`REQUIRES_NEW`；在 `TransactionTemplate` 回调内，第一条 Mapper 语句执行 `LOCK TABLE gt_dsh_seat IN EXCLUSIVE MODE`，获得锁后才调用业务回调的 COUNT / 读取 / 修改。使用同一个 Spring 管理事务与 MyBatis 连接，不另开连接，不使用只读事务。
- 事务提交或回滚释放 DM 表锁。锁等待之后的 COUNT 使用读提交，读取前一持锁事务已提交的最新状态，避免保留等待之前的事务级快照。

达梦官方文档明确给出该 `LOCK TABLE ... IN EXCLUSIVE MODE` 语法，并说明锁持续到当前事务结束后自动解除；读提交与串行化的行为分别见管理事务文档。依据：[DM 手动上锁](https://eco.dameng.com/document/dm/zh-cn/pm/consistency-concurrency.html)、[DM 管理事务](https://eco.dameng.com/document/dm/zh-cn/pm/management-affairs.html)。此处采用 DM 明文规则，没有借用 Oracle 的行为推断。

已逐路核对：初次席位授予、操作 REASSIGN / REVOKE 均经过同一事务入口；会话创建、刷新轮换、注销也复用此入口。管理页面的容量读取只用于展示，不作授予判断。资料投影更新不改变席位容量或 grant；数据库表锁会阻止并发修改该表。

**代价与约束**：DM 锁的粒度是整个 `gt_dsh_seat`，跨安装实例也会串行，短暂阻塞该表相关访问；当前取舍适用于低频席位/会话管理。事务回调只做短 SQL 操作，不能加入 Redis、HTTP、License 刷新等远程调用。锁失败会回滚并拒绝继续执行容量操作。

## 其余检查项

| 检查项 | 当前结果 |
| --- | --- |
| Mapper SQL | 新增语句使用绑定参数、普通 JOIN / EXISTS / CASE / 子查询与行锁；没有 MySQL `ON DUPLICATE KEY`、`INSERT IGNORE`、JSON 查询函数或写死 LIMIT 的 Mapper。DM 专用 LOCK 仅由 DM 分支调用。 |
| 分页 | `MybatisConfig` 从 `mybatis-plus.db-type` 选择分页插件；DM profile 明确设置 `DM`。使用当前依赖 MyBatis-Plus 3.5.6 的真实 `DbType.DM` 路径生成 ROWNUM 分页，MySQL 路径生成 LIMIT。该库内部复用 OracleDialect 实现，这是库对 DM 的映射，不是拿 Oracle 实机结果替代 DM 验证。DM 的 ROWNUM / FOR UPDATE 规则见[官方查询文档](https://eco.dameng.com/document/dm/zh-cn/pm/check-phrases.html)。 |
| 行锁 | `lockSeat` 单表与 `lockSession` JOIN 查询均为非聚合 SELECT FOR UPDATE。DM 官方查询文档说明支持多表连接，并锁定涉及的表行；没有把 COUNT 聚合添加 FOR UPDATE。 |
| 字段及空值 | 两份脚本表/列、默认值、NULL / NOT NULL 一致；时间类型分别为 DATETIME(6) / TIMESTAMP(6)，结果文本为 TEXT / CLOB，Unicode 显示列容量按数据库语义区别设置。`revoked_at` 的清空通过显式 Mapper SET 参数执行，不依赖 MyBatis-Plus 忽略 null 的实体更新策略。 |
| 用户显示字符串 | 用户名/显示名入口限制 255 code point，规范化后允许大小写展开；MySQL 搜索列 510 字符、DM 搜索列 2040 字节。`client_version` 当前生产写入恒为 null，未开放额外用户输入入口，本轮不扩展该字段。其余安装 ID / UUID / 状态 / 错误码使用受限 ASCII 格式或内部常量。 |
| CHAR 摘要 | `token_hash`、`payload_hash` 均由 SHA-256 十六进制生成器产生恰好 64 个 ASCII 字符，正好填满 CHAR(64)，不依赖 MySQL 去掉补空格的行为。 |
| CLOB | `result_payload` Java 属性为 String；MyBatis `String + JdbcType.CLOB` 映射到 ClobTypeHandler，经 JDBC Clob 读取内容，没有强转 `getObject()` 的结果。离线测试覆盖该读取处理器；未声称完成 DM JDBC CLOB 实机往返。DM JDBC 的 CLOB 元数据/对象与 `clobAsString` 行为见[官方 JDBC 指南](https://eco.dameng.com/document/dm/zh-cn/pm/jdbc-rogramming-guide.html)。 |

## 回归结果

新增 `DshSqlPortabilityTest` 的 9 项离线测试覆盖：两份 DDL 字段/类型/默认值/空值对照、100 Unicode code point 与 UTF-8 字节容量、固定宽度摘要、实际库 DM 分页分支、MyBatis CLOB 读取、DM 的事务/锁/COUNT/INSERT/提交顺序、锁失败和业务失败回滚，以及 MySQL 隔离级别与不执行 DM 锁。

已同步两个既有 SQL 测试夹具，确保真实数据库 opt-in 回归会按实际 URL 传入 DM / MYSQL 分支；没有把 DM 集成测试错误地落到 MySQL 默认分支。

Java 17、本地 Maven 3.9.9 / 缓存依赖离线执行：

```sh
mvn -o -Dmaven.repo.local=/private/tmp/f062-m2 \
-Ddsh.test.contractDirectory=/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts \
-Dtest=DshSqlPortabilityTest,DshCompletionContractTest,DshSeatOperationTest,DshSessionRepositoryTest test
```

实际结果：**BUILD SUCCESS；16 tests run，0 failures，0 errors，2 skipped**，即 14 项实际通过；其中新测试 **9/9 通过**。两项跳过是未配置隔离数据库的既有 SQL 集成测试。`git diff --check` 通过。

本报告提供源码、官方 DM 语义及离线 Java 回归证据，不包含 DM 实机建表、锁竞争、JDBC 空值 / LOB 或事务超时执行验证。本轮未提交、推送或部署。
