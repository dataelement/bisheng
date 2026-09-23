# F062 毕昇 SQL 可移植性复核

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

日期：2026-09-09。范围为当前工作树的 F062 毕昇新增代码及旧文件增量，不包含 gateway，也不代表数据库实机验收。

## 结论

当前范围未发现新增业务手写 SQL，也未发现依赖 MySQL 专有查询语法的实现。查询、分页、行锁由 SQLAlchemy / SQLModel 表达式生成；修改使用 ORM 对象赋值、`add` / `flush` 和事务。插入竞争通过唯一约束、savepoint 与 `IntegrityError` 重读处理，没有 `INSERT IGNORE` 或 `ON DUPLICATE KEY UPDATE`。

本轮按照用户要求暂不连接达梦实测。当前解释器中 `dmSQLAlchemy`、`dmPython`、`dmAsync` 均不可用，因此真实 DM 方言的 DDL / 查询编译测试明确跳过；没有使用 Oracle 方言替代并宣称达梦验证通过。

## 检查范围与结果

- `bisheng/dsh/domain/repositories/`：策略、操作历史、使用量投影、校正、管理查询与身份读取；业务入口未使用 `text()`、`exec_driver_sql()` 或字符串 SQL 执行。
- `bisheng/user/domain/repositories/dsh_profile.py`：用户与租户成员行锁、资料批量查询、用户 ID 游标分页全部使用 ORM。
- 四个 DSH ORM 表：数值及关系字段使用通用 SQLAlchemy 类型；策略配置、操作载荷及审计快照通过共享 `JsonType` 存储。新 `ModelConfigsType` 外层负责配置对象与确定结构的载荷转换，内层仍委托 `JsonType`。
- `v3_0_0_f062_profile_version.py`：仅以 `column_exists()` 守卫增加 `user.dsh_profile_version`，类型为 `BigInteger`，默认值为 `0`；没有 SELECT / UPDATE 数据迁移。既有表模型增加的相同字段与该迁移一致。
- 旧文件增量：用户保存、用户部门变更、登录同步、租户切换均接入资料持久化服务；LLM 快照读取沿用既有 DAO。其余路由、worker、配置与租户模型注册增量没有新增 SQL 执行路径。

`server_default=text("0")`、`text("CURRENT_TIMESTAMP")`、ORM `onupdate` 及 `CheckConstraint` 字符串属于 DDL / ORM 默认表达式，不属于业务手写 SQL。`UPDATE_TIME_SERVER_DEFAULT` 继续由共享适配器按数据库生成语法；MySQL 侧生成 `ON UPDATE CURRENT_TIMESTAMP` 是适配器职责，不是业务代码写死 MySQL。未新增直接导入 MySQL 类型或 `JSON_EXTRACT`、`JSON_CONTAINS`、`FIND_IN_SET`、`LAST_INSERT_ID`、`information_schema` 的业务依赖。

## 新增回归与实际执行

测试文件：`src/backend/test/dsh/test_sql_portability.py`。

1. AST 检查整个新增 `bisheng/dsh` Python 目录、资料 repository 和 F062 migration，检测原始 SQL 入口及 MySQL 方言直接导入；允许列默认表达式。使用包含导入别名、`exec_driver_sql`、直接字符串和 f-string 的反例校验守卫有效性。
2. 用真实可用 MySQL 方言编译四个 DSH 表、所有索引及用户新增列；从实际 repository 方法捕获策略/操作/用户行锁、操作分页、最后调用和用户游标查询，验证参数保留绑定、行锁仍存在。
3. `JsonType` 和 `ModelConfigsType` 的绑定与结果处理器往返测试：MySQL 选择原生 JSON，按 `dm` 名称路由选择 CLOB；覆盖 Unicode、NULL、int64 和逐模型额度对象。`dm-type-routing-only` 使用明确命名的测试替身，仅验证共享类型适配器的分支与序列化，不能证明 DM SQL 编译、驱动 LOB 行为或数据库实际执行。
4. 当环境安装真实 `dmSQLAlchemy.base.DMDialect` 后，同一 DDL 与 repository 查询编译测试将自动运行 DM 分支。

执行目录：工作树 `src/backend`。命令：

```sh
config=/private/tmp/f062-backend-test.yaml MPLCONFIGDIR=/private/tmp \
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
--confcutdir=test/dsh test/dsh/test_sql_portability.py -q -rs
```

实际结果：**10 passed, 2 skipped in 0.42s**。两项跳过均因为 `No module named 'dmSQLAlchemy'`。新测试 Ruff 检查通过。

此结果是源码审查、MySQL 方言离线编译和 JSON 适配器单元回归的证据，不包含达梦实机、真实 DM 方言编译、驱动 LOB 读取、锁竞争或迁移执行验证。本轮未新增或调整业务持久化实现。


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
