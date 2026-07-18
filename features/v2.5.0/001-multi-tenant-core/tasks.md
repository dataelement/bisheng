# Tasks: 多租户核心基础设施

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 14 项检查通过，3 个问题已修复 |
| tasks.md | ✅ 已拆解 | 21 项检查通过（Round 2），9 个任务 |
| 实现 | ✅ 已完成 | 9 / 9 完成 |

---

## 开发模式

**后端 Test-First（务实版）**：
- 理想流程：先写测试（红），再写实现（绿）
- 务实适配：当前项目测试基础薄弱（无 conftest/fixtures），T001 首先搭建最小 pytest 基础设施（conftest.py、SQLite fixture）
- 如果某任务的测试编写成本极高（如需要完整的 Milvus/ES mock），标注 `**测试降级**: 手动验证 + TODO 标记`

**前端 Test-Alongside（暂缓版）**：
- F001 不涉及前端，无前端测试

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## 依赖图

```
T001 (conftest + 配置)
  │
  v
T002 (ORM + DAO + 错误码)
  │
  v
T003 (ContextVar + Bypass)
  │
  ├──────────┬──────────┐
  v          v          v
T004       T005       T007
(SQLAlchemy (JWT+Auth) (Celery)
 事件钩子)
  │          │
  v          v
  └────┬─────┘
       v
T006 (HTTP/WS 中间件)
  │
  v
T008 (存储前缀函数)
  │
  v
T009 (DDL 迁移 + 默认数据)
```

---

## Tasks

### 基础设施

- [x] **T001**: 测试基础设施 + MultiTenantConf 配置
  **文件（新建）**:
  - `src/backend/test/conftest.py` — 最小 pytest fixture：SQLite in-memory engine + sync/async session + settings mock
  - `src/backend/bisheng/core/config/multi_tenant.py` — `MultiTenantConf(BaseModel)` 含 `enabled: bool = False`, `default_tenant_code: str = "default"`
  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — Settings 类添加 `multi_tenant: MultiTenantConf = MultiTenantConf()`
  **逻辑**:
  - conftest.py 提供 `db_engine` fixture（SQLite in-memory）、`sync_session` / `async_session` fixture、`mock_settings` fixture
  - `MultiTenantConf` 定义两个字段 + config.yaml 不在此任务修改（T009 迁移时一并加入）
  **覆盖 AC**: —（基础设施，无直接 AC）
  **依赖**: 无

- [x] **T002**: Tenant/UserTenant ORM + DAO + 错误码
  **文件（新建）**:
  - `src/backend/bisheng/database/models/tenant.py` — Tenant + UserTenant SQLModel 表定义 + TenantDao + UserTenantDao
  - `src/backend/bisheng/common/errcode/tenant.py` — 200xx 错误码
  - `src/backend/test/test_tenant_dao.py` — DAO 单元测试
  **逻辑**:
  - `Tenant` 表：id(INT PK), tenant_code(VARCHAR 64 UNIQUE), tenant_name(VARCHAR 128), logo, root_dept_id, status(active/disabled/archived), contact_name/phone/email, quota_config(JSON), storage_config(JSON), create_user, create_time, update_time
  - `UserTenant` 表：id(INT PK), user_id, tenant_id, is_default, status, last_access_time, join_time。UniqueConstraint(user_id, tenant_id)
  - `TenantDao` classmethods: `get_by_id`/`aget_by_id`, `get_by_code`/`aget_by_code`, `create_tenant`/`acreate_tenant`
  - `UserTenantDao` classmethods: `get_user_tenants`/`aget_user_tenants`, `get_user_default_tenant`, `add_user_to_tenant`/`aadd_user_to_tenant`
  - 错误码类继承 `BaseErrorCode`，模块编码 200，编号 20000~20004（TenantNotFoundError, TenantDisabledError, UserNotInTenantError, TenantCodeDuplicateError, NoTenantContextError）
  **测试**: `test_tenant_dao.py` — `test_create_tenant`, `test_get_by_code`, `test_create_user_tenant`, `test_unique_constraint`, `test_get_user_tenants`
  **覆盖 AC**: AC-01
  **依赖**: T001（conftest fixture）

---

### 后端核心基础设施（Test-First 配对）

- [x] **T003**: 租户 ContextVar + Bypass 机制
  **文件（新建）**:
  - `src/backend/bisheng/core/context/tenant.py` — ContextVar 定义 + 工具函数
  - `src/backend/test/test_tenant_context.py` — ContextVar 单元测试
  **逻辑**:
  - `DEFAULT_TENANT_ID: int = 1` 常量
  - `current_tenant_id: ContextVar[Optional[int]] = ContextVar("current_tenant_id", default=None)`
  - `get_current_tenant_id() -> Optional[int]`: 读取 ContextVar
  - `set_current_tenant_id(tenant_id: int) -> Token`: 设置 ContextVar，返回 token 用于 reset
  - `_bypass_tenant_filter: ContextVar[bool] = ContextVar("_bypass_tenant_filter", default=False)`
  - `bypass_tenant_filter()`: contextmanager，进入时设 True，退出时 reset
  - `is_tenant_filter_bypassed() -> bool`: 读取 bypass 状态
  **测试**: `test_tenant_context.py` —
  - `test_default_is_none` — 未设置时返回 None
  - `test_set_get` — 设置后读取正确值
  - `test_bypass_context_manager` — 进入 bypass 后 is_bypassed=True，退出后 False
  - `test_bypass_nested` — 嵌套 bypass 正确恢复
  - `test_async_isolation` — 不同 asyncio task 间 ContextVar 隔离
  **覆盖 AC**: AC-06
  **依赖**: T001

- [x] **T004**: SQLAlchemy 事件钩子（租户自动过滤 + 自动填充）
  **文件（新建）**:
  - `src/backend/bisheng/core/database/tenant_filter.py` — 事件注册 + 处理函数
  - `src/backend/test/test_tenant_filter.py` — 集成测试（SQLite in-memory）
  **文件（修改）**:
  - `src/backend/bisheng/core/database/manager.py` — 引擎创建后调用 `register_tenant_filter_events(engine)`
  **逻辑**:
  - `_tenant_aware_tables: Set[str]` — 启动时通过 `SQLModel.metadata.tables` 自动发现含 `tenant_id` 列的表名集合（不硬编码）
  - `register_tenant_filter_events(sync_engine, async_engine)` — 注册以下两个事件
  - **`do_orm_execute` 事件**（查询拦截）:
    1. 检查 `is_tenant_filter_bypassed()` → True 则跳过
    2. 检查 `orm_execute_state.is_select` → 非 SELECT 跳过
    3. 检查语句涉及的表是否在 `_tenant_aware_tables` 中
    4. 获取 `get_current_tenant_id()` → None 时：`multi_tenant.enabled=false` 用 DEFAULT_TENANT_ID，`enabled=true` 抛 `NoTenantContextError`
    5. 修改 statement：`orm_execute_state.statement = statement.where(table.c.tenant_id == tid)`
  - **`before_flush` 事件**（写入填充）:
    1. 遍历 `session.new`（新增对象）
    2. 如果对象的表名在 `_tenant_aware_tables` 中且 `tenant_id` 为 None 或 0
    3. 设置 `obj.tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID`
  - **已知限制**: `text()` raw SQL 不触发 ORM 事件，在函数 docstring 中注明
  **测试**: `test_tenant_filter.py`（使用 conftest.py 的 SQLite session） —
  - `test_select_auto_filter` — 插入两条不同 tenant_id 的记录，设置 context=1，SELECT 只返回 tenant_id=1 的 → AC-04
  - `test_insert_auto_fill` — 不设 tenant_id 创建记录，验证自动填充 → AC-05
  - `test_bypass_returns_all` — bypass 上下文中 SELECT 返回所有记录 → AC-06
  - `test_no_context_enabled_raises` — enabled=true 且无 context 时 SELECT 抛 NoTenantContextError → AC-11
  - `test_no_context_disabled_uses_default` — enabled=false 且无 context 时使用 DEFAULT_TENANT_ID → AC-11
  - `test_non_tenant_table_unaffected` — 无 tenant_id 列的表不受过滤影响
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-11
  **依赖**: T003

- [x] **T005**: JWT Payload 扩展 + LoginUser/UserPayload 改造
  **文件（修改）**:
  - `src/backend/bisheng/user/domain/services/auth.py`
  **文件（新建）**:
  - `src/backend/test/test_tenant_auth.py` — JWT + LoginUser 测试
  **逻辑**:
  - `LoginUser` 添加字段: `tenant_id: int = Field(default=1, description="Current tenant ID")`
  - `LoginUser.__init__` 中: `self.tenant_id = kwargs.get('tenant_id', DEFAULT_TENANT_ID)`
  - `LoginUser.create_access_token(user, auth_jwt, tenant_id=None)`: payload dict 加 `'tenant_id': tenant_id or DEFAULT_TENANT_ID`
  - `LoginUser.init_login_user(user_id, user_name, tenant_id=DEFAULT_TENANT_ID)` / `init_login_user_sync`: 接受并传递 tenant_id
  - `LoginUser.get_login_user(auth_jwt)`: 从 `subject.get('tenant_id', DEFAULT_TENANT_ID)` 提取
  - `LoginUser.get_login_user_from_ws(websocket, auth_jwt, t)`: 同上
  - `LoginUser.get_admin_user` / `get_admin_user_from_ws`: 同步传递 tenant_id
  - `UserPayload`（继承 LoginUser）自动获得 `tenant_id` 字段，无需额外修改
  **测试**: `test_tenant_auth.py` —
  - `test_jwt_encode_with_tenant_id` — 编码含 tenant_id 的 JWT，解码验证 → AC-07
  - `test_jwt_decode_old_token_fallback` — 解码不含 tenant_id 的旧 JWT，tenant_id 默认为 1 → AC-07
  - `test_login_user_has_tenant_id` — 构造 LoginUser 后访问 tenant_id → AC-08
  - `test_init_login_user_passes_tenant_id` — init_login_user 传入 tenant_id=2，验证实例中值为 2
  **覆盖 AC**: AC-07, AC-08
  **依赖**: T003

- [x] **T006**: HTTP/WS 中间件 — 租户上下文注入
  **文件（修改）**:
  - `src/backend/bisheng/utils/http_middleware.py`
  **逻辑**:
  - `CustomMiddleware.dispatch` 中，在 `trace_id_var.set(trace_id)` 之后：
    1. 尝试从 `request.cookies.get("access_token_cookie")` 获取 JWT token
    2. 如果有 token：`AuthJwt(req=request).decode_jwt_token(token)` → 提取 `subject.get('tenant_id', DEFAULT_TENANT_ID)`
    3. 调用 `set_current_tenant_id(tenant_id)`
    4. 如果无 token 且 `multi_tenant.enabled=false`：`set_current_tenant_id(DEFAULT_TENANT_ID)`
    5. 如果无 token 且 `multi_tenant.enabled=true`：不设 ContextVar（公开端点如 /health 不需要）
    6. JWT 解析异常时静默跳过（认证失败由 endpoint 层的 Depends 处理）
  - `WebSocketLoggingMiddleware.__call__` 中，在 `trace_id_var.set(trace_id)` 之后：
    1. 从 `scope.get("headers")` 或 cookies 提取 JWT token
    2. 同样解析 tenant_id 并设置 ContextVar
  **测试降级**: 中间件依赖完整的 ASGI 栈，集成测试在 T009 后通过端到端手动验证确认
  **手动验证**:
  - 启动后端，登录后在浏览器中发起 API 请求
  - 在 endpoint handler 中打断点验证 `get_current_tenant_id()` 返回值
  - 建立 WebSocket 连接，验证 ContextVar 正确设置
  **覆盖 AC**: AC-07（运行时验证）
  **依赖**: T003, T005

- [x] **T007**: Celery 租户上下文传播
  **文件（新建）**:
  - `src/backend/bisheng/worker/tenant_context.py` — 信号处理函数
  - `src/backend/test/test_celery_tenant.py` — mock 信号测试
  **文件（修改）**:
  - `src/backend/bisheng/worker/main.py` — 导入 tenant_context 模块以触发信号注册
  **逻辑**:
  - `@before_task_publish.connect` 信号:
    ```python
    def inject_tenant_header(headers=None, **kwargs):
        tid = get_current_tenant_id()
        if tid is not None and headers is not None:
            headers['tenant_id'] = tid
    ```
  - `@task_prerun.connect` 信号:
    ```python
    def restore_tenant_context(sender=None, **kwargs):
        request = sender.request
        tenant_id = (getattr(request, 'headers', None) or {}).get('tenant_id')
        if tenant_id is not None:
            set_current_tenant_id(int(tenant_id))
        else:
            set_current_tenant_id(DEFAULT_TENANT_ID)
    ```
  - `@task_postrun.connect` 信号: reset ContextVar 避免线程池复用时泄漏
  - 在 `worker/main.py` 添加 `import bisheng.worker.tenant_context` 确保信号注册
  **测试**: `test_celery_tenant.py` —
  - `test_inject_tenant_header` — mock headers dict，设置 ContextVar=2，调用信号函数，验证 headers['tenant_id']=2 → AC-09
  - `test_restore_tenant_context` — mock sender.request.headers={'tenant_id': 3}，调用信号函数，验证 get_current_tenant_id()=3 → AC-09
  - `test_no_header_uses_default` — headers 中无 tenant_id，验证回退到 DEFAULT_TENANT_ID → AC-09
  - `test_postrun_resets_context` — 执行后 ContextVar 被 reset
  **覆盖 AC**: AC-09
  **依赖**: T003

---

### 存储与迁移

- [x] **T008**: 存储前缀工具函数
  **文件（新建）**:
  - `src/backend/bisheng/core/storage/tenant_storage.py` — 前缀工具函数
  - `src/backend/test/test_tenant_storage.py` — 前缀函数单元测试
  **逻辑**:
  - `get_minio_prefix(tenant_id: int, tenant_code: str) -> str`: 默认租户→`""`，新租户→`"tenant_{tenant_code}/"`
  - `get_milvus_collection_prefix(tenant_id: int) -> str`: 默认→`""`，新→`"t{tenant_id}_"`
  - `get_es_index_prefix(tenant_id: int) -> str`: 默认→`""`，新→`"t{tenant_id}_"`
  - `get_redis_key_prefix(tenant_id: int) -> str`: 默认→`""`，新→`"t:{tenant_id}:"`
  **测试**: `test_tenant_storage.py` —
  - `test_minio_prefix_default_tenant` — get_minio_prefix(1, "default") == "" → AC-10
  - `test_minio_prefix_new_tenant` — get_minio_prefix(2, "cofco") == "tenant_cofco/" → AC-10
  - `test_milvus_prefix_default` — get_milvus_collection_prefix(1) == "" → AC-10
  - `test_milvus_prefix_new` — get_milvus_collection_prefix(2) == "t2_" → AC-10
  - `test_es_prefix_default` — get_es_index_prefix(1) == "" → AC-10
  - `test_es_prefix_new` — get_es_index_prefix(3) == "t3_" → AC-10
  - `test_redis_prefix_default` — get_redis_key_prefix(1) == "" → AC-10
  - `test_redis_prefix_new` — get_redis_key_prefix(2) == "t:2:" → AC-10
  **覆盖 AC**: AC-10
  **依赖**: T003

- [x] **T009**: DDL 迁移 + 默认租户初始化 + config.yaml
  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f001_multi_tenant_{hash}.py` — Alembic 迁移脚本
  **文件（修改）**:
  - `src/backend/bisheng/common/init_data.py` — `init_default_data()` 中调用 `init_default_tenant()`
  - `src/backend/bisheng/config.yaml` — 添加 `multi_tenant:` 配置节（enabled: false, default_tenant_code: "default"）
  **逻辑**:
  - **DDL upgrade**:
    1. CREATE TABLE `tenant`（按 spec §5 DDL）
    2. CREATE TABLE `user_tenant`（按 spec §5 DDL）
    3. 对 23+ 业务表: `ALTER TABLE {table} ADD COLUMN tenant_id INT UNSIGNED NOT NULL DEFAULT 1; ALTER TABLE {table} ADD INDEX idx_tenant_id (tenant_id);`
    4. 业务表清单: flow, flow_version, assistant, assistant_link, knowledge, gpts_tools, channel, t_report, evaluation, dataset, session, chat_message, tag, tag_link, template, t_variable_value, `group`, role, role_access, audit_log, mark_task, mark_record, mark_app_user, invite_code
    5. INSERT 默认租户: `(id=1, tenant_code='default', tenant_name='Default Tenant', status='active')`
    6. 回填 user_tenant: `INSERT INTO user_tenant (user_id, tenant_id, is_default, status) SELECT user_id, 1, 1, 'active' FROM user`
  - **DDL downgrade**（回滚方案）:
    1. 对 23+ 业务表: `ALTER TABLE {table} DROP INDEX idx_tenant_id; ALTER TABLE {table} DROP COLUMN tenant_id;`
    2. DROP TABLE `user_tenant`
    3. DROP TABLE `tenant`
    - 注意：回滚会丢失新租户数据（tenant_id>1 的记录的 tenant_id 信息不可恢复），仅适用于升级失败时紧急回退
  - **init_default_tenant()** (`init_data.py`):
    - 幂等检查：如果 `Tenant(id=1)` 不存在则创建
    - 检查 user 表中无 user_tenant 关联的用户，补充 user_tenant(tenant_id=1) 记录
    - 在 `init_default_data()` 函数的表创建之后、角色初始化之前调用
  **手动验证**:
  - 在远程服务器 192.168.106.114 上运行迁移脚本
  - 验证 `SELECT * FROM tenant` 返回默认租户 → AC-02
  - 验证 `SELECT tenant_id FROM flow LIMIT 5` 全部为 1 → AC-03
  - 验证 `SELECT COUNT(*) FROM user_tenant` 等于 user 表总数 → AC-02
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T002, T003, T004

---

## AC 覆盖追溯

| AC | 覆盖任务 |
|----|---------|
| AC-01 | T002（ORM 模型定义 + DAO 测试） |
| AC-02 | T009（默认租户初始化 + DDL 迁移） |
| AC-03 | T009（DDL 迁移 23+ 表） |
| AC-04 | T004（do_orm_execute 事件钩子） |
| AC-05 | T004（before_flush 事件钩子） |
| AC-06 | T003（bypass 机制）+ T004（集成验证） |
| AC-07 | T005（JWT 编解码）+ T006（中间件运行时） |
| AC-08 | T005（LoginUser.tenant_id 字段） |
| AC-09 | T007（Celery 信号） |
| AC-10 | T008（存储前缀函数） |
| AC-11 | T004（enabled=false/true 行为分支） |

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

1. **DDL 迁移表数量扩展**: spec 提到 "23+ 业务表"，实际迁移覆盖了 46 张表（包含 DDD 模块中的 knowledge/tool/channel/finetune/linsight/llm/message/share_link 等），遵循 INV-1 "所有业务表必须含 tenant_id"
2. **T006 测试降级**: HTTP/WS 中间件测试降级为手动验证（需要完整 ASGI 栈），符合 tasks.md 预期
3. **tenant_filter 事件注册**: 采用 Session 类级别全局注册（而非 Engine 级别），更简洁且与 SQLModel 兼容性更好
4. **_extract_tenant_id_from_token**: 在 http_middleware.py 中提取了一个辅助函数，避免在 HTTP 和 WS 两处重复 JWT 解码逻辑
