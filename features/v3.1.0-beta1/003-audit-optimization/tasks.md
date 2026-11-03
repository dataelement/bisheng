# Tasks: 审计功能优化

**关联规格**: [spec.md](./spec.md) · **设计**: [design.md](./design.md)
**版本**: v3.1.0-beta1 · **分支**: `feat/3.1.0-beta1-003-audit-optimization`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-03 用户确认 |
| design.md | ✅ 已评审 | 2026-11-03 用户确认 |
| tasks.md | ✅ 已拆解 | AC-01 至 AC-42 均已追溯到任务 |
| 实现 | 🔄 进行中 | 14 / 16 完成 |

---

## 开发模式

- 按 Wave 推进，同一 Wave 内无依赖可并行。
- 后端 Test-First：测试放 `src/backend/test/audit/`，沿用该目录现有 SQLite fixture；中间件和 DM8 在 CI 跑。
- 前端用 Vitest 测试已有的 `LogPage/*.test.tsx`，加手动验证步骤。
- 设计论证见 design.md 对应决策，任务内不重复。

---

## Tasks

### Wave 1 — 存储与快照基础

- [x] **T001**: 五张表加组织快照列 + 迁移
  **文件**: `database/models/audit_log.py`、`database/models/session.py`、`open_api/domain/models/model_call_record.py`、`app_publish/domain/models/capability_call_record.py`、`database/models/app_access_log.py`、`core/database/alembic/versions/v3_1_0b1_f003_audit_operator_dept.py`
  **逻辑**: 每张表加 `operator_dept_id`（Integer，可空，索引，无默认值，无外键）和 `operator_dept_path`（String(1024)，可空）。迁移 `down_revision = f114_app_authorization`，只做 DDL，`column_exists` 守卫，不回填（design 决策 1）。
  **测试**: `test/database/test_alembic_single_head.py`
  **覆盖 AC**: AC-07、AC-09、AC-10
  **依赖**: 无

- [x] **T002**: 快照解析与组织条件构造
  **文件**: `database/models/org_snapshot.py`（新）、`test/audit/test_org_snapshot.py`（新）
  **逻辑**:
  - 哨兵常量：`DEPT_NONE = 0`、`DEPT_NOT_APPLICABLE = -1`。
  - 解析函数：`resolve_user_dept` / `aresolve_user_dept` / `aresolve_users_dept`（批量），返回 `(id, path)`。取主部门的 `department_id`，名称路径按 `path` 批量换名，查询包 `bypass_tenant_filter()`，异常时返回 `(None, None)` 并 `logger.warning`。
  - 填写函数：`stamp_audit_logs` / `astamp_audit_logs`，`operator_id == 0` 写 `-1`，只填两列仍为空的行；`astamp_session`、`stamp_session`，`api_subject_type` 非空写 `-1`。
  - 条件构造：`DeptSelection` 数据类、`build_dept_predicate(column, scope, selection)`（design 决策 5）。
  **测试**: 哨兵规则；成员关系主键陷阱；名称路径；异常留空；批量去重；条件的前缀带结尾 `/`、包含与不包含下级、归档、两个固定项、与闭包求交、受限用户丢弃固定项。
  **覆盖 AC**: AC-07、AC-10、AC-11、AC-16、AC-22、AC-23、AC-25
  **依赖**: T001

### Wave 2 — 写入点与范围解析

- [x] **T003**: 所有写入点接入快照 + 守卫测试
  **文件**:
  - `database/models/audit_log.py`（三个插入方法）
  - `database/models/session.py`（`insert_one` / `async_insert_one`）
  - 直接构造 `AuditLog` 的 9 处：`open_api/domain/repositories/credential_repository.py` ×3、`app_publish/domain/repositories/app_secret_repository.py`、`open_api` 调用审计的批量写入处、`open_mcp/server.py`、`open_mcp/auth.py`、`linsight/domain/services/personal_skill_service.py`、`public_endpoints/domain/services/guest_link.py`
  - 运行记录：`model_gateway_service._start_record`、`app_access_log_service.record_access`、`capability_audit.record_retrieval`
  - `test/audit/test_org_snapshot_write_sites.py`（新）
  **逻辑**: design §4.1。运行记录各按自己的主体字段判断，异常不能离开原函数。
  **测试**: DAO 三方法和会话两方法写入后有值；系统触发写 `-1`；开放接口会话写 `-1`；守卫扫描 `AuditLog(` 构造所在文件都调用了快照函数。
  **覆盖 AC**: AC-05、AC-07、AC-08、AC-11
  **依赖**: T002

- [x] **T004**: 部门范围解析与部门仓储
  **文件**: `department/domain/repositories/audit_dept_repository.py`（新）、`department/domain/services/audit_dept_scope.py`（新）、`test/audit/test_audit_dept_scope.py`（新）
  **逻辑**: 身份判定顺序与 `AuditDeptScope`（design 决策 4）；闭包含所管路径上的归档部门；部门管理员按当前审计租户过滤。
  **测试**: 全局超管、租户管理员（兼部门管理员）、部门管理员（多部门并集）、菜单角色、无主部门菜单角色、用户组管理员无菜单 → 拒绝。
  **覆盖 AC**: AC-12、AC-13、AC-14、AC-15、AC-17
  **依赖**: T002

### Wave 3 — 后端各页签

- [x] **T005**: 系统操作接入范围与组织筛选
  **文件**: `api/services/audit_log.py`（`_prepare_audit_query`、`_resolve_audit_groups`、`get_audit_log`、`export_audit_log`、`get_all_operators`）、`database/models/audit_log.py`（`get_audit_logs`、`get_all_operators` 加 `dept_predicate`）、`api/v1/audit.py`、`test/audit/test_audit_org_filter.py`（新）
  **逻辑**: 删除用户组管理员分支（design 决策 9）；四个组织参数写进签名；列表行带两列。
  **测试**: 范围与筛选的交集；改参请求范围外部门返回空；用户组管理员被拒；导出与列表一致；操作者候选受范围限制；组织与用户组同选为交集、用户组不扩大范围；原有对象、备注、原因字段照原样返回。
  **覆盖 AC**: AC-17、AC-18、AC-19、AC-24、AC-25、AC-28、AC-39、AC-40、AC-41
  **依赖**: T003、T004

- [x] **T006**: 应用使用接入范围、组织筛选与使用类型
  **文件**: `api/services/audit_log.py`（`get_session_list`、`get_session_messages`）、`api/v1/schema/chat_schema.py`（`AppChatList` 加 `operator_dept_id`、`operator_dept_path`、`usage_type`）、`chat_session/domain/repositories/audit_session_repository.py`（新）、`api/v1/audit.py`、`test/audit/test_audit_session_usage_type.py`（新）
  **逻辑**: design 决策 7；类型白名单扩到 5/10/15/20/25/30；20/25/30 名称用 `flow_name`。
  **测试**: 四类归类；多版本只计一次；20/25/30 进入列表；类型与组织取交集；导出带新字段。
  **覆盖 AC**: AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35
  **依赖**: T003、T004

- [x] **T007**: 两个候选接口
  **文件**: `api/v1/audit.py`、`department/domain/services/audit_dept_scope.py`、`department/domain/repositories/audit_dept_repository.py`、`chat_session/domain/repositories/audit_session_repository.py`、`test/audit/test_audit_candidates.py`（新）
  **逻辑**: design §6.1 契约。
  **测试**: 三类身份的顶层；`parent_id` 懒加载；搜索匹配名称、`dept_id`、`external_id`；归档平铺；固定项开关；全局超管按租户分组；用户候选受范围限制。
  **覆盖 AC**: AC-18、AC-21、AC-23、AC-27
  **依赖**: T004

- [x] **T008**: 会话详情的范围校验
  **文件**: `chat_session/api/endpoints/session.py`、`api/services/audit_log.py`（`assert_session_in_audit_scope`）、`test/audit/test_audit_session_detail_scope.py`（新）
  **逻辑**: design 决策 8。
  **测试**: 范围内放行，范围外拒绝；`/chat/history` 发起人本人放行；`/api/v1/chat/history` 不受影响。
  **覆盖 AC**: AC-36、AC-37、AC-38
  **依赖**: T004

- [x] **T009**: 应用运行记录接入组织
  **文件**: `app_governance/api/router.py`（`filters()`）、`app_governance/domain/schemas/runtime_audit.py`（`normalize`、`FIELDS`、scope 加 `dept_scope` 并进 `digest`）、`app_governance/domain/services/runtime_audit_scope.py`、`app_governance/domain/repositories/runtime_audit_repository.py`、`app_governance/domain/services/runtime_audit_export_service.py`（CSV 文案）、`test/app_governance/test_runtime_audit_org.py`（新）
  **逻辑**: design 决策 10 与 §4.2。
  **测试**: 参数解析（逗号串、`"false"`、非法值拒绝）；部门范围用户直接调用只拿闭包内记录；导出 CSV 文案。
  **覆盖 AC**: AC-20、AC-42
  **依赖**: T003、T004

### Wave 4 — 前端

- [x] **T010**: 动作补齐与模块映射
  **文件**: `platform/src/controllers/API/log.ts`、三份 `bs.json`、`systemLog/index.test.tsx`
  **逻辑**: 5 个旧动作进 `legacyActions`；`getActionsByModuleApi` 改显式映射；单租户隐藏租户管理模块。
  **测试**: 模块到动作的映射；5 个动作的三语文案不是原始值。
  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-06
  **依赖**: 无

- [x] **T011**: 组织筛选面板组件与 API
  **文件**: `platform/src/pages/LogPage/components/OrgFilter/*`（新）、`platform/src/controllers/API/log.ts`（`getAuditDepartmentsApi`）、三份 `bs.json`
  **逻辑**: design 决策 11。
  **测试**: 确定后不立即查询；清除；包含下级默认勾选；固定项按开关显示；归档项单列。
  **覆盖 AC**: AC-21、AC-22、AC-23、AC-26、AC-27
  **依赖**: T007

- [x] **T012**: 系统操作页接入
  **文件**: `systemLog/index.tsx`、`systemLog/auditRow.ts`、`controllers/API/log.ts`
  **逻辑**: 组织面板、组织列（三种哨兵文案）、参数、CSV 组织列。
  **覆盖 AC**: AC-10、AC-39、AC-41
  **依赖**: T005、T011

- [x] **T013**: 应用使用页接入
  **文件**: `useAppLog/index.tsx`、`controllers/API/log.ts`、`controllers/API/index.ts`（若需）
  **逻辑**: 组织面板、用户列后组织列、使用类型单选、用户候选改用 `/audit/session/users`、15/20/25/30 进日常详情、CSV 组织和类型列取自 `item`。
  **覆盖 AC**: AC-29、AC-30、AC-33、AC-35、AC-36
  **依赖**: T006、T007、T011

- [x] **T014**: 应用运行记录页接入
  **文件**: `runtime/RuntimeAuditPanel.tsx`、`runtime/RuntimeAuditCell.tsx`、`controllers/API/runtimeAudit.ts`
  **逻辑**: 三个子页加组织列与文案、组织面板、`dept_ids` 逗号串。
  **覆盖 AC**: AC-42
  **依赖**: T009、T011

### Wave 5 — 验收

- [ ] **T015**: `/e2e-test`，非管理员账号走完 spec AC
  **依赖**: T005–T014
- [ ] **T016**: `/sdd-code-review --base feat/3.1.0-beta1`
  **依赖**: T015

---

## 实际偏差记录

（实现中如有偏差，在这里留一行指针，论证写进 design.md。）

- T001：`AuditLog` 实际表名是 `auditlog`，迁移按此写（design §4.1 已改）。
- T003：模型调用的快照在 `ModelCallRecordWriter._write_record_batch` 整批取，不在 `_start_record`（design §4.1 已改，原因是热路径同步查库）。
- T003：`open_api.call` 三处入队与 `guest_link.py` 已经经过 `ainsert_audit_logs`，真正需要单独接入的直接构造是 5 处（`credential_repository` ×3、`app_secret_repository`、`personal_skill_service`）。design 决策 2、§4.1、§5 已按此改。
- T004：`audit_dept_repository.py` 推迟到 T007 建；T004 的范围解析只用已有 DAO，没有新查询。
- T005：删除无调用方的 `AuditLogService.get_filter_flow_ids`（用户组管理员入口，且引用了未导入的 `GroupResourceDao`，不可能执行）。
- T005：`test/audit/conftest.py` 新增 autouse `audit_identity`，替身部门管理关系、主部门和审计菜单；旧的「用户组管理员仍能看所管组」用例改为「无菜单被拒」。
- T005：`_user_has_log_web_menu` 删除，菜单判定并入 `AuditDeptScopeService._has_audit_menu`。
- T006：`/audit/session/users` 与 `get_session_users` 随 T006 一起建（与列表共用 `_session_scope_conditions`），T007 只补部门候选。
- T007：闭包里主部门（`exact_ids`）直接 `IN`，不走 path 子查询（design 决策 5）；全局超管跨租户时顶层取各租户根部门（design §6.1）。
- T008：`/chat/history` 额外放行标注任务分配人（`markappuser`），见 design 决策 8。
- T009：导出按执行时范围取数，不是被 `check_snapshot_scope` 拒绝；带 `app_id` 的请求不加部门条件，见 design 决策 10。
- T010：`systemLog/index.test.tsx` 在改动前就失败（mock 缺 `actionToI18nKey`，重置断言缺 F056 的 `targetAppId` / `tenantId`），改为部分 mock 并补齐断言。
- T011：「清除所选」直接把空选择写回页面草稿并关闭面板（仍要点「查询」才生效）；类型与参数构造放在 `controllers/API/log.ts`（`OrgSelection`、`toDeptParams`），供三个页签共用。
- T013：使用类型用单选下拉（与反馈筛选同款）；CSV 列顺序为 会话、应用、使用类型、创建时间、用户、组织、用户组……；`FilterByUser` 换成审计专用候选下拉。
- T014：`runtimeAudit.test.tsx` 的整体 mock 改为部分 mock（新增 `withRuntimeOrg`）；组织列放在访问者列之后。
- T015：107 库的迁移版本仍是 `f076_session_skill_snapshot`，没有执行 `alembic upgrade`。只给五张审计表补了可空的 `operator_dept_id` / `operator_dept_path` 和索引（迁移脚本里有 `column_exists`，以后正式升级会跳过）。API 用例 9 个通过；页面清单和非管理员账号还没走。
