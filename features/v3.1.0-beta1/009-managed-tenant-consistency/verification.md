# F009 实施验证记录

日期：2026-11-11。用户已确认最小设计及范围；当前分支 `codex/3.1.0-beta1/managed-tenant-bugfix`。业务实现和本地检查完成，集成验收尚未完成。没有提交、推送、合并、部署或改动生产数据。原完整40条AC不能全部标为交付；范围仍为28纳入、11部分、AC-33延期。

## 实际结果

| 检查 | 结果 | 证据/限制 |
| --- | --- | --- |
| 本批21个新增后端测试文件 | **86 passed，0 failed** | 真实SQLite事务/租户过滤为主，外部系统用局部替身；包含权限恢复SQL镜像、复制worker入口，不是broker端到端 |
| 16个既有相关回归文件 | **202 passed，10 failed** | 10个失败ID与原HEAD隔离基线中复现者一致，详见下表及validation-results.json；旧DAO/SQL替身已适配当前E/仓储 |
| HTTP E2E | **3 skipped** | 专用隔离环境、前缀数据与临时token缺失；0项端到端通过，不能算API验收 |
| DDL | SQLite upgrade重复执行/downgrade保留旧行通过；alembic唯一head | head `v310b1_f009_managed_tenant`；父 `v310b1_f004_workflow_soft_delete`；MySQL/DM8未执行 |
| Ruff增量 | **0新增诊断** | 当前诊断与HEAD按(rule,message)计数比较；遗留文件未宣称全量lint通过 |
| arch-guard | **0 VIOLATION** | 每个修改/新增Python路径单独检查；workflow API现存分层WARNING及测试假密码WARNING留证，未当通过全库红线 |
| locale生成一致/i18n | **通过** | shared源三语与六份产物一致；85个既有frontend-only错误码提示未扩展清理 |
| 改动TS/TSX语法 | **2文件0语法错误** | TypeScript transpileModule；不是完整类型检查或浏览器验证 |
| Platform完整TSC | **未通过** | 当前依赖图缺react/共享workspace包类型，并有共享组件诊断；不能写成构建通过 |
| CLI | `managed_tenant_preflight.py --help`通过 | 没有连接生产执行盘点；FGA验证输出NOT_RUN |

## 已核实基线失败

在 `/tmp/f009-baseline-check` 由原HEAD的 `git archive` 只读快照执行同名用例，未修改当前worktree来切换基线。六条SSO用例及四条部门编排用例在旧HEAD即失败；不将它们隐藏、改成skip或归咎本次修复。原HEAD原相关集合为124 passed / 10 failed；本轮扩展到16模块并适配受本批接口变化影响的替身，两个集合的通过总数不可直接做增减比较。

| 模块 | 基线已失败用例 |
| --- | --- |
| SSO | test_wecom_explicit_re_enable_clears_delete；test_empty_admin_list_removes_fga_admin_on_sso_member_dept；test_leader_dept_grants_admin_tuple；test_name_change_triggers_update；test_successful_existing_user_sync_touches_update_time；test_disabled_user_skips_guest_reconcile |
| 部门成员编排 | test_aadd_members_secondary_path_skips_sync；test_aadd_members_primary_path_routes_to_change_primary；test_aadd_members_primary_propagates_relocate_blocked；test_acreate_local_member_triggers_sync_for_new_user |

额外尝试的既有 `test/api/test_build_managed_tenant_scope.py` 有2失败（假表缺flow.is_delete），同样在旧HEAD单独复现为2 failed / 2 passed；不计入上表202/10或新增86结果。原14个观察脚本只证明旧缺陷可复现，不当修复正确性回归。

## 可复现命令

从 `src/backend`，Python使用主仓已有 `.venv/bin/python`，配置为 `/tmp/bisheng-managed-tenant-review-config.yaml` 的隔离空配置；不读取生产凭据。环境前缀：

```sh
config=/tmp/bisheng-managed-tenant-review-config.yaml PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest <文件集合> -q -p no:cacheprovider --disable-warnings --tb=short
```

新增集合逐项列在[validation-results.json](validation-results.json)的new_regressions.files，不包含E2E。既有集合为role/test_role_service、tool/test_tool_executor_permissions、user/test_user_tenant_sync_service、user/test_user_tenant_sync_subtree、sso/test_sso_login_sync_service、department/test_dept_member_add_sync、approval/test_approval_gate、dsh/test_subject_policy、dsh/test_chat_credits、quota/test_quota_service、quota/test_quota_service_check_chain、quota/test_quota_service_tenant_tree、quota/test_require_quota_decorator、permission/test_creation_rollback、permission/test_creation_rollback_repository、permission/test_f048_projection_sql_runtime，均在test下、扩展名.py。

前端从仓库根执行 `node src/frontend/packages/locales/scripts/build.mjs --check` 与 `node src/frontend/scripts/check-i18n.mjs`。仅复用主仓现有依赖软链接，无安装/升级依赖。完整TSC结果不通过，临时原始日志在 `/tmp/f009-tsc.txt`。

## 测试证明的边界

角色定义O事务、本人H绑定/E/菜单、B≠S候选、外国兼属拒绝、作用域丧失/扩张不复活、回迁不复活、SSO后代路径与兼属支持终止、重复快照不发默认、10/5/3配额、统计未知、creator迁出止增、父子/v0同T、PENDING前置拒绝、联合列表过滤、原创建账本/owner SQL finalization、copy固定关联/唯一领取/条件发布与局部失败，均有本地回归。并非证明真实MySQL/DM8行锁、跨进程竞态、FGA收敛、broker应答丢失、文件/向量完整性或浏览器交互。

MySQL/DM8、FGA、Redis、Celery broker、对象/向量库和浏览器尚待隔离测试环境。按[升级说明](upgrade-guide.md)先排空旧copy消息，再执行集中验收；[E2E报告](e2e-report.md)和[手动清单](e2e-checklist.md)保留未勾选状态。T047/T048没有假标完成；当前不满足合入/发布验收门禁。

## 发布线基线差异

最终只读核对：当前HEAD `24c02859e2`，本地缓存 `origin/feat/3.1.0-beta1=d69b219394`，`git rev-list --left-right --count HEAD...origin/feat/3.1.0-beta1` 为0/2156；没有fetch，不能称此引用为服务器最新状态。本次变更与基线之后发布线变更有38个路径重叠（含文档/测试），明细见release-baseline-check.json。发布线已另含`v310b1_merge_work130_heads`，其parent包括本分支原F004及f130部署历史；当前F009仅在旧基线上是唯一head。未自动合并2156个提交或改其父revision冒充兼容。同步当前发布线、处理冲突/迁移head并重跑检查，是合入前独立必需步骤。
