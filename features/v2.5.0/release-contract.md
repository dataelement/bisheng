# Release Contract — v2.5.0

> 本文件是 v2.5.0 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。
>
> **v2.5.0 核心目标**：权限体系从 RBAC 迁移到 ReBAC（OpenFGA）+ 多租户支持（逻辑隔离）。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

### v2.5.0 新增对象

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| Tenant | F001-multi-tenant-core | 租户 CRUD，含 quota_config JSON schema 定义 |
| UserTenant | F001-multi-tenant-core | 用户-租户多对多关联 |
| TenantContextVar | F001-multi-tenant-core | current_tenant_id ContextVar + SQLAlchemy event 自动注入 |
| Department | F002-department-tree | 部门树 CRUD，物化路径维护 |
| UserDepartment | F002-department-tree | 用户-部门关联 |
| UserGroup (扩展) | F003-user-group | 复用现有 Group 表，扩展 tenant_id + visibility |
| PermissionTuple (OpenFGA) | F004-rebac-core | OpenFGA 元组写入/删除/检查 |
| AuthorizationModel (OpenFGA) | F004-rebac-core | FGA type definition 管理 |
| FailedTuple | F004-rebac-core | OpenFGA 双写失败补偿表 |
| Role (策略角色扩展) | F005-role-menu-quota | 新增 department_id + quota_config，菜单权限（WEB_MENU） |
| RoleAccess (WEB_MENU 类型) | F005-role-menu-quota | 前端菜单可见性控制 |
| OrgSyncConfig | F009-org-sync | 三方组织同步配置（P2） |
| OrgSyncLog | F009-org-sync | 同步执行日志（P2） |

### 既有对象（Owner 不变，v2.5 增加权限检查调用）

| 领域对象 | 现有 Owner 模块 | v2.5 变更 | 适配 Feature |
|---------|----------------|----------|-------------|
| Knowledge | knowledge/ | 操作前增加 PermissionService.check()，创建时写 owner 元组 | F008 |
| KnowledgeFile | knowledge/ | 同上 + 文件夹层级 parent 元组 | F008 |
| Flow (所有 FlowType) | 对应业务模块 | 操作前增加 PermissionService.check()，创建时写 owner 元组 | F008 |
| Assistant / AssistantLink | assistant 相关 | 同上 | F008 |
| GptsTools | tool/ | 同上 | F008 |
| Channel | channel/ | 同上 | F008 |
| ChatMessage | chat_session/ | tenant_id 自动过滤（无 ReBAC 检查） | F001（自动注入） |
| MessageSession | chat_session/ | 同上 | F001（自动注入） |
| _（新增对象时在此追加）_ | — | — | — |

**规则**：
- 非 Owner Feature 不得创建/修改/删除上述对象，只能读取或调用 Owner 的 Service
- 既有模块的领域对象 Owner 保持不变，v2.5 Features 只增加权限检查调用
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-1 | 所有业务表必须含 `tenant_id` 字段，通过 SQLAlchemy event 自动注入查询过滤和写入填充，代码中禁止手动 `WHERE tenant_id=` | 所有 ORM 模型 | F001 |
| INV-2 | 资源创建时必须同步写入 OpenFGA owner 元组（通过 `PermissionService.authorize()`），禁止仅写 MySQL 不写 OpenFGA | PermissionTuple | F004 |
| INV-3 | 权限检查统一使用 `PermissionService.check()`，禁止直接查询 `role_access` 或 `group_resource`（WEB_MENU 类型除外） | PermissionTuple, Role | F004, F005 |
| INV-4 | OpenFGA 与 MySQL 双写，失败记入 `failed_tuples` 补偿表，不可静默丢弃 | PermissionTuple, FailedTuple | F004 |
| INV-5 | 系统管理员（`system:global` 的 `super_admin`）全权放行，权限检查链路中短路在第一级 | 所有权限相关 | F004 |
| INV-6 | 租户归属检查（`tenant_id` 匹配）是安全底线，位于权限检查第二级，不可跳过 | Tenant, UserTenant | F001 |
| INV-7 | 权限金字塔 `owner ⊃ manager(can_manage) ⊃ editor(can_edit) ⊃ viewer(can_read)`，高级角色隐含低级角色全部权限 | PermissionTuple | F004 |
| INV-8 | Celery 任务发送时将 `tenant_id` 写入 headers，Worker 执行前恢复 `current_tenant_id` ContextVar | 所有 Worker 任务 | F001 |
| INV-9 | 外部存储按租户隔离：默认租户(tenant_id=1)保留原有路径/前缀/key（零迁移兼容），新租户使用 `t{tenant_id}_`（Milvus/ES collection/index）、`tenant_{tenant_code}/`（MinIO 路径）、`t:{tenant_id}:`（Redis key）前缀 | 所有存储操作 | F001 |
| INV-10 | 废弃表（`role_access` 资源授权部分、`group_resource`、`space_channel_member`）的数据迁移到 OpenFGA 后，旧逻辑不再新增 | 旧权限表 | F004, F006 |
| INV-11 | 配额执行：资源创建必须检查 `effective_quota = min(tenant_remaining, role_quota)`，达到上限时拒绝并返回明确错误码。不使用分布式锁，允许高并发下轻微超额（下次检查时纠正） | Tenant, Role, 所有资源表 | F005 |
| INV-12 | 部门 admin 继承：admin 通过 OpenFGA `admin from parent` 向下传递，member **不**继承。授权"部门(含子部门)"时，业务层展开子部门树（`path LIKE`），为每个子部门写入独立元组 | Department, PermissionTuple | F002, F004 |
| INV-13 | 登录租户上下文：认证后每个请求（HTTP/WS/Celery）必须有有效 tenant 上下文。JWT 中无有效 tenant_id 的请求被拒绝（系统管理员端点除外）。`multi_tenant.enabled=false` 时隐式使用默认租户(id=1) | Tenant, UserTenant, JWT | F001 |
| INV-14 | 租户创建原子性：创建租户必须原子地创建租户记录、根部门、UserTenant 关联、OpenFGA 元组（tenant admin/member）。MySQL commit 后的 OpenFGA 写入失败必须记入 `failed_tuples` 补偿表 | Tenant, Department, PermissionTuple | F001, F004 |
| INV-15 | 资源权限接入完整性：授权模型中有 OpenFGA type 的资源模块（knowledge_space/folder/knowledge_file/workflow/assistant/tool/channel/dashboard）必须在变更操作前调用 `PermissionService.check()`，创建时调用 `PermissionService.authorize()`。无 OpenFGA type 的模块（linsight/workstation/mcp/evaluation/dataset/mark_task）豁免 | 所有资源模块 | F008 |
| _（新增约束时在此追加）_ | — | — | — |

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F000-test-infrastructure | 无 | 搭建 pytest conftest + fixture + 前端测试框架基础 |
| F001-multi-tenant-core | F000 | 租户模型、tenant_id 自动注入、存储隔离前缀、Celery 上下文、JWT 扩展 |
| F002-department-tree | F001 | 部门树依赖租户存在，创建租户时自动创建根部门 |
| F003-user-group | F001 | 用户组属于租户，依赖 tenant_id |
| F004-rebac-core | F001, F002, F003 | OpenFGA 集成，授权主体包括用户/部门/用户组 |
| F005-role-menu-quota | F004 | 策略角色扩展（department_id + quota_config）、WEB_MENU、三级配额执行 |
| F006-permission-migration | F004, F005 | 旧权限数据（role_access/group_resource/space_channel_member）迁移到 OpenFGA |
| F007-resource-permission-ui | F004 | 前端资源授权管理对话框，权限级别徽章 |
| F008-resource-rebac-adaptation | F004, F007 | 给现有 6 模块（knowledge/workflow/assistant/tool/channel/dashboard）接入 PermissionService |
| F009-org-sync | F002 | 三方组织同步（飞书/企微/钉钉），P2 延后 |
| F010-tenant-management-ui | F001, F005 | 租户 CRUD API + 管理页面、登录租户选择、租户切换 |
| _（新增 Feature 时在此追加）_ | — | — |

### 依赖图（可视化）

```
F000-test-infrastructure
  │
  v
F001-multi-tenant-core
  │         │         │
  v         v         v
F002-dept  F003-grp  F010-tenant-mgmt-ui ←── 也依赖 F005
  │         │
  └────┬────┘
       v
F004-rebac-core
  │         │         │
  v         v         v
F005-role  F007-ui   F008-resource-adapt ←── 也依赖 F007
  │
  v
F006-migration

F009-org-sync ← 仅依赖 F002（P2，延后）
```

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | 对应 errcode 文件 |
|----------------|------|-------------------|
| 100 | server | `server.py` |
| 101 | finetune | `finetune.py` |
| 104 | assistant | `assistant.py` |
| 105 | flow | `flow.py` |
| 106 | user | `user.py` |
| 108 | llm | `llm.py` |
| 109 | knowledge | `knowledge.py` |
| 110 | linsight | `linsight.py` |
| 120 | workstation | `workstation.py` |
| 130 | chat/channel | `chat.py`, `channel.py` |
| 140 | message/qa | `message.py`, `qa.py` |
| 150 | tool | `tool.py` |
| 160 | dataset | `dataset.py` |
| 170 | telemetry | `telemetry.py` |
| 180 | knowledge_space | `knowledge_space.py` |
| **190** | **permission (v2.5 新增)** | _待创建_ |
| **200** | **tenant (v2.5 新增)** | _待创建_ |
| **210** | **department (v2.5 新增)** | _待创建_ |
| **220** | **org_sync (v2.5 P2 新增)** | _待创建_ |
| **230** | **user_group (v2.5 新增)** | `common/errcode/user_group.py` |

---

## 特殊架构模块

以下模块不遵循标准 DDD（api/ + domain/）结构，arch-guard 规则对其放宽：

| 模块 | 结构 | 原因 |
|------|------|------|
| workflow/ | nodes/ + graph/ + callback/ + edges/ | DAG 执行引擎，按引擎组件组织 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-04-11 | 初始版本 | — |
| 2026-04-11 | Feature 列表从 8 扩展为 11（拆分 F001、新增 F008/F009/F010）；新增 INV-11~15 五条不变量；补充 INV-9 默认租户零迁移说明；领域对象归属表增加 F008/F009/F010 对象；既有对象表增加适配 Feature 列；补充 220 模块编码 | 全部 Feature |
