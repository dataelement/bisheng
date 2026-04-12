# Feature: 租户管理与登录流程

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 多租户需求文档 §3-5](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 租户 CRUD API 端点（系统管理员专用）：
  - `POST /api/v1/tenants` — 创建租户
  - `GET /api/v1/tenants` — 租户列表（分页）
  - `GET /api/v1/tenants/{id}` — 租户详情
  - `PUT /api/v1/tenants/{id}` — 更新租户
  - `PUT /api/v1/tenants/{id}/status` — 启用/停用/归档
  - `DELETE /api/v1/tenants/{id}` — 物理删除
  - `GET /api/v1/tenants/{id}/quota` — 配额与用量查询
  - `PUT /api/v1/tenants/{id}/quota` — 设置配额
  - `POST /api/v1/tenants/{id}/users` — 添加用户到租户
  - `DELETE /api/v1/tenants/{id}/users/{user_id}` — 移除用户
  - `GET /api/v1/user/tenants` — 获取当前用户租户列表
  - `POST /api/v1/user/switch-tenant` — 切换租户（重发 JWT）
- 租户管理页面（系统管理员入口）：
  - 列表：名称/编码/状态/用户数/存储用量/创建时间
  - 创建表单：名称/编码(不可变)/Logo/联系人/存储配额/管理员选择
  - 编辑：名称/Logo/联系人/状态/管理员/配额
  - 停用确认对话框 + JWT 吊销 + API 拦截
- 登录流程变更：
  - 认证后查询 user_tenant 列表
  - 1 个租户 → 自动进入
  - 多个租户 → 显示租户选择页（按 last_access_time 排序）
  - 0 个租户 → 提示"无可用企业，请联系管理员"
- 租户切换：
  - Header 下拉显示当前租户名/Logo
  - 选择其他租户 → 重发 JWT（新 tenant_id）→ 整页刷新
  - 系统管理员额外显示"系统管理"入口
- 首次登录初始化：无租户时强制创建租户流程

**OUT**:
- Tenant ORM 模型定义 → F001-multi-tenant-core
- 配额执行逻辑 → F005-role-menu-quota
- 跨租户使用分析仪表盘 → P2

**关键文件（预判）**:
- 新建: `src/backend/bisheng/tenant/`（DDD 模块：api/ + domain/） 或集成到已有 user 模块
- 新建: `src/frontend/platform/src/pages/TenantPage/`
- 修改: `src/frontend/platform/src/pages/LoginPage/`（租户选择）
- 修改: `src/frontend/platform/src/components/Header`（租户切换下拉）

**关联不变量**: INV-13, INV-14

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
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
