# Tasks: Developer Token Management and Authentication

## Metadata
- Feature ID: `044-developer-token`
- Status: `draft`
- Related requirements: `specs/044-developer-token/requirements.md`
- Related design: `specs/044-developer-token/design.md`
- Created: `2026-06-10`
- Updated: `2026-06-10`

## Task Format

Every implementation task includes:
- Checkbox and stable task ID.
- Requirement ID.
- Acceptance criterion ID when behavioral.
- Verification method or verification ID.
- Boundary when scope-sensitive or parallel-safe.

## Phase 1: Contract and Foundation

- [x] T001 Register developer token error module code
  - Done when: developer token module code `198` is registered in the project release contract or equivalent registry, with no conflict against existing `181 approval` and `190 channel` assignments.
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-05_
  - _Verification: V-AC-REQ-006-05; review `features/v2.6.0/release-contract.md` or the adopted registry._
  - _Boundary: SDD/release metadata only; do not implement runtime code in this task._

- [x] T002 Create backend developer token package skeleton
  - Done when: backend package directories and empty package markers exist for `developer_token/api`, `developer_token/api/endpoints`, `developer_token/domain/models`, `developer_token/domain/schemas`, `developer_token/domain/repositories`, and `developer_token/domain/services`.
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-04, AC-REQ-006-06_
  - _Verification: Code review confirms package structure matches `design.md` File Structure Plan._
  - _Depends: T001_
  - _Boundary: Package structure only; no endpoint or business behavior._

- [x] T003 Add database migration for `developer_token`
  - Done when: migration creates `developer_token` table with required fields and indexes, and downgrade drops created artifacts safely.
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-REQ-002-06, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: Migration review; `cd src/backend && uv run alembic upgrade head` in a prepared dev DB when available; DM8 compatibility checked in CI/Linux if available._
  - _Depends: T001_
  - _Boundary: `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f044_developer_token.py` only, plus migration registry metadata if required._

- [x] T004 Implement developer token ORM/domain model
  - Done when: SQLModel entity represents all required `developer_token` columns and uses project-compatible field types/defaults.
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-REQ-002-06, AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: Code review and model import test if project test harness supports it._
  - _Depends: T003_
  - _Boundary: `src/backend/bisheng/developer_token/domain/models/developer_token.py` only._

- [x] T005 Define schemas and error codes
  - Done when: request/response/query schemas exist and `common/errcode/developer_token.py` defines `19801` through `19809` developer token errors with stable names and messages.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-03, AC-REQ-003-07, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-006-05_
  - _Verification: Code review; backend import/unit tests once service/API tests are added._
  - _Depends: T001_
  - _Boundary: `domain/schemas/developer_token.py` and `common/errcode/developer_token.py`._

## Phase 2: Repository and Service Test-First Work

- [x] T006 Implement repository data-access tests or repository contract checks
  - Done when: tests or contract checks cover list pagination/keyword behavior, lookup by id, lookup by hash, create, update, logical delete, and last-used update without embedding permission/IP/Redis logic.
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-006-03, AC-REQ-006-06_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_repository.py` if repository tests are introduced; otherwise code-review checklist in implementation PR._
  - _Depends: T004_
  - _Boundary: `src/backend/test/developer_token/` repository-focused tests only._

- [x] T007 Implement `DeveloperTokenRepository`
  - Done when: repository exposes `list_tokens`, `get_token_by_id`, `get_token_by_hash`, `create_token`, `update_token`, `logic_delete_token`, and `update_last_used` as data-access-only methods.
  - _Requirements: REQ-002, REQ-006_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-006-03, AC-REQ-006-06_
  - _Verification: T006 repository checks pass or code review confirms repository contains no permission, IP, Redis, or crypto decisions._
  - _Depends: T004, T006_
  - _Boundary: `src/backend/bisheng/developer_token/domain/repositories/developer_token_repository.py` only._

- [x] T008 Write service tests for admin permissions and lifecycle
  - Done when: service tests cover global super admin management, tenant admin tenant scoping, ordinary user denial, cross-tenant binding denial, create/list/update/delete/secret view behavior, and secret storage constraints.
  - _Requirements: REQ-001, REQ-002, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-008-01_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py`._
  - _Depends: T005, T007_
  - _Boundary: `src/backend/test/developer_token/test_developer_token_service.py`; use mocks/fakes for DAO, Redis, audit, crypto where appropriate._

- [x] T009 Write service tests for global config and override rules
  - Done when: tests cover missing config defaults, global config permission, invalid whitelist rejection, IP override precedence, and rate-limit override precedence.
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py -k "global_config or override or whitelist"`._
  - _Depends: T005, T007_
  - _Boundary: `test_developer_token_service.py`; do not create real external Redis or DB dependencies unless existing fixtures already support them._

- [x] T010 Implement `DeveloperTokenService` management behavior
  - Done when: service implements admin permission checks, user/tenant binding validation, token generation, HMAC hash, encryption/decryption, list/create/update/delete/secret view, global config read/update, whitelist validation, and audit for sensitive actions.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04_
  - _Verification: T008 and T009 pass; code review verifies no raw plaintext storage/logging._
  - _Depends: T008, T009_
  - _Boundary: `src/backend/bisheng/developer_token/domain/services/developer_token_service.py`; no API route wiring._

## Phase 3: Authentication Dependency and Limiter

- [x] T011 Write dependency tests for token authentication failures and success
  - Done when: tests cover missing header, unknown token, disabled token, deleted token, disabled/missing user, invalid tenant, successful `UserPayload`, constrained tenant context, opt-in-only behavior, and best-effort last-used update.
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-004-07, AC-REQ-004-08, AC-REQ-004-09_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py`._
  - _Depends: T010_
  - _Boundary: `src/backend/test/developer_token/test_developer_token_dependency.py`; use an opt-in test route only._

- [x] T012 Write dependency tests for IP whitelist and Redis rate limit
  - Done when: tests cover empty whitelist allow-all, single IP match, CIDR match, IP miss rejection, no-limit semantics, exceeded limit rejection, Redis fail-closed, and key TTL behavior.
  - _Requirements: REQ-003, REQ-005_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py -k "ip or rate or redis"`._
  - _Depends: T010_
  - _Boundary: Dependency tests with fake/mock Redis; no real production Redis mutation._

- [x] T013 Implement developer token authentication dependency
  - Done when: `get_developer_token_user(request: Request) -> UserPayload` delegates to service authentication and is importable by opt-in business APIs.
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-004-07, AC-REQ-004-08, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06_
  - _Verification: T011 and T012 pass._
  - _Depends: T011, T012_
  - _Boundary: `src/backend/bisheng/developer_token/api/dependencies.py` and service auth internals only; do not modify existing business endpoints._

## Phase 4: Backend Admin API Integration

- [x] T014 Write admin API integration tests
  - Done when: API tests cover list, create, update, delete, secret view, global config read/update, role/tenant permission boundaries, response wrappers, and audit assertions.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-07, AC-REQ-006-04, AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py`._
  - _Depends: T010, T013_
  - _Boundary: `src/backend/test/developer_token/test_developer_token_api.py`._

- [x] T015 Implement admin endpoints and router wiring
  - Done when: `/api/v1/admin/developer-tokens` endpoints support list, create, update, delete, secret view, global config read, and global config update, and are registered in the admin/global API router according to project conventions.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-07, AC-REQ-006-04, AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: T014 passes; arch-guard shows no endpoint direct ORM imports._
  - _Depends: T014_
  - _Boundary: `developer_token/api/router.py`, `developer_token/api/endpoints/developer_token.py`, `admin/api/router.py` and/or `api/router.py` registration only._

## Phase 5: Platform Frontend

- [x] T016 Implement Platform API wrapper
  - Done when: `developerToken.ts` exposes typed functions for list, create, update, delete, secret view, global config read, and global config update using the wrapped request module.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07_
  - _Verification: Typecheck/build if available; code review confirms no direct `axios` import except wrapped `@/controllers/request`.
  - _Depends: T015_
  - _Boundary: `src/frontend/platform/src/controllers/API/developerToken.ts` only._

- [x] T017 Implement Developer Token Platform UI component
  - Done when: Developer Token component renders global config panel, token table, create/edit dialog, delete confirmation, secret view confirmation/dialog, form validation hooks, loading/empty states, and error display via existing Platform patterns.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-07, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07_
  - _Verification: Manual Platform checklist; frontend typecheck/build if available.
  - _Depends: T016_
  - _Boundary: `src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx`; split subcomponents/hooks if file would exceed 600 lines._

- [x] T018 Wire System Page tab and i18n
  - Done when: System Page displays Developer Token tab for authorized admin roles, wires the component, and all added strings have zh-Hans/en-US/ja keys as required by project conventions.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: Manual Platform role checks; i18n key lookup review; frontend build/typecheck if available._
  - _Depends: T017_
  - _Boundary: `SystemPage/index.tsx` and Platform locale JSON files only._

## Phase 6: Verification and Review

- [x] T019 Run backend developer token test suite
  - Done when: backend developer token tests pass or failures are documented with root cause and follow-up tasks.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-004-07, AC-REQ-004-08, AC-REQ-004-09, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05, AC-REQ-006-06, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/`._
  - _Depends: T015_
  - _Boundary: Verification only; no new behavior implementation._

- [ ] T020 Run Platform manual verification checklist
  - Done when: manual evidence covers tab visibility, global config visibility/editing, tenant admin restrictions, token create/edit/delete/list, secret view, invalid whitelist error, and disabled token authentication rejection.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07_
  - _Verification: Manual notes/screenshots or `verification.md` entries after implementation._
  - _Depends: T018, T019_
  - _Boundary: Manual verification only; no new behavior implementation._

- [x] T021 Run frontend static verification
  - Done when: Platform build/typecheck/lint command chosen by the project succeeds, or failures unrelated to this feature are documented with evidence.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07_
  - _Verification: Example target `cd src/frontend/platform && npm run build` or project-approved equivalent._
  - _Depends: T018_
  - _Boundary: Verification only; no dependency installation unless separately approved._

- [x] T022 Perform security and architecture review
  - Done when: review confirms no plaintext token persistence/logging, no direct endpoint ORM imports, repository/service boundaries are preserved, Redis fail-closed behavior exists, DM8-incompatible SQL is absent, and no existing endpoint was retrofitted without scope approval.
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-005, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-002-06, AC-REQ-004-09, AC-REQ-005-05, AC-REQ-006-02, AC-REQ-006-06, AC-REQ-008-03_
  - _Verification: Code review report or `/code-review` plus security checklist after implementation._
  - _Depends: T019, T021_
  - _Boundary: Review only; fixes require separate scoped tasks or follow-up commits._

- [x] T023 Update SDD verification artifact after implementation
  - Done when: `specs/044-developer-token/verification.md` records every acceptance criterion as PASS, FAIL, MANUAL_REQUIRED, or NOT_RUN with evidence or skipped reason.
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-003-07, AC-REQ-003-08, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-004-07, AC-REQ-004-08, AC-REQ-004-09, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05, AC-REQ-006-06, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04_
  - _Verification: `specs/044-developer-token/verification.md` exists and references concrete command output/manual evidence._
  - _Depends: T019, T020, T021, T022_
  - _Boundary: SDD verification artifact only._

## Phase 7: Binding UX Change

- [x] T024 Update SDD artifacts for tree user binding
  - Done when: requirements/design/tasks describe tree-based user selection, backend tenant resolution from selected department context, and removal of manual `tenant_id`/`user_id` UI inputs.
  - _Requirements: REQ-002, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-07, AC-REQ-002-08, AC-REQ-007-05, AC-REQ-007-08, AC-REQ-007-09_
  - _Verification: Review `requirements.md`, `design.md`, and `tasks.md` traceability._
  - _Boundary: `specs/044-developer-token/` only._

- [x] T025 Extend tree user selector selection context
  - Done when: the existing Platform tree user selector can return selected department context along with the selected user while preserving backward compatibility for existing callers.
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-05, AC-REQ-007-08, AC-REQ-007-09_
  - _Verification: `cd src/frontend/platform && npm run build`; code review of selector call sites._
  - _Depends: T024_
  - _Boundary: `src/frontend/platform/src/components/bs-comp/selectComponent/DepartmentUsersSelect.tsx` and wrapper types only._

- [x] T026 Replace manual Developer Token binding inputs with tree user picker
  - Done when: Developer Token create/edit dialog uses single-select tree user picker, hides manual `tenant_id`/`user_id` inputs, validates selected user and department context, and submits no manual tenant id.
  - _Requirements: REQ-002, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-07, AC-REQ-007-05, AC-REQ-007-08, AC-REQ-007-09_
  - _Verification: `cd src/frontend/platform && npm run build`; manual UI checklist remains required._
  - _Depends: T025_
  - _Boundary: `src/frontend/platform/src/controllers/API/developerToken.ts`, `src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx`, and locale keys only._

- [x] T027 Resolve token tenant from selected department in backend
  - Done when: create/update schemas accept selected department context, service resolves tenant from that department, validates user membership and admin scope, and persists resolved `tenant_id`.
  - _Requirements: REQ-001, REQ-002, REQ-006_
  - _Acceptance: AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-07, AC-REQ-002-08, AC-REQ-006-04_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/`._
  - _Depends: T024_
  - _Boundary: `src/backend/bisheng/developer_token/domain/schemas/developer_token.py`, `src/backend/bisheng/developer_token/domain/services/developer_token_service.py`, and API tests._

- [x] T028 Add binding regression tests
  - Done when: tests cover create/update payloads without `tenant_id`, selected department tenant resolution, rejected mismatched user/department, and API payload forwarding.
  - _Requirements: REQ-001, REQ-002, REQ-007_
  - _Acceptance: AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-07, AC-REQ-002-08, AC-REQ-007-09_
  - _Verification: `cd src/backend && uv run pytest test/developer_token/`._
  - _Depends: T027_
  - _Boundary: `src/backend/test/developer_token/` only._

- [x] T029 Refresh verification after binding UX change
  - Done when: `verification.md` records backend tests, frontend build, arch guard, and remaining manual UI requirements for the tree picker workflow.
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-03, AC-REQ-002-07, AC-REQ-002-08, AC-REQ-007-05, AC-REQ-007-08, AC-REQ-007-09_
  - _Verification: `specs/044-developer-token/verification.md` evidence entries._
  - _Depends: T025, T026, T027, T028_
  - _Boundary: Verification artifact only._

## Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | T008, T010, T014, T015, T017, T019, T022, T023, T027, T028, T029 | Backend service/API tests, Platform manual checks, review |
| REQ-002 | AC-REQ-002-01..08 | T003, T004, T006, T007, T008, T010, T014, T015, T017, T019, T022, T023, T024, T026, T027, T028, T029 | Backend service/API/repository tests, migration/code review |
| REQ-003 | AC-REQ-003-01..08 | T009, T010, T012, T013, T014, T015, T017, T019, T023 | Backend service/dependency/API tests, Platform manual checks |
| REQ-004 | AC-REQ-004-01..09 | T011, T013, T019, T022, T023 | Backend dependency tests, regression review |
| REQ-005 | AC-REQ-005-01..06 | T012, T013, T019, T022, T023 | Backend dependency/limiter tests |
| REQ-006 | AC-REQ-006-01..06 | T001, T002, T003, T004, T005, T006, T007, T014, T015, T019, T022, T023, T027, T029 | Migration/code review, backend tests, arch review |
| REQ-007 | AC-REQ-007-01..09 | T016, T017, T018, T020, T021, T023, T024, T025, T026, T028, T029 | Platform manual checklist, frontend static verification |
| REQ-008 | AC-REQ-008-01..04 | T008, T010, T014, T015, T019, T022, T023 | Backend API/service tests, audit/log review |

## Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## Implementation Notes
- This spec intentionally does not implement production code.
- Before implementation, re-read `requirements.md`, `design.md`, this `tasks.md`, and directly related backend/frontend files.
- If implementation changes scope, update `requirements.md` and `design.md` before continuing.
- If the project later requires `features/v2.6.0/044-developer-token/` artifacts in addition to this `/sdd-spec` layout, create a separate sync/update task rather than silently duplicating sources of truth.
