# Feature: 三方组织同步

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3.2.1](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P2（延后）
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- OrgSyncProvider 抽象基类（authenticate/fetch_departments/fetch_members）
- 四种实现：FeishuProvider、WeComProvider、DingTalkProvider、GenericAPIProvider
- OrgSyncConfig ORM（provider、auth_type、auth_config、sync_scope、schedule_type、cron_expression、target tenant_id）
- OrgSyncLog ORM（执行历史、状态、统计）
- 同步调和逻辑：
  - 部门同步：新增/重命名/层级变更/归档
  - 成员同步：新增/信息变更/转岗/离职
- OpenFGA 元组维护：成员加入/离开部门时同步写入/删除 member 元组
- Celery 定时任务支持（schedule_type=cron）
- 目标租户选择（系统管理员指定，租户管理员固定为当前租户）
- API 端点：同步配置 CRUD、手动触发、同步历史查询
- 错误码模块 220

**OUT**:
- 第三方 OAuth 回调页面（用其他方式认证）
- 实时 Webhook 同步（仅支持定时/手动触发）

---

_以下章节待 Spec Discovery 后填写（P2 延后）_

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
