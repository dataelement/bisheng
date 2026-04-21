# Feature: 多租户核心基础设施

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 多租户需求文档 §1-4](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P0
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- Tenant ORM（PRD §2.1 全字段含 quota_config JSON schema）、UserTenant ORM
- `current_tenant_id` ContextVar 定义 + `bypass_tenant_filter` 旁路机制
- SQLAlchemy event hooks：查询自动 `WHERE tenant_id=X`、写入自动填充
- JWT payload 扩展：增加 tenant_id 字段
- UserPayload/LoginUser：增加 tenant_id 字段
- Celery 任务 headers 写入/读取 tenant_id
- 存储隔离工具函数（MinIO/Milvus/ES/Redis 前缀逻辑）— 仅定义函数，不改调用点
- config.yaml 新增 `multi_tenant` 配置节
- DDL 迁移：创建 tenant/user_tenant 表，23+ 业务表加 tenant_id 列，创建默认租户(id=1)，回填 tenant_id=1
- 错误码模块 200
- 最小 pytest conftest.py（SQLite in-memory + settings mock）

**OUT**:
- 租户 CRUD API 端点 → F010-tenant-management-ui
- 租户管理 UI → F010
- 登录流程变更 / 租户选择页 → F010
- 配额执行逻辑 → F005-role-menu-quota
- OpenFGA 租户元组写入 → F004-rebac-core
- 存储调用点改造（MinIO/Milvus/ES 现有代码修改）→ F008-resource-rebac-adaptation

**关联不变量**: INV-1, INV-6, INV-8, INV-9, INV-13, INV-14

---

## 1. 概述与用户故事

F001 是 v2.5.0 权限体系改造的地基。它在系统的每一层（数据库、请求上下文、异步任务、存储路径）植入租户感知能力，但本身不暴露任何新的 API 或 UI。所有后续 Feature（F002~F010）依赖 F001 提供的租户隔离保障。

**用户故事 1**:
作为 **BiSheng 运维人员**，
我希望 **所有业务数据自动按 tenant_id 隔离**，
以便 **后续多租户功能（F010）可以依赖数据库级别的隔离保障，无需逐模块手动添加 WHERE 条件**。

**用户故事 2**:
作为 **BiSheng 开发者**，
我希望 **Celery 异步任务自动继承 HTTP 请求的租户上下文**，
以便 **知识库文件解析、工作流执行等异步任务在正确的租户隔离下运行**。

**用户故事 3**:
作为 **BiSheng 运维人员**，
我希望 **升级到 v2.5.0 时所有存量数据自动归入默认租户(id=1)且存储路径不变**，
以便 **零迁移成本升级，不影响生产环境已有的知识库文件和向量数据**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 运维人员 | 执行 DDL 迁移 | `tenant` 表和 `user_tenant` 表按 PRD §2.1 DDL 创建，字段类型、索引、约束完全匹配 |
| AC-02 | 运维人员 | 首次启动应用 | 自动创建默认租户（id=1, tenant_code="default", tenant_name="Default Tenant", status="active"），所有现有用户自动获得 user_tenant 关联(tenant_id=1, is_default=1) |
| AC-03 | 运维人员 | 执行 DDL 迁移 | 23+ 业务表均包含 `tenant_id INT UNSIGNED NOT NULL DEFAULT 1` 列和 `idx_tenant_id` 索引，存量数据 tenant_id=1 |
| AC-04 | 开发者 | 执行 `session.exec(select(Flow))` | 返回结果自动附加 `WHERE tenant_id=当前上下文值`，不返回其他租户的数据 |
| AC-05 | 开发者 | 执行 `session.add(Flow(...))` 且未手动设置 tenant_id | 记录自动填充 tenant_id=当前上下文值 |
| AC-06 | 开发者 | 在 `with bypass_tenant_filter():` 上下文中执行 SELECT | 查询不附加 tenant_id 过滤，返回所有租户数据 |
| AC-07 | 用户 | 使用含 tenant_id 的新版 JWT 通过 HTTP 请求和 WebSocket 连接访问；使用不含 tenant_id 的旧版 JWT 访问 | 新版 JWT 正确提取 tenant_id 并设置 ContextVar（HTTP 中间件和 WebSocket 中间件均生效）；旧版 JWT 自动回退到 tenant_id=1，不报错 |
| AC-08 | 开发者 | 在 endpoint handler 中访问 `login_user.tenant_id` | 返回当前请求的 tenant_id（从 JWT 解析） |
| AC-09 | 开发者 | 通过 `.delay()` 或 `.apply_async()` 派发 Celery 任务 | 任务 headers 中包含 `tenant_id`；Worker 执行时 `get_current_tenant_id()` 返回正确的 tenant_id |
| AC-10 | 开发者 | 调用 `get_minio_prefix(tenant_id=1, tenant_code="default")` | 返回空字符串 `""`（默认租户零前缀）。调用 `get_minio_prefix(tenant_id=2, tenant_code="cofco")` 返回 `"tenant_cofco/"` |
| AC-11 | 运维人员 | 配置 `multi_tenant.enabled=false` 启动系统 | 行为与现有单租户系统完全一致：自动使用默认租户，无租户选择，SELECT 自动附加 `WHERE tenant_id=1` |

---

## 3. 边界情况

- 当 **multi_tenant.enabled=true 但请求中无 tenant 上下文**（无 JWT cookie 或 JWT 中无 tenant_id）时，系统应对需要认证的端点返回 401，公开端点（如 `/health`）正常响应
- 当 **系统管理员需要跨租户查询**时，代码必须显式使用 `bypass_tenant_filter()` 上下文管理器，否则仍受租户过滤约束
- 当 **Celery Beat 定时任务执行**时（无 HTTP 请求上下文），默认使用 `DEFAULT_TENANT_ID=1`。多租户启用后，需要遍历所有活跃租户逐个执行的场景由 F010 处理
- 当 **raw SQL（`text()`）查询**时，SQLAlchemy ORM 事件不会拦截。这是已知限制，raw SQL 使用者须自行添加 `WHERE tenant_id=X`。F001 在代码中添加注释文档说明此限制
- 当 **已有 JWT token 无 tenant_id 字段**时（升级过渡期），系统通过 `subject.get('tenant_id', DEFAULT_TENANT_ID)` 回退到默认租户，不中断现有会话
- **不支持**：运行时动态切换租户隔离策略（延后到 v3.x）
- **不支持**：物理隔离（独立数据库 per tenant）（延后到 v3.x）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | SQLAlchemy 租户过滤实现方式 | A: `do_orm_execute` 事件（查询拦截）+ `before_flush`（写入填充） / B: Session `execution_options` + 自定义编译扩展 | 选 A | `do_orm_execute` 与 SQLModel 的 `session.exec(select(...))` 直接兼容，拦截点明确，实现透明。方案 B 过于底层，调试困难 |
| AD-02 | 系统管理员跨租户行为 | A: 系统管理员始终在某个租户上下文中操作，跨租户端点显式绕过 / B: 系统管理员不设 tenant 上下文 | 选 A | 符合 PRD §5.5.2（系统管理员始终在某个租户上下文中操作），统一了代码路径。方案 B 会导致所有 DAO 查询需要额外处理 NULL tenant 分支 |
| AD-03 | 默认租户存储路径 | A: 默认租户(id=1)保留原路径，新租户加前缀 / B: 所有租户统一加前缀 | 选 A | 零迁移兼容（INV-9）。存量 MinIO 文件、Milvus collection、ES index 无需移动/重命名 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

#### tenant 表

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, Integer, JSON, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class Tenant(SQLModelSerializable, table=True):
    __tablename__ = "tenant"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    tenant_code: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, comment="租户编码")
    )
    tenant_name: str = Field(
        sa_column=Column(String(128), nullable=False, comment="租户名称")
    )
    logo: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True, comment="租户 Logo URL")
    )
    root_dept_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="根部门 ID")
    )
    status: str = Field(
        default="active",
        sa_column=Column(String(16), nullable=False, server_default=text("'active'"),
                         index=True, comment="状态: active/disabled/archived")
    )
    contact_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, comment="联系人姓名")
    )
    contact_phone: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment="联系人电话")
    )
    contact_email: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True, comment="联系人邮箱")
    )
    quota_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True, comment="租户级资源配额")
    )
    storage_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True, comment="租户级存储配置覆盖")
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="创建人")
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))
    )
```

#### user_tenant 表

```python
class UserTenant(SQLModelSerializable, table=True):
    __tablename__ = "user_tenant"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    is_default: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0"),
                         comment="是否为用户的默认租户")
    )
    status: str = Field(
        default="active",
        sa_column=Column(String(16), nullable=False, server_default=text("'active'"),
                         comment="状态: active/disabled")
    )
    last_access_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, comment="最后访问时间")
    )
    join_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text("CURRENT_TIMESTAMP"))
    )

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uk_user_tenant"),
    )
```

### DAO 方法

| 类 | 方法 | 说明 |
|----|------|------|
| TenantDao | `get_by_id(id)` / `aget_by_id(id)` | 按 ID 查询租户 |
| TenantDao | `get_by_code(code)` / `aget_by_code(code)` | 按编码查询租户 |
| TenantDao | `create_tenant(tenant)` / `acreate_tenant(tenant)` | 创建租户 |
| UserTenantDao | `get_user_tenants(user_id)` / `aget_user_tenants(user_id)` | 获取用户所属租户列表 |
| UserTenantDao | `get_user_default_tenant(user_id)` | 获取用户默认租户 |
| UserTenantDao | `add_user_to_tenant(user_id, tenant_id)` | 添加用户到租户 |

### 业务表 tenant_id 字段

23+ 业务表添加 `tenant_id INT UNSIGNED NOT NULL DEFAULT 1` + `INDEX idx_tenant_id (tenant_id)`。

具体表清单见 PRD §2.3。不加 tenant_id 的表：`user`, `user_link`, `tenant`, `user_tenant`, `recall_chunk`, `failed_tuples`, `relation_definition`。

---

## 6. API 契约

N/A — F001 不新增 API 端点。租户 CRUD API 由 F010 负责。

---

## 7. Service 层逻辑

N/A — F001 是纯基础设施 Feature，不包含业务 Service。核心逻辑分布在：

| 组件 | 文件 | 职责 |
|------|------|------|
| TenantContextVar | `core/context/tenant.py` | ContextVar 定义、getter/setter、bypass 机制 |
| TenantFilter | `core/database/tenant_filter.py` | SQLAlchemy 事件钩子（查询过滤 + 写入填充） |
| TenantStorage | `core/storage/tenant_storage.py` | 存储路径前缀工具函数 |
| TenantCeleryContext | `worker/tenant_context.py` | Celery 信号处理（headers 写入/读取） |

---

## 8. 前端设计

N/A — F001 不涉及前端变更。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/database/models/tenant.py` | Tenant + UserTenant ORM 模型 + TenantDao + UserTenantDao |
| `src/backend/bisheng/core/context/tenant.py` | `current_tenant_id` ContextVar、getter/setter、bypass 上下文管理器 |
| `src/backend/bisheng/core/database/tenant_filter.py` | SQLAlchemy `do_orm_execute` + `before_flush` 事件钩子 |
| `src/backend/bisheng/core/config/multi_tenant.py` | `MultiTenantConf` Pydantic 配置模型 |
| `src/backend/bisheng/core/storage/tenant_storage.py` | MinIO/Milvus/ES/Redis 前缀工具函数 |
| `src/backend/bisheng/common/errcode/tenant.py` | 200xx 租户错误码 |
| `src/backend/bisheng/worker/tenant_context.py` | Celery `before_task_publish` / `task_prerun` 信号处理 |
| Alembic 迁移脚本 | DDL: 创建 tenant/user_tenant 表 + 23+ 表添加 tenant_id |
| `src/backend/test/conftest.py` | 最小 pytest fixture（SQLite in-memory + settings mock） |
| `src/backend/test/test_tenant_context.py` | ContextVar + bypass 机制测试 |
| `src/backend/test/test_tenant_filter.py` | SQLAlchemy 事件钩子集成测试 |
| `src/backend/test/test_tenant_storage.py` | 存储前缀函数单元测试 |
| `src/backend/test/test_celery_tenant.py` | Celery 租户上下文传播测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/core/config/settings.py` | 添加 `multi_tenant: MultiTenantConf = MultiTenantConf()` 字段 |
| `src/backend/bisheng/user/domain/services/auth.py` | LoginUser 添加 `tenant_id` 字段；JWT payload 添加 `tenant_id`；`init_login_user` 接受 `tenant_id`；`get_login_user` 从 subject 提取 `tenant_id` |
| `src/backend/bisheng/utils/http_middleware.py` | `CustomMiddleware.dispatch` 解析 JWT cookie 提取 tenant_id 并设置 ContextVar；`WebSocketLoggingMiddleware` 同理 |
| `src/backend/bisheng/core/database/manager.py` | 引擎创建后调用 `register_tenant_filter_events(engine)` |
| `src/backend/bisheng/common/init_data.py` | 添加 `init_default_tenant()` 函数调用 |
| `src/backend/bisheng/config.yaml` | 添加 `multi_tenant:` 配置节（enabled: false, default_tenant_code: "default"） |

---

## 10. 非功能要求

- **性能**: SQLAlchemy 事件钩子增加的延迟 < 1ms/查询。存储前缀函数为纯字符串操作，无网络开销
- **安全**: tenant_id 过滤是数据隔离的安全底线。`multi_tenant.enabled=true` 时，无 tenant 上下文的 ORM 查询将抛出 `NoTenantContextError`，fail-closed 防止数据泄漏
- **兼容性**: 默认租户(id=1)零迁移兼容。升级后所有存量数据 tenant_id=1，所有存储路径不变。旧 JWT token 自动回退到 tenant_id=1
- **可测试性**: 通过 `bypass_tenant_filter()` 上下文管理器，测试代码可以在不设置 tenant 上下文时操作数据库

---

## 11. 错误码表

> 模块编码 200（tenant），已在 release-contract.md 注册。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 20000 | TenantNotFoundError | 指定的租户 ID 或编码不存在 | — |
| 200 (body) | 20001 | TenantDisabledError | 租户已被禁用 | — |
| 200 (body) | 20002 | UserNotInTenantError | 用户不属于当前租户 | — |
| 200 (body) | 20003 | TenantCodeDuplicateError | 租户编码重复 | — |
| 200 (body) | 20004 | NoTenantContextError | 请求中缺少租户上下文（multi_tenant.enabled=true 时） | AC-11 |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
