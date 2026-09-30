# 任务拆分 Tasks: 按文件分类自动移动到公共知识空间

## 阅读摘要
- 本文档用于按 Test-First 顺序实施 F061。
- 先重写纯预检/路由测试，再实现普通文件编排和版本链 Saga。
- 禁止自动运行真实业务 `--apply`，禁止触碰工作区已有无关改动。

## 元信息 Metadata
- Feature ID: `061-classified-public-space-file-move`
- Status: `completed`
- Related requirements: `features/v2.6.0/061-classified-public-space-file-move/requirements.md`
- Related design: `features/v2.6.0/061-classified-public-space-file-move/design.md`
- Created: `2026-07-17`
- Updated: `2026-07-17`

## 阶段 1：多来源与分类路由 Foundation

- [x] T001 重写 CLI、来源发现和分类路由失败测试
  - Done when: 测试覆盖多个来源 ID、去重稳定排序、默认 dry-run、文件状态过滤、分类 code-to-label、公共空间唯一匹配、根目录直属文件夹唯一匹配及全部跳过原因；当前旧实现按预期失败。
  - _Requirements: REQ-001, REQ-002, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-006-01_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-006-01_
  - _Depends: none_
  - _Boundary: tests only; no production or external writes_

- [x] T002 实现新 CLI、来源 inventory 和分类/目标索引
  - Done when: `--source-space-id` 可重复且替代旧筛选/目标参数；批量预检构建来源、分类 label、公共空间和直属目录索引；T001 对应测试转绿。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04_
  - _Depends: T001_
  - _Boundary: `move_knowledge_space_files.py` CLI and read-only preflight/index components only_

## 阶段 2：迁移单元与冲突规划 Planning

- [x] T003 增加普通文件、版本链和冲突 planner 失败测试
  - Done when: 测试覆盖普通文件/版本链分组、部分链越界、成员非成功、分类缺失、路由不同、模型不一致、目标同名/MD5、批内冲突、链内同名不自冲突和稳定选择顺序；当前实现按预期失败。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-004-01, V-AC-REQ-004-02_
  - _Depends: T001_
  - _Boundary: tests only; planner uses fake data and performs no writes_

- [x] T004 实现 MigrationUnitPlanner 和冲突预留
  - Done when: 候选形成稳定排序的 `SingleFileUnit`/`VersionChainUnit`；版本链使用全成员一致性 guard；目标既有及批内名称/MD5冲突按要求跳过；T003 测试转绿。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-004-01, V-AC-REQ-004-02_
  - _Depends: T002, T003_
  - _Boundary: `move_knowledge_space_files.py` pure planning models/functions only_

## 阶段 3：普通文件和版本链执行 Execution

- [x] T005 增加目标上下文、版本图和 Saga 补偿失败测试
  - Done when: 测试覆盖目标 owner 字段、owner/parent 权限、存储/索引/标签验证、新文件 ID 映射、版本号/主版本重建，以及复制、标签、权限、版本图、目标验证、来源删除每个失败点的补偿结果。
  - _Requirements: REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-006-04_
  - _Verification: V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-006-04_
  - _Depends: T003_
  - _Boundary: tests only; use protocol fakes/mocks, no real DB or middleware writes_

- [x] T006 参数化普通文件操作并实现 VersionChainSaga
  - Done when: `BishengMoveOperations` 接收每文件目标上下文；普通文件回归保持；版本链先复制并重建目标版本图、验证后删除来源，失败按阶段补偿；T005 测试转绿。
  - _Requirements: REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-006-04_
  - _Verification: V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-006-04_
  - _Depends: T004, T005_
  - _Boundary: move script operations, version persistence and Saga only; no online API changes_

## 阶段 4：协调、报告与文档 Integration

- [x] T007 重写执行协调、dry-run 和报告测试
  - Done when: 测试证明 dry-run 不构造写操作；apply 按单元稳定执行；报告包含普通文件/版本链目标和补偿字段；失败返回非零、纯跳过返回零。
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03_
  - _Depends: T004, T005_
  - _Boundary: tests only; no real application context or external writes_

- [x] T008 实现 MoveCoordinator、扩展报告并更新 README
  - Done when: dry-run 输出完整 selected/skipped 计划；apply 执行所有独立单元并聚合结果；JSON schema 可追踪版本链；README 提供新 CLI、匹配/跳过规则、旧参数迁移和风险说明；T007 测试转绿。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-002-03, AC-REQ-004-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-002-03, V-AC-REQ-004-03, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03_
  - _Depends: T006, T007_
  - _Boundary: move script coordinator/report and `scripts/README.md` only_

## 阶段 5：验证与收尾 Verification

- [x] T009 执行定向回归、静态检查和 CLI 烟测
  - Done when: F061 脚本测试、`test_file_worker_copy_normal.py`、Ruff format/check、`py_compile`、脚本 `--help`、`git diff --check` 均有新鲜结果；工作区无无关改动。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all AC-REQ-*_
  - _Verification: all V-AC-* plus static quality gates_
  - _Depends: T002, T004, T006, T008_
  - _Boundary: verification only; no real business dry-run/apply, dependency or config changes_

- [x] T010 更新 verification、任务状态和实施偏差
  - Done when: 创建 `verification.md`，逐条记录实际命令、退出码、AC 状态、未执行的真实环境演练和残留风险；更新 task checkbox 和设计偏差，不伪报未运行验证。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all AC-REQ-*_
  - _Verification: verification.md_
  - _Depends: T009_
  - _Boundary: docs/spec only_

## 阶段 6：MinIO 客户端缺陷修复 Bugfix

- [x] T011 记录真实 apply 失败、根因和回归验收标准
  - Done when: requirements/design/tasks 记录错误行为、期望行为、影响范围、根因、最小修复策略和验证方式。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: spec traceability review_
  - _Depends: T010_
  - _Boundary: F061 spec only_

- [x] T012 增加 MinIO helper 失败回归测试
  - Done when: 测试直接执行 `_storage_exists()` 和 `_copy_object_if_present()`，旧实现因不存在的客户端入口而失败。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02_
  - _Depends: T011_
  - _Boundary: move script test only; fake MinIO, no external writes_

- [x] T013 替换为统一 MinIO 同步客户端入口
  - Done when: 两个 helper 使用 `get_minio_storage_sync()`，T012 从红转绿，`copy_file` 回归保持通过。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03_
  - _Depends: T012_
  - _Boundary: move script import and two helper calls only_

- [x] T014 执行定向回归和静态检查
  - Done when: 移动脚本测试、copy worker 回归、Ruff、format、py_compile、CLI help、arch-guard 和 `git diff --check` 均有新鲜结果。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: all V-AC-REQ-007-* plus static quality gates_
  - _Depends: T013_
  - _Boundary: verification only; no real dry-run/apply_

- [x] T015 更新缺陷验证记录
  - Done when: verification.md 和 retrospective.md 记录线上证据、RED/GREEN 结果、最终命令、测试盲区和仍需人工重跑的真实 apply。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: verification.md_
  - _Depends: T014_
  - _Boundary: F061 spec/verification/retrospective only_

## 阶段 7：版本链跳过报告快速修复

- [x] T016 记录分类字段和底层 route reason 丢失缺陷
  - Done when: requirements/design/tasks 记录现象、根因、兼容边界和回归标准。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03_
  - _Verification: spec traceability review_
  - _Depends: T015_
  - _Boundary: F061 spec only_

- [x] T017 增加版本链目标未解析报告失败测试
  - Done when: 旧实现因分类字段为空、底层原因缺失或重复解析而失败。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03_
  - _Verification: V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-03_
  - _Depends: T016_
  - _Boundary: move script planner test only_

- [x] T018 实现诊断上下文保留和单次目标解析
  - Done when: 保留分类、底层 route detail 和兼容 reason code；T017 转绿。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03_
  - _Verification: V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-03_
  - _Depends: T017_
  - _Boundary: `_resolve_chain_unit` and its local skip helper only_

- [x] T019 执行回归并更新 verification/retrospective
  - Done when: 定向测试和静态质量门通过，文档记录 RED/GREEN 与未执行真实重跑。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03_
  - _Verification: all V-AC-REQ-008-* plus static quality gates_
  - _Depends: T018_
  - _Boundary: tests and F061 verification docs; no real apply_

## 阶段 8：零宽字符路由与线上数据修复

- [x] T020 记录零宽字符缺陷、线上证据和受控修复边界
  - Done when: requirements/design/tasks 包含 REQ-009、事务风险、回滚和真实 dry-run 验收。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02, AC-REQ-009-03, AC-REQ-009-04_
  - _Verification: spec traceability review_
  - _Depends: T019_
  - _Boundary: F061 spec only_

- [x] T021 增加零宽字符名称匹配失败测试
  - Done when: 旧实现无法匹配带 `U+200B`/`U+FEFF` 的空间或根目录，测试以预期原因失败。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02_
  - _Verification: V-AC-REQ-009-01, V-AC-REQ-009-02_
  - _Depends: T020_
  - _Boundary: move script resolver tests only_

- [x] T022 最小修复统一名称规范化并执行回归
  - Done when: T021 转绿，完整定向 pytest、Ruff、编译和差异检查通过。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02_
  - _Verification: V-AC-REQ-009-01, V-AC-REQ-009-02 plus static quality gates_
  - _Depends: T021_
  - _Boundary: `_normalize_label`, tests and required spec evidence only_

- [x] T023 事务性清理线上8个公共空间名称末尾的 `U+200B`
  - Done when: 更新前值和清理后唯一性全部通过断言，单事务提交后8个名称均无 `U+200B`。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-03_
  - _Verification: V-AC-REQ-009-03 pre/post production query_
  - _Depends: T022_
  - _Boundary: Knowledge IDs 3888, 3889, 3890, 3891, 3894, 3895, 3896, 3897 only_

- [x] T024 使用17个来源空间执行线上 dry-run
  - Done when: `target_space_not_found=0`，记录 selected units、`dry_run_selected` 和报告路径；不传 `--apply`。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-03_
  - _Verification: V-AC-REQ-009-03_
  - _Depends: T023_
  - _Boundary: production read-only planner plus JSON report write only_

- [x] T025 提取并核对批内 MD5/名称冲突清单
  - Done when: 对每条冲突记录输出来源和占用单元；不删除、改名或强制移动冲突文件。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-04_
  - _Verification: V-AC-REQ-009-04_
  - _Depends: T024_
  - _Boundary: report and source metadata read only_

- [x] T026 更新验证与复盘记录
  - Done when: verification/retrospective 记录 RED/GREEN、线上事务、dry-run和冲突清单证据。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02, AC-REQ-009-03, AC-REQ-009-04_
  - _Verification: all V-AC-REQ-009-*_
  - _Depends: T025_
  - _Boundary: F061 documentation only_

## 阶段 9：目标标签快照一致性修复

- [x] T027 记录真实标签校验失败及最小修复边界
  - Done when: requirements/design/tasks 记录89515、89516失败证据、快照唯一来源、精确替换和诊断验收标准。
  - _Requirements: REQ-010_
  - _Acceptance: AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: spec traceability review_
  - _Depends: T026_
  - _Boundary: F061 spec only_

- [x] T028 增加目标标签快照一致性失败测试
  - Done when: 旧实现因重新调用 `_copy_file_tags()` 而未使用缓存快照，并且标签不一致错误缺少双方 ID，两个测试按预期失败。
  - _Requirements: REQ-010_
  - _Acceptance: AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: V-AC-REQ-010-01, V-AC-REQ-010-02, V-AC-REQ-010-03 RED_
  - _Depends: T027_
  - _Boundary: move script operation tests only; fake DB/storage/index/permission boundaries_

- [x] T029 使用来源快照精确替换目标标签并补充差异诊断
  - Done when: `copy_tags()` 使用 `SourceSnapshot.tags` 调用精确替换 helper，不再依赖审批私有复制函数；T028 转绿。
  - _Requirements: REQ-010_
  - _Acceptance: AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: V-AC-REQ-010-01, V-AC-REQ-010-02, V-AC-REQ-010-03 GREEN_
  - _Depends: T028_
  - _Boundary: move script tag import, `copy_tags`, `verify_target` and focused tests only_

- [x] T030 执行完整回归并更新验证与复盘
  - Done when: 定向 pytest、Ruff、format、py_compile、arch-guard、`git diff --check` 全部有新鲜证据，文档记录真实 apply 未重跑。
  - _Requirements: REQ-010_
  - _Acceptance: AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: all V-AC-REQ-010-* plus static quality gates_
  - _Depends: T029_
  - _Boundary: verification and F061 documentation only; no production apply_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002, T008, T009, T010 | V-AC-REQ-001-01..03 |
| REQ-002 | AC-REQ-002-01..04 | T001, T002, T008, T009, T010 | V-AC-REQ-002-01..04 |
| REQ-003 | AC-REQ-003-01..04 | T003, T004, T009, T010 | V-AC-REQ-003-01..04 |
| REQ-004 | AC-REQ-004-01..05 | T003, T004, T005, T006, T008, T009, T010 | V-AC-REQ-004-01..05 |
| REQ-005 | AC-REQ-005-01..04 | T005, T006, T009, T010 | V-AC-REQ-005-01..04 |
| REQ-006 | AC-REQ-006-01..04 | T001, T005, T006, T007, T008, T009, T010 | V-AC-REQ-006-01..04 |
| REQ-007 | AC-REQ-007-01..03 | T011, T012, T013, T014, T015 | V-AC-REQ-007-01..03 |
| REQ-008 | AC-REQ-008-01..03 | T016, T017, T018, T019 | V-AC-REQ-008-01..03 |
| REQ-009 | AC-REQ-009-01..04 | T020, T021, T022, T023, T024, T025, T026 | V-AC-REQ-009-01..04 |
| REQ-010 | AC-REQ-010-01..03 | T027, T028, T029, T030 | V-AC-REQ-010-01..03 |

## 执行顺序

```text
T001 → T002 ┐
  └→ T003 → T004 ─┬→ T005 → T006 ─┐
                  └→ T007 ─────────┴→ T008 → T009 → T010
                                                       └→ T011 → T012 → T013 → T014 → T015
                                                                                       └→ T016 → T017 → T018 → T019
                                                                                                                   └→ T020 → T021 → T022 → T023 → T024 → T025 → T026 → T027 → T028 → T029 → T030
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
- [x] Real business apply is explicitly excluded from automated verification.

## 实现记录 Implementation Notes
- 规格生成时当前分支为 `feat/2.5.0-sg`。
- 规格生成前工作区已有聊天流错误处理和 `celerybeat-schedule.db` 相关改动，均属于用户现有变更；F061 不得修改、重置或覆盖这些文件。
- F061 不涉及 schema migration，也不需要新增第三方依赖。
- 项目要求 `spec.md` 兼容摘要，因此除核心 SDD 三文件外同步创建该文件。
- 实现与自动化验证已完成；真实业务 dry-run/apply 仍按 `verification.md` 标记为人工验证，不属于未完成代码任务。
- REQ-007 修复使用项目统一 MinIO 同步客户端入口，并补充直接 helper 回归测试；线上失败的 3 个来源文件未创建目标记录，仍需部署修复后人工重跑。
- REQ-008 保持 chain reason code 兼容，同时补齐分类字段、底层 route detail，并将一致分类的目标解析收敛为一次。
- REQ-009 仅删除明确的零宽格式字符，不扩大名称匹配语义；线上数据修复与 dry-run 依用户确认的生产权限执行。
- T023 首次预检因数据库排序规则将正常名称与带 `U+200B` 名称视为相等而安全回滚；核对无外部冲突后排除目标8条自身并重新提交。
- REQ-010 限定在迁移脚本内复用已保存标签快照，不修改审批发布模块和标签 DAO。
