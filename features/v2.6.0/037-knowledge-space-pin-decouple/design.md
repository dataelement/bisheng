# Design: 知识空间置顶与成员关系解耦

**关联**: [spec.md](./spec.md)
**版本**: v2.6.0
**最后更新**: 2026-06-24

---

## 1. 目标与非目标

- **目标**：把知识空间"置顶"从成员表里搬出来，做成独立的"用户置顶"记录；修复"返回成功但未置顶"，并补上 set-pin 缺失的权限校验。
- **非目标**：不动频道置顶；不动 ReBAC/部门授权访问控制；不改 `set-pin` 对外契约。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7（分层 / 双 DB / 多租户 / 权限 / 错误码）。
- **特有约束**：
  - 新表 + 迁移须 MySQL / 达梦双兼容；建表迁移幂等（参考 `v2_5_1_f021`）。
  - 置顶是高频读（每次列表都要知道哪些被置顶）→ `(user_id, space_id)` 需可快速查。

---

## 3. 方案对比与选定

### 决策 1：置顶状态存哪里

- **备选**：
  - A. **独立置顶表** `knowledge_space_user_pin(user_id, space_id)` — 置顶=个人偏好，完全脱离 membership；缺点是新增表 + 改多处读路径 + 老数据回填。
  - B. 继续存成员行 `is_pinned`，无成员行时补插一行 — 改动小；但补插的行会污染成员计数 / 成员管理 / 订阅审批（`async_get_members_by_space` 等 7+ 处），且普通部门成员换部门**无回收钩子** → 孤儿行。
  - C. 无成员行时 set-pin 直接报错"此空间不可置顶" — 最小改动；但产品上授权/部门空间不能置顶，体验受限。
- **选定**：A
- **原因**：置顶语义上就是个人偏好，不该寄生在成员关系上。B 需要在 7+ 处查询里按 `membership_source` 排除并加懒删除，漏一个就泄漏，脆弱；C 牺牲功能。A 一次性把语义切干净。
- **何时该重新考虑**：若未来置顶要带"团队级置顶/全员置顶"语义（不再是纯个人偏好），需重新评估归属。

### 决策 2：换部门 / 失去访问后，遗留置顶记录怎么清理

- **备选**：
  - A. **不主动清理，靠读取端权限重校验使其惰性失效**（可选 lazy-delete）。
  - B. 在部门变更 / ReBAC 撤销时级联删除置顶记录。
- **选定**：A
- **原因**：所有空间列表读取本就会用 `view_space` 重新校验权限（失去访问的空间根本不进列表）。置顶表**不参与**成员计数、成员管理、审批，遗留记录纯属该用户自己看不到的死数据，**无害**，正确性不依赖清理。B 要给"部门变更 / 用户组变更 / 直接授权撤销"等所有撤权路径都挂钩子，成本高且易漏 —— 而决策 1 选 A 的全部价值就是不必再碰这些。
- **何时该重新考虑**：若置顶表体量异常增长（死记录占比过高）成为存储/查询负担，再加 lazy-delete（读到无权限空间时顺手删该用户该行）或定期清理脚本。

### 决策 3：set-pin 权限校验

- **选定**：service 层 `pin_space` 先调用 `_require_read_permission(space_id)`（校验 `view_space`，顺带拿到 space、统一抛 `SpaceNotFoundError` / `SpacePermissionDeniedError`），再写置顶表。
- **原因**：现接口**完全无权限校验**，仅靠"得有成员行才生效"隐式兜底；解耦后必须显式 gate，否则任何登录用户都能给任意空间写置顶记录。

### 决策 4：旧 `is_pinned` 列与老数据

- **选定**：用一次性脚本（`scripts/`，非 alembic，遵循 backend AGENTS.md "数据迁移走脚本"）把 `space_channel_member.is_pinned=true & business_type='space'` 回填进新表；之后**停止读写**该列，列暂时保留（不在本次做破坏性 drop）。
- **原因**：保住老用户已有置顶；drop 列是独立的破坏性变更，留待后续。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（改造后）

**置顶写**：
`POST /{space_id}/set-pin` → `knowledge_space.py:set_channel_pin` → `KnowledgeSpaceService.pin_space` → `_require_read_permission` 校验 → `KnowledgeSpaceUserPinDao.pin/unpin`

**置顶读（列表）**：
`KnowledgeSpaceService._format_accessible_spaces` / `_format_member_spaces` 一次性 `KnowledgeSpaceUserPinDao.list_pinned_space_ids(user_id)` → 用 `space.id in pinned_ids` 决定 `is_pinned` 与置顶分组。

### 4.2 关键数据结构 / 字段约定

新表 `knowledge_space_user_pin`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK auto | 主键 |
| `user_id` | INT, index | 置顶人 |
| `space_id` | INT | 被置顶知识空间 id |
| `create_time` | DATETIME, server default | 置顶时间 |
| uniq `(user_id, space_id)` | — | 幂等去重 |

对外 HTTP 契约**不变**：`set-pin` 请求体 `{"is_pined": bool}`，响应 `resp_200(data=True)`。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `knowledge_space.py:set_channel_pin` | endpoint，透传 | 不做业务 |
| `KnowledgeSpaceService.pin_space` | 权限校验 + 编排置顶读写 | 不直接写 ORM |
| `KnowledgeSpaceUserPinDao`（新） | 置顶表 CRUD：pin / unpin / list_pinned_space_ids | 不碰成员表 |
| `_format_accessible_spaces` / `_format_member_spaces` | 列表装配，按 pinned_ids 分组 | 不再读 `member.is_pinned` |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 普通部门成员（viewer）**没有** `space_channel_member` 行，访问纯靠 ReBAC `department→viewer` 继承；只有部门管理员才有成员行且有回收钩子（`_sync_removed_admin`） | 误以为"补插成员行"可行 → 给普通部门成员造孤儿行 | 用独立置顶表，根本不碰成员表 |
| 2 | `async_count_space_members` / `async_get_members_by_space` 只按 `status=ACTIVE` 裸查，不区分来源 | 任何插进成员表的"伪成员"都会污染成员数 / 成员管理 / 审批 | 置顶不进成员表 |
| 3 | 旧 `pin_space_id` 无条件 `return True`，UPDATE 命中 0 行也报成功 | "成功但没置顶"假象 | 改为写独立表 + 权限前置校验 |
| 4 | set-pin 原本**零权限校验** | 解耦后任何人可给任意空间写置顶 | `pin_space` 前置 `_require_read_permission` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v1/knowledge/space/{id}/set-pin` | HTTP（行为修复，签名不变） | platform 前端 |

### 6.2 我依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `_require_read_permission` 的 `view_space` 判定 | 内部 API | 权限语义若变，置顶可写范围随之变 |
| 列表装配处统一按 `view_space` 过滤 | 隐式约定 | 若某列表不重校验权限，遗留置顶可能泄漏可见性（决策 2 的前提） |

---

## 7. 测试与可观测

- **单测/集成**（pytest，`test/knowledge/`）：覆盖 AC1–AC7。重点：AC2（授权用户置顶不产生成员行 + 成员数不变）、AC4（无权限拒绝不写库）、AC5（失访惰性失效）、AC6（迁移回填）、AC7（幂等）。
- **手动**：用一个仅部门授权访问的账号，对 space 3733 调用 set-pin → 列表确认置顶生效且 `space_channel_member` 无新增行。

---

## 8. 后续改进

- 旧 `is_pinned` 列的破坏性 drop（独立迁移，确认无残留读写后再做）。
- 死记录过多时再引入 lazy-delete / 定期清理（决策 2）。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-24 | 初版 | 置顶不生效排障 → 解耦设计 |
