# Tasks: 部门知识空间成员授权范围收敛

**关联规格**: [spec.md](./spec.md) · 设计真相: [design.md](./design.md)

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-10 评审通过，需求全覆盖、EARS 规范、已清 How 泄漏 |
| design.md | ✅ 已评审 | 2026-06-10 评审通过，无 high/medium 遗留；super_admin 不豁免已定稿。接手第一入口 |
| tasks.md | ✅ 已拆解 | 2026-06-10 评审通过（2 轮）：Test-First 配对、AC 逐条追溯、前端 Client 分区 |
| 实现 | 🔄 进行中 | 13 / 14 完成（后端 ✅ e2e 10、前端 ✅ tsc 0、脚本 ✅ AC-06 真库验证）。剩余：T-14 完整验证（仅 AC-01 UI 手动清单待人工走查） |

## 任务拆解

> 全部测试落 `test/permission/`（`asyncio_mode=auto`，无需 `@pytest.mark.asyncio`）。后端单文件 = `src/backend/bisheng/permission/api/endpoints/resource_permission.py`；文件锚点见 design.md §4.3（后端）/ §4.4（前端 Client）/ §4.5（脚本）。本 feature 无新增 ORM / 错误码 / 配置（复用 `PermissionDeniedError`），故无独立基础设施任务。

### Wave 1 — 后端范围判定（Test-First）

- [x] **T-01**〔后端测试〕`test/permission/test_department_space_scope.py`：`_resolve_department_space_scope('knowledge_space', id)` 部门空间命中、普通空间返回 `None`、非 knowledge_space 返回 `None`、绑定部门归档 → 子树为空。覆盖 AC: AC-02, AC-03, AC-04 ✅ 4 passed
- [x] **T-02**〔后端实现〕在 `resource_permission.py` 实现 `_resolve_department_space_scope`（design B1）：`DepartmentKnowledgeSpaceDao.aget_by_space_id` → `DepartmentDao.aget_by_id` → 复用 `DepartmentDao.aget_subtree_ids`（已含 `status='active'` + path 前缀）得 `subtree_dept_ids`。返回 `frozenset` 的 `_DepartmentSpaceScope`。依赖 T-01。✅

### Wave 2 — 后端列表收敛

> 测试策略调整（见偏差记录）：T-03/05/07 的 SQLite seed 单测改为统一的真库 e2e（`test/e2e/test_e2e_department_space_scope.py`），因本地有可用中间件，e2e 是 ReBAC/多租户行为的正确测试层级。

- [x] **T-03→e2e**〔后端测试〕部门空间 `grant-subjects/departments` 仅绑定部门+子部门；普通空间全租户（回归）。覆盖 AC: AC-02, AC-05 ✅ e2e `test_ac02_*` + `test_ac05_normal_space_departments_tenant_wide`
- [x] **T-04**〔后端实现〕`_list_knowledge_space_grant_departments` 增 `restrict_dept_ids`（`Department.id.in_(...)`）+ `get_grant_subject_departments` 端点透传（design B2/B4）。✅
- [x] **T-05→e2e**〔后端测试〕部门空间 `grant-subjects/users` 仅子树成员、严格子集；普通空间回归。覆盖 AC: AC-03, AC-05 ✅ e2e `test_ac03_*`
- [x] **T-06**〔后端实现〕`_list_knowledge_space_grant_users` 增 `restrict_dept_ids`（`join UserDepartment` + `distinct`，先过滤后分页）+ 端点透传（design B3/B4）。✅
- [x] **T-07→e2e**〔后端测试〕部门空间 `grant-subjects/user-groups` 返回空数组；普通空间回归。覆盖 AC: AC-01(数据面), AC-05 ✅ e2e `test_ac04_user_groups_disabled_*` + `test_ac05_normal_space_lists_user_groups`
- [x] **T-08**〔后端实现〕`get_grant_subject_user_groups` 部门空间短路 `resp_200([])`（design B5）。✅

### Wave 3 — 后端授权准入

- [x] **T-09→e2e**〔后端测试〕部门空间 grant user_group → 拒、子树外 user/department → 拒、子树内 → 通过、revoke 放行；**super_admin 跑拒绝用例同样被拒**；普通空间三维度全通过（回归）。覆盖 AC: AC-04, AC-05 ✅ e2e `test_ac04_*` + `test_ac05_*`（admin = super_admin）
- [x] **T-10**〔后端实现〕`authorize_resource` 加 B6 准入：`_validate_department_space_grants` + `_subtree_user_ids`，scope 命中时对 `grants` 逐条校验（user_group / 子树外 → `PermissionDeniedError`，revoke 不拦），**置于 `if not login_user.is_admin()` 豁免分支之外**（design B6）。✅

### Wave 4 — 前端 Client 隐藏用户组维度

- [x] **T-11**〔前端 Client〕`KnowledgeSpaceShareDialog.tsx` 加 `isDepartmentSpace?: boolean` prop，`SUBJECT_TABS` 改 `useMemo`，命中时剔除 `user_group`（列表 + 授权弹窗同源，超管同样两 tab）（design F1）。✅ tsc 0 error
- [x] **T-12**〔前端 Client〕两个 call site（`SpaceDetail/index.tsx` 门控 `permTarget.type==='knowledge_space' && space.spaceKind==='department'`、`knowledge/index.tsx` 门控 `spacePermissionDialogSpace.spaceKind==='department'`）传 `isDepartmentSpace`（design F2/F3）。**无新增 i18n**：仅隐藏 tab，后端 PermissionDenied 文案走既有 toast。依赖 T-11。✅ 覆盖 AC: AC-01

### Wave 5 — 历史数据清理

- [x] **T-13**〔脚本〕`src/backend/scripts/clean_department_space_user_group_grants.py`（design §4.5；一次性清理归 `scripts/` 非 `migration/`）：`--dry-run`（默认）输出 `(space_id, group_id, relation, 波及用户数)`，`--apply` 经 `PermissionService.authorize` revoke 删除部门空间 user_group tuple + binding。入口 `initialize_app_context`（DB+OpenFGA）+ `bypass_tenant_filter`。覆盖 AC: AC-06 ✅ 真库验证：dry-run 扫 31 空间/0 grant；seed-and-apply spot check 通过

### Wave 6 — 验证

- [ ] **T-14**〔验证〕`/e2e-test` + 手动验证一遍（design §7）：部门空间两 tab/子树范围、普通空间三 tab 不变、超管拒绝用例、脚本 dry-run→apply。覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06

## 实际偏差记录

> 实现中若偏离 design，在此记录并回写 design.md（改了系统认知的偏差必须回写）。

- **2026-06-10 / T-02**：`_DepartmentSpaceScope` 只保留 `department_id` + `subtree_dept_ids`，**去掉 design B1 写的 `path` 字段**——B2/B3/B6 实际只用 `subtree_dept_ids`，`path` 在 `aget_subtree_ids` 内部消化，对外无用。复用既有 `DepartmentDao.aget_subtree_ids`（已含 `status='active'` 过滤）而非自写 `path.like`，少一处 SQL 重复。design §4.3 B1 已同步。
- **2026-06-10 / 测试策略**：Wave 2-3 的后端测试由「每任务 SQLite seed 单测（T-03/05/07/09）」改为**统一真库 e2e**（`test/e2e/test_e2e_department_space_scope.py`，10 用例）。原因：本地中间件 + config.yaml 可用，e2e 是 ReBAC/多租户/部门子树行为的正确测试层级，避免给 `test/fixtures/table_definitions.py` 补一堆部门相关表。Wave 1 的纯逻辑 resolver 仍保留 SQLite 单测。
- **2026-06-10 / e2e 取舍**：① 普通空间对照**复用**管理员已有的普通空间（创建配额已满，且 grant-then-revoke 不留痕）；② AC-03 成员包含用「管理员（user 1，确定的租户活跃成员）+ 严格子集」断言——新建用户经 `/user/create` 默认未必是 `UserTenant` 活跃成员，不能用作 list 包含断言（但其 `UserDepartment` 成立，故 AC-04 校验用之有效）。这是**测试环境特性**，非产品缺陷。
- **2026-06-10 / T-13 脚本位置**：清理脚本从 design 原稿的 `permission/migration/` 改放 `src/backend/scripts/`——一次性数据清理归 `scripts/`，`migration/` 只放 schema 迁移（用户确认 + `src/backend/CLAUDE.md`「Migration vs. script」已成文规约）。脚本入口须 `initialize_app_context`（DB+OpenFGA）否则 `--apply` 的 FGA 写报 `FGAClient not available`（scripts/CLAUDE.md §6 已把本脚本列为正确参考）。design §4.5 已同步。
