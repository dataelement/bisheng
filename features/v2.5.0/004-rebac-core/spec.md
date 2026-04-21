# Feature: ReBAC 权限引擎核心

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §1-2](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)、[2.5 技术方案](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20技术方案.md)
**优先级**: P0
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- `core/openfga/client.py`：FGAClient 单例（check/list_objects/write_tuples/read_tuples/write_authorization_model）
- `permission/` DDD 模块：PermissionService（check/list_accessible_ids/authorize/_expand_subject/_save_failed_tuples）
- 静态 OpenFGA 授权模型 DSL（13 种类型：user/system/tenant/department/user_group + 8 种资源类型）
- FailedTuple ORM + Celery 补偿任务（每 30s 重试，最多 3 次）
- Permission API 端点：
  - `POST /api/v1/permissions/check` — 权限检查
  - `POST /api/v1/resources/{type}/{id}/authorize` — 授权（授予/撤回）
  - `GET /api/v1/resources/{type}/{id}/permissions` — 查询资源权限列表
  - `GET /api/v1/permissions/objects` — 列出可访问资源
- 五级检查链路集成到 LoginUser：① super_admin → ② tenant member → ③ tenant admin → ④ ReBAC → ⑤ RBAC menu
- L2 缓存（Redis，10s TTL，authorize/成员变更时主动清除）
- Owner 兜底逻辑（OpenFGA 写入延迟时，DB creator 放行）
- Docker compose OpenFGA 服务定义
- 错误码模块 190

**OUT**:
- 实际资源模块权限检查调用 → F008-resource-rebac-adaptation
- 角色/菜单/配额管理 → F005-role-menu-quota
- 旧权限数据迁移 → F006-permission-migration
- 前端授权对话框 → F007-resource-permission-ui
- 动态授权模型生成（P2 延后）
- RelationDefinition 表（P2 延后）

**关键决策（预判）**:
- AD-01: P0 阶段静态 FGA 模型，不做动态生成
- AD-02: super_admin 检查走 LoginUser.is_admin() 缓存，不走 OpenFGA Check 热路径
- AD-03: OpenFGA 不可用时 fail-closed（拒绝访问），不 fail-open
- AD-04: 列表 API 权限级别用 BatchCheck（owner→can_manage→can_edit→can_read），admin 短路返回 owner

**关键文件（预判）**:
- 新建: `src/backend/bisheng/core/openfga/client.py`
- 新建: `src/backend/bisheng/permission/`（完整 DDD 模块：api/ + domain/）
- 新建: `src/backend/bisheng/database/models/failed_tuple.py`
- 修改: `src/backend/bisheng/user/domain/services/auth.py`（LoginUser 五级链路）
- 修改: `docker/docker-compose.yml`（OpenFGA 服务）
- 修改: `src/backend/bisheng/core/context/manager.py`（FGAClient 初始化）

**关联不变量**: INV-2, INV-3, INV-4, INV-5, INV-7, INV-12

---

## 1. 概述与用户故事

F004 是 v2.5 权限体系改造的核心基础设施。它将 OpenFGA 作为 ReBAC 引擎集成到 BiSheng 后端，提供统一的权限检查、资源授权、缓存和双写补偿能力。后续 F005-F008 均依赖此 Feature 提供的 PermissionService 接口。

### 用户故事

**US-01 系统管理员**：作为系统管理员，我期望在任何资源操作中都自动获得全部权限（无需等待 OpenFGA 查询），以便快速处理紧急运维任务。

**US-02 资源所有者**：作为资源创建者，我期望创建资源后立即拥有 owner 权限，即使 OpenFGA 写入有短暂延迟，也不影响我对资源的操作。

**US-03 普通用户**：作为普通用户，我期望只能看到和操作被授权的资源，授权变更后在 10 秒内生效，确保数据安全。

**US-04 租户管理员**：作为租户管理员，我期望在本租户内拥有所有资源的管理权限（无需逐个授权），以便管理租户内的资源分配。

**US-05 权限管理者**：作为资源的 manager，我期望能将资源授权给用户、部门（含子部门）或用户组，并能查看和撤销已有的授权关系。

---

## 2. 验收标准

### AC-01: FGAClient 正确封装 OpenFGA REST API

- [ ] `FGAClient.check(user, relation, object)` 调用 `POST /stores/{store_id}/check`，返回 `bool`
- [ ] `FGAClient.write_tuples(writes, deletes)` 调用 `POST /stores/{store_id}/write`，支持批量写入和删除
- [ ] `FGAClient.list_objects(user, relation, type)` 调用 `POST /stores/{store_id}/list-objects`，返回对象 ID 列表
- [ ] `FGAClient.read_tuples(user, relation, object)` 调用 `POST /stores/{store_id}/read`，支持过滤条件
- [ ] `FGAClient.batch_check(checks)` 调用 `POST /stores/{store_id}/batch-check`，返回 `list[bool]`
- [ ] 所有方法在 OpenFGA 连接失败时抛出 `FGAConnectionError`（fail-closed，AD-03）
- [ ] httpx.AsyncClient 复用连接池，超时可配置

### AC-02: PermissionService 五级检查链路

- [ ] 系统管理员（`LoginUser.is_admin() == True`）直接返回 True，不调用 OpenFGA（INV-5）
- [ ] 租户管理员短路：`tenant:{id}#admin` 在本租户内直接返回 True
- [ ] 普通用户走 OpenFGA Check，再走 Owner 兜底
- [ ] Owner 兜底：OpenFGA 返回 False 时，查 DB 资源表 `user_id == current_user_id`，如匹配返回 True
- [ ] OpenFGA 不可用时返回 False（fail-closed，AD-03），不降级为 True

### AC-03: 资源授权 API

- [ ] `POST /resources/{type}/{id}/authorize` 支持 grants 和 revokes 批量操作
- [ ] 支持三种授权主体：user、department、user_group
- [ ] department 授权时 `include_children=true`（默认）自动展开子部门树，为每个子部门写入独立元组（INV-12）
- [ ] 授权成功后主动清除相关用户的 L2 缓存
- [ ] 仅资源 owner 或 manager 可调用授权 API

### AC-04: FailedTuple 补偿机制

- [ ] OpenFGA 写入失败时自动记入 `failed_tuple` 表，不抛异常给调用方（INV-4）
- [ ] Celery Beat 每 30s 扫描 `status=pending` 且 `retry_count < max_retries` 的记录并重试
- [ ] 重试成功后 `status` 更新为 `succeeded`
- [ ] 超过 3 次重试后 `status` 更新为 `dead`，记录 `logger.critical` 告警
- [ ] FailedTuple 表包含 `tenant_id` 字段，遵循自动租户过滤

### AC-05: L2 Redis 缓存

- [ ] `PermissionService.check()` 先查 Redis 缓存，命中直接返回
- [ ] `PermissionService.list_accessible_ids()` 先查 Redis 缓存，命中直接返回
- [ ] 缓存 TTL = 10 秒
- [ ] `authorize()` / `revoke()` 操作后主动清除相关用户缓存
- [ ] ChangeHandler 执行成员变更后清除受影响用户缓存
- [ ] `can_manage` 和 `can_delete` 检查不走缓存（安全敏感操作，实时查询 OpenFGA）

### AC-06: Owner 兜底逻辑

- [ ] 资源创建时调用 `PermissionService.authorize()` 写入 owner 元组
- [ ] 写入失败时记入 FailedTuple，但调用方仍返回创建成功
- [ ] 补偿完成前，资源创建者通过 DB `user_id` 字段匹配获得等效 owner 权限

### AC-07: ChangeHandler 连接真实 OpenFGA

- [ ] `DepartmentChangeHandler.execute()` 替换日志桩为 `PermissionService.batch_write_tuples()`
- [ ] `GroupChangeHandler.execute()` 替换日志桩为 `PermissionService.batch_write_tuples()`
- [ ] 两个 Handler 的 `TupleOperation` 提取为共享 dataclass，保留原模块 re-export

### AC-08: Docker Compose OpenFGA 服务

- [ ] `docker/docker-compose.yml` 包含 `openfga` 服务定义
- [ ] 使用 MySQL 存储引擎（复用 bisheng-mysql）
- [ ] 健康检查配置：`/healthz` 端点
- [ ] 端口映射：8080(HTTP), 8081(gRPC), 3000(Playground)

### AC-09: 应用启动时自动初始化

- [ ] `FGAManager` 启动时自动检测/创建 Store
- [ ] 自动比对并写入最新的 Authorization Model（静态 DSL）
- [ ] `config.yaml` 中 `openfga.enabled=false` 时跳过初始化（不影响启动）
- [ ] `openfga.enabled=true` 但 OpenFGA 不可达时，FGAManager 初始化失败但不阻塞其他服务

### AC-10: LoginUser 集成

- [ ] `LoginUser` 新增 `async rebac_check(relation, object_type, object_id) -> bool`
- [ ] `LoginUser` 新增 `async rebac_list_accessible(relation, object_type) -> Optional[list[str]]`
- [ ] 旧方法 `access_check()` / `async_access_check()` 保持不变（F008 逐步迁移）
- [ ] `UserPayload` 继承 LoginUser，新方法自动可用

---

## 3. 边界情况

| ID | 场景 | 预期行为 |
|----|------|---------|
| EC-01 | OpenFGA 服务完全不可达 | `FGAClient` 抛出 `FGAConnectionError`；`PermissionService.check()` 执行 Owner 兜底后返回 False（fail-closed）；`authorize()` 全部记入 FailedTuple |
| EC-02 | OpenFGA 写入部分成功（批量中部分元组失败） | 成功的生效，失败的逐条记入 FailedTuple |
| EC-03 | 部门授权含子部门，但部门树深度 > 100 | 展开子部门 ID 列表，分批写入（每批 ≤ 100 条元组）|
| EC-04 | FailedTuple 堆积超过阈值 | Celery 任务每次只取 100 条处理，不会 OOM；dead 记录由运维手动处理 |
| EC-05 | 资源创建后立即检查权限（owner 元组写入延迟） | Owner 兜底查 DB `user_id`，确保创建者始终有权限 |
| EC-06 | 并发授权同一资源（多人同时修改权限） | OpenFGA 支持幂等写入，重复元组不报错；缓存清除可能有 < 10s 窗口不一致 |
| EC-07 | `openfga.enabled=false` | FGAManager 不注册；`PermissionService.check()` 降级为旧 `RoleAccess` 检查逻辑 |
| EC-08 | Authorization Model 版本变更 | FGAManager 启动时检测当前 model_id，不一致则写入新 model；旧元组与新 model 兼容（只增不删 type） |
| EC-09 | 删除部门/用户组后，相关授权元组残留 | ChangeHandler.on_archived/on_deleted 生成 delete 操作；F006 迁移时统一清理 |
| EC-10 | 缓存与 OpenFGA 状态不一致（缓存清除失败） | 最多 10s 后缓存自动过期；对安全敏感操作（如 can_manage）不缓存 |

---

## 4. 架构决策

| ID | 决策 | 理由 | 替代方案 |
|----|------|------|---------|
| AD-01 | P0 使用静态 FGA 授权模型，不支持动态生成 | 动态 DSL 生成正确性难保证，并发竞态风险高；13 种类型在 v2.5 范围内足够 | P2 实现带分布式锁的动态模型生成 |
| AD-02 | super_admin 判定走 `LoginUser.is_admin()`（JWT + DB role），不走 OpenFGA | 减少热路径 OpenFGA 调用；admin 判定在请求级内存中缓存，零网络开销 | 写入 `system:global#super_admin` 元组，每次 check |
| AD-03 | OpenFGA 不可用时 fail-closed（拒绝） | 安全优先；fail-open 会导致未授权用户访问资源 | fail-open + 告警 |
| AD-04 | 列表 API 通过 BatchCheck 计算 permission_level | 单次 batch 调用代替 4 次串行 check；从高到低（owner→can_manage→can_edit→can_read），命中即停 | 每个资源 4 次 check |
| AD-05 | FGAClient 使用 httpx 自封装，不引入 openfga-sdk | 项目已有 httpx；减少外部依赖；REST API 简单稳定（5 个核心端点） | `pip install openfga-sdk` |
| AD-06 | FGAManager 启动时自动创建 Store + 写入 Model | 零运维配置，适合开发和 CI；生产环境也可通过 config 指定已有 store_id | 运维手动初始化 |
| AD-07 | ChangeHandler.execute() 保留同步版本 + 新增异步版本 | 兼容 F002/F003 现有的同步调用点，同时支持异步上下文 | 全部改为异步 |
| AD-08 | TupleOperation 提取为共享 dataclass | 消除 DepartmentChangeHandler 和 GroupChangeHandler 的重复定义 | 各自维护独立定义 |
| AD-09 | knowledge_file 统一为 7 关系结构 + can_delete | PRD 原 knowledge_file 只有 owner/can_read/can_edit/can_delete 四关系；统一为与其他资源一致的 owner/manager/editor/viewer + can_manage/can_edit/can_read + can_delete 结构，降低 PermissionService 的类型特殊处理 | 保留 PRD 原有的简化结构 |
| AD-10 | 所有资源类型均包含 can_delete 关系 | 顶级资源 `can_delete: owner`，层级资源 `can_delete: owner or can_manage from parent`；统一删除权限控制点 | 删除逻辑硬编码在业务层 |

---

## 5. 数据库 & Domain 模型

### 5.1 新增表：failed_tuple

```sql
CREATE TABLE failed_tuple (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    action          VARCHAR(8)   NOT NULL DEFAULT 'write' COMMENT 'write | delete',
    fga_user        VARCHAR(256) NOT NULL COMMENT 'OpenFGA user, e.g. user:7, department:5#member',
    relation        VARCHAR(64)  NOT NULL COMMENT 'OpenFGA relation, e.g. owner, viewer',
    object          VARCHAR(256) NOT NULL COMMENT 'OpenFGA object, e.g. workflow:abc-123',
    retry_count     INT          NOT NULL DEFAULT 0,
    max_retries     INT          NOT NULL DEFAULT 3,
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending | succeeded | dead',
    error_message   TEXT         DEFAULT NULL,
    tenant_id       INT UNSIGNED NOT NULL DEFAULT 1,
    create_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_status_retry (status, retry_count),
    INDEX idx_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OpenFGA tuple write compensation queue';
```

### 5.2 OpenFGA 授权模型（13 种类型）

```
model
  schema 1.1

type user

type system
  relations
    define super_admin: [user]

type tenant
  relations
    define admin: [user]
    define member: [user]

type department
  relations
    define parent: [department]
    define admin: [user] or admin from parent
    define member: [user]

type user_group
  relations
    define admin: [user]
    define member: [user]

type knowledge_space
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner

type folder
  relations
    define parent: [knowledge_space, folder]
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner or can_manage from parent
    define editor: [user, department#member, user_group#member] or manager or can_edit from parent
    define viewer: [user, department#member, user_group#member] or editor or can_read from parent
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner or can_manage from parent

type knowledge_file
  relations
    define parent: [folder, knowledge_space]
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner or can_manage from parent
    define editor: [user, department#member, user_group#member] or manager or can_edit from parent
    define viewer: [user, department#member, user_group#member] or editor or can_read from parent
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner or can_manage from parent

type channel
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner

type workflow
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner

type assistant
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner

type tool
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner

type dashboard
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor: [user, department#member, user_group#member] or manager
    define viewer: [user, department#member, user_group#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer
    define can_delete: owner
```

### 5.3 权限金字塔

```
owner ─────────────── 可查看 + 编辑 + 管理 + 删除
  └─ manager ──────── 可查看 + 编辑 + 管理
       └─ editor ──── 可查看 + 编辑
            └─ viewer  可查看
```

`can_manage` / `can_edit` / `can_read` 为计算关系（computed），分别等价于 `manager` / `editor` / `viewer` 及其所有父级。

`can_delete` 为独立关系：顶级资源（knowledge_space/workflow/assistant/tool/channel/dashboard）仅 owner 可删除；层级资源（folder/knowledge_file）owner 或父级 manager 以上可删除。

### 5.4 共享 TupleOperation DTO

```python
@dataclass
class TupleOperation:
    action: Literal['write', 'delete']
    user: str       # e.g. "user:7", "department:5#member"
    relation: str   # e.g. "owner", "viewer", "member"
    object: str     # e.g. "workflow:abc-123", "department:5"
```

从 `permission/domain/schemas/tuple_operation.py` 导出，DepartmentChangeHandler 和 GroupChangeHandler 改为导入此共享定义。

---

## 6. API 契约

### 6.1 权限检查

```
POST /api/v1/permissions/check
Authorization: Bearer <JWT>

Request:
{
    "object_type": "workflow",      // 资源类型
    "object_id": "abc-123",         // 资源 ID
    "relation": "can_edit"          // 检查的权限关系
}

Response 200:
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "allowed": true
    }
}
```

### 6.2 资源授权

```
POST /api/v1/resources/{resource_type}/{resource_id}/authorize
Authorization: Bearer <JWT>

Path: resource_type = knowledge_space|folder|knowledge_file|workflow|assistant|tool|channel|dashboard
      resource_id = 资源 ID

Request:
{
    "grants": [
        {
            "subject_type": "department",
            "subject_id": 5,
            "relation": "viewer",
            "include_children": true      // 默认 true，展开子部门
        },
        {
            "subject_type": "user",
            "subject_id": 12,
            "relation": "editor"
        },
        {
            "subject_type": "user_group",
            "subject_id": 3,
            "relation": "manager"
        }
    ],
    "revokes": [
        {
            "subject_type": "user",
            "subject_id": 8,
            "relation": "viewer"
        }
    ]
}

Response 200:
{
    "status_code": 200,
    "status_message": "success",
    "data": null
}

Response 403 (无授权管理权限):
{
    "status_code": 19000,
    "status_message": "Permission denied",
    "data": null
}
```

### 6.3 查询资源权限列表

```
GET /api/v1/resources/{resource_type}/{resource_id}/permissions
Authorization: Bearer <JWT>

Response 200:
{
    "status_code": 200,
    "status_message": "success",
    "data": [
        {
            "subject_type": "user",
            "subject_id": 7,
            "subject_name": "张三",
            "relation": "owner"
        },
        {
            "subject_type": "department",
            "subject_id": 5,
            "subject_name": "工程部",
            "relation": "viewer",
            "include_children": true
        },
        {
            "subject_type": "user_group",
            "subject_id": 3,
            "subject_name": "Alpha项目组",
            "relation": "editor"
        }
    ]
}
```

### 6.4 列出可访问资源

```
GET /api/v1/permissions/objects?object_type=workflow&relation=can_read
Authorization: Bearer <JWT>

Response 200:
{
    "status_code": 200,
    "status_message": "success",
    "data": ["abc-123", "def-456", "ghi-789"]
}
```

管理员返回 `null`（表示"不过滤"，调用方走无条件查询）。

### 6.5 错误码表

| 编码 | 类名 | 描述 | 关联 AC |
|------|------|------|--------|
| 19000 | PermissionDeniedError | 权限不足，拒绝访问 | AC-02, AC-03 |
| 19001 | PermissionCheckFailedError | 权限检查执行失败（内部错误） | AC-01 |
| 19002 | PermissionFGAUnavailableError | 授权服务不可达 | AC-07, AC-09 |
| 19003 | PermissionInvalidResourceError | 无效的资源类型或 ID | AC-03 |
| 19004 | PermissionTupleWriteError | 授权元组写入失败（已记入补偿队列） | AC-04 |
| 19005 | PermissionInvalidRelationError | 无效的权限关系 | AC-03 |

---

## 7. Service 层逻辑

### 7.1 PermissionService（核心）

```
PermissionService
├── check(user_id, relation, object_type, object_id, login_user?) -> bool
│     L1: login_user.is_admin() → True                    [INV-5]
│     L2: PermissionCache.get_check() → 缓存命中返回
│     L3: FGAClient.check() → True/False
│     L4: Owner 兜底 → 查 DB resource.user_id
│     L5: fail-closed → False                              [AD-03]
│
├── list_accessible_ids(user_id, relation, object_type, login_user?) -> Optional[list[str]]
│     admin → None (不过滤)
│     PermissionCache.get_list_objects() → 缓存命中返回
│     FGAClient.list_objects() → 提取 ID 列表
│
├── authorize(object_type, object_id, grants, revokes?)
│     展开 department 子部门 (_expand_subject)
│     FGAClient.write_tuples(writes, deletes)
│     失败 → _save_failed_tuples()                        [INV-4]
│     成功 → PermissionCache.invalidate 相关用户
│
├── batch_write_tuples(operations: list[TupleOperation])
│     分离 writes/deletes
│     FGAClient.write_tuples()
│     失败 → _save_failed_tuples()
│
├── get_resource_permissions(object_type, object_id) -> list[dict]
│     FGAClient.read_tuples()
│     聚合部门子部门元组为单条记录
│
├── get_permission_level(user_id, object_type, object_id) -> Optional[str]
│     FGAClient.batch_check() 从高到低: owner → can_manage → can_edit → can_read [AD-04]
│     命中即返回
│
└── _expand_subject(subject_type, subject_id, include_children) -> list[str]
      user → ["user:{id}"]
      department (include_children=True) → DepartmentDao.get_subtree_ids() → ["department:{id}#member", ...]
      department (include_children=False) → ["department:{id}#member"]
      user_group → ["user_group:{id}#member"]
```

### 7.2 PermissionCache

```
PermissionCache
├── get_check(user_id, relation, object_type, object_id) -> Optional[bool]
│     key: perm:chk:{user_id}:{relation}:{object_type}:{object_id}
├── set_check(..., result: bool)                           TTL=10s
├── get_list_objects(user_id, relation, object_type) -> Optional[list[str]]
│     key: perm:lst:{user_id}:{relation}:{object_type}
├── set_list_objects(..., ids: list[str])                   TTL=10s
├── invalidate_user(user_id)                               SCAN perm:*:{user_id}:* + DEL
└── invalidate_all()                                       SCAN perm:* + DEL
```

### 7.3 OwnerService

```
OwnerService
├── write_owner_tuple(user_id, object_type, object_id)    → PermissionService.authorize(grants=[owner])
├── check_is_owner(user_id, object_type, object_id)       → PermissionService.check(relation="owner")
└── transfer_ownership(from_id, to_id, object_type, object_id) → revoke old + grant new
```

### 7.4 FGAClient

```
FGAClient(api_url, store_id, model_id)
├── check(user, relation, object) -> bool                   POST /stores/{sid}/check
├── list_objects(user, relation, type) -> list[str]         POST /stores/{sid}/list-objects
├── write_tuples(writes, deletes?) -> None                  POST /stores/{sid}/write
├── read_tuples(user?, relation?, object?) -> list[dict]    POST /stores/{sid}/read
├── batch_check(checks) -> list[bool]                       POST /stores/{sid}/batch-check
├── write_authorization_model(model) -> str                 POST /stores/{sid}/authorization-models
├── create_store(name) -> str                               POST /stores
├── list_stores() -> list[dict]                             GET /stores
├── health() -> bool                                        GET /healthz
└── close()                                                 关闭 httpx client
```

### 7.5 FGAManager

```
FGAManager(BaseContextManager[FGAClient])
  name = "openfga"
  _async_initialize():
    1. 创建 httpx.AsyncClient
    2. list_stores() → 查找 store_name 匹配的 store
    3. 不存在 → create_store(store_name) → 获得 store_id
    4. write_authorization_model(AUTHORIZATION_MODEL) → 获得 model_id
    5. 返回 FGAClient(api_url, store_id, model_id)
  _async_cleanup(): close httpx client
  health_check(): client.health()
```

---

## 8. 前端设计

本 Feature 无前端变更。前端授权管理 UI 在 F007-resource-permission-ui 中实现。

---

## 9. 文件清单

### 新建文件

| 文件路径 | 说明 |
|---------|------|
| `core/config/openfga.py` | OpenFGA 配置模型 |
| `core/openfga/__init__.py` | 包初始化 |
| `core/openfga/client.py` | FGAClient httpx 封装 |
| `core/openfga/exceptions.py` | FGA 异常类 |
| `core/openfga/manager.py` | FGAManager 生命周期管理 |
| `core/openfga/authorization_model.py` | 静态 DSL 定义 |
| `permission/__init__.py` | 模块初始化 |
| `permission/domain/__init__.py` | domain 层初始化 |
| `permission/domain/schemas/__init__.py` | schemas 包 |
| `permission/domain/schemas/permission_schema.py` | Pydantic DTOs |
| `permission/domain/schemas/tuple_operation.py` | 共享 TupleOperation |
| `permission/domain/services/__init__.py` | services 包 |
| `permission/domain/services/permission_service.py` | PermissionService 核心 |
| `permission/domain/services/permission_cache.py` | L2 Redis 缓存 |
| `permission/domain/services/owner_service.py` | Owner 元组管理 |
| `permission/api/__init__.py` | API 包 |
| `permission/api/router.py` | APIRouter 注册 |
| `permission/api/endpoints/__init__.py` | endpoints 包 |
| `permission/api/endpoints/permission_check.py` | check + objects 端点 |
| `permission/api/endpoints/resource_permission.py` | authorize + permissions 端点 |
| `database/models/failed_tuple.py` | FailedTuple ORM + DAO |
| `common/errcode/permission.py` | 错误码 190xx |
| `worker/permission/__init__.py` | worker 包 |
| `worker/permission/retry_failed_tuples.py` | Celery 补偿任务 |
| `core/database/alembic/versions/v2_5_0_f004_rebac.py` | 数据库迁移 |

### 修改文件

| 文件路径 | 变更说明 |
|---------|---------|
| `core/config/settings.py` | 添加 `openfga: OpenFGAConf` 字段；CeleryConf 添加 beat_schedule |
| `core/context/manager.py` | `_register_default_contexts()` 注册 FGAManager |
| `config.yaml` | 添加 `openfga:` 配置块 |
| `user/domain/services/auth.py` | LoginUser 添加 `rebac_check` / `rebac_list_accessible` |
| `department/domain/services/department_change_handler.py` | TupleOperation 共享导入 + execute 连接 OpenFGA |
| `department/domain/services/department_service.py` | execute → execute_async |
| `user_group/domain/services/group_change_handler.py` | 同上 |
| `user_group/domain/services/user_group_service.py` | 同上 |
| `api/router.py` | 注册 permission_router |
| `worker/__init__.py` | 导入补偿任务模块 |
| `docker/docker-compose.yml` | 添加 OpenFGA 服务 |

---

## 10. 非功能要求

| 维度 | 要求 |
|------|------|
| **性能** | `PermissionService.check()` P99 < 50ms（含缓存命中场景 < 5ms）；`list_objects()` P99 < 200ms |
| **可用性** | OpenFGA 不可达时 fail-closed，不阻塞应用启动（FGAManager 初始化失败记日志） |
| **可靠性** | 双写补偿 FailedTuple 保证最终一致性；dead 记录需运维关注 |
| **安全性** | 权限检查不可绕过（F008 全量接入后）；fail-closed 确保未授权不可访问 |
| **可观测性** | FGAClient 调用记录 Trace ID；FailedTuple dead 记录 critical 日志；FGAManager 纳入 /health |
| **兼容性** | 旧 `access_check()` 方法保持不变；`openfga.enabled=false` 时行为与 v2.4 一致 |
| **可测试性** | `InMemoryOpenFGAClient` mock 支持全部 FGAClient 接口，测试无需真实 OpenFGA |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- 技术方案 Review: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案 Review.md`
