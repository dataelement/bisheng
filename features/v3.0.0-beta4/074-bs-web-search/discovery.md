# F074 - Published Tool Invocation for Work

Status: confirmed by the user on 2026-10-15 ("确认OK"). Latest user correction
replaces the fixed search proposal. The next gate is spec confirmation; design
confirmation remains separate under SDD-Guide section 3. This document records
the confirmed discovery, not implementation or deployment acceptance.

## Baseline and Scope

- Verified 2026-10-15: `origin/feat/3.0.0-beta4` and `v3.0.0-beta4` both identify
  `db23811133b397eff1f572c8e5404c262a8f1332`.
- Branch `codex/bs-web-search`, independent checkout at
  `/Users/alex/Documents/Code/dataelem/bisheng-bs-web-search`.
- Original checkout main updated to `ca4ca8bf0e`; local `.drone.yml` modifications
  restored without conflict and untracked blog content preserved.
- Only Bisheng changes. No Gateway/Work edits, deployment, merge or push.
- Generic published-tool invocation replaces the independent search route.
  First supported tool kind: saved OpenAPI tools. MCP and other kinds rejected.

## Verified Beta4 Evidence

### Authentication

`bisheng/dsh/api/endpoints/models.py:desktop_principal` requires exactly one
Authorization header. `DshAccessService.authenticate` in
`bisheng/dsh/domain/services/access.py` verifies HS256 signature, token type,
issuer, audience, required claims, expiry and token lifetime. It checks current
natural-person and tenant status, then introspects the active Gateway
seat/session/grant version. This is the reusable enterprise Bearer contract;
other browser/provider Bearer tokens are not equivalent.

`principal_scope` establishes tenant context and clears inherited administrative
bypass flags. Publication lookup and execution must enter it.
`bisheng/utils/http_middleware.py` has exact credential-route ownership; the
parameterized invoke route needs a bounded anchored match and authenticated
endpoint, not a blanket DSH-prefix exemption.

### Tools and persistence

`ToolExecutor.init_by_tool_id` in `bisheng/tool/domain/services/executor.py`
loads saved tool/category and checks current
`check_business_action(resource_type="tool", action="use")` against the category.
Its OpenAPI loader consumes saved host/auth/key configuration. Request arguments
must never be merged into executor initialization configuration.

`GptsTools` and `GptsToolsType` carry tenant IDs. Root resources may be visible:
visibility alone does not prove binding ownership. The adapter must verify its
business target and tenant explicitly. `bisheng/tool/api/tool.py` has management,
schema and test operations, not a suitable published invocation API.

`bisheng/dsh/domain/repositories/settings.py` demonstrates JSON persistence in
the existing Config table, whose keys are globally unique. Its current instance
key `dsh_management` cannot hold unscoped tenant publication data.

### Gateway source inspection

The current local Gateway checkout proxies `/api/v1/**`. `DshRoutes.backend`
does not list the proposed invoke path. `PathRateGlobalFilter` and
`CustomResponseFilter` apply to configured URL fragments; checked-in defaults
match assistant/chat and process paths, not this tools path. Missing ownership
alone does not prove blockage. Deployed filter configuration, license behavior
and header preservation require actual HTTP acceptance. No Gateway change.

## Proposed Discovery Decisions

### Invocation contract

`POST /api/v1/dsh/tools/{toolCode}/invoke`, verified DSH Bearer:

```json
{"arguments":{"query":"search terms"}}
```

```json
{"tool":"bs_web_search","result":{"results":[],"truncated":false}}
```

`toolCode` is unique within each tenant, matching `[a-z][a-z0-9_]{0,63}`.
Resolve it using verified tenant identity and require enabled publication plus
the caller's current saved-tool use permission. A guessed code or tool ID is
not publication authorization. Only arguments is allowed in the invoke envelope.

Generic arguments must be an object validated against the actual saved supported
OpenAPI schema: required fields, types, enums and unexpected override parameters.
Unsupported schema constructs fail publication explicitly. The client cannot
supply execution configuration, identity, tool definitions, URL or credentials.
Legitimate tool arguments are distinct from internal executor configuration.

JSON text is parsed once into JSON values, preserving object/array/scalar meaning.
Ordinary non-JSON text has stable generic representation `{"text":"..."}`.
Do not guess wrappers or turn arbitrary text into search success.

### Practical publication management

Add browser-authenticated admin GET collection and GET/PUT item endpoints:

- `/api/v1/dsh/admin/tool-publications`
- `/api/v1/dsh/admin/tool-publications/{toolCode}`

```json
{
  "tool_id":123,
  "enabled":true,
  "limits":{
    "timeout_seconds":30,
    "max_input_bytes":65536,
    "max_output_bytes":1048576,
    "max_concurrency":4
  }
}
```

Require current tenant/global administration in the selected tenant and current
tool-category edit permission. Derive tenant from verified admin context.
PUT creates/replaces a mapping; enabled=false disables it. GET supports actual
configuration verification. No new frontend page is included in this proposal.

Store one tenant/code-qualified Config entry, for example
`dsh_tool_publication:<tenant>:<code>`, using Repository locking and atomic writes.
No new table is proposed. This is a key in a global config table, not a manual
tenant filter on business tables. Save and execution verify non-deleted, supported
OpenAPI tool/category owned by the tenant; no implicit other-tenant fallback.
Changing/deleting a saved tool cannot silently retain valid publication access.

### Bounds and errors

Proposed configurable bounds: timeout 1-60 seconds (default 30), input at most
64 KiB, output at most 1 MiB, concurrency at most 16 (default 4) per tenant/code.
Concurrency uses Redis leases shared by API replicas, owner-safe release and
expiry beyond execution timeout; uncertainty fails closed and cancellation
releases the lease. Input bounds apply before expensive parsing. Output bounds
must cover upstream reads where the executor permits, not only final JSON;
any executor gap must be resolved or surfaced in design review.

Success is HTTP 200 with top-level tool/result, without data wrapping. Errors
use the current DSH envelope:
`{"error":{"message":"...","type":"...","code":"..."},"request_id":"..."}`.
Proposed statuses: 400 invalid arguments, 401 invalid token, 403 denied,
404 unpublished code, 429 concurrency cap, 502 upstream failure/invalid result,
503 dependencies unavailable, 504 timeout. Diagnostics expose safe classification
and correlation ID, never saved secrets/configuration or raw upstream bodies.

### Search business contract and actual upstream

`bs_web_search` reserves its search result contract independently per tenant:
`{output?:string,results:[{url,title?,snippet?,published_at?}],truncated:boolean}`.
Query proposal: trimmed, 1-4096 characters. Validate every result and HTTP(S) URL;
bound results to 20 and preserve/set truncated when dropping valid results.
Reject generic text fallback, errors, invalid fields and opaque encrypted output.
Optional maxResults is supported only if explicitly declared and approved in the
published search schema; Work's initial request uses query only.

Administrators create/import a normal OpenAPI tool pointing to a real service
that accepts flat query and emits this contract, save server credentials, grant
use permission, then publish its ID under bs_web_search. Additional generic tools
use the same publication/invocation APIs without new routes or business code.

Schema import does not create a service. Raw Sub2API alpha/search requires
`{model,commands:{search_query:[{q}]}}`; translation belongs to the tool/provider
adapter. The generic endpoint cannot send bare query to that raw API. No actual
compatible upstream service or saved production tool has been verified here yet.
Validate effective destination and redirect behavior to reject invocation of this
endpoint itself, including aliases/other tool codes, and prevent recursion.

## Required Acceptance

- Forged/expired/wrong-audience token, duplicate headers, disabled user/tenant,
  revoked session and isolation from body-supplied identity.
- Admin publication permissions, uniqueness, tenant isolation, disabled/deleted/
  foreign target, revoked use permission and unsupported kind/schema rejection.
- Two distinct saved OpenAPI schemas invoked through the same route; validation
  of required/type/enum/extra arguments and configuration override rejection.
- JSON object/text/array/scalar and stable plain text; empty/malformed/encrypted
  search output, upstream failure and result truncation.
- Size limits including upstream reads, timeout/cancellation, cross-replica
  concurrency, lease recovery, recursion rejection and sensitive error redaction.
- Middleware/route integration, existing DSH/tool permission regressions, Ruff
  and architecture guard. Real Work/Gateway/upstream acceptance remains pending.

## Confirmation Record

User confirmed this revised Discovery on 2026-10-15, including API-only
publication management, verified DSH Bearer, tool/result contract and proposed
limits. Next prepare and review spec, obtain its confirmation, then design and
its confirmation, then tasks, implementation, tests and local commit. No feature
completion is claimed. No authorization to push was added by this confirmation.
