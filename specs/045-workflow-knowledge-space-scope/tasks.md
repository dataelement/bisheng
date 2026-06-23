# Tasks: Workflow Knowledge Space Retrieval Scope

## Metadata
- Feature ID: `045-workflow-knowledge-space-scope`
- Status: `draft`
- Related requirements: `specs/045-workflow-knowledge-space-scope/requirements.md`
- Related design: `specs/045-workflow-knowledge-space-scope/design.md`
- Created: `2026-06-23`
- Updated: `2026-06-23`

## Task Format

Every implementation task includes:
- Checkbox and stable task ID.
- Requirement ID.
- Acceptance criterion ID when behavioral.
- Verification method or evidence target.
- Boundary when scope-sensitive.

## Phase 1: Contract and Option Source

- [x] T001 Confirm or add authorized knowledge space option API
  - Done when: there is an API wrapper that returns current user's joined or otherwise authorized knowledge spaces with `id`, `name`, search keyword, and pagination/load-more support.
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: Backend/API test or code review of reused endpoint; frontend API wrapper type check._
  - _Boundary: Existing knowledge space API/service and `src/frontend/platform/src/controllers/API/knowledgeSpace.ts`; do not alter knowledge space permission semantics._

- [x] T002 Add knowledge space i18n keys
  - Done when: Platform workflow locale files include labels/placeholders/empty states for `知识空间` selector behavior.
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01, AC-REQ-003-05_
  - _Verification: Locale key lookup review and Platform build._
  - _Depends: T001_
  - _Boundary: `src/frontend/platform/public/locales/*/flow.json` only._

## Phase 2: Frontend Selection Behavior

- [x] T003 Extend `KnowledgeSelectItem` with `space` scope
  - Done when: document knowledge retrieval node shows tabs in order `文档知识库` -> `知识空间` -> `临时知识库`, loads authorized knowledge spaces, supports search/load-more, saves `{ type: "space", value: [...] }`, and preserves existing `knowledge`/`tmp` behavior.
  - _Requirements: REQ-001, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-006-01, AC-REQ-006-05_
  - _Verification: Component test if available; manual node editor check; `cd src/frontend/platform && npm run build`._
  - _Depends: T001, T002_
  - _Boundary: `KnowledgeSelectItem.tsx` and narrowly scoped helper/hook extraction if needed._

- [x] T004 Extend `KnowledgeQaSelectItem` with knowledge space scope
  - Done when: document knowledge QA node can select existing QA knowledge bases or knowledge spaces, supports old array values, saves new scoped values for space, and preserves required validation/search/回显 behavior.
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-05, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-006-02, AC-REQ-006-04_
  - _Verification: Component test if available; manual node editor check; Platform build._
  - _Depends: T001, T002_
  - _Boundary: `KnowledgeQaSelectItem.tsx` and narrowly scoped shared option helper if needed._

- [x] T005 Hide and clear `metadata_filter` for knowledge space scope
  - Done when: selecting `space` in the document knowledge retrieval node hides the metadata filter field, immediately resets its saved value to `{}`, and does not restore old cleared filters when switching back.
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04_
  - _Verification: Frontend test or manual save/reopen check; inspect saved node data._
  - _Depends: T003_
  - _Boundary: `Parameter.tsx`, `MetadataFilter.tsx`, or node form state code only; do not hide metadata filters for unrelated nodes._

- [x] T006 Add frontend compatibility normalization where required
  - Done when: old workflow params for both affected nodes still initialize and save correctly after the new scoped values are introduced.
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: Frontend regression test or manual load of old node JSON; Platform build._
  - _Depends: T003, T004, T005_
  - _Boundary: `flowCompatible.ts`, node template defaults, or local component normalization only._

## Phase 3: Backend Runtime

- [x] T007 Add explicit `space` branch to document retrieval runtime
  - Done when: `RagUtils.init_multi_retriever()` branches explicitly for `knowledge`, `space`, and `tmp`; `space` initializes a knowledge space retriever and never falls through to temporary file retrieval.
  - _Requirements: REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-06, AC-REQ-006-03_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py -k "knowledge_retriever"`._
  - _Depends: T001_
  - _Boundary: `src/backend/bisheng/workflow/common/knowledge.py` and existing knowledge space service calls only._

- [x] T008 Add knowledge space branch to QA retriever runtime
  - Done when: `QARetrieverNode` normalizes old array and new scoped object params, keeps old QA behavior, and uses knowledge space retrieval for `type="space"` without QA-only metadata parsing failures.
  - _Requirements: REQ-002, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-03_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py -k "qa_retriever"`._
  - _Depends: T001, T007_
  - _Boundary: `src/backend/bisheng/workflow/nodes/qa_retriever/qa_retriever.py` and shared normalization helper if needed._

- [x] T009 Add runtime permission and stale-space handling
  - Done when: runtime revalidates selected knowledge space access, handles deleted or unauthorized spaces with explicit node error or empty authorized result as defined in implementation, and never substitutes another retrieval scope.
  - _Requirements: REQ-003, REQ-005_
  - _Acceptance: AC-REQ-003-04, AC-REQ-003-05, AC-REQ-005-06_
  - _Verification: Backend tests with unauthorized/deleted space fixtures or mocks._
  - _Depends: T007, T008_
  - _Boundary: Workflow runtime and existing knowledge space service boundary only._

## Phase 4: Tests and Verification

- [x] T010 Add backend workflow regression tests
  - Done when: tests cover old document knowledge, old temporary knowledge, new document retrieval `space`, old QA array params, new QA `space` params, stale `metadata_filter`, and unauthorized/deleted space behavior.
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-03_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`._
  - _Depends: T007, T008, T009_
  - _Boundary: `src/backend/test/workflow/test_knowledge_space_scope.py` only._

- [x] T011 Add frontend regression coverage or manual checklist
  - Done when: there is frontend test coverage where feasible, or a documented manual checklist for tab order, search, selection, required validation, metadata hide/clear, save/reopen, old workflow load, and single-node debug.
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-05_
  - _Verification: Component tests if existing setup supports them; otherwise manual evidence in implementation verification notes._
  - _Depends: T003, T004, T005, T006_
  - _Boundary: Frontend tests/checklist only._

- [x] T012 Run static and integration verification
  - Done when: backend workflow tests and Platform build/typecheck pass, or failures unrelated to this feature are documented with command output and root cause.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: All acceptance criteria_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`; `cd src/frontend/platform && npm run build` or project-approved equivalent._
  - _Depends: T010, T011_
  - _Boundary: Verification only; no new scope expansion during this task._

- [x] T013 Architecture and compatibility review
  - Done when: review confirms no direct frontend `axios` import, no new UI/state libraries, backend branches preserve existing knowledge/tmp/QA behavior, metadata filter is cleared only for `space`, and old workflow params remain compatible.
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-05, AC-REQ-002-03, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: Code review report or implementation handoff notes._
  - _Depends: T012_
  - _Boundary: Review only; fixes require scoped follow-up tasks._

## Implementation Order Notes
- T003 and T004 can run in parallel after T001/T002 because they touch different components.
- T007 should precede T008 if shared knowledge space retriever initialization is extracted into `RagUtils`.
- T005 should wait for T003 because it depends on a stable active-scope value.
- Verification tasks should not be marked complete until actual command output or manual evidence exists.

## Bugfix Follow-up

- [x] T014 Extend metadata filter hide/clear behavior to `rag`
  - Done when: Platform “文档知识库问答” (`rag`) selecting `space` hides `metadata_filter`, clears the saved `metadata_filter.value`, and restores an empty filter UI when switching back to document knowledge.
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04_
  - _Verification: `cd src/frontend/platform && npm run build`; browser verification on `http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a` without saving. Evidence: build passed in 10.92s; `rag` selecting `space -> 营销` produced `hasMetadataFilter: false`, switching back to document knowledge produced `hasMetadataFilter: true` and `hasSelectedMarketing: false`._
  - _Boundary: `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/Parameter.tsx` and verification docs only; no backend runtime or unrelated selector refactor._

## UX Optimization Follow-up

- [x] T015 Add grouped tree rendering support for knowledge space selector options
  - Done when: the selector can render knowledge space options grouped by `space_level` in the order `公共空间` -> `部门空间` -> `团队空间` -> `个人空间`; group nodes expand/collapse only and are not persisted as selected values.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: `cd src/frontend/platform && npm run build`; browser verification on both affected workflow nodes. Evidence: build passed with `8300 modules transformed`, built in `13.72s`; browser showed `公共空间`、`部门空间`、`团队空间`、`个人空间` in both `knowledge_retriever` and `rag`, and clicking `公共空间` collapsed children without adding selected badges._
  - _Boundary: `src/frontend/platform/src/components/bs-ui/select/multi.tsx`, `KnowledgeSelectItem.tsx`, `KnowledgeQaSelectItem.tsx`, and small local helpers only; preserve existing flat `MultiSelect` behavior._

- [x] T016 Add grouped knowledge space search, loading state, and empty state
  - Done when: searching knowledge spaces keeps grouped display with empty groups hidden; initial load, search, and load-more show visible loading feedback; empty search results show an explicit empty state.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06_
  - _Verification: `cd src/frontend/platform && npm run build`; browser verification using the running workflow editor. Evidence: searching `性能` kept only `个人空间(1)` with `性能`; searching `不存在的知识空间xyz` showed `暂无匹配的知识空间`; request-in-flight state showed `正在加载知识空间...`._
  - _Depends: T015_
  - _Boundary: Knowledge space selector UI and locale files only; do not change workflow runtime loading behavior._

- [x] T017 Update knowledge space selector typing and locale text
  - Done when: Platform API types include `space_level`, and locale files used by the workflow editor include group labels, loading text, and empty text.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-05, AC-REQ-007-06_
  - _Verification: TypeScript build and locale key review. Evidence: `KnowledgeSpaceSummary.space_level` typed; `zh-Hans`/`en-US`/`ja` flow locale files include `knowledgeSpaceLevel`, `loadingKnowledgeSpaces`, and `emptyKnowledgeSpaces`; Platform build passed._
  - _Depends: T015_
  - _Boundary: `src/frontend/platform/src/controllers/API/knowledgeSpace.ts` and workflow locale files only._

- [x] T018 Adapt workflow ORM user for knowledge-space runtime permission checks
  - Done when: workflow knowledge-space retrieval converts database `User` objects into `LoginUser`-compatible objects before invoking `KnowledgeSpaceChatService`, while preserving already-compatible `LoginUser/UserPayload` objects.
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-06, AC-REQ-005-07_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`. Evidence: `11 passed, 8 warnings in 2.81s`;新增覆盖 ORM-like workflow `User` 会适配为具备 `get_user_group_ids()` 的登录用户对象，且已兼容用户对象保持原样。_
  - _Boundary: `src/backend/bisheng/workflow/common/knowledge.py` and `src/backend/test/workflow/test_knowledge_space_scope.py` only; do not change global `BaseNode.init_user_info()` behavior._

- [x] T019 Inject version repository for workflow knowledge-space retrieval
  - Done when: workflow knowledge-space retrieval creates the same version repository dependency that normal FastAPI `KnowledgeSpaceChatService` dependency injection provides, and `aretrieve_chunks()` no longer fails with missing `version_repo`.
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-06, AC-REQ-005-08_
  - _Verification: `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`. Evidence: `12 passed, 8 warnings in 3.81s`;新增覆盖 `retrieve_knowledge_space_documents_sync()` 在调用 `KnowledgeSpaceChatService.aretrieve_chunks()` 前注入 `version_repo`。`uv run ruff check --select I001 bisheng/workflow/common/knowledge.py test/workflow/test_knowledge_space_scope.py` 通过。_
  - _Boundary: `src/backend/bisheng/workflow/common/knowledge.py` and `src/backend/test/workflow/test_knowledge_space_scope.py` only; do not change API dependency factories or knowledge space chat service constructor._

- [x] T020 Prevent knowledge-space selector reopen pagination race
  - Done when: both affected selectors do not issue load-more requests while the first knowledge-space page is still loading, so reopening a selector that defaults to `space` shows the first page instead of `暂无匹配的知识空间`.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07_
  - _Verification: `cd src/frontend/platform && npm run build`; `cd src/frontend/platform && npx vitest run src/test/workflowKnowledgeSpaceSelectorRace.test.tsx`. Evidence: build passed in `14.12s`; Vitest `2 tests` passed in `24ms`, covering both `KnowledgeSelectItem` and `KnowledgeQaSelectItem` reopening on `space` without requesting page 2 before page 1 settles. Browser verification was not completed because the active Chrome tab was running an unrelated user task._
  - _Boundary: `KnowledgeSelectItem.tsx` and `KnowledgeQaSelectItem.tsx`; only touch `MultiSelect` if the race cannot be contained in the callers._
