# Release Contract — v3.0.1

> 本文件是 v3.0.1 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。
>
> **版本定位**：v3.0.1 是 v3.0.0（应用工场）之后的补丁线，不引入新的产品方向；上游 PRD 沿用
> 《3.0 应用工场 PRD-1》与伴生《3.0 开放 API 鉴权与身份传递 PRD》，本版本不新增 PRD。
>
> **编号约定**：
> - Feature 编号**全局递增**（跨版本连续）：v3.0.0 已用到 **F119**，本版本从 **F120** 起。
> - 跨 Feature 不变量：v3.0.0 的 **INV-1 ~ INV-43** 在本版本**无条件继续生效**；新增从 **INV-44** 起。
> - 引用历史编号时必须带版本前缀（v2.5.1 的 INV-T* 与 v3.0.0 的 INV-N 是不同编号空间）。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| 无新增独立领域对象 | — | 本版本首个 feature 只新增一条登录链路，不新建表 |
| **企微 OAuth 登录会话**（授权发起、state 校验、回调换取企业微信 userid 的一次性会话） | **F120-wecom-sso** | 新建。只拥有"一次登录交互"的生命周期（Redis 中短 TTL、一次性消费），不拥有任何持久实体 |
| `User` / `UserRole`（含首登超管引导） | 原 Owner 不变（F106 用户域；首登超管语义见 INV-44） | F120 只通过既有 Service 调用，不新增字段、不改变既有写入语义 |
| `Department` / `UserDepartment` | 原 Owner 不变（F048 部门投影 / F009 组织同步） | F120 登录时携带企微部门并调用既有 LoginSync 链路；不新增写入口 |
| `UserTenant`（leaf 租户派生） | 原 Owner 不变（tenant `UserTenantSyncService`） | F120 复用既有派生逻辑 |
| `OrgSyncConfig`（企微 corpid / corpsecret / agent_id） | 原 Owner 不变（F009/F021 组织同步） | F120 **只读**该配置，作为企微登录的唯一凭据来源（INV-45）；不新增配置表、不新增管理页 |
| `AuditLog` / `OrgSyncLog` | 原 Owner 不变（审计 / 组织同步） | F120 写入既有审计动作与 sso_realtime 同步日志类型 |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-44 | **企微 SSO 不改变"谁可以成为超管"的既有约束**：只有平台不存在任何用户时，第一个成功登录的企微用户才自动获得超管角色；此后任何企微首登用户只获得默认角色 | User / UserRole | F120 AC-09 |
| INV-45 | **企微登录凭据唯一来源是组织同步配置**（`org_sync_config` 中 provider=wecom 的启用配置）。登录链路不得新增 corpid/corpsecret 配置文件项，也不得允许多套凭据并存；配置缺失或停用时企微登录入口不可用（fail-closed） | OrgSyncConfig（只读） | F120 AC-03 / AC-13 |
| INV-46 | **登录凭据不进 URL**：任何登录成功后的跳转 URL 中不得携带可复用的访问令牌（query / hash / path 均不可），登录态只能通过服务端下发的 cookie 或等价的非 URL 通道交给浏览器 | 企微 OAuth 登录会话 | F120 AC-08 |
| INV-47 | **企微登录必须复用既有 SSO 同步语义**：用户 upsert、部门绑定、leaf 租户派生、禁用用户拦截、跨来源账号冲突处理，一律走 F014 `LoginSyncService` 的现有规则，不得在登录链路里另写一套用户创建/绑定逻辑 | User / UserDepartment / UserTenant | F120 AC-05 / AC-06 / AC-10 |

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F120-wecom-sso | F009-org-sync / F021-wecom-org-sync-provider | 原因：读取 wecom 组织同步配置（corpid/corpsecret/agent_id）作为登录凭据 |
| F120-wecom-sso | F014-sso-org-realtime-sync | 原因：复用 `LoginSyncService`（用户 upsert + 部门绑定 + 租户派生 + JWT 签发） |
| F120-wecom-sso | F048 部门权限投影 | 原因：部门归属写入后沿用既有 FGA 投影路径，不另建 |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。权威来源始终是 `common/errcode/` 中的 `Code` 字面量。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 193 | sso_sync（已有 19301–19304、19310–19318） | F014 |
| **193（子段 19330–19349）** | **企微 SSO 登录**（授权/回调/state/配置缺失/企微接口错误） | **F120-wecom-sso** |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-11-16 | 创建 v3.0.1 契约；登记 F120，分配 INV-44 ~ INV-47 与 193 段 19330–19349 | 全版本 |
