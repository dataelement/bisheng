# Design: 部门知识空间唯一管理员与超级管理员前台隐藏

> **本文档定位 — 现状快照（Why this How）**
> spec.md 回答做什么；本文回答为什么这么实现；tasks.md 是执行流水。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0（cofco 分支 feat/cofco-818）
**最后更新**: 2026-08-13

---

## 1. 目标与非目标

- **目标**：把部门知识空间的管理权来源从「创建者(超管) + 部门管理员自动同步」收敛为「超管显式配置的唯一空间管理员」；超管的平台治理身份与空间权限身份彻底分离，前台不落任何隐式关系。
- **非目标**：不动普通/个人空间的创建者模型；不动 F033 的部门成员 viewer 收敛；不动频道成员模型；不做管理员多人制或转交审批。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7；错误码沿用知识空间段 **180xx**（`common/errcode/knowledge_space.py`，已用到 18002x 段位前的 18000–18011+，新码续排）。
- **DB 与 OpenFGA 双写不在一个事务里**：管理员唯一性必须由 **MySQL/DM8 的列 + 唯一语义**保证，FGA tuple 只是权限物化，允许短暂滞后、必须可对账修复。
- 双 DB（MySQL/DM8）：新列的 DDL 走 Alembic revision；存量归一是**运维脚本**，不进 revision（backend AGENTS.md 铁律）。
- cofco 分支特殊性：本功能落在 `feat/cofco-818`，后续向主线合并时注意「有意删除」不被误恢复（见记忆 cofco-merge-clobber-pitfall）。

---

## 3. 方案对比与选定

### 决策 1：空间管理员的真相源

- **备选**：
  - A. `department_knowledge_space` 表加 `admin_user_id`（nullable）列，作为唯一真相；成员行 + FGA tuple 为物化副本。
  - B. 只用 `space_channel_member` 的 ADMIN 行表达（现状风格），靠服务端校验唯一。
  - C. 只用 OpenFGA `owner` tuple 表达。
- **选定**：A
- **原因**：AC-05/06 要求「至多一名 + 原子替换 + 无中间状态」，单列 UPDATE 天然原子且可加约束级保证；B 是行集合，唯一性只能靠应用层锁，正是现状产生多 ADMIN 的根源；C 的 FGA 写入无事务，做不了原子替换真相源。`admin_user_id IS NULL` ⟺【待配置管理员】，不需要独立状态列。
- **何时该重新考虑**：如果产品改为允许多名空间管理员。

### 决策 2：管理员的权限物化形态

- **备选**：
  - A. 沿用现状形态：`space_channel_member` 一行 `user_role=ADMIN`（新 `membership_source="space_admin"`）+ FGA `knowledge_space#manager` tuple。
  - B. 新造 FGA relation（如 `space_admin`）并改授权模型。
- **选定**：A
- **原因**：审批链路（`approval_service.py:273`、`knowledge_space_subscribe_scenario_handler.py:45`）与空间管理能力判定都按「CREATOR/ADMIN 成员 + manager relation」解析，沿用形态则审批、成员管理、前台展示全部免改——空间管理员天然成为审批人、天然在成员界面展示（AC-03）；改 FGA 模型要动 authorization_model + 全量重放，收益为零。
- **何时该重新考虑**：FGA 模型大版本重构时。

### 决策 3：部门管理员自动同步机制——整体下线（★ 用户已确认 2026-08-13）

- **备选**：
  - A. 整体删除：`_grant_default_department_admins` / `sync_department_admin_memberships` / `cleanup_removed_department_admins` / `_sync_added_admin` / `_sync_removed_admin` 及其调用点全删，`membership_source="department_admin"`、`department_admin_promoted_from_role` 字段停用（列保留不删，避免双 DB 无谓 DDL）。
  - B. 保留机制但降级为普通成员同步。
- **选定**：A
- **原因**：用户拍板「去掉,简单」。机制与唯一管理员直接冲突（可 0 可多）；钩子散布 `department_service.py:1160/1274/2008`、`login_sync_service.py:700/736`，保留即维护两套权限来源。
- **实现偏差（已落地）**：`department_admin_promoted_from_role` 列**没有停用**而是被 `space_admin` 物化复用——语义完全相同（记录提升为管理员前的角色,AC-07 回退需要）；`membership_source` 新增值 `"space_admin"`,`"department_admin"` 仅存量遗留、迁移脚本清除。
- **何时该重新考虑**：客户要求部门管理员天然可管本部门空间时（届时以显式授权替代,不复活自动同步）。

### 决策 4：创建者不落前台关系的实现方式

- **备选**：
  - A. `create_knowledge_space` 加 `materialize_creator=False` 分支：部门空间创建时不写 CREATOR 成员行、不写 FGA owner tuple；`Knowledge.user_id` 保留（审计意义 + 表非空约束），`department_knowledge_space.created_by` 继续记录审计。
  - B. 照常写入，再靠所有读接口过滤超管。
- **选定**：A
- **原因**：写入源头掐断后，「隐藏超管」在增量数据上自动成立，读路径（成员列表 `/resources/{type}/{id}/permissions`、人数统计、候选人 `grant-subjects/*`、`get_space_info`）**不需要加过滤分支**——过滤方案要在每个读口重复实现且永远漏（AC-12 的人数一致性极难保证）。存量的 CREATOR 行 / owner tuple 由迁移脚本清除。
- **何时该重新考虑**：若发现有读路径按「space 必有 creator」假设崩溃（见 §5 坑 2）。

### 决策 5：管理员失效的触达方式

- **备选**：
  - A. 事件钩子：用户停用/删除、SSO 同步移除、移出企业的各入口调用 `DepartmentKnowledgeSpaceService.handle_admin_invalidated(user_id)`，命中 `admin_user_id` 的空间置 NULL + 通知超管。
  - B. 定时对账任务扫描失效管理员。
- **选定**：A 为主，B 作兜底（复用现有 Beat 对账风格，频率低）。
- **原因**：AC-08 要求即时限制与通知；纯定时有窗口期。现状 `cleanup_removed_department_admins` 只挂了 SSO 和部门流程，**用户管理页的停用/删除入口今天没有钩子**，是新增覆盖点。
- **何时该重新考虑**：入口收敛到统一的用户生命周期事件总线后改订阅。

### 决策 6：【待配置管理员】的操作限制实现

- **选定**：读时判定 `admin_user_id IS NULL` → 拒绝「新增授权（authorize 写口）+ 需管理员审批的场景发起」，返回新错误码；浏览/检索/问答链路不查此状态（AC-09）。不做独立状态机表。
- **原因**：状态可由列推导，避免第二真相源。

---

## 4. 系统现状（接手必读）

### 4.1 今天的数据流（改造前）

**创建**：`POST /api/v1/knowledge/space/department/batch-create`（`knowledge_space.py:241`）→ `DepartmentKnowledgeSpaceService.batch_create_spaces`（`department_knowledge_space_service.py:289`）→ `KnowledgeSpaceService.create_knowledge_space`（写 Knowledge + **CREATOR 成员行**`knowledge_space_service.py:1532` + **FGA owner tuple**`:1539`）→ 写 `department_knowledge_space` 绑定行 → 部门 viewer tuple → **拉部门管理员列表逐个授 ADMIN + manager tuple**（`_grant_default_department_admins`）。

**部门管理员变动同步**：部门管理员任免（`department_service.py:1160/1274`）、SSO 组织同步（`login_sync_service.py:700/736`）、部门删除（`department_service.py:2008`）→ `sync_department_admin_memberships` / `cleanup_removed_department_admins` → 增删 ADMIN 成员行 + manager tuple（含「提升前角色回退」逻辑 `department_admin_promoted_from_role`）。

**审批人解析**：需空间管理员审批的场景按「该空间 CREATOR/ADMIN 成员」取审批人（`approval_service.py:273`）；`approver_resolver.py:77` 的 `knowledge_space_owner/manager` 源由场景 handler 解析。

**前台展示**：成员/权限详情 `GET /resources/knowledge_space/{id}/permissions`（`resource_permission.py:1072`）、候选人 `grant-subjects/*`（`:917` 起）、空间详情 `get_space_info`。超管作为 CREATOR 今天**会**出现在这些口的返回里——这就是要消灭的现状。

**平台治理入口**：`GET /space/department/all`（超管全量列表，`_ensure_super_admin` 平台级校验，不依赖成员关系）——这条已经符合目标口径,不动。

### 4.2 目标态关键字段 / 契约

| 字段 / 结构 | 类型 | 说明 | 谁消费 |
|---|---|---|---|
| `department_knowledge_space.admin_user_id` | int NULL | 唯一空间管理员；NULL ⟺ 待配置（迁移 `f049_dks_admin_user_id`） | 服务端校验、管理列表、审批锁 |
| batch-create item `admin_user_id` | int 必填（服务端校验,缺→18003） | 创建时指定负责人 | platform 两个创建弹窗 |
| `PUT /knowledge/space/department/{department_id}/admin` | HTTP API | 超管更换管理员（原子,冲突→18006） | platform 已创建列表「更换负责人」 |
| `/space/department/all` 响应 `admin_user_id`/`admin_user_name`/`pending_admin` | JSON | 负责人与待配置展示（`_decorate_department_metadata` 统一填充,并抹掉部门空间的创建者 user_role/user_name/avatar） | platform 管理面 + client 各空间列表 |
| `space_channel_member.membership_source="space_admin"` | str | 管理员物化行标记（复用 `department_admin_promoted_from_role` 存回退角色） | 成员展示 / 审批解析（无感知） |
| 错误码 18003/18004/18005/18006 | 未配管理员 / 用户无效 / 待配置受限 / 并发冲突 | 三语文案 `packages/locales` `api_errors` | 两个前端 |
| 站内信 action codes | `assigned_/revoked_knowledge_space_admin`（沿用）、`pending_knowledge_space_admin`（新,发超管） | client 通知中心 i18n `com_notifications_action_*` | client |
| Beat `reconcile_department_space_admins` | 每 6h（:30 错峰） | 列↔成员行↔manager 元组对账 + 漏网失效兜底（`worker/knowledge/space_admin_reconcile.py`） | 运维观测（repaired/invalidated 日志） |

### 4.3 关键模块职责（目标态）

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `department_knowledge_space_service.py` | 管理员配置/原子更换/失效标记/存量归一编排 | 不再有任何部门管理员同步逻辑 |
| `knowledge_space_service.py` | 空间创建加 `materialize_creator` 开关 | 普通空间路径零变化 |
| `department_service.py` / `login_sync_service.py` | 删除对同步钩子的调用 | 不感知空间管理员 |
| `user` 模块停用/删除入口 | 调 `handle_admin_invalidated` | 不直接写空间数据 |
| platform `DepartmentKnowledgeSpaceManagerDialog.tsx`（326 行） | 创建弹窗加必选负责人（企业用户搜索）、待配置徽标、更换入口 | 客户端 client 无改动点 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | DB 与 FGA 双写无事务：`admin_user_id` UPDATE 成功但 manager tuple 写失败是可能态 | 管理员「有名无权」，且现状代码对 FGA 失败只 warning 吞掉（`_grant_department_admin_manager:130`） | 换人流程按「先写列，FGA 失败重试 + 对账兜底」；对账任务比对列与 tuple |
| 2 | 部分读路径可能假设空间必有 CREATOR 成员/owner tuple（如 `knowledge_space_service.py:422/885/4850` 按 CREATOR 分支） | 部门空间不再有 CREATOR 后这些分支静默走空,权限判定或展示异常 | tasks 里逐处排查 CREATOR 分支对部门空间的行为 |
| 2b | **`/permissions` 接口会从 `Knowledge.user_id` 现算合成一条不可删的「创建者=owner」行**（`resource_permission.py _add_creator_owner_entry`,knowledge_space 视创建者为永久 owner）——不是存量数据,迁移清不掉,105 走查时真实命中 | 部门空间授权面板永远显示超管创建者,AC-04/12 落空 | `_add_creator_owner_entry` 对部门空间（有 dks 绑定）直接跳过合成 |
| 3 | `Knowledge.user_id` 不能置空（多处按 user_id 过滤/统计,含空间数上限统计 `exclude_department_spaces=True` 已豁免部门空间） | 乱动 user_id 会伤个人空间列表逻辑 | 保留 user_id=创建超管,仅不物化前台关系 |
| 4 | 用户管理页的停用/删除今天**没有**部门空间钩子（只有 SSO/部门流程有） | 管理员被停用后空间不进待配置,AC-08 漏 | 决策 5 的新钩子必须覆盖 `user` 模块入口 |
| 5 | 存量归一是运维脚本不是 Alembic revision;多 ADMIN 归一涉及「提升前角色回退」数据（`department_admin_promoted_from_role`） | 写进 revision 违反迁移铁律;直接删行会误伤被提升前就是成员的用户 | 脚本按 `membership_source` 与回退字段分支处理（同 `_sync_removed_admin` 现逻辑） |
| 6 | 在途审批任务在空间进待配置时的处置**产品口径未定**（spec 边界-3） | 实现自作主张 | ★ 实现前向用户要口径;默认候选=挂起待新管理员接手 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的

| 契约 | 形式 | 谁在用 |
|---|---|---|
| batch-create 请求体新增必填 `admin_user_id` | HTTP API（**破坏性**：旧请求体将被 422/业务码拒绝） | platform 管理弹窗（同 PR 内适配） |
| 更换管理员 API（新） | HTTP API | platform |
| `handle_admin_invalidated(user_id)` | 内部 Python API | user 模块、SSO 同步 |
| 空间管理员 = ADMIN 成员行 | 隐式数据契约 | 审批解析、成员展示（不变量:待配置 ⟺ 无 space_admin 来源的 ADMIN 行） |

### 6.2 我依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F033 部门空间授权范围收敛（authorize 写口的部门子树校验） | 内部链路 | 待配置锁加在同一写口,勿互相绕过 |
| 审批中心按 CREATOR/ADMIN 成员解析审批人 | 隐式契约 | 若 F025 改解析口径,待配置锁的语义要联动 |
| 用户停用/删除入口位置（`user/domain/services/user.py`） | 内部调用点 | 入口不止一处时漏挂钩子（含 v2 开放接口） |

---

## 7. 测试与可观测

- 单测：`test/knowledge/`（管理员配置/更换原子性/失效标记/存量归一脚本 dry-run）；审批锁用 `test/approval/` 场景样例。
- e2e 手动主线：超管建部门空间（不选负责人被拒 → 选人成功）→ 负责人前台可见且可管 → 超管不出现在成员/权限/人数 → 停用负责人 → 空间待配置 + 通知 + 授权被锁 → 补配恢复 → 更换负责人原子生效。
- 观测：管理员变更/失效/归一全部走审计日志；FGA 对账差异打 warning 日志。

## 8. 后续改进 / 不打算做的事

- 不做多管理员、不做管理员转交审批流（产品口径单人负责制）。
- 用户生命周期事件总线化后,决策 5 的散点钩子应收敛为订阅。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-13 | 初版 | spec 确认后设计 |
| 2026-08-13 | §3 决策 3 补实现偏差（promoted_from_role 复用）；§4.2 换为落地契约（f049 迁移、18003-18006、通知码、对账任务）；决策 5 的三个入口落地为 user.py 停用、SSO/网关 disable、租户调岗（except_tenant_id） | 实现完成同步 |
