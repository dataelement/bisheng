# Feature: 策略角色、菜单权限与配额管理

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3.2-3.4](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)、[2.5 多租户需求文档 §5.4 §6](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- Role 表迁移：新增 `department_id`（部门作用域）+ `quota_config`（JSON）+ `role_type`（global/tenant）
- Role CRUD API（新 DDD 模块 `role/`，含部门作用域过滤）
- WEB_MENU 管理（保留 RoleAccess type=99 机制，更新 WebMenuResource 枚举）
- 配额执行服务：`QuotaService`（三级配额逻辑 + `@require_quota` 装饰器）
- 默认配额常量定义
- 旧 API 向后兼容（`user/api/user.py` 中角色端点委托新 Service）
- 错误码定义（模块 240）

**OUT**:
- 角色管理前端页面改造 → F010-tenant-management-ui
- 配额监控仪表盘 → P2
- 配额告警（80%/90%/100% 阈值）→ P2
- 存储配额实际拦截（MinIO 上传）→ F008 集成时调用本 Feature 提供的检查函数
- 资源创建端点的 `@require_quota` 装饰器实际应用 → F008

**关键文件（预判）**:
- 修改: `database/models/role.py`、`database/models/role_access.py`、`user/domain/services/auth.py`、`user/api/user.py`、`common/init_data.py`、`api/router.py`
- 新建: `role/` DDD 模块、`common/errcode/role.py`、Alembic 迁移

**关联不变量**: INV-1（tenant_id 自动注入）, INV-3（WEB_MENU 除外的权限检查用 PermissionService）, INV-5（系统管理员短路）, INV-11（配额执行不使用分布式锁）

---

## 1. 概述与用户故事

**US-01**: 作为**租户管理员**，我希望**创建和管理策略角色**（包含菜单权限和资源配额），以便**控制本租户内用户能看到哪些功能入口，以及各类资源的创建上限**。

**US-02**: 作为**系统管理员**，我希望**创建全局角色**（所有租户可见但只读），以便**为全平台用户提供标准化的角色模板**。

**US-03**: 作为**普通用户**，当我创建资源（知识空间、频道、工作流等）时，系统应**自动检查我的有效配额**并在超限时明确拒绝，以便**我了解自己的资源限额并避免无效操作**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 角色 CRUD

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 租户管理员 | 创建角色：提供 role_name + department_id + quota_config + remark | 角色创建成功，role_type='tenant'，tenant_id=当前租户；返回完整角色对象 |
| AC-02 | 系统管理员 | 创建全局角色：提供 role_name + quota_config，不提供 department_id | 角色创建成功，role_type='global'，department_id=NULL |
| AC-03 | 租户管理员 | 列表查询角色 | 返回：role_type='global' 的全局角色（只读标记） + 本租户的角色；按 create_time DESC 排序，支持分页和关键字搜索 |
| AC-04 | 系统管理员 | 列表查询角色 | 返回所有角色（全局 + 当前租户，AdminRole 除外），均可编辑 |
| AC-04b | 部门管理员 | 列表查询角色 | 仅返回：role_type='global' 的全局角色（只读）+ 本部门及子部门创建的角色（department_id 在当前部门子树内）；不可见其他部门的角色 |
| AC-05 | 租户管理员 | 更新角色：修改 role_name / quota_config / remark | 更新成功，返回更新后对象 |
| AC-06 | 租户管理员 | 更新全局角色 | 返回错误码 24003（RolePermissionDeniedError），全局角色对租户管理员只读 |
| AC-07 | 任意用户 | 删除内置角色（id=1 AdminRole 或 id=2 DefaultRole） | 返回错误码 24004（RoleBuiltinProtectedError） |
| AC-08 | 租户管理员 | 删除本租户角色 | 角色删除成功，同时级联删除：UserRole 关联 + RoleAccess 关联 |
| AC-09 | 租户管理员 | 创建角色，role_name 与同 tenant_id + role_type 下的已有角色重名 | 返回错误码 24002（RoleNameDuplicateError） |
| AC-10 | 租户管理员 | 获取角色详情（含 quota_config、department_name、user_count） | 返回完整角色信息，department_name 从 Department 表关联查询 |
| AC-10b | 普通用户 | 调用角色管理 API（创建/更新/删除角色） | 返回错误码 24003（RolePermissionDeniedError），普通用户无权管理角色 |
| AC-10c | 租户管理员 | 创建角色时 quota_config 包含非法值（如 key 值为非整数、负数非 -1） | 返回错误码 24005（QuotaConfigInvalidError），合法值：-1（不限制）、0（禁止）、正整数（上限） |

### 菜单权限

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-11 | 租户管理员 | 更新角色菜单权限：POST /roles/{role_id}/menu 传入菜单 ID 列表 | RoleAccess 表 type=WEB_MENU 记录先清后加，返回成功 |
| AC-12 | 租户管理员 | 查询角色菜单权限：GET /roles/{role_id}/menu | 返回该角色当前的菜单权限列表 |
| AC-13 | 普通用户 | 登录后获取用户信息（GET /user/info） | 返回的 web_menu 字段包含用户所有角色的菜单权限并集 |
| AC-14 | 系统管理员 | 登录后获取用户信息 | web_menu 包含所有菜单项（WebMenuResource 全集） |

### 配额计算

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-15 | 普通用户 | 查询有效配额：GET /quota/effective | 返回每种资源类型的 role_quota + tenant_quota + tenant_used + effective 值 |
| AC-16 | — | 用户绑定多个角色，各角色 quota_config.workflow 分别为 10、20、-1 | get_effective_quota 返回 -1（任一角色不限制则不限制） |
| AC-17 | — | 用户绑定多个角色，各角色 quota_config.channel 分别为 5、10 | get_effective_quota 取角色最大值 10，再与租户剩余取 min |
| AC-18 | — | 用户角色 quota_config 未设置某资源类型（key 缺失） | 使用系统默认配额（DEFAULT_ROLE_QUOTA 常量） |
| AC-19 | 系统管理员 | 查询有效配额 | 所有资源类型返回 -1（管理员不限制） |

### 配额检查

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-20 | 普通用户 | 创建资源时配额已满（effective_quota == 已创建数量） | 返回错误码 24001（QuotaExceededError），包含资源类型和当前配额信息 |
| AC-21 | 普通用户 | 创建资源时配额充足 | check_quota 返回 True，不拦截 |
| AC-22 | — | 租户级配额已满（tenant.quota_config 上限达到） | 即使用户角色配额充足，仍返回 QuotaExceededError（租户硬上限优先） |
| AC-23 | — | 并发创建导致轻微超额（INV-11） | 不使用分布式锁，允许超额，下次检查时纠正 |

### 向后兼容

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-24 | 任意用户 | 调用旧 API POST /role/add | 角色创建成功（内部委托 RoleService） |
| AC-25 | 任意用户 | 调用旧 API GET /role/list | 返回角色列表（保持原有响应结构） |
| AC-26 | 任意用户 | 调用旧 API POST /role_access/refresh | 菜单权限更新成功 |
| AC-27 | 任意用户 | 调用旧 API GET /role_access/list | 返回权限列表 |

---

## 3. 边界情况

- 当 **角色的 quota_config 为 NULL** 时，所有资源类型使用 `DEFAULT_ROLE_QUOTA` 系统默认值
- 当 **租户的 quota_config 为 NULL** 时，视为租户不限制（全部返回 -1）
- 当 **quota_config 中某个 key 缺失** 时，该资源类型使用系统默认值
- 当 **用户未绑定任何角色** 时，使用系统默认配额（DEFAULT_ROLE_QUOTA）
- 当 **删除角色时有用户仍绑定该角色** 时，级联删除 UserRole 关联；用户自动回退到其他角色或无角色状态
- 当 **department_id 指向的部门不存在或已归档** 时，创建/更新角色返回 24005 错误
- 当 **role_name 为空或超长（>128 字符）** 时，返回参数校验错误
- **不支持**：角色间的继承关系（延后到 P2）
- **不支持**：配额使用量的实时精确统计（采用创建时检查，允许并发轻微超额，INV-11）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 全局角色的表示方式 | A: tenant_id=0 哨兵值 / B: role_type 字段 | 选 B | 不破坏 INV-1 自动租户过滤机制；查询时 `WHERE role_type='global' OR tenant_id=当前租户` 无需 bypass_tenant_filter |
| AD-02 | 角色模块位置 | A: 留在 user/ 模块 / B: 新建 role/ DDD 模块 | 选 B | user/api/user.py 已 700+ 行；F005 新增配额等复杂逻辑，独立模块更清晰；符合 F002/F003 已建立的 DDD 模式 |
| AD-03 | quota_config JSON 范围 | A: 仅 PRD UI 展示的 2 字段 / B: 技术方案定义的 8 字段 | 选 B | 后端 schema 一步到位，F008 资源接入时无需改 schema；前端按需展示 |
| AD-04 | 配额检查机制 | A: Service 方法直接调用 / B: `@require_quota` 装饰器 | 选 B（兼用 A） | 装饰器用于 API 端点声明式检查；Service 方法用于复杂场景灵活调用。装饰器内部调用 QuotaService.check_quota() |
| AD-05 | 旧 API 兼容策略 | A: 旧端点委托新 Service / B: 废弃旧端点 | 选 A | 前端未改造前必须兼容旧路径；内部统一逻辑避免重复 |
| AD-06 | 错误码模块编码 | 240 | 240 | release-contract.md 中下一个可用编码（230 已分配给 user_group） |
| AD-07 | group_id 字段处理 | A: 立即删除 / B: 保留但标记 deprecated | 选 B | 旧 API 仍引用 group_id 作为参数；F006 数据迁移完成后再清理 |
| AD-08 | knowledge_space_file_limit 处理 | A: 立即删除 / B: 迁移到 quota_config 并保留 | 选 B | Alembic 迁移时将旧值写入 quota_config.knowledge_space_file，保留字段供旧代码读取 |
| AD-09 | 全局角色查询策略 | A: 每次查询 bypass 租户过滤 / B: 自定义 DAO 方法合并查询 | 选 B | 在 RoleDao 中编写专门的 `get_visible_roles()` 方法：`SELECT * FROM role WHERE (role_type='global') OR (tenant_id=:tid AND role_type='tenant')` |

---

## 5. 数据库 & Domain 模型

### 5.1 Role 表变更

> 修改现有表 `role`（`database/models/role.py`），不新建表。

**新增字段**：

```python
class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='Frontend Display Name')
    role_type: str = Field(
        default='tenant',
        sa_column=Column(String(16), nullable=False, server_default=text("'tenant'"),
                         comment='global: cross-tenant visible; tenant: tenant-scoped'),
    )
    department_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True,
                         comment='Department scope ID; NULL = no scope restriction'),
    )
    quota_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True,
                         comment='Resource quota config JSON'),
    )
    remark: Optional[str] = Field(default=None, index=False)
    # ── deprecated fields (AD-07, AD-08) ──
    group_id: Optional[int] = Field(default=None, index=True)  # deprecated: use department_id
    knowledge_space_file_limit: Optional[int] = Field(default=0, index=False)  # deprecated: use quota_config
    # timestamps
    create_time: Optional[datetime] = Field(...)
    update_time: Optional[datetime] = Field(...)
```

**唯一约束变更**：
```python
class Role(RoleBase, table=True):
    __table_args__ = (
        UniqueConstraint('tenant_id', 'role_type', 'role_name', name='uk_tenant_roletype_rolename'),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
```

### 5.2 RoleAccess 表 — 无 Schema 变更

仅更新 `WebMenuResource` 枚举（`database/models/role_access.py`）：

```python
class WebMenuResource(Enum):
    """Front-end menu bar resources — updated for v2.5 PRD."""
    # 一级菜单
    WORKSTATION = 'workstation'       # 工作台（用户端入口）
    ADMIN = 'admin'                   # 管理后台（管理端入口）
    # 二级菜单 — 构建/资源
    BUILD = 'build'                   # 应用构建
    KNOWLEDGE = 'knowledge'           # 知识库管理
    KNOWLEDGE_SPACE = 'knowledge_space'  # 知识空间
    MODEL = 'model'                   # 模型管理
    TOOL = 'tool'                     # 工具管理
    MCP = 'mcp'                       # MCP 服务
    CHANNEL = 'channel'               # 频道管理
    # 二级菜单 — 评测/数据
    EVALUATION = 'evaluation'         # 模型评测
    DATASET = 'dataset'               # 数据集管理
    MARK_TASK = 'mark_task'           # 标注任务
    BOARD = 'board'                   # 看板/仪表盘
    # 系统管理子项
    SUBSCRIPTION = 'subscription'     # 订阅管理
    # 兼容旧值（deprecated, AD-07）
    FRONTEND = 'frontend'             # deprecated
    BACKEND = 'backend'               # deprecated
    CREATE_DASHBOARD = 'create_dashboard'  # deprecated
```

### 5.3 配额常量

```python
# role/domain/services/quota_service.py

DEFAULT_ROLE_QUOTA: dict[str, int] = {
    'knowledge_space': 30,        # 知识空间数量
    'knowledge_space_file': 500,  # 知识空间文件上传上限 (GB)
    'channel': 10,                # 频道数量
    'channel_subscribe': 20,      # 频道订阅数量
    'workflow': -1,               # 工作流数量 (-1=不限制)
    'assistant': -1,              # 助手数量
    'tool': -1,                   # 工具数量
    'dashboard': -1,              # 看板数量
}

class QuotaResourceType:
    """Supported resource types for quota enforcement."""
    KNOWLEDGE_SPACE = 'knowledge_space'
    KNOWLEDGE_SPACE_FILE = 'knowledge_space_file'
    CHANNEL = 'channel'
    CHANNEL_SUBSCRIBE = 'channel_subscribe'
    WORKFLOW = 'workflow'
    ASSISTANT = 'assistant'
    TOOL = 'tool'
    DASHBOARD = 'dashboard'
```

### 5.4 Alembic 迁移

文件: `core/database/alembic/versions/v2_5_0_f005_role_menu_quota.py`

```
down_revision = v2_5_0_f004 系列最后一个
```

操作：
1. `ADD COLUMN department_id INT NULL` + 索引
2. `ADD COLUMN quota_config JSON NULL`
3. `ADD COLUMN role_type VARCHAR(16) NOT NULL DEFAULT 'tenant'`
4. `DROP INDEX group_role_name_uniq`
5. `CREATE UNIQUE INDEX uk_tenant_roletype_rolename ON role(tenant_id, role_type, role_name)`
6. 数据回填：`UPDATE role SET role_type='global' WHERE id IN (1, 2)`（AdminRole, DefaultRole）
7. 数据迁移：将 `knowledge_space_file_limit > 0` 的值写入 `quota_config`

### 5.5 Domain DTO（Pydantic Schema）

文件: `role/domain/schemas/role_schema.py`

```python
class RoleCreateRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=128)
    department_id: Optional[int] = None
    quota_config: Optional[dict] = None
    remark: Optional[str] = Field(None, max_length=512)

class RoleUpdateRequest(BaseModel):
    role_name: Optional[str] = Field(None, min_length=1, max_length=128)
    department_id: Optional[int] = None
    quota_config: Optional[dict] = None
    remark: Optional[str] = Field(None, max_length=512)

class RoleListResponse(BaseModel):
    id: int
    role_name: str
    role_type: str                        # 'global' | 'tenant'
    department_id: Optional[int] = None
    department_name: Optional[str] = None # 关联查询填充
    quota_config: Optional[dict] = None
    remark: Optional[str] = None
    user_count: int = 0                   # 绑定用户数
    is_readonly: bool = False             # 对当前用户是否只读
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None

class EffectiveQuotaItem(BaseModel):
    resource_type: str
    role_quota: int          # 角色级配额（多角色取 max）,-1=不限制
    tenant_quota: int        # 租户级配额, -1=不限制
    tenant_used: int         # 租户已使用量
    user_used: int           # 用户已使用量
    effective: int           # 有效配额 = min(tenant_remaining, role_quota), -1=不限制

class MenuUpdateRequest(BaseModel):
    menu_ids: list[str]      # WebMenuResource 值列表
```

---

## 6. API 契约

### 端点列表

> 认证：`LoginUser = Depends(LoginUser.get_login_user)`（`user/domain/services/auth.py`）  
> 响应包装：`UnifiedResponseModel[T]`  
> 新端点前缀：`/api/v1/roles`，配额前缀：`/api/v1/quota`

| Method | Path | 描述 | 权限 | 关联 AC |
|--------|------|------|------|---------|
| POST | `/api/v1/roles` | 创建角色 | 系统管理员或租户管理员 | AC-01, AC-02 |
| GET | `/api/v1/roles` | 角色列表（分页） | 登录用户 | AC-03, AC-04 |
| GET | `/api/v1/roles/{role_id}` | 角色详情 | 登录用户 | AC-10 |
| PUT | `/api/v1/roles/{role_id}` | 更新角色 | 系统管理员或创建者所在租户管理员 | AC-05, AC-06 |
| DELETE | `/api/v1/roles/{role_id}` | 删除角色 | 系统管理员或创建者所在租户管理员 | AC-07, AC-08 |
| POST | `/api/v1/roles/{role_id}/menu` | 更新菜单权限 | 系统管理员或租户管理员 | AC-11 |
| GET | `/api/v1/roles/{role_id}/menu` | 获取菜单权限 | 登录用户 | AC-12 |
| GET | `/api/v1/quota/effective` | 当前用户有效配额 | 登录用户 | AC-15, AC-16, AC-17, AC-18, AC-19 |
| GET | `/api/v1/quota/usage` | 当前用户资源使用量 | 登录用户 | AC-15 |

### 请求/响应示例

**创建角色**:
```json
POST /api/v1/roles
{
  "role_name": "知识库编辑员",
  "department_id": 5,
  "quota_config": {
    "knowledge_space": 10,
    "knowledge_space_file": 100,
    "channel": 0,
    "workflow": -1
  },
  "remark": "仅允许知识库相关操作"
}
```

**成功响应**:
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 15,
    "role_name": "知识库编辑员",
    "role_type": "tenant",
    "department_id": 5,
    "quota_config": {"knowledge_space": 10, "knowledge_space_file": 100, "channel": 0, "workflow": -1},
    "remark": "仅允许知识库相关操作",
    "create_time": "2026-04-12T10:00:00"
  }
}
```

**角色列表**:
```json
GET /api/v1/roles?keyword=编辑&page=1&limit=10
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": 2,
        "role_name": "Regular users",
        "role_type": "global",
        "department_id": null,
        "department_name": null,
        "quota_config": null,
        "user_count": 45,
        "is_readonly": true,
        "create_time": "2026-01-01T00:00:00"
      },
      {
        "id": 15,
        "role_name": "知识库编辑员",
        "role_type": "tenant",
        "department_id": 5,
        "department_name": "技术部/AI团队",
        "quota_config": {"knowledge_space": 10},
        "user_count": 3,
        "is_readonly": false,
        "create_time": "2026-04-12T10:00:00"
      }
    ],
    "total": 2
  }
}
```

**更新菜单权限**:
```json
POST /api/v1/roles/15/menu
{
  "menu_ids": ["workstation", "build", "knowledge", "knowledge_space"]
}
```

**查询有效配额**:
```json
GET /api/v1/quota/effective
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "resource_type": "knowledge_space",
      "role_quota": 30,
      "tenant_quota": 100,
      "tenant_used": 42,
      "user_used": 8,
      "effective": 30
    },
    {
      "resource_type": "workflow",
      "role_quota": -1,
      "tenant_quota": -1,
      "tenant_used": 15,
      "user_used": 5,
      "effective": -1
    }
  ]
}
```

**配额超限错误**:
```json
{
  "status_code": 24001,
  "status_message": "Resource quota exceeded: knowledge_space (used: 30, limit: 30)",
  "data": null
}
```

### 错误码表

> 模块编码 240，注册于 release-contract.md「已分配模块编码」。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 24000 | RoleNotFoundError | 角色不存在 | AC-05, AC-06, AC-08 |
| 200 (body) | 24001 | QuotaExceededError | 资源配额超限 | AC-20, AC-22 |
| 200 (body) | 24002 | RoleNameDuplicateError | 同作用域下角色名重复 | AC-09 |
| 200 (body) | 24003 | RolePermissionDeniedError | 无权操作此角色（普通用户/租户管理员操作全局角色） | AC-06, AC-10b |
| 200 (body) | 24004 | RoleBuiltinProtectedError | 内置角色不可删除/修改核心属性 | AC-07 |
| 200 (body) | 24005 | QuotaConfigInvalidError | quota_config 值非法（合法值：-1/0/正整数）或 department_id 无效 | AC-10c |

---

## 7. Service 层逻辑

> Service 文件位置：`role/domain/services/`

### 7.1 RoleService（`role_service.py`）

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `create_role` | RoleCreateRequest + LoginUser | Role | 权限检查 → 校验 department_id → 去重 → 创建 + 审计日志 |
| `list_roles` | keyword + page + limit + LoginUser | PageData[RoleListResponse] | 合并查询（全局角色 + 当前租户角色），关联 department_name 和 user_count，标记 is_readonly |
| `get_role` | role_id + LoginUser | RoleListResponse | 查询单个角色详情 |
| `update_role` | role_id + RoleUpdateRequest + LoginUser | Role | 权限检查（全局角色对租户管理员只读）→ 内置角色保护 → 更新 + 审计日志 |
| `delete_role` | role_id + LoginUser | None | 权限检查 → 内置角色保护 → 级联删除（UserRole + RoleAccess）+ 审计日志 |
| `update_menu` | role_id + menu_ids + LoginUser | None | 权限检查 → 委托 RoleAccessDao.update_role_access_all(type=WEB_MENU) |
| `get_menu` | role_id + LoginUser | List[str] | 查询 RoleAccess type=WEB_MENU 记录 |

**权限检查逻辑**（四级短路）：
1. `login_user.is_admin()` → 系统管理员，全部放行
2. 检查是否为租户管理员（通过 OpenFGA `PermissionService.check(user_id, 'admin', 'tenant', tenant_id)`）→ 租户管理员，全局角色只读，本租户角色可操作
3. 检查是否为部门管理员（通过 OpenFGA `PermissionService.check(user_id, 'admin', 'department', dept_id)`）→ 部门管理员，仅可操作本部门子树内创建的角色（department_id 在其部门 path 子树内），全局角色只读
4. 以上均不满足 → 返回 24003 RolePermissionDeniedError（AC-10b）

**角色列表查询逻辑（AD-09）**：
```python
# RoleDao.get_visible_roles(tenant_id, keyword, page, limit, department_path=None)
# SQL: SELECT * FROM role
#      WHERE id > 1  -- AdminRole(id=1) 是系统内置超级管理员角色，不在角色管理列表展示
#        AND (
#              (role_type = 'global')
#           OR (tenant_id = :tid AND role_type = 'tenant')
#        )
#        AND (role_name LIKE :keyword OR :keyword IS NULL)
#        -- 部门管理员过滤：仅看到自己部门子树内创建的角色
#        AND (:dept_path IS NULL OR department_id IN (
#             SELECT id FROM department WHERE path LIKE :dept_path || '%'))
#      ORDER BY create_time DESC
#      LIMIT :limit OFFSET :offset
```

> **设计说明**：AdminRole(id=1) 是系统超级管理员角色，通过 `user_role` 表直接分配给超级管理员用户，不出现在角色管理列表中（与 v2.4 行为一致）。DefaultRole(id=2) 作为全局角色正常展示。

### 7.2 QuotaService（`quota_service.py`）

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `get_effective_quota` | user_id + resource_type + tenant_id + LoginUser | int | 三级配额计算（见下方） |
| `check_quota` | user_id + resource_type + tenant_id + LoginUser | bool | 调用 get_effective_quota，比对已用量，超限抛 QuotaExceededError |
| `get_all_effective_quotas` | user_id + tenant_id + LoginUser | List[EffectiveQuotaItem] | 遍历所有资源类型，返回完整配额信息 |
| `get_tenant_resource_count` | tenant_id + resource_type | int | 统计租户级资源总量 |
| `get_user_resource_count` | user_id + resource_type | int | 统计用户级资源数量 |

**get_effective_quota 核心逻辑**：
```python
async def get_effective_quota(cls, user_id, resource_type, tenant_id, login_user=None):
    # 1. 管理员短路
    if login_user and login_user.is_admin():
        return -1

    # 2. 获取用户角色列表
    user_roles = await UserRoleDao.aget_user_roles(user_id)
    role_ids = [r.role_id for r in user_roles]

    # 3. 多角色取最大值
    if not role_ids:
        role_quota = DEFAULT_ROLE_QUOTA.get(resource_type, -1)
    else:
        roles = await RoleDao.aget_role_by_ids(role_ids)
        max_quota = None
        for role in roles:
            q = (role.quota_config or {}).get(resource_type)
            if q is None:
                q = DEFAULT_ROLE_QUOTA.get(resource_type, -1)
            if q == -1:
                return -1  # 任一角色不限制 → 不限制
            if max_quota is None or q > max_quota:
                max_quota = q
        role_quota = max_quota if max_quota is not None else DEFAULT_ROLE_QUOTA.get(resource_type, -1)

    # 4. 租户级硬上限
    tenant = await TenantDao.aget_by_id(tenant_id)
    tenant_limit = (tenant.quota_config or {}).get(resource_type, -1) if tenant else -1

    if tenant_limit == -1:
        return role_quota  # 租户不限制，仅看角色

    # 5. 租户剩余 = 租户上限 - 已用
    tenant_used = await cls.get_tenant_resource_count(tenant_id, resource_type)
    tenant_remaining = tenant_limit - tenant_used

    # 6. effective = min(tenant_remaining, role_quota)
    if role_quota == -1:
        return max(tenant_remaining, 0)
    return min(max(tenant_remaining, 0), role_quota)
```

**资源计数 SQL 映射**（`_count_resource` 内部方法）：

| resource_type | 计数 SQL |
|--------------|---------|
| knowledge_space | `SELECT COUNT(*) FROM knowledge WHERE tenant_id=? AND type=3 AND status!=-1` |
| knowledge_space_file | `SELECT COALESCE(SUM(file_size), 0) FROM knowledgefile WHERE tenant_id=? AND status IN (1,2)` (bytes → GB) |
| channel | `SELECT COUNT(*) FROM channel WHERE tenant_id=? AND status='active'` |
| channel_subscribe | 同上（按场景细化） |
| workflow | `SELECT COUNT(*) FROM flow WHERE tenant_id=? AND flow_type=10 AND status!=0` |
| assistant | `SELECT COUNT(*) FROM flow WHERE tenant_id=? AND flow_type=5 AND status!=0` |
| tool | `SELECT COUNT(*) FROM gptstools WHERE tenant_id=? AND is_delete=0` |
| dashboard | `SELECT COUNT(*) FROM flow WHERE tenant_id=? AND flow_type=15 AND status!=0` |

### 7.3 @require_quota 装饰器

```python
def require_quota(resource_type: str):
    """Decorator for resource creation endpoints.
    
    Extracts login_user from kwargs, calls QuotaService.check_quota().
    Raises QuotaExceededError if quota is exhausted.
    
    Usage:
        @require_quota(QuotaResourceType.KNOWLEDGE_SPACE)
        async def create_knowledge_space(*, login_user: LoginUser = Depends(...)):
            ...
    """
```

注：装饰器在 F005 中定义，但实际应用到各资源创建端点在 F008-resource-rebac-adaptation 中完成。

### 权限检查

- 角色 CRUD 操作：系统管理员全权 + 租户管理员本租户操作
- 菜单权限管理：同上
- 配额查询：登录用户可查自己的配额
- 不涉及 OpenFGA 资源级权限（角色本身不是 OpenFGA 管理的资源类型）

### DAO 调用约定

- 新增 `RoleDao.get_visible_roles(tenant_id, keyword, page, limit)` — 合并全局+租户角色查询
- 新增 `RoleDao.count_visible_roles(tenant_id, keyword)` — 计数
- 新增 `RoleDao.aget_visible_roles(...)` — 异步版本
- 现有 `RoleAccessDao.update_role_access_all()` 和 `aget_role_access()` 复用
- 现有 `UserRoleDao.aget_user_roles()` 复用

---

## 8. 前端设计

> F005 为纯后端 Feature（AD），前端改造归 F010-tenant-management-ui。

### 8.1 Platform 前端影响评估

F005 后端变更对前端的影响（F010 需要处理）：

1. **角色管理页面**：
   - group_id 选择器 → department_id 部门树选择器
   - 新增 quota_config 表单（知识空间文件上限 + 频道数量上限 + 无限制勾选框）
   - 新增 role_type 显示（全局/租户标签）
   - 全局角色显示只读标记，禁用编辑/删除按钮
   - API 路径可从旧路径迁移到新路径（或继续用旧路径，向后兼容）

2. **菜单权限配置**：
   - WebMenuResource 枚举新增项需同步到前端开关列表
   - 新增的菜单项（workstation, admin, tool, mcp, channel, dataset, mark_task）需在前端注册

3. **用户信息接口**：
   - GET /user/info 返回的 web_menu 字段已包含新菜单值
   - 前端需在路由守卫中识别新菜单键

### 8.2 Client 前端

无影响。Client 前端不涉及角色管理和配额配置。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/role/__init__.py` | 模块初始化 |
| `src/backend/bisheng/role/api/__init__.py` | API 包 |
| `src/backend/bisheng/role/api/router.py` | 模块路由注册 |
| `src/backend/bisheng/role/api/endpoints/__init__.py` | 端点包 |
| `src/backend/bisheng/role/api/endpoints/role.py` | 角色 CRUD 端点 |
| `src/backend/bisheng/role/api/endpoints/role_access.py` | 菜单权限端点 |
| `src/backend/bisheng/role/api/endpoints/quota.py` | 配额查询端点 |
| `src/backend/bisheng/role/domain/__init__.py` | Domain 包 |
| `src/backend/bisheng/role/domain/schemas/__init__.py` | Schema 包 |
| `src/backend/bisheng/role/domain/schemas/role_schema.py` | Pydantic DTO |
| `src/backend/bisheng/role/domain/services/__init__.py` | Service 包 |
| `src/backend/bisheng/role/domain/services/role_service.py` | 角色 CRUD 业务逻辑 |
| `src/backend/bisheng/role/domain/services/quota_service.py` | 配额执行服务 |
| `src/backend/bisheng/common/errcode/role.py` | 错误码 240xx |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f005_role_menu_quota.py` | 迁移脚本 |
| `src/backend/test/test_quota_service.py` | QuotaService 单元测试 |
| `src/backend/test/test_role_service.py` | RoleService 单元测试 |
| `src/backend/test/test_role_api.py` | API 集成测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/database/models/role.py` | 新增 role_type/department_id/quota_config 字段 + 新 DAO 方法 + 唯一约束变更 |
| `src/backend/bisheng/database/models/role_access.py` | 更新 WebMenuResource 枚举 |
| `src/backend/bisheng/user/domain/services/auth.py` | get_roles_web_menu() 适配新 role_type；WebMenuResource 全集更新 |
| `src/backend/bisheng/user/api/user.py` | 旧角色端点内部委托 RoleService |
| `src/backend/bisheng/common/init_data.py` | 内置角色设置 role_type='global' + 默认 quota_config + 新菜单权限 |
| `src/backend/bisheng/api/router.py` | 注册 role 模块路由 |
| `features/v2.5.0/release-contract.md` | 注册 240 模块编码 |

---

## 9.1 Known Post-Release Issues（v2.5.1 自测发现）

> 2026-04-19 F016-tenant-quota-hierarchy 在 114 服务器跑 `/tenants/quota/tree`
> 自测时暴露以下遗留 bug，由 F016 ac-verification.md 追溯到 F005。修复目前
> 未排期；后续 F017 共享资源场景或独立 hotfix 择机处理。

| ID | Bug | 位置 | 现状 |
|----|-----|------|------|
| KI-01 | `knowledge_space` SQL 模板引用不存在的 `status` 列 | `quota_service.py` L41 `_RESOURCE_COUNT_TEMPLATES['knowledge_space']` = `"SELECT COUNT(*) FROM knowledge WHERE {col}=:{param} AND status != -1"`；实际 `knowledge` 表只有 `state` / `is_released`，无 `status` 列 | `_count_resource` try/except 捕获 `Unknown column 'status'` 后返 0，导致 `/quota/tree.root.usage[knowledge_space].used` **恒为 0**，前端 UI 显示的知识库用量失真；F016 单测用 mock 未暴露，E2E 触达后才发现 |
| 影响面 | — | F016 `/quota/tree`、v2.5.0 F008 `@require_quota(KNOWLEDGE_SPACE)` 依赖此计数的端点 | F016 未修（tenant-quota 只负责沿树聚合，底层 SQL 模板归属 F005） |
| 建议修复 | — | 把模板改为 `WHERE {col}=:{param} AND state != 0`（或其他正确的"已生效"条件）+ 补一条 integration test | hotfix/v2.5.1 或 F017 顺带 |

---

## 10. 非功能要求

- **性能**: 配额检查为 SQL COUNT + Redis 缓存场景。get_effective_quota 涉及 2-3 次数据库查询（用户角色 + 角色详情 + 资源计数），应控制在 50ms 内。批量配额查询（get_all_effective_quotas）使用单次角色查询 + N 次资源计数查询。
- **并发安全**: 配额检查不使用分布式锁（INV-11），允许高并发下轻微超额。超额部分在下次检查时自动纠正。
- **安全**: 角色管理仅限系统管理员和租户管理员操作；普通用户只能查询自己的配额。tenant_id 自动注入确保数据隔离（INV-1）。
- **兼容性**: 旧 API 路径（`/role/add`、`/role/list`、`/role/{id}`、`/role_access/refresh`、`/role_access/list`）保持功能正常，内部委托新 RoleService 实现。`group_id` 和 `knowledge_space_file_limit` 字段保留但标记 deprecated。
- **可观测性**: 角色创建/修改/删除操作写入审计日志（复用 AuditLogService）。配额超限事件记录 WARNING 级别日志。

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- 前序 Feature: F001(multi-tenant-core), F002(department-tree), F004(rebac-core)
