# Feature: F023-user-group-tenant-isolation (用户组按租户隔离)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §3.3 / §4.5（"Child Admin 管本子租户内成员、角色、资源"）
**优先级**: P1
**所属版本**: v2.5.1
**模块编码**: 沿用 F003（`user_group`）
**依赖**: F001（多租户基础）+ F011（Tenant 树）+ F019（admin-scope）

> **状态：占位 stub**（2026-04-26 创建）。本 Feature 与 Child Admin /sys 部门修复（同日提交，commit `feat(tenant): scope dept tree+permission to Child Admin`）配套，承接其遗留缺口：让 Child Admin 看见用户组 tab 之后，把后端 user_group 资源真正按 tenant 隔离。

---

## 1. 背景与遗留缺口

同日 commit 把「用户组管理」tab 对 Child Admin 显示，并放行 `_can_open_user_group_management` 让 tenant admin 能进入用户组接口。但**用户组实体本身仍是全局表，没有 tenant_id**：

- `group` 表（`bisheng/database/models/group.py`）无 `tenant_id` 字段
- `UserGroupService.alist_groups` / `aget_group` / `acreate_group` 不按 tenant 过滤/写入
- 跨 tenant 资源授权（用户组 → app/knowledge/...）目前由资源侧 tenant 隔离兜底，但用户组列表仍可见全部组

后果：
- Child Admin 进入「用户组管理」tab 看到的是**全部用户组**（包括 Root 的、其他 Child 的）
- Child Admin 创建的用户组归属不明，未挂 tenant
- Child Admin 理论上可把别 tenant 的用户加入自己组（除非另有权限拦截）

---

## 2. 验收标准（草稿，待细化）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | Child Admin (tenant=5) | `GET /api/v1/user-groups/` | 200；仅返回 `tenant_id ∈ {5, 1*}` 的组（*Root 共享策略待定，参考 F011 `share_default_to_children`） |
| AC-02 | Child Admin (tenant=5) | `POST /api/v1/user-groups/` 创建组 | 201；新组 `tenant_id=5` 自动写入 |
| AC-03 | Child Admin (tenant=5) | `PUT /api/v1/user-groups/{id}` 改 Root 组 | 403 + `19xxx` 错误码（待分配） |
| AC-04 | Sys Admin | `GET /api/v1/user-groups/` | 200；返回全部组（无 tenant 过滤） |
| AC-05 | Sys Admin（admin-scope=5） | `GET /api/v1/user-groups/` | 200；以 tenant=5 视角返回（与 AC-01 等价） |
| AC-06 | Child Admin | 把别 tenant 用户加入自己组 | 403 |

---

## 3. 设计方向（草稿）

1. **Schema 迁移**：`group` 表增加 `tenant_id INT NOT NULL DEFAULT 1`，加 `INDEX idx_group_tenant_id`。把存量组归 Root（tenant_id=1）。挂载迁移走 alembic。
2. **Service 改造**：`alist_groups` / `aget_group` 过滤；`acreate_group` 从 `login_user.tenant_id`（或 `get_current_tenant_id()` 兼容 admin-scope）写入；`aupdate_group` / `adelete_group` 跨 tenant 拦截。
3. **跨租户加成员拦截**：`UserGroupService.aadd_member` 校验 `target_user.tenant_id == group.tenant_id`（或允许 Root 用户加入任何组，待决策）。
4. **Root 共享语义**：参考 F011 `share_default_to_children`、F022 `tenant_system_model_config` 的"Root 默认 + Child 覆盖"模式，决定 Root 创建的组是否对所有 Child 可见。
5. **网关侧**：`_sync_user_group_delete_side_effects` 中的 Redis 通知（`bisheng/user_group/domain/services/user_group_service.py:65-68`）需要带 tenant 上下文，确认网关订阅端如何处理。
6. **错误码**：在 `bisheng/common/errcode/user_group.py` 新增 `UserGroupCrossTenantError`（19xxx，待分配）。

---

## 4. 状态

- [ ] tasks.md 拆解
- [ ] schema 迁移设计
- [ ] alist/aget/acreate 改造
- [ ] 错误码与跨 tenant 拦截
- [ ] Root 共享语义决策
- [ ] 网关同步影响评估
- [ ] 测试覆盖

> 本 stub 提交后请在迭代会议把本 Feature 排期入正式 v2.5.1 / v2.5.2 计划。
