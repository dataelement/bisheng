# Release Contract — v2.6.0

> 本文件是 v2.6.0 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| ApprovalScenario / ApprovalRouteRule / ApprovalFlowDefinition / ApprovalFlowVersion / ApprovalNodeDefinition | F025-approval-center-unification | 审批场景配置、条件分支、流程定义、流程版本与顺序节点 |
| ApprovalInstance / ApprovalTask / ApprovalException / ApprovalOutbox / ApprovalActionLog | F025-approval-center-unification | 审批实例、审批任务、异常、业务执行队列、审批时间线 |
| UserMenuAccess | F025-approval-center-unification | 菜单权限申请通过后的用户级菜单授权与撤回记录 |
| ChannelAuthorizationWrite | F026-channel-active-authorization | 频道资源主动授权、撤销授权、频道 relation-model binding 写入与清理行为 |
| SpaceChannelMember(channel relation/source fields) | F026-channel-active-authorization | `space_channel_member` 中 `business_type='channel'` 的四档关系与授权来源字段；不拥有知识空间成员关系 |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-1 | 审批事实源统一为 `approval_instance` / `approval_task`；站内信只负责提醒和跳转，不作为审批状态真相来源 | ApprovalInstance, ApprovalTask, InboxMessage | F025 |
| INV-2 | 审批中心所有新表都必须带 `tenant_id`，并遵守现有多租户隔离规则；申请人/审批人/管理员的数据可见性不能跨租户 | Approval* | F025 |
| INV-3 | 审批通过不等于绕过业务安全检查；handler 执行业务动作前仍需复用原业务校验逻辑 | ApprovalOutbox, 业务资源模块 | F025 |
| INV-4 | 菜单权限申请通过后只写用户级菜单授权，不修改角色菜单权限；用户有效菜单 = 角色菜单 ∪ 个人授权 ∪ 管理员权限 | UserMenuAccess, RoleAccess | F025 |
| INV-5 | 流程变更采用版本快照模型；已发起实例继续使用其创建时的流程版本，新配置仅影响后续新申请 | ApprovalFlowVersion, ApprovalInstance | F025 |

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F025-approval-center-unification | F005, F011, F012, F013 | 依赖菜单审批模式、多租户、租户解析与权限隔离基线 |
| F026-channel-active-authorization | F006, F013 | 依赖统一 ReBAC/OpenFGA 授权与多租户权限隔离基线 |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 181 | approval | F025（沿用现有 `common/errcode/approval.py`，扩展为统一审批中心错误码） |
| 190 | channel / bisheng_information | F026 沿用现有 `common/errcode/channel.py`，扩展频道授权错误码时不得与既有 190xx 冲突 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-05-18 | 初始化 v2.6.0 契约，并登记 F025 统一审批中心的领域对象、依赖与不变量 | F025 |
| 2026-05-28 | 登记 F026 频道主动授权的领域对象归属、依赖与 190 模块错误码边界 | F026 |
