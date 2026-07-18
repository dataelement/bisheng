# Tasks: 测试基础设施

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 14 项检查通过（6 PASS + 8 N/A） |
| tasks.md | ✅ 已拆解 | 21 项检查通过（1 low 跳过），9 个任务 |
| 实现 | ✅ 已完成 | 9 / 9 完成，50/50 后端测试通过，2/2 前端测试通过 |

---

## 开发模式

**特殊模式（测试基础设施自身）**：
- F000 本身就是测试基础设施，不适用标准 Test-First 模式
- 验证方式：每个任务完成后运行 `pytest --collect-only` 确认无 import 错误 + 最终 T008 的 smoke test 验证全部 fixture
- F001 回归保护：每个修改 conftest.py 的任务必须确认 `pytest test/test_tenant_*.py` 全部通过

**前端 Test-Alongside**：
- T009 搭建 Vitest 框架 + smoke test，一步到位

**自包含任务**：每个任务内联文件、逻辑、验证方式，实现阶段不需要回读 spec.md。

---

## 依赖图

```
T001 (pytest 配置 + 依赖)
  │
  ├── T002 (import chain 预 mock)
  │     │
  │     ├── T004 (DB fixtures) ─── T006 (TestClient)
  │     │                                │
  │     └── T005 (Redis/MinIO/FGA mock)──┘
  │
  └── T003 (SQLite DDL 定义)
        │
        ├── T004 (DB fixtures)
        │
        └── T007 (工厂函数)

T004 + T005 + T006 + T007 ──→ T008 (smoke test)

T009 (前端 Vitest) ── 独立，可与后端并行
```

---

## Tasks

### 基础设施配置

- [x] **T001**: pytest 配置 + 测试依赖声明
  **文件（修改）**:
  - `src/backend/pyproject.toml` — 添加 `[tool.pytest.ini_options]` + `[project.optional-dependencies].test`
  **逻辑**:
  - `[tool.pytest.ini_options]`:
    - `testpaths = ["test"]`
    - `python_files = ["test_*.py"]`
    - `asyncio_mode = "auto"`（支持异步 DAO 测试）
    - `markers`: `e2e`（需要运行中的后端）、`slow`（>5s 的测试）
    - `filterwarnings`: ignore SQLAlchemy DeprecationWarning
  - `[project.optional-dependencies].test`:
    - `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-cov>=5.0`
    - `fakeredis[lua]>=2.21`（Redis mock）
    - `httpx>=0.27`（已在 main deps 中，此处确认可用）
  - 安装验证：`uv sync --extra test`
  **验证**: `cd src/backend && pytest --collect-only` 无报错，收集到 F001 现有测试
  **覆盖 AC**: AC-01（部分，配置层面）
  **依赖**: 无

---

### 后端 fixture 搭建

- [x] **T002**: Import chain 预 mock 集中化
  **文件（新建）**:
  - `src/backend/test/fixtures/__init__.py` — fixture 子包入口（空文件）
  - `src/backend/test/fixtures/mock_services.py` — 集中化预 mock 模块
  **逻辑**:
  - 从 F001 的 `test_tenant_filter.py` 和 `test_tenant_auth.py` 顶部提取 `sys.modules` 预 mock 列表，合并去重
  - 定义 `PREMOCK_MODULES` 常量列表（包含已知会引发循环依赖的模块路径）：
    - `bisheng.common.services` 及子模块（config_service, telemetry）
    - `bisheng.database.models.*`（user_group, role_access, group, role 等）
    - `bisheng.database.constants`
    - `bisheng.user.domain.models.*`（user_role, user）
    - `bisheng.common.errcode.http_error`
    - `bisheng.common.exceptions.auth`
  - 提供 `premock_import_chain()` 函数：遍历列表，对未在 `sys.modules` 中的模块注入 MagicMock
  - 提供 `create_mock_settings(multi_tenant_enabled=False, ...)` 工厂函数：返回配置好的 MagicMock
  - **关键约束**: 不使用 autouse fixture 调用 premock（会干扰 F001 已有的自包含 pre-mock），而是在 conftest.py 顶部以模块级代码调用
  **验证**: `pytest test/test_tenant_*.py -v` 全部 PASSED（F001 回归）
  **覆盖 AC**: AC-01（import chain 兼容）
  **依赖**: T001

- [x] **T003**: SQLite 表定义集中管理
  **文件（新建）**:
  - `src/backend/test/fixtures/table_definitions.py` — SQLite 兼容 DDL 定义
  **逻辑**:
  - 为每张表定义一个 SQL 字符串常量（`TABLE_TENANT`, `TABLE_USER_TENANT`, `TABLE_USER`, ...）
  - 已有表（从 F001 `test_tenant_dao.py:24-53` 提取）：`tenant`, `user_tenant`
  - 新增表（为 F002-F008 准备，参照生产 ORM 定义转写为 SQLite 兼容语法）：
    - `user` — id, user_name, password, role_id, tenant_id, ...
    - `department` — id, tenant_id, name, parent_id, path, level, ...
    - `user_department` — id, user_id, department_id, is_primary, ...
    - `user_group`（即 `group` 表）— id, tenant_id, group_name, ...
    - `role` — id, role_name, role_type, tenant_id, ...
    - `role_access` — id, role_id, access_type, access_id, ...
    - `flow` — id, tenant_id, name, flow_type, status, ...
    - `knowledge` — id, tenant_id, name, model, ...
  - DDL 转写规则：`AUTO_INCREMENT` → `AUTOINCREMENT`，`ON UPDATE CURRENT_TIMESTAMP` → 省略，`ENUM` → `VARCHAR`，`INT UNSIGNED` → `INTEGER`
  - 提供 `create_all_tables(engine)` 建全部表
  - 提供 `create_tables(engine, *table_names)` 选择性建表（`table_names` 为字符串参数如 `'tenant'`, `'user'`）
  - 表名到 DDL 的映射用 `TABLE_DEFINITIONS: dict[str, str]`
  **验证**: 在 Python REPL 中 `create_all_tables(engine)` 无报错，`create_tables(engine, 'tenant', 'department')` 只建 2 张表
  **覆盖 AC**: AC-02（部分，DDL 层面）
  **依赖**: T001

- [x] **T004**: DB fixtures（同步 + 异步）
  **文件（修改）**:
  - `src/backend/test/conftest.py` — 扩展，新增 DB 相关 fixture
  **逻辑**:
  - 在文件顶部（fixture 定义之前）调用 `premock_import_chain()`（模块级代码，非 fixture）
  - 保留现有 `mock_settings` fixture 不变
  - 新增 fixture：
    - `db_engine`（scope=session）：`create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)` → `create_all_tables(engine)` → yield → `engine.dispose()`
    - `db_session`（scope=function）：从 `db_engine` 创建 connection → `begin()` → `Session(bind=connection)` → yield → `rollback()` → `close()`
    - `async_db_engine`（scope=session）：`create_async_engine('sqlite+aiosqlite://', ...)` → 异步建表 → yield → dispose
    - `async_db_session`（scope=function）：异步连接 + 事务 + AsyncSession → yield → rollback
    - `tenant_context`（scope=function）：接受 `tenant_id` 参数（默认 1），设置 `current_tenant_id` ContextVar，yield 后 reset
    - `bypass_tenant`（scope=function）：进入 `bypass_tenant_filter()` 上下文
  - **兼容性保障**: F001 测试文件自带的 `dao_engine`/`session`/`filter_engine` fixture 仍然独立工作，conftest 的 `db_engine`/`db_session` 只在显式声明时使用
  **验证**:
  - `pytest test/test_tenant_*.py -v` 全部 PASSED（F001 回归）
  - 编写一个临时测试验证 `db_session` 能做 CRUD
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T002, T003

- [x] **T005**: 外部服务 mock（Redis / MinIO / OpenFGA）
  **文件（新建）**:
  - `src/backend/test/fixtures/mock_openfga.py` — InMemoryOpenFGAClient
  **文件（修改）**:
  - `src/backend/test/conftest.py` — 新增 `mock_redis`, `mock_minio`, `mock_openfga` fixture
  **逻辑**:
  - `mock_redis`（scope=function）：返回 `fakeredis.FakeRedis()` 实例，每个测试自动 `flushall()`
  - `mock_minio`（scope=function）：返回 `MagicMock()` 配置 `put_object`/`get_object`/`remove_object` 方法返回值
  - `mock_openfga`（scope=function）：返回 `InMemoryOpenFGAClient()` 实例，每个测试自动 `reset()`
  - **InMemoryOpenFGAClient 实现**:
    - 内部存储 `_tuples: set[tuple[str, str, str]]`（object, relation, user 三元组）
    - `write_tuples(writes)` — 将 `[{"object": ..., "relation": ..., "user": ...}]` 添加到集合
    - `delete_tuples(deletes)` — 从集合移除
    - `check(user, relation, object)` — 直接匹配三元组是否存在（不实现 userset 展开）
    - `list_objects(user, relation, type)` — 返回 user 对 type 类型有 relation 关系的所有 object
    - `list_users(relation, object, user_type)` — 返回对 object 有 relation 关系的所有 user_type 类型用户
    - `assert_tuple_exists(user, relation, object)` — 断言元组存在，不存在时 raise AssertionError 含详细信息
    - `assert_tuple_count(expected)` — 断言元组总数
    - `reset()` — 清空 `_tuples`
    - 所有 async 方法内部无真正异步操作，仅 `async def` 签名以匹配未来 F004 的异步 client 接口
  **验证**: 单独 `import test.fixtures.mock_openfga` 无报错；在临时测试中验证 write + check 基本流程
  **覆盖 AC**: AC-04, AC-05, AC-06
  **依赖**: T002

- [x] **T006**: TestClient fixture
  **文件（修改）**:
  - `src/backend/test/conftest.py` — 新增 `test_client` fixture
  **逻辑**:
  - `test_client`（scope=function）：
    1. 导入 `bisheng.main:create_app` 创建 FastAPI app（或直接导入 `app`）
    2. 通过 `app.dependency_overrides` 覆盖关键依赖：
       - `UserPayload.get_login_user` → 返回固定的 mock UserPayload（user_id=1, tenant_id=1）
       - 数据库 session → 使用 `db_session` fixture 的 session
    3. 使用 `starlette.testclient.TestClient(app)` 创建客户端
    4. yield client
    5. teardown：清空 `dependency_overrides`
  - **已知限制**: 由于 lifespan 会初始化 DB/Redis/MinIO 等真实连接，TestClient 需要使用 `raise_server_exceptions=False` 或 mock 掉 lifespan。具体策略在实现时根据 `create_app` 的 lifespan 实现决定
  - **测试降级**: 如果 mock lifespan 复杂度过高，降级为仅验证 `/health` 端点（不需要 DB 连接），并在偏差记录中说明
  **验证**: `test_client.get("/health")` 返回 200
  **覆盖 AC**: AC-07
  **依赖**: T004, T005

- [x] **T007**: Test data 工厂函数
  **文件（新建）**:
  - `src/backend/test/fixtures/factories.py` — 工厂函数
  **逻辑**:
  - 纯函数（非 fixture），接受 session 参数，创建记录并返回：
    - `create_tenant(session, code='test', name='Test Tenant', **kwargs) -> dict` — INSERT tenant 记录，返回包含 id 的 dict
    - `create_user_tenant(session, user_id, tenant_id, is_default=1) -> dict` — INSERT user_tenant 记录
    - `create_test_user(session, user_name='testuser', tenant_id=1, **kwargs) -> dict` — INSERT user 记录
  - 返回 dict 而非 ORM 对象，避免导入生产 ORM 模型引发 import chain 问题
  - 使用 `sqlalchemy.text()` 执行 raw SQL INSERT，不依赖 SQLModel
  - 每个函数有合理的默认值，调用方只需覆盖关心的字段
  **验证**: 在临时测试中 `create_tenant(session)` 后 `SELECT * FROM tenant` 返回一条记录
  **覆盖 AC**: AC-08
  **依赖**: T003

---

### 验证与前端

- [x] **T008**: 基础设施 smoke test
  **文件（新建）**:
  - `src/backend/test/test_infrastructure_smoke.py` — smoke test
  **逻辑**:
  - ~10 个测试，验证 F000 所有 fixture 和工具正常工作：
    - `test_db_engine_creates_tables` — `db_engine` fixture 建表成功，`PRAGMA table_info(tenant)` 返回列信息
    - `test_db_session_crud` — 通过 `db_session` INSERT + SELECT 一条 tenant 记录
    - `test_db_session_rollback_isolation` — 一个测试中 INSERT 数据，另一个测试看不到（ROLLBACK 生效）
    - `test_async_db_session_crud` — 通过 `async_db_session` 异步 INSERT + SELECT
    - `test_mock_redis_basic_ops` — `mock_redis.set("key", "val")` 后 `get("key")` 返回 `b"val"`
    - `test_mock_minio_callable` — `mock_minio.put_object(...)` 不抛异常
    - `test_mock_openfga_write_and_check` — `write_tuples` 后 `check` 返回 True，未写入的返回 False
    - `test_mock_openfga_list_objects` — `write_tuples` 后 `list_objects` 返回正确列表
    - `test_mock_openfga_assert_helpers` — `assert_tuple_exists` 正确断言、`assert_tuple_count` 正确计数
    - `test_factory_create_tenant` — `create_tenant(session)` 创建记录，SELECT 验证字段值
    - `test_test_client_health`（条件性）— 如果 T006 的 TestClient 可用，验证 `/health` 返回 200
  **验证**: `pytest test/test_infrastructure_smoke.py -v` 全部 PASSED
  **覆盖 AC**: AC-09, AC-10（通过同时运行 `pytest test/test_tenant_*.py` 验证回归）
  **依赖**: T004, T005, T006, T007

- [x] **T009**: 前端 Platform Vitest 配置
  **文件（修改）**:
  - `src/frontend/platform/package.json` — 添加 devDependencies + scripts
  **文件（新建）**:
  - `src/frontend/platform/vitest.config.ts` — Vitest 配置
  - `src/frontend/platform/src/test/setup.ts` — 测试 setup
  - `src/frontend/platform/src/test/test-utils.tsx` — 自定义 render
  - `src/frontend/platform/src/test/smoke.test.ts` — smoke test
  **逻辑**:
  - `package.json` devDependencies 添加：`vitest@^3.0`, `@testing-library/react@^16.0`, `@testing-library/jest-dom@^6.0`, `@testing-library/user-event@^14.0`, `@vitest/coverage-v8@^3.0`, `jsdom@^25.0`
  - `package.json` scripts 添加：`"test": "vitest run"`, `"test:watch": "vitest"`, `"test:coverage": "vitest run --coverage"`
  - `vitest.config.ts`：`mergeConfig(viteConfig, defineConfig({ test: { globals: true, environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], include: ['src/**/*.{test,spec}.{ts,tsx}'] } }))`
  - `setup.ts`：`import '@testing-library/jest-dom'` + i18n mock（参考 Client 的 `test/setupTests.js` 模式）
  - `test-utils.tsx`：自定义 `render` 函数包裹 `BrowserRouter`，re-export `@testing-library/react` 全部导出
  - `smoke.test.ts`：1 个基础测试验证 Vitest 运行正常
  **验证**: `cd src/frontend/platform && npm install && npm test` smoke test PASSED
  **覆盖 AC**: AC-11
  **依赖**: 无（与后端任务独立）

---

## AC 覆盖追溯

| AC | 覆盖任务 |
|----|---------|
| AC-01 | T001（pytest 配置）+ T002（import chain 兼容） |
| AC-02 | T003（DDL 定义）+ T004（db_session fixture） |
| AC-03 | T004（async_db_session fixture） |
| AC-04 | T005（mock_redis fixture） |
| AC-05 | T005（mock_minio fixture） |
| AC-06 | T005（mock_openfga fixture） |
| AC-07 | T006（test_client fixture） |
| AC-08 | T007（create_tenant 工厂函数） |
| AC-09 | T008（smoke test 全部通过） |
| AC-10 | T008（F001 回归验证） |
| AC-11 | T009（Vitest smoke test） |

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- _（待实现后填写）_
