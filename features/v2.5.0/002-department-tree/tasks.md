# Tasks: 部门树

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-12 审查通过（1 low 项已确认跳过） |
| tasks.md | ✅ 已拆解 | 2026-04-12 审查通过（Round 2），7 个任务 |
| 实现 | ✅ 已完成 | 7 / 7 完成，64 tests passed |

---

## 开发模式

**后端 Test-First（务实版）**：
- 理想流程：先写测试（红），再写实现（绿）
- F000 已搭建 pytest 基础设施（conftest.py、SQLite fixture、factories）
- **务实适配**：ORM + DAO 层和 Service 层的实现与测试合并在同一任务中（先写 ORM/DAO 骨架，随即在同任务内编写测试验证）。这与 F001 的 T002（ORM+DAO+test 合并）模式一致
- API 层可实现后补集成测试

**前端**：N/A — F002 不涉及前端

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## 依赖图

```
T001 (ORM + DAO + 错误码 + DAO 测试)
  │
  ├─→ T002 (测试基础设施更新)
  │
  ├─→ T003 (DepartmentChangeHandler DTO + stub)
  │    │
  │    └─→ T004 (DepartmentService + Service 测试)
  │         │
  │         └─→ T005 (API Schema + 端点 + 路由注册)
  │              │
  │              └─→ T006 (API 集成测试)
  │
  └─→ T007 (init_data 默认根部门 + 测试)
```

---

## Tasks

### 数据层

- [x] **T001**: Department/UserDepartment ORM + DAO + 错误码 + DAO 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/database/models/department.py` — Department + UserDepartment SQLModel 表定义 + DepartmentDao + UserDepartmentDao
  - `src/backend/bisheng/common/errcode/department.py` — 210xx 错误码
  - `src/backend/test/test_department_dao.py` — DAO 单元测试
  **逻辑**:
  - **`Department` 表**：id(INT PK AUTO), dept_id(VARCHAR 64 UNIQUE, 业务键如"BS@a3f7e"), name(VARCHAR 128 NOT NULL), parent_id(INT nullable, NULL=根部门), tenant_id(INT NOT NULL DEFAULT 1, INDEX), path(VARCHAR 512 NOT NULL, INDEX, 物化路径如"/1/2/3/"), sort_order(INT DEFAULT 0), source(VARCHAR 32 DEFAULT 'local'), external_id(VARCHAR 128 nullable), status(VARCHAR 16 DEFAULT 'active', INDEX), default_role_ids(JSON nullable), create_user(INT nullable), create_time(DATETIME server_default CURRENT_TIMESTAMP), update_time(DATETIME server_default CURRENT_TIMESTAMP ON UPDATE)
  - `__table_args__` 含 `UniqueConstraint('source', 'external_id', name='uk_source_external_id')`
  - **`UserDepartment` 表**：id(BIGINT PK AUTO), user_id(INT NOT NULL, INDEX), department_id(INT NOT NULL, INDEX), is_primary(SMALLINT DEFAULT 1, 1=主部门 0=挂靠), source(VARCHAR 32 DEFAULT 'local'), create_time(DATETIME)。`UniqueConstraint('user_id', 'department_id', name='uk_user_dept')`
  - 两个表均继承 `SQLModelSerializable`，列定义用 `sa_column=Column(...)` 模式（参照 `database/models/tenant.py`）
  - **`DepartmentDao`** classmethods（sync `get_xxx` + async `aget_xxx`）:
    - `get_by_id(id)` / `aget_by_id(id)` — `select(Department).where(Department.id == id)`
    - `get_by_dept_id(dept_id)` / `aget_by_dept_id(dept_id)` — `where(Department.dept_id == dept_id)`
    - `create(dept)` / `acreate(dept)` — `session.add(dept)` + `session.flush()` + `session.refresh(dept)` 获取 auto id
    - `update(dept)` / `aupdate(dept)` — `session.add(dept)` + `session.commit()` + `session.refresh(dept)`
    - `get_children(parent_id)` / `aget_children(parent_id)` — `where(parent_id==X, status=='active')` 返回列表
    - `get_subtree(path_prefix)` / `aget_subtree(path_prefix)` — `where(Department.path.like(f'{path_prefix}%'), status=='active')` 返回列表
    - `get_subtree_ids(path_prefix)` / `aget_subtree_ids(path_prefix)` — 同上但 `select(Department.id)`
    - `get_all_active()` / `aget_all_active()` — `where(status=='active')` 返回当前租户全部活跃部门
    - `update_paths_batch(old_prefix, new_prefix)` / `aupdate_paths_batch(...)` — `update(Department).where(Department.path.like(f'{old_prefix}%')).values(path=func.replace(Department.path, old_prefix, new_prefix))`
    - `get_root_by_tenant(tenant_id)` / `aget_root_by_tenant(tenant_id)` — `where(parent_id==None)` 用 `bypass_tenant_filter()` 按指定 tenant 查询
    - `check_name_duplicate(parent_id, name, exclude_id=None)` / `acheck_name_duplicate(...)` — `where(parent_id==X, name==Y, id!=exclude_id, status=='active')` 返回 bool
  - **`UserDepartmentDao`** classmethods:
    - `add_member(user_id, dept_id, is_primary, source)` / `aadd_member(...)` — INSERT
    - `batch_add_members(entries: list[dict])` / `abatch_add_members(...)` — 批量 INSERT
    - `remove_member(user_id, dept_id)` / `aremove_member(...)` — DELETE
    - `get_members(dept_id, page, limit, keyword)` / `aget_members(...)` — JOIN user 表分页查询，`WHERE user.delete==0`，keyword 模糊匹配 user_name
    - `get_member_count(dept_id)` / `aget_member_count(dept_id)` — `select(func.count(...))`
    - `get_user_departments(user_id)` / `aget_user_departments(user_id)` — 返回用户所属部门列表
    - `get_user_primary_department(user_id)` / `aget_user_primary_department(...)` — `where(is_primary==1)`
    - `check_member_exists(user_id, dept_id)` / `acheck_member_exists(...)` — 返回 bool
  - **错误码**（继承 `BaseErrorCode`，参照 `common/errcode/tenant.py`）:
    - `DepartmentNotFoundError(Code=21000, Msg='Department not found')`
    - `DepartmentNameDuplicateError(Code=21001, Msg='Department name already exists at this level')`
    - `DepartmentHasChildrenError(Code=21002, Msg='Cannot delete department with children')`
    - `DepartmentHasMembersError(Code=21003, Msg='Cannot delete department with members')`
    - `DepartmentCircularMoveError(Code=21004, Msg='Cannot move department to its own subtree')`
    - `DepartmentSourceReadonlyError(Code=21005, Msg='Third-party synced department is read-only')`
    - `DepartmentRootExistsError(Code=21006, Msg='Root department already exists for this tenant')`
    - `DepartmentMemberExistsError(Code=21007, Msg='User is already a member of this department')`
    - `DepartmentMemberNotFoundError(Code=21008, Msg='User is not a member of this department')`
    - `DepartmentPermissionDeniedError(Code=21009, Msg='No permission for this department operation')`
  **测试**（`test_department_dao.py`，使用 `db_session` fixture + factory 函数）:
  - `test_create_department` — 使用 factory 创建部门，验证返回 dict 含所有字段
  - `test_dept_id_unique` — 插入相同 dept_id 抛 IntegrityError
  - `test_get_children` — 创建父+2子部门，`get_children(parent_id)` 返回 2 条
  - `test_get_subtree` — 创建 3 层树 A→B→C，`get_subtree('/A/')` 返回 A+B+C
  - `test_get_subtree_ids` — 同上但只返回 ID 列表
  - `test_update_paths_batch` — 创建子树，执行路径替换，验证所有后代 path 更新
  - `test_check_name_duplicate_true` — 同级同名存在时返回 True
  - `test_check_name_duplicate_false` — 不同级或不同名返回 False
  - `test_check_name_duplicate_exclude` — 更新时排除自身 ID
  - `test_add_member` — 添加成员，验证 user_department 记录
  - `test_add_member_duplicate` — 重复添加抛 IntegrityError
  - `test_remove_member` — 移除成员后查询不存在
  - `test_get_members_paged` — 创建 3 个成员，page=1 limit=2 返回 2 条 + total=3
  - `test_get_member_count` — 添加 3 个成员后 count=3
  - `test_get_user_departments` — 1 用户 2 部门，返回 2 条
  - `test_check_member_exists` — 存在返回 True，不存在返回 False
  **覆盖 AC**: AC-01, AC-02, AC-12, AC-13, AC-14, AC-15
  **依赖**: 无

---

### 测试基础设施

- [x] **T002**: 测试 table_definitions + factories 更新
  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — 更新 TABLE_DEPARTMENT 和 TABLE_USER_DEPARTMENT 的 DDL
  - `src/backend/test/fixtures/factories.py` — 新增 `create_department()` 和 `create_user_department()` 工厂函数
  **逻辑**:
  - **TABLE_DEPARTMENT** 更新（当前缺少 dept_id/default_role_ids/create_user，多了 level/admin_user_id）:
    ```sql
    CREATE TABLE IF NOT EXISTS department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id VARCHAR(64) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        parent_id INTEGER,
        tenant_id INTEGER NOT NULL DEFAULT 1,
        path VARCHAR(512) NOT NULL DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        source VARCHAR(32) DEFAULT 'local',
        external_id VARCHAR(128),
        status VARCHAR(16) DEFAULT 'active',
        default_role_ids JSON,
        create_user INTEGER,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(source, external_id)
    )
    ```
  - **TABLE_USER_DEPARTMENT** 更新（当前缺少 source）:
    ```sql
    CREATE TABLE IF NOT EXISTS user_department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        department_id INTEGER NOT NULL,
        is_primary INTEGER DEFAULT 1,
        source VARCHAR(32) DEFAULT 'local',
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(user_id, department_id)
    )
    ```
  - **`create_department()`** 工厂函数（参照 `create_tenant()` 模式，使用 raw SQL + `session.execute(text(...))`）:
    ```python
    def create_department(
        session: Session,
        dept_id: str = 'BS@test1',
        name: str = 'Test Dept',
        tenant_id: int = 1,
        parent_id: int = None,
        path: str = '',
        **kwargs,
    ) -> dict:
    ```
  - **`create_user_department()`** 工厂函数:
    ```python
    def create_user_department(
        session: Session,
        user_id: int,
        department_id: int,
        is_primary: int = 1,
    ) -> dict:
    ```
  **覆盖 AC**: —（测试基础设施）
  **依赖**: T001（需要 ORM 定义对齐 DDL）

---

### 领域服务层

- [x] **T003**: DepartmentChangeHandler — TupleOperation DTO + 事件方法 + 日志 stub
  **文件（新建）**:
  - `src/backend/bisheng/department/__init__.py` — 空 init
  - `src/backend/bisheng/department/domain/__init__.py` — 空 init
  - `src/backend/bisheng/department/domain/services/__init__.py` — 空 init
  - `src/backend/bisheng/department/domain/services/department_change_handler.py` — TupleOperation + DepartmentChangeHandler
  **逻辑**:
  - `TupleOperation` dataclass:
    ```python
    @dataclass
    class TupleOperation:
        action: Literal['write', 'delete']
        user: str        # e.g. "user:7" or "department:5#member"
        relation: str    # e.g. "member", "admin", "parent"
        object: str      # e.g. "department:5"
    ```
  - `DepartmentChangeHandler` 类，全部 `@staticmethod`:
    - `on_created(dept_id: int, parent_id: int) -> List[TupleOperation]` — 返回 `[TupleOperation(action='write', user=f'department:{parent_id}', relation='parent', object=f'department:{dept_id}')]`
    - `on_moved(dept_id: int, old_parent_id: int, new_parent_id: int) -> List[TupleOperation]` — 返回 delete 旧 parent + write 新 parent 两条
    - `on_archived(dept_id: int, parent_id: int) -> List[TupleOperation]` — 返回 delete parent 关系
    - `on_members_added(dept_id: int, user_ids: List[int]) -> List[TupleOperation]` — 每个 uid 返回 `write(user:{uid}, member, department:{dept_id})`
    - `on_member_removed(dept_id: int, user_id: int) -> List[TupleOperation]` — 返回 `delete(user:{uid}, member, department:{dept_id})`
    - `execute(operations: List[TupleOperation]) -> None` — **日志 stub**: `logger.info(f"DepartmentChangeHandler: {len(operations)} tuple operations (stub, F004 not yet)")` + 逐条 debug 日志
  **覆盖 AC**: AC-20
  **依赖**: T001

- [x] **T004**: DepartmentService + Schema + Service 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/department/domain/schemas/__init__.py` — 空 init
  - `src/backend/bisheng/department/domain/schemas/department_schema.py` — Pydantic 请求/响应 DTO
  - `src/backend/bisheng/department/domain/services/department_service.py` — DepartmentService 类
  - `src/backend/test/test_department_service.py` — Service 单元测试
  **逻辑**:
  - **Pydantic Schema**（`department_schema.py`）:
    - `DepartmentCreate(BaseModel)`: name(str, 2-50 chars), parent_id(int), sort_order(int=0), default_role_ids(Optional[List[int]])
    - `DepartmentUpdate(BaseModel)`: name(Optional[str]), sort_order(Optional[int]), default_role_ids(Optional[List[int]])
    - `DepartmentMoveRequest(BaseModel)`: new_parent_id(int)
    - `DepartmentMemberAdd(BaseModel)`: user_ids(List[int], min 1), is_primary(int=0)
    - `DepartmentTreeNode(BaseModel)`: id, dept_id, name, parent_id, path, sort_order, source, status, member_count(int=0), children(List['DepartmentTreeNode']=[])
    - `DepartmentMemberInfo(BaseModel)`: user_id, user_name, department_id, is_primary, source, create_time
  - **DepartmentService 类**（全部 `@classmethod`，使用 `async with get_async_db_session() as session`）:
    - `generate_dept_id(prefix="BS") -> str` — `f"{prefix}@{secrets.token_hex(3)}"` 生成 6 位 hex，冲突重试 3 次
    - `acreate_department(data: DepartmentCreate, login_user) -> Department`:
      1. 权限检查：`if not _is_admin(login_user): raise DepartmentPermissionDeniedError`
      2. 校验父部门：`parent = await DepartmentDao.aget_by_id(data.parent_id)`，不存在 raise DepartmentNotFoundError
      3. 校验父部门 active：`parent.status != 'active'` raise DepartmentNotFoundError
      4. 校验名称：`await DepartmentDao.acheck_name_duplicate(data.parent_id, data.name)` → raise DepartmentNameDuplicateError
      5. 生成 dept_id（重试 3 次）
      6. INSERT Department（dept_id, name, parent_id, sort_order, default_role_ids, source='local', status='active', create_user=login_user.user_id）
      7. UPDATE path = `f"{parent.path}{dept.id}/"`
      8. 调用 `DepartmentChangeHandler.on_created(dept.id, parent.id)` → `execute(ops)`
      9. 返回 dept
    - `aget_tree(login_user) -> List[DepartmentTreeNode]`:
      1. 权限检查
      2. `depts = await DepartmentDao.aget_all_active()`
      3. 批量查询 member_count（一次 GROUP BY department_id）
      4. 内存构建树：按 parent_id 分组 → 递归组装 children → sort_order 排序
      5. 返回嵌套结构
    - `aget_department(dept_id: str, login_user) -> Department`:
      1. 权限检查
      2. `dept = await DepartmentDao.aget_by_dept_id(dept_id)`，不存在 raise DepartmentNotFoundError
      3. 附加 member_count
      4. 返回
    - `aupdate_department(dept_id: str, data: DepartmentUpdate, login_user) -> Department`:
      1. 权限检查
      2. 查询部门，不存在 raise DepartmentNotFoundError
      3. `dept.source != 'local'` 且 data.name 非 None → raise DepartmentSourceReadonlyError
      4. data.name 非 None → `acheck_name_duplicate(dept.parent_id, data.name, exclude_id=dept.id)` → raise DepartmentNameDuplicateError
      5. 更新字段（仅 non-None 字段）
      6. 返回
    - `adelete_department(dept_id: str, login_user)`:
      1. 权限检查
      2. 查询部门
      3. `await DepartmentDao.aget_children(dept.id)` 非空 → raise DepartmentHasChildrenError
      4. `await UserDepartmentDao.aget_member_count(dept.id)` > 0 → raise DepartmentHasMembersError
      5. UPDATE status='archived'
      6. `DepartmentChangeHandler.on_archived(dept.id, dept.parent_id)` → `execute(ops)`
    - `amove_department(dept_id: str, data: DepartmentMoveRequest, login_user)`:
      1. 权限检查
      2. 查询部门 + 新父部门（不存在 raise DepartmentNotFoundError）
      3. 循环检测：`new_parent.path.startswith(dept.path)` → raise DepartmentCircularMoveError
      4. 也检查 `data.new_parent_id == dept.id` → raise DepartmentCircularMoveError
      5. old_path = dept.path
      6. new_path = `f"{new_parent.path}{dept.id}/"`
      7. `await DepartmentDao.aupdate_paths_batch(old_path, new_path)` — 批量更新子树
      8. UPDATE dept.parent_id, dept.path
      9. `DepartmentChangeHandler.on_moved(dept.id, dept.parent_id_old, data.new_parent_id)` → `execute(ops)`
    - `acreate_root_department(tenant_id: int, name: str = 'Default Organization') -> Department`:
      1. `with bypass_tenant_filter():` 上下文
      2. 检查租户是否存在根部门：`await DepartmentDao.aget_root_by_tenant(tenant_id)` → 存在则 raise DepartmentRootExistsError
      3. INSERT Department（parent_id=None, tenant_id=tenant_id, source='local', status='active'）
      4. UPDATE path = `f"/{dept.id}/"`
      5. UPDATE Tenant.root_dept_id = dept.id
      6. 返回 dept
    - `aadd_members(dept_id: str, data: DepartmentMemberAdd, login_user)`:
      1. 权限检查
      2. 查询部门
      3. 对每个 user_id: `await UserDepartmentDao.acheck_member_exists(uid, dept.id)` → 存在 raise DepartmentMemberExistsError
      4. `await UserDepartmentDao.abatch_add_members(entries)` — entries = [{user_id, department_id, is_primary, source='local'}]
      5. `DepartmentChangeHandler.on_members_added(dept.id, data.user_ids)` → `execute(ops)`
    - `aremove_member(dept_id: str, user_id: int, login_user)`:
      1. 权限检查
      2. `await UserDepartmentDao.acheck_member_exists(user_id, dept_id_int)` → 不存在 raise DepartmentMemberNotFoundError
      3. `await UserDepartmentDao.aremove_member(user_id, dept_id_int)`
      4. `DepartmentChangeHandler.on_member_removed(dept_id_int, user_id)` → `execute(ops)`
    - `aget_members(dept_id: str, page: int, limit: int, keyword: str, login_user) -> PageData`:
      1. 权限检查
      2. `await UserDepartmentDao.aget_members(dept.id, page, limit, keyword)` — 返回 list + total
      3. 包装为 `PageData`
  - **辅助函数** `_is_admin(login_user) -> bool`: 检查 `login_user.role == 'admin'` 或 user_role 中包含 AdminRole(1)。F004 后替换为 PermissionService.check()
  **测试**（`test_department_service.py`，使用 `db_session` fixture + factory 函数）:
  - `test_create_department_success` — 创建部门，验证返回 dept_id/path 格式
  - `test_create_department_name_duplicate` — 同级同名 raise DepartmentNameDuplicateError
  - `test_create_department_parent_not_found` — parent_id 不存在 raise DepartmentNotFoundError
  - `test_get_tree` — 创建 3 层树，验证嵌套结构 + sort_order 排序 + member_count
  - `test_get_department` — 查询单个部门详情
  - `test_update_department_name` — 修改名称成功
  - `test_update_department_source_readonly` — source='feishu' 修改 name raise DepartmentSourceReadonlyError
  - `test_delete_department_success` — 无子无成员，status 变 archived
  - `test_delete_department_has_children` — raise DepartmentHasChildrenError
  - `test_delete_department_has_members` — raise DepartmentHasMembersError
  - `test_move_department_success` — 移动后 path 正确更新（父+子孙全部）
  - `test_move_department_circular` — 移到自己子树 raise DepartmentCircularMoveError
  - `test_add_members_batch` — 批量添加 3 个用户
  - `test_add_members_duplicate` — 已存在 raise DepartmentMemberExistsError
  - `test_get_members_paged` — 分页查询验证
  - `test_remove_member` — 移除成员
  - `test_remove_member_not_found` — 不存在 raise DepartmentMemberNotFoundError
  - `test_permission_denied` — 非 admin 调用 raise DepartmentPermissionDeniedError
  - `test_create_root_department` — 创建根部门，验证 parent_id=None + path=`/{id}/` + tenant.root_dept_id 回写
  - `test_create_root_department_exists` — 重复创建 raise DepartmentRootExistsError
  - `test_change_handler_on_created` — 验证 on_created 返回正确 TupleOperation
  - `test_change_handler_on_moved` — 验证 on_moved 返回 delete+write 两条
  - `test_change_handler_on_members_added` — 验证每个 uid 一条 write
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18, AC-19, AC-20
  **依赖**: T001, T002, T003

---

### API 层

- [x] **T005**: API Schema + 端点 + 路由注册
  **文件（新建）**:
  - `src/backend/bisheng/department/api/__init__.py` — 空 init
  - `src/backend/bisheng/department/api/router.py` — 路由聚合
  - `src/backend/bisheng/department/api/endpoints/__init__.py` — 空 init
  - `src/backend/bisheng/department/api/endpoints/department.py` — 部门 CRUD + tree + move 端点
  - `src/backend/bisheng/department/api/endpoints/department_member.py` — 成员管理端点
  **文件（修改）**:
  - `src/backend/bisheng/api/router.py` — 导入并注册 department_router
  **逻辑**:
  - **router.py**:
    ```python
    from bisheng.department.api.endpoints.department import router as department_router
    from bisheng.department.api.endpoints.department_member import router as department_member_router
    
    router = APIRouter(prefix='/departments', tags=['Department'])
    router.include_router(department_router)
    router.include_router(department_member_router)
    ```
  - **department.py** 端点（6 个）:
    - `POST /` — `create_department(data: DepartmentCreate, login_user=Depends(UserPayload.get_login_user))` → `resp_200(await DepartmentService.acreate_department(data, login_user))`
    - `GET /tree` — `get_tree(login_user=Depends(...))` → `resp_200(await DepartmentService.aget_tree(login_user))`
    - `GET /{dept_id}` — `get_department(dept_id: str, login_user=Depends(...))` → `resp_200(...)`
    - `PUT /{dept_id}` — `update_department(dept_id: str, data: DepartmentUpdate, login_user=Depends(...))` → `resp_200(...)`
    - `DELETE /{dept_id}` — `delete_department(dept_id: str, login_user=Depends(...))` → `resp_200(...)`
    - `POST /{dept_id}/move` — `move_department(dept_id: str, data: DepartmentMoveRequest, login_user=Depends(...))` → `resp_200(...)`
  - **department_member.py** 端点（3 个）:
    - `GET /{dept_id}/members` — `get_members(dept_id: str, page: int = 1, limit: int = 20, keyword: str = '', login_user=Depends(...))` → `resp_200(PageData)`
    - `POST /{dept_id}/members` — `add_members(dept_id: str, data: DepartmentMemberAdd, login_user=Depends(...))` → `resp_200(...)`
    - `DELETE /{dept_id}/members/{user_id}` — `remove_member(dept_id: str, user_id: int, login_user=Depends(...))` → `resp_200(...)`
  - 所有端点用 `try/except BaseErrorCode as e: return e.return_resp()` 捕获业务异常
  - **api/router.py 注册**（在 `src/backend/bisheng/api/router.py` 中添加）:
    ```python
    from bisheng.department.api.router import router as department_router
    router.include_router(department_router)
    ```
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16
  **依赖**: T004

---

### API 测试

- [x] **T006**: API 集成测试
  **文件（新建）**:
  - `src/backend/test/test_department_api.py` — API 集成测试
  **逻辑**:
  使用 TestClient + conftest 的 mock login_user fixture，测试所有端点。
  **测试用例**:
  - `test_create_department_success` — POST /departments，验证 200 + data 结构 → AC-01
  - `test_create_department_duplicate_name` — 21001 → AC-02
  - `test_get_tree` — GET /departments/tree，验证嵌套结构 → AC-03
  - `test_get_department` — GET /departments/{dept_id}，验证详情 → AC-04
  - `test_update_department` — PUT 修改 name → AC-05
  - `test_update_department_source_readonly` — PUT source=feishu → 21005 → AC-06
  - `test_delete_department` — DELETE 无子无成员 → AC-07
  - `test_delete_department_has_children` — 21002 → AC-08
  - `test_delete_department_has_members` — 21003 → AC-09
  - `test_move_department` — POST move → AC-10
  - `test_move_department_circular` — 21004 → AC-11
  - `test_add_members` — POST members → AC-12
  - `test_add_members_duplicate` — 21007 → AC-13
  - `test_get_members` — GET members 分页 → AC-14
  - `test_remove_member` — DELETE member → AC-15
  - `test_permission_denied` — 非 admin 调用 → 21009 → AC-16
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16
  **依赖**: T005

---

### 初始化集成

- [x] **T007**: init_data 默认根部门创建 + 测试
  **文件（修改）**:
  - `src/backend/bisheng/common/init_data.py` — 新增 `_init_default_root_department(session)` 函数
  **文件（新建）**:
  - `src/backend/test/test_init_root_department.py` — init_data 根部门创建测试
  **逻辑**:
  - 新增 async 函数 `_init_default_root_department(session)`:
    1. `from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter`
    2. `from bisheng.database.models.tenant import Tenant`
    3. `from bisheng.database.models.department import Department`
    4. `with bypass_tenant_filter():`
    5. 查询默认租户：`tenant = (await session.exec(select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID))).first()`
    6. 如果 `tenant is None` 或 `tenant.root_dept_id is not None`：return（幂等检查）
    7. 创建根部门：
       ```python
       dept = Department(
           dept_id='BS@root',
           name='Default Organization',
           parent_id=None,
           tenant_id=DEFAULT_TENANT_ID,
           path='',
           source='local',
           status='active',
       )
       session.add(dept)
       await session.flush()
       await session.refresh(dept)
       dept.path = f'/{dept.id}/'
       tenant.root_dept_id = dept.id
       await session.commit()
       ```
    8. `logger.info(f'Default root department initialized (id={dept.id})')`
  - 在 `init_default_data()` 中，`await _init_default_tenant(session)` 之后调用 `await _init_default_root_department(session)`
  **测试**（`test_init_root_department.py`）:
  - `test_init_creates_root_department` — 先创建 tenant(id=1)，调用 `_init_default_root_department`，验证 department 创建且 tenant.root_dept_id 已回写
  - `test_init_idempotent` — 连续调用两次，验证第二次不创建新部门（幂等）
  **覆盖 AC**: AC-17
  **依赖**: T001, T004

---

## AC 覆盖矩阵

| AC | T001 | T002 | T003 | T004 | T005 | T006 | T007 |
|----|------|------|------|------|------|------|------|
| AC-01 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-02 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-03 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-04 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-05 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-06 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-07 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-08 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-09 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-10 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-11 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-12 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-13 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-14 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-15 | DAO+test | — | — | ✓ | ✓ | ✓ | — |
| AC-16 | — | — | — | ✓ | ✓ | ✓ | — |
| AC-17 | — | — | — | — | — | — | ✓ |
| AC-18 | — | — | — | ✓ | — | — | — |
| AC-19 | — | — | — | ✓ | — | — | — |
| AC-20 | — | — | DTO | ✓ | — | — | — |
