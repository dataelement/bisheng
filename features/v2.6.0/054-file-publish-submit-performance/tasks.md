# 任务拆分 Tasks: 发布申请提交性能优化（第一阶段）

## 阅读摘要
- 本文档按 Test-First 顺序执行 F054。
- 只实现发布申请第一阶段；发现需要修改响应协议、权限规则或审批状态时必须先更新规格并重新确认。
- 每个任务完成后记录实际验证证据；最终生成 `verification.md` 和 `retrospective.md`。

## 元信息 Metadata
- Feature ID: `054-file-publish-submit-performance`
- Status: `completed`
- Related requirements: `features/v2.6.0/054-file-publish-submit-performance/requirements.md`
- Related design: `features/v2.6.0/054-file-publish-submit-performance/design.md`
- Created: `2026-07-14`
- Updated: `2026-07-14`

## 阶段 1：定向目标校验与权限回归

- [x] T001 编写定向目标校验与提交权限回归测试（先红）
  - Done when: 覆盖合法文档、合法独立文件、跨空间、非成功状态、多版本、已入链、提交不调用全量搜索及不调用 `view_file`。
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-006-01_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-006-01_
  - _Depends: none_
  - _Boundary: tests only; `test/knowledge/test_knowledge_version_service_similar_scan.py`, `test/approval/test_shougang_approval_service.py`_

- [x] T002 实现单目标发布版本校验并替换提交全量复验
  - Done when: 提交只调用定向方法并保持现有错误文案；T001 全绿；候选搜索列表行为不变。
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-006-01_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-006-01_
  - _Depends: T001_
  - _Boundary: `knowledge_version_service.py`, `shougang_approval_service.py`; 不修改普通版本搜索_

## 阶段 2：独立通知 Outbox 持久化

- [x] T003 编写通知 outbox 模型、Repository 和迁移测试（先红）
  - Done when: 覆盖建表字段/索引/唯一约束、幂等创建、状态更新、跨租户补偿扫描、最大重试和 downgrade。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-02_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-006-02_
  - _Depends: T002_
  - _Boundary: tests only; 新增 approval outbox repository/migration tests_

- [x] T004 实现通知 outbox 模型、Repository 与 F058 迁移
  - Done when: 新表符合双库和多租户要求，Repository 提供幂等创建、get/update、dispatchable scan；T003 全绿。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-02_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-006-02_
  - _Depends: T003_
  - _Boundary: notification outbox model/repository + `v2_6_0_f058_approval_notification_outbox.py`; 不修改 `ApprovalOutbox`_

## 阶段 3：Celery 通知与补偿

- [x] T005 编写通知 Service、Consumer 和 Beat Dispatcher 测试（先红）
  - Done when: 覆盖成功发送、发送失败、成功短路、并发互斥、Beat 重投、重试上限、租户恢复和消息参数兼容。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-03_
  - _Verification: V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-006-03_
  - _Depends: T004_
  - _Boundary: tests only; approval notification service/worker tests_

- [x] T006 实现通知 Service、Celery Consumer 和 Beat 补偿任务
  - Done when: 发布通知可即时投递且 30 秒内由 Beat 补偿；失败状态和错误摘要可见；现有业务执行 outbox 测试不变；T005 全绿。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-03_
  - _Verification: V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-006-03_
  - _Depends: T005_
  - _Boundary: approval notification service, worker registration, Celery settings；不修改其他消息场景_

## 阶段 4：发布提交集成与性能日志

- [x] T007 编写发布提交通知入队和分段日志测试（先红）
  - Done when: 覆盖 pending 有任务入队、非 pending/重复/无任务不入队、同步消息不调用、成功/失败性能日志字段和异常透传。
  - _Requirements: REQ-001, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-004-01, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-004-01, V-AC-REQ-004-05, V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T006_
  - _Boundary: tests only; `test_shougang_approval_service.py`_

- [x] T008 集成通知 outbox 并增加发布提交分段性能日志
  - Done when: 发布申请响应不等待站内信，性能日志包含规定阶段，知识空间创建消息仍保持原同步行为；T007 全绿。
  - _Requirements: REQ-001, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-004-01, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-004-01, V-AC-REQ-004-05, V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T007_
  - _Boundary: `shougang_approval_service.py` 与必要 endpoint dependency；不修改 Client_

## 阶段 5：审批任务批量持久化

- [x] T009 编写批量审批任务 Repository/Gate 测试（先红）
  - Done when: 覆盖多审批人单批调用、ID 顺序、字段兼容、批量异常不返回部分结果和 SQLite Repository 实际持久化。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-006-02_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-006-02_
  - _Depends: T008_
  - _Boundary: tests only; `test_approval_gate.py` 和必要 Repository 测试_

- [x] T010 实现审批任务单事务批量写入
  - Done when: `ApprovalGate` 不再逐审批人提交事务，返回顺序和字段不变，T009 及审批回归测试全绿。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-006-02_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-006-02_
  - _Depends: T009_
  - _Boundary: `approval_instance_repository.py`, `approval_gate.py`; 不重构其他审批写路径_

## 阶段 6：验证与收尾

- [x] T011 运行验收验证并更新 SDD 与版本索引
  - Done when: Ruff、定向测试、审批回归、迁移静态/SQLite 验证均有新鲜证据；更新 `verification.md`、`retrospective.md`、F054 索引和 release contract。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: verification.md_
  - _Depends: T001, T002, T003, T004, T005, T006, T007, T008, T009, T010_
  - _Boundary: verification and docs only_

### 计划验证命令

```bash
cd src/backend
uv run ruff check bisheng/approval bisheng/knowledge/domain/services/knowledge_version_service.py bisheng/worker/approval test/approval test/knowledge/test_knowledge_version_service_similar_scan.py
uv run pytest test/approval/test_shougang_approval_service.py -q
uv run pytest test/knowledge/test_knowledge_version_service_similar_scan.py -q
uv run pytest test/approval/test_approval_gate.py test/approval/test_approval_worker_tasks.py -q
uv run pytest test/approval -q
uv run alembic heads
```

真实 DM8 migration 验证仅在 Linux CI 可执行；本地 macOS 不声明 DM8 通过。

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..02 | T007, T008, T011 | V-AC-REQ-001-01..02 |
| REQ-002 | AC-REQ-002-01..04 | T001, T002, T011 | V-AC-REQ-002-01..04 |
| REQ-003 | AC-REQ-003-01..02 | T001, T002, T011 | V-AC-REQ-003-01..02 |
| REQ-004 | AC-REQ-004-01..05 | T003-T008, T011 | V-AC-REQ-004-01..05 |
| REQ-005 | AC-REQ-005-01..03 | T009, T010, T011 | V-AC-REQ-005-01..03 |
| REQ-006 | AC-REQ-006-01..03 | T001-T011 | V-AC-REQ-006-01..03 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- T001 RED：定向接口缺失触发 7 个 `AttributeError`；提交测试命中旧 `view_file` 检查器断言。
- T002 GREEN：7 个定向校验测试和发布提交定向调用测试通过；提交不再调用空关键词全量搜索或构造 `view_file` 检查器。
- 现有 SQLite fixture 缺少 `knowledgefile.file_subcategory_code`，新增定向测试改用 Repository mock 隔离，未扩大修改公共测试基础设施。
- T003/T004：通知 Outbox 的 5 个模型、Repository、跨租户扫描和迁移往返测试通过；`alembic heads` 为单一 F058 head。
- T005/T006：通知 Service/Worker/Beat 的 7 个用例通过；与 Outbox/迁移合计 12 个测试通过，保留原 `ApprovalNotificationService` 静态通知接口。
- T007/T008：发布提交 pending 入队、pass 跳过、成功/失败性能日志和异常透传测试通过；完整首钢审批文件 69 通过、3 个既存漂移失败。
- T009/T010：Gate/Repository 共 29 个测试通过；首节点审批任务改为一次批量事务写入并按解析顺序返回 ID。
- T011：专项验证 `48 + 7 + 5` 条测试全部通过；新增/改动文件 Ruff 检查、`compileall`、`git diff --check` 与 Alembic 单 head 检查通过；审批目录全量基线为 `161 passed, 15 failed`，失败均为本特性范围外既有漂移，详见 `verification.md`。
