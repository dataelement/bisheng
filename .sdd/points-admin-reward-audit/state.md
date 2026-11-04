# PAR-LOG 积分规则修改留痕

- 路径：完整 SDD。当前阶段：研发完成，待独立验收。
- 需求：`.sdd/points-admin-reward-audit/requirements.html` 版本 1.1。2026-11-04 用户回复「确认」。版本 1.0 只覆盖管理员奖励，该确认已失效。
- 设计：`.sdd/points-admin-reward-audit/design.html` 版本 0.10。同一次「确认」一并确认。
- 研发用例：`.sdd/points-admin-reward-audit/test-cases.html` 版本 0.10。定义已对齐 1.1；对应 mock 测试已执行，真实库验收未执行。
- 代码基线：分支工作区基于 `404fa3e3b`，改动未提交。业务文件：`src/backend/bisheng/points/domain/services/points_rule_service.py`、`src/backend/bisheng/common/errcode/points.py`。测试：`src/backend/test/points/test_points_rule_update_audit.py`，并让 `test_points_rule_display_name.py` 的假会话带上 `add` 和 `user_id`。
- 实现：`PointsRuleService.update_rule` 对获取、扣减、管理员奖励的实际字段变化，在同一会话 `add` 一条 `audit_log`（action `points.rule.update`）后只 `commit` 一次。无变化不 `save_rule`、不 `commit`。提交失败时 `rollback`、写回修改前字段，并抛 `PointsRuleAuditError`（18209，「保存失败，积分规则未更改，请重试」）。成功日志 `points.rule.updated`，失败日志 `points.rule.update_failed`。说明文案 `update_copies` 和 `create_rule` 未接入这条审计。未改 `_UI_VISIBLE_V2_ACTIONS`，未写 `user_point_log`，无 DDL。
- 开发验证（2026-11-04，本机 mock，未连 171 MySQL，未起服务）：`cd src/backend && uv run pytest test/points/test_points_rule_update_audit.py test/points/test_points_rule_display_name.py -q` → 21 passed。`bash scripts/arch-guard.sh` 对上述后端文件退出码 0。`ruff format` 已跑。`ruff check` 对这几个文件仍报改动前就有的中文标点 RUF001/RUF002/RUF003；本次用户可见句「保存失败，积分规则未更改，请重试」按原文保留，并在新增行加了 `noqa: RUF001`。
- 代码审核：同一实现上下文复核，不是另一岗位独立审核。未发现阻塞项。真实事务原子性、并发后写覆盖、超时后的库状态未验证。
- 2026-11-04 用户要求平台「系统操作」展示这些审计行，并展示变更明细。`points.rule.update` 已加入 `_UI_VISIBLE_V2_ACTIONS` 和前端模块/操作筛选。备注列按 `metadata.changes` 显示字段与改前改后。积分管理「操作记录」仍不展示。已有行不回写 `note`，页面读取时格式化。
- 展示验证：`uv run pytest test/points/test_points_rule_update_audit.py -q` → 14 passed。`npx vitest run src/test/logActions.test.ts` → 7 passed。arch-guard 通过。未重启 7860，未打开页面。
- 测试岗位验收状态：未开始，未执行。需要在真实库核对：一次保存后 `point_rule` 新值与恰好一条 `audit_log` 同事务出现；提交失败时两者都保持旧状态；无变化不新增审计且 `update_time` 不动；获取、扣减、管理员奖励都覆盖；说明文案不产生 `points.rule.update`。系统操作页能看到上述行，备注含变更明细。
