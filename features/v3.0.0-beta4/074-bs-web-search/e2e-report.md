# F074 Tool API Validation

Updated 2026-10-15 after the user's request to simplify tests.
Scope: the new external invocation API and its execution boundaries. No tool
creation/save/publication tests. Combined API and existing regression selection:
77 passed on Python 3.12. Deployed acceptance is pending.

## Test Selection

Five Python test files (695 lines) plus one import-time defaults YAML:
- test/dsh/test_tool_invoke_http.py: route, credential policy, envelope, bounded body,
  disconnect cleanup and safe error response.
- test/e2e/test_e2e_tool_api.py: actual API/service/ToolExecutor with existing tool
  lookup injected; two input schemas, exact argument forwarding, current use denial,
  missing/deleted/foreign-tenant/unsupported tools, upstream failure and trace privacy.
- test/tool/test_tool_api_schema.py: newly added invocation schema validation and
  recursive/ambiguous destination rejection, without tool persistence.
- test/tool/test_tool_api_transport.py: newly added bounded HTTP execution, streaming
  cleanup, upstream errors and credential-safe logging.
- test/dsh/test_tool_leases.py: newly added Redis atomic concurrency and owner expiry.

Removed the standalone SQL repository, saved-tool service, orchestration and result
unit suites and the separate published_tools.py test harness. Assertions central to
the API are covered through HTTP. Existing tool CRUD suites are unchanged.

API tests use a signed DSH JWT and the actual execution chain, but inject saved-tool
lookup, user/FGA/seat dependencies, telemetry and lease calls. Upstream HTTP uses
httpx.MockTransport. Redis is tested separately with an isolated real redis-server.
No local socket HTTP server or publication fixture is needed.

## Reproduce

From src/backend with backend dependencies and redis-server installed, unset
HTTP/HTTPS/ALL proxy variables used by legacy SDK import-time initialization.

```bash
config=test/e2e/helpers/tool-api.yaml python -m pytest --confcutdir=test/dsh \
  test/dsh/test_tool_invoke_http.py test/dsh/test_tool_leases.py \
  test/e2e/test_e2e_tool_api.py test/tool/test_tool_api_schema.py \
  test/tool/test_tool_api_transport.py test/dsh/test_access.py \
  test/dsh/test_models_api.py test/dsh/test_middleware.py \
  test/tool/test_tool_executor_permissions.py -q
```

The combined run includes existing identity/model/middleware/executor regressions.
Python 3.11's minimal environment separately passes 18 schema/Redis tests.
It is not a full frozen backend installation.

## Coverage and Limits

| Area | Evidence |
| --- | --- |
| Direct API and generic inputs/results | Actual endpoint/service/executor; two schemas without save/publish |
| Authentication and resource authorization | Signed JWT, denied user, missing/deleted/foreign tool/category |
| Invalid requests and failures | Exact HTTP/error codes, safe request_id, no execution on denied input |
| Invocation bounds | Schema, body/output limits, streamed response cleanup and disconnect |
| Shared concurrency | Isolated real Redis multi-client and owner-expiry tests |

The removed SQL lookup suite is no longer current acceptance evidence. Database
tenant filtering, live accounts/OpenFGA, production async drivers and MySQL/DM8,
Gateway/Work and a real provider remain integration acceptance items. The reduced
suite does not claim exhaustive coverage of every original AC.

Ruff passes; the architecture guard reports only the deliberately fake credential
in the transport logging regression, with no violations. Full backend/CI, frontend
lint/typecheck and deployed acceptance were not run. No production behavior changed
during this test simplification. No push or deployment.
