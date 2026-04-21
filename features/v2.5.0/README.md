# v2.5.0 Feature 索引

**版本目标**：权限体系从 RBAC 迁移到 ReBAC（OpenFGA）+ 多租户支持（逻辑隔离）

**版本契约**：[release-contract.md](./release-contract.md)

**开发主线分支**：`2.5.0-PM`

---

## Feature 列表

| # | Feature | 优先级 | 状态 | 依赖 |
|---|---------|--------|------|------|
| F000 | [test-infrastructure](./000-test-infrastructure/) | P0 | 🔲 未开始 | 无 |
| F001 | [multi-tenant-core](./001-multi-tenant-core/) | P0 | 🔲 未开始 | F000 |
| F002 | [department-tree](./002-department-tree/) | P0 | 🔲 未开始 | F001 |
| F003 | [user-group](./003-user-group/) | P0 | 🔲 未开始 | F001 |
| F004 | [rebac-core](./004-rebac-core/) | P0 | 🔲 未开始 | F001, F002, F003 |
| F005 | [role-menu-quota](./005-role-menu-quota/) | P1 | 🔲 未开始 | F004 |
| F006 | [permission-migration](./006-permission-migration/) | P1 | 🔲 未开始 | F004, F005 |
| F007 | [resource-permission-ui](./007-resource-permission-ui/) | P1 | 🔲 未开始 | F004 |
| F008 | [resource-rebac-adaptation](./008-resource-rebac-adaptation/) | P1 | 🔲 未开始 | F004, F007 |
| F009 | [org-sync](./009-org-sync/) | P2 | 🔲 未开始 | F002 |
| F010 | [tenant-management-ui](./010-tenant-management-ui/) | P1 | 🔲 未开始 | F001, F005 |

---

## 依赖图

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

## 分阶段推进

| 阶段 | Feature | 说明 |
|------|---------|------|
| Phase 1 | F000 → F001 | 基础设施，关键路径 |
| Phase 2 | F002 + F003（可并行） | 组织模型 |
| Phase 3 | F004 | 权限引擎，关键路径 |
| Phase 4 | F005 + F007 + F008 + F010（高并行） | 集成层 |
| Phase 5 | F006 | 迁移，上线前最后完成 |
| 延后 | F009 | P2，飞书/企微/钉钉组织同步 |
