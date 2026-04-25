# ReBAC 权限系统 Bug 审查报告

日期: 2026-04-23
分支: feat/2.5.0

---

## Bug 1（P0 致命）：`_run_async_safe` 跨 event loop 污染全局连接

### 现象
日志中出现以下错误后，所有权限检查全部失败返回 403：
```
Cache get_check error: ... got Future <Future pending> attached to a different loop
_resolve_resource_tenant failed for knowledge_library:50: ... attached to a different event loop
Unexpected error during permission check: <asyncio.locks.Event ...> is bound to a different event loop
```

### 根因
`src/backend/bisheng/permission/domain/services/owner_service.py:18` 的 `_run_async_safe`：

```python
def _run_async_safe(coro):
    try:
        loop = asyncio.get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=10)
    except RuntimeError:
        try:
            return anyio.from_thread.run(_await, coro)
        except Exception:
            pass
        return asyncio.run(coro)  # ← 创建临时 event loop
```

FastAPI sync 端点跑在 threadpool 里，`get_running_loop()` 抛 RuntimeError，`anyio.from_thread.run()` 也可能失败，最终 fallback 到 `asyncio.run()` 创建新 loop。

**致命点**：如果这次调用触发了 lazy 初始化（Redis manager 的 `asyncio.Lock`、DB 的 `create_async_engine` 连接池），这些资源就永久绑定到临时 loop。之后主 loop 上的所有 async 操作全部报错。

### 受影响调用点
| 文件 | 行号 | 调用 |
|------|------|------|
| `knowledge_service.py` | 381 | `write_owner_tuple_sync`（创建知识库） |
| `auth.py` | 210, 322, 360-361 | `rebac_check` / `rebac_list_accessible` |
| `knowledge_permission_service.py` | 68, 313 | `check_permission_id_sync` / `check_access_sync` |
| `application_permission_service.py` | 41, 252 | sync 方法 |
| `tool_permission_service.py` | 198, 235 | sync 方法 |

### 修复方向
1. 把所有 sync 端点改成 async，消除 `_run_async_safe` 调用
2. 或者：确保 `_run_async_safe` 永远不走 `asyncio.run()` 分支——在 FastAPI threadpool 里必须用 `anyio.from_thread.run()` 回到主 loop

---

## Bug 2（P0 致命）：`check()` 和 `get_effective_permission_ids_async()` 双轨不一致

### 现象
同一个用户对同一个资源，两条路径可能返回不同结果。

### 根因
系统有两条完全不同的权限检查路径：

**路径 A — `PermissionService.check()`**
- 直接调 `fga.check(user='user:X', relation='can_read')`
- 依赖 FGA 的 computed relation + department membership tuple 解析
- 用于：写权限（`KNOWLEDGE_WRITE`）、`get_permission_level`、`authorize_resource` 校验

**路径 B — `get_effective_permission_ids_async()`**
- 调 `fga.read_tuples(object=...)` + Python 层面匹配 `user_subject_strings`（从 DB 查 UserDepartment 构建）
- 不依赖 FGA 的 department membership tuple
- 用于：读权限（`view_kb` / `use_kb`）、列表过滤

**不一致场景**：用户通过 department 被授权 viewer。
- 路径 B：`read_tuples` 返回 `department:5#member viewer knowledge_library:50`，Python 匹配 `user_subject_strings` 里有 `department:5#member` → 允许
- 路径 A：`fga.check(user='user:7', relation='can_read')` → FGA 需要 `user:7 member department:5` tuple 才能解析 → 如果没有（Bug 3）→ 拒绝

### 修复方向
统一走一条路径。建议统一走路径 B（read_tuples + Python 匹配），因为它不依赖 FGA department membership 同步。

---

## Bug 3（P1 严重）：Migration 缺少 department membership 同步到 FGA

### 现象
通过 department 授权的资源，`fga.check()` 和 `fga.list_objects()` 返回 False。

### 根因
`src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py` 有 6 个步骤：
1. Super Admin
2. User Group Membership
3. Role Access Expansion
4. Space/Channel Members
5. Resource Owners
6. Folder Hierarchy

**缺少**：Department Membership（`user:X member department:Y`）。

`DepartmentChangeHandler.on_members_added` 只在部门成员**变更**时触发。升级后已有的部门成员不会被同步到 FGA。

OpenFGA authorization model 定义了 `department#member` 作为 viewer/editor/manager 的 `directly_related_user_types`，所以 `fga.check()` 和 `fga.list_objects()` 需要这些 tuple 才能解析间接授权。

### 修复方向
在 migration 里增加 Step 7：遍历 `user_department` 表，为每条记录写入 `user:{uid} member department:{dept_id}` tuple。

---

## Bug 4（P1 严重）：`list_objects` 无法查到 department/user_group 间接授权的资源

### 现象
知识库列表为空，即使用户通过 department 被授权了 viewer。

### 根因
`PermissionService.list_accessible_ids` 调用：
```python
fga.list_objects(user=f'user:{user_id}', relation='can_read', type='knowledge_library')
```

只传 `user:X`，不传 `department:Y#member`。OpenFGA 需要通过 authorization model 解析间接关系，但前提是 FGA 里有 `user:X member department:Y` tuple（Bug 3）。

`_finalize_accessible_ids` 的补偿逻辑只补充了：
- creator 创建的资源
- 部门管理员隐式可见的资源
- 子租户管理员可见的资源

**不会**补充通过 department/user_group 授权的资源。

### 修复方向
修复 Bug 3 后此问题自动解决。或者在 `_finalize_accessible_ids` 里增加 department/user_group 授权资源的补偿查询。

---

## Bug 5（P2 中等）：Bindings 全局存储无 tenant 隔离

### 现象
不同租户的 binding 混在一起，理论上可能匹配到错误的 binding。

### 根因
`_get_bindings()` 从 `Config` 表读取 `permission_relation_model_bindings_v1`。Config 表没有 `tenant_id` 列，所有租户的 bindings 存在同一个 JSON blob 里。

`_resolve_binding_for_tuple` 按 `resource_type + resource_id + subject + relation` 匹配。不同租户的资源 ID 理论上可能碰撞（虽然概率低）。

更重要的是 bindings 列表会无限增长，没有清理机制。

### 修复方向
短期：binding key 里加入 tenant_id。长期：bindings 迁移到独立表。

---

## Bug 6（P2 中等）：tenant_filter 和 `_filter_ids_by_tenant_gate` 双重过滤导致共享资源不可见

### 现象
Child 用户看不到 Root tenant 共享的资源。

### 根因
`_finalize_accessible_ids` → `_filter_ids_by_tenant_gate` 允许了 Root 共享资源（通过 `_is_shared_to` 检查）。

但 `aget_user_knowledge` 的 ORM 查询被 `tenant_filter.py` 自动注入 `WHERE tenant_id = current_tenant_id`（leaf_id）。Root 资源的 `tenant_id = 1 ≠ leaf_id`，被过滤掉。

`tenant_filter.py:87`:
```python
stmt = stmt.where(table.c.tenant_id == tid)  # 严格等于，不是 IN-list
```

`visible_tenant_ids` ContextVar 存了 `{leaf_id, 1}`，但 `tenant_filter.py` 完全没有使用它。

### 修复方向
`tenant_filter.py` 的 `_resolve_tenant_id` 应该检查 `visible_tenant_ids`，如果有值则用 `WHERE tenant_id IN (...)` 代替 `WHERE tenant_id = X`。

---

## Bug 7（P3 低）：PermissionCache 对 department/user_group 授权变更的缓存失效不完整

### 现象
通过 department 授权后，部分用户需要等 10s 才能看到权限变更。

### 根因
`PermissionService.authorize` 第 284 行只清除直接受影响用户的缓存：
```python
if affected_user_ids:
    await PermissionCache.invalidate_user(uid)
```

对于 department/user_group 授权，`affected_user_ids` 只包含 `subject_id`（department ID），不包含 department 下的所有用户。

### 修复方向
对 department/user_group 类型的 grant/revoke，展开所有成员 user_id 并清除缓存。

---

## PRD 对比发现的实现偏差

### 偏差 1（P1）：PRD 要求 knowledge 统一为 `knowledge_space`，实现拆成了两个 type

PRD 原文：
> 知识库统一为 knowledge_space：管理后台文档/QA知识库(type=0,1) 和工作台知识空间(type=3) 在 ReBAC 层共用同一个 object_type

实际实现：`authorization_model.py` 定义了 `knowledge_space` 和 `knowledge_library` 两个独立 type。代码里到处区分这两个 type，并且有 `_legacy_alias_object_types` 做兼容映射。

影响：
- 增加了代码复杂度（每个权限检查都要处理 legacy alias）
- `_legacy_alias_object_types` 对每个 knowledge_library 资源都要额外查一次 DB 判断类型
- bindings 里 `resource_type` 可能是 `knowledge_space` 也可能是 `knowledge_library`，需要 migration 逻辑（`_migrate_legacy_knowledge_library_bindings`）

### 偏差 2（P1）：PRD 要求 `list_accessible_ids` 始终返回 `list[str]`，实现返回 `None`

PRD 原文：
> `PermissionService.list_accessible_ids()` 本身始终返回 `list[str]`，语义清晰，调用方无需处理 None 分支

实际实现：admin 返回 `None`，非 admin 返回 `list[str]`。所有调用方都要处理 `None` 分支。

PRD Review 也指出了这个问题（3.2 节），建议将 admin 判断提前到调用方。

### 偏差 3（P2）：PRD 要求 `relation_definition` 表，实现用 Config 表 JSON blob

PRD 设计了独立的 `relation_definition` 表存储关系定义。实际实现把 relation models 和 bindings 都存在 `Config` 表的 JSON blob 里（key: `permission_relation_models_v1` 和 `permission_relation_model_bindings_v1`）。

影响：
- 无法用 SQL 查询/过滤单条 binding
- bindings 列表无限增长，每次读取都要 parse 整个 JSON
- 无 tenant 隔离（Bug 5）
- 并发写入可能丢失数据（read-modify-write 不是原子的）

### 偏差 4（P2）：PRD 要求权限列表 API 分 direct/inherited，实现只返回 direct

PRD API 4.3 设计：
```json
{
    "direct": [...],
    "inherited": [{ "inherited_from": { "object_type": "knowledge_space", ... } }]
}
```

实际实现 `get_resource_permissions` 只返回 `fga.read_tuples` 的直接 tuples，没有 inherited 字段。对于 folder/knowledge_file 类型的资源，用户看不到从父级继承的权限。

### 偏差 5（P2）：PRD 要求 `failed_tuples` 补偿表，实现存在但重试机制不完整

PRD 要求：
> 定时任务每 30s 扫描 failed_tuples，重试写入，最多 3 次

实际实现有 `failed_tuples` 表和 `retry_failed_tuples.py` worker，但：
- worker 用 `write_tuples_sync`（sync 方法），可能触发 Bug 1 的 event loop 问题
- 没有看到 30s 定时调度的配置（需要确认 Celery beat 是否配置了）

### 偏差 6（P1）：PRD 要求双写期宽松策略，实现直接切到 ReBAC-only

PRD Phase 3：
> `LoginUser.access_check` 同时查旧表和 OpenFGA，任一通过即允许（宽松策略）

实际实现没有双写期。`check_access_async` 直接走 ReBAC 路径（`check_permission_id_async` 或 `PermissionService.check`），不再查旧的 `RoleAccessDao`。

如果 migration 不完整（Bug 3），用户在旧系统有权限但 FGA 里没有对应 tuple，就会被拒绝。

---

## 调用链路图

```
前端请求
  │
  ├─ GET /knowledge (列表)
  │   └─ get_knowledge()
  │       ├─ rebac_list_accessible('can_read', 'knowledge_library')
  │       │   └─ PermissionService.list_accessible_ids()
  │       │       ├─ fga.list_objects(user='user:X')  ← Bug 3,4: department 授权查不到
  │       │       └─ _finalize_accessible_ids()
  │       │           └─ _filter_ids_by_tenant_gate()  ← Bug 6: 允许共享资源
  │       │
  │       ├─ filter_knowledge_ids_by_permission_async(merged, 'use_kb')
  │       │   └─ get_effective_permission_ids_async()  ← 路径 B
  │       │       ├─ fga.read_tuples() + Python 匹配
  │       │       ├─ get_implicit_permission_level()
  │       │       └─ get_permission_level()  ← 路径 A (fallback)
  │       │
  │       └─ aget_user_knowledge(knowledge_id_extra)
  │           └─ ORM query + tenant_filter  ← Bug 6: WHERE tenant_id = leaf_id
  │
  ├─ GET /knowledge/file_list/{id} (文件列表)
  │   └─ aget_knowledge_files()
  │       └─ ensure_knowledge_read_async()
  │           └─ check_access_async()
  │               └─ check_permission_id_async('view_kb')  ← 路径 B
  │
  ├─ POST /authorize (授权)
  │   └─ authorize_resource()
  │       ├─ PermissionService.authorize()  → fga.write_tuples()
  │       └─ _save_bindings()  → Config 表 JSON  ← Bug 5: 无 tenant 隔离
  │
  └─ 创建知识库 (sync 端点)
      └─ write_owner_tuple_sync()
          └─ _run_async_safe()  ← Bug 1: 可能污染全局连接
```
