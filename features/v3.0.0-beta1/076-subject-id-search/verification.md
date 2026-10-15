# F076 验证记录

日期：2026-10-15。分支：`feat/cofco-1021-3.0.0-beta1`。按用户要求实现后统一测试，未提交、合并或部署。

## 已执行

| 检查 | 结果 | 边界 |
|---|---|---|
| 聚焦后端回归 | **153 passed, 4 skipped** | 4 个跳过项是真实 API E2E，未配置专用夹具；其余测试包含真实 SQLite SQL、权限和分页回归 |
| 扩大后端回归 | **1681 passed, 46 failed, 24 skipped** | 不是全绿；与隔离 HEAD 基线比较，失败用例名称集合完全一致，无本次新增失败项 |
| HEAD 隔离基线 | **1654 passed, 46 failed, 20 skipped** | 使用相同测试配置及前端源码快照；未改动当前工作区代码 |
| 架构守卫 | 0 违规、0 警告 | 对所有修改和新增 src 文件执行 |
| Ruff | 新增诊断 0；当前 231、HEAD 351 | 改动文件仍有既存诊断，不宣称整体 lint 通过；新增索引迁移测试单独检查通过 |
| Alembic | 单 head：`f076_subject_id_search_indexes` | 仅离线图检查，不代表目标库已升级 |
| 索引迁移测试 | SQLite 实际建删索引、重复升级/降级和原数据保留通过 | 不等同 MySQL/DM8 DDL 实测 |
| 差异空白检查 | `git diff --check` 通过 | 不代替前端编译检查 |
| 独立代码审查 | 已完成并修复发现项 | 修复租户候选仅首屏、切类型丢已选、完整部门树遗漏 external_id；不改变授权写入 |

聚焦命令（`src/backend` 中、配置必要的测试环境变量后）：

```sh
.venv/bin/pytest -q \
  test/common/test_subject_search.py \
  test/user/test_management_subject_search.py \
  test/user/test_user_list_department_path.py \
  test/user/test_user_list_without_org_scope.py \
  test/department/test_global_members_search.py \
  test/department/test_department_lazy_api.py \
  test/tenant/test_tenant_users_query_source.py \
  test/tenant/test_grant_subject_search_repository.py \
  test/permission/test_f048_grant_subjects.py \
  test/permission/test_prospective_grant_application.py \
  test/permission/test_f048_background_resource_registry.py \
  test/user_group/test_user_group_service.py \
  test/database/test_alembic_single_head.py \
  test/database/test_subject_id_search_indexes.py \
  test/database/test_dm_dialect_helpers.py \
  test/e2e/test_e2e_subject_id_search.py
```

扩大命令：上述 common、索引图和 DM 方言测试，加 `test/permission test/user test/department test/tenant test/user_group` 目录及本期 E2E。本地执行经临时 wrapper 为 !env 配置提供 localhost/test-only 默认值，不改项目配置，不使用生产凭据。

临时原始证据：`/private/tmp/f076-final-focused-tests.log`、`/private/tmp/f076-broad-tests.log`、`/private/tmp/f076-head-tests.log`、`/private/tmp/f076-ruff-report.json`、`/private/tmp/f076-arch-guard.txt`。这些临时文件不属于提交内容；可按上述命令复测。

## 待验收

- 真实 API E2E：使用专用测试租户，配置 `E2E_SUBJECT_ID_FIXTURE`，准备带 `e2e-subject-id-` 前缀的用户/部门/资源；用例只读、不创建业务数据。环境 JSON 字段见测试 fixture。当前没有实际服务通过证据。
- 两个 SPA 的页面检查见 [e2e-checklist.md](./e2e-checklist.md)，全部保持待执行。前端测试、lint、typecheck、构建遵照用户既有约定未在本地运行，仍需镜像/CI 质量门禁。
- MySQL/DM8 的真实大小写/通配符执行、索引 DDL、执行计划均待验收。当前仅有 SQL 编译和 SQLite 语义证据。
- ≥15 万用户、≥3 万部门的双库性能，包含名称原基线与 ID 完整/短前缀/无结果/越界页/最宽和部门范围，记录硬件、并发、缓存、P50/P95、SQL 计划；目标各入口服务端 P95≤500ms。**当前不能宣称名称性能无回退或性能验收通过。**

## 升级与回滚

唯一结构增量为 user、department 各一个 external_id 前导非唯一索引：`ix_user_external_id_search`、`ix_department_external_id_search`。保留来源唯一约束，无业务数据回填。前后端同版发布；启动前按既有流程执行 `alembic upgrade head`，先核对目标库索引创建能力、耗时和锁影响。本地只验证了迁移图和 SQLite 行为。

如撤回本期版本，前后端一起恢复；若确认删除索引，按发布流程回退至前一 revision `cofco_923_information_cursor`，本期 downgrade 只删除这两个索引，不删除用户、部门或授权数据。生产升级/回滚未在本任务执行。

## 扩大回归中与 HEAD 一致的 46 个失败

以下仅证明失败在同一配置下原已存在；没有将这些失败算作通过，也未扩大本期范围修复它们。

- `test/permission/test_f027_role_scope_nullsafe_unique.py::test_upgrade_adds_scope_key_and_swaps_to_nullsafe_unique_constraint`
- `test/permission/test_f027_role_scope_nullsafe_unique.py::test_upgrade_dedupes_existing_null_scope_collisions_before_creating_constraint`
- `test/permission/test_f027_role_scope_nullsafe_unique.py::test_downgrade_restores_previous_constraint_and_drops_scope_key`
- `test/permission/test_f048_decision_api.py::test_concrete_action_check_returns_true_and_normal_false_as_200`
- `test/permission/test_f048_decision_api.py::test_unknown_action_and_fga_unavailable_preserve_distinct_errors`
- `test/permission/test_f048_decision_api.py::test_missing_and_cross_tenant_targets_are_equally_hidden`
- `test/permission/test_f048_domain_boundaries.py::test_f048_domain_does_not_import_business_orm_repository_or_service`
- `test/permission/test_f048_grant_api.py::test_resource_context_models_roster_and_self_summary_contract`
- `test/permission/test_f048_grant_api.py::test_protected_mutation_and_stale_cursor_preserve_business_codes`
- `test/permission/test_f048_grant_api.py::test_mode_draft_and_apply_only_send_server_draft_identity`
- `test/permission/test_f048_legacy_runtime_retirement.py::test_frontends_do_not_expose_retired_permission_contracts`
- `test/permission/test_f048_linsight_runtime.py::test_linsight_rejects_old_role_or_unhealthy_runtime[manager0]`
- `test/permission/test_f048_linsight_runtime.py::test_linsight_rejects_old_role_or_unhealthy_runtime[manager1]`
- `test/permission/test_legacy_rbac_sync_service.py::test_group_change_handler_invalidates_direct_user_cache`
- `test/user/test_user_department_service.py::TestHappyPath::test_promote_new_primary_triggers_sync`
- `test/user/test_user_department_service.py::TestHappyPath::test_first_primary_no_demote`
- `test/user/test_user_department_service.py::TestBlockedPropagation::test_sync_blocked_raises`
- `test/user/test_user_department_service.py::TestTriggerEnumUsed::test_trigger_value_is_dept_change`
- `test/user/test_user_string_lengths.py::test_user_string_columns_are_bounded[user_name-128-False]`
- `test/user/test_user_tenant_sync_service.py::TestNoChange::test_same_leaf_returns_early`
- `test/user/test_user_tenant_sync_service.py::TestRelocateHappy::test_swap_flow_calls_all_collaborators`
- `test/user/test_user_tenant_sync_service.py::TestRelocateHappy::test_warns_but_proceeds_when_owned_resources_exist`
- `test/user/test_user_tenant_sync_service.py::TestRelocateHappy::test_permission_rewrite_revokes_old_and_grants_new`
- `test/user/test_user_tenant_sync_service.py::TestRelocateHappy::test_skip_permission_grant_for_root_leaf`
- `test/user/test_user_tenant_sync_service.py::TestBlocked::test_not_blocked_when_enforce_true_but_no_owned_resources`
- `test/user/test_user_tenant_sync_service.py::TestFirstTimeSync::test_no_active_row_no_count_no_delete`
- `test/user/test_user_tenant_sync_service.py::TestFirstTimeSync::test_first_time_sync_root_writes_no_audit_reason_set`
- `test/user/test_user_tenant_sync_service.py::TestPermissionTolerance::test_permission_exception_does_not_abort_sync`
- `test/user/test_user_update_tenant_admin_gate.py::test_tenant_admin_helper_defined`
- `test/user/test_user_update_tenant_admin_gate.py::test_tenant_admin_scoped_user_ids_helper_defined`
- `test/department/test_apply_local_primary_dept_sync.py::test_no_old_primary_inserts_and_syncs`
- `test/department/test_apply_local_primary_dept_sync.py::test_cross_tenant_swap_dispatches_fga_and_syncs`
- `test/department/test_apply_local_primary_dept_sync.py::test_relocate_blocked_propagates`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_secondary_path_skips_sync`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_primary_path_routes_to_change_primary`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_primary_propagates_relocate_blocked`
- `test/department/test_dept_member_add_sync.py::test_acreate_local_member_triggers_sync_for_new_user`
- `test/tenant/test_sync_user_scope_clear.py::test_cross_tenant_relocation_clears_scope`
- `test/tenant/test_sync_user_scope_clear.py::test_same_tenant_noop_does_not_clear_scope`
- `test/tenant/test_sync_user_scope_clear.py::test_scope_clear_failure_does_not_break_relocation`
- `test/tenant/test_tenant_bypass_filter_guard.py::test_bypass_tenant_filter_must_carry_tenant_id_predicate`
- `test/tenant/test_tenant_id_default_guard.py::test_tenant_id_default_must_be_none`
- `test/tenant/test_tenant_mount_service.py::TestMountChild::test_happy_path_creates_child_and_sets_mount`
- `test/tenant/test_tenant_mount_service.py::TestUnmountChild::test_unmount_migrates_resources_archives_and_unsets`
- `test/tenant/test_tenant_mount_service.py::TestMountChildSubtreeSync::test_mount_invokes_subtree_sync_and_records_counts`
- `test/tenant/test_tenant_mount_service_transaction.py::test_mount_child_writes_root_dept_id_and_single_commit`
