# F086 verification

Local date: 2026-10-21. Branch: `codex/086-shared-app-chat`.
No commits/push/merge/deployment. Heavy checks ran serially; test workers = 1.

| Check | Outcome | Evidence |
|---|---|---|
| Shared `vitest run` | PASS: 35 tests, 8 files | `/tmp/f086-shared-tests.log` |
| Shared `tsc --noEmit` / ESLint | PASS | `/tmp/f086-shared-types.log`, `/tmp/f086-shared-lint.log` |
| Platform annotation forms/page, panel isolation/history and assistant closing | PASS: 21 tests, 4 files | `/tmp/f086-host-tests.log` |
| Client state/media/workflow activation/share token/task artifacts | PASS: 94 tests, 5 suites | `/tmp/f086-client-regression.log` |
| Chrome shared-component fixture | PASS: send/form/choice each once, source-code copy; readonly guards; 390px body width; no page errors or API requests | `/tmp/f086-browser-final.log` |
| Platform typecheck | PASS: 723 strict files | platform segment of `/tmp/f086-root-types.log` |
| Client final typecheck | BLOCKED: 4 errors, all in unchanged skill-center files | `/tmp/f086-client-types-final.log` |
| Root `pnpm lint` | BLOCKED: 83 platform errors in untouched files | `/tmp/f086-root-lint-final.log` |
| Client lint | BLOCKED: 89 errors + 1 warning in untouched files | `/tmp/f086-client-lint-final.log` |
| Changed-file ESLint audit | PASS: no diagnostics in changed/new files across those logs; shared package separately clean | comparison of log paths against git changed/untracked paths |
| Suppression ledger | PASS: generated with each app's `lint:prune`; all counts shrink or stay equal, no added suppression | comparison against HEAD |
| `locales` generation check / `check-i18n` | PASS: no new drift, zh-Hans/en/ja shared keys | `/tmp/f086-i18n.log` |
| Frozen offline lockfile check | PASS, existing versions only, isolated modules-dir; no reinstall/purge of app modules | `/tmp/f086-lock-verify.log` |
| Architecture guard on changed TS/TSX | PASS, no warnings/violations | `/tmp/f086-arch.log` |
| Platform production build | PASS | `/tmp/f086-platform-build.log` |
| Client production build | PASS; final rerun after restoring user timestamp recorded below | `/tmp/f086-client-build.log`, `/tmp/f086-client-build-final.log` |
| Scope/import/line-count/diff audit | PASS: no daily/task production source diff, no package app/store/router/HTTP imports, new TS/TSX under 600 lines, no whitespace errors | git diff / package search / line count |

## Existing gate failures

Client typecheck: `src/api/skillCenter.ts` lines 137/151/159 and
`src/components/Skills/useSkillCenter.ts` line 12 (request config/generic/hook
signature). The earlier run had the same four pre-existing errors; one F086 file
icon type issue was fixed and the final result returns to those four only.

Platform lint: `selectComponent/useSubjectSearch.ts`, `controllers/API/index.ts`,
`controllers/API/license.ts`, `test/f067LicenseBannerCopy.test.ts`.
Client lint: `api/chatApi.ts`, legacy `CitationReferencesDrawer.tsx`, Skills test
files, permission tree/keyword helpers and `SkillCenterPage.test.tsx`.
`git diff --name-only` confirms these error files were not changed by F086.
These were not hidden with new suppressions or expanded into unrelated repairs.

## Test harness notes

Client node-only regression tests used the existing Jest/Babel configuration plus
a temporary config that removes browser-only global setup and supplies
`__APP_ENV__.BASE_URL`. The first artifact smoke attempt failed on that missing
test global; with it supplied all 94 tests pass. No production source was changed
to accommodate this test-harness issue.

Browser checks used an isolated temporary Vite fixture and real headless Chrome
with all API requests blocked. The initial attempt hit the platform HTML-plugin
login entry, so it was replaced with an isolated config; the final run passed.
Temporary fixtures/configs and local Vite processes were removed/stopped.
Screenshots were visually inspected in desktop light and narrow dark layouts.
This does not claim end-to-end host transport, real QA writes or live version/
guest/tenant permission coverage. Those remain in `e2e-checklist.md`.

Review and correction evidence: `code-review.md`; meaningful error-frame RED
fixture: `/tmp/f086-review-red.log`, followed by GREEN in the shared test log.

Overall acceptance status: **PARTIAL** — implementation and focused local checks
are ready; full-repo gates have existing failures, and live business/design
acceptance is pending. See the unchecked module-based checklist.


## Client Markdown parity follow-up

- User authorized client-first Markdown implementation, styles and parameters.
- `/tmp/f086-markdown-parity-red.log`: two new fixtures fail before the change.
- `/tmp/f086-markdown-parity-tests.log`: 37 tests / 8 files pass after the change.
- `/tmp/f086-markdown-parity-types.log` and `...-lint.log`: empty, successful.
- `/tmp/f086-markdown-browser.log`: computed headings/margins/table zebra/code
  token styles match under both host sheets; math renders; legacy sibling keeps
  platform's original 16px h3 while shared h3 is 18px; no page errors, 390px body.
- Browser screenshots inspected in light desktop and dark narrow layouts.
- Production build logs: `/tmp/f086-markdown-platform-build.log` and
  `/tmp/f086-markdown-client-build.log` (results checked before delivery).
- Temporary fixture/config removed; Vite stopped. Scope is workflow/assistant;
  original daily/task Markdown and CSS remain unchanged.


## Platform composer alignment correction

User screenshots exposed host controls still carrying absolute positioning inside
the shared toolbar. Attachment selection now belongs to `ConversationComposer`
(`onAttach` port); client uses its existing hidden-trigger/openPicker contract,
and platform ChatFiles exposes the same operation without its old trigger UI.
Platform voice has an inline client-style button in both shared composers while
its existing modal placement remains unchanged.

- Shared regression test was RED before the new attachment action port;
  `/tmp/f086-toolbar-red.log`. After fixing, shared suite: 38 tests PASS;
  package strict types/lint PASS (`/tmp/f086-toolbar-{tests,types,lint}.log`).
- Actual platform voice/file-manager integration: two tests PASS
  (`/tmp/f086-platform-toolbar-tests.log`), covering inline toolbar ownership,
  actual file-picker delegation and preserved legacy modal positioning.
- Real Chrome host-widget fixture: attachment/voice/send each 32×32, aligned on
  the same center line with 8px gaps at 800px and 390px; file chooser opens;
  no page errors. `/tmp/f086-toolbar-browser.log`; screenshots inspected.
- New attach label ships zh-Hans/en/ja via generated shared locales;
  check-i18n and generated-artifact checks PASS.
- User's existing Vite servers remain running against 120:3002. Temporary
  validation fixture/config removed and its separate server stopped.

- Final platform typecheck: PASS, 726 strict files (`/tmp/f086-toolbar-platform-types.log`). Public file-picker ref/props are now typed; host integration tests rerun and both pass after removing the replaced trigger.


## Client opening actions and preview suggestions follow-up (2026-10-22)

Compared current code with the client MessageRemark/MessageBsChoose baseline in
HEAD. The generic bubble footer had replaced right-aligned hover actions and the
preview still owned a second, absolutely positioned suggestion widget.

- Shared GreetingMessage restores client padding/title/avatar layout and a right
  aligned footer, hidden on fine-pointer idle and visible on hover; touch remains
  visible. Form/choice footers restore right aligned hover actions and the client
  selected check appearance. Preview greeting uses its authorized TTS action,
  not a copy button; compact platform voice uses the client's 14px glyph.
- Shared SuggestedQuestions replaces all three old question renderers. Preview
  workflow questions and input lock stay panel-local; assistant uses its existing
  question visibility state. Suggestions sit in the message scroller and invoke
  the existing panel-local, lock-guarded resend event. Sending/clearing removes
  workflow suggestions. The input's floating recommendation widget is removed.
- Preview-only dotted backgrounds are removed to follow the current client.
- Shared: 40 tests pass, package strict types/lint pass. The greeting layout RED
  fixture is `/tmp/f086-message-layout-red.log`; GREEN logs use `...-tests.log`.
- Host: 7 panel/toolbar/suggestion tests pass. Platform typecheck: 729 strict files
  pass (`/tmp/f086-message-platform-types.log`). Changed-file lint audit has no
  diagnostics; existing unrelated full-repo lint failures remain.
- Chrome with the actual platform audio control: idle opacity=0, hover=1, touch=1,
  icon size=14, right aligned, recommended question click works within message
  flow, no page errors. `/tmp/f086-message-browser.log`; screenshot inspected.
- Temporary browser fixture/config removed and its separate Vite stopped;
  normal local Vite servers remain running for user acceptance.

- Final client typecheck returns only the same four existing skill-center errors; no F086 diagnostics (`/tmp/f086-message-client-types.log`).


## Output option editing regression (2026-10-22)

User reported that an output-node choice label could not keep editing. Its editor
bound `value` to the saved label with no input-change handler, so the shared Input
restored the old text on each edit. The existing blur/Enter commit flow now uses
an uncontrolled draft (`defaultValue`); Enter used to confirm an IME composition
does not finish editing. No global Input behavior or option IDs changed.

Three meaningful fixtures fail before the fix and pass after it: continuous
editing + blur commit with stable ID, Enter commit, composing Enter stays editable.
`/tmp/f086-option-edit-red.log` and `/tmp/f086-option-edit-tests.log`.
Targeted ESLint passes (`/tmp/f086-option-edit-lint.log`); local Vite hot updates
this existing editor. Real user workflow acceptance remains with the running UI.

## Workflow form presentation parity (2026-10-22)

Platform now uses the same MessageFrame around the active workflow form as the
client, including the application logo/name and body indentation. Its transcript
padding follows the client. WorkflowForm no longer uses the platform-only
`bisheng-label` class; scoped shared CSS pins label typography. Both workflow
upload adapters render WorkflowFileField from @bisheng/chat, with the file icon
inside the same clickable field and a normal-weight filename. Hosts retain
upload services, limits, file paths and display-name callbacks. Other callers of
the existing upload adapters retain their presentation.

The attempted select extraction was withdrawn at the user's request after a
client dropdown regression was reported. Single/multi-select imports, renderers,
and dependencies remain as before this follow-up; select parity is deferred.
No new select implementation or dependency remains in the shared package.

- Shared package: 44 tests across 10 files pass; TypeScript and ESLint pass.
  Logs: /tmp/f086-form-final-tests.log, /tmp/f086-form-final-types.log,
  /tmp/f086-form-final-lint.log. Added coverage checks host-label isolation,
  file-path/display-name submission, icon placement and disabled/loading guards.
- Chrome: actual platform InputForm plus shared client presentation fixture have
  matching computed label/file/text styles and widths. Existing single-select
  works, mocked upload yields report.pdf and submits its storage path, no page
  errors, no overflow at 390px. No real upload/chat request was sent.
  /tmp/f086-form-browser-final.log; screenshot f086-form-parity.png inspected.
- Platform strict typecheck and changed-file ESLint pass. Client typecheck still
  reports the same four pre-existing skill-center errors; changed-file lint is
  clean. Logs: /tmp/f086-form-platform-final-types.log,
  /tmp/f086-form-platform-final-lint.log, /tmp/f086-form-client-types.log,
  /tmp/f086-form-client-lint.log.

## Merge latest release line (2026-10-22)

User requested merging the newest release line into this feature branch. Saved
all F086 work in local checkpoint 5e93dfff2 and a pre-merge recovery archive at
/tmp/f086-premerge-files.tar.gz, then merged origin/feat/3.0.0 at 58996f12b.
Three textual conflicts: release-contract.md keeps both F086 and F087 history
entries; both InputForm adapters retain shared chat layout/upload/submission and
adopt the upstream @bisheng/ui Select plus the upstream localized copy hooks.
No old message renderers or deleted legacy select wrappers were restored. The
upstream InputFormSkill and voice callback changes also survived the auto-merge.

- Both production builds pass: /tmp/f086-merge-build.log.
- 44 shared-chat tests, 27 host regression tests and one new merge regression
  covering real shared Select single/multiple submission pass (72 total).
  /tmp/f086-merge-chat-tests.log, /tmp/f086-merge-platform-tests.log,
  /tmp/f086-merge-select-tests.log.
- @bisheng/chat and @bisheng/ui typechecks/lint pass; resolved form files and the
  new regression test pass targeted lint.
- Browser: actual platform InputForm uses the upstream 32px Select, gray focus
  border and 2px gray shadow; popup stays below the trigger, single/multiple work,
  no errors or 390px overflow. All API traffic blocked. Screenshot
  f086-merge-select.png inspected; /tmp/f086-merge-browser.log.
- Full workspace gates remain blocked by upstream/previous issues: platform lint
  85 errors; client lint 101 errors + 1 warning; platform typecheck one error in
  clientVoiceDraft.test.tsx (47), client five skill-center errors. The affected
  source/test files match origin/feat/3.0.0; no merge-conflict form diagnostics.
  /tmp/f086-merge-lint.log, /tmp/f086-merge-types.log,
  /tmp/f086-merge-client-lint.log, /tmp/f086-merge-client-types.log.
- The new shared-UI Popover/Slider dependencies are already present in the local
  workspace store; only their package-local links were added. No full dependency
  installation or canvas relinking was performed.
