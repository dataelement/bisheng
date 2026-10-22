# F086 acceptance and regression coverage

Branch: `codex/086-shared-app-chat`. No backend endpoints or schemas changed.
All verification below ran locally with one test worker. Browser fixtures block
API requests; no real QA/status writes were made against 120.

## AC classification

- UI/interaction contracts: AC-02、AC-03、AC-04、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-14、AC-15、AC-16、AC-19; focused automated fixtures plus the module-based live checklist below.
- Internal extraction/state contracts: AC-01、AC-05、AC-06、AC-13、AC-17、AC-20; pure/core/host regression tests, source-scope audit and builds.
- Existing authorization contract: AC-18; no backend/API behavior changed. Local denied-citation/capability fixtures cover the frontend portion; non-admin/tenant live verification remains pending.

## Automated evidence

| Coverage | Result | ACs |
|---|---|---|
| Shared package: raw history, roles, hidden protocol rows, reasoning, files, exact QA pairing/identity, workflow and assistant delta/final/error reconciliation | 37 tests passed across core and interaction suites | AC-01、AC-06、AC-07、AC-08、AC-09、AC-10、AC-13、AC-16、AC-17 |
| Controlled choice/form/composer: read-only and keyboard guards, pending lock, failed-submit retry, IME, stop; history prepend and underfilled viewport | Included in the 37 tests | AC-07、AC-08、AC-16 |
| Markdown: safe text/table/line breaks, source-code copy, forbidden citation does not request private detail/preview; attachments preserve media metadata and recover authorized image URL | Included in the 37 tests | AC-04、AC-09、AC-18 |
| Platform QA dialogs, captured source IDs, failed writes/status, late completion A→B and A→B→A, independent stores/history generations, run close behavior | 21 tests passed | AC-11、AC-12、AC-13、AC-14、AC-17、AC-18 |
| Client state under Immer, transport metadata removal, workflow media, workflow activation/restart, share-token contracts and task artifact utilities | 94 tests passed, 5 suites | AC-02、AC-05、AC-06、AC-09、AC-10、AC-17、AC-18 |
| Real Chrome component fixture: read-only input/form, code copy, one send/form/choice, light desktop and dark 390px | Passed; no page errors/API calls; body width 390px | AC-04、AC-07、AC-15、AC-16 |
| Independent review | Two P2 regressions identified and fixed: assistant error terminal frame; client separator translation | AC-10、AC-19 |

This is frontend regression coverage, not a claim of full end-to-end service
acceptance. Existing API contracts are unchanged, so no backend pytest cases
were added. Server-side permission/tenancy behavior still needs the existing
service test environment; button visibility is not treated as authorization.

## Business acceptance — pending human/live-environment execution

Use a test account and disposable conversations/QA library. Check one whole
business journey at a time. The following items are intentionally **unchecked**:

### Client workflow

- [ ] Open an existing workflow, load older history; check order, reasoning,
  attachments, references and separate outputs from the same node.
- [ ] Run text, choice and upload forms; required values validate, each choice
  sends once, execution continues in the selected conversation. Refresh to
  verify historical submitted values.
- [ ] Stop/restart, reconnect, switch during output, return to the running chat;
  verify drafts/output stay with their origin and older-history reading stays put.
- [ ] Open an authorized readonly share: copy/preview/download work; historical
  forms/choices/code cannot execute and mounting creates no generation socket.

### Client assistant

- [ ] Send with attachments; check streaming reasoning/tools/answer, final output
  is unique, feedback/export/voice and code permissions follow the account.
- [ ] Test v1/v2/v3, guest and shared access where enabled; citation denied/expired
  states show the applicable message and no misleading empty success preview.
- [ ] Cause a retryable model/tool failure; pending indicators finish and retry
  remains possible. Verify switching chats does not move output or draft text.

### Platform test panels

- [ ] Workflow editor: change unsaved node parameters, test without saving,
  complete a form/choice, stop/restart/clear; results use the unsaved definition.
- [ ] Assistant editor: change unsaved model/tools/prompt, test without saving,
  stop/clear/retry; results use the edited definition and retained history.
- [ ] Open independent panels/views; loading/clearing/viewing logs in one does
  not overwrite another panel's messages or the assistant editor configuration.

### Annotation and logs

- [ ] On a question, add it to existing QA entries as a similar question; on a
  chosen answer, create QA with the correct question and that exact answer.
- [ ] Edit/generate similar questions, select libraries, test required validation
  and save errors; only successful saves mark the origin conversation complete.
- [ ] Navigate A→B and A→B→A while generation/save is pending; old completion
  neither closes a new dialog nor changes the current conversation's status.
- [ ] Verify assignment restrictions, all three statuses and previous/next.
  Open workflow/assistant audit logs: copy/preview allowed, no QA write controls,
  no send/stop/execute controls and no generation connection.

### Markdown visual follow-up

- [ ] In both hosts, check heading hierarchy, lists, table zebra rows, links,
  inline code, highlighted code/copy labels and formulas against client baseline.
- [ ] Check citation hover on mouse, tap on touch, resize across 767/768px and the
  existing client LaTeX preference; readonly still cannot execute code.

### Daily/task and design follow-up

- [ ] Daily chat: send/history, code/artifacts and readonly share smoke.
- [ ] Task mode: run/history, deliverable preview/download and share smoke.
- [ ] Designer reviews both modes in light/dark/narrow layouts in each host;
  this extraction retains the client baseline and does not redefine UI specs.

## Quality gates and limits

Final command results are recorded in `verification.md`. Full-repo gates must
be distinguished from changed-file/package gates: unrelated existing skill-center
errors can block the root command even while shared code checks pass.
