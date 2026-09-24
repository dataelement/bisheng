# Verification: 发布申请提交性能优化（第一阶段）

**Feature ID**: `054-file-publish-submit-performance`  
**Date**: 2026-07-14  
**结论**: 第一阶段代码和专项自动化验收通过；真实 DM8 迁移、生产 Celery 联调及接口耗时对比仍需在部署环境完成。

## 1. 自动化验证

| 验证项 | 状态 | 证据 |
|--------|------|------|
| 通知 outbox、通知 Service/Worker、批量任务及原业务 outbox 回归 | PASS | `.venv/bin/python -m pytest test/approval/test_approval_notification_outbox_repository.py test/approval/test_approval_notification_service.py test/approval/test_approval_notification_worker.py test/approval/test_approval_gate.py test/approval/test_approval_outbox_service.py test/approval/test_approval_worker_tasks.py -q` → `48 passed` |
| 定向目标校验 | PASS | `.venv/bin/python -m pytest test/knowledge/test_knowledge_version_service_similar_scan.py -q -k 'get_shougang_publish_version_target'` → `7 passed, 19 deselected` |
| 发布提交异步通知与性能日志 | PASS | 聚焦 5 个发布提交场景 → `5 passed, 67 deselected` |
| 新增文件完整 Ruff | PASS | 模型、Repository、迁移、Worker 与新增测试执行 `ruff check` → `All checks passed` |
| 改动文件关键 Ruff 规则 | PASS | `ruff check --select E4,E7,E9,F ...` → `All checks passed`；保留 `knowledge_version_service.py` 原有 import 顺序，未为 I001 扩大格式化差异 |
| Python 编译与差异检查 | PASS | `compileall -q ...`、`git diff --check` → exit code 0 |
| Alembic head | PASS | `.venv/bin/alembic heads` → `f058_approval_notification_outbox (head)` |
| Beat 配置 | PASS | 配置读取结果为 `bisheng.worker.approval.notification_tasks.dispatch_approval_notifications 30.0` |
| 审批目录全量基线 | FAIL（既有） | `pytest test/approval -q --tb=short` → `161 passed, 15 failed`；失败集中于既有 Admin Service API 缺失、测试 DB/await mock、tenant fixture、既有字段漂移等，与本次改动链路无关 |

## 2. Acceptance Criteria

| Requirement | 状态 | 证据与说明 |
|-------------|------|------------|
| REQ-001 | PASS | 成功和失败分段日志测试通过；包含基础校验、目标校验、审批创建、通知入队、总耗时及失败阶段 |
| REQ-002 | PASS | 文档/独立文件合法目标与跨空间、失败状态、目录、版本链非法目标测试通过；提交不调用空关键词全量搜索 |
| REQ-003 | PASS | 发布提交不再构造或调用目标文件 `view_file`；登录、源空间 `publish_file`、目标空间 `view_space` 与可选目录 `view_folder` 保留 |
| REQ-004 | PASS | 独立通知 outbox 幂等、成功短路、失败重试、锁、跨租户 Beat 补偿及原消息参数兼容测试通过 |
| REQ-005 | PASS | 首节点审批任务单事务批量创建、输入顺序和异常回滚测试通过 |
| REQ-006 | PASS | API 响应结构未改；审批实例和任务仍同步落库；原业务 `ApprovalOutbox` 回归通过 |

## 3. 未执行项

- `MANUAL_REQUIRED`：在可回滚 MySQL 和 Linux DM8 环境执行 F058 upgrade → downgrade → upgrade。
- `MANUAL_REQUIRED`：启动真实 Worker、Beat 和消息中心，验证即时投递、30 秒补偿及失败恢复。
- `MANUAL_REQUIRED`：部署后采集同一数据规模下提交接口优化前后 P50/P95，并根据新增阶段日志判断是否进入第二阶段 OpenFGA 优化。
- 未运行 `alembic upgrade head`，避免未经单独确认修改当前数据库。

## 4. 基线失败说明

- 首钢审批文件全量结果为 `69 passed, 3 failed`；3 个失败分别是两个既有 `auto_tag_library_ids` 参数漂移和一个既有 `primary_knowledge_file_id` 测试数据缺失。
- 审批目录其余 12 个失败不触达本次新增通知 outbox、定向目标校验或批量任务写入路径。
- 本次不修改这些范围外测试或生产逻辑，避免扩大第一阶段边界。

## 5. 已知交付限制

- 审批实例/任务与通知 outbox 由两个连续事务提交，并非同一数据库事务。审批事实提交后、通知 outbox 创建前若发生数据库故障，可能形成有审批但无初始提醒的孤儿窗口。
- 通知为 at-least-once；消息已发送但成功状态未落库时，重试可能产生重复提醒。
