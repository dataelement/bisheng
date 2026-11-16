# F086 部门投影故障分析与范围确认

日期：2026-11-16。目标：origin/feat/cofco-1111-3.0.0-beta1，基线00720a9c697f55f19086fc7c7ad111986a95f4ac。独立分支codex/cofco-1111-department-recovery。目标分支F078已用于其他功能，本任务用F086，旧交付包不覆盖。

## 已确认范围

用户已确认：自动恢复仅处理业务树合法、当前绑定/版本未变且目标仍可证明的投影失败；模型变化、父级失效、IAM重挂/归档由默认dry-run的运维脚本生成明确计划后执行。不新增表，沿用前期不新增schema、按当前业务状态/当前生效模型核对、保留权限边界及串行限速的要求。

## 已核对的代码路径

1. department_service.py::aupsert_synced_department在SQL事务内保存parent/path、last_sync_ts及投影绑定，提交后_execute_department_projection写FGA；FGA失败并不会回退已提交的同步时间戳。departments_sync_service.py::_apply_upsert先做OrgSyncTsGuard，SKIP_TS立即返回。同一消息再次送达可能因此无法触发投影恢复；新时间戳但parent不变时也不会新建拓扑投影。
2. _resume_department_projection_if_needed只处理PROJECTING；SqlDepartmentProjectionScope.bind要求CURRENT，scope.reserve只接受原绑定PROJECTING；ProjectionService._resume拒绝FAILED_CLOSED，通用失败恢复仅resource scope。故部门FAILED不是靠重推即可恢复。
3. ProjectionService._finalize先提交业务scope.finalize，再将operation从COMMITTED改FINALIZED，两步存在中断窗口；已有scope.finalize对CURRENT/target_version幂等，但只按PROJECTING触发的部门恢复遗漏CURRENT+COMMITTED收口。
4. 同步aupsert_synced_department仅为本行重新计算path，没有更新后代。普通移动路径另有批量更新，不能证明SSO已覆盖。因此父级重挂后部分子部门未再次同步时可能留下陈旧path。
5. Worker已注册的stale_parent_projections针对知识文件资源，不是部门；CeleryConf默认schedule和Worker入口中没有部门投影定时恢复。OrgReconcileService定义也不等于已接线；sso_realtime种子按设计跳过，不能将它当自动修复保障。
6. 父级不存在/软删除时DeptUpsertService拒绝upsert，不按名称或旧记录猜新父级。既有SSO remove及full_snapshot走业务归档/清理；源端在场的子部门不能凭父级归档推导也应删除，历史孤儿由手动校对解决。

## 基线验证

本地原有部门scope/projection、projection_service和org_sync reconciler定向回归：53 passed。SQLite/fake外部服务，不证明DM执行计划、真实FGA或生产恢复成功。复用现有Python环境，测试使用/private/tmp临时空配置；未改生产或其他工作树。

## 分层实施方向

- 新写入：同步重试在时间戳短路前处理原绑定恢复；合法部门重挂时保持子树path同事务一致；收口操作保持幂等。
- 自动恢复：后台任务实际注册并调度，有界候选、退避/频率限制、跨进程互斥、租户上下文、原目标证明与执行进度；不放宽请求门禁。
- 手动校对：长期维护CLI，默认dry-run、明确目标/差异/影响、当前事实及当前模型、按依赖执行和同计划续跑；SQL无法核实的候选才定点问IAM；不搬临时包的基线硬门禁。
- 性能：保留原v6的教训，禁止Store遍历和无关全量查询，避开已复现的多状态IN+排序分页整行探测，祖先批量读取、阶段耗时及查询计数可观测；停服加速与在线自动恢复分开。

## 当前阶段

Discovery范围已由用户确认；spec R1已确认，design R1待确认。自动恢复新增跨模块契约，按AGENTS.md及SDD-Guide需要规格、设计确认后再编码。本文件不宣称已修复或已合入cofco-1111。
