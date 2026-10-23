# Design: Shared workflow and assistant conversations

**关联**: [spec.md](spec.md) · [request.md](request.md) · [tasks.md](tasks.md)
**版本**: v3.0.0
**最后更新**: 2026-10-21
**状态**: User confirmed 2026-10-21; implementation in progress. Proposed modules below are not yet shipped.

## 1. Goals and non-goals

Extract client-based workflow/assistant conversation behavior into `@bisheng/chat`.
Client app chat, platform test, annotation and application-history viewers consume
one presentation and interpretation implementation. Platform contributes its QA
and annotation operations through typed host callbacks.

Daily chat, task/Linsight, app navigation, backend contracts, permission policy
and UI redesign are outside this change. The existing `Config.tsx` modification
and `filterByUserPagination.test.tsx` are unrelated working-tree changes.

## 2. Constraints

Follow [constitution](../../../docs/constitution.md) C1–C8 and
[release contract](../release-contract.md) V3-INV-5. No backend/API/schema changes.

- `@bisheng/ui` is a presentation-only foundation; chat business components belong
  in a separate source-shipped workspace package, alongside `file-viewers`.
- Client uses Recoil and react-query v4; platform uses Zustand and react-query v3.
  The package imports neither those stores/query clients nor application aliases,
  request modules, router, auth context or application-specific i18n hooks.
- Do not add Recoil atoms/imports. Existing client host integrations may retain
  their current imports while leaf components become controlled by props.
- No shared mutable singleton conversation state. Rendering two sessions must
  not share drafts, source IDs, form selection, pending uploads or callbacks.
- UI work follows current `packages/ui/docs/` and landed components. The source
  of conversation layout/behavior is client `pages/appChat`, not platform forks.
  Do not restyle `@bisheng/ui` or introduce a new UI/state-management library.
- Existing v1/v2/v3, guest/share auth, host/base URLs and upload contracts stay
  at the host boundary. A package callback is not an authorization decision.

## 3. Decisions

### D1. One business package with explicit subpath boundaries

Alternatives: move everything to `@bisheng/ui`; import client source from platform;
add a workspace package. Select `packages/chat`, named `@bisheng/chat`, exporting
React components from the main entry and pure contracts/normalizers/reducers from
`@bisheng/chat/core`. A styles entry is explicit and limited to chat composition.

Reason: ui's contract forbids business services, while importing client directly
pulls Recoil, contexts, route/asset assumptions and task/daily dependencies into
platform. Both current applications already consume source-shipped packages.
Revisit only if core has non-React external consumers requiring independent
versioning; no separate core npm package in this phase.

### D2. Share interpretation and UI; keep application orchestration

Alternatives: transplant the client providers/stores/socket map; share only
static bubbles; share pure message interpretation plus controlled UI. Select the
third. Client and platform keep authentication, endpoint selection, API calls,
connection creation/disposal, navigation and business writes. Shared functions
interpret history and live events; hosts feed snapshots to shared components.

Reason: static-only sharing leaves the two history/stream parsers drifting,
whereas provider transplantation would violate stack boundaries. Current
`useWebsocket.ts`, `useChatHelpers.ts` and both platform message stores combine
protocol handling with application state and API calls.

Existing client background-session and standalone auto-rerun orchestration stays
in client. Platform test initialization stays in the platform adapter. Shared
code never decides to open a connection merely because a message is mounted.
Revisit transport sharing after the hosts' handshake/lifecycle contracts converge.

### D3. Explicit operation capabilities, separate from conversation mode

Alternatives: reuse overloaded `debug`/`mark`/`readOnly` flags; introduce independent
execution, feedback, annotation and resource-preview capabilities. Select explicit
capabilities, defaulting to disabled. Hosts derive them from existing permissions.

Reason: platform currently passes `debug` for historical viewing while interactive
forms and stores are elsewhere; client `readOnly` sometimes carries a share token.
A single flag cannot express 'inspect citations and annotate, but never execute'.
Revisit only when a new host requires a distinct capability; do not add mode-name
branches to each message component.

### D4. QA forms and writes remain platform business compositions

Select shared action entries and a shared Q/A selection utility, with platform
callbacks opening existing `AddSimilarQuestions` and `SaveQaLibForm`. Reject moving
knowledge selection, permission requests, annotation task navigation and QA write
APIs into the package.

Reason: those dialogs manage existing QA resources, not conversation presentation.
The shared callback supplies exact source identity, question and selected answer;
platform owns validation, saving, errors and completion status. A failed save must
not be reported as marked. If the existing dialog closes before a failed request,
fix only its success/failure lifecycle required by AC-14, not its business rules.
Revisit when a second host actually needs to manage QA libraries.

### D5. Isolate daily/task dependencies during extraction

Reject moving all `components/Chat` or editing daily/task consumers to make the
new package work. Select a bounded client-based extraction for app chat only.

Client app-chat currently imports Markdown, citations, selection/export and media
helpers also used by daily/task chat. Extract the app-chat-required implementation
into the new package, replace application context dependencies with host services,
and wire only workflow/assistant consumers. Daily/task entry points and existing
contracts remain unchanged. Their old Markdown path can remain until separately
approved; it is not an alternative workflow/assistant production renderer.

The package may not import the original client Markdown as a shortcut, nor keep
platform's old Markdown as a permanent second workflow/assistant renderer.
Revisit shared daily/task utilities only in that later explicitly authorized scope.

## 4. Current code and target flow

### 4.1 Verified current implementation (not planned work presented as shipped)

| Entry | Current responsibility | Main coupling |
|---|---|---|
| client `pages/appChat/index.tsx`, `ChatView.tsx` | workflow/assistant initialization, history, host layout | route, Recoil, auth/share/version |
| client `pages/appChat/ChatMessages.tsx`, `components/*` | message categories, forms, choices, run details | Recoil selectors, localize, action events |
| client `pages/appChat/useChatHelpers.ts`, `useWebsocket.ts` | WS handshake, events, state writes | API version, global socket map, Recoil |
| client `components/Chat/Messages/Content/Markdown.tsx` | Markdown, citations, code/diagram/media/artifacts | client APIs, contexts, permissions; also daily/task |
| platform `BuildPage/flow/FlowChat/` | workflow test and workflow history display | global Zustand store, socket and file APIs |
| platform `components/bs-comp/chatComponent/` | assistant test/history and message/citation display | separate global store, APIs and contexts |
| platform `LabelPage/taskAppChats.tsx` | workflow/assistant annotation, Q/A actions, task status | both platform message stores and QA dialogs |
| platform `LogPage/useAppLog/appChatDetail.tsx` | historical workflow/assistant viewing | both stores, legacy debug semantics |

Pure protocol functions do not yet exist as a shared module. Common-category
interpretation is split across client helpers and two platform stores. Client
node/form/choice behavior is the starting implementation; platform-only debug
run details are retained as optional shared blocks.

### 4.2 Target data flow

1. Host verifies access, resolves application/version/session and fetches raw
   backend history rows. Its request adapter may unwrap the response envelope,
   but must not filter categories, parse message/files, rewrite roles/category or
   derive display fields before calling shared core.
2. Shared core normalizes raw history exactly once into an ordered typed snapshot.
   Move the transformations currently inside client `api/apps.ts:getChatHistoryApi`
   and the platform history stores into core. Host owns the
   snapshot's storage and updates; existing state libraries are not imported into chat.
3. For interactive sessions only, host opens its current connection and forwards
   decoded events through shared mode-specific normalization and the pure reducer.
4. `AppChatConversation` displays the controlled snapshot using common message,
   composer, form, choice, reasoning, run, file and citation components.
5. User actions invoke typed callbacks. Host checks the current session/capability
   and executes its existing operation; resulting events update that session only.
6. History viewers use the same presentation without execution callbacks or a
   live transport lifecycle. Annotation adds only the authorized Q/A callbacks.

Client state adapters remain at the current app-chat hook/entry boundary. Existing
Recoil state may keep required sidebar/background-session metadata; message
classification and stream merging move to shared pure functions, not two adapters.
Platform replaces global viewer/test message storage with per-mounted-session
adapters/local state as needed; it does not copy the client atom graph.

The client request split adds a raw-history fetch for the new path, preserving
URL/version/share headers, pagination and response errors. Workflow/assistant
initial load and load-more both call it, then core. Inventory remaining callers
of legacy `getChatHistoryApi` before retiring its display transformations: any
out-of-scope caller keeps compatibility via an explicitly documented adapter;
never feed its already-transformed result into the new normalizer. Unsupported
raw categories are classified/preserved or explicitly ignored by core fixtures,
not silently dropped in a host. No daily/task request contract is changed.

### 4.3 Package and host responsibilities (proposed paths)

| Path | Owns | Does not own |
|---|---|---|
| `packages/chat/src/core/types.ts` | public snapshot, message, event and action contracts | host auth/DTO/API types |
| `packages/chat/src/core/normalizeHistory.ts`, `normalizeEvent.ts`, `reduceConversation.ts` | workflow/assistant history and event interpretation, immutable updates | socket connection or HTTP |
| `packages/chat/src/core/selectQaPair.ts` | deterministic question/answer selection and source identity | knowledge/QA writes |
| `packages/chat/src/components/AppChatConversation.tsx` | shared layout, history scrolling and action placement | navigation or global session state |
| `packages/chat/src/messages/` and `forms/` | client-based messages, composer, forms/choices and run details | app stores and request modules |
| `packages/chat/src/content/` | client-based Markdown, citations, attachment/media and code/diagram presentation | auth-specific URL resolution and task timelines |
| client `pages/appChat/adapters/` | existing Recoil bindings, version/guest/share lifecycle, API/preview/export services | duplicate message renderer or parser |
| platform `components/bs-comp/appChat/adapters/` | per-panel snapshots, history/test connections, file/preview services | old global message singleton |
| platform `LabelPage` and `LogPage` | QA dialogs, annotation task/status, authorized viewing | private copies of message/Markdown presentation |

Split touched files above 600 lines by these responsibilities; new package files
have strict types and no legacy suppression headers. Keep scope-specific source
provenance in the design/tasks when extracting shared client dependencies.

## 5. Known pitfalls and treatment

| Fact | Failure if ignored | Treatment |
|---|---|---|
| `id`, `message_id` and locally generated keys differ; platform answer annotation currently uses `message_id` in one path | QA writes attach to the wrong answer or no message | core identity retains stable UI key and optional server source ID separately; actions use verified source IDs |
| Workflow parent links may be absent; system/run/form rows interleave with Q/A | adjacent-row pairing selects a tool result as the user's question | `selectQaPair`: use validated turn/parent relation when available; otherwise scan original ordered semantic user inputs, skipping run/system rows; selected answer identity stays exact |
| A question can have multiple output answers | saving one answer accidentally concatenates another turn | each eligible answer is selectable with its own source ID, paired with the same corresponding input |
| QA writes can complete after switching sessions or opening another dialog | old A success mutates B status or closes B's dialog | platform captures the immutable QA operation context; origin-only writes, active-generation-only UI updates, per-dialog operation checks |
| Client history API already filters, parses and rewrites records | double normalization retains a hidden host parser and loses data before core sees it | raw-history request split at client API boundary; initial and paginated history share the core path |
| History can contain interactive forms/choices | viewing an audit may submit or resume execution | render historical values and submit state; no execution callback/connection; callback guards reject readonly actions |
| Live events may contain complete snapshots or deltas | repeated text or overwritten partial content | preserve protocol-specific event semantics; test both variants before consolidating reducers; never guess based solely on prefix overlap |
| UI key may precede server message ID | final event creates duplicate rows or loses form state | reconcile server IDs onto the existing stable key within the session reducer |
| Client `readOnly` may be a token and `debug` is overloaded in platform | tokens leak into package or readonly is bypassed | host converts access to explicit capabilities; share token stays in host request callbacks |
| Platform stores are global; client active-session selectors hide other session state | two panels overwrite each other or late history updates a switched session | generation/session token guards in host adapters; state and callback lifecycle per panel/session |
| `useLocalize` is not referentially stable | hydration effects reset drafts on every render | translations are rendered copy; do not use translation callback identity as a hydration trigger |
| Client Markdown also imports daily/task artifact support | extracting it transitively migrates excluded modes or bundles task execution | package owns app-chat subset and injected artifact/file actions; no imports of daily/task entry points |
| Preview URLs can expire; sandboxed HTML must stay isolated | blank previews or unsafe HTML execution | inject host URL resolver/viewer; preserve existing sandbox builder; never enable same-origin or raw HTML as a shortcut |
| Backend test panels use unsaved configs and different handshakes | test runs execute the saved graph or duplicate initialization | keep handshake/config assembly in platform transport adapter and test exact outgoing payloads |

## 6. Public contracts and dependencies

### 6.1 Proposed outgoing package contract

- `AppChatConversation`: controlled `snapshot`, `mode` (`workflow`/`assistant`),
  `capabilities`, localized `labels`, `actions`, optional host resource services
  and header/action slots. No user/token/request-client prop.
- `ConversationSnapshot`: session identity, ordered `messages`, run status,
  pending interaction, history pagination state and visible error state.
- `ChatMessage`: discriminated user/answer/system/run/form/choice/file kind;
  stable `key`, optional `sourceMessageId`/parent/turn, content/reasoning,
  citations/files, final/streaming/submitted state. Raw source category is retained
  only where a protocol-specific form/result must be interpreted losslessly.
- `normalizeHistory`, `normalizeEvent`, `reduceConversation`: mode-specific pure
  functions shared by both hosts. UI-only keys are never sent as persisted IDs.
- `selectQaPair`: takes the chosen message and ordered normalized snapshot;
  returns the selected source message, input source identity and `{q,a}` content.
  Missing source identity disables identity-dependent answer writes with a
  localized explanation; it does not fabricate a persisted ID.
- QA actions carry an immutable operation context: `taskId`, `conversationId`,
  `sourceMessageId`, `actionId` and the host's `sessionGeneration`. Capture the
  target/content at action creation; the submit and completion paths must not
  re-read the current route/session to choose their target.
- On successful QA write, any automatic annotation-status write targets the
  captured origin task/conversation and awaits the existing API result. Server
  assignment/status checks still apply; conflicts are surfaced without a blind
  retry. The local status and modal may update only if the operation still
  matches the mounted active session generation and dialog operation. A result
  from A cannot change B or close/reset a newly opened dialog. Revisiting A
  reloads persisted status normally. Failed QA writes never invoke completion.
  The existing no-argument `onMarked` contracts in `AnnotationFormProps`,
  `SaveQaLibForm`, `AddSimilarQuestions` and `taskAppChats` must therefore become
  context-bearing for this integration, with their other callers audited.
- Independent capabilities: send/stop/continue/form-submit, feedback,
  annotation-question, save-answer-to-QA, copy/export/share, resource-preview and
  debug/run-details. An action requires both capability and a supplied handler.
- Host actions return promises where completion matters. Shared forms lock while
  pending, retain values on rejection, and do not advance annotation status.
  Platform QA dialogs retain their own validation and success notification.
- Resource services resolve file/citation details and open previews; optional
  artifact/TTS/export behavior is provided only by hosts that already support it.
  No ambient navigation, API calls or storage access in shared content components.
- Localization: shared copy uses a typed labels object assembled by each app;
  reusable keys live in `packages/locales` shared domain when appropriate. Keep
  host QA/task copy in platform. Avoid importing either app's translation hook.

The package adds no HTTP or Python API. Stable keys/callback semantics are the
new frontend contracts; changes must be reviewed against all consumer adapters.
No process-wide custom event bus for form/choice submission in the new path.

### 6.2 Incoming dependencies and risks

| Dependency | Use and compatibility risk |
|---|---|
| Existing workflow and assistant WS/history formats | event categories and status/identity fields need fixtures; backend changes can break normalization |
| Existing client v1/v2/v3, standalone/share and workflow auto-rerun guards | host must preserve exact handshake/auth/activation behavior; no automatic rerun in history mode |
| Existing platform test payload/version assembly | must keep unsaved graph and model/config inputs |
| Existing annotation/QA endpoints and permissions | writes remain platform-owned; IDs must be from the correct selected message |
| `@bisheng/ui`, icons and current client composition | no style redesign; unfinished primitives follow the current client implementation privately rather than inventing a new design system |
| Current Markdown/math/code/diagram dependencies | reuse installed compatible versions, lazy-load heavy diagram/code surfaces; client uses KaTeX while platform has MathJax, so migration validates formula fixtures |
| Current file/citation viewers, `@bisheng/file-viewers` where applicable | URL/auth/base path differs; injected resolvers must preserve resource permissions and sandboxing |
| Workspace source resolution and Tailwind scanning | both apps must scan chat source and consume explicit styles; no global selector/token resets |

`react`, `react-dom` and `@bisheng/ui` are peers. Add existing required rendering
libraries as package dependencies with workspace/catalog versions when supported;
do not rely on transitive node_modules resolution. Package-local lint forbids app
aliases and store/query/router/request imports. Both app quality scripts include
chat; core tests must run without mounting either application's providers.

## 7. Verification, delivery and observation

Use fixture-first tests for pure normalization/stream merging, identity and Q/A
pairing. Component tests exercise forms, readonly guards, pending/error behavior,
resource actions and two simultaneous sessions. Host integration tests assert exact
test/send/QA payloads and access gating. Explicitly test raw history input before any
host transformation and the absence of duplicate normalization. Use deferred
promises for QA A→switch B, A→B→A, reopening a dialog, failed QA writes and failed
annotation-status writes: verify origin IDs in network payloads and no stale UI
completion. Retain existing app-chat media/auto-rerun
and platform annotation regressions. Add daily/task smoke tests at their existing
boundaries without migrating production consumers.

Deliver vertical slices: shared core plus client workflow rendering; platform
workflow test/history; annotation QA; assistant client/test/history; final removal
of replaced workflow/assistant production renderers and parser branches. A slice
is not complete if client still uses its original renderer and platform alone
uses the package. Temporary coexistence during development is removed before
whole-feature acceptance; QA business dialogs and excluded daily/task code remain.

Verification commands (from `src/frontend`, heavy jobs serial): package/core and
host focused tests, `pnpm lint`, `pnpm typecheck`, `pnpm check-i18n`, and both app
production builds. Include `@bisheng/chat` in root lint/typecheck, and add a
package test command. Record pre-existing failures rather than adding suppressions.
No production code has changed at design review, so these implementation checks
have not yet run for F086.

Manual matrix: client `/workspace` application workflow/assistant chat, standalone
and read-only share; platform workflow/assistant test panel; annotation Q/A save,
status and previous/next; app-log detail. Use the existing configured dev proxies,
authorized test accounts and disposable conversations/QA entries. Confirm exact
routes from current router before publishing acceptance links; do not guess paths
or use destructive operations against shared real data.

Verify desktop/narrow widths and dark/light, streaming, history scroll, forms,
attachments/citations, two panels/switching sessions, failed QA writes, and no
socket/send operation in read-only views. Browser tests capture console errors
and network action counts, not screenshots alone. Record event category/status
and source IDs only for normalization failures; never log tokens or message/file
contents by default. Do not mask model failures with fabricated answers.

Acceptance trace: AC-01、AC-02、AC-03、AC-04 map to D1/D2 and the dual-host
vertical slices; AC-05 maps to D5 and unchanged daily/task smoke coverage;
AC-06、AC-07、AC-08、AC-09、AC-10 map to core/content/forms and protocol/resource
fixtures; AC-11、AC-12、AC-13、AC-14、AC-15 map to D3/D4, exact Q/A identities and
platform QA integration; AC-16、AC-17、AC-18 map to capability guards, session
isolation and host authorization; AC-19 maps to labels/shared locale integration;
AC-20 maps to both app builds, focused tests and the manual host matrix.

## 8. Deferred work and reconsideration triggers

Daily/task extraction is explicitly deferred. Their shared Markdown overlap may
persist until separately authorized, but no workflow/assistant-specific renderer
or parser fork remains after this feature. No task execution timeline is added.

Backend history gaps, missing permissions or incompatible QA contracts are not
solved by granting broad frontend permissions. Surface evidence and ask before
changing backend contracts or accepted scope. UI design gaps retain the current
client pattern and wait for design work if no equivalent exists.

Transport unification, a new state library, and navigation unification are not
needed to eliminate the selected duplication. Revisit only for an independently
approved requirement with evidence of remaining lifecycle duplication.

## Revision history

| Date | Change | Trigger |
|---|---|---|
| 2026-10-21 | Proposed design, not implemented | User confirmed F086 specification and requested continuation |
| 2026-10-21 | Specify raw history boundary and session-bound QA completion | Independent review found two medium contract gaps |

## 8. Implemented local contracts and pitfalls (2026-10-21)

The approved package is now `src/frontend/packages/chat`. Public contracts are
listed in its README; the two host folders bind API/resources and state. The
implementation remains pending full business acceptance; see verification.md.

| Contract / non-obvious behavior | Why it matters | Implementation |
|---|---|---|
| Raw history is normalized before host-compatible message conversion | Reinterpreting already converted rows can lose question text, form values and files | `core/historyForHost.ts`, `core/hostMessages.ts` |
| Compatibility rows carry `__bisheng_chat_snapshot`; outgoing history must use `messagesForTransport` | Runtime descriptors are not backend message fields; snapshots must not leak into requests or recursively grow | shared hostMessages; platform assistant TestChat payload |
| UI keys stay stable; canonical persisted IDs are strings, wire IDs retain original numeric values | Pending rows cannot be annotated or mistaken for stored IDs; backend payloads retain their existing shape | shared workflow/assistant core; Immer regression fixtures |
| Assistant `end_cover/tool/{}` with host cover flag is an error control frame without run identity | Treating it as a normal tool result adds an empty card and leaves the run spinning | `assistantStreamForHost`; error-frame fixture |
| Workflow tokens are deltas, explicit end/over is a snapshot | Prefix heuristics drop repeated tokens such as `ha` + `ha` | `applyWorkflowStream.ts` |
| Backend history can store `tool_call`, `tool_result` and pending input schemas | These private protocol rows must stay in the canonical history without becoming customer answer bubbles or QA candidates | normalizer hidden kind; renderer excludes hidden rows |
| Annotation A→B→A needs generations, not only matching conversation IDs | Old origin completion may write A but must not mutate the newly opened A UI | captured operation + session/dialog generation tests |
| Platform history fetch is a host service, not a Zustand action | Preserves C7 and allows independent panel disposal/invalidation | `appChat/historyAdapter.ts`, per-panel scope |
| Client completion divider payloads may be translation keys | Rendering the literal payload exposes `com_chat_round_finished` | client divider/separator content slot localizes payload |
| Citation popover keys use stable Markdown node offsets | A per-remount ID makes popovers close when active state rerenders Markdown | shared `CitationText` scope from HAST position |

### Revision history

- 2026-10-21: Approved design implemented locally; synchronized canonical/wire
  identities, snapshot stripping, platform panel isolation, terminal error frame,
  hidden history categories and citation state pitfalls. Independent review fixes
  and local evidence are recorded separately; no merge or live acceptance claimed.


## 9. Client Markdown parity follow-up (2026-10-21)

User confirmed client is the style authority and also owns Markdown components
and rendering parameters. Shared `ChatMarkdown` now imports client-derived prose
and syntax-highlight styles scoped to `.bs-mkdown.bisheng-chat-markdown`; platform
legacy `.bs-mkdown` rules remain for unrelated callers. No daily/task renderer or
legacy sheet changed. The CSS scope uses higher specificity so import order does
not change shared headings/tables/code.

`CLIENT_MARKDOWN_DEFAULTS` centralizes client plugin options (MathML,
single-dollar math, highlight detection/missing-language behavior), default LaTeX
preprocessing and media queries. Both hosts now use the shared reactive media
policy: `(max-width: 767px)` and `(hover: hover) and (pointer: fine)`. The existing
client LaTeX preference and host auth/capability/resource services remain ports.
Code bars restore client code layout/copy text and inline-code double-click.

Evidence: 37 shared tests including two new RED→GREEN parity tests; real Chrome
computed-style comparison under platform and client prose sheets, deliberately
loaded after the shared sheet. h1=24px, h3=18px, even table rows and code token
colors match; legacy sibling headings retain their host size. Formula output and
390px dark rendering pass. This adds local rendering evidence, not live QA writes
or completion of the unchecked business acceptance matrix.


## 10. Shared composer action ownership

Attachment, voice and send controls share one `items-center` toolbar. The host
file service supplies `onAttach` and retains upload state/validation/drop/paste;
it must not position another attachment trigger inside the composer. Client's
existing InputFiles supports hideTrigger/openPicker; platform ChatFiles retains
file management and exposes openPicker, with its replaced trigger removed.
Platform voice uses inline mode in shared conversations; its other modal caller
retains legacy placement. This corrects the host absolute-position regression
reported in the user's screenshots without changing upload/recording transport.


## 11. Opening messages and suggestions follow the client baseline

GreetingMessage retains the original client opening-message layout and pointer
hover policy. Host footer slots supply only authorized operations; they do not
choose the greeting action position. Form/choice action placement also belongs
to the shared renderer. Preview no longer substitutes a copy action for greeting
voice playback, and its voice glyph uses the client compact size.

SuggestedQuestions is the common client-style chip list in the message scroller.
Workflow stores own runtime questions and the actual input-lock capability;
assistant keeps its existing configured-question visibility contract. Host input
handlers receive panel-local resend events, keep their execution guards and own
transport. The former floating input question renderers are retired. This is a
presentation relocation, not a new suggestion-generation or send protocol.
