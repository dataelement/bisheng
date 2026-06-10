# Design: Developer Token Management and Authentication

## Metadata
- Feature ID: `044-developer-token`
- Status: `draft`
- Related requirements: `specs/044-developer-token/requirements.md`
- Created: `2026-06-10`
- Updated: `2026-06-10`

## Context
- Existing architecture:
  - Backend: FastAPI + SQLModel + Redis + tenant ContextVar architecture.
  - Backend DDD rule: `Router -> Endpoint -> Service -> Repository -> DB`.
  - Admin APIs currently aggregate under `src/backend/bisheng/admin/api/router.py`.
  - Auth-injected user identity is `UserPayload` from `src/backend/bisheng/common/dependencies/user_deps.py`.
  - Tenant isolation uses `current_tenant_id`, `visible_tenant_ids`, and SQLAlchemy tenant filters in `src/backend/bisheng/core/context/tenant.py`.
  - Platform system management page is `src/frontend/platform/src/pages/SystemPage/index.tsx`.
  - Platform API wrappers use `src/frontend/platform/src/controllers/request.ts` and API modules under `src/frontend/platform/src/controllers/API/`.
- Relevant files inspected:
  - `/Users/wenruli/Desktop/044-developer-token/development-implementation.md`
  - `features/v2.6.0/release-contract.md`
  - `features/_templates/spec.md`
  - `features/_templates/tasks.md`
  - `features/v2.6.0/026-channel-active-authorization/spec.md`
  - `src/backend/CLAUDE.md`
  - `src/backend/bisheng/common/dependencies/user_deps.py`
  - `src/backend/bisheng/core/context/tenant.py`
  - `src/backend/bisheng/admin/api/router.py`
  - `src/backend/bisheng/admin/domain/services/tenant_scope.py`
  - `src/backend/bisheng/common/errcode/admin_scope.py`
  - `src/frontend/platform/src/pages/SystemPage/index.tsx`
  - `src/frontend/platform/src/controllers/API/admin.ts`
  - `src/frontend/platform/src/controllers/API/index.ts`
- Existing tests or validation commands:
  - Backend tests: `cd src/backend && uv run pytest test/<module>/...`
  - New backend tests should be placed under `src/backend/test/developer_token/`.
  - Platform verification is primarily manual for this feature unless existing local tooling is extended.
- Constraints from project guidance:
  - No production code edits in this spec-only phase.
  - Backend must support MySQL and DM8; avoid MySQL-only JSON types and JSON query functions.
  - Do not write manual tenant filter conditions as permission substitutes.
  - Do not import `bisheng.database.models.*` directly in endpoints.
  - Frontend Platform must use TypeScript, functional components, `@/controllers/request.ts`, `bs-ui`, existing i18n, and no new UI/state libraries.
  - 403 handling is automatic in frontend response interceptors.

## Goals / Non-Goals

### Goals
- Provide a backend developer-token domain module with admin management APIs and opt-in authentication dependency.
- Persist developer tokens safely with hash lookup, encrypted secret storage, and no raw plaintext database storage.
- Enforce admin authorization, tenant boundaries, IP whitelist, Redis rate limiting, and audit logging.
- Expose Platform System Page UI for authorized admins to manage tokens and global config.
- Keep existing JWT and non-opt-in endpoints behavior unchanged.
- Produce a task plan that can be implemented and verified incrementally.

### Non-Goals
- Do not bulk retrofit existing business APIs to use developer token dependency.
- Do not implement WebSocket developer token support.
- Do not add token rotation/regeneration in this phase.
- Do not introduce a new first-level Platform menu.
- Do not introduce a new state management or UI library.
- Do not add a separate global developer token config table.

## Boundary Commitments
- Owns:
  - Developer token domain model, repository, service, API endpoints, dependency, error codes, migration, tests, Platform API wrapper, Platform Developer Token UI, and i18n keys.
- Does not own:
  - Existing JWT authentication behavior.
  - Existing `/api/v1` and `/api/v2` endpoints unless later tasks explicitly opt in.
  - WebSocket authentication.
  - General permission engine or tenant middleware architecture.
- Allowed dependencies:
  - `UserPayload`, tenant ContextVar helpers, Redis manager/client, existing `ConfigDao`, existing audit log DAO/service, existing user/tenant models or services, existing response wrapper, existing request IP helper, Platform `bs-ui` components, Platform wrapped request module.
- Revalidation triggers:
  - Any change to error code allocation, tenant admin semantics, config table API, audit log schema, Redis client interface, Platform System Page role flags, or release contract module assignments.

## Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | Admin permission gate in `DeveloperTokenService`; `/api/v1/admin/developer-tokens` endpoints; Platform tab visibility | Backend API/service tests + Platform manual checks |
| REQ-002 | AC-REQ-002-01..08 | Token lifecycle APIs, selected-department tenant resolution, repository, encryption/hash helpers, audit logging | Backend service/API tests + code review |
| REQ-003 | AC-REQ-003-01..08 | Global config via `config` table; override merge rules; whitelist/rate validation | Backend service/dependency tests + Platform manual checks |
| REQ-004 | AC-REQ-004-01..09 | `get_developer_token_user` dependency and `DeveloperTokenService.authenticate` flow | Backend dependency tests + regression review |
| REQ-005 | AC-REQ-005-01..06 | `ipaddress` whitelist evaluation; Redis minute counter | Backend dependency/service tests |
| REQ-006 | AC-REQ-006-01..06 | Migration, ORM/domain model, repository boundary, API contract, error code module `198` | Migration/code review + backend tests |
| REQ-007 | AC-REQ-007-01..09 | Platform API module, System Page tab, DeveloperToken component, tree user picker, dialogs, i18n | Manual UI verification + backend API tests |
| REQ-008 | AC-REQ-008-01..04 | Audit actions and no-secret logging policy; emergency disable behavior | Backend tests + code/log review |

## Architecture
- Pattern:
  - Backend DDD module: `developer_token/{api,domain}`.
  - API layer handles request/response wiring and delegates to service.
  - Service layer owns permission checks, token generation, crypto, config merge, IP validation, Redis limiting, tenant ContextVar setup, `UserPayload` construction, and audit logging.
  - Repository layer owns only data access for developer token records.
  - Global config uses existing `config` table and remains a service concern.
  - Platform UI uses System Page tab composition and API wrapper functions.
- Rationale:
  - A dedicated module avoids mixing developer token concerns into existing JWT or open endpoint modules.
  - Service-owned business logic keeps repository testable and complies with DDD layering.
  - Hash lookup avoids decrypt-and-scan and supports a unique index.
  - Encrypted secret storage supports the explicit secret-view requirement while reducing database leak impact.
  - Opt-in dependency prevents behavior changes to existing endpoints.
- Preserved existing patterns:
  - Admin namespace aggregation under `/api/v1/admin`.
  - `UserPayload` dependency semantics for business code.
  - Tenant ContextVar and SQLAlchemy event-based tenant filtering.
  - `resp_200` / project business error response conventions.
  - Platform `bs-ui`, `useTranslation`, and wrapped request module.
- Architecture change justification, if any:
  - Introduces a new backend top-level DDD module because developer tokens span admin API, authentication dependency, persistence, and operational controls and do not fit cleanly inside existing `admin` or `open_endpoints` modules.

## File Structure Plan
| Path | Create / Modify | Responsibility | Requirements |
|---|---|---|---|
| `features/v2.6.0/release-contract.md` or equivalent project registry | modify | Register developer token module code `198` if implementation uses it | REQ-006 |
| `src/backend/bisheng/developer_token/__init__.py` | create | Developer token module package marker | REQ-006 |
| `src/backend/bisheng/developer_token/api/__init__.py` | create | API package marker | REQ-006 |
| `src/backend/bisheng/developer_token/api/router.py` | create | Aggregate developer token admin endpoints | REQ-006 |
| `src/backend/bisheng/developer_token/api/dependencies.py` | create | Expose `get_developer_token_user` dependency | REQ-004 |
| `src/backend/bisheng/developer_token/api/endpoints/developer_token.py` | create | Admin token/config endpoints under `/api/v1/admin/developer-tokens` | REQ-001, REQ-002, REQ-003, REQ-008 |
| `src/backend/bisheng/developer_token/domain/models/developer_token.py` | create | SQLModel developer token entity | REQ-002, REQ-006 |
| `src/backend/bisheng/developer_token/domain/schemas/developer_token.py` | create | Request/response/query schemas | REQ-001, REQ-002, REQ-003, REQ-007 |
| `src/backend/bisheng/developer_token/domain/repositories/developer_token_repository.py` | create | Data access only for developer token records | REQ-002, REQ-006 |
| `src/backend/bisheng/developer_token/domain/services/developer_token_service.py` | create | Management, auth, crypto, config, whitelist, limiter, audit business logic | REQ-001..REQ-008 |
| `src/backend/bisheng/common/errcode/developer_token.py` | create | `198xx` developer token business errors | REQ-001, REQ-004, REQ-005, REQ-006 |
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f044_developer_token.py` | create | Create/drop `developer_token` table and indexes | REQ-006 |
| `src/backend/bisheng/api/router.py` | modify | Include developer token/admin router as project convention requires | REQ-006 |
| `src/backend/bisheng/admin/api/router.py` | modify | Include developer token admin endpoints if admin aggregation is chosen | REQ-001, REQ-006 |
| `src/backend/test/developer_token/test_developer_token_service.py` | create | Service unit tests | REQ-001, REQ-002, REQ-003, REQ-008 |
| `src/backend/test/developer_token/test_developer_token_api.py` | create | Admin API tests | REQ-001, REQ-002, REQ-003, REQ-006, REQ-008 |
| `src/backend/test/developer_token/test_developer_token_dependency.py` | create | Authentication dependency, tenant context, IP, Redis tests | REQ-004, REQ-005 |
| `src/frontend/platform/src/controllers/API/developerToken.ts` | create | Platform API wrapper for developer token admin APIs | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | create | Developer Token tab UI container and subcomponents | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/index.tsx` | modify | Add Developer Token tab and access gating | REQ-007 |
| `src/frontend/platform/public/locales/zh-Hans/bs.json` | modify | Chinese i18n keys | REQ-007 |
| `src/frontend/platform/public/locales/en-US/bs.json` | modify | English i18n keys | REQ-007 |
| `src/frontend/platform/public/locales/ja/bs.json` | modify if present/required | Japanese i18n keys | REQ-007 |

## Components and Interfaces

### DeveloperToken API endpoints
- Responsibility: Expose management operations for authorized admins.
- Inputs: `UserPayload`, pagination/query parameters, create/update/config payloads, token id path parameters, request metadata for audit.
- Outputs: Project-standard success response with `PageData`, token creation result, token detail, secret view result, or global config.
- Dependencies: `DeveloperTokenService`, `UserPayload.get_login_user` or tenant-admin-compatible dependency, request IP helper, response wrapper.
- Error behavior: Converts domain/business errors to project-standard error responses. Does not catch generic exceptions as intentional business responses.
- Requirements: REQ-001, REQ-002, REQ-003, REQ-006, REQ-008.

### DeveloperTokenService
- Responsibility: Own developer token business logic.
- Inputs: Operator `UserPayload`, request payloads, token id, raw request/token header, request IP/user-agent context.
- Outputs: DTO responses, authenticated `UserPayload`, validation errors.
- Dependencies: `DeveloperTokenRepository`, `ConfigDao`, Redis client, user/tenant data access, audit log DAO/service, tenant ContextVar helpers, crypto utilities, `ipaddress`.
- Error behavior: Raises `DeveloperToken*Error` subclasses for expected failures. Logs best-effort last-used update failure without breaking successful authentication.
- Requirements: REQ-001..REQ-008.
- Binding behavior: Create/update payloads carry `user_id` plus selected department context. The service resolves the tenant from the selected department using existing department mount ancestry semantics, verifies the user belongs to that department and resolved tenant, then applies admin-scope checks before persisting `tenant_id`.

### DeveloperTokenRepository
- Responsibility: Encapsulate database access for `developer_token` rows.
- Inputs: Query filters, token id, token hash, create/update row values.
- Outputs: Domain model rows and pagination count.
- Dependencies: SQLModel/SQLAlchemy session.
- Error behavior: No permission or business decisions; database errors propagate.
- Requirements: REQ-002, REQ-006.

### Developer token authentication dependency
- Responsibility: Provide `get_developer_token_user(request: Request) -> UserPayload` for opt-in business APIs.
- Inputs: FastAPI `Request` with `X-Developer-Token` header.
- Outputs: Bound `UserPayload` and tenant ContextVars set for downstream business logic.
- Dependencies: `DeveloperTokenService.authenticate`.
- Error behavior: Missing, invalid, disabled, forbidden IP, rate limit, and limiter unavailable errors fail the request.
- Requirements: REQ-004, REQ-005.

### Global config handler
- Responsibility: Read/update `developer_token_global_config` stored as JSON string in existing `config` table.
- Inputs: Global config DTO with `ip_whitelist` and `rate_limit_per_minute`.
- Outputs: Normalized config DTO.
- Dependencies: Existing `ConfigDao` methods; JSON parsing/serialization; whitelist validator.
- Error behavior: Missing config returns defaults. Invalid JSON stored in DB should be logged and fail safely rather than silently ignored unless a migration/repair path is specified.
- Requirements: REQ-003.

### Platform DeveloperToken component
- Responsibility: Render Developer Token tab with global config panel, token table, create/edit dialog, delete confirmation, secret view confirmation/dialog.
- Inputs: Current user context, API responses, form state.
- Outputs: User-visible table/dialog state and API mutations.
- Dependencies: `@/controllers/API/developerToken`, `bs-ui`, `useTranslation`, existing toast/confirm utilities.
- Error behavior: Uses existing request error handling and toast/confirm patterns. Does not add custom 403 branches.
- Requirements: REQ-007.
- Binding UI: Uses the existing organization-tree user selector in single-select mode. The dialog does not render editable `tenant_id` or `user_id` fields. The selected option must preserve the selected department id/business id so the backend can resolve the trusted tenant.

## Data / State Changes
- Entities:
  - New `developer_token` table.
  - Existing `config` table key: `developer_token_global_config`.
  - Existing audit log table receives developer token action rows.
- Persistence changes:
  - `developer_token` fields:
    - `id`: integer primary key.
    - `tenant_id`: indexed, not null.
    - `user_id`: indexed, not null.
    - `name`: string length 128, not null.
    - `token_hash`: string length 128, unique, not null.
    - `token_ciphertext`: large text, not null.
    - `token_prefix`: string length 16, indexed.
    - `enabled`: boolean, default true.
    - `override_ip_whitelist`: boolean, default false.
    - `ip_whitelist`: large text, nullable.
    - `override_rate_limit`: boolean, default false.
    - `rate_limit_per_minute`: integer, nullable.
    - `last_used_time`: datetime, nullable.
    - `last_used_ip`: string length 64, nullable.
    - `created_by`: integer, nullable.
    - `updated_by`: integer, nullable.
    - `logic_delete`: integer, default 0.
    - `create_time`: datetime, not null.
    - `update_time`: datetime, not null.
  - Indexes:
    - Unique index on `token_hash`.
    - Indexes on `tenant_id`, `user_id`, and `token_prefix`.
- Migration or rollback:
  - Upgrade creates table and indexes.
  - Global config row may be inserted by migration or returned as default by service on first read. If migration inserts it, downgrade must remove it.
  - Downgrade drops indexes and table. In production use, direct downgrade after issuance is unsafe unless tokens are disabled/retired first.
- Compatibility:
  - Use dual-DB-compatible text/date/default helpers available in the project.
  - Do not use SQLAlchemy JSON or MySQL JSON functions for config or whitelist querying.
  - Multi-tenant filtering must remain event-driven; token hash lookup can use tenant-filter bypass only for authentication lookup, with service enforcing bound tenant semantics after match.

## Testing Strategy
| Acceptance ID | Test Type | Target | Notes |
|---|---|---|---|
| AC-REQ-001-01..05 | unit/integration/manual | `test_developer_token_service.py`, `test_developer_token_api.py`, Platform manual role checks | Cover super admin, tenant admin, ordinary user, global config permissions |
| AC-REQ-002-01..06 | unit/integration/code review | service/API tests and ORM review | Verify plaintext never appears in list or DB columns |
| AC-REQ-003-01..08 | unit/integration/manual | service/dependency tests, Platform invalid form check | Cover override merge semantics and missing global config defaults |
| AC-REQ-004-01..09 | integration/regression | `test_developer_token_dependency.py` | Include opt-in-only regression review |
| AC-REQ-005-01..06 | unit/integration | dependency/service limiter tests | Use fake Redis or mock Redis client |
| AC-REQ-006-01..06 | migration/code review/integration | migration file, repository tests, API tests | DM8 validation through CI/Linux if available |
| AC-REQ-007-01..07 | manual/API regression | Platform System Page | Manual verification checklist required |
| AC-REQ-008-01..04 | integration/code review | API audit tests, log review, dependency disabled-token test | Ensure no plaintext token in audit/logs |

## Decisions

### Decision: Use `X-Developer-Token` request header
- Context: Existing JWT uses Authorization/cookies; external token authentication must not be confused with JWT.
- Options considered: Reuse `Authorization: Bearer`, add `X-Developer-Token`.
- Decision: Use `X-Developer-Token`.
- Rationale: Keeps developer tokens separate from JWT semantics and opt-in dependency explicit.
- Consequences: External callers must add a custom header; API docs must document it.

### Decision: Token identity maps to bound `UserPayload`
- Context: Business endpoints expect `UserPayload`.
- Options considered: Introduce new token principal type, return bound `UserPayload`.
- Decision: Return bound `UserPayload`.
- Rationale: Minimizes changes for opt-in business APIs and matches source requirement.
- Consequences: Service must ensure tenant context is constrained to token-bound tenant.

### Decision: Resolve token tenant from selected organization-tree position
- Context: Users may belong to multiple tenants, and manual `tenant_id` / `user_id` entry is error-prone. The UI should select a concrete user position in the organization tree without trusting a frontend tenant id.
- Options considered: Manual tenant/user IDs, frontend-derived tenant id, backend-derived tenant from selected department context.
- Decision: The management UI submits `user_id` plus selected department context. The backend resolves and persists `tenant_id` from the selected department position.
- Rationale: Keeps persisted token binding explicit while removing manual ID entry and preventing frontend tenant spoofing.
- Consequences: The tree selector must expose selected department context, and the service must validate user-department membership, resolved tenant activity, and admin authority.

### Decision: Store encrypted token secret plus HMAC hash
- Context: Secret view is required, but raw token storage is unsafe.
- Options considered: Store raw token, store only hash and show token once, store encrypted ciphertext plus hash.
- Decision: Store encrypted ciphertext plus HMAC-SHA256 hash and prefix.
- Rationale: Enables secret view while avoiding raw DB plaintext and efficient lookup.
- Consequences: Requires stable server-side secret management and audit on secret view.

### Decision: Use existing `config` table for global developer token config
- Context: Global config is small and independent.
- Options considered: New table, existing `config` table key.
- Decision: Use `developer_token_global_config` key in existing `config` table.
- Rationale: Avoids unnecessary schema for a simple global runtime setting and follows source implementation document.
- Consequences: Service must validate JSON schema and whitelist format because `config.value` is unstructured.

### Decision: Per-token override flags control config precedence
- Context: Empty whitelist and null/0 rate limit are meaningful values.
- Options considered: Infer override from non-empty fields, explicit override flags.
- Decision: Use explicit `override_ip_whitelist` and `override_rate_limit` flags.
- Rationale: Distinguishes "use global" from "override to allow all/no limit".
- Consequences: UI must expose override switches clearly.

### Decision: Redis limiter fails closed
- Context: External opt-in APIs may be exposed to untrusted callers.
- Options considered: Fail open on Redis outage, fail closed.
- Decision: Fail closed with `19806 developer_token_limiter_unavailable`.
- Rationale: Security and abuse prevention have priority for external token authentication.
- Consequences: Redis outage can reduce availability for opt-in endpoints.

### Decision: Do not retrofit existing endpoints in this phase
- Context: Existing endpoints have their own auth behavior and regression risk.
- Options considered: Provide dependency only, also update selected existing endpoints.
- Decision: Provide dependency only.
- Rationale: Keeps this feature low-impact and avoids unintended behavior changes.
- Consequences: Business APIs must explicitly opt in later.

### Decision: Use module error code `198`
- Context: Source document proposed `181`, but v2.6.0 release contract already assigns `181` to approval.
- Options considered: Keep `181`, choose unused `198`.
- Decision: Use `198` for developer token spec.
- Rationale: Avoids module code collision.
- Consequences: Release contract or equivalent registry must be updated before implementation.

## Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| Secret view leaks token to authorized operator | External APIs can be called by copied token | Encrypt at rest, audit secret view, show prefix in lists, confirm before viewing | Backend + Frontend |
| Redis outage blocks opt-in API calls | Availability impact for external callers | Document fail-closed policy; operators can monitor Redis and disable/adjust token usage | Backend + Ops |
| Tenant ContextVar leakage | Requests could execute under wrong tenant | Use request-scoped dependency carefully, tests assert context, reset behavior where needed | Backend |
| DM8 incompatibility | CI/customer DB failure | Use compatible field types/defaults and CI/Linux DM8 validation | Backend |
| Error code registry not updated | Conflicting errors in implementation | Register `198` before/with implementation task | Backend |
| Existing endpoints accidentally changed | Regression in JWT/open endpoints | Keep opt-in dependency unreferenced by existing routes unless separately scoped | Backend |
| Config JSON corruption | Global config read failure or unsafe defaults | Validate on save; fail safely/log on invalid stored value; test default behavior | Backend |

## Acceptance Coverage Detail
| Acceptance ID | Design Element | Verification Strategy |
|---|---|---|
| AC-REQ-001-01 | Admin permission gate allows global super admin cross-tenant management | Backend API/service test |
| AC-REQ-001-02 | Tenant admin scope restriction in service query and mutation paths | Backend API/service test |
| AC-REQ-001-03 | Ordinary user denial through admin permission gate | Backend API test |
| AC-REQ-001-04 | User-tenant binding validation for tenant admin create/update | Backend service test |
| AC-REQ-001-05 | Global config super-admin-only service and UI behavior | Backend API test + manual UI check |
| AC-REQ-002-01 | Token create flow with generated secret response | Backend service/API test |
| AC-REQ-002-02 | Token list DTO omits plaintext and includes metadata | Backend API test |
| AC-REQ-002-03 | Token update flow excludes direct token value changes | Backend API/service test |
| AC-REQ-002-04 | Logical delete plus auth invalidation | Backend API/dependency test |
| AC-REQ-002-05 | Secret view permission and audit path | Backend API test |
| AC-REQ-002-06 | Hash/ciphertext/prefix storage only | Model/repository review + service test |
| AC-REQ-002-07 | Multi-tenant user binds through selected department | Service test |
| AC-REQ-002-08 | Invalid selected department/user relation rejected | Service test |
| AC-REQ-003-01 | Empty global whitelist allow-all rule | Dependency test |
| AC-REQ-003-02 | Empty/null/zero global rate limit no-limit rule | Dependency test |
| AC-REQ-003-03 | Token uses global whitelist when not overridden | Service test |
| AC-REQ-003-04 | Token whitelist override precedence | Service test |
| AC-REQ-003-05 | Token uses global rate limit when not overridden | Service test |
| AC-REQ-003-06 | Token rate-limit override precedence | Service test |
| AC-REQ-003-07 | Invalid whitelist validation error | Service/API test + manual UI check |
| AC-REQ-003-08 | Missing global config default response | Service test |
| AC-REQ-004-01 | Missing `X-Developer-Token` rejection | Dependency test |
| AC-REQ-004-02 | Unknown/deleted token rejection | Dependency test |
| AC-REQ-004-03 | Disabled token rejection | Dependency test |
| AC-REQ-004-04 | Invalid bound user rejection | Dependency test |
| AC-REQ-004-05 | Invalid bound tenant rejection | Dependency test |
| AC-REQ-004-06 | Successful auth returns bound `UserPayload` | Dependency test |
| AC-REQ-004-07 | Successful auth sets constrained tenant context | Dependency test |
| AC-REQ-004-08 | Best-effort last-used update behavior | Dependency test |
| AC-REQ-004-09 | Non-opt-in endpoint behavior unchanged | Regression review/test |
| AC-REQ-005-01 | Single-IP whitelist match | Dependency test |
| AC-REQ-005-02 | CIDR whitelist match | Dependency test |
| AC-REQ-005-03 | Whitelist miss rejection | Dependency test |
| AC-REQ-005-04 | Rate limit exceeded rejection | Dependency test |
| AC-REQ-005-05 | Redis limiter failure fails closed | Dependency test |
| AC-REQ-005-06 | Redis key and TTL behavior | Dependency test with fake/mock Redis |
| AC-REQ-006-01 | `developer_token` table fields | Migration/model review |
| AC-REQ-006-02 | Dual-DB-compatible migration | Migration review + CI |
| AC-REQ-006-03 | Tenant-filter-safe token hash lookup | Dependency/repository test |
| AC-REQ-006-04 | Admin API mounted under `/api/v1/admin/developer-tokens` | API test |
| AC-REQ-006-05 | Error module code `198` | Code/release contract review |
| AC-REQ-006-06 | Repository data-access-only boundary | Code review + repository tests |
| AC-REQ-007-01 | Developer Token tab visibility | Manual UI check |
| AC-REQ-007-02 | Global config panel visible/editable for super admin | Manual UI check |
| AC-REQ-007-03 | Global config hidden/read-only for tenant admin | Manual UI check + API test |
| AC-REQ-007-04 | Token table columns | Manual UI check |
| AC-REQ-007-05 | Create/edit dialog and field validation with tree user selection | Manual UI check |
| AC-REQ-007-06 | Secret view confirmation and dialog | Manual UI check |
| AC-REQ-007-07 | Invalid whitelist UI error | Manual UI check + API test |
| AC-REQ-007-08 | Manual `tenant_id`/`user_id` inputs removed | Manual UI check + code review |
| AC-REQ-007-09 | Frontend payload carries user and department context, not manual tenant id | Code review + build |
| AC-REQ-008-01 | Audit for token create/update/delete/secret view | Backend API test |
| AC-REQ-008-02 | Audit for global config update | Backend API test |
| AC-REQ-008-03 | No plaintext token in denial logs/audit | Code/log review |
| AC-REQ-008-04 | Emergency disable behavior | Dependency test + manual operation note |

## Design Quality Gate
- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Every changed file has one clear responsibility.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
