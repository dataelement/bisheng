# v2.5.1 Feature 索引（Tenant 树架构增量）

**版本目标**：将 v2.5.0 的扁平多租户模型重写为 **Tenant 树形架构**，聚焦集团内分子公司私有化部署场景；落地 2026-04-18 PRD Review 对齐的 9 项关键决策 + 2026-04-20 收窄修订（仅私有化、Root 自动创建+不可删/禁、数据模型精简）。

**版本契约**：[release-contract.md](./release-contract.md)

**开发主线分支**：、`2.5.0-PM` 

**主 PRD**：[../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)

---

## Feature 列表

| # | Feature | 优先级 | 状态 | 依赖 |
|---|---------|--------|------|------|
| F011 | [tenant-tree-model](./011-tenant-tree-model/) | P0 | 🔲 未开始 | v2.5.0 全部完成 |
| F012 | [tenant-resolver](./012-tenant-resolver/) | P0 | 🔲 未开始 | F011 |
| F013 | [tenant-fga-tree](./013-tenant-fga-tree/) | P0 | 🔲 未开始 | F011, F012 |
| F014 | [sso-org-realtime-sync](./014-sso-org-realtime-sync/) | P1 | 🔲 未开始 | F012 |
| F015 | [ldap-reconcile-celery](./015-ldap-reconcile-celery/) | P1 | 🔲 未开始 | F014 |
| F016 | [tenant-quota-hierarchy](./016-tenant-quota-hierarchy/) | P1 | 🟢 代码就绪，待 T09 手工 QA | F013 |
| F017 | [tenant-shared-storage](./017-tenant-shared-storage/) | P1 | 🔲 未开始 | F013 |
| F018 | [resource-owner-transfer](./018-resource-owner-transfer/) | P0 | 🔲 未开始 | F011, F013 |
| F019 | [admin-tenant-scope](./019-admin-tenant-scope/) | P1 | 🔲 未开始 | F013 |
| F020 | [llm-tenant-isolation](./020-llm-tenant-isolation/) | P1 | 🔲 未开始 | F011, F013, F019 |
| F021 | [wecom-org-sync-provider](./021-wecom-org-sync-provider/) | P0 | 🔲 未开始 | v2.5.0/F009, F011 |

---

## 依赖图

```
v2.5.0（全部完成，含 F009 OrgSyncProvider 抽象）
  │
  v
F011-tenant-tree-model（数据模型 + 隔离策略重构）
  │
  ├──────────────┬──────────────┬──────────────┐
  v              v              v              v
F012-resolver  F013-fga-tree  F018-owner-    F021-wecom-
  │              │            transfer       org-sync
  │              │                          (+ v2.5.0/F009)
  │              ├─ F016-quota-hierarchy
  │              ├─ F017-shared-storage
  │              └─ F019-admin-tenant-scope
  │                     │
  v                     v
F014-sso-sync         F020-llm-tenant-isolation
  │                   (+ F011, F013)
  v
F015-ldap-reconcile
```

**关键路径**：
- 主干：F011 → F012/F013 → F014/F015/F016/F017/F018/F019 可并行展开
- 串行阻塞：**F019 → F020**（LLM 超管切换视图依赖 admin-scope）
- 外挂链路：**F021**（WeCom Provider）依赖 v2.5.0/F009 + F011，与权限链路解耦可并行

---

## 2026-04-18 PRD Review 9 项决策映射

| 决策 | 主要落地 Feature |
|------|---------------|
| P0-A MVP 锁 2 层 | F011（parent_tenant_id 单层约束 + UI 强制校验）+ F013（FGA 不支持多层嵌套） |
| P0-B 合规声明 | 文档层（不需单独 feature） |
| P0-C 所有者交接 | **F018**（核心承接） + F012（归属切换告警） |
| P1-D1 挂载决策权 | F011（API 权限 + audit_log 强制写入） |
| P1-D2 取消挂载与孤儿 | F011（一次性处理接口）+ F014（孤儿告警） |
| P1-E 配额简化 | F016（MVP 范围：基础 CRUD + 沿树取严）|
| P1-F 压测与 SSO relink | F015（relink 接口）+ 发布前压测专项 |
| P2-G 两层管理员 | F013（OpenFGA DSL：`tenant.admin` 不继承；Root 不写 tenant#admin） |
| P2-H Feature spec 要求 | F011/F012/F013 spec 强制含依赖/表清单/checklist |
| **2026-04-20 收窄** | F011 新增 AC（Root 不可删/禁、audit_log 表 DDL）+ F015（实时 vs 校对冲突规则）+ 数据模型精简（去 tenant_path/level/tenant_kind） |

### 2026-04-19 LLM 多租户 + admin-scope 4 项决策映射

| 决策 | INV / 约束 | 主要落地 Feature |
|------|-----------|-----------------|
| 决策 1 admin-scope 管理视图切换（Redis TTL 4h 滑动，非 JWT） | INV-T14 | **F019**（新增） |
| 决策 2 Root 共享 LLM 可关闭（超管创建时勾选"仅 Root 使用"） | INV-T15 | F020 |
| 决策 3 Child Admin 自主管理本 Child 的 LLM Server/Model | INV-T15 | F020（`get_tenant_admin_user` 依赖） |
| 决策 4 存量 `llm_server/llm_model` 归 Root 默认分发 Child | INV-T16 | F020（升级迁移） |

---

## SDD 工作流

与 v2.5.0 一致：

1. Spec Discovery → 对齐 PRD 不确定性
2. 编写 spec.md → `/sdd-review spec`
3. 编写 tasks.md → `/sdd-review tasks`
4. 创建 Feature 分支 `feat/v2.5.1/{NNN}-{name}`，基于 `2.5.1-PM`
5. 逐任务执行 → `/task-review` → 打勾
6. `/e2e-test`（强制）
7. `/code-review --base 2.5.1-PM`
8. 合并回 `2.5.1-PM`

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-04-18 | 初始化 v2.5.1；8 个 feature 骨架（F011~F018）基于 Tenant 树 PRD Review 对齐 |
| 2026-04-19 | LLM 多租户 + admin-scope 4 项决策落地：新增 **F019-admin-tenant-scope**（Redis 管理视图切换）+ **F020-llm-tenant-isolation**（Root 共享/Child 自主/存量归 Root）+ **F021-wecom-org-sync-provider**（企业微信 Provider 替换 stub）；新增 INV-T14/T15/T16；错误码 220/197/198 分配 |
| 2026-04-20 | 收窄修订：删 SaaS 多客户场景（仅私有化）；数据模型精简（去 tenant_path/level/tenant_kind）；Root 自动创建+不可删/禁；新增 audit_log/token_version/orphaned；Gateway 实时 vs Celery 校对冲突规则 |
| 2026-04-21 | Round 2 Review 修复：DSL 彻底收窄资源授权（移除 tenant#member）；F014 补 /departments/sync；F011 集中 DepartmentDeletionHandler；F018 删 Root→Child 路径；F017 补衍生数据写入层；audit_log action 清单集中；废弃 API AC 补全；F015 冲突计数 SQL + 索引；其他一致性修复（详见 release-contract 变更历史） |
