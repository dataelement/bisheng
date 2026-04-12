# Feature: 资源模块 ReBAC 适配

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §2](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)、[2.5 多租户需求文档 §8](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 逐模块改造（建议顺序 knowledge → workflow → assistant → tool → channel → dashboard）：
  - 替换 `LoginUser.access_check()` 为 PermissionService.check() 委托链路
  - 资源创建时调用 `PermissionService.authorize()` 写 owner 元组
  - 资源删除时调用 PermissionService 删除所有相关元组
  - 列表 API 使用 `LoginUser.get_accessible_ids()` 过滤可访问资源
  - 资源创建前调用配额检查（F005 提供的 `get_effective_quota`）
- 改造 LoginUser 核心方法：
  - `access_check` / `async_access_check` 内部委托 PermissionService
  - 新增 `get_accessible_ids(object_type, relation)` 方法
- 替换所有 `RoleAccessDao.judge_role_access` 调用（WEB_MENU 类型除外）
- 替换所有 `GroupResource` 访问逻辑
- 替换所有 `SpaceChannelMember` 访问逻辑

**OUT**:
- linsight / workstation / mcp（无权限控制，PRD 明确豁免）
- evaluation / mark_task / dataset（仅 RBAC 菜单控制，F005 处理）

**关键决策（预判）**:
- AD-01: 按模块逐一改造，顺序 knowledge（最复杂，有文件夹层级）→ workflow → assistant → tool → channel → dashboard
- AD-02: 适配器模式 — LoginUser 方法内部委托 PermissionService，最小化端点代码变更

**关键文件（预判）**:
- 修改: `src/backend/bisheng/user/domain/services/auth.py`（LoginUser 方法改造）
- 修改: `src/backend/bisheng/knowledge/` 相关端点和 service
- 修改: `src/backend/bisheng/api/v1/` 下 workflow/assistant/tool 相关端点
- 修改: `src/backend/bisheng/channel/` 相关端点和 service

**关联不变量**: INV-2, INV-3, INV-11, INV-15

---

_以下章节待 Spec Discovery 后填写_

## 1. 概述与用户故事

## 2. 验收标准

## 3. 边界情况

## 4. 架构决策

## 5. 数据库 & Domain 模型

## 6. API 契约

## 7. Service 层逻辑

## 8. 前端设计

## 9. 文件清单

## 10. 非功能要求

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
