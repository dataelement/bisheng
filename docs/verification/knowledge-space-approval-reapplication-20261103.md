# 知识空间历史执行失败单误报待审修复

日期：2026-11-03。修复分支 `codex/knowledge-approval-failed-20261103`，初始基于发布线 `origin/feat/3.0.0@234c154b3a`。按 hotfix 流程处理既有错误状态；不改成功响应字段、知识空间状态枚举、审批路由、权限或数据库结构。提交交付按发布线优先，再定向集成到最新 Work120；实际提交以 Git 历史为准。本记录不表示已部署，未修改 109 业务数据。

## 原因与修复行为

109 DSH 的 user10/dsh-sara5 对知识空间77的旧审批实例16已被审批人通过，但业务执行失败，异常1未处理。重新申请按相同业务键命中实例16，旧逻辑把 execute_failed 映射成 pending，未创建任务，却写入 PENDING 成员行并让界面显示申请中。

- 失败单继续参与去重；再次申请返回 18120，明确说明旧申请已通过但执行失败，需要管理员处理或取消异常。不会创建第二个实例、任务、outbox，或重复执行旧授权。
- 正常 pending 和 exception 的既有去重行为保留。管理员通过原异常管理入口取消旧单后，新申请可正常创建审批实例和待办。
- 空间详情和广场只对无当前有效可见权限的 PENDING 状态补查真实审批状态；命中最新在途执行失败单时，使用既有 not_subscribed、is_pending=false，按钮不再误显示申请中。再次点击申请会显示上述具体错误，不会显示申请提交成功。
- 当前直接或继承授权仍显示已加入；创建者不查失败申请。不修改成员表、审批历史或权限投影。
- 查询固定申请人的验证租户、用户、场景和业务键，按100个键分批，按实例ID倒序与审批入口的去重选择保持一致；不引入逐条查询或新表。读取失败会传播，不伪装正常状态。
- 更新了共享错误码源文案和两端生成文件（中/英/日），以及审批模块指引、错误码登记。

保留失败单是为了防止旧 outbox 可被管理员重试时又产生第二次授权。不能直接把 execute_failed 从全场景去重集合中删除，也不能在用户刷新详情时自动恢复已撤销的授权。若产品未来需要用户自助结束失败申请，应单独设计取消/执行竞态保护后再开放。

## 验证

使用既有 Python 3.11 独立解释器依赖，不安装或改动其他工作区依赖；测试替换外部服务或使用隔离 SQLite。没有以这些结果替代真实 MySQL/DM8 或109部署验证。

```text
cd src/backend
PYTHONPATH=. <existing-python3.11> -m pytest \
  test/approval/test_failed_request_reapplication.py \
  test/approval/test_approval_gate.py \
  test/approval/test_approval_exception_service.py \
  test/approval/test_channel_subscription_approval_integration.py \
  test/approval/test_knowledge_space_subscription_approval_integration.py \
  test/knowledge/test_square_revoked_membership.py \
  test/knowledge/test_knowledge_space_info_optimization.py -q
```

结果：107 passed。包含四个审批场景的失败单重复申请、正常待审去重、真实隔离SQL的用户/租户/场景过滤、批量查询上限、新待审覆盖旧失败单、取消后新建审批任务、知识空间详情/广场一致性、失败申请不写成员/权限。

未修改发布线基线相同选择为88 passed/5 failed：两个审批测试缺少 outbox/action_log/审计替身，三个知识空间测试缺少创建者user_id。已补齐这些受影响路径的测试设施，并保留原断言和增加正常 outbox 调度断言，最终组合运行全部通过。租户事件测试在结束时卸载自己注册的监听器并恢复 ContextVar，避免污染其它用例。

- Ruff format/check：全部变更Python文件通过。
- 架构守卫与 git diff --check：通过。
- 共享文案生成一致性和 check-i18n：通过。
- 完整 pnpm lint：通过。
- 完整 pnpm typecheck：未通过，停在平台22项既有图标导出/依赖版本错误。使用同样依赖的未修改发布线基线完全相同22项，无新增类型错误；下游类型检查因串行脚本中止未执行。未改动依赖或抑制类型错误。

原始测试和质量日志：`/private/tmp/dsh-space77-approval-1103/`，以 `regression-verified.log`、`frontend-lint.log`、`frontend-typecheck.log` 和 `frontend-typecheck-baseline.log` 为最终证据。初次失败及其基线对照日志保留。

## 自审（sdd-code-review hotfix 清单）

边界、权限/租户、并发、信息泄漏、测试、风格、文档七维度检查通过；保留前端全量类型检查基线限制。没有新增审批写入并发路径；旧单仍受同一去重保护，异常重试/取消沿用既有入口。无SQL、底层异常、原文、凭据或其他租户信息进入18120响应。

上线后需另行验收：普通申请人刷新77预览不再显示假申请中；点击申请收到18120；管理员处理或取消旧异常后再申请可创建新待办。当前109的实例16/异常1仍保持原状，本轮没有取消、重试或补授权限。
