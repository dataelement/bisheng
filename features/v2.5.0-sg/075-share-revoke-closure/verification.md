# 验证记录

- Status: `LOCAL_VERIFIED / DEPLOYMENT_MANUAL_REQUIRED`
- 日期：2026-10-14。用户确认方案后实施；证据来自本地代码、SQLite、存储替身和真实前端组件的模拟接口。未部署、未提交、未改线上数据。

## 可执行证据

| 编号 | 范围和实际结果 | 日志 |
|---|---|---|
| E-001 | 将 HEAD 的旧业务方法通过内存替换运行新增复现；5 项按预期失败，包括旧 deleting 分享阻塞再次申请、申请规范化冲突、撤回日志缺失。未替换磁盘生产文件 | `/tmp/share-revoke-business-red.log` |
| E-002 / E-003 | 新增分享闭环 13 项、旧清理与新投影交错 1 项通过；包含待清理/失败、有效冲突拒绝、重复申请、历史保留、旧回调、日志失败回滚和身份拒绝 | 纳入 E-005 |
| E-004 | 两个前端测试文件共 24 项通过；覆盖列表/详情标识、再次申请、撤回失败不移除行、定时刷新和卸载取消 | `/tmp/share-revoke-ui-final.log` |
| E-005 | 受影响后端回归 110 passed、12 deselected，13.70 秒。排除项及理由见下文，未声称全部原有测试通过 | `/tmp/share-revoke-backend-final.log` |
| E-006 | npm run build 成功，22.88 秒；保留项目已有脚本类型、Browserslist 和打包体积等警告 | `/tmp/share-revoke-build-final.log` |
| E-007 | 新增服务/测试 Ruff 检查与格式检查、修改后端源文件 py_compile、git diff --check、本次生产文件 arch-guard 检查通过 | 本地命令执行，无架构守卫输出 |

后端环境：src/backend/.venv/bin/python，Python 3.10。前端环境：既有 Node 20 与项目依赖，没有新增依赖。

### 后端最终命令

在 src/backend 执行：

```sh
.venv/bin/python -m pytest \
 test/knowledge/test_share_revoke_closure.py \
 test/knowledge/test_share_revoke_projection.py \
 test/knowledge/test_knowledge_document_distribution_share.py \
 test/knowledge/test_knowledge_distribution_delete_adapter.py \
 test/knowledge/test_document_projection_batch.py \
 test/knowledge/test_document_projection_batch_worker.py \
 test/knowledge/test_projection_recovery_script.py \
 test/knowledge/test_shared_space_projection_batch.py \
 test/approval/test_knowledge_file_share_approval.py \
 test/approval/test_approval_center_query_service.py \
 -k 'not (registered_rebuild_task_uses_real_celery_parse_route or share_target_candidates_only_include_other_department_spaces or share_target_validation_does_not_require_target_space_view or share_target_validation_rejects_other_tenant or share_approved_resolves_current_target_folder_location or share_approved_rejects_target_folder_from_other_space or list_my_tasks_aggregates_instance_summary or get_instance_detail_blocks_unrelated_user_and_returns_action_logs or withdraw_instance_cancels_pending_tasks_and_records_log or admin_service_lists_and_creates_scenarios or delete_flow_rejected_when_referenced_by_routes or delete_flow_succeeds_when_no_routes_reference_it)' \
 -q --disable-warnings --tb=short
```

在 src/frontend/client 执行：

```sh
npm run test:ci -- --runInBand --coverage=false --runTestsByPath src/pages/knowledge/SpaceDetail/FileShareDialog.test.tsx src/components/approval/ApprovalCenterDialog.test.tsx
npm run build
```

### 本地浏览器验证

内置浏览器使用 localhost 临时验证页面和真实 FileShareDialog、ApprovalCenterDialog 组件；接口、审批生效、清理完成使用模拟数据。最终代码状态下再次执行：

1. 原分享撤回后显示“已撤回 · 后台清理中”，撤回按钮消失。
2. 旧记录清理期间仍可提交新申请。
3. 模拟新审批生效，再模拟旧清理完成；新分享保持生效。
4. 打开原审批自动显示已处理视图；原记录列表、详情、时间线显示已撤回，再次分享记录只显示已同意。

截图：/tmp/share-revoke-history.png。临时浏览器标签、验证服务和自建模拟文件已清理，不交付模拟页面为产品功能。

## 验收对应

| 验收 | 证据 | 状态 |
|---|---|---|
| AC-1、AC-2 | E-002 / E-005：新 ID、新目录/下载策略、幂等回调、有效占位及待审冲突 | 本地通过 |
| AC-3、AC-4 | E-002 / E-005：旧租约阻止新任务提前领取，旧 finalizer 只删除旧 ID，新任务恢复目标归属；现有恢复工具回归 | SQLite / 存储替身通过 |
| AC-5、AC-6、AC-7 | E-003 / E-004：manager/recipient 两路径日志、清理后历史、旧回调、跨租户/目标拒绝、事务回滚 | 本地通过 |
| AC-8 | E-004、浏览器闭环：清理中/失败展示、定时刷新、已办筛选及历史标识 | 本地通过 |

## 基线与未验证项

- 原有两个审批测试文件存在 11 项基线失败；在内存使用 HEAD 的审批中心业务方法运行相同测试，仍为 15 passed / 11 failed。五项缺少 SimpleNamespace.state，六项涉及旧仓储/AsyncMock/场景配置等夹具不匹配。日志 /tmp/share-revoke-approval-baseline.log。没有顺带修改这些测试或产品行为。
- 真实 Celery 解析路由子进程测试因本机 SciPy _spropack.cpython-310-darwin.so 无效 zero-fill section 无法导入；该 worker 路由未修改。日志 /tmp/share-revoke-backend-focused.log。上述 11 项加该项共 12 项从最终定向回归排除。
- 真实 MySQL/DM8 锁竞争、ES/Milvus/OpenFGA、Celery 线上队列未实测。SQL 使用既有 ORM 与 EXISTS，无新增 Schema；SQLite 验证不能证明生产数据库并发特性。
- 必须同步更新前后端，上线后实际验证撤回及再次分享、旧任务完成、新索引归属和原已办履历。没有将本地验证描述为线上闭环完成。
- 既有审批实例或关联键已经缺失的旧分享只告警，不伪造审批；本次不补齐过去已清理且缺少撤回日志的历史。
- 原分享审批状态仍保留原结果；撤回是操作日志的业务终态，不改成审批中申请撤销，不自动回退积分。
- 自检确认放宽标记只用于分享校验，通用发布规则未放宽；原件、其他库入口、审批查询授权及有限清理失败预算保持原行为。既有大文件仅局部修改，不进行无关重构。
