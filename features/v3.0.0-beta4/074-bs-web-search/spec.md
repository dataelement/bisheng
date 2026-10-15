# F074 - Published Tool Invocation for Work

Status: confirmed by the user on 2026-10-15. Discovery and spec are confirmed;
design confirmation and implementation remain pending.

**Related PRD**: [Confirmed discovery](./discovery.md), including the latest user
correction from fixed search to published-tool invocation.
**Priority**: P0 for authentication, isolation and bounded execution; P1 overall.
**Release**: v3.0.0-beta4.
**Dependencies**: existing F062 Desktop identity/session admission; saved OpenAPI
tool management/execution; existing business-resource authorization.
**Release contract**: [v3.0.0-beta4](../release-contract.md).

This specification defines observable requirements. Wire formats, endpoints,
storage, module boundaries and exact limit/error definitions belong to the
subsequent design. Confirmed discovery remains the input to that design.

## 1. Scope and User Stories

As a tenant administrator, I want to publish selected saved tools under stable
codes, control their availability and limits, and verify the saved publication,
so that enterprise clients can use approved capabilities.

As an authenticated enterprise user, I want to invoke a published tool with its
business arguments and receive a predictable result or identifiable failure,
so that Work can use my authorized tenant capabilities.

As a tool administrator, I want to publish another supported OpenAPI tool without
changing application code, so that the integration can grow beyond search.

Included: tenant-scoped publication management, authenticated invocation, saved
schema validation, current resource authorization, execution limits, generic
result normalization and the first search business contract.

Excluded: a management UI (the first release has functional management APIs),
Gateway/Work source changes (separate repositories), standalone search routing
(replaced by published invocation), MCP/preset/other unsupported protocols
(first-release support is limited to executable OpenAPI tools), provider service
hosting or Sub2API protocol conversion (owned by configured tools/adapters),
permission-grant editing, new token issuance, and automatic retries of potentially
side-effecting tools (retry semantics are outside this contract).

## 2. Acceptance Criteria

### 2.1 Publication Management

**AC-01** - WHEN a current tenant administrator or appropriately scoped global
administrator manages publications, THE SYSTEM SHALL provide functional create,
read, list, replace and disable operations within that verified tenant.

**AC-02** - IF an actor lacks current administration authority for the verified
tenant, THEN THE SYSTEM SHALL deny publication management without changing state
or disclosing another tenant's publication data.

**AC-03** - WHEN an administrator creates or replaces a publication, THE SYSTEM
SHALL require current edit authority on its bound saved tool category; an existing
publication SHALL NOT bypass that authorization on subsequent changes.

**AC-04** - THE SYSTEM SHALL identify a publication by a stable code unique within
one tenant and retain its concrete saved-tool binding, availability and execution
limits across requests and application restarts. The same code in another tenant
SHALL identify an independent publication.

**AC-05** - IF a publication code, target or limit is invalid, or its target is
deleted, outside the tenant or of an unsupported tool kind/schema, THEN THE SYSTEM
SHALL reject the change without replacing the previous valid publication.

**AC-06** - WHEN a publication is disabled, THE SYSTEM SHALL reject invocations
admitted after the completed disable operation; re-enabling a valid publication
SHALL allow new authorized invocations. Disabling SHALL NOT imply cancellation
of work already admitted before the operation completed.

**AC-07** - WHEN concurrent administrators update the same tenant/code, THE SYSTEM
SHALL retain one complete valid update without mixing bindings, availability or
limits from different updates; it SHALL NOT create duplicate publications.

### 2.2 Trusted Identity and Authorization

**AC-08** - WHEN an invocation is admitted, THE SYSTEM SHALL authenticate the
existing enterprise Desktop access credential, including cryptographic validity,
issuer, audience, expiry, current user/tenant activity and active session/seat.

**AC-09** - IF credentials are absent, duplicated, forged, expired, for the wrong
audience, or refer to a revoked session or inactive identity, THEN THE SYSTEM SHALL
reject invocation before the upstream tool is contacted. IF identity/session
verification is unavailable, THEN THE SYSTEM SHALL reject admission.

**AC-10** - THE SYSTEM SHALL derive invocation user and tenant exclusively from
verified identity and prevent request arguments, browser credentials or inherited
administrative context from substituting another identity or tenant.

**AC-11** - WHEN an invocation resolves a code, THE SYSTEM SHALL require an enabled
publication in that user's tenant and current use authority on its saved tool;
knowing a code or saved tool identifier SHALL NOT grant invocation authority.

**AC-12** - IF publication, tool or authorization state becomes unavailable,
deleted, unsupported, foreign to the tenant or denied before admission completes,
THEN THE SYSTEM SHALL reject invocation without falling back to another tenant,
unpublished tool or permissive authorization path.

### 2.3 Arguments and Generic Invocation

**AC-13** - WHEN a caller invokes a published tool, THE SYSTEM SHALL accept only
the generic argument envelope with an argument object and validate it against
the actual supported saved input schema before contacting the upstream service.

**AC-14** - IF input violates required fields, types, enumerations or supported
property constraints, contains unsupported extra fields or cannot be validated
faithfully, THEN THE SYSTEM SHALL return an identifiable validation failure
without executing the tool.

**AC-15** - THE SYSTEM SHALL read execution destinations, authentication and tool
definitions only from authorized server-side saved configuration and SHALL NOT
allow caller arguments to override internal execution configuration or identity.

**AC-16** - WHEN administrators publish at least two saved supported OpenAPI tools
with distinct input schemas, THE SYSTEM SHALL invoke both through the same generic
capability without application code or route additions and return each tool's
result without imposing search-specific input or output fields on other tools.

### 2.4 Generic Results and Failures

**AC-17** - WHEN a tool completes successfully, THE SYSTEM SHALL return the stable
published tool code and a structured result at the top level without an additional
business-data wrapper.

**AC-18** - WHEN a successful tool returns JSON text, THE SYSTEM SHALL parse it once
and preserve its JSON value, including object, array, scalar and null. WHEN an
ordinary tool returns non-JSON text, THE SYSTEM SHALL expose a stable text-result
representation rather than guessing a business result from that text.

**AC-19** - IF the invocation or upstream transport/executor reports failure,
THEN THE SYSTEM SHALL return an identifiable non-success response rather than
disguising it as successful tool output or successful empty search results.
Business-level result validation SHALL apply where the published business
contract defines it; the generic layer SHALL NOT guess arbitrary tools' semantics.

**AC-20** - WHEN a request fails, THE SYSTEM SHALL distinguish invalid input,
authentication failure, denied access, unavailable publication, concurrency
exhaustion, upstream failure, unavailable dependencies and timeout using documented
non-success status and error identifiers plus a correlation identifier.

**AC-21** - THE SYSTEM SHALL exclude credentials, saved configuration dumps,
authorization headers and raw sensitive upstream responses from client errors
and invocation diagnostics.

### 2.5 Search Business Contract

**AC-22** - WHEN `bs_web_search` is published, THE SYSTEM SHALL accept a nonempty
trimmed query within the confirmed input bound; optional result-count arguments
SHALL be accepted only when explicitly supported by its published input schema.

**AC-23** - WHEN search completes successfully, THE SYSTEM SHALL return the
confirmed search business result: a required result collection and truncation
indicator, optional output, and individual results with a required absolute HTTP(S)
URL and optional title, snippet and publication-time strings.

**AC-24** - WHEN a valid search returns no results, THE SYSTEM SHALL report a
successful empty collection. IF it returns malformed data, an error result,
ordinary text or opaque encrypted output, THEN THE SYSTEM SHALL report failure
without manufacturing search results.

**AC-25** - WHEN valid search results exceed the confirmed result bound, THE SYSTEM
SHALL validate all supplied results before trimming the collection and report
truncation; existing upstream truncation SHALL remain visible.

**AC-26** - WHEN an administrator configures search, THE SYSTEM SHALL support a
saved tool pointing to a real service that accepts the declared search arguments
and returns the confirmed search contract. Operator instructions SHALL distinguish
schema import from service creation and explain that raw Sub2API requires a
compatible tool/provider adapter rather than receiving a bare search query.

### 2.6 Bounded Execution and Operational Behavior

**AC-27** - THE SYSTEM SHALL enforce each publication's configured input size,
output size, execution timeout and simultaneous-invocation limits within the
confirmed hard caps; publication updates SHALL reject out-of-range limits.

**AC-28** - IF a request or upstream response exceeds its applicable size bound,
THEN THE SYSTEM SHALL stop its processing with an identifiable failure before
unbounded buffering; limiting only the final serialized result SHALL NOT satisfy
the upstream response bound.

**AC-29** - WHEN the execution deadline expires or a request is cancelled, THE
SYSTEM SHALL stop the invocation and release its admission capacity; a timeout
SHALL be distinguishable from an upstream failure. THE SYSTEM SHALL NOT report
that external side effects have been rolled back.

**AC-30** - WHILE invocations run on multiple application replicas, THE SYSTEM
SHALL enforce one shared concurrency limit per tenant/code. IF admission state
is unavailable, THEN THE SYSTEM SHALL reject new work. Capacity retained by an
abnormally terminated request SHALL become available again within a documented
bounded recovery period without allowing an expired owner to release a newer
invocation's capacity.

**AC-31** - IF a tool destination or followed redirect invokes this published-tool
capability itself, including another tool code or a configured local service alias,
THEN THE SYSTEM SHALL reject it without recursive tool execution.

**AC-32** - WHEN the feature is introduced, THE SYSTEM SHALL preserve existing
Agent/workflow saved-tool usage and existing Desktop identity/model functionality;
new routes SHALL NOT grant unauthenticated access to neighboring routes.

## 3. Boundaries and Acceptance Evidence

AC-06 defines admission behavior for disable races; already admitted work may
finish. AC-07 defines complete-update semantics without prescribing a storage
mechanism. AC-12 covers current target and permission revalidation. AC-29 does
not promise to undo upstream actions after cancellation or timeout.

Validation must include ordinary non-admin callers for allowed/denied invocation,
tenant A/B isolation, root-resource visibility and inherited administrative context.
An administrator-only smoke run cannot establish resource-authorization correctness.

Local deterministic acceptance must exercise the complete HTTP admission path,
at least two supported OpenAPI schemas, representative failures and the shared
concurrency behavior. Database compatibility and environment-dependent middleware
checks must state their actual execution environment and any untested dialect.

Real Work/Gateway/upstream acceptance must separately prove credential forwarding,
filter/license compatibility, Work's argument wrapping/result extraction and one
actual compatible configured search service. Fixtures or HTTP 200 alone cannot
establish deployed readiness. Missing environments or an absent provider adapter
must remain explicit unverified delivery items.

## 4. Design and Execution Pointers

The next gated artifact is design.md, which will own wire contracts, exact numeric
limits, error mapping, supported schema subset, persistence and concurrency
decisions, effective-destination checks and module/file boundaries. tasks.md will
subsequently map every AC to implementation and validation work.

No implementation, regression-test result, push, deployment or final acceptance
is asserted by this specification.
