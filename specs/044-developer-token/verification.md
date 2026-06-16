# Verification: Developer Token Management and Authentication

## Metadata
- Feature ID: `044-developer-token`
- Status: `manual-verify-required`
- Related requirements: `specs/044-developer-token/requirements.md`
- Related tasks: `specs/044-developer-token/tasks.md`
- Created: `2026-06-10`
- Updated: `2026-06-16`

## Verification Summary
- Overall status: `MANUAL_VERIFY_REQUIRED`
- Completed tasks: T001-T019, T021-T023, T024-T029, T030-T032, T033-T035, T036-T038, T039-T041
- Remaining tasks: T020
- Blocked tasks: None

## Commands Run
| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `cd src/backend && uv run pytest test/developer_token/` | Backend developer token unit/API/dependency/repository tests | 0 | PASS | `29 passed in 0.26s` after tree-binding contract update |
| `cd src/backend && uv run ruff format bisheng/developer_token test/developer_token && uv run ruff check --fix bisheng/developer_token test/developer_token && uv run ruff check bisheng/developer_token test/developer_token` | Format and lint backend feature code/tests after binding contract update | 0 | PASS | `20 files left unchanged`; `All checks passed!` twice |
| `cd src/backend && uv run ruff format bisheng/core/database/alembic/versions/v2_6_0_f044_developer_token.py && uv run ruff check --fix bisheng/core/database/alembic/versions/v2_6_0_f044_developer_token.py` | Migration formatting and linting | 0 | PASS | `All checks passed!` |
| `cd src/backend && uv run alembic heads` | Verify Alembic graph has a single head after F044 | 0 | PASS | `f044_developer_token (head)` |
| `bash scripts/arch-guard.sh` | Architecture guard for DDD/import boundaries | 0 | PASS | No output; command exited 0 after input placeholder coverage change |
| `cd src/frontend/platform && npm run test -- developerTokenValidation.test.ts` | Regression test for Developer Token whitelist and rate-limit validation helper | 0 | PASS | `1 passed`; `4 tests passed`; covers empty whitelist, single IP, CIDR, separators, invalid rule detection, and integer-only rate-limit helpers |
| `cd src/frontend/platform && npm run build` | Platform TypeScript/Vite build and locale JSON validation | 0 | PASS | Vite build completed successfully after input placeholder coverage change; existing Vite/Browserslist/eval/chunk-size warnings remain |
| `python -m json.tool src/frontend/platform/public/locales/zh-Hans/bs.json >/dev/null && python -m json.tool src/frontend/platform/public/locales/en-US/bs.json >/dev/null && python -m json.tool src/frontend/platform/public/locales/ja/bs.json >/dev/null` | Validate updated Platform locale JSON files | 0 | PASS | All three locale files parsed successfully |
| `wc -l src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm DeveloperToken component stays within frontend single-file line limit | 0 | PASS | `DeveloperToken.tsx` is `594` lines |
| `wc -l src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx && rg -n "placeholder=\|searchPlaceholder=\|globalRateLimitPlaceholder\|searchPlaceholder\|namePlaceholder\|rateLimitPlaceholder" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx src/frontend/platform/public/locales/zh-Hans/bs.json src/frontend/platform/public/locales/en-US/bs.json src/frontend/platform/public/locales/ja/bs.json` | Confirm Developer Token placeholder coverage and line limit after adding missing placeholders | 0 | PASS | Component is `594` lines; placeholders are wired for global IP whitelist, global rate limit, list search, token name, user selector/search, token IP whitelist, and token rate limit; new locale keys exist in zh-Hans/en-US/ja |
| `rg -n "findInvalidIpWhitelistRule\|ipWhitelistInvalidError\|19809" src/frontend/platform/src/pages/SystemPage/components src/frontend/platform/public/locales/zh-Hans/bs.json src/frontend/platform/public/locales/en-US/bs.json src/frontend/platform/public/locales/ja/bs.json` | Confirm invalid whitelist validation and localized backend fallback are wired | 0 | PASS | Save paths call `findInvalidIpWhitelistRule`; local toast key and `errors.19809` exist in zh-Hans/en-US/ja |
| `! rg -n "secretConfirm" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx src/frontend/platform/public/locales/zh-Hans/bs.json src/frontend/platform/public/locales/en-US/bs.json src/frontend/platform/public/locales/ja/bs.json` | Confirm old secret-view confirmation locale key and usage were removed from Platform code/locales | 0 | PASS | No matches in DeveloperToken component or three Platform locale files |
| `rg -n "handleViewSecret\|viewDeveloperTokenSecretApi\|bsConfirm" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm secret view now directly calls the API while delete confirmation still uses `bsConfirm` | 0 | PASS | `handleViewSecret` calls `viewDeveloperTokenSecretApi` directly; remaining `bsConfirm` usage is in delete flow |
| `git diff --check -- specs/044-developer-token/requirements.md specs/044-developer-token/design.md specs/044-developer-token/tasks.md src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx src/frontend/platform/public/locales/zh-Hans/bs.json src/frontend/platform/public/locales/en-US/bs.json src/frontend/platform/public/locales/ja/bs.json` | Check whitespace/conflict-marker hygiene for the direct secret view change | 0 | PASS | No diff hygiene issues reported |
| `rg -n "type=\"number\"" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm Developer Token rate-limit fields no longer use browser number inputs that permit decimals/exponents | 1 | PASS | No matches; rate-limit inputs are integer text inputs |
| `rg -n "handleRateLimitKeyDown\|handleRateLimitPaste\|onKeyDown=\{handleRateLimitKeyDown\}\|onPaste=\{handleRateLimitPaste\}" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm global and token-level rate-limit inputs hard-block invalid key and paste input | 0 | PASS | Handlers are defined and attached to both rate-limit inputs |
| `rg -n "handleRateLimitBeforeInput\|onBeforeInput=\{handleRateLimitBeforeInput\}" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm non-digit input is blocked before it enters global and token-level rate-limit fields | 0 | PASS | `beforeinput` handler is defined and attached to both rate-limit inputs |
| `rg -n "sanitizeRateLimitInput\|handleRateLimitCompositionEnd\|onCompositionEnd" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx && wc -l src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | Confirm IME/composition fallback sanitizes non-digit committed input and file stays within frontend line limit | 0 | PASS | Sanitizer and composition-end handlers are attached to both rate-limit inputs; file is `599` lines |
| `rg "fields\.tenantId\|fields\.userId\|form\.tenant_id\|form\.user_id\|tenant_id: Number\|DeveloperTokenCreate\(name=.*tenant_id\|\"tenant_id\": 1" src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx src/frontend/platform/src/controllers/API/developerToken.ts src/frontend/platform/public/locales/zh-Hans/bs.json src/frontend/platform/public/locales/en-US/bs.json src/frontend/platform/public/locales/ja/bs.json src/backend/test/developer_token src/backend/bisheng/developer_token -n` | Confirm manual token binding ID inputs and old create payload contract are removed from feature files | 1 | PASS | No matches |
| `curl -I http://localhost:3001/` | Platform dev server smoke check | 0 | PASS | HTTP `200 OK` from Vite dev server |
| `rg "get_developer_token_user\|X-Developer-Token" src/backend/bisheng -n` | Confirm no existing business endpoint was retrofitted | 0 | PASS | Only `developer_token/api/dependencies.py` matches |
| `rg "import axios\|from ['\\\"]axios" src/frontend/platform/src/controllers/API/developerToken.ts src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx -n` | Confirm Platform feature uses wrapped request module, not direct axios | 0 | PASS | Only `import axios from "@/controllers/request"` in API wrapper |

## Acceptance Coverage
| Acceptance ID | Requirement | Verification Method | Evidence | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | Automated tests + code review | `test_developer_token_service.py`, `test_developer_token_api.py`; service global-super branch | PASS |
| AC-REQ-001-02 | REQ-001 | Automated tests + code review | Tenant admin scope tests and `_resolve_list_tenant` / `_assert_tenant_admin` review | PASS |
| AC-REQ-001-03 | REQ-001 | Automated tests | `test_tenant_admin_cannot_bind_cross_tenant_user`; service raises `19807` | PASS |
| AC-REQ-001-04 | REQ-001 | Automated tests + code review | Tenant binding validation and admin scope check before create/update | PASS |
| AC-REQ-001-05 | REQ-001 | Automated tests + code review | Global config service requires `_assert_global_super`; API route present | PASS |
| AC-REQ-002-01 | REQ-002 | Automated tests | `test_create_token_returns_secret_once`; create schema now uses `user_id + department_id` and service resolves tenant | PASS |
| AC-REQ-002-02 | REQ-002 | Automated tests | `test_list_tokens_omits_plaintext_secret`; schema excludes plaintext from list row | PASS |
| AC-REQ-002-03 | REQ-002 | Automated tests | `test_update_token_does_not_rotate_secret`; `test_update_token_rebinds_from_selected_department`; update schema has no token value field | PASS |
| AC-REQ-002-04 | REQ-002 | Automated tests + code review | Repository `logic_delete_token`; dependency hash lookup filters non-deleted rows | PASS |
| AC-REQ-002-05 | REQ-002 | Automated tests + code review | `test_secret_view_route_returns_secret_payload`; service audits `developer_token.secret_view` | PASS |
| AC-REQ-002-06 | REQ-002 | Automated tests + code review | ORM stores `token_hash`, `token_ciphertext`, `token_prefix`; create test asserts no raw DB plaintext | PASS |
| AC-REQ-002-07 | REQ-002 | Automated tests | `test_selected_department_resolves_token_tenant` verifies selected department context resolves tenant id | PASS |
| AC-REQ-002-08 | REQ-002 | Automated tests | `test_selected_department_must_contain_selected_user` rejects mismatched selected user/department; `test_selected_department_requires_active_tenant` rejects disabled selected tenant | PASS |
| AC-REQ-003-01 | REQ-003 | Automated tests | `test_ip_whitelist_matching`; empty rules allow all in `_ip_allowed` | PASS |
| AC-REQ-003-02 | REQ-003 | Automated tests | `_normalize_rate_limit` and no-limit path covered by dependency tests | PASS |
| AC-REQ-003-03 | REQ-003 | Automated tests + code review | `_effective_controls` uses global IP rules when override is false | PASS |
| AC-REQ-003-04 | REQ-003 | Automated tests | `test_token_override_rules_take_precedence` | PASS |
| AC-REQ-003-05 | REQ-003 | Automated tests + code review | `_effective_controls` uses global rate limit when override is false | PASS |
| AC-REQ-003-06 | REQ-003 | Automated tests | `test_token_override_rules_take_precedence` validates override no-limit semantics | PASS |
| AC-REQ-003-07 | REQ-003 | Automated tests | `test_invalid_ip_rule_is_rejected` | PASS |
| AC-REQ-003-08 | REQ-003 | Automated tests | `test_missing_global_config_returns_defaults` | PASS |
| AC-REQ-004-01 | REQ-004 | Automated tests | `test_missing_header_is_rejected` | PASS |
| AC-REQ-004-02 | REQ-004 | Automated tests | `test_unknown_token_is_rejected` | PASS |
| AC-REQ-004-03 | REQ-004 | Automated tests | `test_disabled_token_is_rejected` | PASS |
| AC-REQ-004-04 | REQ-004 | Automated tests | `test_disabled_bound_user_is_rejected` | PASS |
| AC-REQ-004-05 | REQ-004 | Automated tests | `test_invalid_bound_tenant_is_rejected` | PASS |
| AC-REQ-004-06 | REQ-004 | Automated tests | `test_auth_sets_constrained_tenant_context` | PASS |
| AC-REQ-004-07 | REQ-004 | Automated tests | `test_auth_sets_constrained_tenant_context` asserts current and visible tenant ContextVars | PASS |
| AC-REQ-004-08 | REQ-004 | Automated tests | `test_last_used_update_is_best_effort` | PASS |
| AC-REQ-004-09 | REQ-004 | Code review + search | `rg "get_developer_token_user\|X-Developer-Token"` only matches the dependency module | PASS |
| AC-REQ-005-01 | REQ-005 | Automated tests | `test_ip_whitelist_matching` single-IP match | PASS |
| AC-REQ-005-02 | REQ-005 | Automated tests | `test_ip_whitelist_matching` CIDR match | PASS |
| AC-REQ-005-03 | REQ-005 | Automated tests | `test_ip_whitelist_matching` miss returns false; service raises `19804` on miss | PASS |
| AC-REQ-005-04 | REQ-005 | Automated tests | `test_rate_limit_exceeded_is_rejected` | PASS |
| AC-REQ-005-05 | REQ-005 | Automated tests | `test_redis_error_fails_closed` | PASS |
| AC-REQ-005-06 | REQ-005 | Automated tests | `test_rate_limit_exceeded_is_rejected` asserts key prefix and 70s expiration | PASS |
| AC-REQ-006-01 | REQ-006 | Migration/model review | ORM and migration define required columns and indexes | PASS |
| AC-REQ-006-02 | REQ-006 | Code review | Migration uses `LargeText` and `UPDATE_TIME_SERVER_DEFAULT`; DM8 CI not available locally | MANUAL_REQUIRED |
| AC-REQ-006-03 | REQ-006 | Code review + tests | Repository `get_token_by_hash` uses `bypass_tenant_filter`; service validates token-bound tenant | PASS |
| AC-REQ-006-04 | REQ-006 | Automated tests | `test_developer_token_api.py`; routes mounted under `/api/v1/admin/developer-tokens` | PASS |
| AC-REQ-006-05 | REQ-006 | Code review | `features/v2.6.0/release-contract.md`; `common/errcode/developer_token.py` | PASS |
| AC-REQ-006-06 | REQ-006 | Automated tests + code review | `test_repository_keeps_business_logic_out_of_data_access_layer` | PASS |
| AC-REQ-007-01 | REQ-007 | Static build + manual pending | System Page tab code compiled; role-specific browser check not run | MANUAL_REQUIRED |
| AC-REQ-007-02 | REQ-007 | Static build + manual pending | Global config panel compiled for `user.role === "admin"`; browser check not run | MANUAL_REQUIRED |
| AC-REQ-007-03 | REQ-007 | Static build + manual pending | Tenant admin path hides global config panel in code; browser check not run | MANUAL_REQUIRED |
| AC-REQ-007-04 | REQ-007 | Static build + manual pending | Table columns compiled; data rendering not checked with live backend | MANUAL_REQUIRED |
| AC-REQ-007-05 | REQ-007 | Static build + manual pending | Create/edit dialog compiled with `DepartmentUsersSelect`; interactive form check not run | MANUAL_REQUIRED |
| AC-REQ-007-06 | REQ-007 | Static build + code review + manual pending | `handleViewSecret` now calls `viewDeveloperTokenSecretApi` directly and opens the plaintext dialog; `secretConfirm` is removed from component/locales; browser click workflow not run | MANUAL_REQUIRED |
| AC-REQ-007-07 | REQ-007 | Frontend unit test + static build + manual pending | `developerTokenValidation.test.ts` covers invalid IP/CIDR detection, separators, and empty allow-all; `DeveloperToken.tsx` save paths call `findInvalidIpWhitelistRule`; `errors.19809` localized; browser workflow not run | MANUAL_REQUIRED |
| AC-REQ-007-08 | REQ-007 | Static build + code search + manual pending | Old manual `tenant_id`/`user_id` form bindings removed from feature files; browser check not run | MANUAL_REQUIRED |
| AC-REQ-007-09 | REQ-007 | Static build + code review | Platform payload type uses optional `user_id`, `department_id`, `dept_id`; `tenant_id` is not sent by `asPayload` | PASS |
| AC-REQ-007-10 | REQ-007 | Static build + code review + manual pending | `DeveloperToken.tsx` now uses integer-only text inputs, `beforeinput`/keydown/paste hard blocking, IME composition-end sanitization, local validation fallback toast, and no `type="number"` matches; browser input/paste workflow not run | MANUAL_REQUIRED |
| AC-REQ-007-11 | REQ-007 | Static build + code review + manual pending | `DeveloperToken.tsx` now wires placeholders for all Developer Token text inputs and three locale files define the new placeholder keys; browser rendering check not run | MANUAL_REQUIRED |
| AC-REQ-008-01 | REQ-008 | Automated tests + code review | Service writes audit for create/update/delete/secret view; API/service tests exercise flows | PASS |
| AC-REQ-008-02 | REQ-008 | Automated tests | `test_global_config_update_writes_audit_log` | PASS |
| AC-REQ-008-03 | Code review + search | Audit metadata excludes plaintext; denied-auth logs do not include raw token | PASS |
| AC-REQ-008-04 | Automated tests + code review | Disabled token dependency test and emergency `enabled=false` behavior | PASS |

## Manual Verification
| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-REQ-007-01 | Log in to Platform as authorized admin and open System Page | Developer Token tab is visible | Not run | NOT_RUN |
| AC-REQ-007-02 | Log in as global super admin and open Developer Token tab | Global config panel is visible and editable | Not run | NOT_RUN |
| AC-REQ-007-03 | Log in as tenant admin and open Developer Token tab | Global config panel is hidden or not editable | Not run | NOT_RUN |
| AC-REQ-007-04 | Seed/list token records and inspect table | Name, prefix, user, tenant, enabled state, override flags, rate limit, last used time/IP render correctly | Not run | NOT_RUN |
| AC-REQ-007-05 | Create and edit a token from the dialog | Required fields, multiline whitelist, and no-limit rate setting work | Not run | NOT_RUN |
| AC-REQ-007-06 | Click view secret action | No confirmation prompt appears; the existing plaintext token dialog opens after the secret API succeeds | Not run | NOT_RUN |
| AC-REQ-007-07 | Submit `not-an-ip`, `10.0.0.999`, `192.168.1.0/33`, and `2001:db8::/129` from global config and token dialog | A localized local error is shown before save; empty whitelist, `10.0.0.1`, `192.168.1.0/24`, and documented separators remain valid | Not run | NOT_RUN |
| AC-REQ-007-08 | Open create/edit token dialog | User is selected from organization tree; no editable tenant ID or user ID inputs are visible | Not run | NOT_RUN |
| AC-REQ-007-10 | Enter or paste `1.5`, `.5`, `1e3`, and `-1` into global and token-level rate-limit inputs, then try saving | Non-integer input is blocked or clearly reported before any API mutation; empty and `0` keep no-limit behavior | Not run | NOT_RUN |
| AC-REQ-007-11 | Open Developer Token page and create/edit dialog | List search, global rate limit, token name, bound user selector/search, IP whitelist, and token rate-limit inputs all display localized placeholders | Not run | NOT_RUN |

## Failures and Gaps
- `cd src/backend && uv run alembic upgrade head` was not run because no prepared local dev database was identified for this session; only `alembic heads` and migration code review were performed.
- Real DM8 validation was not run on macOS; project guidance says DM8 drivers are unavailable locally and CI/Linux is required.
- Platform authenticated manual checklist T020 was not run because no live authenticated Platform session / test accounts were provided. The tree-user-picker create/edit workflow, direct secret view click workflow, invalid whitelist save workflow, input placeholder rendering, and rate-limit paste/input workflow still need browser verification.
- A Vite dev server was started and `curl -I http://localhost:3001/` returned HTTP 200, but this is only a route smoke check, not an authenticated UI workflow check.

## Verification Quality Gate
- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by fresh evidence.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
