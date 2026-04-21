# Tasks: 用户组

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-12 审查通过（2 low 项已确认跳过） |
| tasks.md | ✅ 已拆解 | 2026-04-12 审查通过（Round 2），8 个任务 |
| 实现 | ✅ 已完成 | 8 / 8 完成，49 tests passed |

---

## 开发模式

**后端 Test-First（务实版）**：
- ORM + DAO 层和 Service 层的实现与测试合并在同一任务中（与 F001/F002 一致）
- API 层实现后补集成测试
- GroupChangeHandler 含独立单元测试

**前端**：N/A — F003 不涉及前端

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## 依赖图

```
T001 (errcode + release-contract)
  │
  ├─→ T002 (ORM + DAO + Alembic 迁移 + DAO 测试)
  │     │
  │     └─→ T003 (测试基础设施 table_definitions + factories)
  │
  ├─→ T004 (GroupChangeHandler DTO + stub + 测试)
  │
  └─→ T005 (Pydantic DTO)
       │
       └──→ T006 (Service + Service 测试)  ← 也依赖 T002, T004
              │
              └─→ T007 (API 端点 + router 注册 + init_data)
                   │
                   └─→ T008 (API 集成测试)
```

---

## Tasks

### 数据层

- [x] **T001**: 错误码 230xx + release-contract 注册
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/user_group.py` — 230xx 错误码
  **文件（修改）**:
  - `features/v2.5.0/release-contract.md` — 注册模块编码 230
  **逻辑**:
  - **错误码**（继承 `BaseErrorCode`，参照 `common/errcode/department.py`）:
    - `UserGroupNotFoundError(Code=23000, Msg='User group not found')`
    - `UserGroupNameDuplicateError(Code=23001, Msg='User group name already exists in this tenant')`
    - `UserGroupDefaultProtectedError(Code=23002, Msg='Cannot delete or rename default user group')`
    - `UserGroupHasMembersError(Code=23003, Msg='Cannot delete user group with members')`
    - `UserGroupMemberExistsError(Code=23004, Msg='User is already a member of this group')`
    - `UserGroupMemberNotFoundError(Code=23005, Msg='User is not a member of this group')`
    - `UserGroupPermissionDeniedError(Code=23006, Msg='No permission for this user group operation')`
  - **release-contract.md** 表「已分配模块编码」新增一行：`| **230** | **user_group (v2.5 新增)** | `common/errcode/user_group.py` |`
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

---

- [x] **T002**: Group/UserGroup ORM 扩展 + 新增 async DAO + Alembic 迁移 + DAO 单元测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/group.py` — Group ORM 扩展 + GroupDao 新增 async 方法
  - `src/backend/bisheng/database/models/user_group.py` — UserGroupDao 新增 async 方法
  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f003_user_group.py` — Alembic 迁移
  - `src/backend/test/test_user_group_dao.py` — DAO 单元测试
  **逻辑**:
  - **Group ORM 变更**（`database/models/group.py`）:
    - `GroupBase` 中 `group_name` 去掉 `unique=True`，改为 `group_name: str = Field(index=False, description='用户组名称')`
    - `Group` 类新增 `__tablename__ = 'group'`
    - `Group` 类新增字段:
      ```python
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
      ```
    - `Group` 类新增 `__table_args__`:
      ```python
      __table_args__ = (
          UniqueConstraint('tenant_id', 'group_name', name='uk_tenant_group_name'),
      )
      ```
    - 新增 import: `from sqlalchemy import Column, DateTime, Integer, String, delete, text, update`, `from sqlalchemy.schema import UniqueConstraint`
  - **GroupDao 新增 async 方法**（全部 `@classmethod`）:
    - `aget_by_id(group_id: int) -> Optional[Group]` — `select(Group).where(Group.id == group_id)`
    - `acreate(group: Group) -> Group` — `session.add(group)` + `await session.flush()` + `await session.refresh(group)` + `await session.commit()` + 返回 group
    - `aupdate(group: Group) -> Group` — `session.add(group)` + `await session.commit()` + `await session.refresh(group)` + 返回
    - `adelete(group_id: int) -> None` — `session.exec(delete(Group).where(Group.id == group_id))` + commit
    - `aget_all_groups(page: int = 1, limit: int = 20, keyword: str = '') -> tuple[list[Group], int]` — tenant 自动过滤，keyword 模糊匹配 group_name，返回 (list, total)
    - `acheck_name_duplicate(group_name: str, exclude_id: int = None) -> bool` — `where(Group.group_name == group_name)`，如 exclude_id 则 `where(Group.id != exclude_id)`，返回 bool
    - `aget_visible_groups(user_id: int, page: int = 1, limit: int = 20, keyword: str = '') -> tuple[list[Group], int]` — 查询 `visibility='public'` 的组 UNION 用户所属的 `visibility='private'` 组（通过 LEFT JOIN user_group），keyword 过滤，返回 (list, total)
  - **UserGroupDao 新增 async 方法**（全部 `@classmethod`）:
    - `aget_group_members(group_id: int, page: int = 1, limit: int = 20, keyword: str = '') -> tuple[list, int]` — JOIN user 表（`user.delete == 0`），`is_group_admin == 0`，keyword 模糊匹配 user_name，分页返回 [{user_id, user_name, is_group_admin, create_time}] + total
    - `aget_group_member_count(group_id: int) -> int` — `select(func.count(...)).where(group_id == X, is_group_admin == 0)`
    - `aadd_members_batch(group_id: int, user_ids: list[int]) -> None` — 批量 INSERT UserGroup(user_id=uid, group_id=gid, is_group_admin=0) + commit
    - `aremove_member(group_id: int, user_id: int) -> None` — `delete(UserGroup).where(group_id==X, user_id==Y, is_group_admin==0)` + commit
    - `acheck_members_exist(group_id: int, user_ids: list[int]) -> list[int]` — `select(UserGroup.user_id).where(group_id==X, user_id.in_(Y))` 返回已存在的 user_id 列表
    - `aget_group_admins_detail(group_id: int) -> list[dict]` — JOIN user 表，`where(is_group_admin == 1)`，返回 [{user_id, user_name}]
    - `aset_admins_batch(group_id: int, add_ids: list[int], remove_ids: list[int]) -> None` — remove: `delete(UserGroup).where(group_id==X, user_id.in_(remove_ids), is_group_admin==1)` + add: 批量 INSERT UserGroup(is_group_admin=1) + commit
    - `aget_user_visible_group_ids(user_id: int) -> list[int]` — `select(UserGroup.group_id).where(user_id==X)` 返回用户所属的所有 group_id
  - **Alembic 迁移**（`v2_5_0_f003_user_group.py`）:
    ```python
    revision = 'f003_user_group'
    down_revision = 'f002_department_tree'  # 或实际上一个 revision

    def upgrade():
        # 1. Add visibility column
        op.add_column('group', sa.Column('visibility', sa.String(16),
                       nullable=False, server_default='public',
                       comment='Visibility: public/private'))
        # 2. Drop old unique index on group_name (SQLModel auto-generated)
        try:
            op.drop_index('ix_group_group_name', table_name='group')
        except Exception:
            pass
        # 3. Add composite unique constraint
        op.create_unique_constraint('uk_tenant_group_name', 'group',
                                     ['tenant_id', 'group_name'])

    def downgrade():
        op.drop_constraint('uk_tenant_group_name', 'group', type_='unique')
        op.create_index('ix_group_group_name', 'group', ['group_name'], unique=True)
        op.drop_column('group', 'visibility')
    ```
  **测试**（`test_user_group_dao.py`，使用 `db_session` fixture + factory 函数）:
  - `test_acreate_group` — 创建组，验证返回 id + group_name + visibility='public' + tenant_id=1
  - `test_aget_by_id` — 创建后按 ID 查询，验证字段
  - `test_acheck_name_duplicate_true` — 创建同名组，返回 True
  - `test_acheck_name_duplicate_false` — 不同名组，返回 False
  - `test_acheck_name_duplicate_exclude` — 排除自身 ID，返回 False
  - `test_aget_all_groups_paged` — 创建 3 个组，page=1 limit=2 返回 2 条 + total=3
  - `test_aget_all_groups_keyword` — keyword 过滤验证
  - `test_adelete_group` — 删除后查询返回 None
  - `test_aadd_members_batch` — 批量添加 3 个成员，查询验证
  - `test_acheck_members_exist` — 部分存在返回已存在的 user_ids
  - `test_aget_group_members_paged` — 添加 3 个成员，page=1 limit=2 返回 2 条 + total=3
  - `test_aget_group_member_count` — 添加 3 个成员后 count=3
  - `test_aremove_member` — 移除后 count 减 1
  - `test_aset_admins_batch` — 设置 2 个 admin，查询验证
  - `test_aget_group_admins_detail` — 验证返回 user_id + user_name
  - `test_aget_user_visible_group_ids` — 用户加入 2 个组后返回 2 个 group_id
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-09, AC-12, AC-13, AC-14, AC-15, AC-20
  **依赖**: T001

---

### 测试基础设施

- [x] **T003**: 测试 table_definitions + factories 更新
  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — 更新 TABLE_GROUP + 新增 TABLE_USERGROUP
  - `src/backend/test/fixtures/factories.py` — 新增 `create_group()` + `create_user_group_member()`
  **逻辑**:
  - **TABLE_GROUP** 更新（加 tenant_id + visibility，改 unique 约束）:
    ```sql
    CREATE TABLE IF NOT EXISTS "group" (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name VARCHAR(255),
        remark VARCHAR(512),
        tenant_id INTEGER NOT NULL DEFAULT 1,
        visibility VARCHAR(16) NOT NULL DEFAULT 'public',
        create_user INTEGER,
        update_user INTEGER,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(tenant_id, group_name)
    )
    ```
  - **TABLE_USERGROUP** 新增:
    ```sql
    CREATE TABLE IF NOT EXISTS usergroup (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        group_id INTEGER,
        is_group_admin INTEGER DEFAULT 0,
        tenant_id INTEGER NOT NULL DEFAULT 1,
        remark VARCHAR(512),
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    ```
  - **TABLE_DEFINITIONS** 字典新增 `'usergroup': TABLE_USERGROUP`
  - **`create_group()`** 工厂函数（参照 `create_tenant()` 模式）:
    ```python
    def create_group(
        session: Session,
        group_name: str = 'Test Group',
        tenant_id: int = 1,
        visibility: str = 'public',
        create_user: int = 1,
        **kwargs,
    ) -> dict:
    ```
  - **`create_user_group_member()`** 工厂函数:
    ```python
    def create_user_group_member(
        session: Session,
        user_id: int,
        group_id: int,
        is_group_admin: int = 0,
        tenant_id: int = 1,
    ) -> dict:
    ```
  **覆盖 AC**: —（测试基础设施）
  **依赖**: T002（需要 ORM 定义对齐 DDL）

---

### 领域服务层

- [x] **T004**: GroupChangeHandler — TupleOperation DTO + 事件方法 + 日志 stub + 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/user_group/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/domain/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/domain/services/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/domain/services/group_change_handler.py` — TupleOperation + GroupChangeHandler
  - `src/backend/test/test_group_change_handler.py` — 单元测试
  **逻辑**:
  - `TupleOperation` dataclass（与 F002 DepartmentChangeHandler 相同结构，独立定义不导入）:
    ```python
    @dataclass
    class TupleOperation:
        action: Literal['write', 'delete']
        user: str        # e.g. "user:7"
        relation: str    # e.g. "member", "admin"
        object: str      # e.g. "user_group:5"
    ```
  - `GroupChangeHandler` 类，全部 `@staticmethod`:
    - `on_created(group_id: int, creator_user_id: int) -> List[TupleOperation]` — 返回 `[TupleOperation(action='write', user=f'user:{creator_user_id}', relation='admin', object=f'user_group:{group_id}')]`
    - `on_deleted(group_id: int) -> List[TupleOperation]` — 返回空列表（F004 负责级联清理）
    - `on_members_added(group_id: int, user_ids: List[int]) -> List[TupleOperation]` — 每个 uid 返回 `write(user:{uid}, member, user_group:{group_id})`
    - `on_member_removed(group_id: int, user_id: int) -> List[TupleOperation]` — 返回 `delete(user:{uid}, member, user_group:{group_id})`
    - `on_admin_set(group_id: int, user_ids: List[int]) -> List[TupleOperation]` — 每个 uid 返回 `write(user:{uid}, admin, user_group:{group_id})`
    - `on_admin_removed(group_id: int, user_ids: List[int]) -> List[TupleOperation]` — 每个 uid 返回 `delete(user:{uid}, admin, user_group:{group_id})`
    - `execute(operations: List[TupleOperation]) -> None` — **日志 stub**: `logger.info(f"GroupChangeHandler: {len(operations)} tuple operations (stub, F004 not yet)")` + 逐条 debug 日志
  **测试**（`test_group_change_handler.py`，纯 Python 无需 db_session）:
  - `test_on_created` — 验证返回 1 条 write(user:1, admin, user_group:5)
  - `test_on_deleted` — 验证返回空列表
  - `test_on_members_added` — 3 个 uid，验证返回 3 条 write(member)
  - `test_on_member_removed` — 验证返回 1 条 delete(member)
  - `test_on_admin_set` — 2 个 uid，验证返回 2 条 write(admin)
  - `test_on_admin_removed` — 2 个 uid，验证返回 2 条 delete(admin)
  - `test_execute_stub_no_error` — 调用 execute 不抛异常
  **覆盖 AC**: AC-22
  **依赖**: T001

---

- [x] **T005**: Pydantic DTO（请求/响应 Schema）
  **文件（新建）**:
  - `src/backend/bisheng/user_group/domain/schemas/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/domain/schemas/user_group_schema.py` — Pydantic DTO
  **逻辑**:
  - `UserGroupCreate(BaseModel)`: group_name(str, Field(min_length=1, max_length=128)), visibility(str='public', Field(pattern='^(public|private)$')), remark(Optional[str]=None), admin_user_ids(Optional[List[int]]=None)
  - `UserGroupUpdate(BaseModel)`: group_name(Optional[str]=None, Field(min_length=1, max_length=128)), visibility(Optional[str]=None, Field(pattern='^(public|private)$')), remark(Optional[str]=None)
  - `UserGroupMemberAdd(BaseModel)`: user_ids(List[int], Field(min_length=1))
  - `UserGroupAdminSet(BaseModel)`: user_ids(List[int])
  - `UserGroupListItem(BaseModel)`: id(int), group_name(str), visibility(str), remark(Optional[str]), member_count(int=0), create_user(Optional[int]), create_time(Optional[datetime]), update_time(Optional[datetime]), group_admins(List[dict]=[])
  - `UserGroupMemberInfo(BaseModel)`: user_id(int), user_name(str), is_group_admin(bool), create_time(Optional[datetime])
  **覆盖 AC**: —（DTO 定义）
  **依赖**: T001

---

- [x] **T006**: UserGroupService + Service 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/user_group/domain/services/user_group_service.py` — 核心业务逻辑
  - `src/backend/test/test_user_group_service.py` — Service 单元测试
  **逻辑**:
  - **辅助函数**（模块级）:
    - `_is_admin(login_user) -> bool` — 检查 `1 in login_user.user_role`（AdminRole=1），与 F002 一致
    - `_check_permission(login_user)` — `if not _is_admin(login_user): raise UserGroupPermissionDeniedError()`
  - **UserGroupService 类**（全部 `@classmethod`，使用 `async with get_async_db_session() as session`）:
    - `acreate_group(data: UserGroupCreate, login_user) -> dict`:
      1. `_check_permission(login_user)`
      2. `if await GroupDao.acheck_name_duplicate(data.group_name): raise UserGroupNameDuplicateError()`
      3. `group = Group(group_name=data.group_name, visibility=data.visibility, remark=data.remark, create_user=login_user.user_id, update_user=login_user.user_id)`
      4. `group = await GroupDao.acreate(group)`
      5. 如 data.admin_user_ids 非空：`await UserGroupDao.aset_admins_batch(group.id, add_ids=data.admin_user_ids, remove_ids=[])`
      6. `ops = GroupChangeHandler.on_created(group.id, login_user.user_id)` + `GroupChangeHandler.execute(ops)`
      7. 如 data.admin_user_ids 非空：`ops = GroupChangeHandler.on_admin_set(group.id, data.admin_user_ids)` + `execute(ops)`
      8. 附加 member_count + admins → 返回 dict
    - `alist_groups(page, limit, keyword, login_user) -> dict`:
      1. 若 `_is_admin(login_user)`: `groups, total = await GroupDao.aget_all_groups(page, limit, keyword)`
      2. 否则: `groups, total = await GroupDao.aget_visible_groups(login_user.user_id, page, limit, keyword)`
      3. 批量获取 member_count: 对每个 group `await UserGroupDao.aget_group_member_count(g.id)`
      4. 批量获取 admins: 对每个 group `await UserGroupDao.aget_group_admins_detail(g.id)`
      5. 组装返回 `{"data": [...], "total": total}`
    - `aget_group(group_id: int, login_user) -> dict`:
      1. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      2. 可见性检查：`if group.visibility == 'private' and not _is_admin(login_user)`: 检查 user_id 是否在组内（`aget_user_visible_group_ids`），不在则 raise UserGroupPermissionDeniedError
      3. 附加 member_count + admins → 返回 dict
    - `aupdate_group(group_id: int, data: UserGroupUpdate, login_user) -> dict`:
      1. `_check_permission(login_user)`
      2. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      3. 如 data.group_name 非 None 且与当前不同：检查重复 `acheck_name_duplicate(data.group_name, exclude_id=group_id)` → raise 23001
      4. 更新非 None 字段: group_name, visibility, remark, update_user=login_user.user_id
      5. `await GroupDao.aupdate(group)` → 返回 dict
    - `adelete_group(group_id: int, login_user)`:
      1. `_check_permission(login_user)`
      2. `from bisheng.database.models.group import DefaultGroup`; `if group_id == DefaultGroup: raise UserGroupDefaultProtectedError()`
      3. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      4. `count = await UserGroupDao.aget_group_member_count(group_id)`; `if count > 0: raise UserGroupHasMembersError()`
      5. `await GroupDao.adelete(group_id)`
      6. `ops = GroupChangeHandler.on_deleted(group_id)` + `execute(ops)`
    - `aget_members(group_id, page, limit, keyword, login_user) -> dict`:
      1. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      2. 可见性检查（同 aget_group）
      3. `members, total = await UserGroupDao.aget_group_members(group_id, page, limit, keyword)`
      4. 返回 `{"data": members, "total": total}`
    - `aadd_members(group_id: int, user_ids: list[int], login_user)`:
      1. `_check_permission(login_user)`
      2. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      3. `existing = await UserGroupDao.acheck_members_exist(group_id, user_ids)`; `if existing: raise UserGroupMemberExistsError()`
      4. `await UserGroupDao.aadd_members_batch(group_id, user_ids)`
      5. `ops = GroupChangeHandler.on_members_added(group_id, user_ids)` + `execute(ops)`
    - `aremove_member(group_id: int, user_id: int, login_user)`:
      1. `_check_permission(login_user)`
      2. `existing = await UserGroupDao.acheck_members_exist(group_id, [user_id])`; `if not existing: raise UserGroupMemberNotFoundError()`
      3. `await UserGroupDao.aremove_member(group_id, user_id)`
      4. `ops = GroupChangeHandler.on_member_removed(group_id, user_id)` + `execute(ops)`
    - `aset_admins(group_id: int, user_ids: list[int], login_user) -> list[dict]`:
      1. `_check_permission(login_user)`
      2. `group = await GroupDao.aget_by_id(group_id)`，不存在 raise UserGroupNotFoundError
      3. `current_admins = await UserGroupDao.aget_group_admins_detail(group_id)` → 提取 current_ids
      4. `to_add = set(user_ids) - set(current_ids)`, `to_remove = set(current_ids) - set(user_ids)`
      5. `await UserGroupDao.aset_admins_batch(group_id, list(to_add), list(to_remove))`
      6. 如 to_add: `ops = GroupChangeHandler.on_admin_set(group_id, list(to_add))` + `execute(ops)`
      7. 如 to_remove: `ops = GroupChangeHandler.on_admin_removed(group_id, list(to_remove))` + `execute(ops)`
      8. 返回新 admin 列表
    - `acreate_default_group(tenant_id: int, creator_user_id: int) -> Group`:
      1. `from bisheng.core.context.tenant import bypass_tenant_filter`
      2. `with bypass_tenant_filter():`
      3. INSERT Group(group_name='Default user group', visibility='public', tenant_id=tenant_id, create_user=creator_user_id)
      4. 返回 group（供 init_data / F010 调用）
  **测试**（`test_user_group_service.py`，使用 `db_session` fixture + factory）:
  - `test_create_group_success` — 创建组，验证返回字段含 member_count + admins
  - `test_create_group_name_duplicate` — 同名 raise 23001
  - `test_create_group_with_admins` — 创建时指定 admin_user_ids，验证 admins 设置
  - `test_list_groups_admin` — admin 看到全部组
  - `test_list_groups_non_admin` — 非 admin 只看到 public + 自己所属的 private 组
  - `test_get_group_success` — 查询公开组详情
  - `test_get_group_not_found` — raise 23000
  - `test_get_group_private_denied` — 非成员查 private 组 raise 23006
  - `test_get_group_private_member_ok` — 成员查 private 组成功
  - `test_update_group_name` — 修改名称成功
  - `test_update_group_name_duplicate` — raise 23001
  - `test_delete_group_success` — 空组删除成功
  - `test_delete_group_default_protected` — 删默认组 raise 23002
  - `test_delete_group_has_members` — 有成员 raise 23003
  - `test_add_members_success` — 批量添加成员
  - `test_add_members_duplicate` — raise 23004
  - `test_remove_member_success` — 移除成员
  - `test_remove_member_not_found` — raise 23005
  - `test_set_admins_replace` — 全量替换 admins，验证 diff 逻辑
  - `test_permission_denied` — 非 admin 调用 raise 23006
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-22
  **依赖**: T002, T004, T005

---

### API 层

- [x] **T007**: API 端点 + 路由注册 + init_data
  **文件（新建）**:
  - `src/backend/bisheng/user_group/api/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/api/router.py` — 路由聚合
  - `src/backend/bisheng/user_group/api/endpoints/__init__.py` — 空 init
  - `src/backend/bisheng/user_group/api/endpoints/user_group.py` — CRUD 5 端点
  - `src/backend/bisheng/user_group/api/endpoints/user_group_member.py` — 成员 4 端点
  **文件（修改）**:
  - `src/backend/bisheng/api/router.py` — 注册 user_group_router
  - `src/backend/bisheng/common/init_data.py` — 新增 `_init_default_user_group(session)`
  **逻辑**:
  - **router.py**:
    ```python
    from bisheng.user_group.api.endpoints.user_group import router as user_group_crud_router
    from bisheng.user_group.api.endpoints.user_group_member import router as user_group_member_router

    router = APIRouter(prefix='/user-groups', tags=['UserGroup'])
    router.include_router(user_group_crud_router)
    router.include_router(user_group_member_router)
    ```
  - **user_group.py** 端点（5 个）:
    - `POST /` — `create_group(data: UserGroupCreate, login_user=Depends(UserPayload.get_login_user))` → `resp_200(await UserGroupService.acreate_group(data, login_user))`
    - `GET /` — `list_groups(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), keyword: str = Query(''), login_user=Depends(...))` → `resp_200(...)`
    - `GET /{group_id}` — `get_group(group_id: int, login_user=Depends(...))` → `resp_200(...)`
    - `PUT /{group_id}` — `update_group(group_id: int, data: UserGroupUpdate, login_user=Depends(...))` → `resp_200(...)`
    - `DELETE /{group_id}` — `delete_group(group_id: int, login_user=Depends(...))` → `resp_200(...)`
  - **user_group_member.py** 端点（4 个）:
    - `GET /{group_id}/members` — `get_members(group_id: int, page=Query(1), limit=Query(20), keyword=Query(''), login_user=Depends(...))` → `resp_200(...)`
    - `POST /{group_id}/members` — `add_members(group_id: int, data: UserGroupMemberAdd, login_user=Depends(...))` → `resp_200(...)`
    - `DELETE /{group_id}/members/{user_id}` — `remove_member(group_id: int, user_id: int, login_user=Depends(...))` → `resp_200(...)`
    - `PUT /{group_id}/admins` — `set_admins(group_id: int, data: UserGroupAdminSet, login_user=Depends(...))` → `resp_200(...)`
  - 所有端点用 `try/except BaseErrorCode as e: return e.return_resp()` 捕获业务异常
  - **api/router.py 注册**:
    ```python
    from bisheng.user_group.api.router import router as user_group_router
    router.include_router(user_group_router)
    ```
  - **init_data.py 新增** `_init_default_user_group(session)`:
    1. `from bisheng.core.context.tenant import bypass_tenant_filter`
    2. `from bisheng.database.models.group import Group, DefaultGroup`
    3. `with bypass_tenant_filter():`
    4. 查询默认组：`group = (await session.exec(select(Group).where(Group.id == DefaultGroup))).first()`
    5. 如果不存在：return（首次安装前默认组由现有 init 逻辑创建）
    6. 如果存在但 visibility 为 None 或空：`group.visibility = 'public'`; `await session.commit()`
    7. `logger.info('Default user group visibility ensured')`
  - 在 `init_default_data()` 中，现有默认组/角色初始化之后调用 `await _init_default_user_group(session)`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-23
  **依赖**: T006

---

### API 测试

- [x] **T008**: API 集成测试
  **文件（新建）**:
  - `src/backend/test/test_user_group_api.py` — API 集成测试
  **逻辑**:
  使用 TestClient + conftest 的 mock login_user fixture，测试所有 9 个端点。
  **测试用例**:
  - `test_create_group_success` — POST /user-groups，验证 200 + data.id/group_name/visibility → AC-01
  - `test_create_group_duplicate_name` — 23001 → AC-02
  - `test_list_groups` — GET /user-groups，验证分页 + member_count + admins → AC-04
  - `test_get_group` — GET /user-groups/{id}，验证详情 → AC-05
  - `test_get_group_not_found` — 23000 → AC-06
  - `test_update_group` — PUT 修改 name → AC-07
  - `test_update_group_duplicate_name` — 23001 → AC-08
  - `test_delete_group` — DELETE 空组 → AC-09
  - `test_delete_group_default` — 23002 → AC-10
  - `test_delete_group_has_members` — 23003 → AC-11
  - `test_add_members` — POST members → AC-12
  - `test_add_members_duplicate` — 23004 → AC-13
  - `test_get_members` — GET members 分页 → AC-14
  - `test_remove_member` — DELETE member → AC-15
  - `test_remove_member_not_found` — 23005 → AC-16
  - `test_permission_denied` — 非 admin 调用 → 23006 → AC-17
  - `test_set_admins` — PUT admins 全量替换 → AC-20
  **覆盖 AC**: AC-01, AC-02, AC-04~AC-17, AC-20
  **依赖**: T007

---

## AC 覆盖矩阵

| AC | T001 | T002 | T003 | T004 | T005 | T006 | T007 | T008 |
|----|------|------|------|------|------|------|------|------|
| AC-01 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-02 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-03 | — | — | — | — | — | ✓ | — | — |
| AC-04 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-05 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-06 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-07 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-08 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-09 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-10 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-11 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-12 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-13 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-14 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-15 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-16 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-17 | — | — | — | — | — | ✓ | ✓ | ✓ |
| AC-18 | — | — | — | — | — | ✓ | — | — |
| AC-19 | — | — | — | — | — | ✓ | — | — |
| AC-20 | — | DAO | — | — | — | ✓ | ✓ | ✓ |
| AC-21 | — | — | — | — | — | — | ✓ | — |
| AC-22 | — | — | — | ✓ | — | ✓ | — | — |
| AC-23 | — | — | — | — | — | — | ✓ | — |
