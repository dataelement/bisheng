# 任务拆分 Tasks: Workflow User Selected Knowledge

## 阅读摘要
- 本文档用于指导 Agent 按任务实现。
- 2026-06-24 范围变更后，当前可执行任务从 T018-T026 开始。
- 每个任务必须保持在声明的边界内。
- 不得实现未列入任务的内容。
- task metadata 字段保持英文固定格式，便于 Agent 稳定读取。
- 阅读摘要用于快速理解；任务依赖、边界、需求映射和验证映射以 task metadata 与 Coverage Matrix 为准。

## 元信息 Metadata
- Feature ID: `046-workflow-user-selected-knowledge`
- Status: `scope-updated-pending-implementation`
- Related requirements: `specs/046-workflow-user-selected-knowledge/requirements.md`
- Related design: `specs/046-workflow-user-selected-knowledge/design.md`
- Created: `2026-06-23`
- Updated: `2026-06-24`

## 任务格式 Task Format

## 范围变更说明 Scope Update
- 2026-06-24 用户确认选择方式变更：完整知识库 / 完整知识空间每次最多选择一个；文件 / 文件夹曾按两类来源混选实现，随后同日澄清为 `文档知识库` / `知识空间` TAB 互斥，切换 TAB 清空另一类选择，最终 payload 不混合 knowledge/space items。
- T001-T017 中已完成状态代表旧单 `source_id` 合同下的实现记录；本次范围变更后，不得直接把这些完成状态视为新需求完成。
- 新实现应从 `阶段 5：范围变更重构 Scope Update Rework` 的 T018 开始执行，并在完成后重新运行验证、更新 `verification.md`。

Every implementation task must include:
- Checkbox and task ID.
- Requirement ID.
- Acceptance criterion ID when behavioral.
- Verification method or verification ID.
- Boundary when scope-sensitive or parallel-safe.

Task metadata order must stay stable:
1. `_Requirements: ..._`
2. `_Acceptance: ..._`
3. `_Verification: ..._`
4. `_Depends: ..._`
5. `_Boundary: ..._`

Recommended `_Boundary` values:
- `read-only investigation`
- `implementation only`
- `tests only`
- `verification only`
- `docs/spec only`
- concrete component or file boundary, for example `Platform FlowChat picker only`

## 阶段 1：基础准备 Foundation

- [x] T001 Confirm published workflow runtime entry points
  - Done when: implementation notes identify the exact Platform and Client routes/components that render workflow runtime input, including whether Client is required for the current deployment.
  - _Requirements: REQ-002_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02_
  - _Depends: none_
  - _Boundary: read-only investigation_

- [x] T002 Define shared runtime selection types and constants
  - Done when: 旧合同下的前后端运行态选择常量和类型已存在；2026-06-24 新合同重构由 T018 追踪。
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-05_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-05_
  - _Depends: T001_
  - _Boundary: implementation only_

- [x] T003 Add or confirm knowledge file and knowledge-space range APIs
  - Done when: 旧合同下的知识库和知识空间范围接口路径已确认；树形勾选和同类型多 source 范围接口由 T019-T021 追踪。
  - _Requirements: REQ-003, REQ-006_
  - _Acceptance: AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-006-01_
  - _Verification: V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-006-01_
  - _Depends: T002_
  - _Boundary: existing knowledge and knowledge-space API wrappers/services only_

## 阶段 2：节点模板与运行态 UI Core Frontend

- [x] T004 Add Platform workflow templates for self-selected nodes
  - Done when: Platform node panel can add `自选知识问答` and `自选知识检索`, and their parameter schemas match the design: no fixed knowledge selector and no `metadata_filter`.
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-001-04_
  - _Depends: T002_
  - _Boundary: `src/frontend/platform/src/controllers/API/workflow.ts` and Platform flow locales_

- [x] T005 Build Platform self-selected knowledge picker
  - Done when: 旧合同下的 Platform 选择器已实现；2026-06-24 树形勾选重构由 T019 追踪。
  - _Requirements: REQ-002, REQ-003_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04_
  - _Depends: T003, T004_
  - _Boundary: Platform `FlowChat` picker component and local helpers_

- [x] T006 Add Platform file and folder range selection rules
  - Done when: 旧合同下的 Platform 范围规则已实现；2026-06-24 同类型多 source 文件 / 文件夹规则由 T019 和 T021 追踪。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08_
  - _Verification: V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-003-08_
  - _Depends: T005_
  - _Boundary: Platform self-selected knowledge picker and API wrappers_

- [x] T007 Wire Platform send guard and payload
  - Done when: Platform blocks send when selection is required but missing, and sends the runtime selection object with the current workflow input when valid.
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-REQ-002-04, AC-REQ-002-05, AC-REQ-004-01_
  - _Verification: V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-004-01_
  - _Depends: T005, T006_
  - _Boundary: `ChatInput.tsx`, `ChatPane.tsx`, Platform picker state only_

- [x] T008 Add Client published workflow picker
  - Done when: the published workflow use page shows equivalent self-selected knowledge UI, follows Client app conventions, blocks missing selection, and submits the same payload shape.
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-07, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: V-AC-REQ-002-02, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-01, V-AC-REQ-003-07, V-AC-REQ-004-01, V-AC-REQ-006-05_
  - _Depends: T001, T003, T007_
  - _Boundary: Client workflow runtime input components and Client API layer only_

## 阶段 3：后端运行时 Integration

- [x] T009 Register backend node types
  - Done when: backend recognizes the two new node types, instantiates their node classes, and old node type mappings remain unchanged.
  - _Requirements: REQ-001, REQ-006_
  - _Acceptance: AC-REQ-001-04, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: V-AC-REQ-001-04, V-AC-REQ-006-03, V-AC-REQ-006-04_
  - _Depends: T002, T004_
  - _Boundary: workflow node enum/manage registration only_

- [x] T010 Store runtime selection in workflow shared state
  - Done when: backend extracts the reserved runtime selection field from input node user input, validates basic shape, stores it in GraphState or equivalent shared state, and does not treat it as a node ID.
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05_
  - _Depends: T002, T009_
  - _Boundary: `GraphEngine`, `GraphState`, input validation path_

- [x] T011 Implement runtime selection validation and permission checks
  - Done when: 旧合同下的后端运行态选择校验和权限兜底已实现；2026-06-24 双模式 payload、同类型多 source items 和文件夹展开由 T021 追踪。
  - _Requirements: REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-004-05, V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T003, T010_
  - _Boundary: workflow knowledge runtime helper and existing permission service boundary_

- [x] T012 Implement self-selected knowledge retriever node
  - Done when: `自选知识检索` uses runtime selection for knowledge or space retrieval, applies selected file/folder range, and returns `retrieved_result` compatible with existing `knowledge_retriever`.
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-05, AC-REQ-005-07, AC-REQ-006-04_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-05, V-AC-REQ-005-07, V-AC-REQ-006-04_
  - _Depends: T010, T011_
  - _Boundary: new retriever node class and shared knowledge helper only_

- [x] T013 Implement self-selected knowledge RAG node
  - Done when: `自选知识问答` uses runtime selection for knowledge or space retrieval, generates answers through the existing RAG flow, and preserves user-visible output and downstream variables.
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-06, AC-REQ-005-07, AC-REQ-006-04_
  - _Verification: V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-005-06, V-AC-REQ-005-07, V-AC-REQ-006-04_
  - _Depends: T010, T011, T012_
  - _Boundary: new RAG node class and shared knowledge helper only_

## 阶段 4：测试与验证 Verification and Cleanup

- [x] T014 Add backend workflow regression tests
  - Done when: backend tests cover missing selection, illegal payload, multiple self-selected nodes sharing one selection, whole-source retrieval with no file/folder range, knowledge source retrieval, space source retrieval, over-20 file range, unauthorized/deleted resources, and old node regressions.
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-003-08, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-005-07, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: V-AC-REQ-003-08, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-005-05, V-AC-REQ-005-06, V-AC-REQ-005-07, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04_
  - _Depends: T009, T010, T011, T012, T013_
  - _Boundary: `src/backend/test/workflow/test_user_selected_knowledge.py`_

- [x] T015 Add frontend regression tests
  - Done when: Platform and Client tests or documented manual checks cover component visibility, source replacement, file/folder restrictions, over-limit blocking, missing-selection send guard, and payload shape.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-004-01, V-AC-REQ-006-05_
  - _Depends: T004, T005, T006, T007, T008_
  - _Boundary: frontend tests only_

- [x] T016 Run build, backend tests, and browser smoke verification
  - Done when: backend workflow tests pass, Platform build passes, Client build/test pass where applicable, and manual browser smoke covers Platform plus published workflow use page.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: backend pytest, Platform build/vitest, Client build/test, browser smoke evidence_
  - _Depends: T014, T015_
  - _Boundary: verification only_

- [x] T017 Update `verification.md`
  - Done when: `specs/046-workflow-user-selected-knowledge/verification.md` records executed commands, exit codes, browser evidence, acceptance coverage, skipped items, and residual risks.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T016_
  - _Boundary: docs/spec only_

## 阶段 5：范围变更重构 Scope Update Rework

- [x] T018 Update runtime selection contract and shared types
  - Done when: Platform、Client、后端共享的运行态知识选择结构支持 `mode=source` 与 `mode=items`，可表达完整 source 单选、同类型多 source 文件 / 文件夹多选、`effective_file_count`，且后端 parser 可把旧单 `type/source_id/files/folders` shape 归一化到新 shape。
  - _Requirements: REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-05, AC-REQ-003-08, AC-REQ-004-01, AC-REQ-004-05, AC-REQ-006-03_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-003-05, V-AC-REQ-003-08, V-AC-REQ-004-01, V-AC-REQ-004-05, V-AC-REQ-006-03_
  - _Depends: T001_
  - _Boundary: shared runtime selection types, constants, parser only_

- [x] T019 Rework Platform picker to tree checkbox selection
  - Done when: Platform 运行页选择器以树形结构展示知识库、知识空间、文件和文件夹，支持完整 source 单选、当前 TAB 内多 source 文件 / 文件夹多选、两种模式互斥、TAB 切换清空、加载状态、空状态、20 文件限制和发送前校验。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-09, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-003-09, V-AC-REQ-004-01, V-AC-REQ-006-05_
  - _Depends: T018_
  - _Boundary: Platform `FlowChat` picker, payload builder, local helpers only_

- [x] T020 Rework Client published workflow picker to match Platform contract
  - Done when: Client 已发布 workflow 使用页使用 Client 技术栈实现与 Platform 等价的树形勾选、互斥、超限、加载 / 空状态和 payload 提交行为。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-09, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: V-AC-REQ-002-02, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-003-09, V-AC-REQ-004-01, V-AC-REQ-006-05_
  - _Depends: T018, T019_
  - _Boundary: Client appChat picker, state, websocket payload only_

- [x] T021 Rework backend runtime validation, permission checks, and folder expansion
  - Done when: 后端校验完整 source 单选、完整 source 与 items 互斥、items 必须携带 source 信息、文件夹按 source 类型展开或解释、最终文件数不超过 20，并对 source/file/folder 重新执行运行时权限校验。
  - _Requirements: REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-004-02, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-003-08, V-AC-REQ-004-02, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T018_
  - _Boundary: `runtime_knowledge.py`, workflow shared state extraction, existing permission service boundary_

- [x] T022 Rework self-selected node retrieval for whole source and cross-source items
  - Done when: `自选知识检索` 与 `自选知识问答` 能处理完整知识库、完整知识空间、同类型多 source 文件 / 文件夹三类范围，按 source 分组调用对应检索能力，并保持 `retrieved_result`、用户输出和下游变量兼容。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-005-07, AC-REQ-006-04_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-005-05, V-AC-REQ-005-06, V-AC-REQ-005-07, V-AC-REQ-006-04_
  - _Depends: T021_
  - _Boundary: new self-selected nodes and shared knowledge runtime helper only_

- [x] T023 Update frontend tests for tree selection contract
  - Done when: Platform 和 Client tests 覆盖树形展示、完整 source 替换、模式互斥、TAB 切换清空、同类型多 source 文件 / 文件夹选择、20 文件限制、加载 / 空状态、缺少选择阻止发送和新 payload snapshot。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-09, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: frontend vitest/jest_
  - _Depends: T019, T020_
  - _Boundary: frontend tests only_

- [x] T024 Update backend tests for new runtime selection contract
  - Done when: backend tests cover new payload parser、旧 shape 兼容、完整 source、同类型多 source 文件 / 文件夹、混合 knowledge/space 拒绝、超限、无权限、删除资源、多个自选节点共享选择和旧节点回归。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-005-07, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: backend pytest_
  - _Depends: T021, T022_
  - _Boundary: backend workflow tests only_

- [x] T025 Run automated and browser verification for scope update
  - Done when: backend workflow tests、Platform tests、Client tests/build where applicable、`git diff --check` 和浏览器冒烟验证均已记录结果；浏览器覆盖 Platform 运行预览和 Client 发布页中至少一个真实流程。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: backend pytest, Platform vitest/build, Client jest/build, browser smoke evidence_
  - _Depends: T023, T024_
  - _Boundary: verification only_

- [x] T026 Update verification evidence after rework
  - Done when: `verification.md` 记录本次范围变更后的命令、exit code、浏览器证据、acceptance coverage、未验证项和剩余风险。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T025_
  - _Boundary: docs/spec only_

## 阶段 6：TAB 互斥调整 Tab Mutual Exclusion Update

- [x] T027 Update spec for knowledge/space tab mutual exclusion
  - Done when: requirements、design、tasks 记录 `文档知识库` / `知识空间` TAB 切换、切换清空另一类选择、同一 payload 不混合 knowledge/space items。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-05, AC-REQ-003-10, AC-REQ-004-01, AC-REQ-004-05_
  - _Verification: spec diff review_
  - _Depends: T026_
  - _Boundary: docs/spec only_

- [x] T028 Rework Platform picker into knowledge/space tabs
  - Done when: Platform 运行态选择器使用 `文档知识库` / `知识空间` TAB 展示，默认知识库 TAB，切换 TAB 清空已选完整 source、文件和文件夹，并只渲染当前 TAB 内容。
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-05, AC-REQ-003-09, AC-REQ-003-10, AC-REQ-004-01_
  - _Verification: Platform vitest, browser smoke_
  - _Depends: T027_
  - _Boundary: Platform `FlowChat` picker only_

- [x] T029 Rework Client picker into matching knowledge/space tabs
  - Done when: Client 发布页选择器与 Platform 一致，使用 TAB 区分知识库和知识空间，切换 TAB 清空另一类选择，知识空间 TAB 保留类型分组。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-05, AC-REQ-003-09, AC-REQ-003-10, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: Client jest/build_
  - _Depends: T027, T028_
  - _Boundary: Client appChat picker only_

- [x] T030 Add backend guard against mixed knowledge/space items
  - Done when: 后端 `RuntimeKnowledgeSelection` 拒绝 `mode=items` 同时包含 `knowledge` 与 `space` 条目，并有测试覆盖。
  - _Requirements: REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-003-05, AC-REQ-003-10, AC-REQ-004-05, AC-REQ-006-03_
  - _Verification: backend pytest_
  - _Depends: T027_
  - _Boundary: runtime selection parser/validator and backend tests only_

- [x] T031 Update frontend tests for tab mutual exclusion
  - Done when: Platform 和 Client 组件测试覆盖默认 TAB、切换 TAB 清空、知识空间类型分组、当前 TAB payload 不混合另一类来源。
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-05, AC-REQ-003-10, AC-REQ-004-01_
  - _Verification: Platform vitest, Client jest_
  - _Depends: T028, T029_
  - _Boundary: frontend tests only_

- [x] T032 Verify tab mutual exclusion update and record evidence
  - Done when: backend pytest、Platform vitest/build、Client jest/build、diff checks 和可用时浏览器冒烟结果写入 `verification.md`。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T030, T031_
  - _Boundary: verification and docs/spec only_

## 阶段 7：对话框输入支持 Dialog Input Support

- [x] T033 Update spec for dialog and form input runtime picker support
  - Done when: requirements、design、tasks 记录自选知识组件同时覆盖 `dialog_input` 和 `form_input`，且表单输入支持不回退。
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-002-07, AC-REQ-004-01_
  - _Verification: spec diff review_
  - _Depends: T032_
  - _Boundary: docs/spec only_

- [x] T034 Fix Platform runtime picker visibility for dialog and form input
  - Done when: Platform `FlowChat` 在 `dialog_input` 解锁时和 `form_input` 待提交时都展示可操作的自选知识组件，且不含自选知识节点时不展示。
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-002-07, AC-REQ-004-01_
  - _Verification: Platform vitest, browser smoke_
  - _Depends: T033_
  - _Boundary: Platform `FlowChat` input visibility only_

- [x] T035 Fix Client runtime picker visibility and send guard for dialog and form input
  - Done when: Client 已发布 workflow 页面在 `dialog_input` 解锁时和 `form_input` 待提交时都展示可操作自选知识组件；对话框输入、引导词输入和表单提交都在缺少选择时阻止发送。
  - _Requirements: REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-002-07, AC-REQ-004-01, AC-REQ-006-05_
  - _Verification: Client jest/build_
  - _Depends: T033_
  - _Boundary: Client appChat input visibility and send guard only_

- [x] T036 Update frontend tests for dialog/form input visibility
  - Done when: Platform 和 Client tests 覆盖 `dialog_input` 可见、`form_input` 可见、空闲状态隐藏、只读状态隐藏或禁用的选择器显示合同。
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-06, AC-REQ-002-07, AC-REQ-004-01_
  - _Verification: Platform vitest, Client jest_
  - _Depends: T034, T035_
  - _Boundary: frontend tests only_

- [x] T037 Verify dialog input support
  - Done when: backend pytest、Platform vitest/build、Client jest/build、diff checks 和可用时浏览器冒烟结果写入 `verification.md`。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T036_
  - _Boundary: verification only_

- [x] T038 Update verification evidence after dialog input support
  - Done when: `verification.md` 记录本次对话框输入支持的命令、exit code、浏览器证据、acceptance coverage、未验证项和剩余风险。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T037_
  - _Boundary: docs/spec only_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04 | T004, T009, T025, T026 | V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-001-04 |
| REQ-002 | AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-002-07 | T019, T020, T023, T025, T026, T028, T029, T031, T032, T033, T034, T035, T036, T037, T038 | V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-002-06, V-AC-REQ-002-07 |
| REQ-003 | AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-003-09, AC-REQ-003-10 | T018, T019, T020, T021, T023, T024, T025, T026, T027, T028, T029, T030, T031, T032 | V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-003-07, V-AC-REQ-003-08, V-AC-REQ-003-09, V-AC-REQ-003-10 |
| REQ-004 | AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05 | T018, T019, T020, T021, T023, T024, T025, T026, T027, T028, T029, T030, T031, T032, T033, T034, T035, T036, T037, T038 | V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05 |
| REQ-005 | AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-005-07 | T022, T024, T025, T026 | V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-005-05, V-AC-REQ-005-06, V-AC-REQ-005-07 |
| REQ-006 | AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05 | T018, T019, T020, T021, T022, T023, T024, T025, T026, T029, T030, T032, T035, T037, T038 | V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04, V-AC-REQ-006-05 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- 运行态选择不能作为 websocket input payload 的 top-level key 传入后端，否则 `GraphEngine.continue_run()` 会把它当作节点 ID。实现时应使用当前输入节点数据中的保留字段，并在后端抽取到共享状态。
- 20 文件限制需要后端兜底校验；前端校验只能作为用户体验优化。
- 旧节点 `rag` 和 `knowledge_retriever` 必须作为回归验证对象，避免抽取 helper 时改变固定知识来源行为。
- Platform 运行态入口已确认并接入：`src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatInput.tsx` 负责展示与发送前校验，`ChatPane.tsx` 负责把 `__runtime_knowledge_selection` 放入当前 input node 的 `data`。
- Client 发布页运行态入口已确认并接入：`src/frontend/client/src/pages/appChat/ChatInput.tsx` 展示选择器，`useAreaText.ts` 和 `useWebsocket.ts` 在普通输入与表单提交时提交同一 payload shape。
- P1 review fix: 自选知识节点选择文档知识库时，后端在 `RagUtils.apply_runtime_knowledge_selection()` 固定启用 `_knowledge_auth`，并在 `init_knowledge_retriever()` 通过 `_runtime_selection_required` 强制 `check_auth=True`，避免受节点高级检索开关默认值影响。
- P1 review fix: 已补充后端 runtime 权限兜底、整库/整空间、缺少选择、多个自选节点共享同一选择测试；已补充 Platform 与 Client 选择器组件测试，覆盖知识库文件、知识空间文件/文件夹 payload 与超限状态。
- 2026-06-24 范围变更重构完成：T018-T026 已实现并验证，运行态选择合同升级为 `mode=source/items`；Platform 和 Client 选择器支持树形 source/items 互斥选择、知识空间类型分组、加载态和 20 文件限制；后端支持完整 source、同类型多 source items、旧 shape 兼容和运行时权限兜底。
- 2026-06-24 TAB 互斥调整完成：T027-T032 已实现并验证，Platform 和 Client 选择器使用 `文档知识库` / `知识空间` TAB 区分来源，切换 TAB 清空另一类选择；前端发送前和后端运行态均拒绝同一 `items` payload 混合 knowledge/space。
- 2026-06-24 对话框输入支持完成：T033-T038 已实现并验证，Platform 和 Client 选择器在 `dialog_input` 解锁和 `form_input` 待提交状态都可操作；Client 对话框输入、引导词输入和表单提交统一执行运行态知识选择校验。
