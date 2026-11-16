# F086 实施任务与验收边界

| 文档 | 状态 | 依据 |
| --- | --- | --- |
| spec.md | ✅ R1已确认；R2补用户要求的AC-21 | 2026-11-16 |
| design.md | ✅ R1已确认；R2同步实际实现 | 2026-11-16 |
| test-cases.md | ✅ 八列21项 | 真实QA仍待执行 |
| tasks.md | ✅ 已拆解与执行 | 按实际文件回写 |

依赖沿前项产出的协议逐项推进；表中共享文件为增量修改，不扩大resource授权恢复资格。路径相对src/backend，features路径相对仓库根。

- [x] T-01 [基础设施] `test/permission/test_f086_execution_context.py`：外层bypass、真实SQL租户谓词、session还原、失租。覆盖 AC: AC-08, AC-17, AC-19。
- [x] T-02 [基础设施] `bisheng/core/context/tenant.py; bisheng/permission/domain/repositories/catalog_repository.py`：精确租户及借用UOW。
- [x] T-03 [基础设施] `bisheng/core/lock/token_safe_redis_lock.py; bisheng/department/domain/services/department_projection_scope.py`：token核验与部门scope绑定。
- [x] T-04 [后端 Domain] `test/permission/test_f086_projection_recovery.py`：专用原意图恢复及维护type拒绝。覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-08。
- [x] T-05 [后端 Domain] `bisheng/permission/domain/repositories/projection_repository.py; bisheng/permission/domain/services/projection_service.py`：单状态ID探测、同UOW ledger及专用恢复。
- [x] T-06 [后端 Domain] `test/department/test_f086_department_recovery.py`：真实SQLite/FGA成功SQL失败、历史分裂收口、正常归档不回归。覆盖 AC: AC-03, AC-04, AC-05, AC-08, AC-19。
- [x] T-07 [后端 Domain] `bisheng/department/domain/services/department_projection_recovery.py; bisheng/department/domain/services/department_recovery_facts.py`：Owner原意图/正常执行分开验证，共用执行权和事务。
- [x] T-08 [后端 API] `bisheng/api/services/department_recovery_runtime.py; bisheng/api/services/f048_permission_runtime.py`：注入工厂/定点dispatch，不使domain依赖Worker。
- [x] T-09 [后端 Domain] `test/org_sync/test_f086_sync_recovery.py`：旧消息恢复前置、真实子树路径与回滚。覆盖 AC: AC-01, AC-02, AC-03。
- [x] T-10 [后端 Domain] `bisheng/sso_sync/domain/services/departments_sync_service.py; bisheng/department/domain/services/department_service.py`：时间戳前恢复、批量绑定元数据、父子图path。
- [x] T-11 [Worker] `test/department/test_f086_recovery_worker.py`：实际默认调度配置及健康/异常候选边界，实际Worker导入另有冒烟。覆盖 AC: AC-07, AC-08, AC-16, AC-17。
- [x] T-12 [基础设施] `bisheng/core/config/settings.py; bisheng/worker/__init__.py`：有界恢复配置与真实task导入。
- [x] T-13 [Worker] `bisheng/worker/department/projection_recovery.py`：tenant_id由Celery headers/任务参数进入exact ContextVar并还原；周期跨租户枚举局部bypass，游标/退避/限额。
- [x] T-14 [后端 Domain] `test/permission/test_f086_department_batch_repair.py; test/permission/test_f086_iam_archive_repair.py`：当前计划、依赖、可选定点IAM、归档及关联回滚。覆盖 AC: AC-09, AC-10, AC-11, AC-12, AC-19。
- [x] T-15 [后端 Domain] `bisheng/permission/domain/services/current_department_repair.py; bisheng/permission/application/current_department_repair.py`：当前目标及T1/T2重入、0差异、严格确认。
- [x] T-16 [后端 Domain] `bisheng/permission/domain/repositories/current_department_repair_repository.py; bisheng/permission/application/department_batch_repair.py`：封存、共享审计、来源superseded及依赖排序。
- [x] T-17 [后端 Domain] `bisheng/department/domain/repositories/projection_recovery_repository.py; bisheng/department/domain/repositories/current_repair_repository.py`：薄字段、祖先、成员与生命周期CAS。
- [x] T-18 [后端 Domain] `bisheng/department/domain/repositories/iam_oneoff_repository.py; bisheng/department/domain/services/iam_oneoff_repair.py`：本地身份、真实叶子、重挂证明与CAS。
- [x] T-19 [后端 Domain] `bisheng/department/domain/repositories/iam_archive_repository.py; bisheng/department/domain/services/iam_archive_repair.py`：精确删除证明、关联before及严格清理。
- [x] T-20 [后端 Domain] `bisheng/role/domain/repositories/department_retirement_repository.py; bisheng/department/domain/services/current_projection_repair.py`：Role Owner清理/保护与当前业务证明。
- [x] T-21 [后端 API] `bisheng/api/services/current_department_repair_runtime.py; bisheng/api/services/iam_department_repair_runtime.py`：常驻安全的ContextVar UOW/proof及可选IAM组合。
- [x] T-22 [后端 API] `bisheng/api/services/department_reconciliation_runtime.py; bisheng/api/services/department_business_scan.py`：定点FGA、预算、完成项证明与SQL预筛。
- [x] T-23 [基础设施] `bisheng/permission/application/department_recovery_runtime.py; bisheng/permission/application/department_recovery_model.py`：限定基础设施、只读当前模型、禁止中途repin。
- [x] T-24 [基础设施] `bisheng/permission/application/department_recovery.py; bisheng/permission/application/department_recovery_fga.py`：公开协议和串行限速；resource合同不变。
- [x] T-25 [后端 Domain] `test/permission/test_f086_current_department_repair_repository.py; test/permission/test_f086_department_recovery_timeout_hotfix.py`：共享证据、失效/重入、四状态累计边界、停服续跑。覆盖 AC: AC-13, AC-14, AC-15, AC-17, AC-18。
- [x] T-26 [后端 API] `test/permission/test_f086_department_batch_scope.py; test/permission/test_f086_reconciliation_cli.py`：只读初始化、无全Store/成员导出、证明缓存及备份确认。覆盖 AC: AC-09, AC-13, AC-16, AC-18, AC-20。
- [x] T-27 [后端 API] `scripts/reconcile_department_projections.py; scripts/iam_department_lookup.py`：默认scan、显式apply、精确确认及凭据脱敏。
- [x] T-28 [后端 API] `scripts/department_batch_io.py; scripts/current_department_repair_io.py`：不可变JSONL与before、窗口/备份引用。
- [x] T-29 [后端 API] `scripts/f048_department_recovery_io.py; scripts/README.md`：受控证据文件及运维入口。
- [x] T-30 [基础设施] `bisheng/core/context/manager.py; bisheng/core/database/query_statistics.py`：只初始化所需上下文与ContextVar SQL统计。
- [x] T-31 [后端 Domain] `test/permission/test_f086_projection_alerts.py; test/permission/test_f086_query_statistics.py`：告警白名单/原因/成员计数/请求拒绝及真实SQL耗时。覆盖 AC: AC-17, AC-20, AC-21。
- [x] T-32 [后端 Domain] `bisheng/permission/domain/services/projection_diagnostics.py; bisheng/department/domain/services/permission_context.py`：结构化告警与原拒绝点诊断，不加鉴权查询。
- [x] T-33 [后端 API] `test/e2e/test_e2e_department_recovery.py; features/v3.0.0-beta1/086-cofco-department-projection-recovery/e2e-checklist.md`：真实HMAC HTTP入口三项本地通过；完整部署/普通用户验收另列待执行。覆盖 AC: AC-01, AC-03, AC-07, AC-19, AC-20。
- [x] T-34 [后端 API] `features/v3.0.0-beta1/086-cofco-department-projection-recovery/OPERATIONS.md; features/v3.0.0-beta1/086-cofco-department-projection-recovery/ALERTING.md`：执行、续跑、清理与告警配置。
- [x] T-35 [后端 API] `features/v3.0.0-beta1/086-cofco-department-projection-recovery/validation.md; features/v3.0.0-beta1/086-cofco-department-projection-recovery/code-review.md`：定向/共享资源回归、架构与特性自检，说明真实环境限制。

## 实施细化与审查

- Test-first计划细化为现有工具回归迁入+新故障测试；基础隔离和专用恢复实际观察到缺入口红灯后转绿，SSO/Worker接线与迁入回归在同一波增量落地，不把目录迁移造成的收集失败当业务缺陷证明。
- 基础设施/FGA model发现移入permission.application；测试不放在core的领域依赖守卫目录；每项≤2文件，额外支持代码已拆为T-17至T-30。
- 原FAILED自动恢复复用已有持久门禁，切换和收口在一个UOW内，不额外持久自动T1；人工仍双阶段。正常同步归档保持原业务delta/后续清理流程；后台不能从父子投影已完成推断成员/角色清理完成。见design R2。
- 业务库无tenant列的关联按已锁定D与带tenant条件的D子查询约束；没有新增schema。
- 新增日志只采集原有事实，不增加鉴权查询或授权旁路。
- 推送前补充正常业务与恢复环境/限速隔离回归：正常新操作使用SQL Catalog及运行时pin，不逐操作发现模型、不套恢复写限速；失败恢复保留完整校验与限速。

## 评审修正（R3，用户已授权）

- [x] T-38 统一Catalog共享读屏障：MySQL行共享、DM两张配置表共享；普通资源写前只读校验复用，发布写锁仍有效。
- [x] T-39 将SSO路径维护收敛到SyncedDepartmentTreeRepository，合法挂载身份保留，当前父链核实及真实后代更新；健康改名不展开扫描。
- [x] T-40 正常同步/旧快照/合法与非法挂载/回滚、确定性并发、隔离MySQL多连接及部门门禁范围回归；测试和实机边界写入validation。
- [x] T-41 同步设计、QA Q25–Q28、运维和评审记录，保留真实DM、多节点、端到端待验收项。

## 独立部署验收状态

- [ ] T-36 在隔离MySQL/DM+FGA+Redis部署验证锁、绑定执行计划、LOB、网络未知结果及多节点竞争。
- [ ] T-37 启动同版API/Worker/Beat，验证周期实际执行与普通用户允许/拒绝，再由发布流程决定推送/合入/部署。

这些验收不能用本地SQLite、HTTP依赖注入或task注册代替；不将skip记为通过。详见validation.md。
