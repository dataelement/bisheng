# Design: F074 Published Tool Invocation

Release: v3.0.0-beta4. Updated: 2026-10-15.
Status: proposed design for confirmation; no business implementation exists.
Inputs: confirmed [spec](./spec.md), [discovery](./discovery.md),
[release contract](../release-contract.md). tasks.md follows design confirmation.

## 1. Goal and Non-goals

Expose explicitly published saved OpenAPI tools to verified Desktop users while
retaining tenant boundaries, tool permissions and bounded execution. Search is
the first business contract on a generic arguments/result interface.

No Gateway/Work edits, management UI, MCP/preset execution, provider hosting,
permission grants, token issuance, automatic retries or separate search endpoint.

## 2. Constraints

Follow `docs/constitution.md` C1-C8 and the release invariants. This feature must
reuse the deployed DSH access credential/session contract and saved-tool execution.
It cannot assume that a proxy path proves enterprise authentication compatibility.

| Limit | Default | Allowed range / hard cap |
| --- | --- | --- |
| Publication timeout | 30 seconds | Integer 1-60 seconds |
| Input bytes | 65,536 | Integer 1-65,536, entire UTF-8 request body |
| Output bytes | 1,048,576 | Integer 1-1,048,576, decoded upstream bytes AND serialized result |
| Concurrent invocations | 4 | Integer 1-16, shared per tenant/code |
| Management request | 16,384 bytes | Fixed, entire body |
| Saved schema inspected | 262,144 bytes | Fixed, larger schemas cannot be published |
| Argument schema | 32 properties | Flat scalar inputs; string values capped at 4,096 characters |
| Search results | 20 | All supplied rows validated before truncating |
| Lease retention | 65 seconds | Exceeds the maximum execution deadline |

The invocation deadline begins after DSH identity verification, before publication
lookup/body consumption, and covers all remaining work. Until the publication is
read, apply the 60-second ceiling; shorten to the configured deadline relative to
that same start time. Existing token introspection retains its separate timeout.

One request can hold at most its bounded input, bounded upstream body, parsed
JSON and bounded response representation. JSON depth is capped at 32 and decoded
node count at 10,000; duplicate object keys and non-finite numbers are rejected.
These bounds apply to generic and search outputs, not merely the final 20 rows.

## 3. Decisions and Alternatives

### D1. Durable publication references

Select tenant/code-qualified rows in the existing global Config table, using
`dsh_tool_publication:<tenant_id>:<toolCode>`. Each value holds one complete
publication and an incrementing revision. Do not put all tenants in the existing
instance-wide dsh_management value or use process-local configuration. A new
table is unnecessary for this bounded record and would add migration cost.
Reconsider a dedicated table when indexed publication analytics are required.

### D2. Reuse ToolExecutor with an opt-in strict OpenAPI implementation

The existing OpenApiSchema parser drops body enums and constraints. The existing
OpenApiTools argument schema is not a faithful validator. Its async HTTP wrapper
buffers text, lacks an output cap, logs URL/params, and returns text without
checking HTTP status. Calling it unchanged violates AC-14, AC-19, AC-21 and AC-28.

Select a new tool-owned publication adapter and opt-in bounded OpenApiTools
subclass, loaded through ToolExecutor. Reject reimplementing generic execution in
the DSH endpoint or changing legacy transport behavior for all Agent/workflow
calls. Introduce a narrow ToolExecutor initialization entry for a verified saved
OpenAPI snapshot; it uses the existing permission/build/wrapping functions with
the strict subclass factory, and retains the existing default factory for all
other call sites. Client arguments never become initialization kwargs.

Use `ApplicationTypeEnum.DSH_DESKTOP`, never LINSIGHT: the latter deliberately
converts exceptions into soft error strings. Reconsider sharing strict transport
as the default only in a separate regression-tested change.

### D3. Strict saved-schema validation

Select the full saved category OpenAPI document plus the specific saved tool's
operation path/method/name, rather than reconstructing constraints from the
lossy imported parameters or trusting LangChain's generated args_schema.
Cross-check the effective saved parameters against that operation. Missing or
inconsistent definitions fail publication/invocation instead of selecting a
different operation. Do not auto-fetch remote schema references.

Use jsonschema 4.25.1, already present in uv.lock, as an explicit runtime
dependency without upgrading its closure. Restrict accepted schemas to a
faithfully executable subset (section 6). Reconsider nested inputs only when the
saved parser, argument placement and executor can preserve them end to end.

### D4. Shared admission and bounded recovery

Select Redis atomic owner leases per tenant/code. A semaphore per process would
multiply the configured cap by API replica count. Lease ownership is independent
of publication revision, so edits cannot create a new empty capacity bucket.
Use a 65-second fixed lease lifetime, with a maximum 60-second invocation deadline.
No lease renewal or automatic retry is necessary for this first release.

Keep a persistent initialization marker in the same bounded Redis hash. Missing
state for an existing publication triggers a 65-second admission cooldown, not an
empty-bucket assumption. New publication creation may initialize an empty bucket
while its SQL row is exclusively locked and before it becomes invocable.
Reconsider a queue when tools need execution exceeding 60 seconds.

### D5. Destination and result policy

Select static saved HTTP(S) destinations and no redirects for published calls.
Resolve and normalize the final saved server/path and reject the invoke path
under any hostname, including local aliases and alternate tool codes. This avoids
following a redirect into this API and forwarding credentials. Reject userinfo,
fragments, dot-segments, ambiguous encoding and templated paths rather than
attempting to repair them. No arbitrary URL is taken from request arguments.

Generic success means successful transport/executor completion with JSON or
stable text normalization. Only the reserved bs_web_search code applies search
business validation. Do not infer arbitrary tools' error semantics from a field
named error. Reconsider result-schema publication only when another business
contract requires it. Unknown reverse-proxy rewrites and upstream services that
internally call Bisheng remain operator-owned routing, not discoverable here.

## 4. Current Baseline and Proposed Implementation

### 4.1 Verified baseline

Tag v3.0.0-beta4 and origin/feat/3.0.0-beta4 both identify db23811133. The branch
codex/bs-web-search currently contains discovery/spec documents only.

Existing `dsh/api/endpoints/models.py:desktop_principal` requires exactly one
Authorization header and calls `DshAccessService.authenticate`. That service
verifies JWT signature, typ, issuer, audience, claims/lifetime, current user/tenant
identity and Gateway session/seat/grant introspection. `principal_scope` resets
inherited bypass/admin state. No new token type or unverified JWT decoding.

`UserPayload.get_tenant_admin_user` admits a current child-tenant admin or global
super administrator. Existing DSH settings instead uses get_admin_user, which
does not express the required tenant-admin policy. New endpoints must select the
tenant-admin gate and existing permission application protocols explicitly.

The common AdminScopeMiddleware does not currently own the new management paths.
The new narrow tool-publications prefix must join its management paths; invoke
must remain excluded. Do not extend admin scope to the entire DSH prefix.

### 4.2 Invocation flow

1. Middleware recognizes only POST and the anchored invoke path/code pattern as
   endpoint-owned credentials. Neighboring paths/methods retain existing policy.
2. Authenticate with the shared DSH dependency. Move its implementation to
   dsh/api/dependencies.py and preserve the models.py symbol as an import alias
   so existing overrides/callers retain dependency identity.
3. Enter principal_scope. Read this tenant's publication to determine the bounded
   body limit/deadline. Endpoint reads Request.stream, checks actual bytes, and
   parses strict JSON only after the bound; no eager FastAPI body-model parsing.
   Expose the body schema in generated OpenAPI separately.
4. Under a locked current publication snapshot, recheck enabled state, revision,
   current limits and target; load the tool/category in strict tenant scope.
   Verify both tenant IDs, ownership relationship, active state and supported
   kind/schema before permission shortcuts. If limits shrank while reading,
   revalidate the buffered bytes and remaining deadline against current values.
5. Tool-owned adapter validates current arguments and asks the existing permission
   application facade for use. ToolExecutor constructs the strict implementation
   from that same saved tool/category snapshot. Recheck the locked publication
   revision before admission; do not hold the SQL lock during the upstream call.
6. Acquire one Redis lease while holding the publication lock, then release SQL
   state. This acquisition is the admission point. A completed disable operation
   blocks subsequent admissions; previously admitted work can finish.
7. Invoke ToolExecutor. Its strict OpenAPI implementation builds arguments only
   from declared locations, uses saved credentials, disables environment proxies
   and redirects, checks status, and reads bounded chunks asynchronously. Send
   Accept-Encoding: identity and reject encoded responses, avoiding decompression
   bombs before the byte check; require valid UTF-8 for text/JSON results.
8. Parse JSON once or normalize ordinary text; validate the search business result
   only for bs_web_search. Check serialized result bounds and return tool/result.
9. On every exit, close upstream response/client and release only this lease owner.
   After consuming the body, an endpoint-owned disconnect watcher cancels execution
   on ASGI disconnect. Cleanup is cancellation-shielded with a short deadline;
   failed cleanup is logged safely and lease expiry bounds recovery.

### 4.3 Management flow and persistence

Browser authentication/session checks remain active for admin routes. Require a
positive effective tenant from verified browser/admin scope; never take tenant
from body/query. Use the tenant-admin identity gate and active-tenant check.
Use strict tenant scope while loading targets even for global administrators.

Create/replace requires edit on the proposed saved tool category, including when
replacing an existing mapping. Disable requires edit on its bound category and a
valid target. Reads/list require current tenant administration and expose safe
mapping metadata only. Deleted/invalid targets already fail invocation; repair
them by replacing the mapping with a valid authorized target. There is no
missing-resource exception that bypasses edit authorization.

Repository saves complete JSON under SELECT FOR UPDATE. On first-create unique
key race, use the existing settings Repository savepoint/reselect pattern, then
increment revision on the locked row. A rejected replacement rolls back without
altering the previous value. List uses a literal tenant-key prefix, deterministic
code sorting and bounded pagination; escape underscores in SQL LIKE patterns.

Config is global: tenant qualification is part of its key, not a manual business
table tenant predicate. Tool queries use SQLAlchemy tenant scope and explicit
post-load business checks, not new DAO entry points. No schema migration.

### 4.4 Shared lease details

Key: `dsh:tool:leases:{tenant_id:toolCode}`; braces denote the shared hash tag.
One hash contains an initialization marker/ready_after timestamp and at most
16 UUID owner fields with expiry timestamps. Atomic Lua uses Redis TIME, prunes
expired owners, checks ready_after, counts owners and inserts an owner only if
below the current limit. No whole-key TTL; delete/recreate would hide running work.
Release deletes only its own UUID field. Lowering a limit blocks new work until
existing count falls below it; it does not kill admitted calls.

New SQL publication creation initializes the bucket before exposing the enabled
row. For existing mappings, missing marker creates a single ready_after of now
plus 65 seconds and returns unavailable; repeated failures do not extend it.
Redis unavailable, wrong key type or malformed marker fails admission closed.
Do not delete bucket state on disable, edit or re-enable.

Redis must be shared across replicas. This is a concurrency admission ledger,
not token billing. It does not claim linearizability across a Redis failover that
silently rolls back acknowledged writes. Deployments permitting that must stop
admissions during failover and drain 65 seconds before resuming; verify this
operational assumption separately instead of claiming tested failover safety.

### 4.5 Planned modules

| File under src/backend/bisheng | Responsibility | Does not do |
| --- | --- | --- |
| dsh/api/endpoints/tools.py | HTTP parsing, principal, disconnect watcher | ORM or provider conversion |
| dsh/api/endpoints/tool_publications.py | Browser-admin management HTTP | Tool execution |
| dsh/domain/schemas/tool_publications.py | Strict publication/limit contracts | Read secrets |
| dsh/domain/services/tool_publications.py | Management and invoke orchestration | ORM queries |
| dsh/domain/repositories/tool_publications.py | Config locks, revisions and listing | Authorization decisions |
| dsh/infrastructure/tool_leases.py | Shared atomic admission/release | Billing or SQL ownership |
| tool/domain/repositories/published_tools.py | Consistent saved tool/category snapshot | Bypass tenant policy |
| tool/domain/services/published_tools.py | Target checks, schema matching, edit/use and executor assembly | DSH HTTP imports |
| tool/domain/services/published_schema.py | Supported full-schema extraction/validation | Fetch remote refs |
| tool/domain/services/published_openapi.py | Opt-in bounded OpenApiTools subclass | Arbitrary protocol support |
| dsh/domain/services/tool_results.py | Generic parsing and reserved search result validation | Provider requests |
| common/errcode/dsh.py | Safe DSH tool errors | Sensitive exception interpolation |

Existing router, credential-match and management-prefix registrations change
only to wire these entries. Narrow ToolExecutor extension retains legacy defaults.
Add explicit jsonschema dependency and corresponding lock metadata only.
New error translations belong in packages/locales/src/api_errors/{zh-Hans,en,ja}.json;
regenerate committed artifacts using the existing locales build command, never
edit generated JSON by hand. No component, visual-style or page change is involved.

## 5. Known Pitfalls

| Fact | Consequence if missed | Handling |
| --- | --- | --- |
| Imported body schema drops constraints | Validation silently accepts unsupported arguments | published_schema uses full saved document |
| OpenApiTools allows proxy as a magic kwarg | An argument can alter transport rather than tool data | Reject reserved transport kwargs in published schemas |
| Legacy async request logs URL/params and buffers text | Secret leakage and unbounded memory | Opt-in published_openapi override, no call to legacy arun |
| LINSIGHT converts errors to strings | Upstream failure can look like a successful tool value | DSH_DESKTOP telemetry type |
| Root tools may be visible in leaf tenant scope | Visibility can accidentally become cross-tenant publication | Strict target tenant checks before authorization |
| Business facade can short-circuit global admins | Permission success does not prove valid tool facts | Tool-owned checks before facade |
| Config keys contain underscores | Unescaped LIKE can match unintended codes | Repository prefix escaping |
| Per-revision admission keys reset counters | Updating limits permits excess parallel work | One tenant/code lease bucket |
| Jsonschema considers integral floats integers by default | Input intended to be strict may be coerced | Explicit strict integer/number type checker |
| Callback traces can capture arguments/results | Safe local logs alone do not prove no sensitive trace leakage | No user callbacks; verify runnable tracing configuration and sanitize this path |

## 6. Wire Contracts and Dependencies

### 6.1 Generic invoke

POST `/api/v1/dsh/tools/{toolCode}/invoke` with exactly one verified DSH Bearer.
toolCode pattern: `[a-z][a-z0-9_]{0,63}`. Content-Type application/json; no query
parameters or content encodings. Reject unknown envelope fields and duplicate
JSON keys. The code identifies the publication, never a saved tool name lookup.

```json
{"arguments":{"query":"search terms"}}
```

```json
{"tool":"bs_web_search","result":{"results":[],"truncated":false}}
```

No data wrapper. Generic result can be any valid bounded JSON value. Non-JSON
text is `{"text":"..."}`; empty ordinary text becomes `{"text":""}`.
JSON strings are parsed once only; nested encoded strings remain strings.
Malformed JSON-looking ordinary text is still text, but cannot pass search
validation. Transport failure never reaches this successful normalization path.

### 6.2 Publication management

GET `/api/v1/dsh/admin/tool-publications?offset=0&limit=50` (limit 1-100),
GET/PUT `/api/v1/dsh/admin/tool-publications/{toolCode}`. Standard browser identity;
no body/query tenant override. Successful admin APIs retain standard resp_200 data
wrapping; only invoke is the external tool/result contract.

```json
{
  "tool_id":123,
  "enabled":true,
  "limits":{"timeout_seconds":30,"max_input_bytes":65536,
            "max_output_bytes":1048576,"max_concurrency":4}
}
```

PUT requires tool_id and enabled; omitted limits use defaults as a full replace,
not a partial patch. Strict booleans/integers, no extra keys. Response data adds
tool_code and revision; list data is `{data:[...],total:N}`. No key/host/schema
dump is returned. Every replacement validates the proposed saved target and edit
permission, including disabled mappings.

### 6.3 Supported saved OpenAPI subset

OpenAPI 3.0.x documents saved as JSON or safe YAML. Bound parsing depth/node count
and reject duplicate keys, recursive aliases and ambiguous operationIds. Resolve
at most a local `#/components/schemas/<name>` body-object reference; no remote
refs, nested refs, allOf/anyOf/oneOf, nullable, format coercion or arbitrary regex.

Support GET with flat scalar query parameters, and POST/PUT/DELETE with only an
application/json flat object body or only flat query parameters. No mixed body
and query, path templates, header/cookie inputs, path-level parameters, uploads,
arrays or nested objects in the first release. Reject these explicitly at publish.
Require one unique original operation matching saved path/method/operationId and
parameter names/locations/types. Use saved server_host as the operator-selected
destination; operation-level server overrides cannot silently change it.

Allow scalar string/integer/number/boolean, required, enum, minLength/maxLength,
minimum/maximum, minProperties/maxProperties and descriptive annotations.
Effective root object is closed to undeclared arguments. Do not inject defaults
or coerce values; fail unsupported validation keywords. Reject names colliding
with proxy, callbacks, config, run_manager or other executable wrapper controls.
Authentication parameter names cannot also be client-controlled arguments.
Bound schema and strings before validation, and reject non-finite numeric values.

### 6.4 Search contract and configuration

Reserve code bs_web_search for flat required query, trimmed length 1-4096; only
optional maxResults (strict integer 1-20) may additionally be declared. A query-only
published schema rejects maxResults. Supported maxResults limits output locally
and is forwarded only when declared. No model/commands accepted on this code.

Result must be an object with results array, strict boolean truncated, and optional
output string. Each row has HTTP(S) absolute url (no credentials, at most 8,192
characters), optional title (4,096), snippet (16,384) and published_at (128) strings;
output limit 65,536 characters, all also constrained by byte caps. Reject unknown
business fields, error objects, opaque encrypted output and non-search text.
Preserve row ordering. Validate the entire bounded source array before taking
maxResults or 20 and OR its upstream truncation flag with local truncation.

Operator sequence: create/import a saved OpenAPI tool targeting an actual flat
query service; save its server credentials; grant intended users use access;
publish that tool ID as bs_web_search. The raw Sub2API alpha/search service needs
its separate model/commands adapter and is incompatible when pointed at directly.
Schema import does not supply such a service. No production adapter is verified.

### 6.5 Error contract

Use DshRoute real HTTP error envelope with request_id, no legacy business-code
status masquerading as HTTP. Apply the same safe error mapping to body limits,
JSON validation, permission adapters and bounded transport exceptions.

| Proposed code | Client code | HTTP |
| --- | --- | --- |
| Existing 26101 | invalid_request | 400 |
| Existing DSH authentication/session errors | Existing identifiers | Existing 401/403 |
| 26131 | tool_publication_not_found | 404 |
| 26132 | tool_permission_denied | 403 |
| 26133 | tool_publication_invalid | 400 |
| 26134 | tool_arguments_invalid | 400 |
| 26135 | tool_concurrency_exceeded | 429 |
| 26136 | tool_upstream_failed | 502 |
| 26137 | tool_result_invalid | 502 |
| 26138 | tool_execution_timeout | 504 |
| 26139 | tool_service_unavailable | 503 |
| 26140 | tool_input_too_large | 413 |
| 26141 | tool_output_too_large | 502 |
| Existing 26128 | internal_error | 500 |

Codes 26131-26141 were unused in the beta4 error registry during design inspection;
recheck before implementation and register them in the existing DSH module.
Disabled or missing publication is 404. A formerly valid publication whose current
target is stale/inconsistent is 503, not a successful fallback. HTTP upstream
non-2xx and all redirects are 502; no retry. Known permission backend failures
are 503, not 403. Unknown internal defects are safely logged and become 500.

Do not log exception messages/traceback locals containing upstream data; log safe
classification and stack frames without sensitive values where needed. Retain
trace/request ID, tenant, tool code, revision, tool ID, duration, outcome and byte
counts. Exclude query, arguments, output, headers, complete URL and credentials.
Return no-store and no-referrer; preserve metadata-only ToolExecutor telemetry.
Execute this path with external runnable tracing disabled (including inherited
LangSmith tracing context), no caller callbacks, and a service-owned RunnableConfig;
otherwise automatic tool traces can capture raw arguments/results outside local
logs. Test tracing suppression explicitly instead of assuming callbacks=[] is enough.

### 6.6 Internal and external dependencies

| Dependency / interface | Contract and change risk |
| --- | --- |
| ToolPublicationService.save/read/list/invoke | DSH orchestration consumes tool-owned snapshots and safe errors, not business ORM |
| PublishedToolService.prepare/authorize/build | Tool-owned tenant/schema facts, permission facade and ToolExecutor assembly |
| DshAccessService.authenticate/principal_scope | F062 issuer/audience/session contract changes affect every external invoke |
| ToolExecutor strict initialization entry | Must retain saved permissions and telemetry; never change legacy defaults |
| jsonschema 4.25.1 / httpx / safe YAML parser | Validator and bounded async transport; no new binary or provider SDK |
| Config and existing SQLAlchemy sessions | Transactional updates must work on MySQL and DM8; no MySQL-only SQL |
| Shared Redis | Admission cannot be replaced by process memory; loss/failover recovery as section 4.4 |
| Gateway and real configured tool service | Proxy/filter/license/header behavior and adapter compatibility require live evidence |
| Work plugin | Must send arguments envelope and extract result at the new invoke path; separate repository work |

## 7. Validation and Observability

Unit tests cover schema subset/strict validation, JSON normalization/search rules,
destination normalization, safe errors and all limit boundaries. HTTP tests run
actual endpoint/middleware admission with signed tokens and stubbed identity/
introspection dependencies; a stub is not proof of live Gateway acceptance.
Use two distinct local HTTP fixture services through the actual saved OpenAPI
executor and bounded transport to prove generic invocation, bytes/status/cancel
behavior, and legacy defaults. Ordinary non-admin callers are mandatory.

Redis tests use two independent lease/service instances and shared fakeredis Lua
for deterministic races, cap edits, owner release and cooldown. Real isolated
Redis tests prove scripts, clock and timeout semantics. SQL tests cover config
unique-create/update/disable races and tenant listing on isolated MySQL; DM8
verification is a separate reported integration result, never implied by SQLite.
Compare the same regression selection against beta4 when baseline failures exist.

Run focused DSH/tool tests, Ruff, F821 and architecture guard for changed source.
Run locales generation/check and check-i18n for the added backend error-code copy;
do not update frozen baselines to hide new violations.
The later tasks/e2e report must trace all AC-01 through AC-32 and state skipped
checks. No functional tests are claimed at design stage.

Manual acceptance using actual credentials (never embed tokens in documents):

1. Create an actual compatible saved search tool in the existing tool management
   UI and record its ID; grant use to an ordinary test user.
2. In an authenticated admin browser, call the management APIs, for example:

```javascript
await fetch('/api/v1/dsh/admin/tool-publications/bs_web_search', {
  method: 'PUT', credentials: 'same-origin',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({tool_id: 123, enabled: true})
}).then(response => response.json());
```

3. With a current Desktop test token, POST
   `/api/v1/dsh/tools/bs_web_search/invoke` through the actual Gateway using
   `{"arguments":{"query":"test"}}`. Verify top-level tool/result, real search
   links, and the ordinary user's actual identity/tenant in safe metadata.
4. Disable the publication and revoke use/session separately; verify rejection
   before the fixture/service receives work. Repeat with tenant B and an ordinary
   non-search tool. Verify Work's result unwrapping separately in its repository.
5. Record actual Gateway configuration/license behavior and tested deployment;
   source routing alone is insufficient. No deployment is part of this branch.

## 8. Deferred Work and Reconsideration

Nested schemas, path/header input support, general business result schemas, a
management UI, long-running jobs and additional protocols require separate scope
and regressions. Automatic provider conversion is not part of generic execution.
Real provider adapter availability, deployed Gateway/Work acceptance and DM8
execution remain explicit unverified items until exercised.

The same saved destination/credential can change through existing tool management;
every invocation uses the latest validated snapshot, without pinning old secrets.
Invocation does not promise exactly-once upstream side effects or rollback.
Strong failover admission without the stated Redis drain assumption requires a
separate authoritative admission protocol, not a claim based on lease tests.

## Revision History

2026-10-15: Proposed design after user-confirmed spec; current source gaps and
planned opt-in execution path documented before implementation.
