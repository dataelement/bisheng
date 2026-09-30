# 任务拆分 Tasks：知识空间文件重解析任务入队脚本

## 阅读摘要

- 本计划实现一个独立的 Celery 入队脚本，不修改原本地重解析脚本或 worker。
- 状态转换、跨租户 header 和发布失败补偿属于高风险数据语义，采用测试先行。
- 任务共享同一组定向 pytest 和静态验证，不按 AC 重复执行命令。

## 元信息 Metadata

- Feature ID: `059-enqueue-knowledge-space-reparse`
- Status: `completed`
- Related requirements: `features/v2.5.0-sg/059-enqueue-knowledge-space-reparse/requirements.md`
- Related design: `features/v2.5.0-sg/059-enqueue-knowledge-space-reparse/design.md`
- Created: `2026-07-28`
- Updated: `2026-07-28`

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| requirements/design/spec | ✅ 已确认 | 用户于 2026-07-28 确认 |
| tasks.md | ✅ 已拆解 | 用户已授权快速实施 |
| 实现 | ✅ 已完成 | 4 / 4 完成 |

## 阶段 1：失败契约与核心行为

- [x] T001 建立入队脚本最小回归测试
  - Done when: 测试覆盖 dry-run 无副作用、成功状态转换与发布、筛选后状态漂移、跨租户 header、发布失败回滚、回滚再失败、继续批次和退出码；实现前目标测试因新模块缺失而按预期失败。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04_
  - _Depends: none_
  - _Boundary: tests only; no real database or broker_

- [x] T002 实现候选复用、状态准备、Celery 发布和补偿
  - Done when: 新脚本复用现有候选收集/状态解析，默认 dry-run；`--apply` 逐文件重新复核、更新四字段、显式发布到 `knowledge_celery` 并带文件租户 header；发布失败恢复快照并继续；报告与退出码符合契约。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: EG-001, EG-002, EG-003_
  - _Depends: T001_
  - _Boundary: create src/backend/scripts/enqueue_reparse_knowledge_space_files.py only; do not modify original reparse script or worker_

## 阶段 2：运维交付

- [x] T003 添加包装器和 README 使用说明
  - Done when: shell 包装器符合脚本目录约定；README 在保留现有未提交内容的前提下追加 dry-run、`--apply`、筛选、worker 前置条件、成功入队定义和风险说明。
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-02_
  - _Depends: T002_
  - _Boundary: create one shell wrapper and minimally append src/backend/scripts/README.md_

## 阶段 3：验证与证据

- [x] T004 完成定向验证并记录 evidence
  - Done when: 新旧脚本相关 pytest、Ruff、compileall、shell syntax、CLI `--help`、架构守卫和 diff check 通过；`verification.md` 记录命令、结果、AC coverage 和未执行的真实环境验证。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03_
  - _Verification: EG-001, EG-002, EG-003, EG-004_
  - _Depends: T003_
  - _Boundary: verification commands and features/v2.5.0-sg/059-enqueue-knowledge-space-reparse/verification.md only; never run real --apply_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03 | T001, T002, T004 | EG-001 |
| REQ-002 | AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04 | T001, T002, T004 | EG-002 |
| REQ-003 | AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04 | T001, T002, T004 | EG-003 |
| REQ-004 | AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03 | T003, T004 | EG-004 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Tasks sharing one behavior or command use a verification batch instead of duplicate verification tasks.
- [x] Test work covers distinct outcomes/risks and does not duplicate the same behavior across test layers.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes

- 当前工作区已有用户对 `src/backend/scripts/README.md` 的修改和未跟踪的 `src/backend/scripts/execute_sql.py`；实现不得覆盖、格式化或纳入后者。
- `features/` 被 `.gitignore` 忽略；规格和验证文件存在于工作区，但后续若要提交需显式 `git add -f`。
- T001 RED：目标 pytest 在实现前因 `ModuleNotFoundError: scripts.enqueue_reparse_knowledge_space_files` 失败，证明测试约束了新入口。
- T001/T002 GREEN：新脚本定向测试 `12 passed`。
- T004 相关回归：新旧重解析脚本测试合并执行 `31 passed`；Ruff、compileall、shell syntax、CLI `--help`、架构守卫和 diff check 通过。
- 设计修正：实现前发现 Celery publish signal 会用当前 ContextVar 覆盖 header；发布逻辑采用显式 header 加同值临时租户上下文，并在 `finally` 恢复，测试验证不泄漏。
