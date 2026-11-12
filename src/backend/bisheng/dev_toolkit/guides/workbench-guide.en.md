# BiSheng cloud workbench protocol for Agents

Use the signed-in BiSheng Desktop identity and configured enterprise deployment. Never ask for a publishing key or create a long-lived service credential.

## Requirements before implementation

Determine the users, smallest business flow, whether processing must continue after Desktop closes, shared data and local-device dependencies. Prefer local for individual tasks without continuous processing; cloud for scheduled jobs, webhooks, continuous processing or team collaboration; combine local capabilities and cloud services when needed. Reuse confirmed context and ask only one necessary question at a time. Record the deployment rationale, shared versus personal state and conflict policy.

## Use and develop

Normal use loads the hosted production URL inside the native workbench and checks the visitor's use permission. Do not fetch a source project or run a local business backend. Business queries, record edits and existing settings use business APIs. Fetch source only for an explicit request to change style, layout or application functionality.

This guide is served by the enterprise platform and is shared by cloud workbenches and hosted applications. Do not ask for a local Markdown attachment.

First call `cloud_workbench` with `operation: "guide"`; the tool returns this enterprise server’s guideUrl; visit that URL instead of reading a local Markdown attachment. Use the tool for the operations below. The authenticated local Harness transport is `POST /api/desktop-workbenches/cloud` with JSON:

- `{"operation":"list"}` lists usable online apps; follow next_cursor.
- `{"operation":"list","managed":true}` lists editable apps.
- `{"operation":"create"}` allocates an empty managed directory and projectId. Define requirements first, then create source and bisheng-app.yaml there.
- `{"operation":"checkout","appId":"real app ID","versionId":"real version ID"}` authorizes source editing and safely extracts a verified source archive into a new directory, returning projectId, path and baseVersionId. Never overwrite another directory or run untrusted install scripts.
- `{"operation":"publish","projectId":"real project ID","releaseNotes":"description"}` packages the managed source and submits as the signed-in person through scan, precheck, approval and release. Existing projects retain the checked-out baseline. Merge a stale baseline instead of overwriting. Do not infer destructive database-change confirmation.
- `{"operation":"progress","appId":"real ID","deploymentId":"real receipt ID"}` observes the actual pipeline state. Upload acceptance does not mean production is online.

Hosted pages cannot access this host channel. Never obtain platform tokens, publishing keys, cookies or production database files. Preserve source and genuine failure receipts. Reconnect after session expiry or enterprise switching; do not publish a project into a different enterprise identity.

When a release reaches failed, stop polling and report its stage, error code, platform hints and management link. Fix and self-test only the current application project when the platform diagnostic identifies an application-source problem, then request publication confirmation again. Platform, node and transport failures require an administrator. Do not investigate a failed release by scanning the computer, platform source, host process environments, Docker, service configuration or credentials.

## Enterprise SDK and runtime contract

Create/checkout returns toolkit URLs for the currently configured enterprise, including any reverse-proxy prefix. Fetch versionsUrl and sdkGuideUrl first; platformWiringUrl returns a tar.gz skill bundle: download to a temporary directory, extract it, read SKILL.md and its realtime sample; do not treat the archive as plain text. Get bisheng-sdk from sdkIndexUrl using the version advertised by that server, including for local tests. Do not scan the computer or search public PyPI for the enterprise SDK. Keep its wheel and dependencies out of the uploaded source package; the hosted builder installs the declared dependencies. A missing or incompatible toolkit is a concrete deployment prerequisite, not permission to invent authentication or persistence protocols.

## Shared state and continuous execution

Immutable source releases and persistent business data have separate lifecycles. Browser localStorage is not authoritative shared storage. SDK 0.1.2 `bisheng_sdk.realtime.RealtimeStore` commits SQLite records, revisions, idempotency results and replay events in one transaction. It is for the existing single-writer runtime contract, not multi-replica SQLite writes.

Business APIs obtain trusted visitor identity from the platform and enforce their own data permissions. Never trust userId/tenantId in request bodies. SSE carries authorized invalidations; clients re-fetch permitted data. Resume by cursor, or reload an atomic snapshot and watermark when replay expired. Reject stale revisions and scope idempotency keys to the visitor. The SDK fingerprints the complete value: retry the same business input without injecting a new timestamp or random value on each attempt. Test retries across seconds and after a lost response. Keep the unsaved draft baseline revision separate from the latest server snapshot: SSE, background reads and reconnects must never advance that baseline. Only an explicit user rebase may do so. Ignore delayed snapshots that would regress an already observed revision, and restore the subscription when permission recovery is followed by an explicit reload. Filters, scrolling and unsaved inputs remain personal. Obtain trusted identity before restoring drafts or caches, and namespace them by tenant, application and user. Switching accounts in one browser must not restore another user's draft, baseline or saved status. Stop subscriptions on authorization failure and retain only the current user's draft for recovery. Character-level editing and shared-canvas CRDT require a separate explicit requirement.

Cloud scheduling, background workers and webhooks must continue without an open page; page timers do not satisfy a continuous-processing requirement. After release, guide the owner to team visibility management without changing permissions automatically.

Desktop requires native confirmation before source download or snapshot submission. Explain the target app, version, release summary and migration impact, then wait for the user. Schema changes require a separate native acknowledgement checkbox. A tool argument cannot replace this confirmation. Renderer requests are limited to discovery, guides and progress; use cloud_workbench for development operations.

Only a validated successful mutation receipt may clear a pending operation or unsaved draft. A snapshot fetched after HTTP 409 is still a read result, never a save receipt: preserve the draft and its baseline until explicit rebase and a successful mutation. Test the actual asynchronous UI handler for this path. After successful recovery, update connection feedback and clear the transport error from that outage while preserving independent save-conflict or mutation errors. On authorization loss, disable save and mutation-retry controls and reject stopped-state writes in the handler as well as closing subscriptions. Reconnect must survive several consecutive network or snapshot failures using bounded backoff; one failed recovery fetch must not stop future attempts. Preserve the cursor and draft, stop on authentication/authorization denial, and resume after explicit reload following restored permission.

## Acceptance

Verify ordinary-user allow/deny pairs, two distinct users synchronizing records, conflicts, retries, reconnect replay, revocation, code updates and process replacement with persistent data. Execute the shipped browser script through its real startup path: tests that instantiate a factory and call boot themselves do not prove that the production page starts. Verify required jobs after Desktop closes. List unverified items honestly; builds do not prove deployment or installation.


Account and server binding: reuse the current desktop account, tenant and configured server. Do not introduce separate cloud connection or publishing-key settings. Discover applications automatically after sign-in; refresh discovery and clear stale publishing selections after an account or enterprise change. Sign-in uses the desktop account flow.

## Agent-led publishing conversation

“Cloud workbenches” lists hosted enterprise applications separately. Both the client Apps page and the admin Build → Apps page link to the same catalog. This page only discovers and opens workbenches; it has no manual publishing form. Users start with “Make my workbench” or a development conversation. The Agent completes the flow in that conversation without sending users to a publish button:

1. Reuse confirmed requirements, explain the local/cloud/hybrid deployment rationale in business language, and confirm the smallest scope.
2. After implementation and verification, show the change summary, target, schema effects and proposed team visibility. Proceed when release authorization already exists; otherwise confirm in the conversation. Permission to develop does not imply permission to release or broaden access.
3. Use the `cloud_workbench` tool with create/checkout, publish and progress, genuine project IDs, version baselines and receipts. Read the returned developmentWorkspace status after create/checkout. If ready is false, stop and ask to open its exact directory as the development conversation workspace, carrying the confirmed requirements and projectId. Changing working_directory alone does not change the writable workspace. Do not inspect Desktop internals or broaden sandbox permissions to work around this boundary.
4. Submit through existing scan, precheck and approval steps, and check progress. Distinguish submitted, awaiting approval and online. Never approve on behalf of an administrator. Preserve source and receipts on failure, and merge stale baselines.
5. Verify the production entry, explain native workbench switching, and guide the owner to team visibility management. Never change member permissions without authorization.

Publishing belongs to the development conversation. Viewing apps, querying data and changing business records never triggers source download or code deployment.
