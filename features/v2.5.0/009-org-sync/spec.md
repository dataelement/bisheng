# Feature: 三方组织同步

> **前置步骤**：本文档编写前已完成 Spec Discovery（架构师提问），
> PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3.2.1](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P2
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- OrgSyncProvider 抽象基类（authenticate/fetch_departments/fetch_members/test_connection）
- FeishuProvider 完整实现（飞书开放平台通讯录 API）
- GenericAPIProvider 完整实现（可配置端点 + 字段映射）
- WeComProvider / DingTalkProvider stub（骨架 + NotImplementedError）
- OrgSyncConfig ORM（provider/auth_type/auth_config/sync_scope/schedule/sync_status/tenant_id）
- OrgSyncLog ORM（执行历史/状态/统计/错误详情）
- 两种认证模式：API Key + 账号密码（OAuth 字段保留标记 coming_soon）
- 同步调和引擎 Reconciler：部门差异（新增/重命名/层级变更/归档）+ 人员差异（新增/信息变更/转岗/离职/重新激活）
- 同步编排服务 OrgSyncService：认证 → 拉取 → 调和 → 执行 → 记录
- OpenFGA 元组自动维护（通过 DepartmentChangeHandler，遵守 INV-4）
- Celery 异步执行 + Beat 定时调度（复用 knowledge_celery 队列）
- User 表扩展：source + external_id 字段（与 Department 模型一致）
- 同步创建的用户不设可用密码，仅支持 SSO 登录
- 9 个 API 端点：配置 CRUD(5) + 测试连接 + 手动触发 + 同步历史 + 远程树预览
- 并发保护：DB sync_status + Redis 分布式锁
- 错误码模块 220（22000~22009）

**OUT**:
- 前端配置页面（归后续 Feature）
- OAuth 回调流程（v2.5 不实现，字段保留）
- 实时 Webhook 同步（仅支持定时/手动触发）
- 企微/钉钉完整 Provider 实现（留 stub）

**关键文件（预判）**:
- 新建: `src/backend/bisheng/org_sync/`（DDD 模块：api/ + domain/）
- 新建: `src/backend/bisheng/common/errcode/org_sync.py`
- 新建: `src/backend/bisheng/worker/org_sync/tasks.py`
- 修改: `src/backend/bisheng/user/domain/models/user.py`（source/external_id）
- 修改: `src/backend/bisheng/api/router.py`（路由注册）

**关联不变量**: INV-1, INV-4, INV-8, INV-12

---

## 1. 概述与用户故事

F009 为 BiSheng 引入第三方组织架构同步能力。企业可将飞书/企微/钉钉等平台中的部门树和员工信息同步到 BiSheng，自动创建部门、用户、部门成员关系，并维护 OpenFGA 权限元组。支持手动触发和 Cron 定时同步。

同步引擎采用 **Provider + Reconciler** 架构：Provider 负责从第三方拉取标准化 DTO，Reconciler 负责与本地数据对比产出差异操作列表，OrgSyncService 编排整个流程。

**用户故事 1**:
作为 **BiSheng 系统管理员**，
我希望 **能配置飞书通讯录同步（填写应用凭证、选择同步范围、设置定时计划）**，
以便 **企业现有组织架构自动同步到 BiSheng，无需手动逐个创建部门和用户**。

**用户故事 2**:
作为 **BiSheng 系统管理员**，
我希望 **手动触发一次同步并查看同步结果（成功/部分失败/完全失败、具体统计）**，
以便 **在首次配置或排查问题时能精确掌控同步过程**。

**用户故事 3**:
作为 **BiSheng 系统管理员**，
我希望 **同步时自动处理人员调岗（主部门变更、附属部门增减）和离职（禁用账号、清理权限）**，
以便 **组织变动后权限自动调整，无需手动干预**。

**用户故事 4**:
作为 **BiSheng 后续 Feature 开发者**，
我希望 **新增第三方 Provider 时只需实现 OrgSyncProvider 接口（4 个方法），无需修改同步引擎逻辑**，
以便 **扩展新数据源成本低、风险小**。

**用户故事 5**:
作为 **多租户环境下的租户管理员**，
我希望 **配置本租户的组织同步，同步结果仅影响本租户的部门和用户**，
以便 **租户间数据完全隔离**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 配置管理

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | POST /api/v1/org-sync/configs（provider=feishu, auth_type=api_key, auth_config={app_id, app_secret}） | 返回 200，data 含 id/provider/config_name/auth_type/status，auth_config 中敏感字段已脱敏 |
| AC-02 | 管理员 | POST 创建同 provider + 同 config_name 的配置 | 返回 22001 OrgSyncConfigDuplicateError |
| AC-03 | 管理员 | GET /api/v1/org-sync/configs | 返回当前租户所有配置列表，auth_config 敏感字段脱敏（app_secret 显示 `****`） |
| AC-04 | 管理员 | GET /api/v1/org-sync/configs/{id} | 返回配置详情（同 AC-03 脱敏规则） |
| AC-05 | 管理员 | PUT /api/v1/org-sync/configs/{id}（修改 cron_expression） | 返回更新后的配置 |
| AC-06 | 管理员 | PUT 更新 auth_config 时仅传部分字段（如只改 app_secret） | 合并更新，未传的字段保持原值 |
| AC-07 | 管理员 | DELETE /api/v1/org-sync/configs/{id} | 返回 200，config.status='deleted'（软删除） |
| AC-08 | 管理员 | 操作其他租户的 config_id | 返回 22000 OrgSyncConfigNotFoundError（tenant_id 不匹配） |

### 连接测试

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-09 | 管理员 | POST /api/v1/org-sync/configs/{id}/test（凭证正确） | 返回 200，data 含 connected=true, org_name, total_depts, total_members |
| AC-10 | 管理员 | POST test（凭证错误） | 返回 22002 OrgSyncAuthFailedError，包含 provider 返回的错误信息 |

### 远程树预览

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-11 | 管理员 | GET /api/v1/org-sync/configs/{id}/remote-tree | 返回第三方组织架构树（嵌套结构），每个节点含 external_id/name/children |
| AC-12 | 管理员 | GET remote-tree（Provider 未实现） | 返回 22004 OrgSyncProviderError，msg="Provider not implemented" |

### 同步执行

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-13 | 管理员 | POST /api/v1/org-sync/configs/{id}/execute | 返回 200，data 含 log_id，后台 Celery 任务开始执行 |
| AC-14 | 管理员 | POST execute（config 正在同步中） | 返回 22003 OrgSyncAlreadyRunningError |
| AC-15 | 管理员 | POST execute（config.status='disabled'） | 返回 22009 OrgSyncConfigDisabledError |

### 部门同步

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-16 | 系统 | 同步时远程有新部门（external_id 不在本地） | 自动创建 Department（source=provider, external_id=远程ID），path 正确，DepartmentChangeHandler.on_created 触发 OpenFGA 写入 |
| AC-17 | 系统 | 远程部门名称变更（本地 source=第三方） | 更新 Department.name |
| AC-18 | 系统 | 远程部门名称变更（本地 source=local） | 强制覆盖 name，将 source 改为第三方，external_id 写入 |
| AC-19 | 系统 | 远程部门层级变更（parent 变化） | 更新 parent_id + path（含子树），DepartmentChangeHandler.on_moved 触发 |
| AC-20 | 系统 | 远程部门在本次同步中消失（本地为第三方来源） | Department.status 设为 'archived'，清空成员（保留 admin），DepartmentChangeHandler.on_archived 触发 |
| AC-21 | 系统 | 被归档部门下挂有本地创建的子部门 | 子部门也被归档 |

### 人员同步

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-22 | 系统 | 远程有新员工（external_id 不在本地） | 创建 User（source=provider, external_id, password=随机哈希），创建 UserTenant，创建 UserDepartment（主+附属），DepartmentChangeHandler.on_members_added 触发 |
| AC-23 | 系统 | 新创建的同步用户尝试密码登录 | 登录失败（随机密码不可猜测），必须通过 SSO |
| AC-24 | 系统 | 远程员工信息变更（姓名/邮箱/手机） | 更新 User 对应字段 |
| AC-25 | 系统 | 远程员工主部门变更 | 更新 UserDepartment.is_primary，原主部门 member 元组删除 + 新主部门 member 元组写入 |
| AC-26 | 系统 | 远程员工附属部门增减 | 新增附属：创建 UserDepartment + member 元组；移除附属：删除 UserDepartment + member 元组 |
| AC-27 | 系统 | 远程员工离职/禁用 或 从同步名单消失 | User.delete=1（禁用），清理所有 UserDepartment + member 元组 |
| AC-28 | 系统 | 之前被禁用的同步用户重新出现在远程名单 | User.delete=0（重新激活），重建 UserDepartment + member 元组 |

### 同步历史

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-29 | 管理员 | GET /api/v1/org-sync/configs/{id}/logs?page=1&limit=20 | 返回分页同步日志列表（PageData），含 status/统计/start_time/end_time |
| AC-30 | 管理员 | 查看部分失败的同步日志详情 | error_details 包含每条失败记录的 entity_type/external_id/error_msg |

### 定时同步

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-31 | 系统 | 设置 schedule_type=cron, cron_expression="0 2 * * *"（每日凌晨2点） | Beat 任务在匹配时间自动触发同步，生成 trigger_type='scheduled' 的日志 |
| AC-32 | 系统 | Config.status='disabled' 的定时任务 | 不触发，跳过 |

### 权限与安全

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-33 | 非管理员 | 调用任何 org-sync API | 返回 22005 OrgSyncPermissionDeniedError |
| AC-34 | 管理员 | 读取配置时查看 auth_config | app_secret/api_key/password 字段显示为 `****`，不返回明文 |

---

## 3. 边界情况

- 当 **飞书 API 返回分页数据**时，Provider 自动处理 page_token 循环直到无更多数据
- 当 **飞书 API 限流（HTTP 429）**时，Provider 指数退避重试（最多 3 次，间隔 1s/2s/4s）
- 当 **同步过程中部分操作失败**（如某部门创建失败），引擎跳过该条继续处理其余，最终 OrgSyncLog.status='partial'，error_details 记录失败明细
- 当 **同步正在运行时进程崩溃**，Redis 锁 TTL(30min) 过期后自动释放，config.sync_status 可通过手动 API 或下次同步前的健康检查重置
- 当 **远程部门树存在循环引用**时（极少见），Reconciler 的拓扑排序检测到循环后记录错误并跳过受影响的子树
- 当 **同名部门在同一父级下冲突**时（远程创建的部门名称与本地已有部门重名），创建时捕获 DepartmentNameDuplicateError，记入 error_details，不中断同步
- 当 **User.external_id 唯一约束冲突**时（同一 source + external_id 已存在），走更新逻辑而非创建
- 当 **同步范围（sync_scope）为空或 null** 时，同步全部远程部门和人员
- 当 **GenericAPI 返回不符合标准 DTO 格式的 JSON** 时，Provider 返回 OrgSyncFetchError 并附带原始响应摘要
- 当 **multi_tenant.enabled=false** 时，所有配置和同步操作正常工作，tenant_id 自动填充为默认租户(id=1)
- 当 **Celery Worker 未启动** 时，手动触发的任务进入队列等待，API 立即返回 log_id（异步）
- **不支持**：双向同步（BiSheng → 第三方）、实时 Webhook 推送、OAuth 回调认证

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 模块结构 | A: DDD 独立模块 `org_sync/` / B: 放入 `user/` 下 | 选 A | 与 department/ 一致的 DDD 模式，独立模块利于维护和扩展 |
| AD-02 | auth_config 加密 | A: Fernet / B: AES-256 / C: 明文 | 选 A | 复用 settings.secret_key 的 Fernet 加密，与数据库密码加密方式一致 |
| AD-03 | Celery 队列选择 | A: 复用 knowledge_celery / B: 新建 org_sync_celery | 选 A | 同步频率低（每日 1-2 次），无需独立队列。knowledge_celery 有 20 线程余量 |
| AD-04 | 并发保护方案 | A: DB sync_status 仅 / B: Redis 锁仅 / C: 双重 | 选 C | DB 保证持久性，Redis 锁保证进程崩溃后自动释放（TTL 30min） |
| AD-05 | OpenFGA 元组维护 | A: 直接调 PermissionService / B: 通过 DepartmentChangeHandler | 选 B | 尊重领域边界（release-contract 规定 PermissionTuple Owner 是 F004），Handler 已处理好元组格式 |
| AD-06 | User 外部 ID 存储 | A: User 表加 source+external_id / B: UserLink 关联 | 选 A | 与 Department 模型一致，查询更直接（单表索引），reconcile 匹配性能更好 |
| AD-07 | 同步用户密码策略 | A: 随机密码+强制改密 / B: 不设密码仅 SSO / C: 统一默认密码 | 选 B | 用户确认。password 字段填入 64 位随机哈希（不可猜测），用户只能通过 SSO 登录 |
| AD-08 | Provider 实现优先级 | A: 四个全做 / B: 飞书+通用API / C: 仅飞书 | 选 B | 用户确认。飞书覆盖国内主流场景，通用 API 覆盖长尾需求。企微/钉钉留 stub |
| AD-09 | v2.5 认证模式 | A: 三种全做 / B: API Key + 密码 | 选 B | 用户确认。飞书/钉钉/企微均支持 App ID + App Secret 获取 tenant_access_token，无需 OAuth 回调 |
| AD-10 | 定时调度实现 | A: Celery Beat 静态配置 / B: Beat 检查任务动态调度 | 选 B | 配置可随时增删改，静态配置需重启 Worker。Beat 每 60s 运行 check_org_sync_schedules 检查活跃 cron 配置 |
| AD-11 | 同步绕过 DepartmentService | A: 调用 DepartmentService 公共方法 / B: 直接操作 DAO + ChangeHandler | 选 B | 同步是系统级操作（无 login_user 上下文），需绕过 `_check_permission()` 和 `source_readonly` 检查。直接操作 DAO 保证同步可更新任何 source 的部门，同时通过 ChangeHandler 保证 OpenFGA 元组一致性（INV-4） |
| AD-12 | auth_config 存储策略 | A: 每种 auth_type 独立存储 / B: 单一 JSON blob | 选 B | PRD 原文要求"三种授权模式互不覆盖"，但 v2.5 只支持 API Key + 密码两种模式（AD-09），且每个 OrgSyncConfig 绑定单一 auth_type。切换 auth_type 时创建新配置而非修改现有配置，因此无需多模式并存。如未来引入 OAuth 需要并存，可扩展为 JSON 内 per-type 子对象 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

#### org_sync_config 表

```python
class OrgSyncConfig(SQLModelSerializable, table=True):
    __tablename__ = 'org_sync_config'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
            comment='Tenant ID',
        ),
    )
    provider: str = Field(
        sa_column=Column(
            String(32), nullable=False,
            comment='Provider: feishu/wecom/dingtalk/generic_api',
        ),
    )
    config_name: str = Field(
        sa_column=Column(
            String(128), nullable=False,
            comment='User-given label, e.g. Feishu Production',
        ),
    )
    auth_type: str = Field(
        sa_column=Column(
            String(16), nullable=False,
            comment='Auth mode: api_key/password (oauth reserved)',
        ),
    )
    auth_config: str = Field(
        sa_column=Column(
            Text, nullable=False,
            comment='Fernet-encrypted JSON: credentials per auth_type',
        ),
    )
    sync_scope: Optional[dict] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Sync scope: {"root_dept_ids": ["id1","id2"]} or null=all',
        ),
    )
    schedule_type: str = Field(
        default='manual',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'manual'"),
            comment='Execution mode: manual/cron',
        ),
    )
    cron_expression: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(64), nullable=True,
            comment='Cron expression, e.g. 0 2 * * *',
        ),
    )
    sync_status: str = Field(
        default='idle',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'idle'"),
            comment='Runtime mutex: idle/running',
        ),
    )
    last_sync_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, comment='Last sync time'),
    )
    last_sync_result: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(16), nullable=True,
            comment='Last sync result: success/partial/failed',
        ),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"), index=True,
            comment='Config status: active/disabled/deleted',
        ),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Creator user ID'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('tenant_id', 'provider', 'config_name',
                         name='uk_tenant_provider_name'),
    )
```

**auth_config 加密 JSON 结构**:
```json
// auth_type = "api_key" (飞书/钉钉/企微)
{
    "app_id": "cli_xxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxx"
}

// auth_type = "password" (LDAP / 通用)
{
    "server_addr": "https://api.example.com",
    "username": "admin",
    "password": "xxxxx"
}

// auth_type = "api_key" (通用API)
{
    "endpoint_url": "https://api.example.com/org",
    "api_key": "sk-xxxxxxxx",
    "param_location": "header"  // "header" | "query"
}
```

#### org_sync_log 表

```python
class OrgSyncLog(SQLModelSerializable, table=True):
    __tablename__ = 'org_sync_log'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
        ),
    )
    config_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, index=True,
            comment='FK to org_sync_config.id',
        ),
    )
    trigger_type: str = Field(
        sa_column=Column(
            String(16), nullable=False,
            comment='Trigger: manual/scheduled',
        ),
    )
    trigger_user: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True,
            comment='User who triggered (null for scheduled)',
        ),
    )
    status: str = Field(
        default='running',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'running'"),
            comment='Status: running/success/partial/failed',
        ),
    )
    dept_created: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    dept_updated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    dept_archived: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_created: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_updated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_disabled: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_reactivated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    error_details: Optional[list] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Error list: [{entity_type, external_id, error_msg}]',
        ),
    )
    start_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    end_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
```

#### User 表扩展

在现有 `User` 模型（`user/domain/models/user.py`）中新增：

```python
source: str = Field(
    default='local',
    sa_column=Column(
        String(32), nullable=False,
        server_default=text("'local'"),
        comment='Source: local/feishu/wecom/dingtalk/generic_api',
    ),
)
external_id: Optional[str] = Field(
    default=None,
    sa_column=Column(
        String(128), nullable=True,
        comment='External employee ID for sync',
    ),
)
```

唯一约束：`UniqueConstraint('source', 'external_id', name='uk_user_source_external_id')`
（与 Department 模型的 `uk_source_external_id` 一致）

### Domain 模型 / DTO

```python
# org_sync/domain/schemas/remote_dto.py

@dataclass
class RemoteDepartmentDTO:
    """Standard DTO for a department fetched from a third-party provider."""
    external_id: str
    name: str
    parent_external_id: Optional[str]  # None = root
    sort_order: int = 0

@dataclass
class RemoteMemberDTO:
    """Standard DTO for an employee fetched from a third-party provider."""
    external_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    primary_dept_external_id: str = ''
    secondary_dept_external_ids: list[str] = field(default_factory=list)
    status: str = 'active'  # active / disabled
```

### DAO 方法

| 类 | 方法 | 说明 |
|----|------|------|
| OrgSyncConfigDao | `acreate(config)` | 插入配置 |
| OrgSyncConfigDao | `aget_by_id(id)` | 按 ID 查询 |
| OrgSyncConfigDao | `aget_list(tenant_id, status)` | 列表查询 |
| OrgSyncConfigDao | `aupdate(config)` | 更新配置 |
| OrgSyncConfigDao | `aset_sync_status(id, status)` | 原子更新 sync_status |
| OrgSyncConfigDao | `aget_active_cron_configs()` | 查询 schedule_type=cron + status=active 的配置 |
| OrgSyncLogDao | `acreate(log)` | 插入日志 |
| OrgSyncLogDao | `aupdate(log)` | 更新日志（完成时写入统计） |
| OrgSyncLogDao | `aget_by_config(config_id, page, limit)` | 分页查询某配置的日志 |
| UserDao (扩展) | `aget_by_source_external_id(source, external_id)` | 按 source+external_id 查用户 |
| UserDao (扩展) | `aget_by_source(source, tenant_id)` | 查某来源全部用户（用于 reconcile） |

---

## 6. API 契约

### 6.1 创建同步配置

```
POST /api/v1/org-sync/configs
Auth: UserPayload (admin only)
```

**Request Body**:
```json
{
    "provider": "feishu",
    "config_name": "飞书生产环境",
    "auth_type": "api_key",
    "auth_config": {
        "app_id": "cli_xxxxxxxx",
        "app_secret": "xxxxxxxxxxxxxxxx"
    },
    "sync_scope": {"root_dept_ids": ["od-xxxxxxxx"]},
    "schedule_type": "cron",
    "cron_expression": "0 2 * * *"
}
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "id": 1,
        "provider": "feishu",
        "config_name": "飞书生产环境",
        "auth_type": "api_key",
        "auth_config": {"app_id": "cli_xxxxxxxx", "app_secret": "****"},
        "sync_scope": {"root_dept_ids": ["od-xxxxxxxx"]},
        "schedule_type": "cron",
        "cron_expression": "0 2 * * *",
        "sync_status": "idle",
        "status": "active",
        "create_time": "2026-04-13T10:00:00"
    }
}
```

### 6.2 查询配置列表

```
GET /api/v1/org-sync/configs
Auth: UserPayload (admin only)
```

**Response** (200): 数组，每项同 6.1 响应格式（auth_config 脱敏）

### 6.3 查询配置详情

```
GET /api/v1/org-sync/configs/{id}
Auth: UserPayload (admin only)
```

**Response** (200): 单项，同 6.1 响应格式

### 6.4 更新配置

```
PUT /api/v1/org-sync/configs/{id}
Auth: UserPayload (admin only)
```

**Request Body**（partial update，仅传需要修改的字段）:
```json
{
    "auth_config": {"app_secret": "new_secret_value"},
    "schedule_type": "manual",
    "cron_expression": null
}
```

**约束**: auth_config 为合并更新（merge），未传字段保持原值。更新时解密原配置 → 合并 → 重新加密。

### 6.5 删除配置

```
DELETE /api/v1/org-sync/configs/{id}
Auth: UserPayload (admin only)
```

**约束**: 软删除（status='deleted'）。正在同步中的配置不可删除（返回 22003）。

### 6.6 测试连接

```
POST /api/v1/org-sync/configs/{id}/test
Auth: UserPayload (admin only)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "connected": true,
        "org_name": "毕昇科技",
        "total_depts": 25,
        "total_members": 150
    }
}
```

### 6.7 手动触发同步

```
POST /api/v1/org-sync/configs/{id}/execute
Auth: UserPayload (admin only)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "log_id": 42,
        "message": "Sync task dispatched"
    }
}
```

**约束**: 异步执行。API 返回后 Celery 后台运行。config.sync_status 变为 'running'。

### 6.8 查询同步历史

```
GET /api/v1/org-sync/configs/{id}/logs?page=1&limit=20
Auth: UserPayload (admin only)
```

**Response** (200, PageData):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": {
        "data": [
            {
                "id": 42,
                "config_id": 1,
                "trigger_type": "manual",
                "trigger_user": 1,
                "status": "success",
                "dept_created": 5,
                "dept_updated": 2,
                "dept_archived": 0,
                "member_created": 30,
                "member_updated": 5,
                "member_disabled": 1,
                "member_reactivated": 0,
                "error_details": null,
                "start_time": "2026-04-13T02:00:00",
                "end_time": "2026-04-13T02:01:30"
            }
        ],
        "total": 1
    }
}
```

### 6.9 远程组织树预览

```
GET /api/v1/org-sync/configs/{id}/remote-tree
Auth: UserPayload (admin only)
```

**Response** (200):
```json
{
    "status_code": 200,
    "status_message": "success",
    "data": [
        {
            "external_id": "od-root",
            "name": "毕昇科技",
            "children": [
                {
                    "external_id": "od-dev",
                    "name": "研发部",
                    "children": []
                },
                {
                    "external_id": "od-sales",
                    "name": "销售部",
                    "children": []
                }
            ]
        }
    ]
}
```

**约束**: 同步调用 Provider，可能耗时较长（大组织 5-10 秒），建议前端加 loading 态。

### 错误码表

> 模块编码 220（org_sync），已在 release-contract.md 注册。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 22000 | OrgSyncConfigNotFoundError | 配置 ID 不存在或不属于当前租户 | AC-08 |
| 200 (body) | 22001 | OrgSyncConfigDuplicateError | 同 provider + config_name 已存在 | AC-02 |
| 200 (body) | 22002 | OrgSyncAuthFailedError | Provider 认证失败 | AC-10 |
| 200 (body) | 22003 | OrgSyncAlreadyRunningError | 该配置正在同步中 | AC-14 |
| 200 (body) | 22004 | OrgSyncProviderError | Provider API 错误或未实现 | AC-12 |
| 200 (body) | 22005 | OrgSyncPermissionDeniedError | 无组织同步操作权限 | AC-33 |
| 200 (body) | 22006 | OrgSyncInvalidConfigError | 配置字段缺失或不合法 | AC-01 |
| 200 (body) | 22007 | OrgSyncFetchError | 从 Provider 拉取数据失败 | AC-11 |
| 200 (body) | 22008 | OrgSyncReconcileError | 调和过程中发生不可恢复错误 | — |
| 200 (body) | 22009 | OrgSyncConfigDisabledError | 配置已禁用 | AC-15 |

---

## 7. Service 层逻辑

### OrgSyncProvider（抽象基类）

文件：`org_sync/domain/providers/base.py`

```python
class OrgSyncProvider(ABC):
    def __init__(self, auth_config: dict): ...

    @abstractmethod
    async def authenticate(self) -> bool: ...

    @abstractmethod
    async def fetch_departments(self, root_dept_ids: list[str] | None = None) -> list[RemoteDepartmentDTO]: ...

    @abstractmethod
    async def fetch_members(self, department_ids: list[str] | None = None) -> list[RemoteMemberDTO]: ...

    @abstractmethod
    async def test_connection(self) -> dict: ...
```

工厂方法：`get_provider(provider: str, auth_config: dict) -> OrgSyncProvider`

### FeishuProvider

文件：`org_sync/domain/providers/feishu.py`

| 方法 | 飞书 API | 说明 |
|------|---------|------|
| authenticate | POST /auth/v3/tenant_access_token/internal | 用 app_id + app_secret 换取 tenant_access_token |
| fetch_departments | GET /contact/v3/departments + /children | BFS 遍历，支持 scope 过滤 |
| fetch_members | GET /contact/v3/users?department_id=X | 按部门逐个拉取，page_token 分页 |
| test_connection | authenticate + GET /contact/v3/departments/0 | 验证连接并获取根部门信息 |

关键实现：
- 使用 `httpx.AsyncClient` 发送请求
- token 缓存 2 小时（飞书 token 有效期 2h）
- 限流保护：asyncio.Semaphore(5) 控制并发请求数
- 429 响应指数退避重试（1s/2s/4s，最多 3 次）

### GenericAPIProvider

文件：`org_sync/domain/providers/generic_api.py`

auth_config 中额外配置：
```json
{
    "departments_url": "https://api.example.com/departments",
    "members_url": "https://api.example.com/members",
    "api_key": "sk-xxx",
    "param_location": "header",
    "field_mapping": {
        "dept_id": "id",
        "dept_name": "name",
        "dept_parent_id": "parentId",
        "member_id": "employeeId",
        "member_name": "fullName",
        "member_email": "email",
        "member_phone": "mobile",
        "member_primary_dept": "mainDepartment",
        "member_secondary_depts": "otherDepartments",
        "member_status": "status"
    }
}
```

标准响应格式：
```json
// GET departments_url
{"departments": [{"id": "D001", "name": "研发部", "parentId": null}, ...]}
// GET members_url
{"members": [{"employeeId": "E001", "fullName": "张三", ...}, ...]}
```

### Reconciler（差异比较引擎）

文件：`org_sync/domain/services/reconciler.py`

纯逻辑类，无 IO 依赖，接受数据产出操作列表。

#### reconcile_departments

```
输入: remote_depts: list[RemoteDepartmentDTO], local_depts: list[Department], source: str
输出: list[DeptOperation]

DeptOperation = CreateDept | UpdateDept | MoveDept | ArchiveDept
```

逻辑：
1. 构建 remote_map（external_id → DTO）和 local_map（external_id → Department，按 source 过滤）
2. **创建**：remote_map 中有但 local_map 中无 → CreateDept
3. **更新**：两边都有，name 不同 → UpdateDept
4. **移动**：两边都有，parent_external_id 对应的 local parent_id 不同 → MoveDept
5. **归档**：local_map 中有但 remote_map 中无 → ArchiveDept（含子树）
6. **本地冲突**：如果某 local Department.source='local' 且 external_id 匹配远程 → 强制覆盖 + 改 source（PRD 明确要求）
7. 创建操作按拓扑序排列（父先于子），归档按逆序（子先于父）

#### reconcile_members

```
输入: remote_members: list[RemoteMemberDTO], local_users: list[User],
      local_user_depts: dict[int, list[UserDepartment]],
      ext_to_local_dept: dict[str, int], source: str
输出: list[MemberOperation]

MemberOperation = CreateMember | UpdateMember | TransferMember | DisableMember | ReactivateMember
```

逻辑：
1. 构建 remote_map（external_id → DTO）和 local_map（external_id → User，按 source 过滤）
2. **创建**：remote 有但 local 无 → CreateMember
3. **更新**：两边都有，name/email/phone 不同 → UpdateMember
4. **转岗**：primary_dept 变化 → TransferMember；secondary_depts 变化 → 增减 UserDepartment
5. **禁用**：local 有但 remote 无，或 remote.status='disabled' → DisableMember
6. **重新激活**：local 有且 delete=1，但 remote.status='active' → ReactivateMember
7. **本地冲突**：User.source='local' 但 external_id 匹配 → 强制覆盖 + 改 source

### OrgSyncService（同步编排器）

文件：`org_sync/domain/services/org_sync_service.py`

#### execute_sync(config_id, trigger_type, trigger_user)

主流程：

```
1. 加载 OrgSyncConfig → 解密 auth_config
2. 获取互斥锁:
   a. check config.sync_status == 'idle'
   b. 原子 UPDATE sync_status='running' WHERE sync_status='idle'（返回 affected=0 则已被占用）
   c. 获取 Redis 锁 bisheng:lock:org_sync:{config_id} (TTL=30min)
3. 创建 OrgSyncLog(status='running', start_time=now)
4. 实例化 Provider
5. provider.authenticate()
6. 拉取远程部门: provider.fetch_departments(sync_scope)
7. 加载本地部门: Department where source=provider and tenant_id=config.tenant_id
8. Reconciler.reconcile_departments() → dept_ops
9. 执行 dept_ops via _apply_dept_ops()
10. 拉取远程人员: provider.fetch_members()
11. 加载本地用户: User where source=provider and tenant_id (通过 UserTenant)
12. Reconciler.reconcile_members() → member_ops
13. 执行 member_ops via _apply_member_ops()
14. 更新 OrgSyncLog(status, statistics, end_time)
15. 更新 OrgSyncConfig(last_sync_at, last_sync_result)
16. 释放互斥锁(sync_status='idle', Redis unlock)
```

#### _apply_dept_ops

对每个操作：
- **CreateDept**: 创建 Department(source, external_id, name, parent_id, tenant_id) → DepartmentChangeHandler.on_created → execute_async
- **UpdateDept**: 更新 name（绕过 source_readonly 检查，因为我们就是同步来源）
- **MoveDept**: 更新 parent_id + path 批量替换 → DepartmentChangeHandler.on_moved → execute_async
- **ArchiveDept**: status='archived'，清空成员（保留 admin）→ DepartmentChangeHandler.on_archived → execute_async

注意：同步操作绕过 DepartmentService 的 `_check_permission()` 和 `source_readonly` 检查，因为同步是系统级操作，不是用户手动操作。通过内部方法直接操作 DAO + ChangeHandler。

#### _apply_member_ops

对每个操作：
- **CreateMember**: 创建 User(source, external_id, user_name, password=random_hash) → 创建 UserTenant → 创建 UserDepartment(主+附属) → DepartmentChangeHandler.on_members_added → 分配默认角色(department.default_role_ids)
- **UpdateMember**: 更新 User 字段(user_name, email, phone_number)
- **TransferMember**: 更新 UserDepartment 主部门 → 删除旧 member 元组 + 写入新 member 元组 → 附属部门增减
- **DisableMember**: User.delete=1 → 删除所有 UserDepartment → 删除所有 member 元组 → 清理 Redis 登录态
- **ReactivateMember**: User.delete=0 → 重建 UserDepartment → 重建 member 元组

### 权限检查

所有 API 端点要求管理员权限。使用 `LoginUser.access_check` 检查是否为系统管理员或租户管理员。

同步执行过程中的部门/用户操作是系统级行为，不经过 DepartmentService 的权限检查（直接操作 DAO + ChangeHandler）。

### Celery 任务

```python
# worker/org_sync/tasks.py

@bisheng_celery.task(acks_late=True, time_limit=1800, soft_time_limit=1500)
def execute_org_sync(config_id, trigger_type, trigger_user=None):
    """Async sync execution. Tenant context via INV-8."""
    ...

@bisheng_celery.task(acks_late=True)
def check_org_sync_schedules():
    """Beat task: check cron configs and dispatch if due. Runs every 60s."""
    ...
```

task routing: `"bisheng.worker.org_sync.*": {"queue": "knowledge_celery"}`

Beat schedule 新增: `check_org_sync_schedules` 每 60 秒执行一次

---

## 8. 前端设计

N/A — F009 不涉及前端变更。配置管理 UI 归后续 Feature。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/org_sync/__init__.py` | DDD 模块包 |
| `src/backend/bisheng/org_sync/api/__init__.py` | API 子包 |
| `src/backend/bisheng/org_sync/api/router.py` | 路由聚合，prefix `/org-sync` |
| `src/backend/bisheng/org_sync/api/endpoints/__init__.py` | 端点子包 |
| `src/backend/bisheng/org_sync/api/endpoints/sync_config.py` | 配置 CRUD 端点 (5 个) |
| `src/backend/bisheng/org_sync/api/endpoints/sync_exec.py` | 执行/测试/历史/远程树端点 (4 个) |
| `src/backend/bisheng/org_sync/domain/__init__.py` | 领域子包 |
| `src/backend/bisheng/org_sync/domain/models/__init__.py` | 模型子包 |
| `src/backend/bisheng/org_sync/domain/models/org_sync.py` | OrgSyncConfig + OrgSyncLog ORM + DAO |
| `src/backend/bisheng/org_sync/domain/schemas/__init__.py` | DTO 子包 |
| `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py` | 请求/响应 Pydantic DTO |
| `src/backend/bisheng/org_sync/domain/schemas/remote_dto.py` | RemoteDepartmentDTO + RemoteMemberDTO |
| `src/backend/bisheng/org_sync/domain/services/__init__.py` | 服务子包 |
| `src/backend/bisheng/org_sync/domain/services/org_sync_service.py` | 同步编排器 |
| `src/backend/bisheng/org_sync/domain/services/reconciler.py` | 差异比较引擎 |
| `src/backend/bisheng/org_sync/domain/providers/__init__.py` | Provider 子包 |
| `src/backend/bisheng/org_sync/domain/providers/base.py` | OrgSyncProvider ABC + 工厂方法 |
| `src/backend/bisheng/org_sync/domain/providers/feishu.py` | 飞书 Provider（完整） |
| `src/backend/bisheng/org_sync/domain/providers/wecom.py` | 企微 Provider（stub） |
| `src/backend/bisheng/org_sync/domain/providers/dingtalk.py` | 钉钉 Provider（stub） |
| `src/backend/bisheng/org_sync/domain/providers/generic_api.py` | 通用 API Provider（完整） |
| `src/backend/bisheng/common/errcode/org_sync.py` | 220xx 错误码 (10 个) |
| `src/backend/bisheng/worker/org_sync/__init__.py` | Worker 子包 |
| `src/backend/bisheng/worker/org_sync/tasks.py` | Celery 任务 |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f009_org_sync.py` | 数据库迁移 |
| `src/backend/test/test_org_sync_reconciler.py` | Reconciler 单元测试 |
| `src/backend/test/test_org_sync_api.py` | API 集成测试 |
| `src/backend/test/e2e/test_e2e_org_sync.py` | E2E 测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/api/router.py` | 导入并注册 `org_sync_router` |
| `src/backend/bisheng/user/domain/models/user.py` | User 类新增 source/external_id 字段 + UserDao 新增 aget_by_source_external_id/aget_by_source |
| `src/backend/bisheng/worker/__init__.py` | 导入 org_sync tasks |
| `src/backend/bisheng/core/config/settings.py` | CeleryConf.task_routes 增加 org_sync 路由，beat_schedule 增加 check_org_sync_schedules |

---

## 10. 非功能要求

- **性能**: 同步 1000 部门 + 10000 人员应在 5 分钟内完成。Provider 请求并发控制（Semaphore=5），避免触发第三方限流。本地数据批量查询（一次性加载全部 active 部门/用户到内存 map），避免 N+1 查询
- **安全**: auth_config Fernet 加密存储，API 响应脱敏。所有端点要求管理员权限。tenant_id 自动过滤（INV-1）防止跨租户数据泄漏
- **可靠性**: 部分失败不中断整体同步，错误详情记入 OrgSyncLog。OpenFGA 双写失败记入 FailedTuple 补偿表（INV-4）。进程崩溃后 Redis 锁 30 分钟自动释放
- **兼容性**: User 表新增字段均有默认值（source='local', external_id=NULL），存量用户不受影响。单租户模式行为不变
- **可扩展性**: OrgSyncProvider 是扩展点，新增 Provider 只需实现 4 个方法 + 注册到工厂。Reconciler 是纯逻辑可独立测试
- **可测试性**: Reconciler 无 IO 依赖，可直接单元测试。Provider 可 mock。API 测试使用 TestClient

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
- 部门树 spec: `features/v2.5.0/002-department-tree/spec.md`
