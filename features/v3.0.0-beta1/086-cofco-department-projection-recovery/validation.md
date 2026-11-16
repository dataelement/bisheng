# F086 本地验证记录

## R3三项评审修正验证（2026-11-16）

本次基线为cofco-1118 / `a58ab1c2cbfe383e23f3f210c22dbc954904ca0a`。修正共享发布读屏障、合法挂载子树移动、旧父级快照覆盖路径；普通资源授撤权只读Catalog校验一起复用屏障。没有改成单用户门禁，没有新增schema/模型/依赖或修改前端。

- Test-first：正常路径新用例先观察到4项失败（合法挂载2项、混合批次/跨请求旧快照2项），非法拓扑原有3项拒绝通过；共享Catalog调度先观察到2项排他冲突失败。日志`/private/tmp/f086-normal-paths-red.log`、`/private/tmp/f086-catalog-barrier-red.log`。
- 最终原369项加14项新回归：**383 passed，无skip**（独立MySQL测试在该次选择中deselect，另行实跑）；971条现有warning，日志`/private/tmp/f086-r123-final-regressions.log`。新用例含健康改名不扩展查询、合法挂载保留身份、非法嵌套/租户/标记回滚、重复与旧缓存批次、A资源/其他部门/自动恢复读者重叠及发布等待、fenced拒绝、既有部门级门禁影响范围。
- **真实MySQL 8.0.46多连接测试1 passed**：专用`--network none`、无宿主目录挂载/无发布端口的临时容器；使用实际共享屏障函数编译的SQL，A资源和B部门模拟写事务同时进入外部I/O等待且各自行提交，第三连接发布UPDATE在读者持锁时等待超时，释放后发布成功。日志`/private/tmp/f086-mysql-publication-barrier.log`；容器已停止并自动删除。此项验证数据库锁与独立资源行，不冒充真实FGA/HTTP全链路。
- 复跑方法：`F086_TEST_MYSQL_CONTAINER=codex-f086-lock-test-<专用后缀> config=<测试配置> PYTHONPATH=. python -m pytest test/permission/test_f086_catalog_read_barrier_mysql.py`，cwd=src/backend，容器需专用空库f086_lock_test；该测试会创建/删除仅该容器中的三张测试表。未配置专用容器时仅此集成测试skip，不计通过。
- 扩展6组权限/SSO测试的失败集合对比：修正前 **442 passed / 7 failed**，修正后（未加最后健康改名用例的那轮）**455 passed / 7 failed / 1 skipped**。7个失败nodeid完全相同，新增失败集合为空。日志`/private/tmp/f086-r123-baseline-regressions.log`与`/private/tmp/f086-r123-regressions.log`；跳过项是随后单独实跑通过的MySQL测试。
- 扩展范围既有失败：`test_f048_grant_api.py`的`test_resource_context_models_roster_and_self_summary_contract`、`test_protected_mutation_and_stale_cursor_preserve_business_codes`、`test_mode_draft_and_apply_only_send_server_draft_identity`（permission_runtime测试上下文缺失）；`test_sso_login_sync_service.py`的`TestDepartmentAdminFgaReconcile::{test_empty_admin_list_removes_fga_admin_on_sso_member_dept,test_leader_dept_grants_admin_tuple}`、`TestGuestMembershipReconcile::test_guest_plus_real_vacates_guest`、`TestGuestFallbackPlacement::test_disabled_user_skips_guest_reconcile`（已有测试桩/数据库上下文缺失）。未修改业务逻辑规避这些既有失败。
- 基线对照使用原有干净工作树`cofco-1111-department-recovery`的4557e68595；已验证其所有backend Python源码与a58ab1c2cb完全相同，两个工作树均以各自cwd运行，没有stash/reset/生产连接。新建a58基线工作树请求被自动审批拒绝后，改用上述已核对的现有基线完成对照。
- 本次新增Python lint通过，共享文件相对基线无新增lint；架构守卫无VIOLATION，diff检查通过。配置、模型、alembic、依赖锁、前端均未改。QA为28项八列。

DM兼容证据为锁定wheel的真实编译器源码（2.0.12忽略read=True）及官方SHARE锁语义，加确定性SQL调度；**未运行真实DM、多节点Redis/FGA、普通用户完整部署E2E**。上线前按Q25核实DM应用用户共享锁权限及默认读已提交隔离配置，并完成中央多连接验收，不能以MySQL结果代替。成员变更仍按原部门级门禁关闭同部门上下文，Q28明确验收；无生产速度承诺。

## 交付分支调整验证（2026-11-16）

按用户要求仅调整发布分支，不变更修复逻辑。cofco-1111使用标准revert提交 `063a574764a5af08adf31fd78a77d160a0f6e3e2` 撤销原修复 `4557e685951bbcfd69be84a7ba0e1188fbb612da`，整棵Git tree与原修复父提交 `00720a9c697f55f19086fc7c7ad111986a95f4ac` 完全相同；中粮定制/Celery/单head/部门空间管理员回归 **57 passed**（日志 `/private/tmp/f086-revert-cofco1111.log`）。

远端原无cofco-1118，从上述revert基线建立 `feat/cofco-1118-3.0.0-beta1`，以 `cherry-pick -x` 单独迁入修复（`8e08cf141d`）；迁入后完整tree与原修复相同，再仅更新交付文档中的目标分支及本验证记录。可执行源码、脚本及测试与原修复一致，配置/模型/schema/依赖锁/前端未变，无额外功能混入。重新执行原369项范围：**369 passed，无skip**，971条现有warning，日志 `/private/tmp/f086-cofco1118-migration.log`；`alembic heads`仍仅 `f076_subject_id_search_indexes (head)`，QA清单仍24项八列，客户端三语无重复key。

下文保留原开发阶段基线与验证记录。实际交付使用cofco-1118及[QA-IMPACT.md](QA-IMPACT.md)；真实双库、多节点与生产验收边界不变。Git revert只撤销源码，不撤销客户已经执行的数据修复或运行中的镜像。

## 原开发验证记录

2026-11-16。基线：origin/feat/cofco-1111-3.0.0-beta1 / 00720a9c697f55f19086fc7c7ad111986a95f4ac；独立开发分支codex/cofco-1111-department-recovery。未操作客户生产数据、未改旧F078工作树/交付包，未部署。

## 结果

- 推送前最终回归合计 **369 passed，无skip**：特性/同步/上下文/锁/共享resource投影/仓储/CLI **290项**（595条现有warning，`/private/tmp/f086-push-validation.log`）；中粮定制/Celery/单迁移head/部门空间管理员 **57项**（7条warning，`/private/tmp/f086-cofco-regression.log`）；中粮Owner/空间管理员API/资源创建上下文/配置透传 **22项**（383条warning，`/private/tmp/f086-normal-flow-regression.log`）。这些范围不重叠，warning主要为弃用及SQLModel execute提示。
- 健康CURRENT绑定检查使用薄字段主键元数据。补充实际SQL UOW回归，证明正常新投影不调用恢复模型发现、不套恢复写限速；失败恢复仍启用完整校验和恢复写gate。重复定向测试不叠加计数。
- 实际Worker模块与Celery registry导入冒烟输出 `WORKER_TASKS_REGISTERED`。未启动真实Beat/任务执行。
- 本地HTTP3项真实HMAC测试通过；数据库、DAO/FGA传输注入，不冒充完整部署E2E。完整状态PARTIAL，见e2e-checklist.md。
- 所有新增Python文件ruff check通过；相对基线没有新增lint问题。受改共享文件原有115条lint（中文标点/re-export等）保留，没有为本次屏蔽规则。
- arch-guard无VIOLATION。settings.py的硬编码敏感信息WARNING来自原有JWT默认字段，本次未增加密钥。git diff --check通过。
- schema模型与alembic未改，无新表/列/索引/数据库状态；变更仅添加专用operation_type和既有AuditLog事件。
- `alembic heads`仅 `f076_subject_id_search_indexes (head)`；配置、授权模型、依赖锁及前端对比基线均未改，无文件删除。QA重点交接见[QA-IMPACT.md](QA-IMPACT.md)，24项八列表格已核对。

## 核心证据

| 风险/AC | 证据文件（src/backend/test下） |
| --- | --- |
| AC-01/02/03 同步与并发窗口 | org_sync/test_f086_sync_recovery.py：恢复前置、真实parent子树回滚、refresh不覆盖后继、锁内ts不倒退 |
| AC-03/04/05/08 Owner与ledger | department/test_f086_department_recovery.py：全拥有域、原效果边界、真实SQL事务、FGA成功SQL失败、历史分裂及正常归档原流程 |
| AC-06/08 维护隔离 | permission/test_f086_projection_recovery.py：COMMITTED缺AFTER不重写，维护type先于空tuple/FINALIZED快返拒绝 |
| AC-07 调度 | department/test_f086_recovery_worker.py：实际配置及custom schedule优先；另有真实task import冒烟 |
| AC-09/10/11/12 当前计划与IAM | permission/test_f086_department_batch_repair.py、test_f086_iam_archive_repair.py：依赖顺序、可选IAM、删除证明、空/有成员归档、孤儿path叶子保护 |
| AC-13/14/15/18 重入与停服 | permission/test_f086_current_department_repair_repository.py、test_f086_department_recovery_timeout_hotfix.py：共享sealed记录、原子清理、未知FGA、完成项不重复写及轻量末核验 |
| AC-16/17 查询边界 | permission/test_f086_department_batch_scope.py、test_f086_execution_context.py：禁止全Store、无关成员、健康后代扩展；真实捕获SQL tenant谓词/四状态等值/累计32边界 |
| AC-18/20 CLI | permission/test_f086_reconciliation_cli.py：默认仅database初始化、不检查写marker、已有备份确认无需额外JSON |
| AC-19 权限不扩围 | department/test_permission_context.py、e2e/test_e2e_department_recovery.py及共享F048回归；真实普通用户业务验收仍待执行 |
| AC-17/20/21 诊断 | permission/test_f086_projection_alerts.py、test_f086_query_statistics.py：机器字段、脱敏、请求失效祖先定位、SQL与限速成本 |

解释：SQLShape/SQLite通过不能证明DM优化器采用生产索引或十分钟修复目标。未提供隔离MySQL/DM/OpenFGA/Redis环境配置，未进行真实双库锁/执行计划、多节点、模型发布或普通用户生产验收；没有用skip冒充通过。

## 实现边界

正常归档保持原业务投影与后续清理职责，PROJECTED不是完整清理证明；自动恢复必须另外证明清理义务已完成，否则转人工。原FAILED自动复用已有持久门禁，不额外制造自动T1；人工业务重挂/归档保留T1/T2。与设计R1相比的细化已写入design R2及tasks，不改变已确认的自动/手动边界。

仅提供正向修复/续跑，不提供在线inverse或整库还原。备份是否可恢复由DBA验证，程序不伪造恢复演练。日志规则仍需由客户部署配置。
