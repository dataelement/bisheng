# Feature: 用户组

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3.2.2](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P0
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 复用现有 Group 表，扩展 `visibility` 列（`tenant_id` 已由 F001 迁移添加）
- 改 `group_name` 唯一约束从全局改为 `(tenant_id, group_name)` 复合唯一
- 新建 `user_group/` DDD 模块（api/ + domain/），提供 9 个 REST 端点
- UserGroup CRUD API（创建/列表/详情/更新/删除）
- 成员管理 API（列表/添加/移除）+ 管理员设置 API
- 可见性：public（全租户可见）/ private（仅超管/创建者/成员可见）
- GroupChangeHandler：TupleOperation DTO 定义 + 事件方法产出元组列表 + execute() 日志 stub
- 成员变更时同步产出 OpenFGA `(user_group:X, member, user:Y)` 元组（stub）
- 管理员变更时同步产出 OpenFGA `(user_group:X, admin, user:Y)` 元组（stub）
- init_data 确保默认租户的默认用户组有 tenant_id=1 + visibility='public'
- Alembic 迁移脚本（加 visibility 列 + 改 unique 约束）
- 错误码模块 230（23000~23006）

**OUT**:
- 资源通过用户组授权 → F004-rebac-core 处理检查，F008 处理模块集成
- 用户组在资源授权 UI 中的选择 → F007-resource-permission-ui
- 前端用户组管理页面更新 → 推迟（现有前端继续使用旧 `/api/v1/group/` API）
- OpenFGA 元组实际写入 → 委托 F004-rebac-core 的 PermissionService
- GroupResource 表操作 → F006-permission-migration 处理废弃迁移

**关键决策（预判）**:
- AD-01: 新建 `user_group/` DDD 模块，旧 `api/v1/usergroup.py` + `RoleGroupService` 保留不动
- AD-02: ORM 继续在 `database/models/group.py` 和 `user_group.py`，与 F001/F002 一致
- AD-03: Group 表加 `visibility` 列 + 改 unique 约束为 `(tenant_id, group_name)`
- AD-04: UserGroup 表 tenant_id 不额外处理（F001 已添加，SQLAlchemy event 自动注入）
- AD-05: 权限检查暂用系统管理员判断（`login_user.is_admin()`），F004 后替换
- AD-06: is_group_admin 保留 MySQL 字段 + GroupChangeHandler 产出 admin 元组（双轨）
- AD-07: 用户组硬删除（临时项目组无需归档，与部门 archived 模式不同）
- AD-08: GroupChangeHandler 独立定义 TupleOperation（与 F002 相同 dataclass）
- AD-09: 新端点 `/api/v1/user-groups/...`，旧 `/api/v1/group/...` 原样保留

**关键文件（预判）**:
- 修改: `src/backend/bisheng/database/models/group.py`（扩展字段 + async DAO）
- 修改: `src/backend/bisheng/database/models/user_group.py`（async DAO）
- 新建: `src/backend/bisheng/user_group/`（DDD 模块：api/ + domain/）
- 新建: `src/backend/bisheng/common/errcode/user_group.py`
- 新建: `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f003_user_group.py`
- 修改: `src/backend/bisheng/api/router.py`（路由注册）
- 修改: `src/backend/bisheng/common/init_data.py`（默认用户组初始化）

**关联不变量**: INV-1, INV-2

---

## 1. 概述与用户故事

F003 为 BiSheng 引入多租户感知的用户组管理。用户组是跨部门的临时项目组，与部门（长期组织架构）互补。用户组是 ReBAC 权限体系的三大授权主体之一（`user`、`department#member`、`user_group#member`），F003 建立其数据基础和 OpenFGA 契约。

无论多租户是否启用，用户组功能始终可用。单租户模式下默认租户(id=1)拥有全部用户组；多租户模式下每个租户有独立的用户组空间，名称仅需租户内唯一。

**用户故事 1**:
作为 **BiSheng 系统管理员**，
我希望 **能创建、编辑和删除用户组，并设置用户组的公开/私密可见性**，
以便 **灵活管理跨部门项目团队，私密组可用于敏感项目的权限隔离**。

**用户故事 2**:
作为 **BiSheng 系统管理员**，
我希望 **能向用户组批量添加/移除成员，并设置组管理员**，
以便 **后续通过用户组批量授予资源访问权限，组管理员可辅助管理组内事务**。

**用户故事 3**:
作为 **BiSheng 普通用户**，
我希望 **能看到所有公开的用户组和自己加入的私密用户组**，
以便 **了解自己的组织归属，在资源授权时选择合适的用户组**。

**用户故事 4**:
作为 **BiSheng 后续 Feature 开发者**，
我希望 **F003 提供 GroupChangeHandler 元组 DTO 和 `acreate_default_group()` 服务方法**，
以便 **F004 的 PermissionService 能消费用户组变更事件，F010 的租户创建流程能原子地创建默认用户组**。

**用户故事 5**:
作为 **BiSheng 运维人员**，
我希望 **升级到 v2.5.0 时现有用户组自动获得 visibility='public'，旧 API 继续正常工作**，
以便 **零迁移成本升级，不影响现有功能**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | POST /api/v1/user-groups（group_name="Project Alpha", visibility="public"） | 返回 200，data 含 id/group_name/visibility/create_time |
| AC-02 | 管理员 | POST 创建租户内同名用户组 | 返回 23001 UserGroupNameDuplicateError |
| AC-03 | 管理员 | POST 在不同租户创建同名用户组 | 返回 200 成功（名称唯一性是租户级别） |
| AC-04 | 管理员 | GET /api/v1/user-groups?page=1&limit=20 | 返回 200，分页列表，每个组含 member_count + group_admins |
| AC-05 | 管理员 | GET /api/v1/user-groups/{id}（存在的 group_id） | 返回 200，完整组详情含 member_count + group_admins |
| AC-06 | 管理员 | GET /api/v1/user-groups/{id}（不存在的 group_id） | 返回 23000 UserGroupNotFoundError |
| AC-07 | 管理员 | PUT /api/v1/user-groups/{id}（修改 group_name） | 返回 200，group_name 已变更 |
| AC-08 | 管理员 | PUT 修改 group_name 为租户内已存在的名称 | 返回 23001 UserGroupNameDuplicateError |
| AC-09 | 管理员 | DELETE /api/v1/user-groups/{id}（空组，非默认组） | 返回 200，组已删除 |
| AC-10 | 管理员 | DELETE 默认用户组 | 返回 23002 UserGroupDefaultProtectedError |
| AC-11 | 管理员 | DELETE 有成员的用户组 | 返回 23003 UserGroupHasMembersError |
| AC-12 | 管理员 | POST /api/v1/user-groups/{id}/members（user_ids=[3,5,7]） | 返回 200，三个用户成为组成员 |
| AC-13 | 管理员 | POST members 添加已存在的成员 | 返回 23004 UserGroupMemberExistsError |
| AC-14 | 管理员 | GET /api/v1/user-groups/{id}/members?page=1&limit=20 | 返回 200，分页成员列表（PageData 格式），含 user_id/user_name |
| AC-15 | 管理员 | DELETE /api/v1/user-groups/{id}/members/{user_id} | 返回 200，用户从组中移除 |
| AC-16 | 管理员 | DELETE 不存在的组成员 | 返回 23005 UserGroupMemberNotFoundError |
| AC-17 | 非管理员 | 调用任何管理员专属的用户组 API（创建/更新/删除/添加成员等） | 返回 23006 UserGroupPermissionDeniedError |
| AC-18 | 非管理员 | GET 用户组列表（该用户是某 private 组 "X" 的成员） | 列表包含组 "X" 和所有 public 组 |
| AC-19 | 非管理员 | GET private 组详情（该用户不是成员） | 返回 23006 UserGroupPermissionDeniedError |
| AC-20 | 管理员 | PUT /api/v1/user-groups/{id}/admins（user_ids=[1,5]） | 返回 200，管理员列表被全量替换，GroupChangeHandler.on_admin_set/on_admin_removed 被调用 |
| AC-21 | 运维人员 | 首次启动应用（已有默认租户和默认用户组） | 默认用户组(id=2)的 tenant_id=1, visibility='public' |
| AC-22 | 开发者 | 用户组创建/删除/成员变更/管理员变更后检查 GroupChangeHandler | 各事件方法返回正确的 TupleOperation 列表（action/user/relation/object） |
| AC-23 | 运维人员 | 升级后调用旧 API /api/v1/group/* | 所有现有端点继续正常工作 |

---

## 3. 边界情况

- 当 **并发创建同名用户组**时，依赖 MySQL `uk_tenant_group_name` 复合唯一约束。后到的请求收到 IntegrityError，Service 层捕获后返回 23001。不加分布式锁
- 当 **批量添加成员时部分已存在**时，采用整体拒绝策略：任一 user_id 已是成员则全部拒绝并返回 23004（与 F002 部门成员一致）
- 当 **删除组管理员后该用户仍是组成员**时，仅移除 `is_group_admin=1` 的记录，保留 `is_group_admin=0` 的成员记录。如果该用户只有 admin 记录没有 member 记录，则只移除 admin 身份
- 当 **multi_tenant.enabled=false** 时，所有用户组操作正常工作，tenant_id 自动填充为默认租户(id=1)
- 当 **GroupChangeHandler.execute() 被调用**时，当前为日志 stub（F004 未实现），不影响用户组操作本身的执行
- 当 **默认用户组(id=2)被尝试删除或重命名**时，返回 23002 保护错误。默认组名称和存在性是系统约束
- 当 **非管理员查看用户组列表**时，只返回 public 组 + 该用户所属的 private 组（通过 JOIN user_group 过滤）
- 当 **Alembic 迁移在已有数据的生产环境执行**时，visibility 列 DEFAULT 'public' 确保所有现有组自动获得 public 可见性，无需额外回填

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 模块结构 | A: 新建 `user_group/` DDD 模块 / B: 扩展现有 `api/v1/usergroup.py` | 选 A | F002 建立的 DDD 模式。旧代码混合了 GroupResource 逻辑，新模块干净分离 |
| AD-02 | ORM 位置 | A: `database/models/group.py` / B: `user_group/domain/models/` | 选 A | 与 F001 Tenant、F002 Department 一致，ORM+DAO 内聚在 models 文件 |
| AD-03 | Group 表变更策略 | A: 仅加 visibility + 改 unique 约束（tenant_id 已由 F001 添加）/ B: 全面重建表 | 选 A | 最小变更原则，F001 Alembic 已添加 tenant_id |
| AD-04 | UserGroup 表 tenant_id | A: 不额外处理（F001 已添加，自动注入）/ B: 加冗余 tenant_id 字段 | 选 A | 与 F002 UserDepartment 一致，关联表隔离通过主表传递 |
| AD-05 | F004 前的权限检查 | A: 管理员判断 `login_user.is_admin()` / B: 无权限检查 | 选 A | 与 F002 AD-05 一致，基本安全保障 |
| AD-06 | 删除策略 | A: 硬删除 / B: 软删除（archived） | 选 A | 用户组是临时项目组，无需归档保留。与现有 GroupDao.delete_group 行为一致 |
| AD-07 | is_group_admin 处理 | A: 保留 MySQL + GroupChangeHandler 双轨 / B: 立即废弃 | 选 A | 旧 API/前端依赖该字段，F006 迁移后可废弃。双轨确保向后兼容 |
| AD-08 | ChangeHandler 模式 | A: 独立定义 TupleOperation（与 F002 相同 dataclass）/ B: 复用 F002 的导入 | 选 A | 模块独立性，F004 会提供统一入口后各模块 Handler 可收拢 |
| AD-09 | API 路径 | A: 新端点 `/api/v1/user-groups/`，旧保留 / B: 修改旧端点 | 选 A | 旧 API 与 GroupResource 耦合，修改风险大。新 API 干净分离 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

#### group 表（已有，扩展）

```python
class GroupBase(SQLModelSerializable):
    group_name: str = Field(index=False, description='用户组名称')  # 去掉 unique=True
    remark: Optional[str] = Field(default=None, index=False)
    create_user: Optional[int] = Field(default=None, index=True)
    update_user: Optional[int] = Field(default=None)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Group(GroupBase, table=True):
    __tablename__ = 'group'
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    visibility: str = Field(
        default='public',
        sa_column=Column(String(16), nullable=False, server_default=text("'public'"),
                         comment='Visibility: public/private'),
    )

    __table_args__ = (
        UniqueConstraint('tenant_id', 'group_name', name='uk_tenant_group_name'),
    )
```

#### user_group 表（已有，无结构变更）

UserGroup 表结构不变。`tenant_id` 已由 F001 Alembic 迁移添加，SQLAlchemy event 自动注入。`is_group_admin` 保留用于旧 API 兼容。

### Alembic 迁移

```python
# v2_5_0_f003_user_group.py
# Revises: f002_department_tree (或实际的上一个 revision)

def upgrade():
    # 1. Add visibility column
    op.add_column('group', sa.Column('visibility', sa.String(16), nullable=False,
                                      server_default='public', comment='Visibility: public/private'))
    # 2. Drop old unique index on group_name (if exists)
    try:
        op.drop_index('ix_group_group_name', table_name='group')
    except Exception:
        pass  # Index may not exist or have different name
    # 3. Add composite unique constraint
    op.create_unique_constraint('uk_tenant_group_name', 'group', ['tenant_id', 'group_name'])
```

### DAO 方法

| 类 | 方法 | 说明 |
|----|------|------|
| GroupDao | `aget_by_id(group_id)` | 按 ID 异步查询 |
| GroupDao | `acreate(group)` | 异步插入（flush + refresh 获取 id） |
| GroupDao | `aupdate(group)` | 异步更新（commit + refresh） |
| GroupDao | `adelete(group_id)` | 异步硬删除 |
| GroupDao | `aget_all_groups(page, limit, keyword)` | 分页查询当前租户全部组（tenant 自动过滤） |
| GroupDao | `acheck_name_duplicate(name, exclude_id=None)` | 租户内名称重复检查，返回 bool |
| GroupDao | `aget_visible_groups(user_id, page, limit, keyword)` | 非 admin 视角：public + 用户所属的 private 组 |
| UserGroupDao | `aget_group_members(group_id, page, limit, keyword)` | 分页成员列表 JOIN user（is_group_admin=0），含 user_name |
| UserGroupDao | `aget_group_member_count(group_id)` | 非 admin 成员计数 |
| UserGroupDao | `aadd_members_batch(group_id, user_ids)` | 批量添加成员（is_group_admin=0） |
| UserGroupDao | `aremove_member(group_id, user_id)` | 移除单个成员 |
| UserGroupDao | `acheck_members_exist(group_id, user_ids)` | 返回已存在于组中的 user_id 列表 |
| UserGroupDao | `aget_group_admins_detail(group_id)` | 获取组管理员 JOIN user（含 user_id + user_name） |
| UserGroupDao | `aset_admins_batch(group_id, add_ids, remove_ids)` | 批量设置/移除管理员 |
| UserGroupDao | `aget_user_visible_group_ids(user_id)` | 获取用户所属（member 或 admin）的所有 group_id 列表 |

---

## 6. API 契约

### 6.1 创建用户组

```
POST /api/v1/user-groups
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "group_name": "Project Alpha",     // required, 1-128 chars
    "visibility": "public",            // optional, default "public", enum: public/private
    "remark": "跨部门项目组",           // optional
    "admin_user_ids": [1, 5]           // optional, initial admin user IDs
}
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "id": 3,
        "group_name": "Project Alpha",
        "visibility": "public",
        "remark": "跨部门项目组",
        "create_user": 1,
        "create_time": "2026-04-12T10:00:00",
        "update_time": "2026-04-12T10:00:00",
        "member_count": 0,
        "group_admins": [
            {"user_id": 1, "user_name": "admin"},
            {"user_id": 5, "user_name": "manager1"}
        ]
    }
}
```

### 6.2 用户组列表

```
GET /api/v1/user-groups
Auth: UserPayload (admin sees all; non-admin sees public + own groups)
Query: page=1, limit=20, keyword="" (search by group_name)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "data": [
            {
                "id": 2,
                "group_name": "Default user group",
                "visibility": "public",
                "remark": null,
                "member_count": 5,
                "create_user": 1,
                "create_time": "2026-04-01T00:00:00",
                "update_time": "2026-04-12T10:00:00",
                "group_admins": [{"user_id": 1, "user_name": "admin"}]
            }
        ],
        "total": 1
    }
}
```

### 6.3 用户组详情

```
GET /api/v1/user-groups/{group_id}
Auth: UserPayload (admin or group member/admin for private groups)
Path: group_id — 用户组 ID (int)
```

**Response** (200): 同创建响应格式 + member_count + group_admins

### 6.4 更新用户组

```
PUT /api/v1/user-groups/{group_id}
Auth: UserPayload (admin only)
```

**Request Body**（partial update，仅传需要修改的字段）:
```json
{
    "group_name": "New Name",           // optional, 1-128 chars
    "visibility": "private",            // optional
    "remark": "Updated remark"          // optional
}
```

**约束**: 不可修改默认用户组(id=DefaultGroup)的 group_name

### 6.5 删除用户组

```
DELETE /api/v1/user-groups/{group_id}
Auth: UserPayload (admin only)
```

**约束**: 默认组返回 23002，有成员返回 23003。成功后硬删除。

### 6.6 成员列表

```
GET /api/v1/user-groups/{group_id}/members
Auth: UserPayload (admin or group member for private groups)
Query: page=1, limit=20, keyword="" (search by user_name)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "data": [
            {
                "user_id": 3,
                "user_name": "alice",
                "is_group_admin": false,
                "create_time": "2026-04-12T10:00:00"
            }
        ],
        "total": 1
    }
}
```

### 6.7 批量添加成员

```
POST /api/v1/user-groups/{group_id}/members
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "user_ids": [3, 5, 7]    // required, non-empty
}
```

**约束**: 已存在的成员关系返回 23004（整体原子性：任一冲突则全部拒绝）。

### 6.8 移除成员

```
DELETE /api/v1/user-groups/{group_id}/members/{user_id}
Auth: UserPayload (admin only)
```

**约束**: 不存在的成员关系返回 23005。

### 6.9 设置组管理员

```
PUT /api/v1/user-groups/{group_id}/admins
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "user_ids": [1, 5]    // required, full replacement of admin list
}
```

**逻辑**: 全量替换——提供的列表成为完整的管理员集合。Diff 当前与新列表，产出 on_admin_set/on_admin_removed 元组。

---

## 7. Service 层逻辑

### UserGroupService

| 方法 | 核心逻辑 |
|------|---------|
| `acreate_group(data, login_user)` | 权限检查(admin) → 校验 group_name 租户内不重复(23001) → INSERT Group → 设置初始 admins(如提供) → 调用 ChangeHandler.on_created → 返回完整对象 |
| `alist_groups(page, limit, keyword, login_user)` | admin 查全部组 / 非 admin 查 public + 所属组 → 分页 → 批量附加 member_count + group_admins → 返回 PageData |
| `aget_group(group_id, login_user)` | 按 ID 查询(23000 not found) → 可见性检查(private 组非 admin 需是成员, 23006) → 附加 member_count + admins → 返回 |
| `aupdate_group(group_id, data, login_user)` | 权限检查 → 查询组(23000) → 如修改 group_name 则校验不重复(23001) → UPDATE → 返回 |
| `adelete_group(group_id, login_user)` | 权限检查 → 不可删默认组(23002) → 检查无成员(23003) → DELETE → 调用 ChangeHandler.on_deleted → 返回 |
| `aget_members(group_id, page, limit, keyword, login_user)` | 可见性检查(private 组非 admin 需是成员) → 分页查询 UserGroup JOIN User(is_group_admin=0) → 返回 PageData |
| `aadd_members(group_id, user_ids, login_user)` | 权限检查 → 校验组存在(23000) → 校验无重复成员(23004) → 批量 INSERT → 调用 ChangeHandler.on_members_added → 返回 |
| `aremove_member(group_id, user_id, login_user)` | 权限检查 → 校验成员关系存在(23005) → DELETE → 调用 ChangeHandler.on_member_removed → 返回 |
| `aset_admins(group_id, user_ids, login_user)` | 权限检查 → 获取当前 admin 列表 → Diff(to_add, to_remove) → 批量增删 admin 行 → 调用 ChangeHandler.on_admin_set/on_admin_removed → 返回 |
| `acreate_default_group(tenant_id, creator_id)` | 静态方法，使用 bypass_tenant_filter → INSERT 默认组(group_name='Default user group', visibility='public') → 返回。供 init_data / F010 调用 |

### GroupChangeHandler

为 F004 预留的契约接口。定义 `TupleOperation` DTO，各事件方法产出正确的元组操作列表，`execute()` 当前为日志 stub。

```python
@dataclass
class TupleOperation:
    action: Literal['write', 'delete']
    user: str        # e.g. "user:7"
    relation: str    # e.g. "member", "admin"
    object: str      # e.g. "user_group:5"
```

| 事件方法 | 产出的元组 |
|---------|-----------|
| `on_created(group_id, creator_id)` | `write(user:{creator}, admin, user_group:{group_id})` |
| `on_deleted(group_id)` | 空列表（F004 负责级联清理删除组相关的全部元组） |
| `on_members_added(group_id, user_ids)` | 每个 user_id: `write(user:{uid}, member, user_group:{group_id})` |
| `on_member_removed(group_id, user_id)` | `delete(user:{uid}, member, user_group:{group_id})` |
| `on_admin_set(group_id, user_ids)` | 每个 user_id: `write(user:{uid}, admin, user_group:{group_id})` |
| `on_admin_removed(group_id, user_ids)` | 每个 user_id: `delete(user:{uid}, admin, user_group:{group_id})` |

---

## 8. 前端设计

N/A — F003 不涉及前端变更。现有前端用户组管理页面继续使用旧 `/api/v1/group/` 端点。前端迁移到新 API 推迟到后续 Feature。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/common/errcode/user_group.py` | 230xx 用户组错误码（7 个） |
| `src/backend/bisheng/user_group/__init__.py` | DDD 模块包 |
| `src/backend/bisheng/user_group/api/__init__.py` | API 子包 |
| `src/backend/bisheng/user_group/api/router.py` | 路由聚合，prefix `/user-groups` |
| `src/backend/bisheng/user_group/api/endpoints/__init__.py` | 端点子包 |
| `src/backend/bisheng/user_group/api/endpoints/user_group.py` | 用户组 CRUD 端点（5 个） |
| `src/backend/bisheng/user_group/api/endpoints/user_group_member.py` | 成员管理端点（4 个） |
| `src/backend/bisheng/user_group/domain/__init__.py` | 领域子包 |
| `src/backend/bisheng/user_group/domain/schemas/__init__.py` | DTO 子包 |
| `src/backend/bisheng/user_group/domain/schemas/user_group_schema.py` | 请求/响应 Pydantic DTO |
| `src/backend/bisheng/user_group/domain/services/__init__.py` | 服务子包 |
| `src/backend/bisheng/user_group/domain/services/user_group_service.py` | 用户组核心业务逻辑 |
| `src/backend/bisheng/user_group/domain/services/group_change_handler.py` | TupleOperation DTO + 事件方法 + execute() 日志 stub |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f003_user_group.py` | Alembic 迁移脚本 |
| `src/backend/test/test_user_group_dao.py` | DAO 单元测试 |
| `src/backend/test/test_group_change_handler.py` | ChangeHandler 单元测试 |
| `src/backend/test/test_user_group_service.py` | Service 单元测试 |
| `src/backend/test/test_user_group_api.py` | API 集成测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/database/models/group.py` | Group 类添加 `__tablename__`、`tenant_id`、`visibility` 字段声明、`__table_args__` 复合唯一约束；GroupBase 去掉 `unique=True`；GroupDao 添加 async 方法 |
| `src/backend/bisheng/database/models/user_group.py` | UserGroupDao 添加 async 方法 |
| `src/backend/bisheng/api/router.py` | 导入并注册 `user_group_router` |
| `src/backend/bisheng/common/init_data.py` | 添加 `_init_default_user_group(session)` 函数确保默认组有 visibility='public' |
| `features/v2.5.0/release-contract.md` | 注册模块编码 230 = user_group |
| `src/backend/test/fixtures/table_definitions.py` | TABLE_GROUP 增加 visibility 列定义 |
| `src/backend/test/fixtures/factories.py` | 添加 `create_group()` + `create_user_group_member()` 工厂函数 |

---

## 10. 非功能要求

- **性能**: 列表查询分页，每页默认 20 条。admin 列表一次加载全部组（通常 < 100），内存附加 member_count + admins。非 admin 视角需额外 JOIN user_group 过滤，但数据量有限不构成瓶颈
- **安全**: 管理操作（CRUD/成员管理）要求管理员权限（F004 前使用 `login_user.is_admin()`）。查询操作按可见性控制。tenant_id 自动过滤防止跨租户数据泄漏（INV-1）
- **兼容性**: 旧 API `/api/v1/group/` 和 `RoleGroupService` 完全不动。Alembic 迁移 visibility 列 DEFAULT 'public' 确保存量数据零迁移。DefaultGroup=2 常量保留
- **可测试性**: DAO 测试使用 SQLite in-memory（conftest.py fixture）。Service 测试可 mock DAO。API 测试使用 TestClient
- **可扩展性**: GroupChangeHandler 的 TupleOperation DTO 是 F004 集成的契约边界。visibility 枚举未来可扩展（如 'team_only'）。`acreate_default_group()` 方法供 F010 租户创建调用

---

## 11. 错误码表

> 模块编码 230（user_group），需在 release-contract.md 注册。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 23000 | UserGroupNotFoundError | 用户组 ID 不存在 | AC-06 |
| 200 (body) | 23001 | UserGroupNameDuplicateError | 租户内用户组名称重复 | AC-02, AC-08 |
| 200 (body) | 23002 | UserGroupDefaultProtectedError | 不可删除/重命名默认用户组 | AC-10 |
| 200 (body) | 23003 | UserGroupHasMembersError | 有成员不可删除 | AC-11 |
| 200 (body) | 23004 | UserGroupMemberExistsError | 用户已是组成员 | AC-13 |
| 200 (body) | 23005 | UserGroupMemberNotFoundError | 用户不是组成员 | AC-16 |
| 200 (body) | 23006 | UserGroupPermissionDeniedError | 无权限操作 | AC-17, AC-19 |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- F002 部门树 spec（模式参考）: `features/v2.5.0/002-department-tree/spec.md`
