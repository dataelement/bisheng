# Release Contract — v2.5.1（Tenant 树架构增量）

> 本文件是 v2.5.1 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件，以及 v2.5.0/release-contract.md（基线）。**
>
> **v2.5.1 核心目标**：重写 v2.5.0 的扁平多租户模型为 Tenant 树形架构，落地 2026-04-18 PRD Review 对齐的 9 项决策 + 2026-04-19 LLM 多租户 + admin-scope 4 项决策。

---

## 表 1：v2.5.1 新增/变更领域对象

| 领域对象 | Owner Feature | v2.5.0 → v2.5.1 变更 |
|---------|--------------|-------------------|
| Tenant | F011-tenant-tree-model | **扩展** v2.5.0/F001 的 Tenant；新增 `parent_tenant_id` / `share_default_to_children` 字段（2026-04-20 精简：废弃 tenant_path/level/tenant_kind） |
| UserTenant | F011-tenant-tree-model | **语义变更**：从多对多 → 唯一叶子快照（单条 active 记录，多对多废弃） |
| AuditLog | F011-tenant-tree-model | 新增表（PRD §2.1）：tenant_id / operator_id / operator_tenant_id / action / target / reason / metadata，承载挂载/解绑/交接/禁用日志 |
| User.token_version | F012-tenant-resolver | 新增字段（`ALTER TABLE user ADD COLUMN token_version INT NOT NULL DEFAULT 0`），主部门跨 Tenant 变更时 +1 强制旧 JWT 失效 |
| TenantResolver | F012-tenant-resolver | 新增 `resolve_user_leaf_tenant(user_id)` 沿部门 path 反向派生叶子 Tenant |
| UserTenantSyncService | F012-tenant-resolver | 主部门变更时同步归属；告警 + 可配置阻断 |
| JWT Payload | F012-tenant-resolver | 扩展 `token_version` 字段（2026-04-20 简化：去 tenant_path，2 层下可见集合直接由 tenant_id + Root id=1 推导） |
| OpenFGA tenant type | F013-tenant-fga-tree | 新增 `shared_to` 关系；`admin` 不继承（两层管理员模型）；2026-04-20 精简：**不保留 tenant#parent 关系**（FGA 中冗余） |
| FGA AuthorizationModel v2 | F013-tenant-fga-tree | 升级 model version；保留旧 model 作历史元组解析 |
| TenantMount | F011-tenant-tree-model | `Department.is_tenant_root` + `Department.mounted_tenant_id` 挂载关系 |
| TenantQuotaSnapshot | F016-tenant-quota-hierarchy | 沿树取严 `min(leaf, root)` 的有效配额视图 |
| SharedResourceTuple | F017-tenant-shared-storage | Root 创建资源时的 `tenant:{root}#shared_to` 元组写入 |
| ResourceOwnershipService | F018-resource-owner-transfer | 批量所有者交接事务服务 |
| DepartmentRelinkService | F015-ldap-reconcile-celery | SSO 换型按 path+name 回落的部门映射重建 |
| AuditLog (操作类型扩展) | F011（挂载操作）+ F018（交接操作） | 新增 `tenant.mount` / `resource.transfer_owner` 等事件类型 |
| AdminTenantScope | F019-admin-tenant-scope | **新增**（2026-04-19 决策 1）：Redis-based 管理视图切换 `admin_scope:{user_id}` 存储，非 JWT；仅全局超管可用；TTL 4h 滑动；管理类 API 读 Redis 覆盖查询 IN 列表 |
| LLM Server / Model Tenant Filter | F020-llm-tenant-isolation | **扩展** v2.5.0/F001：`LLMDao` 全部查询方法 tenant 感知；写操作权限从 `get_admin_user` 降到 `get_tenant_admin_user`；Root 共享模型对 Child 只读；Child Admin 完全自主 CRUD 本 Child 模型 |
| AuditLog（LLM + scope 扩展） | F019 + F020 | 新增 `admin.scope_switch` / `llm.server.create/update/delete` / `llm.model.create/update/delete` 事件；payload 含 endpoint URL、api_key_hash、operator_tenant_id、from/to_scope 等 |

### v2.5.0 对象在 v2.5.1 的行为变更

| 对象 | v2.5.0 Owner | v2.5.1 变更 | 适配 Feature |
|------|-------------|------------|-----------|
| Tenant | v2.5.0/F001 | 字段扩展 + 层级语义；Owner 延续到 F011 | F011 |
| 所有业务表的 `tenant_id` | v2.5.0/F001 | 过滤从"严格相等"改为"IN 列表"（leaf + Root + shared_to；2 层下至多 2 个值） | F013（权限链路）+ F017（共享） |
| `PermissionService.check()` | v2.5.0/F004 | 五级短路链路更新：② 改 IN 列表，③ 去掉 parent 继承 | F013 |
| JWT payload | v2.5.0/F001 | 扩展 `token_version` 字段（不含 tenant_path） | F012 |
| Tenant.status 枚举 | v2.5.0/F001 | 新增 `orphaned` 状态（挂载部门被 SSO 删除时进入） | F011 / F015 |

**规则**：非 Owner Feature 不得修改上述对象定义；只能读取或调用 Owner Service。

---

## 表 2：跨 Feature 不变量（INV-N）

> v2.5.0 的 INV 全部继承；以下为 v2.5.1 新增约束。

| ID | 不变量 | 涉及对象 | 来源 spec |
|----|-------|---------|---------|
| INV-T1 | Tenant 树深度锁 2 层：Child 的 `parent_tenant_id` 必须指向 Root；UI/API 拒绝在 Child 下挂载 Grandchild（2026-04-20：废弃 level 字段，改用 parent_tenant_id 维度） | Tenant | F011 |
| INV-T2 | 每个用户最多 1 条 `UserTenant(is_active=1)`；主部门变更触发归属切换 | UserTenant | F011, F012 |
| INV-T3 | OpenFGA `tenant.admin` 不沿 parent 继承；两层管理员模型（全局超管 + Child Admin）；Root Tenant 不写 `tenant#admin` 元组 | OpenFGA model | F013 |
| INV-T4 | 用户主部门跨 Tenant 变更时，其名下资源 `tenant_id` **不迁移** | Resource (所有 8 类) | F012, F018 |
| INV-T5 | 全局超管覆盖整棵树（Root + 所有 Child）；本实例只有一个 Root，无跨实例运维概念 | system/super_admin | F013 |
| INV-T6 | 集团共享资源 `tenant_id = root_id`，**仅计入 Root 自身用量**，不计入 Child（避免 Child 因 Root 共享被动扣配额） | Resource, TenantQuotaSnapshot | F016, F017 |
| INV-T7 | 挂载/解绑子公司操作强制写 `audit_log`，不提供撤销 | Tenant, AuditLog | F011 |
| INV-T8 | 孤儿 Tenant（挂载部门被删除）进入 `orphaned` 状态；不定义处理 SLA | Tenant | F014, F015 |
| INV-T9 | 配额检查 = 叶子 Tenant 配额 + Root 硬盖；**Root 用量 = Root 自身 + Σ 所有 Child 累计**（集团总量上限） | TenantQuotaSnapshot | F016 |
| INV-T10 | 资源所有者交接批量上限 500 条；超限分批调用；to_user 叶子必须 ∈ 资源 tenant_id 的可见集合（即 {tenant_id, tenant_id 的 Root}）。**禁止 Root → Child 下沉路径走本 API**（to_user 在 Child ∉ {Root}），资源下沉请走 F011 `/tenants/{child_id}/resources/migrate-from-root` 改 tenant_id | Resource, ResourceOwnershipService | F018 |
| INV-T11 | **Root Tenant（tenant_id=1）不可禁用、不可归档、不可物理删除**（系统底线，违反返回 403 + 错误码 22008） | Tenant | F011 |
| INV-T12 | Gateway 实时同步 vs Celery 校对冲突按 `ts` 最大为准；同 ts 下 upsert 与 remove 冲突时以 remove 为准（从严处理） | Department, OrgSyncLog | F014, F015 |
| INV-T13 | 集团共享资源衍生数据（对话记录、消息 token、调用日志）归属用户叶子 Tenant；资源本身归 Root | Resource, ChatMessage, AuditLog | F016, F017 |
| INV-T14 | admin-scope 仅对全局超管生效；Child Admin 调 `POST /admin/tenant-scope` 返回 403 + 19701 `admin_scope_forbidden`；Redis TTL=14400s 滑动（每次管理类 API 命中刷新）；在 logout / `user.token_version` +1 / 超管 role 降级 / scope 指向的 Child 被禁用/归档/删除时主动 DEL `admin_scope:{user_id}` | AdminTenantScope, AuditLog | F019 |
| INV-T15 | Root 创建的 `llm_server/llm_model` 默认 shared（复用 `{llm_server}#viewer → tenant:{root}#shared_to#member` FGA 元组），超管创建时可勾选"仅 Root 使用"关闭共享；Child Admin 对 Root 共享模型 PUT/DELETE 返回 403 + 19801 `llm_model_shared_readonly`；Child 无法禁用 Root 共享模型 | LLM Server / Model, OpenFGA | F020 |
| INV-T16 | 单→多租户升级时所有存量 `llm_server/llm_model.tenant_id=1`（Root），随 `share_default_to_children=1` 默认值自动对新挂 Child 可见；知识库/工作流/助手对 model_id 外键不迁移（`knowledge.model_id`、`workflow.model_id`、`assistant.model_id` 等保留原值）；挂载 Child 弹窗提供"不自动分发"选项缓解敏感模型泄露风险 | LLM Server / Model, Tenant | F020 |

**规则**：与 v2.5.0 一致——新增 INV 先在此表追加，再写 AC；修改 INV 必须列出 Impacted Specs 清单。

---

## 表 3：Feature 依赖图

| Feature | 依赖 | 说明 |
|---------|------|------|
| F011-tenant-tree-model | v2.5.0 全部 | 需 v2.5.0 的 Tenant/UserTenant/Department 基础表 |
| F012-tenant-resolver | F011 | 需 Tenant 树字段可用 |
| F013-tenant-fga-tree | F011, F012 | 需新 Tenant 字段 + 叶子 Tenant 派生 |
| F014-sso-org-realtime-sync | F012 | 需 UserTenantSyncService |
| F015-ldap-reconcile-celery | F014 | 依赖 SSO 实时同步框架 |
| F016-tenant-quota-hierarchy | F013 | 需 OpenFGA tenant 树（共享资源计数规则） |
| F017-tenant-shared-storage | F013 | 需 OpenFGA `shared_to` 关系 |
| F018-resource-owner-transfer | F011, F013 | 需 Tenant 模型 + OpenFGA owner 元组 |
| F019-admin-tenant-scope | F013 | 需全局超管识别逻辑 `LoginUser.is_global_super()`；Redis + audit_log |
| F020-llm-tenant-isolation | F011, F013, F019 | 需 Tenant 树、权限检查链路、admin-scope（超管切换视图）|
| F021-wecom-org-sync-provider | v2.5.0/F009, F011 | 扩展 v2.5.0/F009 的 `OrgSyncProvider` 抽象，实现 WeComProvider（替换 stub）+ 管理台表单；Provider 本身无 Tenant 树语义，但 `org_sync_config.tenant_id` 依赖 F011 的叶子 Tenant 归属|

---

## 2026-04-18 PRD Review 9 项决策（落地锚点）

| 决策 | INV / 约束 | 主要 Feature |
|------|-----------|-------------|
| P0-A 2 层嵌套 | INV-T1 | F011 |
| P0-B 合规声明 | 文档层（PRD §1.5） | — |
| P0-C 数据留原处 + 所有者交接 | INV-T4, INV-T10 | F018 |
| P1-D1 挂载决策权 | INV-T7 | F011 |
| P1-D2 取消挂载与孤儿 | INV-T8 | F011, F014 |
| P1-E 配额简化（MVP 仅 CRUD） | INV-T6, INV-T9 | F016 |
| P1-F 压测 + SSO relink | — | F015 |
| P2-G 两层管理员 | INV-T3, INV-T5 | F013 |
| P2-H F011/012/013 spec 要求 | — | F011, F012, F013 |

---

## 已分配模块编码（MMMEE 5 位错误码）

> v2.5.0 编码延续；v2.5.1 新增：

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 220 | tenant_tree | F011（原 190，与 permission F004 冲突，2026-04-19 重分配） |
| 191 | tenant_resolver | F012 |
| 192 | tenant_fga | F013 |
| 193 | tenant_sync | F014, F015 |
| 194 | tenant_quota | F016 |
| 195 | tenant_sharing | F017 |
| 196 | resource_owner_transfer | F018 |
| 197 | admin_scope | F019 |
| 198 | llm_tenant | F020 |

---

## v2.5.1 新增/扩展配置类清单（Pydantic Settings）

> 开发前必读：v2.5.0 仅 `MultiTenantConf(enabled, default_tenant_code)`；下列扩展由各 Feature 的 DDL/代码变更同步引入，实施时需先扩展 Pydantic 模型，否则 `settings.xxx.yyy` 运行时 AttributeError。

| Feature | 配置类 | 新增字段 | 文件 |
|---------|-------|---------|------|
| F011 | `MultiTenantConf` 扩展 | `group_shared_by_default: bool = True`（Root 创建资源默认共享） | `core/config/multi_tenant.py` |
| F012 | **新建** `UserTenantSyncConf` | `enforce_transfer_before_relocate: bool = False`（阻断主部门变更） | `core/config/user_tenant_sync.py`（新） |
| F013 | `OpenFGAConf` 扩展 | `dual_model_mode: bool = False` / `model_id_backup: Optional[str] = None`（灰度双 model） | `core/config/openfga.py` |
| F014 | **新建** `SSOSyncConf` | `gateway_hmac_secret: str = ''`（HMAC 密钥；Gateway 配置同步） | `core/config/sso_sync.py`（新） |
| F019 | `MultiTenantConf` 扩展 | `admin_scope_ttl_seconds: int = 14400`（admin-scope Redis TTL 滑动） | `core/config/multi_tenant.py` |
| F020 | **新建** `LLMConf` 扩展 | `endpoint_whitelist: list[str] = []`（Child Admin 注册端点白名单，默认空=不限制） | `core/config/llm.py`（新） |

`Settings` 类（`core/config/settings.py`）需注册上述 Conf 为字段：

```python
class Settings(BaseSettings):
    # ... v2.5.0 既有
    multi_tenant: MultiTenantConf = MultiTenantConf()
    # v2.5.1 新增
    user_tenant_sync: UserTenantSyncConf = UserTenantSyncConf()
    sso_sync: SSOSyncConf = SSOSyncConf()
    llm: LLMConf = LLMConf()
```

**CI 守卫**：新增 Feature 引入 `settings.xxx.yyy` 前必须先扩展对应 Conf 类；`/code-review` 应扫描 spec 中声明的 config key 是否全部在 `Settings` 中可达。

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-04-18 | 初始化 v2.5.1；基于 Tenant 树 PRD Review 对齐 9 项决策 | 全部 feature |
| 2026-04-20 | 收窄修订：删 SaaS 多客户（仅私有化）；数据模型精简（去 tenant_path/level/tenant_kind）；Root 自动创建+不可删/禁；新增 audit_log/token_version/orphaned/INV-T11~T13；Gateway 实时 vs Celery 冲突规则 | 全部 feature |
| 2026-04-21 | Round 2 Review 修复：① DSL 彻底收窄（资源 manager/editor/viewer 移除 tenant#member，viewer 仅留 shared_to#member）；② F014 补 /departments/sync 端点；③ F011 新增 DepartmentDeletionHandler 集中处理孤儿触发；④ F018 删除 Root→Child 交接路径（改走 F011 migrate-from-root）；⑤ F017 新增 §5.4 衍生数据写入层；⑥ audit_log action 清单集中到 F011；⑦ 补废弃 API AC（POST /tenants、switch-tenant 返 410）；⑧ F015 冲突计数 SQL + 索引要求；⑨ F012 config key 路径明确；⑩ F013 AC-12/13 补普通 Tenant 成员授权边界与 Root admin API 保护 | 全部 feature + PRD 附录 A DSL |
| 2026-04-19 | **F021-wecom-org-sync-provider**（新增）：企业微信 Provider 接入，替换 v2.5.0/F009 中 WeComProvider stub。沿用 F009 的 OrgSyncConfig / OrgSyncLog / 错误码 220 / 9 个 REST 端点 / Celery 调度，不新增领域对象、不新增表、不新增模块编码。新增 AC-35~AC-58（24 条）、7 个架构决策、前端管理台 `/system/org-sync` 入口（同时兼容 Feishu / GenericAPI Provider）。详见 [021-wecom-org-sync-provider/spec.md](021-wecom-org-sync-provider/spec.md) | Provider 层 + Platform 前端；不触碰 Tenant 树相关 Feature |
| 2026-04-19 | LLM 多租户 + admin-scope 决策：① 新增 F019-admin-tenant-scope（Redis-based 管理视图切换，不重签 JWT，仅超管，TTL 4h 滑动）；② 新增 F020-llm-tenant-isolation（LLMDao tenant 感知，Child Admin 完全自主 CRUD，Root 共享模型对 Child 只读，单→多升级零成本）；③ 新增 INV-T14 / T15 / T16；④ 新增模块编码 197=admin_scope、198=llm_tenant；⑤ PRD §1.1 背景重定位，§3.3 Child Admin 能力清单扩展，§4.1 admin-scope 覆盖规则，新增 §5.1.5 管理视图切换章节，§5.2.1 挂载 review，§7.1 彻底重写为"Root 共享 + Child 扩展"两类来源 + 可见性矩阵 + 只读约束 + 升级行为；⑥ 技术方案 §11.2/§11.7/§11.8 同步；⑦ 升级迁移方案新增 §3.7 LLM 模型升级行为 + §9.2 挂载安全提示 | 新增 F019/F020；主 PRD + 技术方案 + 迁移方案同步；错误码 19701/19801/19802 |
| 2026-04-19（后续） | **Feature Spec 对齐 PRD 精化**：用户 PRD 定稿后深度审计 F011~F020 共 10 份 spec；未发现致命违规，补充 23 处精化：① **F011** 新增 AC-04d 定义 `POST /tenants/{child_id}/resources/migrate-from-root`（INV-T10 资源下沉专用 API）+ 错误码 19010/19011，AC-15 响应体精化；② **F012** AC-03 audit action 名明确为 `user.tenant_relocated`，`TenantResolver` 回退 Root 硬编码 id=1，补 config.yaml 示例；③ **F013** 补 `_is_shared_to()` 方法签名（§6）；④ **F014** `/departments/sync` HMAC 细节（算法/密钥/Header/失败码）、F011 依赖明确"仅调用不实现"；⑤ **F015** AC-11 同 ts 冲突执行 3 步路径、AC-12 周报告硬化（`report_ts_conflicts_weekly` + 升级条件）；⑥ **F016** `_aggregate_root_usage` 仅计 active Child，依赖 F011 新 `aget_children_ids_active` + F012 `strict_tenant_filter`；⑦ **F017** 新增 AC-11（`TenantContextMissing` 异常保障）+ AC-12（取消共享 4 步时序）+ AC-13（挂载"不自动分发"）+ 错误码 19504；`ChildMountService.on_child_mounted` 加 `auto_distribute` 参数；⑧ **F018** §7 依赖明确 F011 migrate-from-root，audit 补 `operator_tenant_id` + `target_type/target_id`；⑨ **F019** AC-13 注脚、operator_tenant_id 硬编码注释；⑩ **F020** §5.1 补 endpoint 白名单校验代码，§8 前端抽取 `AdminScopeSelector` 复用组件，§10 依赖补 `get_tenant_admin_user` | 10 份 spec 精化；新增错误码 19010/19011（F011）、19504（F017）；F011 §5.4.2 action 清单已含 `resource.migrate_tenant`（2026-04-21 预先登记） |
| 2026-04-20 | **F021 实现完成**：WeComProvider 36 行 stub 替换为 290 行完整实现（Redis token 缓存 + 分布式锁 + 错误码分桶 + 指数退避）；`OrgSyncConfigCreate/Update` 新增 WeCom 分支 `model_validator`；`OrgSyncService / sync_exec / sync_config` 注入并剥离 `_config_id` 供 Provider Redis key 隔离使用；Platform 首次落地"组织同步" Tab（`/sys` 下 + `isFullAdminShell` 门禁），支持 WeCom/Feishu/Generic 三 Provider 的 CRUD + 测试连接 + 手动同步 + 日志；i18n 新建独立 `orgSync` namespace 三语齐全（90 key × 3 = 270 行文案）。测试：**91 后端单测 + 17 E2E 全绿**（含既有 F009 11 条回归无偏移）；live 企微 API 测试按设计 skip（`E2E_WECOM_TEST_LIVE` 环境变量控制）。未触碰 FGA / 错误码 / 数据模型 / Tenant 树 Feature。开发偏差记录在 `021-wecom-org-sync-provider/tasks.md` 末尾（6 条，最关键的是用轻量自写 InMemoryAsyncRedis 存根绕过 fakeredis/redis-py 7.x 元类冲突） | Provider 层 + Platform 前端；不触碰 Tenant 树相关 Feature |
| 2026-04-19（开发前最终排查） | **3 方向并行深度排查** —— BLOCKER 4 项 + HIGH 6 项全部修复：① **F011 §5.4 audit_log 表与 v2.5.0 冲突解决**：改 `CREATE TABLE` 为 `ALTER TABLE` 补字段（tenant_id / operator_tenant_id / action / target_type / target_id / reason / metadata），保留 v2.5.0 既有字段（system_id / event_type / object_type / object_id）兼容旧代码；明确新旧字段查询互不干扰 + `operator_tenant_id` 填值规则（Child Admin=leaf / 超管无 scope=1 / 超管有 scope=X / 系统=1）；② **F011 §5.4.2 action 清单补 7 行**（`admin.scope_switch` + `llm.server.{create,update,delete}` + `llm.model.{create,update,delete}`）落实 INV-T7；③ **F011 §5.4.3 新增 TenantDao 扩展方法定义**（`aget_children_ids_active` / `aget_non_active_ids` / `aexists`）供 F016/F019 调用；④ **F013 §5 DSL 补 `llm_server` / `llm_model` 资源类型**，解决 F020 写 `{llm_server}#viewer → tenant#shared_to#member` 元组的 "unknown object type" 阻塞；⑤ **F012 §5.4 新增 ContextVar 扩展**（`visible_tenant_ids` / `_strict_tenant_filter` / `_admin_scope_tenant_id` / `_is_management_api`）+ `strict_tenant_filter()` context manager + `get_current_tenant_id()` 优先级规则（admin_scope > JWT leaf），v2.5.0 既有函数签名保留；⑥ **F012 §5.5 新增 Middleware 注册顺序文档**（Auth → TenantContext → AdminScope → 业务路由）；⑦ **F019/F020 前端组件归属明确**：`AdminScopeSelector.tsx` 归 F020 拥有，F019 仅提供后端 API + `useAdminScope` hook；⑧ **F019 §5.4 Celery 任务加 `bypass_tenant_filter()` 包裹** 防 Celery 上下文下 ContextVar=None 导致的隔离行为未定义；⑨ **F020 §5.5 DDL 迁移补前置重名校验**（`UNIQUE(name)` → `UNIQUE(tenant_id, name)` 前先 SELECT GROUP BY 查重，存在冲突则中止迁移）；⑩ **release-contract 新增"配置类清单"章节**（MultiTenantConf / UserTenantSyncConf / SSOSyncConf / LLMConf / OpenFGAConf 扩展），明确 Pydantic Settings 模型归属，防止 `settings.xxx.yyy` 运行时 AttributeError | 11 处修改分布在 F011 / F012 / F013 / F019 / F020 / release-contract；确认 v2.5.0 `current_tenant_id` / `bypass_tenant_filter` / `Tenant.status=String(16)` / 旧 audit_log 表结构与 v2.5.1 的兼容路径；**开发可以开始** |
