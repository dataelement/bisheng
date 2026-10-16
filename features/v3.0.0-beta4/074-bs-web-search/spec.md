# F074 - Existing OpenAPI Tool Invocation for Work

Status: user confirmed on 2026-10-15. The latest corrections remove search-specific
constraints and separate publication management. All supported saved API tools
are callable through the common entry point, subject to existing tenant/use rights.
This supersedes the earlier publication-management requirements.
Release: v3.0.0-beta4. Dependencies: existing F062 identity, tool records/executor,
business authorization. See [design](./design.md) and [release contract](../release-contract.md).

## 1. Scope

Expose existing API tools using their existing tool_key. No registration, alias
mapping, extra publication state, revision or DSH-specific enable step is required.
Use the saved OpenAPI input schema, server destination and credentials.
No Gateway/Work edits, management UI, provider service hosting, permission grants,
new token issuance or automatic upstream retries. MCP/preset execution and expanded
OpenAPI forms remain outside this first implementation; unsupported tools fail explicitly.

## 2. Acceptance Criteria

### 2.1 Existing Tool Lifecycle

**AC-01** - THE SYSTEM SHALL invoke existing tools without separate publication.
**AC-02** - THE SYSTEM SHALL reuse current tool use authorization; invoking SHALL
NOT require tool edit rights or tenant-admin status.
**AC-03** - THE SYSTEM SHALL reuse existing saved schema, destination and credentials,
without a second mapping/configuration store.
**AC-04** - THE SYSTEM SHALL resolve the existing tool_key within the verified tenant,
including when the same key exists in other tenants.
**AC-05** - Unsupported tool types or OpenAPI forms SHALL fail explicitly.
**AC-06** - Deleted tools/categories SHALL NOT admit new executions; previously
admitted executions may finish.
**AC-07** - THE SYSTEM SHALL provide no separate tool-publication management API,
enable state, mapping revision or DSH registration step.

### 2.2 Identity and Resource Access

**AC-08** - Invocation SHALL require the existing verified DSH access credential.
**AC-09** - Forged credentials, browser cookies and other unsupported credential
forms SHALL NOT authorize invocation.
**AC-10** - Tenant/user identity SHALL derive from verified credentials, without
request-controlled identity overrides or inherited administrative bypass.
**AC-11** - Tool and category tenant/deletion/parent facts SHALL be checked before
permission shortcuts. Missing or out-of-scope resources SHALL return unavailable.
**AC-12** - Each invocation SHALL check current saved-tool state and use permission.

### 2.3 Inputs and Execution

**AC-13** - Requests SHALL contain only an arguments object; duplicates, identity,
destination, credentials and executable wrapper controls SHALL be rejected.
**AC-14** - Supported saved OpenAPI constraints SHALL validate arguments without
coercion or default injection. Unknown arguments SHALL be rejected.
**AC-15** - Execution SHALL use the same verified saved tool/category snapshot;
caller inputs SHALL NOT alter credentials, transport controls or destinations.
**AC-16** - Different supported OpenAPI schemas SHALL use the same invocation route.
**AC-17** - Success SHALL return top-level tool/result using the requested tool_key.
**AC-18** - JSON SHALL be parsed once; ordinary text SHALL use a stable text wrapper.
**AC-19** - Transport/execution failures SHALL remain failures; business fields
SHALL NOT be interpreted as generic failure indicators.
**AC-20** - Invalid input, authentication, denial, unavailable tool, unsupported
schema, concurrency, upstream, dependency and timeout errors SHALL be distinguishable
by HTTP status and safe error code with a correlation identifier.
**AC-21** - Client errors/logs/traces SHALL NOT disclose saved credentials,
configuration dumps, authorization headers or raw sensitive provider bodies.

### 2.4 Business Contract Ownership

**AC-22** - All keys, including bs_web_search if it is an actual saved key, SHALL
use their OpenAPI argument schema without name-specific field restrictions or trimming.
**AC-23** - No tool key SHALL require a search-specific result shape.
**AC-24** - Tool services SHALL own business result/error validation; generic
normalization SHALL preserve bounded JSON fields and ordinary text.
**AC-25** - The invocation layer SHALL NOT truncate collections or change business
truncation flags according to tool names or argument names.
**AC-26** - Operators SHALL configure a real service matching the saved schema;
schema import SHALL NOT be represented as creating or hosting that service.

### 2.5 Execution Bounds and Compatibility

**AC-27** - All tools SHALL use common input/output/timeout/concurrency limits;
no per-publication settings are required.
**AC-28** - Oversized input/output SHALL stop with an identifiable failure, including
streamed bodies and serialized result expansion.
**AC-29** - Deadline and disconnect cancellation SHALL close upstream resources
and release this request's capacity; upstream effects cannot be undone.
**AC-30** - Concurrent API replicas SHALL share per-tenant/tool_key admission state.
Redis outages SHALL reject new work; first use SHALL require no initialization.
Expired owners SHALL NOT release successor leases. State-loss recovery requires
the documented operational drain.
**AC-31** - Destinations/redirects that invoke this tool API itself SHALL be rejected.
**AC-32** - Existing Agent/workflow tool and Desktop identity/model behavior SHALL
remain compatible; neighboring routes SHALL NOT gain DSH-credential bypass.

## 3. Acceptance Evidence

Use ordinary users for allow/deny, tenant A/B isolation, current deletion and
permission checks. Local HTTP stories must invoke two real saved schemas through
ToolExecutor with no publication fixture. Real Gateway, Work, account/FGA, MySQL/DM8
and provider evidence remain separate deployment checks.
