# Design: 部门知识空间成员授权范围收敛（仅本部门子树 + 禁用用户组）

- 版本：v2.6.0 · Feature F033
- 状态：📝 待评审（草稿，供 review）
- 负责人：GuoQing Zhang
- 关联：[release-contract](../release-contract.md) · 关联既有 F006/F007（ReBAC 资源授权）、部门知识空间能力

## 1. 目标与非目标

**目标**：在「**部门知识空间**」的成员管理 → 新增用户授权弹窗里，把可授权对象范围收敛为：
1. **部门维度**：只能看到「该空间绑定的部门 + 其所有子部门」，不再展示全租户部门树。
2. **用户维度**：只能看到「上述部门子树内的成员」。
3. **删除用户组维度**：部门知识空间不再支持按「用户组」授权（隐藏 tab + 后端拒绝）。

**关键原则**：以上收敛**只对部门知识空间生效**，**普通知识空间**的成员管理（user / department / user_group 三维度、全租户范围）逻辑**完全不变**。

**非目标（防误扩范围）**：
- 不改普通知识空间的授权弹窗、不改 platform 端 `PermissionDialog`（其只服务 `knowledge_library`，不涉及 `knowledge_space`）。
- 不改部门知识空间创建时「默认授予绑定部门 `viewer`」的既有逻辑（`_grant_department_members_viewer`，`include_children=False`）。
- 不改成员列表展示（`get_space_members` / 角色升降 / 移除）。
- 不做用户组授权的"业务兼容"——历史遗留的部门空间 user_group 授权由**一次性脚本清理**（见 §3 决策 4），运行期代码不再为其保留路径。
- 不动其它资源类型（workflow / assistant / tool / channel / dashboard / knowledge_library）的授权范围。

## 2. 关键约束 + Constitution Check

**本功能特有约束**：
- 「是否部门空间」必须由**后端**依据 `DepartmentKnowledgeSpace` 绑定判定，**不能信任前端传入的标记**——否则可被绕过越权授权（前端 flag 仅用于 UI 隐藏 tab）。
- **范围约束与操作者身份无关**：部门知识空间只能授权给"绑定部门及其子部门"或"这些部门下的成员"，**super_admin / 租户管理员同样受限**，不因身份豁免（既有 `authorize_resource` 对超管跳过管理权校验，本约束须放在该豁免分支之外）。
- 范围收敛必须**后端 + 前端双层**落地（用户已确认）：前端隐藏 user_group tab 且部门/人员列表自动收敛；后端 `grant-subjects/*` 列表接口按部门子树过滤，`authorize` 接口拒绝越界/用户组授权。
- 部门子树判定复用既有 `Department.path` 前缀匹配（`path.like(f'{bound.path}%')`），与 `_list_knowledge_space_grant_departments` 既有写法同构。

**Constitution Check（C1–C7，门禁）**：方案不违反任一条。
- **C1 分层**：改动落在 permission `api/endpoints/resource_permission.py`（接口层 + 私有 helper）。B1/B2/B3 对 `DepartmentKnowledgeSpace` / `Department` / `UserDepartment` 的**跨模块只读**，是**沿用本文件既有 helper 的既定惯例**（`_list_knowledge_space_grant_users` 已 import `DepartmentDao`/`UserDepartmentDao`/`User`），非新开越层；不在接口里写跨模块 ORM 写业务，无新增 DAO。
- **C4 权限 / ReBAC**：收敛是在既有 ReBAC 授权链路（`authorize_resource` + `PermissionService.authorize`）**之上加准入校验**，不改 FGA schema、不改 relation 模型。
- **C3 多租户**：复用既有 `_resolve_grant_subject_tenant_id` + `bypass_tenant_filter` 套路，部门子树天然在租户内，不破租户隔离。
- **C5 错误码**：部门空间拒绝用户组/越界授权**复用既有 `PermissionDeniedError`**（带具体 msg），不新增错误码（详 §3 决策 3）。
- **C2 双 DB / C6 密钥 / C7 前端 store**：不新增表、无密钥；前端仅在组件内派生 tab 列表，不在 store 直连 HTTP。

## 3. 方案对比与选定（最高价值章节）

### 决策 1：「部门空间」判定 = 后端按绑定查询，前端 flag 仅作 UI

| 备选 | 评估 | 结论 |
|------|------|------|
| **后端按 `DepartmentKnowledgeSpaceDao.aget_by_space_id` 判定**；前端额外传 `isDepartmentSpace` 仅用于隐藏 tab | 安全：列表收敛 + authorize 准入都在后端，前端 flag 被篡改也无法越权；前端 flag 缺失时后端仍然兜底 | **选定** |
| 仅前端按 `space.spaceKind === 'department'` 控制 | 可被绕过（直接调 `/authorize` 传 user_group 或子树外部门/用户）；用户已否决"仅前端" | 否决 |
| 后端在 `knowledge_space` 资源上加配置字段标识 | 重复真相：绑定关系已是单一真相，再加字段会不一致 | 否决 |

- **原因**：`DepartmentKnowledgeSpace` 绑定是"是否部门空间 + 绑定哪个部门"的唯一真相；后端判定零额外状态、不可绕过。
- **何时该推翻**：若未来一个空间可绑定多个部门 → 子树范围改为「多绑定部门 path 的并集」，判定函数返回 list 即可，准入逻辑不变。

### 决策 2：收敛点 = 收口到一个 `_resolve_department_space_scope` helper

- **选定**：新增私有 helper `_resolve_department_space_scope(resource_type, resource_id) -> DeptScope | None`，仅当 `resource_type == 'knowledge_space'` 且存在绑定时返回 `{department_id, path, subtree_dept_ids}`，否则 `None`。`grant-subjects/users`、`grant-subjects/departments`、`grant-subjects/user-groups`、`authorize_resource` 四处统一调用它。
- **备选（否决）**：四处各自查绑定 → 判定逻辑四份、易漂移。
- **原因**：单一判定来源；`None` 分支即"普通空间/非空间资源"——**天然保证普通知识空间走原路径**，把"不影响普通空间"做成结构性保证而非散落 if。

### 决策 3：部门空间的非法授权 = 复用 `PermissionDeniedError`，不新增错误码

- **选定**：`authorize_resource` 对部门空间的 `grant` 校验：①`subject_type == 'user_group'` → `PermissionDeniedError.return_resp('部门知识空间不支持按用户组授权')`；②`user`/`department` 的 subject 不在绑定部门子树内 → `PermissionDeniedError.return_resp('只能授权给本部门及子部门的成员')`。
- **备选（否决）**：新增 109/180 段错误码——前端无差异化分支需求（正常流程下越界请求不会发生，仅作越权兜底），无需独立码。
- **原因**：遵循 release-contract「不新增错误码」最省心；与既有 `_is_invalid_owner_subject` 的拒绝模式一致（同样复用 `PermissionDeniedError`）。
- **何时推翻**：若前端需对"用户组被禁"与"越界"做不同文案 → 再拆 180 段两个码。

### 决策 4：历史用户组授权 = 一次性清理脚本，运行期不兼容

- **选定**：上线随附一次性脚本，扫描所有 `DepartmentKnowledgeSpace` 绑定的 `space_id`，删除其上 `subject_type='user_group'` 的 ReBAC tuple（FGA）+ relation-model binding（DB）。运行期 `authorize` 仅拒绝**新增** user_group，不为历史保留读取/展示路径。
- **备选（否决）**：运行期列表里仍渲染历史用户组 + 允许撤销——用户明确选择"脚本清理即可，业务逻辑无需兼容"。
- **原因**：部门空间用户组授权属异常/历史态，集中清理比长期背兼容分支更干净。
- **何时该重新考虑**：N/A——一次性迁移，无递归锚点；若清理后仍有新部门空间残留 user_group 授权，说明 B6 准入未覆盖某入口，应回查 authorize 而非重跑脚本。
- **风险点**：清理会立即收回这些用户组成员的访问；脚本须先 dry-run 输出受影响 space/group/用户量供确认（见 §7）。

### 决策 5：前端范围收敛 = 复用后端已收敛的列表，不在前端做子树过滤

- **选定**：前端不感知部门子树；`SubjectSearchUser` / `SubjectSearchDepartment` 仍调既有 `grant-subjects/users|departments`，因后端已按空间收敛，列表天然只剩子树内数据。前端唯一改动是**按 `isDepartmentSpace` 去掉 `user_group` tab**。
- **备选（否决）**：前端拿到 `departmentId` 后自行裁剪部门树/过滤用户——与后端两份范围逻辑、易不一致。
- **原因**：范围单一真相在后端；前端零重复逻辑，改动面最小。

## 4. 系统现状

### 4.1 复用的既有模式

- 授权入口（客户端）：`client/src/pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog.tsx` —— `SUBJECT_TABS`（user/department/user_group）+ 授权弹窗 `PermissionGrantTab`。**部门空间成员授权的唯一 UI**。
- `client/src/api/knowledge.ts` —— `KnowledgeSpace.spaceKind`（`'normal'|'department'`）/ `departmentId` 已由 `space_kind`/`department_id` 映射好，调用方现成可用。
- 后端授权与列表：`permission/api/endpoints/resource_permission.py`
  - `POST /resources/{type}/{id}/authorize` —— 授权写入 + 既有越权校验（`_is_invalid_owner_subject`、`_can_grant_relation_model`）。
  - `GET .../grant-subjects/users|departments|user-groups` —— 三个候选列表，经 `_resolve_grant_subject_tenant_id` 解析租户后全租户返回。
  - `_list_knowledge_space_grant_departments` 已用 `Department.path.like(...)` 做子树过滤（按租户 root_dept），**复用其 path 前缀写法**。
- 绑定真相：`knowledge/domain/models/department_knowledge_space.py` —— `DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)` 返回绑定（含 `department_id`）。
- 部门数据：`database/models/department.py` —— `Department.path`（子树前缀）、`UserDepartment`（用户-部门，含 `is_primary`）。

### 4.2 数据流（输入 → 输出主线）

```text
[部门空间成员管理 → 新增用户授权]

前端 ShareDialog:
  isDepartmentSpace = space.spaceKind === 'department'   ← 调用方传入
    → SUBJECT_TABS 过滤掉 user_group（仅 user/department）
    → PermissionGrantTab 调 grant-subjects/users|departments

后端 grant-subjects/*:
  scope = _resolve_department_space_scope('knowledge_space', space_id)
    scope is None  → 普通空间/非空间 → 原全租户列表（逻辑不变）
    scope 命中     → users  : 仅 subtree_dept_ids 内成员
                    departments: 仅绑定部门 path 子树
                    user-groups: 返回 []

后端 authorize:
  scope = _resolve_department_space_scope(...)
    scope is None → 原逻辑
    scope 命中 → 对每个 grant:
        user_group            → PermissionDeniedError
        user 不在子树成员      → PermissionDeniedError
        department 不在子树    → PermissionDeniedError
        （revoke 不限制，便于清理/移除）
    通过 → 走既有 PermissionService.authorize
```

### 4.3 后端改动（permission/api/endpoints/resource_permission.py）

| # | 位置 | 做什么 / 不做什么 |
|---|------|------|
| B1 | 新增 `_resolve_department_space_scope(resource_type, resource_id)` | 仅 `resource_type=='knowledge_space'` 时查 `DepartmentKnowledgeSpaceDao.aget_by_space_id`；命中则 `DepartmentDao.aget_by_id` 取绑定部门，复用 `DepartmentDao.aget_subtree_ids(path)`（已含 `status='active'` + path 前缀）得 `subtree_dept_ids`，返回 frozen dataclass `_DepartmentSpaceScope{department_id, subtree_dept_ids: frozenset}`；否则 `None`。**单一判定来源**。〔实现修订：去掉原稿的 `path` 字段，对外只用 `subtree_dept_ids`；见 tasks.md 偏差记录〕 |
| B2 | `_list_knowledge_space_grant_departments` | 增 `restrict_dept_ids: set|None` 入参；非空时在既有 `stmt` 上追加 `Department.id.in_(restrict_dept_ids)`（仍复用既有建树/计数/排序，仅缩小集合）。 |
| B3 | `_list_knowledge_space_grant_users` | 增 `restrict_dept_ids: set|None` 入参；非空时 `join UserDepartment` 并 `where UserDepartment.department_id.in_(restrict_dept_ids)`（多部门用户命中任一即可，`distinct`）。keyword/分页逻辑不变。 |
| B4 | `get_grant_subject_users` / `get_grant_subject_departments` 端点 | 调 B1 得 scope；把 `scope.subtree_dept_ids`（或 None）透传给 B3/B2。 |
| B5 | `get_grant_subject_user_groups` 端点 | 调 B1；scope 命中 → 直接 `resp_200([])`（不查库）；否则原逻辑。 |
| B6 | `authorize_resource` | 调 B1；scope 命中时，对 `request.grants` 逐条准入：`user_group` 拒、子树外 `user`/`department` 拒（复用 B1 的 `subtree_dept_ids`；user 命中需该 user 在子树成员集，可复用 B3 的成员查询抽出的 `_subtree_user_ids(scope)`）；**revokes 不校验**。校验对**所有身份生效（含 super_admin / 租户管理员）**，故必须放在既有 `if not login_user.is_admin()` 管理权豁免分支**之外**——紧跟 `_is_invalid_owner_subject` 块之后、写入之前。 |

> 说明：B2/B3 的 `restrict_dept_ids=None` 即现状路径——**普通知识空间与其它资源零行为变化**，这是"不影响普通空间"的代码级保证。

### 4.4 前端改动（client，仅授权 UI 隐藏用户组 tab）

| # | 文件 | 做什么 |
|---|------|------|
| F1 | `pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog.tsx` | 新增可选 prop `isDepartmentSpace?: boolean`；`SUBJECT_TABS` 改为 `useMemo`：`isDepartmentSpace` 时剔除 `user_group` 项。因授权弹窗的并列 tab 与**现有授权列表** `PermissionListTab` 共用同一 `SUBJECT_TABS`，剔除后**列表视图也不再显示用户组 tab**（恰好符合决策 4：历史用户组授权不在 UI 展示）；`currentSubjectType/grantSubjectType` 初始与重置保持 `'user'`，无 user_group 可达。flag 与操作者身份无关，故 **super_admin 在部门空间同样只有 user/department 两 tab**。 |
| F2 | `pages/knowledge/SpaceDetail/index.tsx`（call site） | `<KnowledgeSpaceShareDialog ... isDepartmentSpace={space.spaceKind === 'department'} />`（`space` 现成）。 |
| F3 | `pages/knowledge/index.tsx`（call site） | 同 F2，用 `spacePermissionDialogSpace?.spaceKind === 'department'`。 |
| F4 | i18n | 如需"部门空间不支持用户组授权"提示文案，加 `com_permission.*` key（en/zh-Hans/ja）。后端 `PermissionDeniedError` 文案已可兜底，前端 toast 走既有 `captureAndAlertRequestErrorHoc`。 |

> 部门树/人员列表**无需前端改动**：后端已收敛，`SubjectSearchDepartment`/`SubjectSearchUser` 拿到的就是子树数据。

### 4.5 一次性清理脚本

- 位置：`src/backend/scripts/clean_department_space_user_group_grants.py`（一次性数据清理归 `scripts/`，非 Alembic/`migration/`——见 `src/backend/CLAUDE.md`「Migration vs. script」）。
- 逻辑：`DepartmentKnowledgeSpaceDao.aget_all()` → 所有部门空间 `space_id` → `PermissionService.get_resource_permissions` 找 `subject_type='user_group'` 的授权 → `--apply` 时经 `PermissionService.authorize` 的 revoke（`enforce_fga_success`）删 ReBAC tuple + `_save_bindings` 去 relation-model binding。
- 运行环境：脚本入口先 `initialize_app_context(config=settings)`（DB + OpenFGA），否则 revoke 的 FGA 写会 `FGAClient not available`（见 `scripts/CLAUDE.md §6`）；DB 读写在 `bypass_tenant_filter()` 下跨租户。
- 安全：`--dry-run` 默认，打印 `(space_id, group_id, relation, 受影响用户数)`；`--apply` 才执行；不可逆。

## 5. 已知坑 / 反直觉事实

1. **判定必须在后端、不能信前端 flag** —— 前端 `isDepartmentSpace` 只控制 tab 显隐；列表收敛与 authorize 准入都必须独立用 B1 判定，否则直接调 API 可越权（绕过隐藏的 tab）。这是双层落地的根因。
2. **revoke 不能被收敛拦截** —— 准入校验只作用于 `grants`。若把 revoke 也拦了，历史用户组授权将无法在 UI/脚本里撤销，与决策 4 冲突。
3. **默认 viewer 授权的 `include_children=False` 与新可选范围不一致是预期的** —— 建空间时只给"绑定部门本级"viewer（`_grant_department_members_viewer`），但新需求允许管理员**额外**勾选子部门/子树成员授更高档位。两者不矛盾：默认是底座，手动授权是叠加。不要在本期去改默认授权的 include_children。
4. **多部门用户** —— 用户只要**任一** `UserDepartment` 落在子树即可见/可授（B3 用 `in_ + distinct`）。不要误用 `is_primary` 过滤（那只用于显示主部门路径）。
5. **`grant-subjects/users` 的子树过滤要在 SQL 层 join，不能拉全量再内存筛** —— 大租户全量用户分页会错位（先分页后过滤会漏）。必须 `join UserDepartment ... where department_id in (...)` 后再 `offset/limit`。
6. **空间被解绑/部门归档** —— B1 命中绑定但绑定部门 `status!='active'` 时，`subtree_dept_ids` 可能为空 → 列表返回空、authorize 拒绝非空 grant。属合理降级（无可授对象），不报错。
7. **platform 端不涉及** —— platform 的 `PermissionDialog` 只用于 `knowledge_library`，不会传 `knowledge_space`；本期不碰它，避免误改普通库授权。
8. **super_admin 不豁免范围约束（反直觉）** —— 一般 `authorize_resource` 对 `is_admin()` 跳过管理权校验，惯性会以为超管可任意授权。但部门空间范围收敛与身份无关：超管同样只能授本部门子树/子树成员、同样禁用用户组。不知道 → 会把 B6 校验误放进 `if not login_user.is_admin()` 分支内，导致超管直连 API 可越界。处理：B6 校验置于该豁免分支之外（§4.3 B6 / §2 约束）。

## 6. 对外契约与依赖

**Outgoing（我提供给别人）**：
- `grant-subjects/users|departments` 对**部门空间**返回收敛后的子集；`grant-subjects/user-groups` 对部门空间返回 `[]`。**风险点**：调用方若假设这些接口总是全租户，需知悉部门空间例外（普通空间不变）。
- `authorize` 对部门空间拒绝 user_group / 子树外 subject（`PermissionDeniedError`）。**风险点**：自动化脚本批量授权部门空间需遵守范围。
- 前端 `KnowledgeSpaceShareDialog` 新增可选 prop `isDepartmentSpace`（默认 `false` → 行为完全不变，向后兼容其它调用方）。

**Incoming（我依赖别人）**：
- `DepartmentKnowledgeSpaceDao.aget_by_space_id` / `aget_all`（F-部门空间 owner）：绑定真相来源。**风险点**：若改为一空间多部门绑定，B1 需同步返回并集。
- `Department.path` 子树语义、`UserDepartment` 表结构（F002 department-tree owner）：子树与成员判定的数据契约。
- 既有 `_resolve_grant_subject_tenant_id` / `bypass_tenant_filter` / `PermissionService.authorize`：不改其行为，仅在其前后加 scope 收敛。
- `KnowledgeSpace.spaceKind`（client api）：前端 flag 来源。

**release-contract 登记**：表 1 标注"无新增领域对象"（仅在既有 ReBAC 授权/列表链路对 `knowledge_space` 资源加部门子树收敛分支）；不新增表/对外 API/错误码（复用 `PermissionDeniedError`）；不新增不变量。

## 7. 测试与可观测

- **后端单元**（`test/permission/`）：
  - `_resolve_department_space_scope`：部门空间命中（返回子树 id 集）、普通空间返回 None、非 knowledge_space 返回 None、绑定部门归档 → 子树空。
  - `grant-subjects/departments`：部门空间仅返回绑定部门+子部门；普通空间返回全租户（回归不变）。
  - `grant-subjects/users`：部门空间仅子树成员，多部门用户任一命中，keyword+分页正确（join 后分页）；普通空间不变。
  - `grant-subjects/user-groups`：部门空间空数组；普通空间不变。
  - `authorize`：部门空间 grant user_group → 拒；grant 子树外 user/department → 拒；grant 子树内 → 通过；revoke user_group → 放行。**以 super_admin 身份重跑上述拒绝用例 → 同样被拒**（验证范围约束不被 `is_admin()` 豁免）。普通空间三维度全通过（回归）。
- **前端**：`KnowledgeSpaceShareDialog` 在 `isDepartmentSpace` 下不渲染 user_group tab；普通空间三 tab 不变（沿用既有 `PermissionGrantTab.test`/`PermissionListTab.test` 风格）。
- **手动验证一遍**：① 部门空间打开成员管理 → 新增授权：只有「用户/部门」两 tab；部门 tab 只列绑定部门及子部门；用户 tab 只列子树成员 → 授权成功。② 普通知识空间同入口：三 tab、全租户范围、可按用户组授权——**确认无变化**。③ 清理脚本 `--dry-run` 输出受影响项，`--apply` 后部门空间不再有用户组授权。

## 8. 后续改进

- **一空间多部门绑定**：当前按单绑定设计，B1 已预留并集化扩展点（§3 决策 1 推翻路径）。
- **差异化错误文案**：如产品要区分"用户组被禁"与"越界授权" → 再拆 180 段错误码（§3 决策 3）。
- **默认授权含子部门开关**：若后续希望建空间即给整棵子树 viewer，再评估改 `_grant_department_members_viewer` 的 `include_children`，本期不做。

## 修订历史

| 日期 | 变更 |
|------|------|
| 2026-06-10 | 初版草稿：部门知识空间成员授权收敛为「绑定部门子树 + 子树成员」、禁用用户组；后端 `_resolve_department_space_scope` 单一判定 + 四处收口，前端隐藏 user_group tab，历史授权一次性脚本清理；复用 `PermissionDeniedError`，不新增错误码/表/领域对象。 |
| 2026-06-10 | 评审修订：明确范围约束与身份无关、**super_admin 不豁免**（B6 校验置于 `is_admin()` 豁免分支外，§2 约束 + §5 坑 8 + §7 超管用例）；补 C1 跨模块只读惯例说明、决策 4 推翻条件、F1 列表 tab 同步隐藏说明。 |
