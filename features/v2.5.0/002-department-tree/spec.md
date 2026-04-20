# Feature: 部门树

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P0
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- Department ORM（物化路径 path、dept_id、external_id、source、status、default_role_ids、tenant_id）
- UserDepartment ORM（user_id、department_id、is_primary、source）
- Department CRUD API（创建/详情/树形查询/更新/归档/移动/成员增删/成员列表）共 9 个端点
- 物化路径维护逻辑（创建/移动/删除时自动更新 path）
- 提供 `create_root_department(tenant_id, name)` 服务方法供租户创建调用
- init_data 为默认租户(id=1)自动创建根部门
- DepartmentChangeHandler：TupleOperation DTO 定义 + 事件方法产出元组列表 + execute() 日志 stub
- 错误码模块 210（21000~21009）

**OUT**:
- 前端部门管理页面 → F010-tenant-management-ui
- 三方组织同步 → F009-org-sync（P2）
- 部门管理员（admin）CRUD → F004-rebac-core（admin 关系存 OpenFGA）
- 部门 admin OpenFGA 元组实际写入 → 委托 F004-rebac-core 的 PermissionService
- 复杂授权 UI → F007-resource-permission-ui

**关键决策（预判）**:
- AD-01: 物化路径格式 `/1/2/3/`，子树查询用 `LIKE '/1/2/%'`
- AD-02: DepartmentChangeHandler 产出元组操作列表但不直接写 OpenFGA，委托 PermissionService（F004），尊重领域归属边界
- AD-03: 根部门创建是租户创建的同步副作用，F002 提供 service 方法，F001/F010 调用
- AD-04: ORM 放 `database/models/department.py`，与 Tenant（F001）一致
- AD-05: 权限检查暂用系统管理员判断（`login_user.is_admin()`），F004 后替换为 OpenFGA 检查
- AD-06: path 两阶段写入（INSERT → UPDATE path），因 path 包含自身 auto_increment id
- AD-07: UserDepartment 不加 tenant_id，隔离通过 Department.tenant_id 传递

**关键文件（预判）**:
- 新建: `src/backend/bisheng/database/models/department.py`
- 新建: `src/backend/bisheng/department/`（DDD 模块：api/ + domain/）
- 新建: `src/backend/bisheng/common/errcode/department.py`
- 修改: `src/backend/bisheng/api/router.py`（路由注册）
- 修改: `src/backend/bisheng/common/init_data.py`（默认根部门创建）

**关联不变量**: INV-1, INV-12, INV-14

---

## 1. 概述与用户故事

F002 为 BiSheng 引入组织架构的核心数据结构——部门树。部门树使用物化路径存储，支持无限层级、高效子树查询，是后续 ReBAC 权限（F004）、角色配额（F005）、资源授权管理（F007/F008）的基础。

无论多租户是否启用，部门功能始终可用。单租户模式下默认租户(id=1)拥有一棵组织树；多租户模式下每个租户各有独立的组织树。

**用户故事 1**:
作为 **BiSheng 系统管理员**，
我希望 **能创建、编辑、移动和归档部门，构建树形组织架构**，
以便 **将用户按组织结构分组管理，后续为部门级别分配资源访问权限**。

**用户故事 2**:
作为 **BiSheng 系统管理员**，
我希望 **能批量将用户添加到部门并管理主/挂靠关系**，
以便 **每个用户都有明确的组织归属，支持一人多部门场景**。

**用户故事 3**:
作为 **BiSheng 后续 Feature 开发者**，
我希望 **F002 提供 `create_root_department()` 服务方法和 DepartmentChangeHandler 元组 DTO**，
以便 **F001/F010 的租户创建流程能原子地创建根部门，F004 的 PermissionService 能消费部门变更事件**。

**用户故事 4**:
作为 **BiSheng 运维人员**，
我希望 **升级到 v2.5.0 时默认租户自动获得根部门，存量系统正常运行**，
以便 **零迁移成本升级，不影响现有功能**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | POST /api/v1/departments（name="研发部", parent_id=根部门 id） | 返回 200，data 含 id/dept_id/name/path，path 格式 `/{root_id}/{new_id}/`，dept_id 为自动生成的业务键 |
| AC-02 | 管理员 | POST 创建同名兄弟部门 | 返回 21001 DepartmentNameDuplicateError |
| AC-03 | 管理员 | GET /api/v1/departments/tree | 返回当前租户完整部门树（嵌套结构），每个节点含 id/dept_id/name/path/children/member_count |
| AC-04 | 管理员 | GET /api/v1/departments/{dept_id}（存在的 dept_id） | 返回部门详情，含全部字段 |
| AC-05 | 管理员 | PUT /api/v1/departments/{dept_id}（修改 name） | 返回更新后的部门，name 已变更 |
| AC-06 | 管理员 | PUT 修改 source='feishu' 的部门 name | 返回 21005 DepartmentSourceReadonlyError |
| AC-07 | 管理员 | DELETE /api/v1/departments/{dept_id}（无子部门无成员） | 返回 200，部门 status 变为 'archived' |
| AC-08 | 管理员 | DELETE 有子部门的部门 | 返回 21002 DepartmentHasChildrenError |
| AC-09 | 管理员 | DELETE 有成员的部门 | 返回 21003 DepartmentHasMembersError |
| AC-10 | 管理员 | POST /api/v1/departments/{dept_id}/move（new_parent_id=有效部门） | 返回 200，该部门及其所有子孙的 path 正确更新 |
| AC-11 | 管理员 | POST move 将部门移到自己的子孙下 | 返回 21004 DepartmentCircularMoveError |
| AC-12 | 管理员 | POST /api/v1/departments/{dept_id}/members（user_ids=[1,2,3]） | 返回 200，三个用户成为部门成员 |
| AC-13 | 管理员 | POST members 添加已存在的成员 | 返回 21007 DepartmentMemberExistsError |
| AC-14 | 管理员 | GET /api/v1/departments/{dept_id}/members?page=1&limit=20 | 返回分页成员列表（PageData 格式），含 user_id/user_name/is_primary/source |
| AC-15 | 管理员 | DELETE /api/v1/departments/{dept_id}/members/{user_id} | 返回 200，用户从部门移除 |
| AC-16 | 非管理员 | 调用任何部门管理 API | 返回 21009 DepartmentPermissionDeniedError |
| AC-17 | 运维人员 | 首次启动应用（已有默认租户） | 默认租户(id=1)自动获得根部门，tenant.root_dept_id 已回写 |
| AC-18 | 开发者 | 调用 create_root_department(tenant_id, name) | 创建根部门（parent_id=None, path=`/{id}/`），回写 tenant.root_dept_id |
| AC-19 | 开发者 | 对已有根部门的租户再次调用 create_root_department | 返回 21006 DepartmentRootExistsError |
| AC-20 | 开发者 | 部门创建/移动/归档/成员变更后检查 DepartmentChangeHandler | 各事件方法返回正确的 TupleOperation 列表（action/user/relation/object） |

---

## 3. 边界情况

- 当 **物化路径长度接近 512 字符**时（约 50+ 层嵌套），path 字段 VARCHAR(512) 可能不足。实际企业组织通常不超过 10 层。当前不做软限制，未来需要时可扩展字段长度
- 当 **并发创建同名兄弟部门**时，依赖 MySQL 事务隔离和 name 唯一性检查（同一 parent_id 下）。不加分布式锁，允许并发失败后重试
- 当 **移动部门时子树规模很大**时（数百个子孙），`UPDATE ... WHERE path LIKE` 批量更新在单事务中执行。MySQL InnoDB 行锁可能导致短暂阻塞，但企业组织树通常规模有限（< 1000 部门），不构成性能瓶颈
- 当 **已归档部门**被引用时，归档部门不出现在树查询结果中（`WHERE status='active'`），但数据保留。物理删除需管理员在 F010 中二次确认
- 当 **用户被删除但 user_department 记录残留**时，成员查询 JOIN user 表时自动过滤已删除用户（`user.delete=0`）
- 当 **dept_id 生成冲突**时（极低概率），INSERT 触发 UNIQUE 约束异常，Service 层捕获后重试（最多 3 次）
- 当 **multi_tenant.enabled=false**时，所有部门操作正常工作，tenant_id 自动填充为默认租户(id=1)
- 当 **DepartmentChangeHandler.execute() 被调用**时，当前为日志 stub（F004 未实现），不影响部门操作本身的执行

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 树结构存储方案 | A: 物化路径（path） / B: 嵌套集合 / C: 闭包表 | 选 A | PRD 规定物化路径。子树查询 `LIKE '/x/%'` + INDEX 高效，移动操作只需批量字符串替换，实现简单 |
| AD-02 | 变更事件处理 | A: Handler 产出 DTO，委托 F004 写入 / B: F002 直接写 OpenFGA | 选 A | 尊重领域归属边界（release-contract 规定 PermissionTuple Owner 是 F004）。DTO 是契约，便于 F004 集成 |
| AD-03 | 根部门创建时机 | A: 租户创建的同步副作用 / B: 异步事件触发 | 选 A | INV-14 要求原子性。F002 提供 service 方法，调用方（init_data / F010）在同一事务中调用 |
| AD-04 | ORM 模型位置 | A: `database/models/department.py` / B: `department/domain/models/` | 选 A | 与 F001 Tenant 一致，arch-guard 兼容。DAO 方法内聚在 ORM 文件中 |
| AD-05 | F004 前的权限检查 | A: 系统管理员判断 / B: 无权限检查 | 选 A | 基本安全保障，防止普通用户修改组织架构。F004 实现后替换为 OpenFGA 细粒度检查 |
| AD-06 | path 写入策略 | A: 两阶段（INSERT → UPDATE path） / B: 预分配 ID | 选 A | MySQL auto_increment 不支持预分配。先插入获取 id，再 UPDATE path 是标准做法 |
| AD-07 | UserDepartment 是否含 tenant_id | A: 不含（通过 Department.tenant_id 传递） / B: 含 tenant_id | 选 A | 纯关联表，JOIN 查询时 Department 已按 tenant 过滤。避免冗余字段，与 user_tenant 模式一致 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

#### department 表

```python
class Department(SQLModelSerializable, table=True):
    __tablename__ = 'department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    dept_id: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True,
                         comment='Business key, e.g. BS@89757'),
    )
    name: str = Field(
        sa_column=Column(String(128), nullable=False, comment='Department name'),
    )
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True,
                         comment='Parent department ID, NULL=root'),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    path: str = Field(
        default='',
        sa_column=Column(String(512), nullable=False, server_default=text("''"),
                         index=True, comment='Materialized path /1/2/3/'),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0'),
                         comment='Sort order among siblings'),
    )
    source: str = Field(
        default='local',
        sa_column=Column(String(32), nullable=False, server_default=text("'local'"),
                         comment='Source: local/feishu/wecom/dingtalk'),
    )
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True,
                         comment='External department ID for sync'),
    )
    status: str = Field(
        default='active',
        sa_column=Column(String(16), nullable=False, server_default=text("'active'"),
                         index=True, comment='Status: active/archived'),
    )
    default_role_ids: Optional[list] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True,
                         comment='Default role IDs for department members'),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Creator user ID'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
    )

    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uk_source_external_id'),
    )
```

#### user_department 表

```python
class UserDepartment(SQLModelSerializable, table=True):
    __tablename__ = 'user_department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment='User ID'),
    )
    department_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment='Department ID'),
    )
    is_primary: int = Field(
        default=1,
        sa_column=Column(SmallInteger, nullable=False, server_default=text('1'),
                         comment='1=primary department, 0=secondary'),
    )
    source: str = Field(
        default='local',
        sa_column=Column(String(32), nullable=False, server_default=text("'local'"),
                         comment='Source: local/feishu/wecom/dingtalk'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP')),
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'department_id', name='uk_user_dept'),
    )
```

### DAO 方法

| 类 | 方法 | 说明 |
|----|------|------|
| DepartmentDao | `get_by_id(id)` / `aget_by_id(id)` | 按主键查询 |
| DepartmentDao | `get_by_dept_id(dept_id)` / `aget_by_dept_id(dept_id)` | 按业务键查询 |
| DepartmentDao | `create(dept)` / `acreate(dept)` | 插入部门（含 flush 获取 id） |
| DepartmentDao | `update(dept)` / `aupdate(dept)` | 更新部门 |
| DepartmentDao | `get_children(parent_id)` / `aget_children(parent_id)` | 直接子部门列表 |
| DepartmentDao | `get_subtree(path_prefix)` / `aget_subtree(path_prefix)` | 子树查询 `LIKE '{path}%'` |
| DepartmentDao | `get_subtree_ids(path_prefix)` / `aget_subtree_ids(path_prefix)` | 子树 ID 列表（用于权限展开） |
| DepartmentDao | `get_all_active()` / `aget_all_active()` | 当前租户全部活跃部门（树查询用） |
| DepartmentDao | `update_paths_batch(old_prefix, new_prefix)` / `aupdate_paths_batch(...)` | 移动时批量更新子树 path |
| DepartmentDao | `get_root_by_tenant(tenant_id)` / `aget_root_by_tenant(tenant_id)` | 租户根部门查询 |
| DepartmentDao | `check_name_duplicate(parent_id, name, exclude_id)` / `acheck_name_duplicate(...)` | 同级名称重复检查 |
| UserDepartmentDao | `add_member(user_id, dept_id, is_primary)` / `aadd_member(...)` | 添加成员 |
| UserDepartmentDao | `batch_add_members(entries)` / `abatch_add_members(...)` | 批量添加成员 |
| UserDepartmentDao | `remove_member(user_id, dept_id)` / `aremove_member(...)` | 移除成员 |
| UserDepartmentDao | `get_members(dept_id, page, limit, keyword)` / `aget_members(...)` | 分页成员列表（JOIN user） |
| UserDepartmentDao | `get_member_count(dept_id)` / `aget_member_count(dept_id)` | 成员计数 |
| UserDepartmentDao | `get_user_departments(user_id)` / `aget_user_departments(user_id)` | 用户所属部门列表 |
| UserDepartmentDao | `get_user_primary_department(user_id)` / `aget_user_primary_department(user_id)` | 用户主部门 |
| UserDepartmentDao | `check_member_exists(user_id, dept_id)` / `acheck_member_exists(...)` | 成员关系是否存在 |

---

## 6. API 契约

### 6.1 创建部门

```
POST /api/v1/departments
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "name": "研发部",          // 2-50 chars, required
    "parent_id": 1,            // required, must exist and be active
    "sort_order": 0,           // optional, default 0
    "default_role_ids": [2]    // optional, role ID list
}
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "id": 2,
        "dept_id": "BS@a3f7e",
        "name": "研发部",
        "parent_id": 1,
        "path": "/1/2/",
        "sort_order": 0,
        "source": "local",
        "status": "active",
        "default_role_ids": [2],
        "create_time": "2026-04-12T10:00:00"
    }
}
```

### 6.2 获取部门树

```
GET /api/v1/departments/tree
Auth: UserPayload (admin only)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": [
        {
            "id": 1,
            "dept_id": "BS@root1",
            "name": "Default Organization",
            "parent_id": null,
            "path": "/1/",
            "sort_order": 0,
            "source": "local",
            "status": "active",
            "member_count": 5,
            "children": [
                {
                    "id": 2,
                    "dept_id": "BS@a3f7e",
                    "name": "研发部",
                    "parent_id": 1,
                    "path": "/1/2/",
                    "member_count": 3,
                    "children": []
                }
            ]
        }
    ]
}
```

### 6.3 获取部门详情

```
GET /api/v1/departments/{dept_id}
Auth: UserPayload (admin only)
Path: dept_id — 部门业务键 (e.g. "BS@a3f7e")
```

**Response** (200): 部门完整字段（同创建响应格式）+ member_count

### 6.4 更新部门

```
PUT /api/v1/departments/{dept_id}
Auth: UserPayload (admin only)
```

**Request Body**（partial update，仅传需要修改的字段）:
```json
{
    "name": "新名称",           // optional, 2-50 chars
    "sort_order": 1,            // optional
    "default_role_ids": [2, 3]  // optional
}
```

**约束**: source 非 'local' 的部门不允许修改 name

### 6.5 归档/删除部门

```
DELETE /api/v1/departments/{dept_id}
Auth: UserPayload (admin only)
```

**约束**: 有子部门返回 21002，有成员返回 21003。成功后 status='archived'。

### 6.6 移动部门

```
POST /api/v1/departments/{dept_id}/move
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "new_parent_id": 3    // required, must exist, not self or descendant
}
```

**逻辑**: 更新 parent_id，批量更新 path（该部门及其全部子孙）。

### 6.7 获取部门成员列表

```
GET /api/v1/departments/{dept_id}/members
Auth: UserPayload (admin only)
Query: page=1, limit=20, keyword="" (optional, search by user_name)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "data": [
            {
                "user_id": 1,
                "user_name": "admin",
                "department_id": 2,
                "is_primary": 1,
                "source": "local",
                "create_time": "2026-04-12T10:00:00"
            }
        ],
        "total": 1
    }
}
```

### 6.8 批量添加成员

```
POST /api/v1/departments/{dept_id}/members
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "user_ids": [1, 2, 3],   // required, non-empty
    "is_primary": 0           // optional, default 0 (secondary)
}
```

**约束**: 已存在的成员关系返回 21007（整体原子性：任一冲突则全部拒绝）。

### 6.9 移除成员

```
DELETE /api/v1/departments/{dept_id}/members/{user_id}
Auth: UserPayload (admin only)
```

**约束**: 不存在的成员关系返回 21008。

---

## 7. Service 层逻辑

### DepartmentService

| 方法 | 核心逻辑 |
|------|---------|
| `create_department(name, parent_id, login_user, ...)` | 权限检查(admin) → 校验父部门存在+active → 校验名称不重复 → 生成 dept_id → INSERT → UPDATE path=`{parent.path}{id}/` → 调用 ChangeHandler.on_created → 返回 |
| `get_tree(login_user)` | 查询当前租户全部 active 部门 → 内存构建树（parent_id 关联）→ 按 sort_order 排序 → 附加 member_count → 返回嵌套结构 |
| `get_department(dept_id, login_user)` | 权限检查 → 按 dept_id 查询 → 附加 member_count → 返回 |
| `update_department(dept_id, update_data, login_user)` | 权限检查 → 校验 source='local'（否则 21005）→ 校验名称不重复 → UPDATE → 返回 |
| `delete_department(dept_id, login_user)` | 权限检查 → 校验无子部门（21002）→ 校验无成员（21003）→ UPDATE status='archived' → 调用 ChangeHandler.on_archived → 返回 |
| `move_department(dept_id, new_parent_id, login_user)` | 权限检查 → 校验新父部门存在 → 校验不是移到自己子树（循环检测：new_parent.path 不以 dept.path 开头）→ 计算 new_path → 批量 UPDATE 子树 path（REPLACE old_prefix → new_prefix）→ UPDATE parent_id → 调用 ChangeHandler.on_moved → 返回 |
| `create_root_department(tenant_id, name)` | 校验该租户无根部门（21006）→ INSERT(parent_id=None) → UPDATE path=`/{id}/` → UPDATE tenant.root_dept_id → 返回 |
| `add_members(dept_id, user_ids, is_primary, login_user)` | 权限检查 → 校验部门存在 → 校验成员不重复（21007）→ 批量 INSERT → 调用 ChangeHandler.on_members_added → 返回 |
| `remove_member(dept_id, user_id, login_user)` | 权限检查 → 校验成员关系存在（21008）→ DELETE → 调用 ChangeHandler.on_member_removed → 返回 |
| `get_members(dept_id, page, limit, keyword, login_user)` | 权限检查 → 分页查询 UserDepartment JOIN User → 返回 PageData |

### DepartmentChangeHandler

为 F004 预留的契约接口。定义 `TupleOperation` DTO，各事件方法产出正确的元组操作列表，`execute()` 当前为日志 stub。

```python
@dataclass
class TupleOperation:
    action: Literal['write', 'delete']
    user: str        # e.g. "user:7" or "department:5#member"
    relation: str    # e.g. "member", "admin", "parent"
    object: str      # e.g. "department:5"
```

| 事件方法 | 产出的元组 |
|---------|-----------|
| `on_created(dept)` | `write(department:{parent_id}, parent, department:{id})` |
| `on_moved(dept, old_parent, new_parent)` | `delete(department:{old_parent}, parent, department:{id})` + `write(department:{new_parent}, parent, department:{id})` |
| `on_archived(dept)` | `delete(department:{parent_id}, parent, department:{id})` |
| `on_members_added(dept, user_ids)` | 每个 user_id: `write(user:{uid}, member, department:{id})` |
| `on_member_removed(dept, user_id)` | `delete(user:{uid}, member, department:{id})` |

### dept_id 生成

工具函数 `generate_dept_id(prefix="BS") -> str`，格式 `{prefix}@{random_5_hex}`。INSERT 时如果 UNIQUE 冲突，重试最多 3 次。

---

## 8. 前端设计

N/A — F002 不涉及前端变更。部门管理前端页面由 F010 实现。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/database/models/department.py` | Department + UserDepartment ORM + DepartmentDao + UserDepartmentDao |
| `src/backend/bisheng/common/errcode/department.py` | 210xx 部门错误码（10 个） |
| `src/backend/bisheng/department/__init__.py` | DDD 模块包 |
| `src/backend/bisheng/department/api/__init__.py` | API 子包 |
| `src/backend/bisheng/department/api/router.py` | 路由聚合，prefix `/departments` |
| `src/backend/bisheng/department/api/endpoints/__init__.py` | 端点子包 |
| `src/backend/bisheng/department/api/endpoints/department.py` | 部门 CRUD + tree + move 端点 |
| `src/backend/bisheng/department/api/endpoints/department_member.py` | 成员管理端点 |
| `src/backend/bisheng/department/domain/__init__.py` | 领域子包 |
| `src/backend/bisheng/department/domain/schemas/__init__.py` | DTO 子包 |
| `src/backend/bisheng/department/domain/schemas/department_schema.py` | 请求/响应 Pydantic DTO |
| `src/backend/bisheng/department/domain/services/__init__.py` | 服务子包 |
| `src/backend/bisheng/department/domain/services/department_service.py` | 部门核心业务逻辑 |
| `src/backend/bisheng/department/domain/services/department_change_handler.py` | TupleOperation DTO + 事件方法 + execute() 日志 stub |
| `src/backend/test/test_department_dao.py` | DAO 单元测试 |
| `src/backend/test/test_department_service.py` | Service 单元测试 |
| `src/backend/test/test_department_api.py` | API 集成测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/api/router.py` | 导入并注册 `department_router` |
| `src/backend/bisheng/common/init_data.py` | 添加 `_init_default_root_department(session)` 函数，在 `_init_default_tenant()` 后调用 |
| `src/backend/test/fixtures/table_definitions.py` | TABLE_DEPARTMENT 增加 dept_id/default_role_ids/create_user，TABLE_USER_DEPARTMENT 增加 source |
| `src/backend/test/fixtures/factories.py` | 添加 `create_department()` + `create_user_department()` 工厂函数 |

---

## 10. 非功能要求

- **性能**: 树查询一次加载当前租户全部活跃部门（通常 < 1000），内存构建树结构。物化路径 INDEX 支持高效子树查询。移动操作的批量 path 更新在单事务中完成
- **安全**: 所有端点要求管理员权限（F004 前使用 `login_user.is_admin()` 判断）。tenant_id 自动过滤防止跨租户数据泄漏（INV-1）
- **兼容性**: 默认租户(id=1)升级后自动获得根部门。单租户模式行为不变。UserDepartment 无 tenant_id，通过 Department 传递隔离
- **可测试性**: DAO 测试使用 SQLite in-memory（conftest.py fixture）。Service 测试可 mock DAO。API 测试使用 TestClient
- **可扩展性**: DepartmentChangeHandler 的 TupleOperation DTO 是 F004 集成的契约边界。dept_id 前缀可配置化。source 字段为 F009 三方同步预留

---

## 11. 错误码表

> 模块编码 210（department），已在 release-contract.md 注册。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 21000 | DepartmentNotFoundError | 部门 ID 不存在 | AC-04 |
| 200 (body) | 21001 | DepartmentNameDuplicateError | 同级部门名称重复 | AC-02 |
| 200 (body) | 21002 | DepartmentHasChildrenError | 有子部门不可删除 | AC-08 |
| 200 (body) | 21003 | DepartmentHasMembersError | 有成员不可删除 | AC-09 |
| 200 (body) | 21004 | DepartmentCircularMoveError | 不能移动到自己的子树 | AC-11 |
| 200 (body) | 21005 | DepartmentSourceReadonlyError | 三方同步部门不可修改 | AC-06 |
| 200 (body) | 21006 | DepartmentRootExistsError | 租户根部门已存在 | AC-19 |
| 200 (body) | 21007 | DepartmentMemberExistsError | 用户已是部门成员 | AC-13 |
| 200 (body) | 21008 | DepartmentMemberNotFoundError | 用户不是部门成员 | AC-15 |
| 200 (body) | 21009 | DepartmentPermissionDeniedError | 无部门操作权限 | AC-16 |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
