# Shared workflow and assistant conversations implementation plan

> For agentic workers: use superpowers:executing-plans to implement inline.
> Steps use checkbox syntax. Spec and confirmed design are the authority.

**Goal:** Both applications consume one client-based workflow/assistant chat
implementation, with platform QA/annotation actions and readonly history.
**Architecture:** Source-shipped `@bisheng/chat` with pure core and controlled
React components; host adapters retain auth/HTTP/connections/stores/business writes.
**Tech stack:** TypeScript, React 18, existing workspace UI/Markdown tooling;
existing app state libraries retained at host boundaries only.

## Document status

| Document | Status | Evidence |
|---|---|---|
| request/discovery | Confirmed | User chose workflow/assistant only |
| spec.md | Reviewed and confirmed | User “继续”, 2026-10-21 |
| design.md | Reviewed, amended and confirmed | Independent review, two resolved medium gaps; user “OK，在新分支开始开发” |
| tasks.md | Reviewed for interfaces and AC traceability | Inline plan below |

## Global constraints and preflight

- Base `bdc886930`; work on `codex/086-shared-app-chat`. No commits/push/merge
  unless requested. Preserve unrelated Config.tsx, FilterByUser.tsx and its test.
- Daily/task production source unchanged; mixed shared helpers retain their old
  contracts and are not pulled into package via application imports.
- No global conversation singleton, new frozen imports or new strict-ignore.
- Heavy checks serial; test workers limited to one.
- Interfaces: Task 1 raw history DTO is consumed before host transformations in
  Tasks 3/4, not after `getChatHistoryApi`; Task 5 QA context and late-result guard
  are shared with Tasks 2/4. No circular app→package→app dependency permitted.

## Task 1: shared core, raw history and identity

Covers AC-01、AC-06、AC-10、AC-13、AC-17、AC-18.
- [x] Add failing fixtures/tests for raw history roles/category/files/reasoning,
  IDs, multiple answers, interleaved form/run rows, stream reconciliation,
  malformed input, independent sessions and captured QA operation identity.
- [x] Create strict `packages/chat` core/types/normalizers/reducer/QAPair modules.
- [x] Run core tests RED→GREEN, strict package check and forbidden-import audit.
Expected: package pure functions consume raw backend rows, stable source identity,
no app providers required, no fabricated persisted IDs.

## Task 2: shared client-based conversation presentation

Covers AC-04、AC-06、AC-07、AC-08、AC-09、AC-15、AC-16、AC-19.
- [x] Write interaction tests for messages, forms/choices, operation capability
  gating, scroll/history, copy/citation/file actions and pending failures.
- [x] Extract controlled client-based message/content/composer/interaction
  components; inject resources/copy/feedback/export via host contracts.
- [x] Configure package exports/styles/locales and both apps' source scanning.
Expected: actual shared UI works without Recoil/router/query providers; readonly
renders historical values but cannot execute or connect.

## Task 3: client workflow and assistant integration

Covers AC-01、AC-02、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-17.
- [x] Test raw initial/paginated history and both modes' runtime snapshots.
- [x] Split raw request from current API display transforms; inventory legacy
  callers; retain version, guest/share, background and auto-rerun guards.
- [x] Route live and history interpretation through core; bind existing host
  state/requests to shared presentation and input callbacks.
- [x] Remove replaced client app-chat renderer/parser branches after consumers
  migrate; preserve unrelated shell, selection/export and daily/task contracts.
Expected: both modes genuinely consume package, not a source import back to client.

## Task 4: platform test and history integrations

Covers AC-01、AC-03、AC-06、AC-07、AC-08、AC-09、AC-10、AC-16、AC-17、AC-18.
- [ ] Add host tests for unsaved workflow/assistant test payloads, init/stop/clear,
  readonly network count and two-panel/switch-session isolation.
- [x] Implement per-panel host adapters and replace workflow/assistant test and
  app-log displays using shared core/UI; keep transport/API/auth at host boundary.
Expected: no singleton overwrite, live controls only in interactive test sessions,
no websocket connection or execution in historical viewing.

## Task 5: annotation and QA host actions

Covers AC-11、AC-12、AC-13、AC-14、AC-15、AC-17、AC-18.
- [x] Deferred-promise tests: QA on A→B and A→B→A, reopen dialog, failed QA/status
  writes; check exact source/target IDs and stale UI guards.
- [x] Shared action payload captures task/session/source message/action/generation.
- [x] Wire existing platform QA dialogs, validation, generation/editing,
  navigation/status and assignment restrictions; completion is context-bearing.
Expected: origin write targets A, never B; late A cannot change B status/modal.

## Task 6: retire forks and whole-feature verification

Covers AC-01、AC-05、AC-18、AC-19、AC-20.
- [x] Audit callers; delete replaced platform/client workflow/assistant renderers
  and parser branches, retain only genuine host adapters and out-of-scope users.
- [ ] Shared/core/host tests; daily/task smoke; package forbidden-import and copy
  audits; lint/types/i18n/both builds serial; browser host matrix from design §7.
- [x] Fresh independent whole-change review; one evidence-based fix pass.
- [x] Record failures/limitations and human whole-feature acceptance checklist.
Expected: one workflow/assistant renderer/interpretation source across apps, no
scope drift, no claims of checks that did not run.

## Implementation ledger

- 2026-10-21: Implementation and focused regression coverage delivered locally;
  whole-feature live acceptance remains pending (see e2e-checklist.md).
- Ruling: work in the explicitly requested existing new branch, retaining the
  shared working directory; no new worktree and no unrelated git writes.

## Actual deviations

- Branch prefix: `feat/3.0.0/086-shared-app-chat` conflicts with existing
  `feat/3.0.0`; used `codex/086-shared-app-chat`.


### Final local implementation checkpoint (2026-10-21)

- Shared core and presentation are consumed by both hosts. Raw initial/paginated
  history reaches shared interpretation before display transformations; live
  workflow and assistant frames use the same core. Replaced renderers are deleted.
- Platform messages/history services are panel-local, with generation guards and
  host EventTargets. History HTTP is outside Zustand state actions. Client state
  contracts remain Recoil/Immer-compatible without adding frozen imports.
- QA origin writes and modal/status updates are protected by captured operation,
  session generation and dialog generation, including A→B→A and rejected writes.
- Shared package 35 tests, platform 21 tests and client regression 94 tests pass.
  Browser component fixture passed desktop/narrow dark, read-only and interactive
  paths without API calls. Both application production builds have passed.
- Independent review returned two P2 findings, fixed in one correction pass.
  Source audit confirms daily/task production implementations are unchanged.
- Task 4's full host transport/payload and readonly-network matrix remains a live
  acceptance item, not claimed from pure shared-component fixtures. Task 6's
  all-green repository gate is blocked by existing lint/type errors in untouched
  files. See verification.md and e2e-checklist.md for exact evidence and limits.
- No commit, push, merge, deployment or real QA/status writes were performed.


### Client-first Markdown follow-up (user confirmed)

- [x] Add failing scope/code-bar/media-default fixtures, then bring to GREEN.
- [x] Own scoped client prose/highlight CSS and centralized rendering defaults
  in `@bisheng/chat`; remove divergent host media configuration.
- [x] Restore client code block/copy-label/inline selection behavior.
- [x] Verify real browser computed styles against both host stylesheets, late
  CSS loading, formulas, dark/narrow and untouched legacy sibling styling.
- [x] Shared 37 tests + package strict types/lint; two app build logs recorded.
- [ ] Real business/design acceptance remains the earlier unchecked checklist.

### Integration authorization (2026-10-22)

The user completed live flow testing, reported no major issues, and explicitly
requested merging into the latest feat/3.0.0 and deleting codex/086-shared-app-chat.
This supersedes the earlier no-commit/no-merge status notes. Individual stress,
permission variants and designer sign-off are not inferred from that smoke pass;
unchecked detailed checklist entries remain a coverage record, not an assertion
that those specific scenarios were individually executed.
