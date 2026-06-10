# Requirements: Developer Token Management and Authentication

## Metadata
- Feature ID: `044-developer-token`
- Status: `draft`
- Mode: `spec-only`
- Created: `2026-06-10`
- Updated: `2026-06-10`
- Source request: `/Users/wenruli/Desktop/044-developer-token/development-implementation.md`

## Intake Summary
- Problem: External callers need a non-JWT developer token mechanism for selected business APIs, while administrators need a controlled way to manage those tokens.
- Current state: BiSheng uses FastAPI, SQLModel, Redis, tenant ContextVar isolation, JWT login, admin management APIs under `/api/v1/admin`, and external RPC endpoints under `/api/v2`. No dedicated developer token management or dependency exists.
- Target outcome: Administrators can manage developer tokens from the Platform system page; selected business APIs can opt in to `X-Developer-Token` authentication and receive a bound `UserPayload` with a constrained tenant context.
- Affected users/systems: Global super admins, tenant admins, ordinary users without management rights, external API callers, opt-in business API endpoints, Redis limiter, audit log, Platform system management UI.
- Requested stopping point: `tasks.md`.

## Scope

### Includes
- Platform System Page adds a Developer Token tab.
- Backend admin APIs support token list, create, update, logical delete, and secret view.
- Each token persists one resolved `tenant_id` and one `user_id`, but management UI does not expose manual tenant/user ID input.
- Token create/update binds a user through organization-tree selection; the request carries selected `user_id` plus selected department context, and the backend resolves the trusted tenant.
- Global developer token config supports IP whitelist and per-minute rate limit.
- Per-token IP whitelist and rate limit can override global config.
- FastAPI dependency authenticates `X-Developer-Token` for APIs that explicitly opt in.
- IP whitelist supports single IP and CIDR rules.
- Redis enforces per-minute rate limiting and fails closed when unavailable.
- Token storage uses hash for lookup and encrypted ciphertext for secret view; plaintext token is never stored raw.
- Management operations and secret view enforce admin permissions and write audit logs.
- Backend implementation follows DDD layering and MySQL/DM8 compatibility rules.
- Platform frontend uses existing `src/frontend/platform/` conventions only.

### Excludes
- No bulk retrofit of existing `/api/v1` or `/api/v2` business APIs.
- No change to existing JWT login or session flow.
- No WebSocket developer token authentication.
- No token automatic rotation or regeneration endpoint in this phase.
- No new first-level menu; entry stays under the System Page tab.
- No new independent global config table; global config uses existing `config` table semantics.
- No direct production code implementation in this spec-only phase.

## Requirements

### REQ-001: Admin visibility and authorization
As a `global super admin or tenant admin`, I want developer token management to respect my management scope, so that tokens cannot be managed across unauthorized tenant boundaries.

#### Acceptance Criteria
- `AC-REQ-001-01`: WHEN a global super admin opens developer token management THEN the system SHALL allow listing and managing developer tokens across all tenants.
- `AC-REQ-001-02`: WHEN a tenant admin opens developer token management THEN the system SHALL show and allow management only for developer tokens belonging to that tenant's users and tenant.
- `AC-REQ-001-03`: WHEN an ordinary user attempts any developer token management operation THEN the system SHALL reject the request with `19807 developer_token_admin_forbidden` or the project-equivalent business error response.
- `AC-REQ-001-04`: WHEN a tenant admin creates or updates a token THEN the system SHALL reject any attempt to bind the token to another tenant or a user outside the admin's tenant.
- `AC-REQ-001-05`: WHEN global config is read or updated THEN only the global super admin SHALL be allowed; tenant admins SHALL be denied.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-001-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_super_admin_can_manage_all_tokens` |
| AC-REQ-001-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_tenant_admin_scope_is_limited` |
| AC-REQ-001-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_ordinary_user_cannot_manage_tokens` |
| AC-REQ-001-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_tenant_admin_cannot_bind_cross_tenant_user` |
| AC-REQ-001-05 | automated test + manual | Backend API test plus Platform UI manual check that tenant admin cannot see global config editor. |

### REQ-002: Developer token lifecycle management
As an `authorized admin`, I want to create, list, update, delete, and inspect developer tokens, so that external callers can be issued and managed safely.

#### Acceptance Criteria
- `AC-REQ-002-01`: WHEN an authorized admin creates a token with valid name, selected organization-tree user, enablement, whitelist, and rate-limit settings THEN the system SHALL resolve the selected department's tenant, create a logical token record, and return the generated plaintext token once in the response.
- `AC-REQ-002-02`: WHEN token records are listed THEN the response SHALL include token metadata, token prefix, tenant, user, enablement, override flags, rate limit, last used time, last used IP, and pagination total, but SHALL NOT include plaintext token.
- `AC-REQ-002-03`: WHEN an authorized admin updates a token THEN the system SHALL allow updating metadata, selected bound user and resolved tenant within scope, enabled state, override flags, whitelist, and rate limit, but SHALL NOT allow changing the token value directly.
- `AC-REQ-002-07`: WHEN the selected user belongs to multiple tenants THEN token binding SHALL use the tenant resolved from the selected organization-tree department position, not from a user-level default or frontend-submitted tenant id.
- `AC-REQ-002-08`: WHEN the selected department does not contain the selected user or cannot resolve to an active tenant THEN save SHALL be rejected with `19808 developer_token_binding_forbidden` or the project-equivalent business error response.
- `AC-REQ-002-04`: WHEN an authorized admin deletes a token THEN the system SHALL logical-delete the record and future authentication SHALL treat it as invalid.
- `AC-REQ-002-05`: WHEN an authorized admin views token secret THEN the system SHALL decrypt and return the plaintext token only after permission checks and audit logging.
- `AC-REQ-002-06`: WHEN token secret is stored THEN the database SHALL store only `token_hash`, encrypted `token_ciphertext`, and `token_prefix`, never raw plaintext token.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-002-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_create_token_returns_secret_once` |
| AC-REQ-002-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_list_tokens_omits_plaintext_secret` |
| AC-REQ-002-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_update_token_does_not_rotate_secret` |
| AC-REQ-002-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_deleted_token_is_invalid` |
| AC-REQ-002-05 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_secret_view_requires_permission_and_audits` |
| AC-REQ-002-06 | automated test + code review | ORM/repository test asserts plaintext column absence; code review verifies no raw token persistence. |
| AC-REQ-002-07 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_selected_department_resolves_token_tenant` |
| AC-REQ-002-08 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_selected_department_must_contain_selected_user` |

### REQ-003: Global and per-token access controls
As an `authorized admin`, I want global and per-token IP/rate-limit settings, so that external access can be restricted consistently while allowing token-specific overrides.

#### Acceptance Criteria
- `AC-REQ-003-01`: WHEN global IP whitelist is empty THEN developer token authentication SHALL allow requests from any client IP, subject to other checks.
- `AC-REQ-003-02`: WHEN global rate limit is missing, empty, null, or `0` THEN developer token authentication SHALL not rate-limit requests, subject to other checks.
- `AC-REQ-003-03`: WHEN `override_ip_whitelist=false` THEN authentication SHALL use global IP whitelist for that token.
- `AC-REQ-003-04`: WHEN `override_ip_whitelist=true` THEN authentication SHALL use the token's own IP whitelist, including empty string meaning allow all IPs.
- `AC-REQ-003-05`: WHEN `override_rate_limit=false` THEN authentication SHALL use global rate limit for that token.
- `AC-REQ-003-06`: WHEN `override_rate_limit=true` THEN authentication SHALL use the token's own rate limit, including null or `0` meaning no rate limit.
- `AC-REQ-003-07`: WHEN whitelist input contains invalid IP or CIDR syntax THEN save SHALL be rejected with `19809 developer_token_invalid_ip_rule` or the project-equivalent business error response.
- `AC-REQ-003-08`: WHEN global config does not exist in `config` table THEN service SHALL return default config: empty IP whitelist and no rate limit.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-003-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_empty_global_ip_whitelist_allows_any_ip` |
| AC-REQ-003-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_empty_global_rate_limit_disables_limiter` |
| AC-REQ-003-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_token_uses_global_ip_when_not_overridden` |
| AC-REQ-003-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_token_ip_override_takes_precedence` |
| AC-REQ-003-05 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_token_uses_global_rate_limit_when_not_overridden` |
| AC-REQ-003-06 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_token_rate_limit_override_takes_precedence` |
| AC-REQ-003-07 | automated test + manual | Backend validation test plus Platform form manual invalid input check. |
| AC-REQ-003-08 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_service.py::test_missing_global_config_returns_defaults` |

### REQ-004: Developer token authentication dependency
As a `business API developer`, I want a FastAPI dependency for developer token authentication, so that selected endpoints can authenticate external callers as a bound user without changing JWT flows.

#### Acceptance Criteria
- `AC-REQ-004-01`: WHEN an opt-in endpoint depends on `get_developer_token_user` and request lacks `X-Developer-Token` THEN the system SHALL reject the request with `19801 developer_token_missing`.
- `AC-REQ-004-02`: WHEN the request token hash does not match an active non-deleted token THEN the system SHALL reject the request with `19802 developer_token_invalid`.
- `AC-REQ-004-03`: WHEN the matched token is disabled THEN the system SHALL reject the request with `19803 developer_token_disabled`.
- `AC-REQ-004-04`: WHEN the bound user does not exist or is disabled THEN the system SHALL reject the request with `19802 developer_token_invalid`.
- `AC-REQ-004-05`: WHEN the bound tenant does not exist or is unavailable THEN the system SHALL reject the request with `19802 developer_token_invalid` or a dedicated compatible business error.
- `AC-REQ-004-06`: WHEN token authentication succeeds THEN the dependency SHALL return a `UserPayload` representing the bound user.
- `AC-REQ-004-07`: WHEN token authentication succeeds THEN the dependency SHALL set tenant ContextVars to the token's bound tenant and constrained visible tenant set, even if the bound user is a global super admin.
- `AC-REQ-004-08`: WHEN token authentication succeeds THEN the system SHALL update last used time and IP as a best-effort side effect; failure of this update SHALL be logged and SHALL NOT fail the already authenticated request.
- `AC-REQ-004-09`: WHEN an existing endpoint does not opt in to the dependency THEN this feature SHALL NOT change its authentication behavior.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-004-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_missing_header_is_rejected` |
| AC-REQ-004-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_unknown_token_is_rejected` |
| AC-REQ-004-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_disabled_token_is_rejected` |
| AC-REQ-004-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_disabled_bound_user_is_rejected` |
| AC-REQ-004-05 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_invalid_bound_tenant_is_rejected` |
| AC-REQ-004-06 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_authenticated_user_payload_matches_binding` |
| AC-REQ-004-07 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_auth_sets_constrained_tenant_context` |
| AC-REQ-004-08 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_last_used_update_is_best_effort` |
| AC-REQ-004-09 | regression test + code review | Confirm no existing route is modified to depend on developer token in this phase. |

### REQ-005: IP whitelist and Redis rate limiting
As a `security operator`, I want developer token requests to enforce IP whitelist and rate limits, so that externally exposed opt-in APIs fail closed under unsafe conditions.

#### Acceptance Criteria
- `AC-REQ-005-01`: WHEN client IP equals a single-IP whitelist rule THEN authentication SHALL pass the IP check.
- `AC-REQ-005-02`: WHEN client IP belongs to a CIDR whitelist rule THEN authentication SHALL pass the IP check.
- `AC-REQ-005-03`: WHEN client IP matches no whitelist rule THEN authentication SHALL reject the request with `19804 developer_token_ip_forbidden`.
- `AC-REQ-005-04`: WHEN rate limit is positive and requests exceed the per-token per-minute limit THEN authentication SHALL reject excess requests with `19805 developer_token_rate_limited`.
- `AC-REQ-005-05`: WHEN Redis limiter storage raises an exception THEN authentication SHALL reject the request with `19806 developer_token_limiter_unavailable` and SHALL NOT bypass rate limiting.
- `AC-REQ-005-06`: WHEN rate limiting is active THEN Redis keys SHALL follow `developer_token:rate:{token_id}:{yyyyMMddHHmm}` and expire after approximately 70 seconds.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-005-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_single_ip_whitelist_match_allows` |
| AC-REQ-005-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_cidr_whitelist_match_allows` |
| AC-REQ-005-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_ip_miss_is_forbidden` |
| AC-REQ-005-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_rate_limit_exceeded_is_rejected` |
| AC-REQ-005-05 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_redis_error_fails_closed` |
| AC-REQ-005-06 | automated test | Redis fake/mock assertion in dependency/service limiter test. |

### REQ-006: Backend data model, API contract, and compatibility
As a `backend maintainer`, I want developer token implementation to follow BiSheng backend conventions, so that it is maintainable and compatible with MySQL and DM8.

#### Acceptance Criteria
- `AC-REQ-006-01`: WHEN the feature is implemented THEN a `developer_token` table SHALL exist with fields for `tenant_id`, `user_id`, `name`, `token_hash`, `token_ciphertext`, `token_prefix`, enablement, override flags, whitelist, rate limit, last usage, creator/updater, logical delete, create time, and update time.
- `AC-REQ-006-02`: WHEN database migration is created THEN it SHALL use dual-DB-compatible types and avoid MySQL-only JSON or JSON query features.
- `AC-REQ-006-03`: WHEN token lookup occurs during authentication THEN repository lookup by `token_hash` SHALL run in a tenant-filter-safe way and still enforce token-bound tenant semantics in service.
- `AC-REQ-006-04`: WHEN admin APIs are implemented THEN routes SHALL be mounted under `/api/v1/admin/developer-tokens` and return project-standard response wrappers.
- `AC-REQ-006-05`: WHEN module errors are implemented THEN developer token errors SHALL use module code `198` unless release-contract review assigns another unused code.
- `AC-REQ-006-06`: WHEN repository methods are implemented THEN they SHALL contain only data access and no permission, IP, Redis, or token cryptography business logic.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-006-01 | automated test + migration review | Migration/model test and code review of ORM fields. |
| AC-REQ-006-02 | code review + CI | Review migration for `LargeText`/compatible fields; DM8 CI on Linux when available. |
| AC-REQ-006-03 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_dependency.py::test_token_lookup_bypasses_current_request_tenant_filter_safely` |
| AC-REQ-006-04 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py` |
| AC-REQ-006-05 | code review | `common/errcode/developer_token.py` and release contract review. |
| AC-REQ-006-06 | code review + unit test boundaries | Repository unit tests mock DB only; service tests cover business logic. |

### REQ-007: Platform management UI
As an `authorized admin`, I want a Developer Token tab in the Platform System Page, so that token management can be performed from the existing admin UI.

#### Acceptance Criteria
- `AC-REQ-007-01`: WHEN an authorized admin opens Platform System Page THEN a Developer Token tab SHALL be available according to the user's management capability.
- `AC-REQ-007-02`: WHEN a global super admin opens the Developer Token tab THEN the global config panel SHALL be visible and editable.
- `AC-REQ-007-03`: WHEN a tenant admin opens the Developer Token tab THEN the global config panel SHALL be hidden or read-only and updates SHALL not be possible.
- `AC-REQ-007-04`: WHEN token list loads THEN the table SHALL display name, prefix, bound user, bound tenant, enabled state, override flags, rate limit, last used time, and last used IP.
- `AC-REQ-007-05`: WHEN creating or editing a token THEN the UI SHALL use existing Platform UI components, validate required fields, support organization-tree single-user selection, support multiline whitelist input, and support null/0 rate-limit meaning no limit.
- `AC-REQ-007-08`: WHEN creating or editing a token THEN the dialog SHALL NOT display manually editable `tenant_id` or `user_id` inputs; it SHALL display the selected user's name and organization path from the tree selector.
- `AC-REQ-007-09`: WHEN saving a token from the UI THEN the frontend SHALL submit selected `user_id` plus selected department context and SHALL NOT submit a manually entered `tenant_id`.
- `AC-REQ-007-06`: WHEN viewing plaintext token THEN the UI SHALL use a separate action and confirmation flow before displaying the token.
- `AC-REQ-007-07`: WHEN IP whitelist input is invalid THEN the UI SHALL display a clear error returned by the backend or equivalent form validation.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-007-01 | manual | Open Platform System Page and verify tab visibility for admin roles. |
| AC-REQ-007-02 | manual | Log in as global super admin and verify global config panel can be edited. |
| AC-REQ-007-03 | manual + API test | Log in as tenant admin and verify panel is not editable; backend rejects update. |
| AC-REQ-007-04 | manual | Create test data and inspect Developer Token table columns. |
| AC-REQ-007-05 | manual | Create/edit token using dialog, multiline whitelist, and no-limit rate setting. |
| AC-REQ-007-06 | manual | Click view secret and verify confirmation + token secret dialog. |
| AC-REQ-007-07 | manual + backend test | Enter invalid IP/CIDR and verify clear error. |
| AC-REQ-007-08 | manual + code review | Open create/edit dialog and verify manual ID inputs are absent. |
| AC-REQ-007-09 | code review + build | Review Platform API payload typing and network payload construction. |

### REQ-008: Auditability and operational safety
As a `security auditor`, I want sensitive developer token actions to be auditable and reversible where possible, so that token usage can be investigated and safely disabled.

#### Acceptance Criteria
- `AC-REQ-008-01`: WHEN token is created, updated, deleted, or secret is viewed THEN an audit log SHALL be written with action, token id, prefix, tenant id, user id, operator id, IP, user agent, and non-secret change summary where available.
- `AC-REQ-008-02`: WHEN global config is updated THEN an audit log SHALL be written without storing plaintext developer token values.
- `AC-REQ-008-03`: WHEN developer token authentication is denied THEN the system MAY log structured application logs and MAY sample audit events, but SHALL NOT write full plaintext token into logs or audit metadata.
- `AC-REQ-008-04`: WHEN runtime emergency stop is required THEN operators SHALL be able to disable tokens by setting `enabled=false` without impacting non-opt-in existing interfaces.

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-008-01 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_sensitive_actions_write_audit_log` |
| AC-REQ-008-02 | automated test | `cd src/backend && uv run pytest test/developer_token/test_developer_token_api.py::test_global_config_update_writes_audit_log` |
| AC-REQ-008-03 | code review + log assertion | Verify no plaintext token in denied auth logs; optional test with caplog. |
| AC-REQ-008-04 | manual + automated dependency test | Disable token and verify dependency rejects while unrelated endpoints are unchanged. |

## Non-Functional Requirements
- `NFR-001`: Token secrets SHALL never be stored or logged as raw plaintext.
- `NFR-002`: Redis limiter failures SHALL fail closed for opt-in developer-token-authenticated requests.
- `NFR-003`: New database objects SHALL remain compatible with MySQL and DM8.
- `NFR-004`: Developer token authentication SHALL not change behavior of endpoints that do not opt in.
- `NFR-005`: Platform UI SHALL not introduce new UI libraries, state libraries, or direct axios imports.
- `NFR-006`: Backend code SHALL preserve DDD layering and avoid endpoint-to-ORM direct imports.

## Clarifications

### Session 2026-06-10
- Q: The source document proposes module code `181`, but `features/v2.6.0/release-contract.md` already assigns `181` to approval. Which module code should developer token use? -> A: Use an unused code; `198` is accepted for this spec.
- Q: Should the spec use the project `features/v2.6.0/...` convention or the `/sdd-spec` directory convention? -> A: Use `/sdd-spec` directory convention: `specs/044-developer-token/requirements.md`, `design.md`, and `tasks.md`.
- Q: Should token create/edit manually input `user_id` and `tenant_id`? -> A: No. New/edit dialogs should use a tree user picker. The frontend submits selected `user_id` plus selected department context; the backend resolves the tenant from that selected position.
- Q: If one user belongs to multiple tenants, which tenant should the token bind to? -> A: Bind to the tenant resolved from the organization-tree position selected by the admin.

## Assumptions
- Global super admin detection will use existing project semantics (`user.role == admin` in Platform and backend global-super checks), but implementation must verify the exact backend helper before coding.
- Tenant admin authorization will use existing `UserPayload.has_tenant_admin(tenant_id)` or the project-approved equivalent; implementation must not infer tenant admin from frontend state alone.
- Global developer token config can reuse existing `config` table via an independent key because the source implementation document explicitly excludes a new config table.
- Token generation format may use a `bst_` prefix as shown in source examples, as long as entropy and storage rules are satisfied.

## Risks
- Module code `198` is accepted for this spec but still must be registered in the appropriate release contract or project registry before implementation to avoid future conflicts.
- Secret view is inherently sensitive. Encrypted storage plus audit reduces database exposure but does not prevent an authorized user from copying a token after viewing it.
- Redis fail-closed behavior protects exposed APIs but can create availability impact for opt-in endpoints during Redis outages.
- Authentication requires safe manipulation and reset of tenant ContextVars; implementation must avoid leaking token tenant context into unrelated request handling.
- DM8 validation is not available on macOS according to project instructions; full dual-DB validation depends on CI/Linux.
- Department-context-based tenant resolution must be backend-authoritative. Trusting a frontend `tenant_id` or user label would permit incorrect or unauthorized token binding.

## Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has a verification method.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains for spec drafting.
- [x] Requirements avoid implementation details unless explicitly required by the source document or project constraints.
