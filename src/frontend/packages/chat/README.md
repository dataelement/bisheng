# @bisheng/chat

Source-shipped workflow and assistant conversations, extracted from the client.
Daily chat and task/Linsight retain their existing implementations.

## Boundaries

`@bisheng/chat/core` consumes raw API history before host transformations and
interprets workflow/assistant frames. It owns message identity, category/role,
reasoning/files, final reconciliation, QA matching and captured operation context.
It is independent of React, application stores, routing and network clients.

`@bisheng/chat` exports controlled messages, Markdown/citations/diagrams,
attachments, choice/input forms, composer and scroll policy. It requires neither
Recoil nor Zustand nor a query/router provider. The presentation follows the
client baseline; Tailwind must scan `packages/chat/src/**/*.{ts,tsx}` and load the
shared UI tokens. The renderer imports the scoped client Markdown/highlight
styles itself; host legacy Markdown sheets cannot redefine this conversation
scope. `@bisheng/chat/styles.css` is also an explicit CSS entry.

Composer action positioning belongs to the shared toolbar: pass `onAttach` and
an inline voice control. The attachments slot owns selected-file content, not
an absolutely positioned attachment button.

Hosts own auth/tenancy/share/version selection, HTTP, WebSocket lifecycle,
upload/download/preview permissions, code execution, voice and business writes.
Capabilities are explicit (`canExecute`, host annotation flags). Read-only
consumers do not mount the live host input/transport. Citation loaders and
resource previews must use the host's existing authorized services.

## Host integration

- Initial and paginated raw rows enter `historyForHost` once. Compatibility
  host rows retain a canonical snapshot for `messagesForPresentation`.
- Workflow deltas/final snapshots use `workflowStreamForHost`; assistant
  start/delta/final-cover frames use `startAssistantForHost` and
  `assistantStreamForHost`. UI keys survive assignment of a persisted ID.
- `messagesForTransport` removes runtime snapshots/UI metadata before a host
  sends conversation history. Source IDs are never manufactured by the core.
- Platform creates a store and history service per mounted panel. The service
  owns API pagination; state actions are synchronous. Disposal invalidates late
  history responses. Host form/choice events use that panel's EventTarget.
- QA actions capture task, session, source message, action and session generation.
  Successful writes target the captured origin. Current UI updates additionally
  require the same generation; dialog reopening also gets its own generation.

## Markdown defaults

`CLIENT_MARKDOWN_DEFAULTS` is the rendering baseline: client remark/rehype
plugins, MathML output, single-dollar math, highlight auto-detection/known-language
subset, LaTeX preprocessing enabled, mobile width < 768px and fine-pointer hover.
Media queries update on resize. Client's existing LaTeX preference may override
that default; host auth/resource/code-execution capabilities remain separate.

Typography, lists, tables/zebra rows, inline code and code syntax colors derive
from the current client CSS and are scoped to `.bs-mkdown.bisheng-chat-markdown`.
The host's legacy CSS remains for daily/task and unrelated pages. Code bars keep
the client's copy label, three-second copied state and inline-code double click.

## Provenance and exclusions

Message layouts, choice/form behavior, Markdown pipeline, citation previews,
image preview, code/diagram controls and scroll policy derive from the client
app-chat implementation. Host adapters retain file viewers, authenticated API
functions, execution controls and business dialogs. Legacy Markdown remains only
for unrelated daily/task/legacy callers, not as the workflow/assistant renderer.
No design-system primitives or new state-management libraries are introduced.

## Checks

From `src/frontend`: `pnpm --filter @bisheng/chat test`,
`pnpm --filter @bisheng/chat typecheck`, `pnpm --filter @bisheng/chat lint`.
Tests use one worker. Full integration evidence and manual acceptance are in
`features/v3.0.0/086-shared-app-chat/e2e-checklist.md`.
