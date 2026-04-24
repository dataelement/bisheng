# 权限相关模型、表与关联关系清单

日期：2026-04-23

## 目的

本文整理 BiSheng 仓库中与权限体系直接相关的：

- 权限引擎与授权模型代码
- 关系模型/权限模板配置代码
- MySQL 中的权限相关表模型
- 旧版本表名/逻辑名与当前 SQL 表名的对应关系
- 表之间的关联关系
- 权限改造相关迁移文件

说明：

- **真正生效的 ReBAC 授权模型**定义在 OpenFGA 模型文件中，不是 MySQL 表。
- 后台“关系模型/权限模板”当前也**不是独立表**，而是存放在 `config` 表中。
- `assistant`、`workflow`、`knowledge` 等业务资源表虽然会被权限系统检查，但它们本身不是“权限定义表”，本文不展开。
- 旧文档里常见的 `role_access`、`user_group`、`group_resource`、`user_role` 与当前数据库里的 SQL 表名不完全一致，本文统一按**当前 SQL 表名**给出。

## 0. SQL 表名速查

下面这批是权限体系里最常用、最容易问到的 SQL 表名：

| 类型 | SQL 表名 | 模型路径 |
| --- | --- | --- |
| 关系模型/模板配置 | `config` | `src/backend/bisheng/common/models/config.py` |
| 角色 | `role` | `src/backend/bisheng/database/models/role.py` |
| 用户-角色 | `userrole` | `src/backend/bisheng/user/domain/models/user_role.py` |
| 角色资源授权 | `roleaccess` | `src/backend/bisheng/database/models/role_access.py` |
| 用户组 | `group` | `src/backend/bisheng/database/models/group.py` |
| 用户-用户组 | `usergroup` | `src/backend/bisheng/database/models/user_group.py` |
| 用户组-资源 | `groupresource` | `src/backend/bisheng/database/models/group_resource.py` |
| 部门 | `department` | `src/backend/bisheng/database/models/department.py` |
| 用户-部门 | `user_department` | `src/backend/bisheng/database/models/department.py` |
| 租户 | `tenant` | `src/backend/bisheng/database/models/tenant.py` |
| 用户-租户 | `user_tenant` | `src/backend/bisheng/database/models/tenant.py` |
| FGA 失败补偿 | `failed_tuple` | `src/backend/bisheng/database/models/failed_tuple.py` |
| 空间/频道成员 | `space_channel_member` | `src/backend/bisheng/common/models/space_channel_member.py` |
| 部门知识空间绑定 | `department_knowledge_space` | `src/backend/bisheng/knowledge/domain/models/department_knowledge_space.py` |

说明：

- 上表中的名字就是当前数据库里对应的 SQL 表名。
- 其中 `roleaccess`、`usergroup`、`groupresource`、`userrole` 这 4 张表没有下划线，最容易和旧文档或代码文件名混淆。

### 0.1 本次核对结论

已按以下三层来源完成逐项核对：

- ORM 运行时实际表名：直接读取模型的 `__table__.name`
- 模型定义：核对 `__tablename__` 或 SQLModel 默认推导结果
- 测试 DDL / 迁移 SQL：核对 `CREATE TABLE` 和原生 SQL 引用

本次核对确认，当前权限相关 SQL 表名如下，和 ORM 实际解析结果一致：

- `config`
- `role`
- `userrole`
- `roleaccess`
- `group`
- `usergroup`
- `groupresource`
- `department`
- `user_department`
- `tenant`
- `user_tenant`
- `failed_tuple`
- `space_channel_member`
- `department_knowledge_space`

附加说明：

- 当前发现的主要问题不在实际表结构，而在部分文档仍沿用旧逻辑名（如 `user_role`、`role_access`）。
- `group` 作为 SQL 保留字，命名本身有可读性/转义风险；当前仓库中的 ORM 和测试 DDL 都通过框架转义或显式引用处理，暂未发现未转义的原生 SQL 风险点。

## 1. SQL 表名对照与旧新映射

| 当前 SQL 表名 | 模型路径 | 业务用途 | 关键字段 | 旧版本表名/逻辑名 | 当前新表名 | 变化说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `src/backend/bisheng/common/models/config.py` | 系统配置总表；当前“关系模型/权限模板”配置实际存这里 | `id`, `key`, `value`, `update_time` | `config` / 旧版本无独立“资源权限模板表” | `config` | 表名未变，但 v2.5 把关系模型配置放进了 `config.key` 中 |
| `role` | `src/backend/bisheng/database/models/role.py` | 角色定义表；当前职责收窄为策略角色、菜单权限和配额作用域 | `id`, `role_name`, `role_type`, `tenant_id`, `department_id`, `quota_config`, `create_user` | `role` | `role` | 表名未变；v2.5 增加 `department_id`、`quota_config`，职责从旧权限角色收窄为策略角色 |
| `userrole` | `src/backend/bisheng/user/domain/models/user_role.py` | 用户与角色的绑定关系 | `id`, `user_id`, `role_id`, `create_time` | `user_role` | `userrole` | 当前库里不存在名为 `user_role` 的独立 SQL 表；旧文档常写 `user_role`，实际 ORM/SQL 表名为 `userrole` |
| `roleaccess` | `src/backend/bisheng/database/models/role_access.py` | 旧 RBAC 资源/菜单授权表 | `id`, `role_id`, `third_id`, `type`, `update_time` | `role_access` | `roleaccess` | 旧资源授权主表；v2.5 后资源类授权逐步迁到 OpenFGA，`WEB_MENU` 仍保留在 MySQL |
| `group` | `src/backend/bisheng/database/models/group.py` | 用户组主表；当前语义是跨部门临时用户组 | `id`, `group_name`, `visibility`, `tenant_id`, `create_user` | `group` | `group` | 表名未变；v2.5 后其业务语义正式收敛为“用户组” |
| `usergroup` | `src/backend/bisheng/database/models/user_group.py` | 用户-用户组关系；记录成员与组管理员 | `id`, `user_id`, `group_id`, `is_group_admin`, `remark` | `user_group` | `usergroup` | 旧文档常写 `user_group`，当前 ORM/SQL 表名为 `usergroup`；成员关系长期目标是迁到 OpenFGA `user_group#member` |
| `groupresource` | `src/backend/bisheng/database/models/group_resource.py` | 用户组与资源的归组关系，主要用于管理页展示和资源归组 | `id`, `group_id`, `third_id`, `type`, `update_time` | `group_resource` | `groupresource` | 旧系统中不参与 `access_check`；v2.5 迁移后定位为废弃表 |
| `department` | `src/backend/bisheng/database/models/department.py` | 部门树主表，承载组织架构与权限主体 | `id`, `dept_id`, `name`, `parent_id`, `tenant_id`, `path`, `source`, `external_id`, `is_tenant_root` | `无` | `department` | v2.5 新增 |
| `user_department` | `src/backend/bisheng/database/models/department.py` | 用户与部门的关系表，记录主部门/副部门 | `id`, `user_id`, `department_id`, `is_primary`, `source` | `无` | `user_department` | v2.5 新增 |
| `tenant` | `src/backend/bisheng/database/models/tenant.py` | 租户主表，承载 tenant tree、租户配额和租户元数据 | `id`, `tenant_code`, `tenant_name`, `root_dept_id`, `parent_tenant_id`, `share_default_to_children`, `quota_config`, `storage_config` | `无` | `tenant` | v2.5 新增 |
| `user_tenant` | `src/backend/bisheng/database/models/tenant.py` | 用户与租户的绑定关系，记录默认租户和当前活跃租户 | `id`, `user_id`, `tenant_id`, `is_default`, `status`, `is_active`, `last_access_time` | `无` | `user_tenant` | v2.5 新增 |
| `failed_tuple` | `src/backend/bisheng/database/models/failed_tuple.py` | OpenFGA tuple 写入失败后的补偿重试队列表 | `id`, `action`, `fga_user`, `relation`, `object`, `retry_count`, `status`, `tenant_id` | `无` / 早期技术方案草案名 `failed_tuples` | `failed_tuple` | 当前落地 SQL 表名为单数 `failed_tuple` |
| `space_channel_member` | `src/backend/bisheng/common/models/space_channel_member.py` | 知识空间/频道成员关系表，记录 creator/admin/member，以及审批/订阅相关状态 | `id`, `business_id`, `business_type`, `user_id`, `user_role`, `status`, `membership_source`, `department_admin_promoted_from_role` | `space_channel_member` | `space_channel_member` | 表名未变；技术方案中长期目标是被 OpenFGA 关系替代 |
| `department_knowledge_space` | `src/backend/bisheng/knowledge/domain/models/department_knowledge_space.py` | 部门知识空间绑定表，记录部门与知识空间的一对一关系及审批开关 | `id`, `tenant_id`, `department_id`, `space_id`, `created_by`, `approval_enabled`, `sensitive_check_enabled` | `无` | `department_knowledge_space` | v2.5.1 新增 |

### 1.1 容易混淆的旧文档名与当前 SQL 表名

| 旧文档/逻辑名 | 当前 SQL 表名 |
| --- | --- |
| `role_access` | `roleaccess` |
| `user_group` | `usergroup` |
| `group_resource` | `groupresource` |
| `user_role` | `userrole` |

如果你在 PRD、技术方案、老代码注释或业务口头描述里看到的是带下划线名称，查库时要优先按当前 SQL 名定位。

其中 `user_role` 是最容易误读的一项：它在当前仓库里主要以 Python 文件名 `user_role.py` 和运行时字段 `LoginUser.user_role` 的形式出现，但当前数据库里对应的 SQL 表名是 `userrole`，不是 `user_role`。

### 1.2 保留但职责发生变化的表

| 表名 | 变化 |
| --- | --- |
| `role` | 从“权限角色”收窄为“策略角色”，主要负责菜单、配额、作用域 |
| `roleaccess` | 资源授权职责逐步迁到 OpenFGA，只保留菜单类 RBAC 记录为主 |
| `group` | 保留，但语义正式变成“用户组” |
| `usergroup` | 还在库里，但成员关系长期目标是迁到 OpenFGA |
| `space_channel_member` | 还在用，但技术方向是逐步由 OpenFGA 关系接管 |

### 1.3 v2.5 之后新增的表

| 新增表 | 作用 |
| --- | --- |
| `department` | 部门树 |
| `user_department` | 用户-部门关系 |
| `tenant` | 租户定义 |
| `user_tenant` | 用户-租户关系 |
| `failed_tuple` | FGA 写失败补偿 |
| `department_knowledge_space` | 部门知识空间绑定 |

## 2. 表之间的关联关系

### 2.1 关系总览

可以先按 4 条主链理解：

1. 用户角色链：`user -> userrole -> role -> roleaccess`
2. 用户组链：`user -> usergroup -> group -> groupresource`
3. 组织租户链：`user -> user_department -> department -> tenant`
4. 资源成员链：`user -> space_channel_member -> knowledge/channel`，以及 `department -> department_knowledge_space -> knowledge`

其中：

- `userrole`、`usergroup`、`user_department`、`department_knowledge_space` 是比较标准的关系表
- `roleaccess`、`groupresource`、`space_channel_member` 是带业务语义的权限/成员关系表
- `config`、`failed_tuple` 不是典型关系表，更多是配置存储和补偿队列

### 2.2 物理外键关系

下面这些关系在模型里有明确外键定义，属于强物理关联：

| 子表 | 字段 | 关联到 | 关系说明 |
| --- | --- | --- | --- |
| `userrole` | `user_id` | `user.user_id` | 一个用户可以绑定多个角色 |
| `userrole` | `role_id` | `role.id` | 一个角色可以分配给多个用户 |
| `usergroup` | `user_id` | `user.user_id` | 一个用户可以属于多个用户组 |
| `usergroup` | `group_id` | `group.id` | 一个用户组可以有多个成员 |
| `user_department` | `user_id` | `user.user_id` | 一个用户可以挂多个部门，其中一个主部门 |
| `user_department` | `department_id` | `department.id` | 一个部门下可以有多个用户 |
| `department_knowledge_space` | `department_id` | `department.id` | 一个部门绑定一个部门知识空间 |
| `department_knowledge_space` | `space_id` | `knowledge.id` | 一个知识空间至多绑定一个部门 |

### 2.3 逻辑关联关系

下面这些关系在代码里明确存在，但不一定通过数据库外键约束：

| 表 | 字段 | 逻辑关联到 | 说明 |
| --- | --- | --- | --- |
| `role` | `tenant_id` | `tenant.id` | 角色属于某个 tenant |
| `role` | `department_id` | `department.id` | 角色可限定到某个部门作用域 |
| `role` | `create_user` | `user.user_id` | 角色创建者 |
| `roleaccess` | `role_id` | `role.id` | 某条资源/菜单授权属于哪个角色 |
| `roleaccess` | `third_id + type` | 资源表 / 菜单资源 | `type` 决定 `third_id` 指向知识库、工作流、助手、工具、看板或菜单资源 |
| `group` | `tenant_id` | `tenant.id` | 用户组属于某个 tenant |
| `group` | `create_user` / `update_user` | `user.user_id` | 用户组创建者/更新者 |
| `groupresource` | `group_id` | `group.id` | 某条资源归组记录属于哪个用户组 |
| `groupresource` | `third_id + type` | 资源表 | 按资源类型记录某资源被归到哪个组 |
| `department` | `tenant_id` | `tenant.id` | 部门属于某个 tenant |
| `department` | `parent_id` | `department.id` | 部门自关联，形成部门树 |
| `department` | `mounted_tenant_id` | `tenant.id` | 部门节点可作为 child tenant 的挂载点 |
| `department` | `create_user` | `user.user_id` | 部门创建人 |
| `tenant` | `root_dept_id` | `department.id` | 一个 tenant 对应一个根部门 |
| `tenant` | `parent_tenant_id` | `tenant.id` | tenant 自关联，形成 tenant tree |
| `tenant` | `create_user` | `user.user_id` | tenant 创建人 |
| `user_tenant` | `user_id` | `user.user_id` | 用户属于哪些 tenant |
| `user_tenant` | `tenant_id` | `tenant.id` | 某个 tenant 下有哪些用户 |
| `failed_tuple` | `tenant_id` | `tenant.id` | FGA 补偿任务所属 tenant |
| `failed_tuple` | `fga_user + relation + object` | OpenFGA tuple | 这不是 SQL 外键，而是待补偿的 FGA 关系三元组 |
| `space_channel_member` | `user_id` | `user.user_id` | 某用户在空间/频道里的成员身份 |
| `space_channel_member` | `business_id + business_type` | `knowledge.id` / `channel.id` | `SPACE` 时通常指知识空间，`CHANNEL` 时指频道 |
| `department_knowledge_space` | `tenant_id` | `tenant.id` | 这条部门知识空间绑定属于哪个 tenant |
| `department_knowledge_space` | `created_by` | `user.user_id` | 绑定创建者 |
| `config` | `key` | 配置逻辑键 | 例如 `permission_relation_models_v1`、`permission_relation_model_bindings_v1` |

### 2.4 关键关联链说明

#### 2.4.1 角色授权链

```text
user
  -> userrole
  -> role
  -> roleaccess
  -> 业务资源 / 菜单资源
```

说明：

- 这是旧 RBAC 的主链
- v2.5 之后，`roleaccess` 的资源授权能力逐步被 OpenFGA 替代
- 但 `WEB_MENU` 类型仍主要保留在 MySQL 中

#### 2.4.2 用户组归组链

```text
user
  -> usergroup
  -> group
  -> groupresource
  -> 业务资源
```

说明：

- 这条链主要用于归组和管理页展示
- 文档明确说明 `groupresource` 在旧系统中不参与 `access_check`
- 因此它和 `roleaccess` 不一样，不应直接理解为真正的访问控制授权链

#### 2.4.3 组织与租户链

```text
user
  -> user_department
  -> department
  -> tenant
```

同时还有：

```text
user
  -> user_tenant
  -> tenant
```

说明：

- `department` 负责组织树
- `tenant` 负责租户边界
- `user_department` 更偏组织归属
- `user_tenant` 更偏租户归属 / 当前活跃租户

#### 2.4.4 空间成员与部门知识空间链

```text
user
  -> space_channel_member
  -> knowledge / channel
```

```text
department
  -> department_knowledge_space
  -> knowledge
```

说明：

- `space_channel_member` 是知识空间/频道成员关系表
- `department_knowledge_space` 是“部门”和“知识空间”的一对一绑定表
- 部门知识空间是 v2.5.1 后新增能力

#### 2.4.5 配置链

```text
config
  -> key = permission_relation_models_v1
  -> key = permission_relation_model_bindings_v1
```

说明：

- 当前“关系模型”和“关系模型绑定”不是独立 SQL 表
- 而是序列化后存到 `config.value`
- 因此它和上面的关系表不同，更像配置型元数据存储

## 3. 权限引擎与授权模型

### 3.1 OpenFGA / ReBAC 核心文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 授权模型定义 | `src/backend/bisheng/core/openfga/authorization_model.py` | OpenFGA 授权模型定义，包含 `system`、`tenant`、`department`、`user_group` 以及各类资源的关系模型 |
| OpenFGA 生命周期管理 | `src/backend/bisheng/core/openfga/manager.py` | 启动时初始化 store / authorization model，并创建 `FGAClient` |
| OpenFGA 客户端 | `src/backend/bisheng/core/openfga/client.py` | 封装 `check`、`list_objects`、`write_tuples` 等调用 |
| OpenFGA 异常定义 | `src/backend/bisheng/core/openfga/exceptions.py` | FGA 连接异常、写入异常等 |

### 3.2 权限域主干代码

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 权限检查主服务 | `src/backend/bisheng/permission/domain/services/permission_service.py` | 运行时权限检查主入口，包含 super_admin、tenant gate、FGA check、owner fallback、部门管理员隐式权限等 |
| owner 相关逻辑 | `src/backend/bisheng/permission/domain/services/owner_service.py` | owner 元组与 owner 相关逻辑 |
| tenant admin 相关逻辑 | `src/backend/bisheng/permission/domain/services/tenant_admin_service.py` | Child Tenant admin 授权逻辑 |
| 权限缓存 | `src/backend/bisheng/permission/domain/services/permission_cache.py` | 权限缓存逻辑 |
| 权限 DTO / schema | `src/backend/bisheng/permission/domain/schemas/permission_schema.py` | 资源类型、关系类型、授权请求结构等 |
| tuple 操作定义 | `src/backend/bisheng/permission/domain/schemas/tuple_operation.py` | FGA tuple 写入操作结构 |
| 资源授权接口 | `src/backend/bisheng/permission/api/endpoints/resource_permission.py` | 资源授权、查询、关系模型接口 |
| 权限检查接口 | `src/backend/bisheng/permission/api/endpoints/permission_check.py` | 权限检查 API |
| 权限路由 | `src/backend/bisheng/permission/api/router.py` | 权限模块路由注册 |
| FGA 失败 tuple 重试任务 | `src/backend/bisheng/worker/permission/retry_failed_tuples.py` | 处理 `failed_tuple` 重试 |
| RBAC → ReBAC 迁移脚本 | `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py` | 权限迁移入口 |

## 4. 关系模型与权限模板配置

后台“关系模型/权限模板”当前不是独立表，而是通过 `ConfigDao` 存入 `config` 表。

| 项目 | 路径 | 说明 |
| --- | --- | --- |
| 关系模型 key 定义 | `src/backend/bisheng/permission/api/endpoints/resource_permission.py` | 定义 `_RELATION_MODELS_KEY`、`_RELATION_MODEL_BINDINGS_KEY` |
| 配置表模型 | `src/backend/bisheng/common/models/config.py` | `Config` / `ConfigDao`，关系模型与绑定信息实际存放处 |
| 知识空间权限模板 | `src/backend/bisheng/permission/domain/knowledge_space_permission_template.py` | 知识空间细粒度权限模板 |

当前配置 key：

- `permission_relation_models_v1`
- `permission_relation_model_bindings_v1`

## 5. 相关迁移文件

以下 Alembic 迁移与权限体系、多租户、部门知识空间等直接相关：

| 迁移文件 | 说明 |
| --- | --- |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f001_multi_tenant.py` | 多租户基础改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f003_user_group.py` | 用户组相关改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f005_role_menu_quota.py` | 角色菜单与配额改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f011_tenant_tree.py` | tenant tree 改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f013_auditlog_tenant_id_nullable.py` | 多租户审计相关改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f020_llm_tenant.py` | LLM 多租户权限相关准备 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f021_department_knowledge_space.py` | 部门知识空间表 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f023_department_admin_membership_overlay.py` | 部门管理员 overlay 权限 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f024_department_space_per_space_approval_settings.py` | 部门知识空间审批配置 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f024_role_creator.py` | 角色创建者字段相关改造 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f026_role_scope_name_unique.py` | 角色作用域唯一性约束 |

## 6. 快速定位建议

如果你的目标是：

- 看真正生效的权限模型：先看 `core/openfga/authorization_model.py`
- 看运行时怎么判权限：先看 `permission/domain/services/permission_service.py`
- 看后台关系模型/权限模板存哪里：先看 `permission/api/endpoints/resource_permission.py` 和 `common/models/config.py`
- 看 SQL 表名、旧新名称和关联关系：先看本文第 `0`、`1`、`2` 节
- 看权限相关迁移：先看本文第 `5` 节

## 7. 不在本文展开的资源表

以下资源表会被权限系统检查，但不属于“权限定义表”：

- `knowledge`
- `assistant`
- `flow` / `workflow`
- `tool`
- `channel`
- `dashboard`

这些资源的权限通常由：

- OpenFGA 元组
- `PermissionService`
- 部分遗留 RBAC 表

共同决定。
