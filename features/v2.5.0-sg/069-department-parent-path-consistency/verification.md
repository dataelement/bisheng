# 验证记录

- Feature ID: `069-department-parent-path-consistency`
- Updated: `2026-09-30`
- Overall Status: `MANUAL_VERIFY_REQUIRED` — 本地修复与定向回归完成，未验证真实 MySQL/DM8 并发锁及生产部署。
- 执行目录：`src/backend`；环境：已有 `.venv/bin/python`，未安装或更换依赖。

## 执行证据
| Evidence | 操作 | 结果 |
|---|---|---|
| E-001 | 修复前运行 `test/department/test_department_sync_reparent_paths.py` | 14 failed, 4 passed；旧缓存路径被写入、真实坏路径后代遗漏、无效父级未拒绝及半创建风险得到复现 |
| E-002 | 接入三类变更入口后运行同文件 | 18 passed |
| E-003 | 补充后台创建、真实父链挂载检查、第二次 UPDATE 故障回滚，运行下述相关回归 | 117 passed, 7 deselected，exit 0；包含 26 项真实 SQLite ORM 回归 |
| E-004 | 独立测试进程将两个 DAO 写入方法及后台创建/移动方法替换为 `6f2a4535f785a38948c6d1b2781018182377aaf0` 原实现 | 下述 7 项同样失败；工作区文件未回退或改写，未将既有失败算为通过 |
| E-005 | 新回归文件及 DeptUpsertService 的 ruff check | PASS |
| E-006 | 其余受影响文件完整 ruff 扫描与新增行对照 | 有 79 条既有提示，本次新增行 0 条；未清理无关风格问题，不宣称整个旧文件 lint 全绿 |
| E-007 | 三个业务文件 py_compile、针对本次文件的 git diff --check | PASS |
| E-008 | 三个业务文件分别执行 `scripts/arch-guard.sh` | exit 0，无架构违规输出 |

最终相关回归命令：

```bash
.venv/bin/python -m pytest -q \
  test/department/test_department_sync_reparent_paths.py \
  test/test_department_service.py test/test_department_sso_dao.py \
  test/sso_sync/test_sg_departments_sync_service.py \
  test/test_dept_upsert_service.py test/test_sso_departments_sync_service.py \
  test/test_department_relink_service.py test/department/test_department_root_guard.py \
  -k 'not (test_get_tree or test_get_members_includes_private_groups_for_global_super or test_get_members_includes_user_group_admin_rows_for_display or test_archive_triggers_fga_cleanup or test_top_level_upsert_passes_none_parent_and_root_path or test_nested_upsert_derives_path_from_parent)' \
  --tb=short
```

## 已有失败边界
以下失败在替换回原方法后仍存在，没有为通过测试扩大生产修改：
- `TestGetTree.test_get_tree`
- `TestPermission.test_get_members_includes_private_groups_for_global_super`
- `TestPermission.test_get_members_includes_user_group_admin_rows_for_display`
- `TestPermission.test_get_tree_allows_tenant_admin_full_tree`
- `TestSgDepartmentsSyncService.test_archive_triggers_fga_cleanup`：模拟组织缺少 path。
- `TestUpsertFromSyncPayload.test_top_level_upsert_passes_none_parent_and_root_path`
- `TestUpsertFromSyncPayload.test_nested_upsert_derives_path_from_parent`：旧预期与现有父路径参数契约不一致。

## 验收覆盖
| Acceptance | Evidence | 状态 |
|---|---|---|
| AC-001 | E-001, E-003 | PASS：同父/换父、错前缀/空路径、无关及其他租户前缀不误改 |
| AC-002 | E-003 | PASS：缺失/跨租户父级和移入真实后代被拒绝；创建失败和已执行第一条 UPDATE 后的故障完整回滚 |
| AC-003 | E-003, E-008 | PASS（本地）：挂载标志、归档状态、默认根禁止移动及提交后通知保持；旧路径不能掩盖真实挂载后代 |
| AC-004 | E-001 至 E-008 | PASS（本地），真实数据库验证另列 |

## 未执行项及发布边界
- 未部署、未重启服务、未操作生产数据库和 ES；330 条生产历史路径不会仅因发布新代码立刻全部恢复。
- 本轮不重写所有使用 path 的查询或既有挂载预检；完整历史清理及看板重新同步需另行确认后执行。
- SQLite 验证不能证明 MySQL/DM8 的行锁、死锁及并发插入行为；目标环境需覆盖并发移动/新增与事务回滚。
- `test/department/test_org_level_on_create.py` 属于真实远程数据库流转测试，本轮不作为已验证证据；初次较大测试命令在到达该文件前已中断，最终回归未包含它。
- 外部操作在验证期间提交为 `df6a59da7`；最终成功测试对应其业务代码，本轮没有执行提交或推送。
- 用户重试时已回到 `feat/2.5.0-sg`，工作区业务代码与已验证提交一致，仅补文档；复用 E-003，不重复运行同一成功回归集。
