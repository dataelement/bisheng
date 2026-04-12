# Tasks: ReBAC 权限引擎核心

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | ���态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | PRD DSL 同步修正（can_delete + knowledge_file 统一 + folder owner） |
| tasks.md | ✅ 已拆解 | 18 个任务 |
| 实现 | 🔲 未开始 | 0 / 18 完成 |

---

## 任务依赖图

```
T01(配置+Docker)──┐
T04(DSL模型)   ──┤
T05(错误码)    ──┤
T06(FailedTuple)─┤
T07a(Schemas)  ──┤
                 ├→ T02(FGAClient) → T03(FGAManager) → T07b(PermissionService) → T08(缓存)
                 │                                             ├→ T09a(Handler重构) → T09b(调用点)
                 │                                             ├→ T10(Celery补偿)
                 │                                             ├→ T11(LoginUser集成)
                 │                                             ├→ T12a(API check) → T12b(API authorize)
                 │                                             └→ T13(OwnerService)
                 └──────────────────────────────────────────→ T14(集成测试)
```

**可并行组**：A(T01,T04,T05,T06,T07a) → B(T02) → C(T03) → D(T07b,T08) → E(T09a,T10,T11,T12a,T13) → F(T09b,T12b) → G(T14)

---

## T01: OpenFGA 配置模型 + Docker 服务

- **AC 覆盖**: AC-08, AC-09
- **预估**: 2h
- **依赖**: 无

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/core/config/openfga.py` |
| 修改 | `src/backend/bisheng/core/config/settings.py` |
| 修改 | `src/backend/bisheng/config.yaml` |
| 修改 | `docker/docker-compose.yml` |

### 实现要点

1. **`core/config/openfga.py`** — `OpenFGAConf(BaseModel)`：
   - `api_url: str = 'http://localhost:8080'`
   - `store_name: str = 'bisheng'`
   - `store_id: Optional[str] = None` — 已有 store 时直接使用
   - `model_id: Optional[str] = None` — 已有 model 时直接使用
   - `timeout: int = 5` — httpx 请求超时（秒）
   - `enabled: bool = True`
   - 参考 `core/config/multi_tenant.py` 的 Pydantic 模式

2. **`core/config/settings.py`** — Settings 类添加字段（在 `multi_tenant` 后）：
   ```python
   from bisheng.core.config.openfga import OpenFGAConf
   openfga: OpenFGAConf = OpenFGAConf()
   ```

3. **`config.yaml`** — 添加默认配置块：
   ```yaml
   openfga:
     api_url: 'http://localhost:8080'
     store_name: 'bisheng'
     enabled: true
   ```

4. **`docker/docker-compose.yml`** — 添加 OpenFGA 服务：
   - `image: openfga/openfga:latest`
   - `command: run`
   - `environment`: `OPENFGA_DATASTORE_ENGINE=mysql`, `OPENFGA_DATASTORE_URI` 指向 bisheng-mysql
   - `ports`: 8080, 8081, 3000
   - `depends_on`: mysql（healthy）
   - `healthcheck`: `wget --no-verbose --tries=1 --spider http://localhost:8080/healthz`
   - `restart: unless-stopped`
   - 需先用 `OPENFGA_DATASTORE_ENGINE=mysql` 执行 `migrate`（init-container 或 entrypoint）

### 测试

- [ ] `OpenFGAConf()` 默认值正确解析
- [ ] `settings.openfga.enabled` 读取 config.yaml 值
- [ ] `docker compose up openfga` 启动成功，`/healthz` 返回 200

---

## T02: FGAClient 核心（httpx 异步客户端）

- **AC 覆盖**: AC-01
- **预估**: 4h
- **依赖**: T01

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/core/openfga/__init__.py` |
| 新建 | `src/backend/bisheng/core/openfga/client.py` |
| 新建 | `src/backend/bisheng/core/openfga/exceptions.py` |

### 实现要点

1. **`core/openfga/exceptions.py`**：
   - `FGAClientError(Exception)` — 基类
   - `FGAConnectionError(FGAClientError)` — 连接失败
   - `FGAWriteError(FGAClientError)` — 元组写入失败
   - `FGAModelError(FGAClientError)` — 授权模型问题

2. **`core/openfga/client.py`** — `FGAClient` 类：
   - `__init__(api_url: str, store_id: str, model_id: str, timeout: int = 5)`
   - 内部创建 `httpx.AsyncClient(base_url=api_url, timeout=timeout)`
   - **核心方法**（全部 async）：

   | 方法 | OpenFGA API | 返回值 |
   |------|------------|--------|
   | `check(user, relation, object)` | `POST /stores/{sid}/check` | `bool` |
   | `list_objects(user, relation, type)` | `POST /stores/{sid}/list-objects` | `list[str]` |
   | `write_tuples(writes, deletes=None)` | `POST /stores/{sid}/write` | `None` |
   | `read_tuples(user?, relation?, object?)` | `POST /stores/{sid}/read` | `list[dict]` |
   | `batch_check(checks)` | `POST /stores/{sid}/batch-check` | `list[bool]` |
   | `write_authorization_model(model)` | `POST /stores/{sid}/authorization-models` | `str`(model_id) |
   | `create_store(name)` | `POST /stores` | `str`(store_id) |
   | `list_stores()` | `GET /stores` | `list[dict]` |
   | `health()` | `GET /healthz` | `bool` |
   | `close()` | — | 关闭 httpx client |

   - 所有方法在 `httpx.ConnectError` / `httpx.TimeoutException` 时抛 `FGAConnectionError`（AD-03 fail-closed）
   - `write_tuples` 的 writes/deletes 参数格式：`[{"user": "user:7", "relation": "owner", "object": "workflow:abc"}]`
   - `check` 和 `batch_check` 请求中包含 `authorization_model_id` 字段
   - `list_objects` 返回值从 `{"objects": ["workflow:abc", ...]}` 提取列表

### 测试

- [ ] mock httpx 响应，验证 check/write_tuples/list_objects/read_tuples/batch_check 的请求格式和返回解析
- [ ] 模拟连接超时，验证抛出 `FGAConnectionError`
- [ ] 模拟 HTTP 400/500 响应，验证抛出 `FGAWriteError`

---

## T03: FGAManager（BaseContextManager）+ 应用上下文注册

- **AC 覆盖**: AC-09
- **预估**: 3h
- **依赖**: T01, T02, T04

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/core/openfga/manager.py` |
| 修改 | `src/backend/bisheng/core/context/manager.py` |

### 实现要点

1. **`core/openfga/manager.py`** — `FGAManager(BaseContextManager[FGAClient])`：
   - `name = "openfga"`
   - 构造函数接收 `OpenFGAConf`
   - `_async_initialize()`:
     1. 创建 httpx.AsyncClient
     2. 如果 config 有 `store_id` → 直接使用；否则 `list_stores()` 查找匹配 `store_name` 的 store → 不存在则 `create_store()`
     3. 如果 config 有 `model_id` → 直接使用；否则调用 `write_authorization_model(AUTHORIZATION_MODEL)` 获得 model_id
     4. 返回 `FGAClient(api_url, store_id, model_id)`
   - `_sync_initialize()`: 不支持同步初始化，抛 `TypeError`
   - `_async_cleanup()`: 调用 `client.close()`
   - 便捷函数 `get_fga_client() -> FGAClient`（模块级，从 context registry 获取实例）
   - 初始化失败时 log error 但不阻塞其他服务（AC-09 第 4 条）

2. **`core/context/manager.py`** — `_register_default_contexts()` 末尾添加（在 PromptManager 后、`logger.debug` 前）：
   ```python
   from bisheng.core.openfga.manager import FGAManager
   if config.openfga.enabled:
       self.register_context(FGAManager(openfga_config=config.openfga))
   ```

### 测试

- [ ] mock FGAClient，验证 FGAManager 初始化流程（create store → write model）
- [ ] config.store_id 已配置时跳过 create_store
- [ ] `openfga.enabled=false` 时 FGAManager 不注册到 app_context

---

## T04: 静态授权模型 DSL

- **AC 覆盖**: AC-09（模型写入）
- **预估**: 3h
- **依赖**: 无

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/core/openfga/authorization_model.py` |

### 实现要点

1. **`core/openfga/authorization_model.py`**：
   - `MODEL_VERSION = "v1.0.0"` — 版本标记
   - `AUTHORIZATION_MODEL: dict` — OpenFGA JSON 格式授权模型
   - 包含 13 种类型（spec §5.2 完整 DSL）：
     - 基础类型：`user`, `system`(super_admin), `tenant`(admin/member), `department`(parent/admin/member), `user_group`(admin/member)
     - 资源类型（8 种）：`knowledge_space`, `folder`, `knowledge_file`, `channel`, `workflow`, `assistant`, `tool`, `dashboard`
   - 所有资源类型包含 `can_delete` 关系（AD-10）
   - 权限金字塔：`owner ⊃ manager ⊃ editor ⊃ viewer`（INV-7）
   - department.admin 从 parent 继承（INV-12）
   - folder/knowledge_file 权限从 parent 继承
   - `get_authorization_model() -> dict` 函数返回副本
   - DSL 以 OpenFGA JSON schema 格式编写（非 DSL 文本），结构：
     ```python
     {"schema_version": "1.1", "type_definitions": [...]}
     ```

### 测试

- [ ] 验证 13 种 type 全部存在
- [ ] 验证每种资源类型包含 can_delete 关系
- [ ] 验证 department.admin 定义包含 `admin from parent`
- [ ] 验证 knowledge_file 包含 7+1 关系（owner/manager/editor/viewer + can_manage/can_edit/can_read + can_delete）

---

## T05: 错误码模块 190

- **AC 覆盖**: AC-01, AC-02, AC-03, AC-04, AC-07, AC-09
- **预估**: 1h
- **依赖**: 无

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/common/errcode/permission.py` |

### 实现要点

参照 `common/errcode/user_group.py`（模块码 230）模式：

```python
from .base import BaseErrorCode

class PermissionDeniedError(BaseErrorCode):
    Code: int = 19000
    Msg: str = 'Permission denied'

class PermissionCheckFailedError(BaseErrorCode):
    Code: int = 19001
    Msg: str = 'Permission check failed'

class PermissionFGAUnavailableError(BaseErrorCode):
    Code: int = 19002
    Msg: str = 'Authorization service unavailable'

class PermissionInvalidResourceError(BaseErrorCode):
    Code: int = 19003
    Msg: str = 'Invalid resource type or ID'

class PermissionTupleWriteError(BaseErrorCode):
    Code: int = 19004
    Msg: str = 'Failed to write authorization tuple'

class PermissionInvalidRelationError(BaseErrorCode):
    Code: int = 19005
    Msg: str = 'Invalid permission relation'
```

### 测试

- [ ] 各错误码可正确 import
- [ ] `return_resp()` 返回正确 status_code

---

## T06: FailedTuple ORM + 数据库迁移

- **AC 覆盖**: AC-04
- **预估**: 3h
- **依赖**: 无

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/database/models/failed_tuple.py` |
| 新建 | `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f004_rebac.py` |

### 实现要点

1. **`database/models/failed_tuple.py`**：
   - `FailedTuple(SQLModelSerializable, table=True)`：
     - `__tablename__ = 'failed_tuple'`
     - `id`: BigInteger, PK, autoincrement
     - `action`: String(8), 'write' | 'delete'
     - `fga_user`: String(256), NOT NULL — OpenFGA user 字符串
     - `relation`: String(64), NOT NULL
     - `object`: String(256), NOT NULL — OpenFGA object 字符串
     - `retry_count`: Integer, default 0
     - `max_retries`: Integer, default 3
     - `status`: String(16), default 'pending' — pending | succeeded | dead
     - `error_message`: Text, nullable
     - `tenant_id`: Integer, default 1（INV-1 租户隔离）
     - `create_time`, `update_time`: DateTime
   - `FailedTupleDao`（@classmethod）：
     - `async acreate_batch(tuples: list[FailedTuple]) -> None`
     - `async aget_pending(limit: int = 100) -> list[FailedTuple]` — status=pending AND retry_count < max_retries
     - `async aupdate_succeeded(id: int) -> None`
     - `async aupdate_retry(id: int, error: str) -> None` — retry_count += 1, error_message = error
     - `async amark_dead(id: int, error: str) -> None` — status = dead
     - `async adelete_old_succeeded(before: datetime) -> int` — 清理历史成功记录

2. **Alembic 迁移** `v2_5_0_f004_rebac.py`：
   - `revision = 'f004_rebac'`, `down_revision = 'f003_user_group'`
   - `upgrade()`: CREATE TABLE failed_tuple（全部字段 + INDEX idx_status_retry + INDEX idx_tenant）
   - `downgrade()`: DROP TABLE failed_tuple

### 测试

- [ ] FailedTuple CRUD 正确（acreate_batch → aget_pending → aupdate_succeeded/aupdate_retry/amark_dead）
- [ ] aget_pending 只返回 status=pending 且 retry_count < max_retries
- [ ] tenant_id 自动过滤生效

---

## T07a: Permission 模块骨架 + Schemas

- **AC 覆盖**: AC-03（DTO 验证）
- **预估**: 1.5h
- **依赖**: 无

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/__init__.py` |
| 新建 | `src/backend/bisheng/permission/domain/__init__.py` |
| 新建 | `src/backend/bisheng/permission/domain/schemas/__init__.py` |
| 新建 | `src/backend/bisheng/permission/domain/schemas/permission_schema.py` |
| 新建 | `src/backend/bisheng/permission/domain/services/__init__.py` |

### 实现要点

创建 `permission/` DDD 模块骨架（__init__.py 均为空文件），以及 Pydantic DTOs。

---

## T07b: PermissionService 核心

- **AC 覆盖**: AC-02, AC-03, AC-05, AC-06
- **预估**: 4h
- **依赖**: T02, T05, T06, T07a

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/domain/services/permission_service.py` |

### 实现要点

1. **`permission/domain/schemas/permission_schema.py`** — Pydantic DTOs：
   - `PermissionCheckRequest(BaseModel)`: object_type, object_id, relation
   - `PermissionCheckResponse(BaseModel)`: allowed(bool)
   - `AuthorizeGrantItem(BaseModel)`: subject_type, subject_id, relation, include_children(bool=True)
   - `AuthorizeRevokeItem(BaseModel)`: subject_type, subject_id, relation
   - `AuthorizeRequest(BaseModel)`: grants(list[AuthorizeGrantItem]), revokes(list[AuthorizeRevokeItem]=None)
   - `ResourcePermissionItem(BaseModel)`: subject_type, subject_id, subject_name, relation, include_children(Optional)
   - `PermissionLevel(str, Enum)`: owner, can_manage, can_edit, can_read
   - `VALID_RESOURCE_TYPES`: set — knowledge_space, folder, knowledge_file, workflow, assistant, tool, channel, dashboard
   - `VALID_RELATIONS`: set — owner, manager, editor, viewer, can_manage, can_edit, can_read, can_delete
   - `UNCACHEABLE_RELATIONS`: set — can_manage, can_delete（AC-05 不缓存）

2. **`permission/domain/services/permission_service.py`** — `PermissionService`：
   - 所有方法 `@classmethod async`，无状态
   - **`check(user_id, relation, object_type, object_id, login_user=None) -> bool`**：
     - L1: `login_user and login_user.is_admin()` → return True（INV-5）
     - L2: relation 不在 UNCACHEABLE_RELATIONS 时，查 PermissionCache → 命中返回
     - L3: `get_fga_client().check()` → True 时写缓存并返回
     - L4: FGA 返回 False → owner 兜底：查 DB 资源表 user_id == user_id → True
     - L5: `FGAConnectionError` 捕获 → log error → return False（AD-03）
   - **`list_accessible_ids(user_id, relation, object_type, login_user=None) -> Optional[list[str]]`**：
     - admin → return None
     - 查 PermissionCache → 命中返回
     - `get_fga_client().list_objects()` → 提取 ID 列表（去 "type:" 前缀） → 写缓存 → 返回
     - `FGAConnectionError` → return []
   - **`authorize(object_type, object_id, grants, revokes=None) -> None`**：
     - 校验 object_type 在 VALID_RESOURCE_TYPES
     - 对每个 grant/revoke 调 `_expand_subject()` 展开
     - 构建 writes/deletes 列表
     - 调 `get_fga_client().write_tuples(writes, deletes)`
     - 成功 → 清缓存（`PermissionCache.invalidate_user` 对涉及用户）
     - 失败 → `_save_failed_tuples(writes + deletes, error)`
   - **`batch_write_tuples(operations: list[TupleOperation]) -> None`**：
     - 分离 writes(action=write) 和 deletes(action=delete)
     - 调 `get_fga_client().write_tuples(writes, deletes)`
     - 失败 → `_save_failed_tuples()`
   - **`get_resource_permissions(object_type, object_id) -> list[dict]`**：
     - `get_fga_client().read_tuples(object=f"{object_type}:{object_id}")`
     - 解析元组，聚合同部门子部门记录
   - **`get_permission_level(user_id, object_type, object_id) -> Optional[str]`**：
     - `batch_check` 检查 [owner, can_manage, can_edit, can_read]（AD-04）
     - 返回第一个 True 的级别，全 False 返回 None
   - **`_expand_subject(subject_type, subject_id, include_children=True) -> list[str]`**：
     - user → `["user:{id}"]`
     - department + include_children → `DepartmentDao.get_subtree_ids(path)` → `["department:{id}#member", ...]`
     - department + not include_children → `["department:{id}#member"]`
     - user_group → `["user_group:{id}#member"]`
   - **`_save_failed_tuples(operations, error) -> None`**：
     - 为每个 operation 创建 FailedTuple 记录
     - `FailedTupleDao.acreate_batch(tuples)`
   - **`_get_resource_creator(object_type, object_id) -> Optional[int]`**：
     - owner 兜底辅助方法：根据 object_type 查对应 DAO 的 user_id/create_user 字段
     - 支持的类型映射表（knowledge_space → KnowledgeDao, workflow → FlowDao 等）

### 测试

- [ ] 管理员短路：is_admin=True → check 返回 True，不调用 FGA
- [ ] 普通用户走 FGA check → 缓存写入 → 第二次调用命中缓存
- [ ] can_manage 检查不走缓存
- [ ] FGA 返回 False + DB user_id 匹配 → owner 兜底返回 True
- [ ] FGA 不可达 → check 返回 False（fail-closed）
- [ ] authorize 展开 department 子部门 → 验证 write_tuples 调用参数
- [ ] authorize 失败 → FailedTuple 记录创建

---

## T08: L2 Redis 缓存层

- **AC 覆盖**: AC-05
- **预估**: 2h
- **依赖**: T07（集成）

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/domain/services/permission_cache.py` |

### 实现要点

1. **`permission/domain/services/permission_cache.py`** — `PermissionCache`：
   - `KEY_PREFIX = "perm:"`, `TTL = 10`
   - 使用 `get_redis_client()` 获取 Redis 连接
   - **方法**（全部 `@classmethod async`）：

   | 方法 | Key 格式 | 说明 |
   |------|---------|------|
   | `get_check(user_id, relation, object_type, object_id)` | `perm:chk:{uid}:{rel}:{otype}:{oid}` | 返回 Optional[bool] |
   | `set_check(...)` | 同上 | SET + EX 10 |
   | `get_list_objects(user_id, relation, object_type)` | `perm:lst:{uid}:{rel}:{otype}` | 返回 Optional[list[str]] |
   | `set_list_objects(...)` | 同上 | JSON 序列化后 SET + EX 10 |
   | `invalidate_user(user_id)` | `perm:*:{uid}:*` | SCAN 模式匹配 + DEL |
   | `invalidate_all()` | `perm:*` | SCAN + DEL |

   - 缓存值用 JSON 序列化（bool → "1"/"0"，list → json.dumps）
   - `invalidate_user` 使用 `SCAN` + pipeline DEL（不用 `KEYS *`）
   - Redis 不可达时静默失败（log warning），不影响权限检查流程

### 测试

- [ ] set_check → get_check 命中
- [ ] TTL 过期后 get_check 返回 None
- [ ] invalidate_user 清除目标用户所有 key
- [ ] Redis 不可达时 get/set 不抛异常

---

## T09a: 共享 TupleOperation + ChangeHandler 重构

- **AC 覆盖**: AC-07
- **预估**: 2h
- **依赖**: T07a

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/domain/schemas/tuple_operation.py` |
| 修改 | `src/backend/bisheng/department/domain/services/department_change_handler.py` |
| 修改 | `src/backend/bisheng/user_group/domain/services/group_change_handler.py` |

### 实现要点

1. **`permission/domain/schemas/tuple_operation.py`** — 共享 TupleOperation（AD-08）：
   ```python
   @dataclass
   class TupleOperation:
       action: Literal['write', 'delete']
       user: str
       relation: str
       object: str
   ```

2. **`department_change_handler.py`** 修改：
   - 删除本地 `TupleOperation` 定义，改为导入共享版本（保留 re-export `TupleOperation = TupleOperation`）
   - 保留所有 `on_*` 静态方法不变
   - `execute()` 保留为同步兼容版本
   - 新增 `async execute_async(operations)` — 延迟导入 PermissionService，调用 batch_write_tuples

3. **`group_change_handler.py`** — 同上模式修改

### 测试

- [ ] TupleOperation 从 permission 模块导入成功
- [ ] 原 handler 模块的 `from ...department_change_handler import TupleOperation` re-export 兼容

---

## T09b: Service 调用点改为 execute_async

- **AC 覆盖**: AC-07
- **预估**: 1h
- **依赖**: T07b, T09a

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/department/domain/services/department_service.py` |
| 修改 | `src/backend/bisheng/user_group/domain/services/user_group_service.py` |

### 实现要点

1. **`department_service.py`** — 所有 `DepartmentChangeHandler.execute(ops)` 调用改为 `await DepartmentChangeHandler.execute_async(ops)`
2. **`user_group_service.py`** — 同上

### 测试

- [ ] 创建部门 → execute_async 被调用 → mock_openfga 中 parent 元组已写入
- [ ] 添加用户组成员 → execute_async 被调用 → mock_openfga 中 member 元组已写入

---

## T10: Celery 补偿任务

- **AC 覆盖**: AC-04
- **预估**: 3h
- **依赖**: T02, T06

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/worker/permission/__init__.py` |
| 新建 | `src/backend/bisheng/worker/permission/retry_failed_tuples.py` |
| 修改 | `src/backend/bisheng/core/config/settings.py` |
| 修改 | `src/backend/bisheng/worker/__init__.py` |

### 实现要点

1. **`worker/permission/retry_failed_tuples.py`**：
   ```python
   @bisheng_celery.task(acks_late=True)
   def retry_failed_tuples():
   ```
   - 查询 `FailedTupleDao.aget_pending(limit=100)`
   - 逐条处理：
     - action=write → `fga_client.write_tuples(writes=[tuple_dict])`
     - action=delete → `fga_client.write_tuples(deletes=[tuple_dict])`
     - 成功 → `FailedTupleDao.aupdate_succeeded(id)`
     - 失败 + retry_count < max_retries-1 → `FailedTupleDao.aupdate_retry(id, str(e))`
     - 失败 + retry_count >= max_retries-1 → `FailedTupleDao.amark_dead(id, str(e))` + `logger.critical(...)`
   - 需处理 Celery sync/async 桥接（任务函数内用 `asyncio.run()` 或项目已有的桥接模式）
   - tenant_id 上下文：使用 `bypass_tenant_filter()` 处理所有租户的 pending 记录

2. **`core/config/settings.py`** — CeleryConf.validate() 添加：
   ```python
   if 'retry_failed_tuples' not in self.beat_schedule:
       self.beat_schedule['retry_failed_tuples'] = {
           'task': 'bisheng.worker.permission.retry_failed_tuples.retry_failed_tuples',
           'schedule': 30.0,
       }
   ```

3. **`worker/__init__.py`** — 添加导入：
   ```python
   from bisheng.worker.permission.retry_failed_tuples import retry_failed_tuples
   ```

### 测试

- [ ] 创建 3 条 pending FailedTuple → 运行 retry_failed_tuples → 全部变 succeeded
- [ ] FGA 持续失败 → retry_count 递增 → 超过 max_retries 后 status=dead
- [ ] logger.critical 在 dead 时被调用

---

## T11: LoginUser 五级权限链路集成

- **AC 覆盖**: AC-10
- **预估**: 3h
- **依赖**: T07

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/user/domain/services/auth.py` |

### 实现要点

在 `LoginUser` 类中新增两个方法（**不修改任何旧方法**）：

```python
async def rebac_check(self, relation: str, object_type: str, object_id: str) -> bool:
    """ReBAC 权限检查（新统一入口，INV-3）。
    委托 PermissionService.check()，内含五级链路。
    """
    from bisheng.permission.domain.services.permission_service import PermissionService
    return await PermissionService.check(
        user_id=self.user_id,
        relation=relation,
        object_type=object_type,
        object_id=object_id,
        login_user=self,
    )

async def rebac_list_accessible(self, relation: str, object_type: str) -> Optional[List[str]]:
    """列出可访问资源 ID（admin 返回 None 表示不过滤）。"""
    from bisheng.permission.domain.services.permission_service import PermissionService
    return await PermissionService.list_accessible_ids(
        user_id=self.user_id,
        relation=relation,
        object_type=object_type,
        login_user=self,
    )
```

- 使用延迟导入避免循环依赖
- `UserPayload` 继�� `LoginUser`，新方法自动可用
- 旧方法 `access_check` / `async_access_check` 完全保留（F008 逐步迁移）

### 测试

- [ ] admin LoginUser 调 rebac_check → True（不触发 FGA）
- [ ] 普通 LoginUser 调 rebac_check → 委托到 PermissionService.check
- [ ] rebac_list_accessible admin → None
- [ ] rebac_list_accessible 普通用户 → ID 列表

---

## T12a: Permission API 端点（check + objects）

- **AC 覆盖**: AC-01, AC-02
- **预估**: 2h
- **依赖**: T05, T07b

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/api/__init__.py` |
| 新建 | `src/backend/bisheng/permission/api/router.py` |
| 新建 | `src/backend/bisheng/permission/api/endpoints/__init__.py` |
| 新建 | `src/backend/bisheng/permission/api/endpoints/permission_check.py` |
| 修改 | `src/backend/bisheng/api/router.py` |

### 实现要点

1. **`permission/api/endpoints/permission_check.py`**：
   - `POST /check`（spec §6.1）：
     - Body: `PermissionCheckRequest`
     - 调 `PermissionService.check(login_user.user_id, ...)`
     - 返回 `resp_200({"allowed": result})`
   - `GET /objects`（spec §6.4）：
     - Query: object_type, relation
     - 调 `PermissionService.list_accessible_ids(...)`
     - admin → `resp_200(None)`，普通用户 → `resp_200(ids)`

2. **`permission/api/endpoints/resource_permission.py`**：
   - `POST /resources/{resource_type}/{resource_id}/authorize`（spec §6.2）：
     - 校验 resource_type 在 VALID_RESOURCE_TYPES
     - 先检查调用者是否有 can_manage 权限
     - 调 `PermissionService.authorize(resource_type, resource_id, request.grants, request.revokes)`
     - 成功 → `resp_200(None)`
     - 无权限 → `PermissionDeniedError.return_resp()`
   - `GET /resources/{resource_type}/{resource_id}/permissions`（spec §6.3）：
     - 先检查调用者是否有 can_manage 权限
     - 调 `PermissionService.get_resource_permissions(...)`
     - 返回 `resp_200(permissions_list)`

3. **`permission/api/router.py`** — 先注册 check_router，resource_router 在 T12b 追加
4. **`api/router.py`** — 注册 permission_router（在 user_group_router 后）

### 测试

- [ ] POST /check 返回 `{"allowed": true/false}`
- [ ] GET /objects 管理员返回 null，普通用户返回 ID 列表

---

## T12b: Permission API 端点（authorize + permissions）

- **AC 覆盖**: AC-03
- **预估**: 2h
- **依赖**: T12a

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/api/endpoints/resource_permission.py` |
| 修改 | `src/backend/bisheng/permission/api/router.py` |

### 实现要点

1. **`resource_permission.py`**：
   - `POST /resources/{resource_type}/{resource_id}/authorize` — 授权/撤销
   - `GET /resources/{resource_type}/{resource_id}/permissions` — 查资源权限列表
2. **`router.py`** — 追加 resource_router

### 测试

- [ ] POST /authorize 无权限 → 19000 错误码
- [ ] POST /authorize 成功 → 200
- [ ] GET /permissions 返回资源权限列表

---

## T13: OwnerService

- **AC 覆盖**: AC-06
- **预估**: 2h
- **依赖**: T07

### 产出文件

| 操作 | 文件 |
|------|------|
| 新建 | `src/backend/bisheng/permission/domain/services/owner_service.py` |

### 实现要点

1. **`permission/domain/services/owner_service.py`** — `OwnerService`（@classmethod async）：
   - **`write_owner_tuple(user_id, object_type, object_id)`**：
     - 调 `PermissionService.authorize(object_type, object_id, grants=[{"subject_type": "user", "subject_id": user_id, "relation": "owner"}])`
     - 失败时不抛异常（由 PermissionService 内部写入 FailedTuple）
   - **`check_is_owner(user_id, object_type, object_id) -> bool`**：
     - 调 `PermissionService.check(user_id, "owner", object_type, object_id)`
   - **`transfer_ownership(from_user_id, to_user_id, object_type, object_id)`**：
     - revoke old owner + grant new owner（单次 authorize 调用）

### 测试

- [ ] write_owner_tuple → mock_openfga 中存在 owner 元组
- [ ] transfer_ownership → 旧 owner 元组删除 + 新 owner 元组写入

---

## T14: 集成测试 + Mock 升级

- **AC 覆盖**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10
- **预估**: 3h
- **依赖**: T01~T13

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `test/fixtures/mock_openfga.py` |
| 修改 | `test/fixtures/table_definitions.py` |
| 新建 | `test/test_fga_client.py` |
| 新建 | `test/test_permission_service.py` |
| 新建 | `test/test_permission_cache.py` |
| 新建 | `test/test_permission_api.py` |
| 新建 | `test/test_failed_tuple_retry.py` |
| 新建 | `test/test_change_handler_integration.py` |

### 实现要点

1. **升级 `mock_openfga.py`**：
   - 添加 `batch_check()` 方法
   - 添加 `write_authorization_model()` 方法（返回 mock model_id）
   - 添加 `create_store()` 方法（返回 mock store_id）
   - 添加 `read_tuples()` 方法（基于内存存储过滤返回）

2. **`table_definitions.py`** — 添加 `TABLE_FAILED_TUPLE` SQLite DDL

3. **测试用例矩阵**：

   | 测试文件 | 覆盖重点 |
   |---------|---------|
   | `test_fga_client.py` | FGAClient 各方法 + httpx mock + 异常处理 |
   | `test_permission_service.py` | 五级链路 + 缓存集成 + authorize 展开 + FailedTuple 写入 |
   | `test_permission_cache.py` | 缓存 hit/miss/invalidate + UNCACHEABLE_RELATIONS |
   | `test_permission_api.py` | 4 个 API 端点 happy path + error path |
   | `test_failed_tuple_retry.py` | Celery 任务重试逻辑 + dead letter |
   | `test_change_handler_integration.py` | Department/Group ChangeHandler → PermissionService 集成 |

### 测试

- [ ] `pytest test/test_fga_client.py` 全部通过
- [ ] `pytest test/test_permission_service.py` 全部通过
- [ ] `pytest test/test_permission_api.py` 全部通过
- [ ] `pytest test/test_change_handler_integration.py` 全部通过
