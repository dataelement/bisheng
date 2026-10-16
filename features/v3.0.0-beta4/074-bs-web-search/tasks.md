# Tasks: F074 Existing Tool Invocation

Latest correction confirmed 2026-10-15: remove independent publication management;
all supported existing API tools use tool_key and existing use permission. No
extra Config entries, registration or admin API. Current source/contract is in
spec.md and design.md; T001-T022 below are historical execution records and their
publication-specific implementation was superseded by T023-T026. No Gateway/Work
writes or push. Rollback removes the invocation entry without changing saved tools.

## Wave 1 - Infrastructure and pure contracts

- [x] T001 Infrastructure: common/errcode/dsh.py and dsh/domain/schemas/tool_publications.py; define safe errors and strict limits. No dependency.
- [x] T002 Tests: test/tool/test_published_schema.py and test/dsh/test_tool_results.py; strict schema extraction, overrides, JSON/search validation. Covers AC: AC-05, AC-13, AC-14, AC-15, AC-18, AC-19, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-28, AC-31. Dependency T001.
- [x] T003 Domain: tool/domain/services/published_schema.py and dsh/domain/services/tool_results.py; implement T002 contracts. Dependency T002.

## Wave 2 - Execution and shared state

- [x] T004 Tests: test/tool/test_published_openapi.py and test/dsh/test_tool_leases.py; actual bounded HTTP transport and isolated shared Redis leases. Covers AC: AC-16, AC-19, AC-21, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32. Dependency T003.
- [x] T005 Domain: tool/domain/services/published_openapi.py and tool/domain/services/executor.py; opt-in strict executor factory, safe transport and tracing suppression, legacy defaults preserved. Dependency T004.
- [x] T006 Infrastructure: dsh/infrastructure/tool_leases.py; atomic per-tenant/code admission and owner cleanup. Dependency T004.
- [x] T007 Tests: test/dsh/test_tool_publications.py and test/tool/test_published_tools.py; management/use permissions, tenant facts, snapshots and persistence behavior. Covers AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-10, AC-11, AC-12, AC-15, AC-20, AC-27. Dependency T005, T006.
- [x] T008 Domain persistence: dsh/domain/repositories/tool_publications.py and tool/domain/repositories/published_tools.py; locked atomic Config records and tenant-scoped tool snapshots. Dependency T007.
- [x] T009 Domain: tool/domain/services/published_tools.py; verify tenant/state/schema, edit/use and construct executor from snapshot. Dependency T008.
- [x] T010 Domain: dsh/domain/services/tool_publications.py; management/invocation orchestration and leases. Dependency T009.

## Wave 3 - HTTP admission

- [x] T011 Tests: test/dsh/test_tool_invoke_http.py; generic and admin routes, signed credentials, errors, bounded bodies, disable, tenant isolation. Covers AC: AC-01, AC-02, AC-06, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-16, AC-17, AC-20, AC-27, AC-29, AC-32. Dependency T010.
- [x] T012 API: dsh/api/endpoints/tools.py and dsh/api/endpoints/tool_publications.py; bounded body parsing after auth and disconnect cleanup. Dependency T011.
- [x] T013 API wiring: dsh/api/dependencies.py and dsh/api/endpoints/models.py; shared dependency preserving alias identity. Dependency T012.
- [x] T014 API wiring: dsh/api/router.py and utils/http_middleware.py; narrow invoke registration and credential ownership. Dependency T013.
- [x] T015 Infrastructure: common/middleware/admin_scope.py; narrow publication-management prefix only. Dependency T014.

## Wave 4 - Packaging, e2e and review

- [x] T016 Infrastructure: pyproject.toml and uv.lock; declare the already locked jsonschema runtime dependency without closure upgrades. Dependency T003.
- [x] T017 Localization source: src/frontend/packages/locales/src/api_errors/zh-Hans.json and en.json; new safe error strings only. Dependency T001.
- [x] T018 Localization source: src/frontend/packages/locales/src/api_errors/ja.json; same key coverage, then regenerate artifacts with existing locale tooling. Dependency T017.
- [x] T019 Tests: test/e2e/test_e2e_published_tools.py and feature e2e-report.md; run available HTTP stories and record all AC coverage and unavailable integration environments. Covers AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32. Dependency T015, T016, T018.
- [x] T020 Review: feature task-review.md and code-review.md; check source conventions, arch guard, focused regression, i18n, safe errors, scope and baseline differences. Dependency T019. Commit only feature changes; report local and remote status.

## Implementation Helper Ownership

T003 also owns utils/bounded_json.py. T005 owns utils/private_http_logs.py.
T010 owns dsh/tool_runtime.py lazy composition. T012 owns api/tool_bodies.py and
PublishedToolRoute in api/responses.py. T019 includes the administrative HTTP,
portable SQL repository and test/e2e/helpers fixtures. These support the approved
contracts without additional product scope. T019 is complete for available local
checks; real deployment acceptance remains PARTIAL in e2e-report.md.

## Actual Deviations

2026-10-15: User confirmed removal of search-specific publisher restrictions.
Spec AC-22, AC-23, AC-24, AC-25, AC-26 and design now assign business contracts
to the saved OpenAPI definition and tool service. Tests use real isolated local
Redis, with no production state touched.

## Confirmed Contract Correction

- [x] T021 Remove search argument, publication-schema and result branches; remove
  business-code parameters from schema verification and result normalization.
- [x] T022 Replace search-special tests with generic schema-bound, unchanged-input,
  unchanged-result and alternate-schema HTTP regressions; synchronize current
  spec/design/discovery/release contract and validation evidence.

## Direct Invocation Correction

- [x] T023 Remove publication admin routes, Config repository, input/publication
  models, management scope prefix and associated management/storage tests.
- [x] T024 Resolve existing tool_key through the tool-owned SavedToolRepository
  and SavedToolService; current state/use permission and common ToolLimits only.
  Remove publication parameters/names from production schema and execution helpers.
- [x] T025 Admit first calls through Redis without publication initialization;
  preserve shared capacity, expiry/owner cleanup, fail-closed outages and document
  state-loss operational assumptions. Align credential route/key syntax.
- [x] T026 Regress direct two-tool HTTP calls with no registration, deletion,
  permission/tenant/missing/unsupported cases, real SQL key lookup, Redis and
  legacy DSH/executor behavior. Synchronize all current contracts and locales.

## Focused API Tests

- [x] T027 User requested a narrower test scope. Remove standalone saved-tool SQL,
  service, orchestration and result suites and the published_tools helper. Retain
  five test files for the new API, invocation-schema/transport and Redis bounds;
  use injected existing-tool lookup and MockTransport with no save/publish flow.
  Existing tool CRUD tests are unchanged. Current evidence supersedes historical
  T019/T026 SQL/socket test claims; see e2e-report.md.

## Existing Tool Lookup Reuse

- [x] T028 Supersede T024's separate SavedToolRepository with existing
  GptsToolsDao.aget_tool_by_tool_key / aget_one_tool_type. Reuse the executor's
  existing use-permission check once per invocation; remove duplicate permission
  logic and repository composition. Keep tenant/state checks and API bounds.
  API tests inject existing DAO results and assert one authorization check.
