# Feature: 测试基础设施

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: 无（基础设施 Feature）
**优先级**: P0
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 后端 pytest 配置（`pyproject.toml` `[tool.pytest.ini_options]` + test markers + 测试依赖声明）
- 共享 conftest.py（DB engine/session fixture、tenant context fixture、TestClient fixture）
- SQLite 兼容 DDL 集中定义（`table_definitions.py`，覆盖 tenant/user_tenant + F002-F008 常用表）
- Import chain 预 mock 集中化（从 F001 各文件的 `sys.modules` 模式提取合并到共享模块）
- 外部服务 mock fixture（Redis → fakeredis、MinIO → MagicMock、OpenFGA → InMemoryOpenFGAClient）
- Test data 工厂函数（`create_tenant()`、`create_user_tenant()`、`create_test_user()` 等）
- 基础设施自身的 smoke test（~10 个用例，验证 fixture 正确工作）
- 前端 Platform Vitest 基础配置 + test-utils + smoke test

**OUT**:
- 具体业务测试用例（各 Feature 自写）
- 浏览器 E2E 测试框架（Playwright/Cypress 等）
- F001 现有测试的迁移/重构（F001 测试自包含且稳定，保持原样）
- Client 前端测试框架（已有 Jest 配置，不在 F000 范围）
- CI/CD 测试步骤（后续独立处理）

**关联不变量**: 无直接关联（F000 提供的 fixture 间接支撑所有 INV 的测试覆盖）

---

## 1. 概述与用户故事

F000 是 v2.5.0 所有 Feature 的测试地基。它提供开箱即用的 pytest fixture、mock 基础和前端测试框架配置，使 F001~F010 的开发者无需重复搭建测试环境。

F001 已内联搭建了一套最小测试基础（SQLite in-memory + conftest.py + 预 mock 模式），但每个测试文件各自维护独立的 engine/session/pre-mock，不可复用。F000 将这些模式正式化为共享基础设施，并为后续 Feature（特别是 F004-rebac-core 所需的 OpenFGA mock）提前准备。

**用户故事 1**:
作为 **BiSheng 后端开发者**，
我希望 **在新 Feature 的测试文件中直接使用 `db_session`、`mock_redis`、`mock_openfga` 等 fixture**，
以便 **不必每次从零搭建 SQLite engine、手动管理 import chain pre-mock、编写事务回滚逻辑**。

**用户故事 2**:
作为 **BiSheng 后端开发者**，
我希望 **通过 `create_tenant(session)`、`create_test_user(session)` 等工厂函数快速构造测试数据**，
以便 **专注于业务逻辑测试而非测试数据准备**。

**用户故事 3**:
作为 **BiSheng 前端开发者**，
我希望 **在 Platform 项目中运行 `npm test` 即可执行 Vitest 测试**，
以便 **F007（资源权限 UI）等前端 Feature 有自动化测试基础可用**。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 开发者 | 在 `src/backend` 下执行 `pytest --collect-only` | 无 import 错误，正确收集所有测试文件（含 F001 现有测试） |
| AC-02 | 开发者 | 在测试函数签名中声明 `db_session` 参数 | 获得一个已建表的 SQLite in-memory Session，测试结束后自动 ROLLBACK（每个测试独立） |
| AC-03 | 开发者 | 在测试函数签名中声明 `async_db_session` 参数 | 获得一个异步 SQLite Session，支持测试异步 DAO 方法（`aget_xxx`） |
| AC-04 | 开发者 | 在测试函数签名中声明 `mock_redis` 参数 | 获得一个 fakeredis 实例，支持 `set`/`get`/`delete` 等基本命令，无需真实 Redis |
| AC-05 | 开发者 | 在测试函数签名中声明 `mock_minio` 参数 | 获得一个 MagicMock 对象，提供 `put_object`/`get_object`/`remove_object` 方法 |
| AC-06 | 开发者 | 在测试函数签名中声明 `mock_openfga` 参数 | 获得一个 `InMemoryOpenFGAClient` 实例，支持 `write_tuples`/`check`/`list_objects`/`list_users` + 测试断言辅助方法 |
| AC-07 | 开发者 | 在测试函数签名中声明 `test_client` 参数 | 获得一个绑定 FastAPI app 的 TestClient，可直接发送 HTTP 请求到 API 端点，DB/Redis/MinIO 已被 mock |
| AC-08 | 开发者 | 调用 `create_tenant(session, code="test")` | 在测试 DB 中创建一条 tenant 记录并返回 Tenant 对象 |
| AC-09 | 开发者 | 执行 `pytest test/test_infrastructure_smoke.py -v` | ~10 个 smoke test 全部 PASSED，验证所有 fixture 正确工作 |
| AC-10 | 开发者 | 执行 `pytest test/test_tenant_*.py -v` | F001 现有的 43+ 测试全部 PASSED（回归无损） |
| AC-11 | 前端开发者 | 在 `src/frontend/platform` 下执行 `npm test` | Vitest smoke test PASSED，test-utils 中的 `render` 函数正常工作 |

---

## 3. 边界情况

- 当 **F001 现有测试文件自带 engine/session/pre-mock** 时，F000 的共享 conftest 不得干扰其独立运行。conftest 中的 session-scoped autouse fixture 必须兼容 F001 的自包含模式
- 当 **新 Feature 只需少量表**（如只需 tenant + department）时，开发者可以使用 `create_tables(engine, 'tenant', 'department')` 选择性建表，无需加载全部 DDL
- 当 **import chain 引发新的循环依赖**（后续 Feature 引入新模块）时，开发者需在 `mock_services.py` 的 `PREMOCK_MODULES` 列表中追加模块路径
- 当 **OpenFGA client 接口发生变化**（F004 定义真实 client 后）时，`InMemoryOpenFGAClient` 需同步更新以匹配接口签名
- **不支持**: 真实 MySQL 测试（需要 MySQL 特有行为的测试使用 E2E 方式）
- **不支持**: 异步 TestClient（当前只提供同步 TestClient，异步 API 测试通过异步 DB session 间接覆盖）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 测试数据库引擎 | A: SQLite in-memory / B: test MySQL 实例 | 选 A | F001 已验证 43+ 测试稳定通过；零外部依赖；亚毫秒级速度；MySQL 特有行为由 E2E 覆盖。SQLite 不兼容的 DDL（如 `ON UPDATE CURRENT_TIMESTAMP`）通过 `table_definitions.py` 集中转写 |
| AD-02 | OpenFGA mock 方式 | A: 纯 Python 内存 mock / B: Docker 测试容器 / C: 留给 F004 | 选 A | OpenFGA client（`core/openfga/`）尚未实现（F004 负责），但 F000 可预定义 mock 接口让后续 Feature 有 fixture 可用。内存 mock 零延迟零依赖，F004 可按需增强。不实现完整 Zanzibar 算法，仅支持直接元组匹配 |
| AD-03 | 前端测试框架 | A: Vitest（Platform）/ B: Jest（统一） | 选 A | Platform 使用 Vite 构建，Vitest 天然共享 `vite.config.mts`（路径别名、插件等）。Client 已有 Jest 配置但不在 F000 范围 |
| AD-04 | F001 测试回迁 | A: 不回迁 / B: 统一迁移到共享 fixture | 选 A | F001 测试稳定且自包含，迁移有回归风险无业务价值。新 Feature 使用共享 fixture，F001 保持原样 |

---

## 5. 数据库 & Domain 模型

N/A — F000 不创建 ORM 模型。`table_definitions.py` 提供 SQLite 兼容 DDL 用于测试建表，但不是生产代码。

### SQLite 兼容 DDL 定义（test-only）

`table_definitions.py` 为每张需要测试的表提供 SQLite 兼容的 `CREATE TABLE` SQL。这些定义从 F001 测试文件提取并扩展，覆盖：

**已有**（从 F001 提取）：`tenant`、`user_tenant`

**新增**（为 F002-F008 准备）：`user`、`department`、`user_department`、`user_group`、`role`、`role_access`、`flow`、`knowledge`

**设计规则**：
- 每张表 DDL 是独立 SQL 字符串常量
- `create_all_tables(engine)` 建全部表，`create_tables(engine, *names)` 选择性建表
- 不含 MySQL 特有语法（`AUTO_INCREMENT` → `AUTOINCREMENT`，`ON UPDATE CURRENT_TIMESTAMP` → 省略）
- 保持与生产 ORM 定义的字段/类型/约束一致（除上述兼容项）

---

## 6. API 契约

N/A — F000 不新增 API 端点。

---

## 7. Service 层逻辑

N/A — F000 是纯测试基础设施 Feature。核心交付物是 pytest fixture 和配置，不含业务逻辑。

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| pytest 配置 | `pyproject.toml` `[tool.pytest.ini_options]` | testpaths、markers（e2e/slow）、asyncio_mode、filterwarnings |
| 预 mock 注册 | `test/fixtures/mock_services.py` | 集中 `sys.modules` 预 mock，解决 import chain 循环依赖 |
| 表定义 | `test/fixtures/table_definitions.py` | SQLite 兼容 DDL，支持全量/选择性建表 |
| DB fixture | `test/conftest.py` | `db_engine`（session-scoped）、`db_session`（function-scoped, ROLLBACK 隔离） |
| 异步 DB fixture | `test/conftest.py` | `async_db_engine`、`async_db_session` |
| Redis mock | `test/conftest.py` | `mock_redis` → fakeredis 实例 |
| MinIO mock | `test/conftest.py` | `mock_minio` → MagicMock |
| OpenFGA mock | `test/fixtures/mock_openfga.py` | `InMemoryOpenFGAClient`：dict 存储元组，支持 write/check/list + 断言辅助 |
| TestClient | `test/conftest.py` | `test_client` → FastAPI TestClient，依赖已 override |
| 工厂函数 | `test/fixtures/factories.py` | `create_tenant()`、`create_user_tenant()`、`create_test_user()` |
| Smoke test | `test/test_infrastructure_smoke.py` | 验证所有 fixture 正确工作 |

### InMemoryOpenFGAClient 接口

```python
class InMemoryOpenFGAClient:
    """纯内存 OpenFGA mock。存储元组为 (object, relation, user) 三元组。
    
    不实现 userset 展开（transitive resolution）。
    F004 引入真实 client 后可增强此 mock 以匹配接口。
    """
    
    async def write_tuples(self, writes: list[dict]) -> None: ...
    async def delete_tuples(self, deletes: list[dict]) -> None: ...
    async def check(self, user: str, relation: str, object: str) -> bool: ...
    async def list_objects(self, user: str, relation: str, type: str) -> list[str]: ...
    async def list_users(self, relation: str, object: str, user_type: str) -> list[str]: ...
    
    # 测试辅助
    def assert_tuple_exists(self, user: str, relation: str, object: str) -> None: ...
    def assert_tuple_count(self, expected: int) -> None: ...
    def reset(self) -> None: ...
```

---

## 8. 前端设计

### 8.1 Platform 前端

> 路径：`src/frontend/platform/`

F000 不创建业务页面，仅搭建 Vitest 测试框架：

**配置**：`vitest.config.ts` 通过 `mergeConfig` 复用 `vite.config.mts`（继承路径别名 `@/` → `src/`、react-swc 插件等）

**测试工具**：`src/test/test-utils.tsx` 提供自定义 `render` 函数，包裹 `BrowserRouter` 等公共 Provider

**Setup**：`src/test/setup.ts` 配置 `@testing-library/jest-dom` matchers + i18n mock

**Smoke test**：`src/test/smoke.test.ts` 验证 Vitest 基础设施可运行

### 8.2 Client 前端

N/A — Client 已有 Jest 配置，不在 F000 范围。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/test/fixtures/__init__.py` | fixture 子包入口 |
| `src/backend/test/fixtures/table_definitions.py` | SQLite 兼容 DDL 集中定义（10 张表） |
| `src/backend/test/fixtures/mock_services.py` | import chain 预 mock 集中化 + 服务 mock 工厂函数 |
| `src/backend/test/fixtures/mock_openfga.py` | InMemoryOpenFGAClient 内存 mock |
| `src/backend/test/fixtures/factories.py` | test data 工厂函数 |
| `src/backend/test/test_infrastructure_smoke.py` | 基础设施 smoke test（~10 用例） |
| `src/frontend/platform/vitest.config.ts` | Vitest 配置（mergeConfig from vite.config.mts） |
| `src/frontend/platform/src/test/setup.ts` | 测试 setup（jest-dom matchers + i18n mock） |
| `src/frontend/platform/src/test/test-utils.tsx` | 自定义 render + Provider 包裹 |
| `src/frontend/platform/src/test/smoke.test.ts` | 前端 smoke test |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/pyproject.toml` | 添加 `[tool.pytest.ini_options]` + `[project.optional-dependencies].test` |
| `src/backend/test/conftest.py` | 扩展为完整共享 fixture（保留现有 `mock_settings`，新增 `db_engine`/`db_session`/`mock_redis`/`mock_minio`/`mock_openfga`/`test_client`/`tenant_context`/`bypass_tenant` 等） |
| `src/frontend/platform/package.json` | 添加 vitest + @testing-library devDependencies + test scripts |

---

## 10. 非功能要求

- **性能**: 全量非 E2E 测试套件（含 F001 43+ 现有测试 + F000 smoke test）应在 30 秒内完成
- **零外部依赖**: 执行 `pytest test/ -m "not e2e"` 不需要 MySQL、Redis、MinIO、Milvus、ES、OpenFGA 等外部服务
- **兼容性**: F001 现有 6 个测试文件（test_tenant_*.py）全部保持 PASSED，不因共享 conftest 引入回归
- **可扩展性**: 后续 Feature 可在 `table_definitions.py` 追加表、在 `mock_services.py` 追加预 mock 模块、在 `factories.py` 追加工厂函数，无需修改 conftest.py

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
