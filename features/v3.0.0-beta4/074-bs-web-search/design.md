# Design: F074 Existing OpenAPI Tool Invocation

Release v3.0.0-beta4. Updated 2026-10-15.
User confirmed removal of separate publication management and search-specific
branches. Local implementation; deployment acceptance pending.
Inputs: [spec](./spec.md), [discovery](./discovery.md), [release contract](../release-contract.md).

## 1. Scope and Decisions

Expose existing supported API tools via their existing tool_key. Reuse current
tool configuration, tenant isolation, use permissions and ToolExecutor. Do not
create aliases, publication records, enable flags, revisions or management APIs.
Tool services own business semantics. No Gateway/Work, provider hosting or UI edits.

Architecture follows docs/constitution.md C1-C8. SQL lives only in repositories.
DSH identity and credentials reuse F062. A proxy route alone does not prove live
Gateway compatibility.

The extra mapping was removed because the existing tenant-qualified tool_key and
tool lifecycle already supply identity and authorization. Reconsider aliases or
DSH-specific availability only for a separately confirmed product requirement.

## 2. Wire Contract

POST /api/v1/dsh/tools/{toolCode}/invoke
Authorization: Bearer <existing DSH access token>
Content-Type: application/json

toolCode is the existing tool_key, not a user-created DSH alias.
Accepted key syntax: 1-125 ASCII letters, digits, underscore or hyphen. This covers
current generated API tool keys and aligns with the existing database column.
The route validator, credential middleware and Redis key validator use the same syntax.

Request: {"arguments":{"query":"search terms"}}
Success example: {"tool":"tool_type_7_<hash>","result":{"results":[]}}

The saved schema determines arguments and business result. The example is not a
reserved search contract. No data wrapper; JSON is parsed once and ordinary text
becomes {"text":"..."}. No business error inference from an error field, row
validation, query trimming or collection truncation.

## 3. Invocation Flow

1. desktop_principal verifies the existing signed access token/session. Its
   verified timestamp starts the subsequent request deadline.
2. Read the arguments envelope with the common input/depth/node bounds; reject
   query parameters, duplicate keys, extra fields, non-finite numbers and controls.
3. ToolInvocationService enters principal_scope and strict_tenant_filter. No
   inherited admin visibility or bypass may widen the verified tenant.
4. SavedToolService reuses GptsToolsDao.aget_tool_by_tool_key and
   aget_one_tool_type under the normal ORM tenant filter. It checks both tenant
   IDs, parent and deletion state, then reuses ToolExecutor's existing use
   permission check. No separate query repository or permission implementation is added.
5. Unsupported types/schema fail explicitly. Validate saved input constraints
   without coercion/default injection, then initialize ToolExecutor from this
   verified snapshot. No SQL lock is held during upstream execution.
6. Acquire shared Redis capacity for tenant/tool_key. First use needs no registration.
7. Execute through init_saved_openapi and BoundedOpenApiTools. Use saved credentials;
   explicit verified method/destination/parameters prevent category extra overriding
   validated execution fields. Transport disables environment proxies and redirects.
8. Parse/normalize the bounded result and return requested tool_key/result.
9. On disconnect/deadline/error, cancel and await the execution task; close the
   response/client and release only this owner. Cleanup has a two-second deadline.

State/permission changes affect subsequent checks; admitted upstream work can
finish. No separate publication revision/disable serialization remains.
Execution uses a verified snapshot; this is not a tool-version pinning feature.

## 4. Common Bounds and Redis

| Limit | Default | Hard cap |
| --- | --- | --- |
| Timeout | 30 seconds | 60 seconds |
| Request bytes | 65,536 | 65,536 |
| Output bytes | 1,048,576 | 1,048,576 |
| Concurrent calls per tenant/key | 4 | 16 |
| Inspected schema bytes | 262,144 | fixed |
| Argument properties | 32 | flat scalars |
| String argument length | 4,096 | generic bound |
| JSON depth / nodes | 32 / 10,000 | fixed |
| Owner lease | 65 seconds | fixed |

ToolLimits supplies the common server-side policy; there is no per-tool management
surface in this feature. The endpoint bounds body time; service deadline includes
preparation, permission and execution. Actual upstream bytes and serialized result
are both capped. Accept-Encoding identity and reject encoded responses.

Redis hash key: dsh:tool:invoke:leases:{tenant:key}. Lua uses Redis TIME to purge
expired unique owner entries, count current owners and admit atomically. Each owner
expires logically after 65 seconds; the hash TTL bounds idle storage. Release deletes
only the owner's UUID. Redis errors/corrupt state fail admission. Different API
replicas share the same bucket; different tenants use separate buckets.

This assumes Redis retains acknowledged lease writes during normal operation.
Restart, eviction or failover that loses active leases can temporarily reset capacity;
operations must drain admission for at least 65 seconds before resuming after such
state loss. First use is intentionally immediate; no per-tool persistent marker or
cooldown initialization remains. No exactly-once upstream side effects are promised.

## 5. OpenAPI and Transport

Reuse existing saved tool/category records. First implementation supports API
tools (is_preset=0) with OpenAPI 3.0 and GET/POST/PUT/DELETE. MCP/preset tools return
tool_unsupported. This changes exposure policy for API tools, not supported protocols.

Support flat scalar query inputs, or an application/json object body for non-GET.
Types: string/integer/number/boolean; required, enum, minLength/maxLength,
minimum/maximum and root property counts. One local root components/schemas
reference is supported. Reject unsupported keywords/forms rather than silently
ignoring them. Unknown fields are rejected. bool/float are not strict integers.

Unsupported: nested object/array inputs, mixed body/query, path templates,
header/cookie inputs, operation server overrides, uploads or executable wrapper
names such as proxy/callbacks/config/run_manager. Saved auth parameters are not
caller-controlled. This is a bounded subset, not complete OpenAPI support.
Response-schema validation is not implemented; tool services own business checks.

Static saved HTTP(S) destinations only. Reject credentials in URLs, fragments,
ambiguous paths/encoding and invoke paths under any hostname. No redirects or
caller-controlled URLs. Unknown reverse-proxy rewrites/internal provider recursion
remain operational routing responsibilities.

## 6. Errors and Privacy

| Code | Client code | HTTP |
| --- | --- | --- |
| 26131 | tool_not_found | 404 |
| 26132 | tool_permission_denied | 403 |
| 26133 | tool_unsupported | 400 |
| 26134 | tool_arguments_invalid | 400 |
| 26135 | tool_concurrency_exceeded | 429 |
| 26136 | tool_upstream_failed | 502 |
| 26137 | tool_result_invalid | 502 |
| 26138 | tool_execution_timeout | 504 |
| 26139 | tool_service_unavailable | 503 |
| 26140 | tool_input_too_large | 413 |
| 26141 | tool_output_too_large | 502 |

Reuse DSH's real HTTP error envelope and request_id. Unexpected tool failures are
contained with safe exception type/correlation diagnostics; no provider body is
serialized/logged. private_http_logs suppresses task-local HTTP-library records
that could contain saved query credentials. Disable ambient LangSmith/callback
capture while retaining the existing executor metadata telemetry wrapper.

## 7. Ownership and Validation

DSH API/services own credential admission, envelope, common bounds, leases and
normalization. Tool-owned repository/service/schema/transport own saved resource
lookup, authorization and execution. Shared dependencies reuse Desktop auth;
models.py re-exports the dependency without changing its identity.

Tests focus on the new external API: two schemas without registration, signed JWT,
denial/deletion/missing/cross-tenant cases, argument/result forwarding, Redis caps,
disconnect and bounded HTTP. Existing executor/identity/model regressions are reused.
Tool lookup is injected and upstream HTTP uses MockTransport; real Redis is tested
separately. No tool save/publication or standalone SQL suite is added. Database
filtering and live identity/FGA/Gateway remain integration acceptance items.

Operator steps: configure a real API service in existing tool management; grant
use permission; obtain its tool_key; invoke through Gateway with DSH credentials.
No DSH publication PUT/enable step. Schema import does not host a provider or
convert protocols. Validate installed Work result extraction and the actual
Gateway/provider separately. No deployment or production compatibility is claimed.
