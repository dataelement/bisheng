# Work120 申请加入审批假待审修复

2026-11-03；直接基于 `origin/feat/bisheng-work-120-main@2169eeb538cb7c5f97a4d055713c241d42ade9fb` 开发，分支 `codex/work120-join-approval-20261103`。未移植此前发布线修复提交。没有数据库迁移、部署或109业务数据操作。

## 问题与修复

历史审批已通过但授权执行失败时，同一申请人重新申请命中旧 execute_failed 实例；原代码返回 pending，但没有新审批任务，并把成员写为 PENDING，导致界面一直显示申请中。

- execute_failed 继续参与去重，再申请明确返回18120：请管理员处理或取消旧异常后再申请。不新建第二个实例、任务或outbox，也不重试旧授权。
- 详情和广场仅对无当前可见权限的PENDING成员核对最新在途审批，执行失败时使用既有not_subscribed/is_pending=false。读取不写成员、权限或审批状态。
- 正常pending/exception、现有权限判断、分页和Work120已有状态优先级保持不变。取消旧单后不再命中在途去重，用户可以走正常新申请流程。
- 新增审批域内只读状态仓储与应用端口，不改变公共租户模块。端口按申请人验证租户绑定已有ContextVar，退出及异常均恢复；每100个业务键一次查询，只读取业务键和状态，不读取审批快照正文。
- 错误18120补齐共享中/英/日源文案及两端生成文件。没有引入该分支原本不存在的其它错误码或功能。

## 验证与自审

```text
PYTHONPATH=. <existing-python3.11> -m pytest \
  test/approval/test_failed_join_requests.py \
  test/knowledge/test_failed_join_display.py \
  test/knowledge/test_square_revoked_membership.py \
  test/approval/test_approval_exception_service.py \
  test/approval/test_channel_subscription_approval_integration.py -q
```

43 passed。覆盖四场景执行失败重复申请、正常状态、最新在途选择、真实隔离SQL的租户/用户/场景过滤、取消后不再去重、100键分批及上下文异常恢复、详情/广场一致性、可见空间原状态保留、失败申请不写成员或授权。SQLite用例仅创建自身表；MySQL/DM8实测及109部署验收未执行。

Ruff、架构守卫、git diff --check、文案生成一致性及check-i18n通过。按hotfix自审清单检查边界、租户、并发、信息泄漏、测试和文档：无新增授权路径或写入竞态；响应不暴露SQL、内部异常或审批快照。原始日志保存在 `/private/tmp/work120-join-approval-20261103/`。

本次前端仅修改文案JSON，无TS/UI逻辑改动；未重新安装依赖或运行全仓前端类型检查。上线后仍需普通用户实测18120显示，并由管理员通过既有异常入口处理历史单；本轮未自动取消或恢复109的实例16/异常1。
