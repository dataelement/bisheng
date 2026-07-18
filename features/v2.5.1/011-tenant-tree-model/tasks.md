# Tasks: F011-tenant-tree-model (Tenant 树数据模型 + 隔离策略重构)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/011-tenant-tree-model`（base=`2.5.0-PM`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-19 Round 2 Review 定稿；T01 同步修订 190→220 |
| tasks.md | ✅ 已拆解 | 2026-04-19 用户确认 11 个任务 |
| 实现 | ✅ 已完成 | 11 / 11 完成；F011 新增 69 tests passed；v2.5.0 全量回归 401 passed / 5 pre-existing failures |

---

## 开发模式

**后端 Test-Alongside（务实版）**：
- F000 已搭建 pytest 基础设施（`test/conftest.py` + SQLite `db_session` fixture + `test/fixtures/factories.py`）
- ORM + DAO 扩展 + DAO 测试合并在同一任务（参照 F002 T001 模式）
- Service / API 层测试与实现合并在 T08~T10 内
- 迁移脚本（T06）通过"手工 DDL 验证 + alembic upgrade/downgrade 往返"保证

**前端**：N/A — F011 不涉及前端（UI 归属于后续 feature，见 spec §2 AC-04c 注释）

**决策锁定**（来自 plan 阶段用户确认）：
- 错误码模块码 `220xx`（原 spec §9 190xx 与 Permission F004 冲突已弃用）
- `UserTenant.is_active TINYINT NULL`（NOT NULL 语义会阻止多条历史记录，用 NULL trick 规避）
- 不改动 `core/database/tenant_filter.py`（"IN 列表"过滤是 F013/F017 职责）
- 分支从 `2.5.0-PM` 切出，PR base=`2.5.0-PM`

---

## 依赖图

```
T01 (错误码 + spec/release-contract/CLAUDE.md 同步)
  │
  ├─→ T02 (Tenant ORM + DAO + DAO 测试)
  │    │
  │    ├─→ T03 (UserTenant ORM 扩展 is_active + DAO 测试)
  │    ├─→ T04 (Department ORM 扩展 is_tenant_root/mounted_tenant_id + DAO 测试)
  │    ├─→ T05 (AuditLog ORM 扩展 + DAO v2 + DAO 测试)
  │    └─→ T07 (TenantService Root 保护 + 废弃 CRUD 410)
  │
  ├─→ T06 (Alembic 迁移脚本 + table_definitions 同步)
  │    [依赖 T02-T05 ORM 稳定]
  │
  ├─→ T08 (TenantMountService 挂载/解绑/资源下沉 + Service 测试)
  │    [依赖 T02, T04, T05]
  │    │
  │    └─→ T09 (DepartmentDeletionHandler + 测试)
  │         │
  │         └─→ T10 (API 端点 + 路由注册 + 集成测试)
  │              [依赖 T07, T08, T09]
  │              │
  │              └─→ T11 (AC 对照 + 手工 QA 执行)
```

---

## Tasks

### 基础：错误码与文档对齐

- [x] **T01**: 错误码注册 + spec / release-contract / CLAUDE.md 同步修订
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/tenant_tree.py` — 11 个错误码类 `22001-22011`
  **文件（修改）**:
  - `features/v2.5.1/release-contract.md` — 表 3 模块编码：`190 tenant_tree F011` → `220 tenant_tree F011`；INV-T11 的 `19008` → `22008`
  - `features/v2.5.1/011-tenant-tree-model/spec.md` — §9 错误码清单全部重排；AC-03 `19001`→`22001`；AC-04d `19010`/`19011`→`22010`/`22011`；AC-11 / AC-15 / §5.5 / INV-T11 / §3 / §8 中所有 `190xx` 引用同步替换
  - `CLAUDE.md` — "错误码模块编码"清单补 `220=tenant_tree`（在 180=knowledge_space 之后）
  **逻辑**:
  ```python
  # src/backend/bisheng/common/errcode/tenant_tree.py
  from .base import BaseErrorCode

  # Tenant tree module error codes, module code: 220
  # (Previously 190 in spec §9, conflicted with permission module — reassigned on 2026-04-19)

  class TenantTreeNestingForbiddenError(BaseErrorCode):
      Code: int = 22001
      Msg: str = 'MVP locked to 2-layer tree; cannot mount a tenant under a child tenant'

  class TenantTreeMountConflictError(BaseErrorCode):
      Code: int = 22002
      Msg: str = 'Target department is already a mount point or lies under one'

  class TenantTreeRootDeptMountError(BaseErrorCode):
      Code: int = 22003
      Msg: str = 'Root department cannot be mounted as a child tenant'

  class TenantTreeInvalidParentError(BaseErrorCode):
      Code: int = 22004
      Msg: str = 'Invalid parent tenant: parent does not exist or is not root'

  class TenantTreeHasChildrenError(BaseErrorCode):
      Code: int = 22005
      Msg: str = 'Cannot physically delete a tenant that has child tenants'

  class TenantTreeMigrateConflictError(BaseErrorCode):
      Code: int = 22006
      Msg: str = 'tenant_id conflict while migrating child tenant resources'

  class TenantTreeOrphanAlreadyExistsError(BaseErrorCode):
      Code: int = 22007
      Msg: str = 'Orphaned tenant already exists for this department'

  class TenantTreeRootProtectedError(BaseErrorCode):
      Code: int = 22008
      Msg: str = 'Root tenant is system-protected; disable/archive/delete forbidden'

  class TenantTreeAuditLogWriteError(BaseErrorCode):
      Code: int = 22009
      Msg: str = 'Failed to write audit_log entry'

  class TenantTreeMigratePermissionError(BaseErrorCode):
      Code: int = 22010
      Msg: str = 'Only global super admin may call migrate-from-root'

  class TenantTreeMigrateSourceError(BaseErrorCode):
      Code: int = 22011
      Msg: str = 'migrate-from-root requires resource.tenant_id == 1 (Root)'
  ```
  **测试**: 无（纯文档 + 常量类定义；被下游 Task 引用时隐式覆盖）
  **覆盖 AC**: AC-03 / AC-04d / AC-11 / AC-15（错误码映射）
  **依赖**: 无

---

### 数据层

- [x] **T02**: Tenant ORM 扩展 + DAO 新方法 + DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/tenant.py` — 在 `Tenant` SQLModel 追加两字段；扩展 `TenantDao`
  **文件（新建）**:
  - `src/backend/test/test_tenant_tree_dao.py` — DAO 新方法测试
  **逻辑**:
  - **`Tenant` 扩展字段**（追加到 `status` 之后、`contact_name` 之前）:
    ```python
    parent_tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='NULL=Root tenant; else points to Root (id=1) — 2-layer MVP',
        ),
    )
    share_default_to_children: bool = Field(
        default=True,
        sa_column=Column(
            'share_default_to_children',
            Integer,  # MySQL TINYINT(1), SQLModel maps bool→Integer
            nullable=False, server_default=text('1'),
            comment='Whether Root-created resources default to shared_to all children',
        ),
    )
    ```
  - **`Tenant.status` 注释更新**：`Status: active/disabled/archived/orphaned`（不改 column 类型，仅注释）
  - **`TenantDao` 新增 classmethods**（sync 版可选，仅写 async 满足下游需要）:
    - `aget_children_ids_active(root_id: int) -> list[int]` — `select(Tenant.id).where(parent_tenant_id==root_id, status=='active')`；用 `bypass_tenant_filter()` 包裹（跨 tenant 查询）
    - `aget_non_active_ids() -> list[int]` — `where(status.in_(['disabled','archived','orphaned']))`；用 `bypass_tenant_filter()`
    - `aexists(tenant_id: int) -> bool` — `select(func.count()).where(Tenant.id==tenant_id)`；用 `bypass_tenant_filter()`
    - `aget_by_parent(parent_id: int) -> list[Tenant]` — 通用 parent 查询，供挂载冲突校验使用
  - **Root 保护辅助**（TenantDao 上一层）：无需改 DAO，留给 Service 层 T07
  **测试**（`test_tenant_tree_dao.py`，使用 `db_session` + factory）:
  - `test_aget_children_ids_active_returns_only_active` — 插 1 Root + 3 Child（active/disabled/archived），只返回 active 那条
  - `test_aget_children_ids_active_empty` — 无 Child 时返回空列表
  - `test_aget_non_active_ids_excludes_active` — 混合状态 5 条，仅返回 disabled/archived/orphaned 3 条
  - `test_aexists_true` — 存在返回 True
  - `test_aexists_false` — 不存在返回 False
  - `test_aget_by_parent_returns_all` — 混合状态全部返回（未过滤 status）
  - `test_parent_tenant_id_null_for_root` — 插入 Root（parent_tenant_id=NULL）并读回验证字段可空
  - `test_share_default_to_children_defaults_true` — 新建 Tenant 不传该字段，默认为 True
  **覆盖 AC**: AC-01（Root parent_tenant_id=NULL）、AC-02（Child parent_tenant_id=1）、§5.4.3 DAO 方法契约
  **依赖**: T01

---

- [x] **T03**: UserTenant ORM 扩展（is_active NULL/1）+ DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/tenant.py` — `UserTenant` 新增 `is_active` + 更换唯一约束；`UserTenantDao` 新增 `aget_active_user_tenant`
  **文件（新建）**:
  - `src/backend/test/test_user_tenant_leaf.py` — 唯一叶子 DAO 测试
  **逻辑**:
  - **`UserTenant` 扩展字段**（在 `status` 之后）:
    ```python
    is_active: Optional[int] = Field(
        default=None,
        sa_column=Column(
            'is_active',
            Integer,  # TINYINT NULL in MySQL; NULL=history, 1=current leaf
            nullable=True,
            comment='1=active leaf (unique per user); NULL=historical record',
        ),
    )
    ```
  - **`UserTenant.__table_args__` 替换**：
    ```python
    __table_args__ = (
        UniqueConstraint('user_id', 'is_active', name='uk_user_active'),
    )
    ```
    （旧 `uk_user_tenant(user_id, tenant_id)` 由迁移 T06 `DROP INDEX`；ORM 层只保留新约束）
  - **`UserTenantDao` 新增方法**:
    - `aget_active_user_tenant(user_id: int) -> Optional[UserTenant]` —
      `select(UserTenant).where(user_id==X, is_active==1)` + `bypass_tenant_filter()`；
      返回当前活跃叶子记录或 None
    - `adeactivate_user_tenant(user_id: int, tenant_id: int)` —
      `update(UserTenant).where(user_id==X, tenant_id==Y, is_active==1).values(is_active=None)`；
      供 F012 主部门变更时降级旧记录使用
    - `aactivate_user_tenant(user_id: int, tenant_id: int)` —
      先 deactivate 当前活跃记录，再 upsert 目标记录为 `is_active=1`；事务内完成
  **测试**:
  - `test_uk_user_active_enforced` — 同一 user_id 插两条 is_active=1 → 第二条抛 IntegrityError
  - `test_uk_user_active_allows_multiple_nulls` — 同一 user_id 插多条 is_active=NULL → 全部成功（验证 NULL trick 生效）
  - `test_aget_active_user_tenant_returns_active` — 有 1 active + 2 NULL 时返回 active 那条
  - `test_aget_active_user_tenant_none_when_all_history` — 全部 NULL 时返回 None
  - `test_adeactivate_sets_null` — 调用后原 active 记录 `is_active` 变 NULL
  - `test_aactivate_swaps` — 原活跃 tenant=1，调用 activate(user, tenant=2) 后 tenant=1 为 NULL、tenant=2 为 1
  **覆盖 AC**: AC-09（uk_user_active 唯一约束）、§5.2 DDL
  **依赖**: T02

---

- [x] **T04**: Department ORM 扩展（is_tenant_root / mounted_tenant_id）+ DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/department.py` — `Department` 新增两字段 + `DepartmentDao.aget_mount_point`
  **文件（修改）**:
  - `src/backend/test/test_department_dao.py` — 追加挂载点相关测试（不重写既有 F002 测试）
  **逻辑**:
  - **`Department` 扩展字段**（在 `status` 之后、`default_role_ids` 之前）:
    ```python
    is_tenant_root: int = Field(
        default=0,
        sa_column=Column(
            'is_tenant_root',
            Integer,  # TINYINT(1)
            nullable=False, server_default=text('0'),
            comment='1=Tenant mount point (department marked as child tenant root)',
        ),
    )
    mounted_tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            'mounted_tenant_id',
            Integer,
            nullable=True, index=True,
            comment='FK → tenant.id; set when is_tenant_root=1',
        ),
    )
    ```
    （不加数据库层 FK 约束，避免与 tenant 表循环依赖；通过 Service 层保证一致性）
  - **`DepartmentDao` 新增 classmethods**:
    - `aget_mount_point(dept_id: int) -> Optional[Department]` — 仅返回 `is_tenant_root=1` 的部门，否则 None
    - `aget_ancestors_with_mount(dept_id: int) -> Optional[Department]` — 沿 `path` 向上查最近的 `is_tenant_root=1` 祖先（含自身）；用 `LIKE` + `ORDER BY LENGTH(path) DESC LIMIT 1`；供 T08 嵌套校验 + F012 叶子派生使用
    - `aset_mount(dept_id: int, tenant_id: int)` — `UPDATE SET is_tenant_root=1, mounted_tenant_id=X`
    - `aunset_mount(dept_id: int)` — `UPDATE SET is_tenant_root=0, mounted_tenant_id=NULL`
  **测试**（追加到 `test_department_dao.py`）:
  - `test_is_tenant_root_default_zero` — 新建部门默认 `is_tenant_root=0, mounted_tenant_id=NULL`
  - `test_aget_mount_point_returns_only_marked` — `is_tenant_root=0` 的部门返回 None
  - `test_aget_ancestors_with_mount_finds_nearest` — 3 层树 A(mount)→B→C，`aget_ancestors_with_mount(C.id)` 返回 A
  - `test_aget_ancestors_with_mount_none` — 无挂载点祖先返回 None
  - `test_aset_unset_mount_roundtrip` — set → get→1；unset → get→None
  **覆盖 AC**: AC-02（Department `is_tenant_root=1, mounted_tenant_id` 写入）、AC-03（嵌套判定依赖 aget_ancestors_with_mount）
  **依赖**: T02

---

- [x] **T05**: AuditLog ORM 扩展 + DAO v2 + DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/audit_log.py` — `AuditLog` 追加 7 字段；`AuditLogDao` 新增 v2 方法
  **文件（新建）**:
  - `src/backend/test/test_audit_log_v2.py` — v2 方法测试
  **逻辑**:
  - **`AuditLog` 扩展字段**（在 `ip_address` 之后、`create_time` 之前）:
    ```python
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='v2.5.1: leaf tenant of the resource being acted on',
        ),
    )
    operator_tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True,
            comment='v2.5.1: leaf tenant of the operator (may differ from tenant_id for super-admin cross-child ops)',
        ),
    )
    action: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(64), nullable=True, index=True,
            comment='v2.5.1: structured action name (e.g. tenant.mount, resource.migrate_tenant); see spec §5.4.2',
        ),
    )
    target_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment='v2.5.1: tenant / department / resource / ...'),
    )
    target_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    reason: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    audit_metadata: Optional[dict] = Field(
        default=None,
        sa_column=Column(
            'metadata',  # MySQL column name stays `metadata`
            JSON, nullable=True,
            comment='v2.5.1: extended fields (e.g. old/new quota, affected resource ids, from/to scope)',
        ),
    )
    ```
    （Python 字段名 `audit_metadata` 避免与 SQLModel base 的 `metadata` 冲突；SQL 列名仍用 `metadata`）
  - **`AuditLogDao` 新增 async 方法**:
    - `ainsert_v2(tenant_id, operator_id, operator_tenant_id, action, target_type, target_id, reason=None, metadata=None) -> None` —
      构造 AuditLog 实例后插入；`operator_tenant_id` 填值规则严格遵守 spec §5.4 （普通 = leaf / 超管无 scope = 1 / 超管有 scope = scope 值 / 系统 = 1），由 caller 决定
    - `aget_by_action(action: str, tenant_id: Optional[int] = None, page=1, limit=20) -> tuple[list[AuditLog], int]` —
      按 action 过滤；`tenant_id` 传入时额外过滤（用 `bypass_tenant_filter()` 避开自动注入避免二次过滤）
    - `aget_visible_for_child_admin(tenant_id: int, page=1, limit=20) -> tuple[list[AuditLog], int]` —
      Child Admin 可见：`WHERE tenant_id = X OR operator_tenant_id = X`（spec §5.4 "可见性规则"）
  **测试**:
  - `test_ainsert_v2_writes_all_fields` — 插入后 `SELECT *` 所有字段到位
  - `test_ainsert_v2_metadata_json_roundtrip` — metadata={'old_quota': 10, 'new_quota': 20} 写入后读回值相等
  - `test_aget_by_action_filters` — 插 3 条 `tenant.mount` + 2 条 `quota.update`，`aget_by_action('tenant.mount')` 返回 3 条
  - `test_aget_visible_for_child_admin_includes_operator_match` — Child=5 本地 mount 记录 + 超管对 Child=5 的记录（tenant_id=1 但 operator_tenant_id=5）都可见
  - `test_legacy_event_type_still_works` — 旧代码路径（写 `system_id/event_type/object_type`）仍可写入，新字段为 NULL；按 `event_type` 查询不受影响
  **覆盖 AC**: AC-07（audit_log 强制记录）、AC-13（表字段齐全）、§5.4 填值规则
  **依赖**: T02

---

### 迁移脚本

- [x] **T06**: Alembic 迁移脚本 + SQLite table_definitions 同步
  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f011_tenant_tree.py`
  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — 同步 `TABLE_TENANT` / `TABLE_USER_TENANT` / `TABLE_DEPARTMENT` / `TABLE_AUDIT_LOG` 的 DDL，使 SQLite 测试环境字段对齐
  **逻辑**:
  - **迁移 revision 声明**:
    ```python
    revision: str = 'f011_tenant_tree'
    down_revision: Union[str, None] = 'f011_backfill_create_knowledge_web_menu'
    # v2.5.0 最后一个迁移（见 ls alembic/versions/）
    ```
  - **upgrade() 步骤**（全部幂等，用 `_column_exists()` / `_index_exists()` helper 包裹）:
    1. **ALTER tenant**：
       ```python
       op.add_column('tenant', sa.Column('parent_tenant_id', sa.Integer, nullable=True))
       op.create_index('idx_tenant_parent', 'tenant', ['parent_tenant_id'])
       op.add_column('tenant', sa.Column(
           'share_default_to_children', sa.Integer,
           nullable=False, server_default='1',
       ))
       # status 注释扩展 (no schema change; enum enforced at application layer)
       ```
    2. **UPDATE tenant SET parent_tenant_id=NULL, share_default_to_children=1 WHERE id=1**（幂等：NULL 默认即此值；仅显式化）
    3. **ALTER user_tenant**：
       ```python
       op.add_column('user_tenant', sa.Column('is_active', sa.Integer, nullable=True))
       # 数据回填
       op.execute("UPDATE user_tenant SET is_active = 1 WHERE status = 'active' AND is_default = 1")
       # 清理多条 active（保留 last_access_time 最新）
       op.execute("""
           UPDATE user_tenant ut1
           JOIN (
               SELECT user_id, MAX(last_access_time) AS max_ts
               FROM user_tenant
               WHERE is_active = 1
               GROUP BY user_id
               HAVING COUNT(*) > 1
           ) dup ON ut1.user_id = dup.user_id
           SET ut1.is_active = NULL
           WHERE ut1.is_active = 1
             AND (ut1.last_access_time IS NULL OR ut1.last_access_time < dup.max_ts)
       """)
       op.drop_constraint('uk_user_tenant', 'user_tenant', type_='unique')
       op.create_unique_constraint('uk_user_active', 'user_tenant', ['user_id', 'is_active'])
       ```
    4. **ALTER department**：
       ```python
       op.add_column('department', sa.Column('is_tenant_root', sa.Integer, nullable=False, server_default='0'))
       op.add_column('department', sa.Column('mounted_tenant_id', sa.Integer, nullable=True))
       op.create_index('idx_dept_mounted_tenant', 'department', ['mounted_tenant_id'])
       ```
    5. **ALTER auditlog**（注意 F001 表名是 `auditlog` 无下划线）:
       ```python
       op.add_column('auditlog', sa.Column('tenant_id', sa.Integer, nullable=True))
       op.create_index('idx_auditlog_tenant_time', 'auditlog', ['tenant_id', 'create_time'])
       op.add_column('auditlog', sa.Column('operator_tenant_id', sa.Integer, nullable=True))
       op.add_column('auditlog', sa.Column('action', sa.String(64), nullable=True))
       op.create_index('idx_auditlog_action', 'auditlog', ['action'])
       op.add_column('auditlog', sa.Column('target_type', sa.String(32), nullable=True))
       op.add_column('auditlog', sa.Column('target_id', sa.String(64), nullable=True))
       op.add_column('auditlog', sa.Column('reason', sa.Text, nullable=True))
       op.add_column('auditlog', sa.Column('metadata', sa.JSON, nullable=True))
       ```
    6. 日志 print 摘要（new/altered tables）
  - **downgrade()**：反向 DROP COLUMN / DROP INDEX；`is_active` 数据不可恢复时输出 WARNING
  - **幂等 helper**：参照 F004 `v2_5_0_f004_rebac.py` 的 `_table_exists` 模式；新增 `_column_exists(table_name, column_name)` 查 `information_schema.columns`
  - **SQLite table_definitions 同步**：在 `TABLE_TENANT` 后追加 `parent_tenant_id INTEGER, share_default_to_children INTEGER DEFAULT 1`；`TABLE_USER_TENANT` 追加 `is_active INTEGER`，替换 UNIQUE；`TABLE_DEPARTMENT` 追加 `is_tenant_root INTEGER DEFAULT 0, mounted_tenant_id INTEGER`；`TABLE_AUDIT_LOG` 追加 7 字段
  **测试**:
  - 在本地 MySQL 执行 `alembic upgrade head` → `DESC tenant/user_tenant/department/auditlog` 字段齐全
  - `alembic downgrade -1` → 字段移除
  - SQLite 测试集（T02-T05）绿灯即为 table_definitions 同步成功的佐证
  **覆盖 AC**: AC-01（Root 自动存在）、AC-05（升级回归）、AC-09（唯一约束）、AC-12（status 枚举）、AC-13（audit_log 表字段）
  **依赖**: T02-T05 ORM 稳定

---

### Service 层

- [x] **T07**: TenantService Root 保护 + 废弃 CRUD 改 410 Gone
  **文件（修改）**:
  - `src/backend/bisheng/tenant/domain/services/tenant_service.py` — `aupdate_status` / `adelete_tenant` 前置 Root 校验
  - `src/backend/bisheng/tenant/api/endpoints/tenant_crud.py` — `POST /tenants` endpoint 改 410 Gone 响应
  - `src/backend/bisheng/tenant/api/endpoints/user_tenant.py` — `POST /user/switch-tenant` 改 410 Gone
  **文件（新建）**:
  - `src/backend/test/test_tenant_service_root_protect.py`
  **逻辑**:
  - **Root 常量**：`tenant/domain/constants.py` 新建（如不存在）—
    ```python
    ROOT_TENANT_ID: int = 1
    ```
  - **`TenantService` 新增/改造方法**（保留既有 sync 方法不动）:
    - `aupdate_status(tenant_id: int, new_status: str, operator: UserPayload) -> Tenant` —
      校验 `tenant_id != ROOT_TENANT_ID`；否则 `raise TenantTreeRootProtectedError()`；否则调 `TenantDao.aupdate_tenant(status=new_status)` + 写 audit_log `action='tenant.disable'` / `'tenant.archive'`
    - `adelete_tenant_guarded(tenant_id: int, operator)` — 前置 Root 保护 + 空 Child 校验（`TenantDao.aget_children_ids_active` 非空 → `TenantTreeHasChildrenError`），通过后删除
    - `validate_status_enum(status: str)` — 白名单 `{'active','disabled','archived','orphaned'}`
  - **废弃端点 410 Gone**：
    ```python
    # tenant_crud.py
    @router.post('/tenants', ...)
    async def create_tenant_deprecated():
        return JSONResponse(
            status_code=410,
            content={
                'error': '410 Gone',
                'detail': 'Root 由系统初始化自动创建（迁移时）；Child 通过 POST /api/v1/departments/{dept_id}/mount-tenant 创建',
            },
        )
    # user_tenant.py
    @router.post('/user/switch-tenant', ...)
    async def switch_tenant_deprecated():
        return JSONResponse(
            status_code=410,
            content={'error': '410 Gone', 'detail': 'Tenant switching removed — user tenant is derived from primary department'},
        )
    ```
    **保留签名不动**：不删 endpoint 以免前端调用崩溃；仅改实现
  **测试**:
  - `test_aupdate_status_root_rejected` — 对 tenant_id=1 调用 → 抛 `TenantTreeRootProtectedError`
  - `test_aupdate_status_child_succeeds` — tenant_id=2 + status='archived' → DAO 被调用
  - `test_adelete_tenant_root_rejected` — 同上
  - `test_adelete_tenant_with_active_children_rejected` — Child 存在时抛 `TenantTreeHasChildrenError`
  - `test_validate_status_enum_includes_orphaned` — 四个状态全部通过；`'foo'` 抛 ValueError
  - `test_post_tenants_returns_410` — TestClient `POST /api/v1/tenants` → status_code=410
  - `test_switch_tenant_returns_410` — TestClient `POST /api/v1/user/switch-tenant` → 410
  **覆盖 AC**: AC-11（Root 保护 22008）、AC-12（status 枚举）、AC-15（POST /tenants 410）、switch-tenant 410
  **依赖**: T01, T02

---

- [x] **T08**: TenantMountService（挂载 / 解绑策略 A/B/C / 资源下沉）+ Service 测试
  **文件（新建）**:
  - `src/backend/bisheng/tenant/domain/services/tenant_mount_service.py`
  - `src/backend/test/test_tenant_mount_service.py`
  **逻辑**:
  - **`TenantMountService` classmethods**（全部 async，事务内完成；sync 版不需要）:
    - `async mount_child(dept_id: int, tenant_code: str, tenant_name: str, operator: UserPayload) -> Tenant`
      1. 校验 `operator.is_global_super()`（通过 `LoginUser` 或 `PermissionService`）
      2. 加载 `Department`；校验：
         - 非根部门（`parent_id is not None`）→ 否则 `TenantTreeRootDeptMountError(22003)`
         - `is_tenant_root != 1`（未重复挂载）→ 否则 `TenantTreeMountConflictError(22002)`
         - `DepartmentDao.aget_ancestors_with_mount(dept_id)` 为 None（无祖先挂载，MVP 2 层）→ 否则 `TenantTreeNestingForbiddenError(22001)`
      3. 创建 Child Tenant：`Tenant(tenant_code=X, tenant_name=Y, parent_tenant_id=ROOT_TENANT_ID, status='active')`
      4. `DepartmentDao.aset_mount(dept_id, new_tenant.id)`
      5. 写 audit_log `action='tenant.mount'`，metadata 含 `{'dept_id': X, 'dept_path': Y, 'tenant_code': Z}`
      6. 事务提交（用 `async with get_async_db_session() as session` 单事务）
    - `async unmount_child(dept_id: int, policy: Literal['migrate','archive','manual'], operator) -> dict`
      - 策略 A（migrate）：事务内批量 `UPDATE <23 张业务表> SET tenant_id=ROOT_TENANT_ID WHERE tenant_id=<child_id>`（抽 helper `_migrate_child_resources_to_root(child_id)`，循环 F001 `TENANT_TABLES` 列表）；Child.status='archived'；写 audit_log `action='tenant.unmount'` metadata `{'policy':'migrate', 'migrated_counts': {...}}`；返回 `{migrated: N}`
      - 策略 B（archive）：`TenantDao.aupdate_tenant(child_id, status='archived')`；`DepartmentDao.aunset_mount(dept_id)`；audit_log `action='tenant.unmount'` metadata `{'policy':'archive'}`
      - 策略 C（manual）：仅标记 `status='pending_manual'`（临时状态，不入正式枚举）+ 返回 `{message: 'UI flow pending, call reassign API'}`；**MVP 可实现为 `archive` + 警告日志**，真正 UI 推迟到未来 feature
    - `async migrate_resources_from_root(child_id: int, resource_ids: list[int], new_owner_user_id: Optional[int], operator) -> dict`（AC-04d）
      1. `operator.is_global_super()` → 否则 `TenantTreeMigratePermissionError(22010)`
      2. 遍历 resource_ids，确认所属表 + `resource.tenant_id == 1`；否则计入 failed 列表（`TenantTreeMigrateSourceError(22011)` 的 reason 字段）
      3. 事务内 `UPDATE <table> SET tenant_id=child_id WHERE id IN (passed_ids)`；可选 `new_owner_user_id` → 调 `PermissionService.authorize(resource_type, id, new_owner)` 重写 FGA owner 元组（如 `PermissionService` 已提供 `transfer_owner`）
      4. 写 audit_log `action='resource.migrate_tenant'` metadata `{'from_tenant_id':1, 'to_tenant_id':child_id, 'count':N, 'resource_ids': [...]}`
      5. 返回 `{migrated: N, failed: [{resource_id, reason}, ...]}`
    - **内部 helper**：`_ensure_global_super(operator)` / `_write_audit_log(...)`（封装 `AuditLogDao.ainsert_v2` + fail-open：写失败记 logger.error 不中断主事务）
  - **资源类型枚举**（MVP 仅 5 种，对齐 spec §6 可迁移表）：`{'knowledge','flow','assistant','channel','t_gpts_tools'}`；其他表通过扩展白名单追加；未知 resource_type 抛 `TenantTreeMigrateConflictError(22006)`
  **测试**（使用 `db_session` + mock `PermissionService` + factory）:
  - `test_mount_child_happy_path` — 普通部门 → Child 创建 + is_tenant_root=1 + audit_log 1 条
  - `test_mount_child_rejects_nested` — 先挂 dept A，再对 A 的子部门 B 挂 → `TenantTreeNestingForbiddenError`
  - `test_mount_child_rejects_root_dept` — parent_id=None 的部门 → `TenantTreeRootDeptMountError`
  - `test_mount_child_rejects_re_mount` — 已挂载部门再挂 → `TenantTreeMountConflictError`
  - `test_mount_child_rejects_non_super` — 非超管 operator → 抛权限错误（PermissionDenied or 22010 视实现）
  - `test_unmount_archive_policy` — 策略 B → Child.status='archived' + Department.is_tenant_root=0 + audit_log
  - `test_unmount_migrate_policy` — Child 下挂 1 knowledge + 1 flow，migrate 后两表 tenant_id=1 + Child.status='archived'
  - `test_migrate_resources_from_root_happy` — 2 条 tenant_id=1 的 resource → migrate 后 tenant_id=child + audit_log
  - `test_migrate_resources_rejects_non_super` — Child Admin 调 → `TenantTreeMigratePermissionError`
  - `test_migrate_resources_rejects_wrong_source` — resource.tenant_id=2 → 计入 failed，不影响其他成功项
  **覆盖 AC**: AC-02（挂载）、AC-03（嵌套拒绝）、AC-04a/b/c（解绑）、AC-04d（下沉）、AC-07（audit）
  **依赖**: T02, T04, T05, T07

---

- [x] **T09**: DepartmentDeletionHandler（孤儿集中入口）+ 测试
  **文件（新建）**:
  - `src/backend/bisheng/tenant/domain/services/department_deletion_handler.py`
  - `src/backend/test/test_department_deletion_handler.py`
  **逻辑**:
  - **`DepartmentDeletionHandler.on_deleted(dept_id, deletion_source)`**（spec §5.4.1 签名）:
    1. `dept = DepartmentDao.aget(dept_id)`；若 `dept.mounted_tenant_id is None` → return（普通删除）
    2. `TenantDao.aupdate_tenant(id=mounted_tenant_id, status='orphaned')`
    3. `AuditLogDao.ainsert_v2(tenant_id=mounted_tenant_id, operator_id=0, operator_tenant_id=ROOT_TENANT_ID, action='tenant.orphaned', target_type='tenant', target_id=str(mounted_tenant_id), metadata={'deletion_source': deletion_source, 'dept_id': dept_id})`
    4. 站内消息：通过 `MessageService.send_message` 给所有全局超管（`LoginUser.list_global_supers()` 或直接查 `system:global#super_admin` FGA 元组 → 取 user_id 列表）；title="子公司挂载点被删除"，body 含 source / dept.name / tenant_id
    5. 邮件：若 `SMTPConf` 配置可用则发送；否则 fail-silently + logger.warning
  - **调用方集成点**（F011 本身不触发）：文档化 `deletion_source` 枚举 `'sso_realtime' | 'celery_reconcile' | 'manual'`；F014/F015 通过 import 本 handler 调用
  - **全局超管列表获取**：新增 helper `async def _list_global_super_admins() -> list[int]`，内部调 `FGAClient.list_users(system:global, super_admin)` 或回退 `RoleDao` 查 `role_id=1` 用户集合（取决于 v2.5.0 实现，必要时只查 Role）
  **测试**（`test_department_deletion_handler.py`）:
  - `test_on_deleted_non_mounted_noop` — 普通部门（mounted_tenant_id=NULL）调用 → Tenant status 不变，audit_log 无新记录
  - `test_on_deleted_sets_orphaned` — 挂载部门调用 → Tenant.status='orphaned'
  - `test_on_deleted_writes_audit_log` — audit_log `action='tenant.orphaned'` 包含 deletion_source
  - `test_on_deleted_sends_inbox_message` — mock MessageService.send_message 被调用，接收者=全局超管列表
  - `test_on_deleted_already_orphaned_idempotent` — 已 orphaned 再调 → 不重复 audit_log（或允许重复但 idempotent；看实际需求，默认允许重复以便追溯多次触发）
  **覆盖 AC**: AC-08（SSO 同步触发孤儿）、AC-14（is_deleted + mounted_tenant_id 触发 orphaned）、§5.4.1 DepartmentDeletionHandler 签名
  **依赖**: T02, T05, T08

---

### API 层

- [x] **T10**: API 端点 + 路由注册 + 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/tenant/api/endpoints/tenant_mount.py` — 4 个新端点
  - `src/backend/bisheng/tenant/api/schemas/mount_schema.py` — 请求/响应 Pydantic DTO
  - `src/backend/test/test_tenant_mount_api.py` — TestClient 集成测试
  **文件（修改）**:
  - `src/backend/bisheng/tenant/api/router.py` — 注册 tenant_mount 子路由
  **逻辑**:
  - **Schemas**（`mount_schema.py`）:
    ```python
    class MountTenantRequest(BaseModel):
        tenant_code: str = Field(..., min_length=1, max_length=64)
        tenant_name: str = Field(..., min_length=1, max_length=128)

    class UnmountTenantRequest(BaseModel):
        policy: Literal['migrate', 'archive', 'manual']

    class MigrateFromRootRequest(BaseModel):
        resource_ids: list[int] = Field(..., min_items=1, max_items=500)
        resource_type: str = Field(..., pattern='^(knowledge|flow|assistant|channel|t_gpts_tools)$')
        new_owner_user_id: Optional[int] = None

    class TenantStatusRequest(BaseModel):
        status: Literal['active', 'disabled', 'archived']  # orphaned 不允许手动设置
    ```
  - **端点清单**:
    1. `POST /api/v1/departments/{dept_id}/mount-tenant` — body=MountTenantRequest → 调 `TenantMountService.mount_child`；返 `UnifiedResponseModel[Tenant]`
    2. `DELETE /api/v1/departments/{dept_id}/mount-tenant` — body=UnmountTenantRequest → 调 `TenantMountService.unmount_child`；返 `UnifiedResponseModel[dict]`
    3. `PUT /api/v1/tenants/{tenant_id}/status` — body=TenantStatusRequest →
       - **路由 guard**：`if tenant_id == 1: return TenantTreeRootProtectedError.return_resp()`（在进入 Service 前的第一行）
       - 否则调 `TenantService.aupdate_status`
    4. `POST /api/v1/tenants/{child_id}/resources/migrate-from-root` — body=MigrateFromRootRequest → 调 `TenantMountService.migrate_resources_from_root`；返 `{migrated: N, failed: [...]}` via `UnifiedResponseModel`
  - **认证**：每个端点 `user: UserPayload = Depends(UserPayload.get_login_user)`；Service 内部再做 `is_global_super` 校验
  - **路由注册**：`tenant/api/router.py` 引入 `from .endpoints import tenant_mount` + `router.include_router(tenant_mount.router)`
  - **`DELETE /api/v1/tenants/{tenant_id}` 保护**：既有 endpoint（如存在）在路由处插入 `tenant_id == 1 → 403 + 22008` guard；不新建端点
  **测试**（TestClient，使用 `test_client` fixture + `create_tenant` / `create_department` factory + mock operator）:
  - `test_mount_tenant_happy_path` — 普通部门 POST → 201 + Child Tenant 返回
  - `test_mount_tenant_nested_returns_22001` — 已挂载的子部门再挂 → 400 + code=22001
  - `test_mount_tenant_root_dept_returns_22003` — parent_id=None 部门挂 → 400 + code=22003
  - `test_unmount_archive_returns_ok` — DELETE body policy=archive → 200 + Child status=archived
  - `test_put_tenant_status_root_returns_22008` — `PUT /tenants/1/status` → 403 + code=22008
  - `test_put_tenant_status_child_succeeds` — `PUT /tenants/2/status body={status:'disabled'}` → 200
  - `test_delete_tenant_root_returns_22008` — `DELETE /tenants/1` → 403 + code=22008
  - `test_migrate_from_root_happy` — 2 个 Root 资源 → 200 + migrated=2
  - `test_migrate_from_root_non_super_returns_22010` — Child Admin → 403 + code=22010
  - `test_migrate_from_root_wrong_source_returns_22011` — resource.tenant_id=2 → 200 + failed 列表含 22011
  - `test_post_tenants_deprecated_returns_410` — AC-15 验证
  - `test_switch_tenant_deprecated_returns_410`
  **覆盖 AC**: AC-02, AC-03, AC-04a/b/d, AC-11, AC-15
  **依赖**: T07, T08, T09

---

### 验收

- [x] **T11**: AC 对照表 + spec §8 手工 QA 执行记录
  **文件（新建）**:
  - `features/v2.5.1/011-tenant-tree-model/ac-verification.md` — AC-01~AC-15 每条对应的测试名 / 手工验证命令 / 实际结果
  **逻辑**:
  - 建立 AC→测试映射表：
    | AC | 测试文件 / 手工命令 | 状态 |
    |----|-------------------|------|
    | AC-01 | `test_tenant_tree_dao.py::test_parent_tenant_id_null_for_root` + 手工 `SELECT * FROM tenant WHERE id=1` | 待验证 |
    | AC-02 | `test_tenant_mount_api.py::test_mount_tenant_happy_path` | 待验证 |
    | ... | ... | ... |
  - 执行 spec §8 "手工 QA 清单"（4 组共 20+ 条）：
    - 8.1 基础功能（9 条）— 本地环境手工跑 + 截图
    - 8.2 数据隔离（4 条）— 用真实用户登录跨 Tenant 验证
    - 8.3 边界与容错（4 条）— 唯一约束冲突、循环挂载等
    - 8.4 升级回归（5 条）— alembic upgrade head → 字段/数据/废弃 API
    - 8.5 审计（3 条）— audit_log 查询
  - 执行 `.venv/bin/pytest src/backend/test/` 全绿（v2.5.0 回归）
  - 执行 `.venv/bin/pytest src/backend/test/test_tenant_tree_dao.py src/backend/test/test_user_tenant_leaf.py src/backend/test/test_department_dao.py src/backend/test/test_audit_log_v2.py src/backend/test/test_tenant_service_root_protect.py src/backend/test/test_tenant_mount_service.py src/backend/test/test_department_deletion_handler.py src/backend/test/test_tenant_mount_api.py -v` 本 feature 测试全绿
  **覆盖 AC**: 全部 15 条
  **依赖**: T01-T10

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差。

- 待填写

---

## 工时预估

| Task | 预估 | 备注 |
|------|------|------|
| T01 | 1h | 纯错误码 + 文档 |
| T02 | 2h | ORM + 4 个 DAO 方法 + 8 条测试 |
| T03 | 1.5h | ORM + 3 个 DAO 方法 + 6 条测试 |
| T04 | 1.5h | ORM + 4 个 DAO 方法 + 5 条测试 |
| T05 | 2h | ORM + 3 个 DAO 方法 + 5 条测试 |
| T06 | 3h | Alembic + SQLite DDL 同步 + 本地往返验证 |
| T07 | 2h | Root 保护 + 2 个 410 端点 + 7 条测试 |
| T08 | 4h | Mount/Unmount/Migrate 三主流程 + 10 条测试 |
| T09 | 2h | Handler + 5 条测试 |
| T10 | 3h | 4 个端点 + DTO + 11 条集成测试 |
| T11 | 4h | AC 映射 + 手工 QA + 回归 |
| **合计** | **26h** | ~3-4 人日 |
