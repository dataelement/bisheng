# Feature: F024-tenant-user-mgmt-ui-realign（租户用户管理 UI 与 F012 派生模型对齐）

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §3（Tenant 树形 + 主部门派生归属）
**优先级**: P1（不阻塞主线，但模型不一致已造成实操困惑和数据漂移）
**所属版本**: v2.5.1（修复型，不引入新模型字段）
**模块编码**: 沿用 192（`tenant`），不新增模块编码
**依赖**: F010（被修订）+ F011（Tenant 树）+ F012（leaf 自动派生 + `UserTenantSyncService`）+ F019（admin-scope）

> **本 Feature 修订 F010 spec 的决策**：
> - **F010 AC-3.1**（"系统管理员可添加已有用户到租户，同时写入 OpenFGA member 元组"）→ **废止**：`POST /api/v1/tenants/{id}/users` 改 410 Gone；管理员加人请到组织/部门页改主部门
> - **F010 AC-3.2 / AC-3.3**（"移除用户前校验 / 清理 UserTenant + FGA 元组"）→ **废止**：`DELETE /api/v1/tenants/{id}/users/{user_id}` 改 410 Gone；解除归属请到组织/部门页改主部门
> - **F010 AC-7.x**（租户管理页用户列表）→ **修订**：列表数据源从 `UserTenant` 改为"主部门挂在该租户子树下的 User"；保留分页/搜索；保留「设为管理员/取消管理员」操作

---

## 1. 概述与用户故事

**故事 A（操作员视角对齐）**：
作为 **集团 IT 全局超管 / 子租户管理员**，
我希望 **「租户管理 → 用户管理」展示的成员列表与"用户实际归属哪个租户"一致**，
以便 **不再被"幽灵成员"误导**——当前列表查 `UserTenant`，但 F012 之后用户的真实归属由主部门派生，UI 显示"在该租户的成员"≠ "实际登录会进该租户的用户"。

**故事 B（操作动作收敛）**：
作为 **租户管理员**，
我希望 **"把人加入/移出该租户"只有一个权威入口**，
以便 **不再需要在两个 UI（租户用户管理 / 部门成员管理）之间猜哪个真起作用**——当前两个入口语义不等价：部门入口改主部门 → 真改归属；租户入口写 `UserTenant` → 不改归属（用户登录后仍进原 leaf），且下次 sync 还会被回填。

**故事 C（API 契约清理）**：
作为 **集成 BiSheng API 的外部系统/脚本**，
我希望 **能明确判断哪些租户成员管理 API 仍可用**，
以便 **不再写出"加了用户但用户实际登录进不了"的脚本**——当前 `POST /tenants/{id}/users` 仍返 200 但语义模糊（写入被动 `UserTenant` 行，不影响 leaf 派生），需要明确标记为 deprecated。

**背景**：v2.5.0 F010 落地时按"用户可属多租户、登录选择"模型设计 UI 和 API（AC-3.x 添加/移除用户、AC-5.x 多租户登录选择）。v2.5.1 F011 改向 Tenant 树形 + F012 改向"leaf 由主部门自动派生"+ `switch-tenant` 自 F011 AC-15 起返 410 Gone（`bisheng/tenant/api/endpoints/user_tenant.py:30` `switch_tenant_deprecated`），但 F010 的添加/移除用户 UI 与对应后端 API 未同步收敛，造成：

1. **操作员困惑**：刚发现的 P0 修复（`_apply_local_primary_department_change` 漏触发 sync）排查时，需要分清"UI 上看到的成员"和"实际归属"两层语义
2. **数据漂移**：`tenant_service.aadd_users` 写入的"幽灵 UserTenant 行"无法通过 sync 自然消除（sync 只管 active 行）
3. **合规盲区**：`enforce_transfer_before_relocate=true` 在租户用户管理 UI 路径里完全失效（这条路径根本不走 sync）

本 Feature 把 UI / API 收敛到"主部门派生"单一模型，消除两层语义。

---

## 2. 验收标准

> AC-ID 在本 Feature 内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 列表数据源切换（核心）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 全局超管 | `GET /api/v1/tenants/{id}/users?page=1&page_size=20` | 200；返回**主部门挂在该租户子树**的 User 列表（JOIN `Department` + `UserDepartment.is_primary=1`），不再返回仅有 `UserTenant` 行但主部门不在该租户的"幽灵成员" |
| AC-02 | 全局超管 | 用户 X 主部门刚从 Tenant A 调到 Tenant B（`UserTenantSyncService.sync_user` 已完成） | Tenant A 的成员列表立刻**不**含 X；Tenant B 的成员列表立刻**含** X；不依赖 UserTenant 行的清理 |
| AC-03 | 全局超管 | 用户 X 在 Tenant B 子树有兼职部门（`is_primary=0`），主部门在 Tenant A | Tenant A 的列表含 X；Tenant B 的列表**不**含 X（兼职不改归属，与 F012 一致） |
| AC-04 | 全局超管 | 关键字搜索 `keyword=alice` | 按 `user.user_name` LIKE 过滤；语义与切换前一致 |

### 2.2 操作按钮收敛

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-05 | 全局超管 | 打开「租户管理 → 用户管理」对话框 | 不再显示「添加用户」picker 和「移除用户」按钮；显示提示文案"添加/移除成员请到 组织 → 部门管理"，链接跳转部门页 |
| AC-06 | 全局超管 | 「设为管理员 / 取消管理员」按钮 | **保留**，行为不变（写/撤 OpenFGA `tenant:#admin` tuple，不动 UserTenant 行） |
| AC-07 | Root Tenant 用户管理对话框 | 进入对话框 | 不显示「设为管理员/取消管理员」（Root admin 由系统级 `is_admin` 标志管理，沿用现有 `isRootTenant` 短路） |

### 2.3 API 端点 deprecation

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-08 | 任意调用方 | `POST /api/v1/tenants/{id}/users` | HTTP 410 Gone；body `{"error": "410 Gone", "message": "管理租户成员请通过修改用户主部门完成（F012 派生模型）", "migration": "PUT /api/v1/department/{dept_id}/members/{user_id}/apply-edit"}` |
| AC-09 | 任意调用方 | `DELETE /api/v1/tenants/{id}/users/{user_id}` | HTTP 410 Gone；body 同上 |
| AC-10 | 任意调用方 | `GET /api/v1/tenants/{id}/users` | **保留**，行为按 AC-01~04（数据源切换） |
| AC-11 | 任意调用方 | `POST /api/v1/tenants/{id}/admins/{user_id}` / `DELETE /api/v1/tenants/{id}/admins/{user_id}` | **保留**，行为不变 |

### 2.4 残留 `UserTenant` 行的处理

> 决策见 AD-03：不做 reconcile / 不动数据，仅在新查询里过滤掉。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-12 | 升级到含 F024 的部署 | DB 中存在 v2.5.0 时期 `aadd_users` 写入的 `UserTenant` 行（主部门不在该租户子树） | 列表查询不展示这些行；DB 不动；F012 `sync_user` 行为完全不变 |
| AC-13 | 升级回滚 | 降级到不含 F024 的版本 | 数据零变更，旧版本继续按原查询返回（含幽灵成员）；回滚最干净 |

### 2.5 兼容与可观察

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-14 | 调用废弃端点的脚本 | 收到 410 后查日志 | nginx/access.log 中标记 `endpoint_deprecated=true`；后端 logger.warning 记录 `caller_ip + tenant_id + user_id` 便于排查残留集成 |
| AC-15 | F012 / F019 / 现有同步链路 | 升级后跑全量 sync | `UserTenantSyncService.sync_user` 行为完全不变（只读/写 `is_active=1` 行）；F019 admin-scope 不依赖列表查询，不受影响 |

---

## 3. 边界情况

- **历史多归属用户**：v2.5.0 时期被 `aadd_users` 加入多个租户的用户，升级后只在主部门所在租户的列表里出现一次（其他 `UserTenant` 行打 legacy）。如果操作员需要"恢复多归属"——不支持，请改用户主部门
- **Root Tenant 列表**：Root 租户没有 `mounted_tenant_id`，列表数据源退化为"主部门 path 不在任何 Child Tenant 子树下"的 User（即真正归属 Root 的用户）
- **跨租户兼职**：用户 X 主部门在 Tenant A，兼职部门在 Tenant B 子树——X 在 A 的列表，不在 B 的列表。如果操作员希望"看到所有跨租户协作过的人"——本 Feature 不提供该视图，可在未来加"协作者"独立页
- **API 调用方仍依赖 POST/DELETE**：返 410，并在 release-notes 标注 deprecation。不提供"开关恢复旧端点"的逃生门——这与 `switch-tenant` 410 Gone 的处理保持一致
- **不支持**：v2.5.x 系列**不**回头支持"用户多租户 + 登录选择"模型；该方向已在 F011/F012 决策中废弃（2026-04-18 PRD Review）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 列表数据源 | A: 继续查 `UserTenant` 但加 status 过滤 / B: 改为 JOIN `Department.path` + `UserDepartment.is_primary=1` / C: 同时支持两种视图（带 toggle） | **B** | A 仍以衍生表为权威源，治标不治本；C 又把"两种语义"暴露给操作员，违背收敛初衷；B 直接以 source-of-truth 查询，与 `TenantResolver.resolve_user_leaf_tenant` 同源 |
| AD-02 | 废弃端点处理 | A: 保留端点但写 deprecated header / B: 直接 410 Gone / C: 改为转发到部门 API | **B** | 与 `switch-tenant` 的 410 Gone 模式一致，简单直接；A 留下"看似可用"的歧义路径；C 跨域转发涉及主部门解析逻辑泄漏到不合适的层 |
| AD-03 | 残留 UserTenant 行处理 | A: 直接 hard-delete / B: 软删（status='legacy'）+ 启动钩子 reconcile / C: 不动数据，新查询不再以 UserTenant 为权威源 | **C** | F024 把列表的权威源从 `UserTenant` 整体迁到"主部门 JOIN" → 老的幽灵 `UserTenant` 行**根本不会被新查询触达**，无需过滤更无需迁移；F024 落地后 POST/DELETE 已 410、`aadd_users` service 仅内部脚本可达，legacy 集合是**封闭历史集合**，自然消亡；C 不动数据 → 回滚最干净 → 升级风险最低；A 破坏调岗历史可追溯；B 增加启动钩子 + 幂等键 + audit 写入，复杂度不偿失 |
| AD-04 | UI 提示位置 | A: 对话框顶部 banner / B: 表格空状态提示 / C: 隐藏直接消失 | **A** | 操作员从「添加用户」按钮消失到理解"为啥消失"需要引导；C 信息密度不足，预计有支持工单冲击；B 只在空列表时见，常见场景看不到 |
| AD-05 | Service 层方法保留与否 | A: 保留 `aadd_users` / `aremove_user` 给内部脚本用 / B: 与 API 同步删除 | **A** | 内部 worker / migration 工具可能用到；保留 service 方法 + 加 deprecation warning + 标 internal-only，比删了再补回来更稳 |
| AD-06 | 新查询接口的命名 | A: 沿用 `GET /tenants/{id}/users`（语义内变） / B: 新增 `GET /tenants/{id}/members-by-primary-dept` | **A** | 现有前端调用点已散落，改路由会触发更多前端回归；语义内变 + 在 spec/changelog 明确说明，性价比更高 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

**不新增表，不变更字段**。

`UserTenant` 表 schema、`status` 取值、`is_active` 语义全部保持不变。F024 仅在新 DAO 查询里用 `NOT EXISTS` 子查询把"主部门不在该租户子树"的 user 过滤掉，不动 DB 一行数据。

### Domain 模型 / DTO

无新增。`bisheng/tenant/domain/schemas/tenant_schema.py` 不动。

---

## 6. API 契约

### 端点变更

| Method | Path | F024 后行为 | 关联 AC |
|--------|------|-------------|--------|
| GET | `/api/v1/tenants/{id}/users` | **数据源变**：JOIN `Department.path` + `UserDepartment.is_primary=1`；返回 schema 不变 | AC-01~04, AC-10 |
| POST | `/api/v1/tenants/{id}/users` | **410 Gone** | AC-08 |
| DELETE | `/api/v1/tenants/{id}/users/{user_id}` | **410 Gone** | AC-09 |
| POST | `/api/v1/tenants/{id}/admins/{user_id}` | 不变 | AC-11 |
| DELETE | `/api/v1/tenants/{id}/admins/{user_id}` | 不变 | AC-11 |

### 410 响应示例

```json
HTTP/1.1 410 Gone
{
  "error": "410 Gone",
  "message": "管理租户成员请通过修改用户主部门完成（F012 派生模型）",
  "migration": "POST /api/v1/department/{dept_id}/members/{user_id}/apply-edit",
  "deprecated_since": "v2.5.1",
  "removed_in": "v2.6.0"
}
```

### 错误码表

不新增模块错误码。复用：
- 410 Gone：`{ "error": "410 Gone" }`，与 `switch-tenant` 端点同形态（参见 `bisheng/tenant/api/endpoints/user_tenant.py:30`）

---

## 7. Service 层逻辑

### 修改方法

| 方法 | 文件 | 变更 |
|------|------|------|
| `TenantService.aget_tenant_users` | `bisheng/tenant/domain/services/tenant_service.py` | 查询逻辑从 `UserTenantDao.aget_tenant_users` 切到新 DAO 方法 `UserDepartmentDao.aget_users_by_tenant_subtree(tenant_id)`；返回 schema 不变（`{data, total}`） |
| `TenantService.aadd_users` | 同上 | 加 `@deprecated` 装饰器 + logger.warning；保留实现给内部脚本用；公开 API 端点改 410 |
| `TenantService.aremove_user` | 同上 | 同上 |

### 新增方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `UserDepartmentDao.aget_users_by_tenant_subtree` | `bisheng/database/models/department.py` | 解析 tenant 的 `root_dept` 取得 `path` → JOIN `Department.path LIKE '<root_dept_path>%' AND UserDepartment.is_primary = 1` → JOIN `User`；分页 + keyword 参数；与 `TenantResolver.resolve_user_leaf_tenant` 同源逻辑（避免 UI 显示和 leaf 派生分叉） |

伪代码：
```python
# Tenant root_dept_path 解析略
SELECT u.user_id, u.user_name, u.avatar, ut.last_access_time AS join_time
FROM user u
JOIN user_department ud ON ud.user_id = u.user_id AND ud.is_primary = 1
JOIN department d ON d.id = ud.department_id
LEFT JOIN user_tenant ut
       ON ut.user_id = u.user_id AND ut.tenant_id = :tenant_id AND ut.is_active = 1
WHERE d.path LIKE :root_dept_path_prefix
  AND (:keyword IS NULL OR u.user_name LIKE :keyword)
ORDER BY ut.last_access_time DESC NULLS LAST, u.user_id
LIMIT :page_size OFFSET :offset
```

注意：本查询不需要 `NOT EXISTS` 过滤——因为列表的"权威源"就是主部门视图，根本不查 `UserTenant`，幽灵行天然不会出现。`UserTenant` 仅作为"上次访问时间"等元信息的 LEFT JOIN 装饰。

---

## 8. 前端设计

### 8.1 Platform 前端

> 路径：`src/frontend/platform/src/pages/TenantPage/`

**修改组件**：

```
TenantPage/
├── components/
│   ├── TenantUserDialog.tsx           ← 主修改文件
│   │   ├── 删除「添加用户」picker (DepartmentUsersSelect + Button)
│   │   ├── 删除「移除用户」按钮
│   │   ├── 新增顶部 Banner：「成员归属由用户主部门决定。添加/移除请到 [组织管理]，
│   │   │                    本页只展示当前归属并提供管理员配置。」+ 跳转链接
│   │   └── 保留「设为管理员/取消管理员」按钮（已有逻辑不变）
│   └── ...
```

**API 调用变更**：
- `src/controllers/API/tenant.ts`：
  - 删除 `addTenantUsersApi` 和 `removeTenantUserApi` 调用点（保留导出但标 `@deprecated` 注释，给可能的外部使用方过渡）
  - `getTenantUsersApi` 调用不变（端点路径不变，返回 schema 不变）

**i18n** 键新增：

```json
{
  "tenant.membershipBanner.title": "成员管理已迁移",
  "tenant.membershipBanner.body": "成员归属由用户主部门决定。添加/移除请到 [组织管理]，本页只展示当前归属并提供管理员配置。",
  "tenant.membershipBanner.cta": "前往组织管理"
}
```

### 8.2 Client 前端

不涉及。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/test/test_tenant_users_query_source.py` | AC-01~04 数据源切换 + AC-12 幽灵行不展示测试 |
| `src/backend/test/test_tenant_membership_endpoints_deprecated.py` | AC-08~09 410 响应测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/database/models/department.py` | 新增 `UserDepartmentDao.aget_users_by_tenant_subtree` |
| `src/backend/bisheng/tenant/domain/services/tenant_service.py` | `aget_tenant_users` 改用新 DAO；`aadd_users`/`aremove_user` 加 `@deprecated` + logger.warning |
| `src/backend/bisheng/tenant/api/endpoints/tenant_users.py` | `add_users` / `remove_user` 端点改 410；`get_tenant_users` 行为不变（端点路径不变，service 内部数据源切了） |
| `src/frontend/platform/src/pages/TenantPage/components/TenantUserDialog.tsx` | 删「添加用户」picker + 删「移除用户」按钮 + 加跳转 Banner |
| `src/frontend/platform/src/controllers/API/tenant.ts` | `addTenantUsersApi`/`removeTenantUserApi` 加 `@deprecated` 注释 |
| `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/bs.json` | 新增 `tenant.membershipBanner.*` 三个 key |
| `features/v2.5.1/release-contract.md` | 在「F010 修订记录」段加一条：F024 修订 F010 AC-3.x / AC-7.x |

### 不动（兼容）

| 文件 | 说明 |
|------|------|
| `UserTenant` ORM / `UserTenantDao` | 保留全部 — `sync_user` 仍依赖；status='legacy' 仅是新枚举 |
| `bisheng/tenant/api/endpoints/tenant_admin.py` | tenant 管理员 API 不动（仍是租户作用域操作） |

---

## 10. 非功能要求

- **性能**：新查询 JOIN Department + UserDepartment + User 三表，需在 `Department.path` 上有 prefix index（已有 F011 落地的 `idx_department_path`）；分页查询 P95 < 200ms（同等数据量级 v2.5.0 测试结果对照）
- **安全**：`get_tenant_users` 仍走 `get_admin_user` 依赖；新 DAO 方法默认 `bypass_tenant_filter()`（管理路径）
- **兼容性**：
  - GET 端点行为内变但路径/schema 不变 → 前端调用点零改动
  - POST/DELETE 端点直接 410 → 外部脚本侧需要适配（release-notes 标 BREAKING）
  - DB 层无 schema 变更，回滚直接降级即可
- **可观察**：reconcile 任务的 metadata 计入 audit_log，便于复盘升级期间标了多少 legacy 行

---

## 11. 上线节奏

**一次到位**——前后端 + API 契约变更同 PR 同版本发布。

理由：
- AD-03 选 C 后无数据迁移，无启动钩子，回滚零数据风险
- 前端 / 后端 / API 三层动作统一上线，不出现"前端隐藏按钮但后端还能调用"的中间态（与 F024 立项动机相悖）
- 当前 v2.5.1 部署面以私有化集成为主，POST/DELETE 端点的外部调用方可控

**Release Notes 必备项**：
- BREAKING：`POST /api/v1/tenants/{id}/users` / `DELETE /api/v1/tenants/{id}/users/{user_id}` 改 410 Gone
- 迁移指引：用 `POST /api/v1/department/{dept_id}/members/{user_id}/apply-edit` 改主部门
- 提前通知：发版前向已知 SDK / 集成对接方告知

---

## 相关文档

- 版本契约：[features/v2.5.1/release-contract.md](../release-contract.md)
- 被修订 spec：[features/v2.5.0/010-tenant-management-ui/spec.md](../../v2.5.0/010-tenant-management-ui/spec.md)
- F012 leaf 派生：[features/v2.5.1/012-tenant-resolver/spec.md](../012-tenant-resolver/spec.md)
- 同模式参考：`switch-tenant` 410 Gone 实现（`bisheng/tenant/api/endpoints/user_tenant.py:30`）
- 上游修复：本 Feature 立项的直接触发点是 P0 修复（`_apply_local_primary_department_change`）+ G1（`aadd_members(is_primary=1)` 路由到 `change_primary_department`）+ G2（`acreate_local_member` 补 sync）排查时暴露的 UI/模型漂移。本 Feature 是这些"功能层修复"之上的"模型一致性收敛"，逻辑上独立但动机连贯
