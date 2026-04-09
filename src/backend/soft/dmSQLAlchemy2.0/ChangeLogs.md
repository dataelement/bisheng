# dmSQLAlchemy

此包为Python的SQLAlchemy包连接达梦数据库的适配框架，当前版本为 `2.0.11` ，API详见安装目录下的 `《DM8_dmPython使用手册》` ，目前用于适配2.0及以上版本的SQLAlchemy。

## ChangeLogs

#### dmSQLAlchemy v2.0.11(2025-10-21)

* 修复了在dpc环境下由于lastrowid导致的插入失败情况
* 改进了执行策略，当前将采用参数绑定的方式执行映射，执行效率将会提升

#### dmSQLAlchemy v2.0.10(2025-09-20)

* 新增了连接数据库时选择兼容模式选项
* 修复了在MySQL语法解析模式下使用limit，offset选项报错的问题

#### dmSQLAlchemy v2.0.9(2025-09-14)

* 新增了MySQL语法解析模式下对于on duplicate update功能的支持

#### dmSQLAlchemy v2.0.8(2025-8-18)

* 新增了对于达梦数据库中向量类型的支持
* 新增了在MySQL兼容模式下对于MySQL语法的兼容

#### dmSQLAlchemy v2.0.7(2025-7-13)

* 新增了对于SQLAlchemy异步功能的支持

#### dmSQLAlchemy v2.0.6(2025-06-20)

* 修正了连接错误时返回的错误码，当前连接错误时将返回`DBAPIError`
* 新增了对于inspector.get_sequence_names与inspect.get_materialized_view_names方法的支持
* 修正了inspect.get_schema_names方法无法获取所有模式名的问题
* 新增了对于JSON类型的支持

#### dmSQLAlchemy v2.0.5(2025-01-21)

* 修复了连接句柄使用 `IPV6` 格式主机名无法连接到数据库的问题

#### dmSQLAlchemy v2.0.4(2025-01-20)

* 改进了执行策略，当前获取表与序列信息将不再从 `sysobjects` 系统表获取以减少数据量，同时修改部分函数的缓存机制

* 修复了列名或表名为大小写共存的情况下，执行插入语句报错的问题
* 修复了当列名或表名为保留字的情况下，执行插入语句报错的问题
* 变更了主键策略，当前版本下，integer类型的主键将不再自动添加 `自增` 属性
* 修复了映射表时当创建者与当前使用模式不同时出现无法查询到列信息的问题

#### dmSQLAlchemy v2.0.3(2024.12.10)

* 修复了如果安装dmSQLAlchemy时没安装SQLAlchemy会安装最新版的问题
* 修复了特定情况下 `fetch` 语句拼写错误
* 修正了绑定策略，当前 `boolean` 类型将在数据库中被绑定为 `smallint` 类型
* 修复了执行多行插入时获取 `inserted_primary_key_rows` 异常的问题

#### dmSQLAlchemy v2.0.2(2024.10.31)

* 修复了部分类型无法对应到 `SQLAlchemy` 支持类型的问题，当前类型支持详见 `《DM8_dmPython使用手册》`  5.3节类型映射

* 修复了自增列自增值设置报错问题

* 修复了列类型为 `Enum` 时访问该列时报错的问题


#### dmSQLAlchemy v2.0.1(2024.08.27)

* 修复了单条语句执行时长最大为30秒的问题，现执行语句默认将不再限制执行时长
* 新增了对于SQLAlchemy的 `array` 类型的支持

#### dmSQLAlchemy v2.0.0(2023.01.06)

* 修复了主键为自增列的情况下执行插入操作报错的问题