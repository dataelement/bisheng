# 任务拆分 Tasks: 一个部门绑定多个知识空间

## 阅读摘要
- 本文档用于指导 Agent 按 Test-First 顺序实现 F060。
- 每个任务必须保持在声明边界内，不得执行真实数据库 upgrade。
- 实施前必须重新检查工作区，保护用户已有 `celerybeat-schedule.db` 修改。

## 元信息 Metadata
- Feature ID: `060-department-multiple-spaces`
- Status: `verified`
- Related requirements: `features/v2.6.0/060-department-multiple-spaces/requirements.md`
- Related design: `features/v2.6.0/060-department-multiple-spaces/design.md`
- Created: `2026-07-16`
- Updated: `2026-07-16`

## 阶段 1：基线与 Schema Foundation

- [x] T001 记录实施基线并增加 migration/model 失败测试
  - Done when: 记录当前 branch/status/active migration heads；测试证明当前模型仍声明 `uk_dks_department_id`，且期望 upgrade 删除部门唯一、保留空间唯一和普通索引。
  - _Requirements: REQ-001, REQ-006_
  - _Acceptance: AC-REQ-001-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04, V-AC-REQ-006-05_
  - _Depends: none_
  - _Boundary: tests and read-only baseline only; no production schema or database mutation_

- [x] T002 新增约束迁移并更新 ORM 模型
  - Done when: 新 Alembic revision 基于实施时 active heads；upgrade 仅删除 `uk_dks_department_id`；downgrade 在无重复时恢复、有重复时明确失败；ORM 仅保留 `space_id` 唯一；T001 测试转绿。
  - _Requirements: REQ-001, REQ-006_
  - _Acceptance: AC-REQ-001-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04_
  - _Depends: T001_
  - _Boundary: migration and DepartmentKnowledgeSpace ORM constraint only; do not execute live upgrade_

## 阶段 2：一对多绑定与集合读取 Core Binding

- [x] T003 增加一部门多空间和完整列表失败测试
  - Done when: 测试覆盖已占用部门 rebind 成功、原绑定保留、批量创建同部门多个不同空间、旧团队库绑定同部门、一个空间仍唯一、列表完整去重；当前实现至少因部门冲突校验而失败。
  - _Requirements: REQ-001, REQ-002, REQ-005_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-005-01, AC-REQ-005-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-005-01, V-AC-REQ-005-03_
  - _Depends: T001_
  - _Boundary: backend tests only; prefer new `test/knowledge/test_department_multiple_spaces.py` for isolated cases_

- [x] T004 实现绑定写入和读取的一对多语义
  - Done when: rebind、批量创建与旧团队库绑定不再拒绝部门已有其他空间；所有目标调用使用集合查询；`space_id` 冲突仍稳定拒绝；T003 测试转绿。
  - _Requirements: REQ-001, REQ-002, REQ-005_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-005-01, AC-REQ-005-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-005-01, V-AC-REQ-005-03_
  - _Depends: T002, T003_
  - _Boundary: department binding model/repository/service only; no target resolver or frontend changes_

## 阶段 3：管理员同步 Admin Membership

- [x] T005 增加管理员全量同步失败测试
  - Done when: 测试证明新增和移除管理员必须对同一部门所有 `space_id` 调用既有同步逻辑，并覆盖中途不可恢复失败传播；当前单空间实现按预期失败。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03_
  - _Depends: T003_
  - _Boundary: department admin sync tests only_

- [x] T006 实现管理员同步全部绑定空间
  - Done when: 单次调用先加载完整绑定集合，再按确定顺序逐空间复用 `_sync_added_admin`/`_sync_removed_admin`；错误记录和传播符合现有约定；T005 测试转绿。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03_
  - _Depends: T004, T005_
  - _Boundary: `department_knowledge_space_service.py` admin sync path only_

## 阶段 4：共享目标解析与集成 Target Resolution

- [x] T007 增加共享 resolver 及两条调用链失败测试
  - Done when: 测试覆盖唯一部门空间、部门空间优先旧绑定、当前部门无候选父级回退、多部门空间冲突、多旧绑定冲突、全链无候选；自由库迁移歧义 block，filelib 歧义不创建文件并返回 19904。
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-02_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-02_
  - _Depends: T003_
  - _Boundary: resolver/free-migration/filelib tests only; no production writes_

- [x] T008 实现共享 resolver 并接入自由库迁移与外部文件同步
  - Done when: resolver 一次批量读取部门链绑定和 scope；按已确认优先级解析；新增 18004；自由库转换为 ambiguous block；filelib 映射 19904 且在临时文件保存前失败；移除目标生产链路 `.first()` 单绑定查询；T007 测试转绿。
  - _Requirements: REQ-002, REQ-004, REQ-005_
  - _Acceptance: AC-REQ-002-03, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-02_
  - _Verification: V-AC-REQ-002-03, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-02_
  - _Depends: T004, T007_
  - _Boundary: shared resolver, free-space migration, filelib service/repository and error mapping only_

## 阶段 5：Client 契约与回归 Client/Regression

- [x] T009 更新 Client 旧冲突预期并验证保存刷新
  - Done when: 已绑定部门不再被测试为保存失败；编辑保存成功、详情/侧边栏/列表刷新断言保留；非管理员只读与拒绝行为不变。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-03_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-03_
  - _Depends: T004_
  - _Boundary: Client portal knowledge workbench tests and strictly necessary implementation only_

- [x] T010 执行定向回归、静态检查与迁移审查
  - Done when: F060 新测试、F058 rebind、部门空间 service、自由库迁移、filelib sync、Client 定向测试、ruff、format check、compileall、arch guard 与 `git diff --check` 均有新鲜结果；目标生产调用不存在单值选库方法。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05_
  - _Verification: all V-AC-* plus static quality gates_
  - _Depends: T002, T004, T006, T008, T009_
  - _Boundary: verification only; no live database upgrade, external writes, dependency changes or broad formatting_

- [x] T011 更新 verification、任务状态和实施偏差
  - Done when: 创建 `verification.md`，记录每条实际命令、退出码、AC 状态、DM8 CI 待验证项和未执行的 live migration；更新任务勾选与偏差，不伪报未运行验证。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all AC-REQ-*_
  - _Verification: verification.md_
  - _Depends: T010_
  - _Boundary: docs/spec only_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002, T003, T004, T010, T011 | V-AC-REQ-001-01..03 |
| REQ-002 | AC-REQ-002-01..03 | T003, T004, T008, T010, T011 | V-AC-REQ-002-01..03 |
| REQ-003 | AC-REQ-003-01..03 | T005, T006, T010, T011 | V-AC-REQ-003-01..03 |
| REQ-004 | AC-REQ-004-01..05 | T007, T008, T010, T011 | V-AC-REQ-004-01..05 |
| REQ-005 | AC-REQ-005-01..03 | T003, T004, T007, T008, T009, T010, T011 | V-AC-REQ-005-01..03 |
| REQ-006 | AC-REQ-006-01..05 | T001, T002, T010, T011 | V-AC-REQ-006-01..05 |

## 执行顺序

```text
T001 → T002 ┐
  └→ T003 → T004 ─┬→ T005 → T006 ┐
                  ├→ T007 → T008 ├→ T010 → T011
                  └→ T009 ───────┘
```

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.
- [x] Test tasks precede behavior implementation tasks.
- [x] Live database migration is explicitly excluded from implementation verification.

## 实现记录 Implementation Notes
- 规格生成时当前分支为 `feat/2.5.0-sg`。
- 规格生成前工作区已有 `src/backend/celerybeat-schedule.db` 修改，属于用户现有变更；F060 不得修改、重置或覆盖该文件。
- 规格阶段静态识别到多个 Alembic heads；T001 必须重新计算实施时 heads，禁止把当前快照硬编码为长期事实。
- `features/` 目录可能被 `.gitignore` 忽略，SDD 文件仍作为本地工作产物保存并用于实施追踪。
- 实施时 Alembic active heads 为 `f044_route_allowlist`、`v2_5_0_sg_048_portal_hot_search`、`v2_5_0_sg_f059_knowledge_sort_weight`；F060 revision 合并这三个头，最终仅剩 `f060_department_multiple_spaces (head)`。
- Client 整文件测试存在 40 个与本次改动无关的既有失败；本次直接相关的保存成功与通用失败两条用例定向运行通过，详情见 `verification.md`。
- 未执行真实数据库 upgrade；DM8 真实 DDL 兼容性留给 Linux/DM8 CI 验证。
