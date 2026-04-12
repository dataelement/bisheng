# Feature: 资源权限管理前端

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §2.5](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 前端资源授权对话框（三类授权主体：用户/部门/用户组）
- 授予权限 UI：选择主体类型 → 搜索/选择主体 → 选择权限级别（viewer/editor/manager）
- 撤回权限 UI：从权限列表中移除授权
- 继承权限展示：显示"继承自父级"并附来源链接
- 权限级别徽章：在资源列表页显示当前用户的权限级别（viewer/editor/manager/owner）
- 前端 API 封装层 `src/controllers/API/permission.ts`（包装 F004 的后端 API）
- 适用全部资源类型：knowledge_space、workflow、assistant、tool、channel、dashboard

**OUT**:
- 后端权限 API → F004-rebac-core
- 后端权限执行（业务模块中的 check 调用）→ F008-resource-rebac-adaptation
- 文件夹级权限 UI（知识库文件夹）→ 随 F008 知识库适配一起处理

**关键文件（预判）**:
- 新建: `src/frontend/platform/src/controllers/API/permission.ts`
- 新建: `src/frontend/platform/src/components/bs-ui/permission/` 组件目录
- 修改: 各资源列表页（增加权限徽章）

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
