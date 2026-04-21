# Feature: F011-tenant-tree-model (Tenant 树数据模型 + 隔离策略重构)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §2 / §5.2
**优先级**: P0（阻塞全部 v2.5.1 feature）
**所属版本**: v2.5.1
**基线**: v2.5.0/F001 multi-tenant-core

---

## 1. 概述与用户故事

作为 **集团 IT 管理员**，
我希望 **Tenant 数据模型支持树形结构（Root + 0~N 个 Child 两层）表达"集团 + 子公司"私有化部署拓扑**，
以便 **集团内部子公司逻辑隔离 + 配额管控；社区版单租户作为"仅 Root 无 Child"的退化形态**。

核心变更：
- 扩展 `tenant` 表：新增 `parent_tenant_id` / `share_default_to_children` 字段（2026-04-20 精简：废弃 tenant_path/level/tenant_kind）
- 变更 `user_tenant` 语义：从多对多 → 唯一叶子快照
- **Root Tenant 由系统初始化自动创建**（tenant_id=1，不可删除/禁用/归档）
- 新增"子公司挂载"能力：全局超管在 UI 把部门树节点标记为 Child Tenant 挂载点
- 新增 `audit_log` 表（承载挂载/解绑/交接/禁用日志）
- Tenant.status 枚举增加 `orphaned`（挂载部门被 SSO 删除时进入）
- 23+ 张业务表的 `tenant_id` 过滤策略：从"严格相等" → "IN 列表（leaf + Root + shared_to）"

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 系统启动 | 首次部署执行迁移脚本 | 自动创建 Root Tenant：`tenant_id=1, parent_tenant_id=NULL, tenant_code='default'`；不需要任何用户/管理员手工 CRUD |
| AC-02 | 全局超管 | 对部门节点 D 发起 `POST /departments/{D}/mount-tenant` | 自动创建 Child Tenant（`parent_tenant_id=1`），Department `is_tenant_root=1, mounted_tenant_id=新Child.id` |
| AC-03 | 全局超管 | 尝试在 Child Tenant 下的部门再次挂载 | HTTP 400 错误码 `22001`，提示"MVP 锁 2 层，不支持嵌套" |
| AC-04a | 全局超管 | 对 Child Tenant 发起 `DELETE /departments/{D}/mount-tenant` 选 A（迁移到 Root） | 按顺序执行两步：① 子树资源 `tenant_id` 批量改为 Root ID（事务保证一致性）；② Child Tenant 自动置为 `archived`（资源已迁出，空 Tenant 仍保留 tenant 记录供审计追溯）；写 audit_log |
| AC-04b | 全局超管 | 解绑 Child 选 B（归档 Child） | Child Tenant 置为 `archived`，资源保留在 Child（不可访问）；写 audit_log |
| AC-04c | 全局超管 | 解绑 Child 选 C（手工） | Child Tenant 进入待处理状态；UI 跳转资源列表逐项确认；超管手工迁移每条资源后才能完成解绑。**UI 交互详细设计推迟到 UI 子 Feature**（MVP 阶段可先支持 API 逐条调用 F011 `/tenants/{id}/resources/reassign` 或复用 F018 交接 API） |
| AC-04d | 全局超管 | `POST /api/v1/tenants/{child_id}/resources/migrate-from-root` body `{resource_ids: [int], new_owner_user_id?: int}` | **资源下沉专用 API**（INV-T10：Root→Child 下沉不走 F018 transfer-owner）：① 权限校验仅全局超管（Child Admin 403 + `22010`）；② 校验每个 resource.tenant_id == 1（否则 400 + `22011` "仅支持 Root→Child 下沉"）；③ 事务内批量改 `tenant_id=child_id` + 重写 FGA owner 元组（可选 `new_owner_user_id` 重新授权 Child 内用户）；④ 写 audit_log（action=`resource.migrate_tenant`，metadata 含 from_tenant_id=1 / to_tenant_id=child_id / count / resource_ids）；⑤ 响应 `{migrated: N, failed: [{resource_id, reason}]}` |
| AC-05 | 升级管理员 | 升级脚本对存量数据回填 | tenant_id=1 的默认 Root 自动存在；所有业务表 `tenant_id=1`；audit_log 表创建成功；23+ 张表可查询正常 |
| AC-06 | 业务用户 | 查询资源列表时 | SQLAlchemy event 自动注入 `tenant_id IN (leaf, root, ...shared_to)` 过滤；跨 Tenant 资源不可见 |
| AC-07 | 全局超管 | 操作挂载/解绑动作 | audit_log 强制记录 operator/时间/子公司 ID/策略/配额，不可撤销；查询 API 返回历史 |
| AC-08 | 全局超管 | SSO 同步触发挂载部门被删除 | Child Tenant 进入 `orphaned` 状态；audit_log 记录 + 站内消息发给全局超管；不定义处理 SLA |
| AC-09 | 开发 | 对同一 user 尝试写入两条 `UserTenant(is_active=1)` | 唯一约束 `uk_user_active` 报错（MySQL 1062） |
| AC-10 | 业务用户 | Tenant 禁用时 | JWT 吊销；API 403；已入队 Celery 任务允许完成，新任务挂起不执行 |
| AC-11 | 全局超管 | 尝试 `PUT /api/v1/tenants/1/status` disabled / `DELETE /api/v1/tenants/1` / 归档 Root | HTTP 403 错误码 `22008` "Root Tenant 受系统保护，不可禁用/归档/删除" |
| AC-12 | 开发 | Tenant.status 取值 | 枚举包含 `active / disabled / archived / orphaned`；DDL 校验 |
| AC-13 | 开发 | 部署本 feature 后查询 | `audit_log` 表存在，含 tenant_id / operator_id / operator_tenant_id / action / target_type / target_id / reason / metadata / create_time 全部字段及索引 |
| AC-14 | 系统 | `department.is_deleted=1` 且 `mounted_tenant_id NOT NULL` | `DepartmentDeletionHandler.on_deleted(dept_id, source)` 自动触发 `Tenant.status='orphaned'` + 写 audit_log（action=`tenant.orphaned`，metadata 含 deletion_source）+ 发送站内消息/邮件给全局超管 |
| AC-15 | 开发 | `POST /api/v1/tenants` 请求 | HTTP 410 Gone；响应体 `{"error":"410 Gone","detail":"Root 由系统初始化自动创建（迁移时）；Child 通过 POST /api/v1/departments/{dept_id}/mount-tenant 创建"}` |

---

## 3. 边界情况

- **Root Tenant 永不可删除/禁用/归档**：API 层强制返回 403 + 错误码 22008（INV-T11，PRD §5.1.3）
- **空 Child Tenant 删除**：Child 物理删除前必须先清空资源或归档，否则 HTTP 409
- **挂载根部门**：不允许（根部门即 Root Tenant 默认挂载点）
- **MVP 锁 2 层**：写入时校验 `parent_tenant_id is NULL（Root）或 parent_tenant_id == 1（Child 指向 Root）`；禁止 Child 下挂载
- **孤儿 Tenant 长期未处理**：不自动清理，仅持续告警；客户外部流程承接（PRD §1.5）
- **不支持**：
  - 3+ 层嵌套（MVP 限制，v2.6+ 附录 G.4）
  - 子公司挂载的审批工作流（v2.6+ 附录 G.2）
  - 多 Root（仅私有化单实例，2026-04-20 收窄）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | Tenant 树表达方式 | A: 单表 parent_tenant_id / B: 物化路径 / C: 闭包表 | 选 A | 一张表 + 单字段表达 2 层拓扑；PRD §2 决策（2026-04-20 精简：去 tenant_path） |
| AD-02 | 树深度限制 | A: 锁 2 层 / B: 放开多层 | 选 A | MVP 锁 2 层，3+ 级集团客户拍平到 Child 同层（PRD Review P0-A） |
| AD-03 | user_tenant 语义 | A: 多对多 / B: 唯一叶子 | 选 B | 匹配集团"主部门归属"；PRD Review P0-C |
| AD-04 | tenant_id 过滤策略 | A: 严格相等 / B: IN 列表 | 选 B | 支持共享资源；leaf + Root + shared_to |
| AD-05 | 挂载决策权 | A: 双人审批 / B: 单人操作 | 选 B | MVP 克制；强制操作日志兜底（PRD Review P1-D1） |
| AD-06 | Root Tenant 创建方式 | A: API CRUD / B: 系统初始化自动 | 选 B | 仅私有化单实例，Root 由迁移脚本创建；保护不可删/禁（2026-04-20 收窄）|

---

## 5. 数据库 & Domain 模型

### 5.1 tenant 表字段扩展

```python
class Tenant(SQLModelSerializable, table=True):
    __tablename__ = "tenant"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_code: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    tenant_name: str = Field(sa_column=Column(String(128), nullable=False))
    root_dept_id: Optional[int] = Field(default=None)
    # status 枚举：active / disabled / archived / orphaned（2026-04-20 新增 orphaned）
    status: str = Field(default="active", sa_column=Column(String(16)))
    quota_config: Optional[dict] = Field(sa_column=Column(JSON))

    # v2.5.1 新增 Tenant 树字段（2026-04-20 精简：仅保留 parent_tenant_id + share_default_to_children）
    parent_tenant_id: Optional[int] = Field(default=None, sa_column=Column(INT_UNSIGNED, index=True))
    share_default_to_children: bool = Field(default=True)

    create_time / update_time: ...
```

**派生视图**（运行时计算，不入表）：
- 是 Root：`parent_tenant_id IS NULL`（本实例唯一）
- 是 Child：`parent_tenant_id IS NOT NULL`（MVP 下永远 = 1）
- Root 是否有 Child：`EXISTS(SELECT 1 FROM tenant WHERE parent_tenant_id = 1)`

### 5.2 user_tenant 唯一叶子约束

```sql
ALTER TABLE user_tenant
    ADD UNIQUE KEY uk_user_active (user_id, is_active);
-- 只允许同一 user 最多 1 条 is_active=1 记录
```

### 5.3 Department 扩展（已在 v2.5.0/F002 存在，本 Feature 使用）

```
Department.is_tenant_root    BOOLEAN DEFAULT 0
Department.mounted_tenant_id INT UNSIGNED NULL  -- FK → tenant.id
```

### 5.4 audit_log 表扩展（2026-04-20 新增；**与 v2.5.0 AuditLog 兼容扩展**）

**背景**：v2.5.0 已存在 `audit_log` 表（`src/backend/bisheng/database/models/audit_log.py`），字段：`operator_id / operator_name / group_ids / system_id / event_type / object_type / object_id / object_name / note / ip_address / create_time / update_time`。

**方案**：**ALTER 现表补充新字段**，旧字段保留供 v2.5.0 遗留代码兼容；新代码统一用新字段（`action / target_type / target_id / tenant_id / operator_tenant_id / reason / metadata`）。避免新建 `audit_log_v2` 导致两套审计系统分裂。

```sql
-- Alembic 迁移 v2_5_1_f011_audit_log_ext：对现有 audit_log 表追加字段
ALTER TABLE audit_log
    ADD COLUMN tenant_id          INT UNSIGNED  NULL       COMMENT '日志所属 Tenant（资源所在的叶子 Tenant）；v2.5.0 旧记录为 NULL',
    ADD COLUMN operator_tenant_id INT UNSIGNED  NULL       COMMENT '操作者叶子 Tenant（可与 tenant_id 不同，如全局超管跨 Child 操作）',
    ADD COLUMN action             VARCHAR(64)   NULL       COMMENT 'tenant.mount / quota.update / resource.transfer_owner / admin.scope_switch / llm.server.create 等（见 §5.4.2 清单）',
    ADD COLUMN target_type        VARCHAR(32)   NULL       COMMENT 'tenant / department / resource / user / llm_server / llm_model / resource_batch',
    ADD COLUMN target_id          VARCHAR(64)   NULL,
    ADD COLUMN reason             TEXT          NULL,
    ADD COLUMN metadata           JSON          NULL       COMMENT '扩展字段（如旧/新配额、涉及资源列表、from/to_scope 等）',
    ADD INDEX idx_tenant (tenant_id, create_time),
    ADD INDEX idx_action (action);
-- 注：idx_operator 索引已由 v2.5.0 创建，不重复添加
```

**字段填值规则**（v2.5.1 新代码必须遵守）：

- v2.5.1 新代码写入必填：`tenant_id` / `operator_id` / `operator_tenant_id` / `action` / `create_time`；`target_type` / `target_id` / `reason` / `metadata` 按需
- v2.5.0 旧代码路径：继续写 `system_id / event_type / object_type / object_id`，保持不变；新字段为 NULL
- **查询规则**：按新代码 action 查询用 `WHERE action = 'xxx'`；按旧代码 event_type 查用 `WHERE event_type = 'xxx'`；两者互不干扰
- `operator_tenant_id` 取值：
  - 普通用户 / Child Admin → `operator.leaf_tenant_id`
  - 全局超管（无 F019 scope） → 硬编码 `ROOT_TENANT_ID = 1`（INV-T11）
  - 全局超管（已设 F019 scope=X） → 填 scope 值 X（代表当前管理视图）
  - 系统触发（`operator_id=0`） → 硬编码 1 （Root）

**可见性规则**：
- 全局超管：跨 tenant_id 查全部
- Child admin：可见 `tenant_id = 本 Child` OR `operator_tenant_id = 本 Child`（能看到全局超管对本 Child 的操作）

### 5.4.1 DepartmentDeletionHandler（孤儿处理集中入口，2026-04-21 新增）

**动机**：部门删除可能由 SSO 实时同步（F014）、Celery 定时校对（F015）、人工操作触发。若删除的部门挂载了 Child Tenant，需统一走"Tenant orphaned + audit_log + 告警"流程，避免多 feature 分散实现。

**签名**：

```python
class DepartmentDeletionHandler:
    @classmethod
    async def on_deleted(cls, dept_id: int, deletion_source: str) -> None:
        """
        deletion_source: 'sso_realtime' | 'celery_reconcile' | 'manual'
        """
        dept = await DepartmentDao.aget(dept_id)
        if not dept or not dept.mounted_tenant_id:
            return  # 普通部门删除，无需处理

        # 1. Tenant 切为 orphaned
        await TenantDao.aupdate(id=dept.mounted_tenant_id, status='orphaned')

        # 2. 写 audit_log
        await AuditLogDao.acreate(
            tenant_id=dept.mounted_tenant_id,
            operator_id=0,  # 系统触发
            operator_tenant_id=1,
            action='tenant.orphaned',
            target_type='tenant',
            target_id=str(dept.mounted_tenant_id),
            metadata={'deletion_source': deletion_source, 'dept_id': dept_id},
        )

        # 3. 告警（站内消息 + 邮件）
        await NotificationService.notify_global_super_admins(
            title='子公司挂载点被删除',
            body=f'Child Tenant {dept.mounted_tenant_id} 因部门 {dept.name} 被 {deletion_source} 删除而进入 orphaned 状态，请尽快处理',
        )
```

**调用方**：

- F014（SSO 实时同步）：处理 `remove` 部门后调用 `on_deleted(dept_id, 'sso_realtime')`
- F015（Celery 校对）：冲突规则应用 remove 后调用 `on_deleted(dept_id, 'celery_reconcile')`
- F011 自身（解绑场景 AC-04）：策略 B 归档时 **不**触发此 handler（主动操作不算孤儿）

### 5.4.2 audit_log.action 取值清单（2026-04-21 新增）

所有写入 audit_log 的 feature 必须使用下表定义的 action 字符串，避免拼写不一致导致查询漏网：

| action | 写入 feature | 说明 |
|--------|-------------|------|
| `tenant.mount` | F011 | 挂载 Child Tenant |
| `tenant.unmount` | F011 | 解绑 Child Tenant |
| `tenant.disable` | F011 | 禁用 Child Tenant |
| `tenant.orphaned` | F011 (via F014/F015 触发) | Tenant 进入孤儿状态 |
| `quota.update` | F016 | 配额修改 |
| `resource.transfer_owner` | F018 | 所有者交接 |
| `resource.migrate_tenant` | F011 | Root → Child 资源下沉（新增） |
| `user.tenant_relocated` | F012 | 用户主部门变更引发归属切换（含 reason=no_primary_department 子场景） |
| `user.tenant_relocate_blocked` | F012 | 主部门变更被 enforce_transfer_before_relocate 阻断 |
| `dept.sync_conflict` | F015 | Gateway 实时 vs Celery 校对 ts 冲突 |
| `admin.scope_switch` | F019 | 全局超管管理视图切换（metadata: from_scope/to_scope/ip/user_agent） |
| `llm.server.create` | F020 | LLM Server 创建（metadata: endpoint/api_key_hash/model_count） |
| `llm.server.update` | F020 | LLM Server 更新（含 share 开关切换；metadata: changed_fields） |
| `llm.server.delete` | F020 | LLM Server 删除 |
| `llm.model.create` | F020 | LLM Model 创建 |
| `llm.model.update` | F020 | LLM Model 更新 |
| `llm.model.delete` | F020 | LLM Model 删除 |

新增 action 前必须先在此表登记并更新 INV-T7（强制留痕约束）。**开发过程中引入新 action 的 PR 需同步修改此表，作为 `/code-review` 强制检查项**。

### 5.4.3 TenantDao 扩展方法（F011 新增；供下游 Feature 调用）

下列三个 DAO 方法由本 Feature 在 `src/backend/bisheng/tenant/domain/models/tenant.py` 新增，所有在依赖清单中声明使用它们的下游 Feature 必须等待本 feature 落地后才能实施：

```python
class TenantDao:

    @classmethod
    async def aget_children_ids_active(cls, root_id: int) -> list[int]:
        """返回 parent_tenant_id = root_id 且 status='active' 的 Child Tenant id 清单。

        用于 F016 Root 用量聚合（INV-T9）：仅活跃 Child 计入，禁用/归档/孤儿不计。
        MVP 下 root_id 只可能是 1（Root），但保留参数形态便于未来 3+ 层扩展。
        """
        async with get_async_db_session() as session:
            stmt = select(Tenant.id).where(
                Tenant.parent_tenant_id == root_id,
                Tenant.status == 'active',
            )
            result = await session.exec(stmt)
            return list(result.all())

    @classmethod
    async def aget_non_active_ids(cls) -> list[int]:
        """返回所有 status IN ('disabled', 'archived', 'orphaned') 的 Tenant id 清单。

        用于 F019 Celery 巡检清理指向非活跃 Tenant 的 admin_scope Redis key。
        不含 active 状态；性能上 10 Child 规模一次查询即可。
        """
        async with get_async_db_session() as session:
            stmt = select(Tenant.id).where(
                Tenant.status.in_(['disabled', 'archived', 'orphaned'])
            )
            result = await session.exec(stmt)
            return list(result.all())

    @classmethod
    async def aexists(cls, tenant_id: int) -> bool:
        """检查 tenant_id 是否存在（任意状态）。

        用于 F019 `POST /admin/tenant-scope` body tenant_id 合法性校验
        （AC-15 指向不存在的 Tenant 返 400 + 19702）。
        """
        async with get_async_db_session() as session:
            stmt = select(func.count()).select_from(Tenant).where(Tenant.id == tenant_id)
            count = await session.exec(stmt)
            return count.scalar() > 0
```

**调用点登记**：

| 方法 | Caller Feature | 用途 |
|------|---------------|------|
| `aget_children_ids_active` | F016 | Root 用量聚合（`_aggregate_root_usage`） |
| `aget_non_active_ids` | F019 | Celery 巡检 `admin_scope_cleanup` |
| `aexists` | F019 | `TenantScopeService.set_scope` 合法性校验 |

### 5.5 Root Tenant 保护（API 层）

`PUT /api/v1/tenants/{id}/status` 与 `DELETE /api/v1/tenants/{id}`：
- 进入路由前先校验 `id == 1`（Root），命中则直接返回 403 + 错误码 22008，不进业务逻辑
- 全局超管也不能绕过
- `POST /api/v1/tenants` 已废弃（见 AC-15），返回 410 Gone；Root 由迁移脚本自动创建

**"禁用 Root 连带 Child" 死代码说明**（2026-04-21 新增）：原 PRD §5.1.3 描述的"禁用 Root 会连带禁用所有 Child"为防御性实现，因 INV-T11 Root 永不可禁用而**实际不会触发**；代码中保留此连带逻辑仅作 defense-in-depth（防止未来意外移除 Root 保护时仍保留连锁语义）。实施者无需为此路径写单元测试。

---

## 6. 23 张业务表改造清单（P2-H 决策要求）

> 2026-04-18 PRD Review 要求：本 Feature 必须逐表列出改造点与 checklist。

| # | 表名 | 模块 | tenant_id 状态 | IN 列表过滤注入点 | Checklist |
|---|------|------|--------------|-----------------|-----------|
| 1 | knowledge | knowledge | ✓ v2.5.0 已加 | `KnowledgeDao.get_list` | ☐ DAO 查询自动注入 IN 列表 ☐ 单元测试覆盖跨 Tenant 隔离 ☐ 共享资源读取（shared_to）可见 |
| 2 | knowledgefile | knowledge | ✓ | `KnowledgeFileDao.get_list` | 同上 |
| 3 | flow | workflow/assistant/workstation/linsight | ✓ | `FlowDao.get_list` | ☐ 按 flow_type 区分的各场景 ☐ 共享流向 Child |
| 4 | flow_version | workflow | ✓ | — | ☐ 随 flow 过滤 |
| 5 | assistant | assistant | ✓ | `AssistantDao.get_list` | 同 knowledge |
| 6 | assistant_link | assistant | ✓ | — | ☐ 级联 assistant tenant_id |
| 7 | t_gpts_tools | tool | ✓ | `ToolDao.get_list` | 同上 |
| 8 | channel | channel | ✓ | `ChannelDao.get_list` | 同上 + shared_to 共享 |
| 9 | chat_message | chat_session | ✓ | 自动注入 | ☐ 归属跟叶子 Tenant 走 |
| 10 | message_session | chat_session | ✓ | 自动注入 | ☐ 归属跟叶子 Tenant 走 |
| 11 | role | user | ✓ | `RoleDao.get_list` | ☐ 全局角色 tenant_id=0 特殊处理 |
| 12 | role_access | user | ✓ | `RoleAccessDao.get_list` | ☐ WEB_MENU 类型菜单权限 |
| 13 | user_role | user | ✓ | — | ☐ 随 user 归属 |
| 14 | `group` (UserGroup) | user | ✓ | `GroupDao.get_list` | ☐ 租户内唯一命名 |
| 15 | user_group_user | user | ✓ | — | ☐ 随 group 过滤 |
| 16 | department | user/permission | ✓ | `DepartmentDao.get_list` | ☐ 集团场景整棵树 ☐ tenant_id 由部门挂载关系派生 |
| 17 | user_department | user | ✓ | — | ☐ 用户主部门变更触发 UserTenantSync |
| 18 | tag | tag | ✓ | `TagDao.get_list` | — |
| 19 | tag_link | tag | ✓ | — | — |
| 20 | mark_task | mark | ✓ | `MarkTaskDao.get_list` | ☐ 菜单权限控制 |
| 21 | mark_record | mark | ✓ | — | — |
| 22 | variable_value | variable | ✓ | `VariableValueDao.get_list` | — |
| 23 | audit_log | audit | ✓ | `AuditLogDao.get_list` | ☐ 挂载/交接/禁用操作类型 |
| 24 | invite_code | invite_code | ✓ | — | ☐ 邀请码限租户使用 |
| 25 | evaluation | evaluation | ✓ | — | ☐ 菜单权限控制 |
| 26 | dataset | evaluation | ✓ | — | ☐ 菜单权限控制 |
| 27 | finetune_job | finetune | ✓ | — | ☐ 菜单权限控制 |
| 28 | report_template | report | ✓ | — | — |
| 29 | share_link | share_link | N/A | **不过滤** | ☐ 分享链接公开访问不受 tenant_id 限制（PRD v1 决策） |
| 30 | llm_server / llm_model | llm | ✓ 或 0 | `LLMDao.get_list` | ☐ tenant_id=0 表示系统级共享 |

**注入实现**：`src/backend/bisheng/core/database/tenant_filter.py` 新增 SQLAlchemy event listener，按 `current_tenant_id` ContextVar 自动注入 IN 列表。

---

## 7. 依赖与阻塞

### 7.1 前置依赖

| 依赖 | 依赖内容 | 使用方式 |
|------|---------|---------|
| v2.5.0/F001-multi-tenant-core | Tenant / UserTenant 基础表 + ContextVar | 扩展其表字段与语义 |
| v2.5.0/F002-department-tree | Department 物化路径 + parent 关系 | 挂载点标记依赖部门 ID |
| v2.5.0/F004-rebac-core | OpenFGA 客户端 + FailedTuple 补偿 | 挂载时写 tenant 元组 |

### 7.2 本 Feature 阻塞的下游

- F012-tenant-resolver（需要 Tenant 树字段）
- F013-tenant-fga-tree（需要新字段决定 DSL 升级范围）
- F018-resource-owner-transfer（需要 Tenant 模型）

### 7.3 外部依赖

- MySQL 8.0 支持 JSON 字段和 unique 索引
- SQLAlchemy event 机制（already in use）

---

## 8. 手工 QA 清单（P2-H 决策要求）

> 在自动化测试搭建前，本 feature 必须通过以下手工测试：

### 8.1 基础功能

- [ ] **Root 自动初始化**：执行迁移脚本后 `SELECT * FROM tenant WHERE id=1` 返回 `parent_tenant_id=NULL`；无需任何手工 CRUD
- [ ] **挂载 Child Tenant**：对某部门调 mount API，验证 Child 创建（`parent_tenant_id=1`）、Department `is_tenant_root=1`
- [ ] **禁止嵌套**：在 Child 下的部门再次挂载，返回 400 + 错误码 22001
- [ ] **解绑 Child（策略 A 迁移）**：验证子树资源 tenant_id 全部改为 Root
- [ ] **解绑 Child（策略 B 归档）**：验证 Child 状态 = archived，数据保留不可访问
- [ ] **解绑 Child（策略 C 手工）**：验证资源列表 UI 可用
- [ ] **Root 保护**：`PUT /api/v1/tenants/1/status disabled` 返回 403 错误码 22008；`DELETE /api/v1/tenants/1` 同
- [ ] **audit_log 表创建**：DDL 执行后 `DESC audit_log` 含 tenant_id / operator_id / operator_tenant_id / action / target_type / target_id / reason / metadata / create_time 字段及 3 个索引
- [ ] **orphaned 状态**：手工 UPDATE department 删除挂载点后，关联 Child Tenant.status 自动变 `orphaned`

### 8.2 数据隔离

- [ ] **跨 Tenant 查询隔离**：用户 A 在 tenant 1，登录后查询资源，不应看到 tenant 2 的数据
- [ ] **祖先可见**：Child 用户可看到 Root 的共享资源（tenant_id=Root, shared_to=Child）
- [ ] **非共享不可见**：Root 未共享的资源 Child 用户看不到
- [ ] **全局超管跨 Tenant 可见**：通过 ① 短路，整棵 Root 子树可见

### 8.3 边界与容错

- [ ] **禁用 Tenant**：禁用后 JWT 立刻失效；已队列 Celery 任务完成，新任务挂起
- [ ] **孤儿产生**：手工删除挂载部门，验证 Child 进入 orphaned；audit_log 记录；站内消息发送
- [ ] **循环挂载**：API 试图设置 parent_tenant_id = self.id，返回 400
- [ ] **唯一叶子约束**：INSERT 违反 `uk_user_active`，MySQL 1062 错误

### 8.4 升级回归

- [ ] **v2.5.0 → v2.5.1 升级**：tenant_id=1 默认 Root 已存在；audit_log 表创建成功；user.token_version 列存在（默认 0）
- [ ] **存量数据**：23 张业务表的 tenant_id 默认值为 1，查询正常
- [ ] **uk_user_active 约束**：升级时所有 user_tenant 记录被校验，冲突记入 failed 表
- [ ] **旧 API 废弃**：`POST /api/v1/tenants`（创建 Root）返回 410 Gone；`POST /api/v1/user/switch-tenant` 返回 410 Gone
- [ ] **Tenant.status 枚举升级**：旧记录无影响；新枚举值 `orphaned` 可写入

### 8.5 审计

- [ ] **挂载日志**：audit_log 含 operator/时间/子公司ID/配额/初始管理员/原因
- [ ] **解绑日志**：audit_log 含策略（A/B/C）和资源数
- [ ] **查询日志**：全局超管可查询历史挂载/解绑记录

---

## 9. 错误码分配

> **模块编码 220**（tenant_tree）；原 spec 草稿声明 `MMM=190`，与 F004 permission 模块已上线的 19000~19005 直接冲突，于 2026-04-19 重新分配到 **220**（release-contract 表 3 同步修订）。实施代码见 `src/backend/bisheng/common/errcode/tenant_tree.py`。

- **MMM=220** (tenant_tree 模块)
- 22001: 禁止嵌套挂载（MVP 锁 2 层）
- 22002: 挂载部门冲突（目标部门已是挂载点或子节点）
- 22003: 根部门不可挂载
- 22004: Tenant parent 关系非法（parent 不存在或非 Root）
- 22005: Tenant 下存在 Child 无法物理删除
- 22006: Child Tenant 迁移资源时 tenant_id 冲突
- 22007: 孤儿 Tenant 已存在
- 22008: **Root Tenant 受系统保护**（不可禁用/归档/删除；INV-T11）
- 22009: audit_log 写入失败
- 22010: 资源下沉权限不足（`migrate-from-root` 仅全局超管；INV-T10）
- 22011: 资源下沉来源校验失败（resource.tenant_id != 1 Root）

---

## 10. 不在本 Feature 范围

- JWT 叶子派生、UserTenantSyncService → F012
- OpenFGA tenant type DSL 升级 → F013
- 挂载审批工作流 → v2.6+（附录 G.2）
- 3+ 层嵌套 → v2.6+（附录 G.5）
- 所有者交接 API → F018
