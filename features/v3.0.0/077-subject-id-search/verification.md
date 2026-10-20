# F077 主线验证记录

日期 2026-10-15。基线 origin/feat/3.0.0：`fbb9bc60651d4b60d5b40eda8f538be207958cc5`。独立 worktree 和 codex/subject-id-search-3.0.0 分支；没有合并或 cherry-pick 任何客户分支提交。规格/设计沿用户已确认的通用需求。

## 主线纯净性

- 全部修改以主线版本为底逐段适配，新代码仅为 ID 查询、输入/分页状态及业务 ID 展示；没有整分支合并。
- User 未引入 is_hidden，授权 Scope 未引入 include_hidden；授权用户仍为主线平铺查询，没有新增用户树 API/前端组件。
- 无邀请确认/个人授权审批、文件变更审批、知识空间策略、机器人、网关或客户部署配置变更；权限模型文件未改。
- 仅增加 `v3_0_0_f077_subject_id_search_indexes.py`；父 revision 为主线原唯一 head `merge_release_information_heads`，未携带中粮 migration。
- 独立 reviewer 审查新增与修改文件，未发现可验证 P0/P1/P2 或客户定制混入。root 另修复 Client 用户/组切资源时分页污染，维持主线范围边界；适配器引用变化不触发搜索循环。
- 新增 src 内容扫描 cofco、include_hidden、is_hidden、personal_grant_invite、user_invite_request、hidden_from_lists、knowledge_space_read_bypass、grant-subjects/users/tree，无命中。主线已有部门空间范围逻辑原样保留。

## 本地执行

| 检查 | 结果 |
|---|---|
| 聚焦回归 | **168 passed, 4 skipped**；4 个为未配置夹具的真实 API E2E |
| 扩大回归 | **1516 passed, 132 failed, 10 skipped** |
| 相同主线基线扩大回归 | **1492 passed, 132 failed, 10 skipped**；失败和错误名称集合完全一致，无新增失败项 |
| Ruff 改动范围对比 | 当前 316 条、基线 349 条，新增诊断 0；整体 lint 并非全绿 |
| 架构守卫 | 全部修改及新增 src 文件 0 违规/警告 |
| Alembic | 单 head `f077_subject_id_search_indexes`；重复升级/降级、索引和数据保留 SQLite 测试通过 |
| 差异检查 | `git diff --check` 通过；最终暂存检查包含新增文件 |

测试包含纯规则、MySQL/DM SQL 编译（含达梦 as_comparison 修正）、真实 SQLite 查询、授权范围/计数、用户/部门/租户管理、用户组原成员显示、迁移图与回滚。期间修正测试 harness 对新 Repository 的会话注入以及新增目录装配参数的 mock 签名，没有为测试放宽业务范围。

使用 `/Users/shanghang/dataelem/ca-bisheng/src/backend/.venv/bin/python -m pytest -q`，工作目录和 PYTHONPATH 指向各自的 src/backend。config 指向主线自带 docker/bisheng/config/config.yaml；临时 wrapper 仅提供 localhost/test-only 的 !env 默认值，不复制客户配置或修改真实数据库。

扩大范围：`test/permission test/user test/department test/tenant test/user_group test/database/test_alembic_single_head.py test/database/test_dm_dialect_helpers.py`。

聚焦范围：`test/common/test_subject_search.py`、`test/user/test_management_subject_search.py`、`test/user/test_user_list_department_path.py`、`test/user/test_user_list_without_org_scope.py`、`test/department/test_global_members_search.py`、`test/department/test_department_lazy_api.py`、`test/tenant/test_tenant_users_query_source.py`、`test/tenant/test_grant_subject_search_repository.py`、`test/permission/test_f048_grant_subjects.py`、`test/permission/test_prospective_grant_application.py`、`test/permission/test_f048_background_resource_registry.py`、`test/user_group/test_user_group_service.py`、`test/database/test_alembic_single_head.py`、`test/database/test_subject_id_search_indexes.py`、`test/database/test_dm_dialect_helpers.py`、`test/e2e/test_e2e_subject_id_search.py`。

本地临时证据：`/private/tmp/f077-final-focused.log`、`/private/tmp/f077-current-broad.log`、`/private/tmp/f077-baseline.log`、`/private/tmp/f077-ruff-report.json`、`/private/tmp/f077-arch-guard.json`。

## 未执行与发布

- 两端前端测试、lint/typecheck/构建按用户既有约定交镜像/CI，本地未运行。页面交互清单见 e2e-checklist.md。
- 真实 API E2E 需专用测试租户和 E2E_SUBJECT_ID_FIXTURE；当前只读用例已提供，但因缺少夹具跳过。
- 此主线版本尚未执行真实 MySQL/DM8 DDL 和请求性能验收。达梦修复参考已验证的通用比较表达式；不能将另一环境的结果当成本分支验收。
- 需在专用 ≥15 万用户/3 万部门数据集，与原名称查询同环境基线比较 P50/P95、SQL 计划、冷热缓存及并发；目标服务端 P95≤500ms。当前不声称性能无回退。
- 发布前后端同版更新，执行 Alembic 正向迁移，仅新增两个非唯一 external_id 索引，没有数据回填或授权模型迁移。回退本 revision 只删除新增索引；实际库升级与回滚仍需按该环境流程备份验证。

## 扩大回归与主线一致的既有失败

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
- `test/permission/test_retry_failed_tuples.py::test_cleanup_deletes_only_succeeded_records_before_retention_cutoff`
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
- `test/department/test_department_api.py::TestDepartmentAPI::test_create_department_parent_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_get_department_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_update_department_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_delete_department_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_move_department_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_get_members_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_add_members_not_found`
- `test/department/test_department_api.py::TestDepartmentAPI::test_remove_member_not_found`
- `test/department/test_department_api.py::TestDepartmentPermission::test_permission_denied_delete`
- `test/department/test_department_api.py::TestDepartmentPermission::test_permission_denied_members`
- `test/department/test_department_dao.py::TestDepartmentModel::test_create_department`
- `test/department/test_department_dao.py::TestDepartmentModel::test_dept_id_unique`
- `test/department/test_department_dao.py::TestDepartmentModel::test_get_children`
- `test/department/test_department_dao.py::TestDepartmentModel::test_get_subtree`
- `test/department/test_department_dao.py::TestDepartmentModel::test_get_subtree_ids`
- `test/department/test_department_dao.py::TestDepartmentModel::test_update_paths_batch`
- `test/department/test_department_dao.py::TestDepartmentModel::test_check_name_duplicate_true`
- `test/department/test_department_dao.py::TestDepartmentModel::test_check_name_duplicate_false`
- `test/department/test_department_dao.py::TestDepartmentModel::test_check_name_duplicate_exclude`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_add_member`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_add_member_duplicate`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_remove_member`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_get_members_paged`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_get_member_count`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_get_user_departments`
- `test/department/test_department_dao.py::TestUserDepartmentModel::test_check_member_exists`
- `test/department/test_department_dao.py::TestTenantMountFields::test_defaults_are_unmounted`
- `test/department/test_department_dao.py::TestTenantMountFields::test_mount_persists`
- `test/department/test_department_dao.py::TestTenantMountFields::test_aget_mount_point_select_semantics`
- `test/department/test_department_dao.py::TestTenantMountFields::test_nearest_ancestor_select_semantics`
- `test/department/test_department_dao.py::TestTenantMountFields::test_no_ancestor_mount_returns_none`
- `test/department/test_department_dao_lazy.py::TestAgetChildren::test_active_only_by_default`
- `test/department/test_department_dao_lazy.py::TestAgetChildren::test_include_archived`
- `test/department/test_department_dao_lazy.py::TestAgetChildren::test_root_layer_parent_none`
- `test/department/test_department_dao_lazy.py::TestAgetChildrenExistence::test_returns_only_parents_with_active_children`
- `test/department/test_department_dao_lazy.py::TestAgetChildrenExistence::test_include_archived_counts_archived_child`
- `test/department/test_department_dao_lazy.py::TestAgetByNameLike::test_substring_match_unscoped`
- `test/department/test_department_dao_lazy.py::TestAgetByNameLike::test_scope_path_prefixes`
- `test/department/test_department_dao_lazy.py::TestAgetByNameLike::test_archived_excluded_by_default`
- `test/department/test_department_dao_lazy.py::TestAgetByNameLike::test_limit_caps_results`
- `test/department/test_department_lazy_api.py::TestChildrenLayer::test_root_layer_sys_admin`
- `test/department/test_department_lazy_api.py::TestChildrenLayer::test_children_of_node_active_only`
- `test/department/test_department_lazy_api.py::TestChildrenLayer::test_children_include_archived`
- `test/department/test_department_lazy_api.py::TestChildrenLayer::test_has_children_false_for_leaf`
- `test/department/test_department_lazy_api.py::TestChildrenLayer::test_leaf_children_empty`
- `test/department/test_department_lazy_api.py::TestSearch::test_prunes_to_ancestor_chain`
- `test/department/test_department_lazy_api.py::TestSearch::test_case_insensitive`
- `test/department/test_department_lazy_api.py::TestSearch::test_truncated_when_over_limit`
- `test/department/test_department_lazy_api.py::TestPathTree::test_locate_deep_node_sys_admin`
- `test/department/test_department_lazy_api.py::TestPathTree::test_locate_missing_node_sys_admin`
- `test/department/test_department_lazy_api.py::TestDeptAdminScope::test_root_layer_is_admin_dept`
- `test/department/test_department_lazy_api.py::TestDeptAdminScope::test_search_ancestors_clamped_to_scope`
- `test/department/test_department_lazy_api.py::TestDeptAdminScope::test_path_tree_clamped`
- `test/department/test_department_lazy_api.py::TestDeptAdminScope::test_children_out_of_scope_parent_denied_no_leak`
- `test/department/test_department_lazy_api.py::TestDeptAdminScope::test_locate_out_of_scope_denied_no_leak`
- `test/department/test_department_service.py::TestCreateDepartment::test_create_department_success`
- `test/department/test_department_service.py::TestCreateDepartment::test_create_department_name_duplicate`
- `test/department/test_department_service.py::TestCreateDepartment::test_create_department_parent_not_found`
- `test/department/test_department_service.py::TestGetTree::test_get_tree`
- `test/department/test_department_service.py::TestUpdateDepartment::test_update_department_name`
- `test/department/test_department_service.py::TestUpdateDepartment::test_update_department_source_readonly`
- `test/department/test_department_service.py::TestDeleteDepartment::test_delete_department_success`
- `test/department/test_department_service.py::TestDeleteDepartment::test_delete_department_has_children`
- `test/department/test_department_service.py::TestDeleteDepartment::test_delete_department_has_members`
- `test/department/test_department_service.py::TestMoveDepartment::test_move_department_success`
- `test/department/test_department_service.py::TestMoveDepartment::test_move_department_circular`
- `test/department/test_department_service.py::TestMemberManagement::test_add_members_batch`
- `test/department/test_department_service.py::TestMemberManagement::test_add_members_duplicate`
- `test/department/test_department_service.py::TestMemberManagement::test_get_members_paged`
- `test/department/test_department_service.py::TestMemberManagement::test_remove_member`
- `test/department/test_department_service.py::TestMemberManagement::test_remove_member_not_found`
- `test/department/test_department_service.py::TestRootDepartment::test_create_root_department`
- `test/department/test_department_service.py::TestRootDepartment::test_create_root_department_exists`
- `test/department/test_department_sso_dao.py::TestDepartmentF014Fields::test_defaults`
- `test/department/test_department_sso_dao.py::TestDepartmentF014Fields::test_soft_delete_flag_persists`
- `test/department/test_department_sso_dao.py::TestGetBySourceExternalId::test_returns_active_row`
- `test/department/test_department_sso_dao.py::TestGetBySourceExternalId::test_returns_archived_row_no_is_deleted_filter`
- `test/department/test_department_sso_dao.py::TestGetBySourceExternalId::test_source_isolation`
- `test/department/test_department_sso_dao.py::TestUpsertByExternalId::test_insert_when_missing`
- `test/department/test_department_sso_dao.py::TestUpsertByExternalId::test_update_preserves_mount_fields`
- `test/department/test_department_sso_dao.py::TestUpsertByExternalId::test_resurrect_clears_is_deleted`
- `test/department/test_department_sso_dao.py::TestArchiveByExternalId::test_archive_flips_flags_and_ts`
- `test/department/test_department_sso_dao.py::TestArchiveByExternalId::test_archive_missing_returns_no_row`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_secondary_path_skips_sync`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_primary_path_routes_to_change_primary`
- `test/department/test_dept_member_add_sync.py::test_aadd_members_primary_propagates_relocate_blocked`
- `test/department/test_dept_member_add_sync.py::test_acreate_local_member_triggers_sync_for_new_user`
- `test/department/test_init_root_department.py::TestInitDefaultRootDepartment::test_init_creates_root_department`
- `test/department/test_init_root_department.py::TestInitDefaultRootDepartment::test_init_idempotent`
- `test/tenant/test_sync_user_scope_clear.py::test_cross_tenant_relocation_clears_scope`
- `test/tenant/test_sync_user_scope_clear.py::test_same_tenant_noop_does_not_clear_scope`
- `test/tenant/test_sync_user_scope_clear.py::test_scope_clear_failure_does_not_break_relocation`
- `test/tenant/test_tenant_bypass_filter_guard.py::test_bypass_tenant_filter_must_carry_tenant_id_predicate`
- `test/tenant/test_tenant_id_default_guard.py::test_tenant_id_default_must_be_none`
- `test/tenant/test_tenant_mount_service.py::TestMountChild::test_happy_path_creates_child_and_sets_mount`
- `test/tenant/test_tenant_mount_service.py::TestUnmountChild::test_unmount_migrates_resources_archives_and_unsets`
- `test/tenant/test_tenant_mount_service.py::TestMountChildSubtreeSync::test_mount_invokes_subtree_sync_and_records_counts`
- `test/tenant/test_tenant_mount_service_transaction.py::test_mount_child_writes_root_dept_id_and_single_commit`
