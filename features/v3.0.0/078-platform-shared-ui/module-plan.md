# Platform component migration by business module

User-approved cadence (2026-10-19): finish one whole module for user acceptance. Since 2026-10-19, develop the
next module while the user tests the previous one; acceptance fixes take priority. Do not pause for acceptance after individual pages.
Use finalized shared components, preserve explicit library gaps, and replace
business-owned icons with bisheng-icons equivalents; keep an old icon only when
no suitable equivalent exists. As updated on2026-10-20, buttons/inputs/notices import @bisheng/ui directly;
the temporary compatibility entry points have been removed. Business-specific
field compositions remain under bs-comp/formFields.

| Order | Module | Scope | Status |
| --- | --- | --- | --- |
| 1 | Model management | Provider list/editor, system model settings, fine-tuning and its dialogs, API-document viewer | User accepted 2026-10-19 |
| 2 | Knowledge | Libraries, files, upload/parse, adjustments, Q&A | Functional testing: no issues found; design review pending |
| 3 | Application building | Apps, templates, assistant editor, tools | Ready for module acceptance |
| 4 | Workflow | Canvas, node settings, debug and results | User testing |
| 5 | Evaluation | Evaluations, creation/results, datasets | User testing |
| 6 | Annotation | Tasks, task apps, conversation annotation | User testing |
| 7 | Logs | App/system logs and conversation details | User testing |
| 8 | Dashboard | List, editor, shared viewer | User testing |
| 9 | System administration | Organization/members, users/groups, roles, sync, API accounts/tokens, config/theme | User testing |
| 10 | Approval | Approval tabs and flow configuration | Ready for module acceptance |
| 11 | Tenants | List, creation, editing and management | User testing |
| 12 | Desktop administration | License/seats, quotas, usage, access, plugins | User testing |
| 13 | Other entries | Workbench configuration, reports/resources, auth/tenant selection, permissions/errors, navigation/profile | Ready for module acceptance |


## Explicit retained implementations

The library has no finalized Table, Select/Cascader/Combobox, ordinary Dialog,
DropdownMenu, Pagination, Progress or Card replacement. Keep these and their
internal controls/icons, plus the existing confirmation service (the finalized
Confirm is client-context-bound, not exported by @bisheng/ui). Keep the chart's
own Recharts tooltip. They are gaps, not completed shared-library migrations.
Desktop administration components under ModelPage/manage/dsh belong to module 12;
their shared model-selection dependencies receive regression checks here.

Native input length/numeric validation and app request feedback continue through
the accepted adapters. No backend endpoints or shared component styles change.

## Module 1 verification (2026-10-19)

- 138 tests passed: model-directory regressions (including shared selectors used
  by desktop management), model permissions/name validation, parameter draft
  save/cancel/JSON rejection, system-tab callbacks and child-admin request gating,
  fine-tuning status selection stability.
- Model-directory ESLint passed with shrink-only suppression pruning. Platform
  strict typecheck passed. Final production build passed (35.88s); existing bundle-size
  warning remains.
- Independent read-only review found no newly introduced actionable issue.
  Existing list-polling races and nested prompt-dialog trigger buttons remain
  pre-existing limitations, outside this component migration.
- Isolated Chromium checks with mocked APIs passed: fine-tuning filter stability,
  invalid/valid JSON in the model-parameter dialog, web-search draft toggle,
  connection-field rendering, real Chinese copy and 768px filter layout; no page
  JavaScript errors. Light/dark screenshots were captured for review.
  Temporary fixture sources removed and browser closed.
- Real model calls, credentials, training, publish/stop/delete operations were
  not exercised against shared 120 data during automated checks; user acceptance
  subsequently completed on 2026-10-19.
- Dev entry remains http://localhost:3001/model/management and uses the existing
  120:3002 proxy. Fine-tuning route: /model/finetune; API PDF route: /model/doc.

### Acceptance fixes: return tooltip

- Use the bs namespace for the common return label in system settings.
- Remove platform's legacy variable override for Tailwind white: configurable
  theme values are HSL channels, whereas shared white text must remain literal.
- Shared cn now supports both tailwind-merge v1 and v2 config shapes. Platform's
  Vite prebundle resolves the shared source import to its v2 copy; without that
  compatibility, text-body deletes text-white before CSS can apply it.
- Verified semantic-size/color merging in unit tests, shared strict types, and
  actual browser white-text contrast under light/dark themes with HSL --white.

Module 1 acceptance: user confirmed on 2026-10-19 after status tags, return
tooltip, field alignment and settings-button refinements. Module 2 starts next.
