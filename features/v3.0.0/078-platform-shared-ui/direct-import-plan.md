# Direct shared UI imports — 2026-10-20

User explicitly supersedes the compatibility-path requirement: all platform
button/input/notice primitives must import @bisheng/ui directly. Shared styles
and APIs remain unchanged. Input limits follow the shared soft-limit design;
business submission validation remains required. Existing unrelated changes
and the Vite process are preserved. No commit or push.

1. Capture current import/call inventory and save only touched sources to /tmp.
   Move actual business compositions (numeric stepper, labeled secret/numeric
   fields, editable list) into bs-comp; their primitives import shared UI.
2. Replace primitive imports and LoadButton alias; normalize black variant;
   preserve loading submission blocking at callers. No wrapper/re-export alias.
3. Move Input/Textarea shell/content classes to correct shared props; use
   shared search/password affordances with localized labels. Trace maxLength
   and numeric business handlers and enforce invalid submissions at source.
4. Convert each legacy notice call directly to notification.open or toast.show;
   flatten multi-line descriptions explicitly; remove useToast and mount the
   shared Toaster/Notifier once with localized labels. Preserve API interceptor
   errors and shared de-duplication. No production normalization bridge.
5. Remove old entry files, update docs/tests/mocks, verify zero production old
   imports/hooks. Run interaction regressions, scoped lint, frontend typecheck,
   i18n parity and production build serially. Record unrelated failures.
6. One fresh read-only final review of the migration; fix material findings and
   provide a page-oriented acceptance list.

Progress: inventory complete (339 consuming files;387 notification calls).
Baseline: shared-ui/menus/grants49 tests green from previous cleanup. Two
knowledgeSpaceGrantSubjects assertions already disagree with current permission
code; preserve that unrelated work and report separately.

## Delivered

- Removed platform primitive entry points: bs-ui/button/index,
  bs-ui/input/index, bs-ui/toast/index and toast/use-toast. Primitive callsites,
  including HTTP interceptors, import @bisheng/ui directly. Production
  useToast/LoadButton calls are gone; literal button variants/sizes use the
  canonical shared axes. InputGroup/action/upload/title-edit compositions are
  business controls, not compatibility entry points, and use shared primitives.
- Moved real business controls into bs-comp/formFields: NumberStepper,
  InputList, PassInput and NonNegativeInput. They keep validation/labels/list
  identifiers/decimal stepping, with no primitive re-export layer.
- Numeric validation is a pure business utility, not an input wrapper. Moved
  old numeric bounds to affected callsites, including dynamic node types;
  retained pre-existing shared quota fields' editable invalid drafts.
- Length limits use shared soft-limit feedback. Added submit/confirm guards
  where old native caps had been the only protection, including workbench,
  model descriptions, reports, metadata filters, roles, brand names, accounts,
  tenant edits and chart names. Existing business validators stay in place.
- Notices directly use notification.open or toast.show, flattening arrays with
  newlines. The app mounts one Toaster and one Notifier with translated labels.
  No live production action/duration/update-handle consumer required a bridge.
- Updated platform AGENTS.md, feature spec and plan to supersede retaining
  adapters. No backend, dependency, or shared UI implementation changes in this
  follow-up. Existing unrelated working-tree changes preserved; no commit/push.

## Verification

- 181 tests passed in36 files, one worker; covers direct-import boundary,
  shared queues, fields/compositions, dynamic numeric bounds, auth, grants,
  workbench, evaluation, tenants, system/desktop and common selectors.
- Import-boundary test was observed RED before conversion, GREEN afterwards.
  Dynamic InputItem upper/lower-bound test was RED before its business guard,
  GREEN after; pure numeric bounds tests cover empty drafts and fractions.
- Whole frontend typecheck passed: platform671 strict files, client1368,
  file-viewer tsc. i18n check passed with no new drift.
- Scoped ESLint retains one existing DepartmentUsersSelect effect-dependency
  error; zero additional errors. No suppressions added. git diff --check clean.
- Existing knowledgeSpaceGrantSubjects assertion drift (two mismatches in the
  prior cleanup record) remains outside this migration's acceptance suite.
- Isolated Chrome:1001-character workbench input visibly flags1000 limit and
  cannot POST; valid correction saves; dynamic numeric max rejects6 and accepts5;
  password reveal preserves value; shared Toast and Notification display
  together without page errors. All API calls intercepted, no120 writes.
  Fixture files removed and browser closed. Vite started on port3001 with the
  authorized120:3002 proxy because no server was listening when checked.
- Independent read-only review found missing business bounds caused by removing
  native caps. These were addressed in the callers, including the final dynamic
  node max, workbench maxTokens, and raw chart-name length checks. No additional
  important notice, ref or rendering regression identified.


Final production build passed in59.88s (existing Ace/eval/chunk warnings only).
