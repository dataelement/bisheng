# Knowledge module acceptance

Entry: http://localhost:3001/filelib (existing proxy: 120:3002).
Status: user functional testing found no issues (2026-10-19); design review pending.

## Scope

Finalized shared Tabs, Checkbox, Switch, Tooltip and status Tag compositions now
cover document/Q&A libraries, file lists, uploads, parsing previews, adjustment,
chunk editing, metadata and Q&A editing. Buttons, inputs and notices continue
through the accepted shared adapters. Matching business icons use bisheng-icons.
Oversized pages were split into library dialogs, Q&A editor, file status/filter
and paragraph metadata hook without changing API contracts or permissions.

## User acceptance checklist

- Libraries: switch document/Q&A tabs; search, create, edit, delete and select
  embedding models; check editable versus read-only permissions and tags.
- Files: single/multiple selection, status filtering (including parsing), reset,
  pagination/search, status/reason hints, retry, import/export and row actions.
- Upload: document, spreadsheet, mixed files and URL import; duplicate handling;
  split rules, table rules, preview selection and strategy tab synchronization;
  previous/next, parse results and cancellation.
- Adjustment/chunks: switch file/chunk views, preview original files, select,
  edit/delete chunks and manage metadata. Check draft preservation on save errors.
- Q&A: create/edit with multiple answers, import, search, select, delete and export.

## Explicit gaps retained

Shared Table, Select/Cascader, ordinary Dialog, DropdownMenu, Pagination,
Progress, upload/drop area, step indicator and rich/file editors are not finalized
shared replacements. Existing implementations remain. Generic permissions UI is
owned by the system module and is retained here. Existing confirmation service
also remains; the shared Confirm is not exported for this app.

Keep specialized file-type icons and unmatched Lucide icons: Shield, Crosshair,
Link2, FileCode, LocateFixed, SearchCheck and Hash. No substitute is invented.

## Verification

- 21 tests passed across 8 files: library lazy actions, duplicate handling,
  spreadsheet localization, metadata requests/save/permissions/error drafts,
  file parse failures, parsing filter apply, preview document/table switching.
- Knowledge ESLint passed with generated shrink-only suppression pruning.
- Full frontend typecheck passed (platform/client/file-viewers). Platform production
  build passed in 33.51s with existing chunk-size warnings. Full frontend lint is
  blocked by 95 existing errors and one warning outside KnowledgePage (API typing,
  builder, license tests and generic components); no such files were modified.
- Independent review findings (missing parsing filter and broken preview/strategy
  tab linkage) fixed and reviewed again without further findings.
- Isolated Chromium checks passed with mocked APIs: tab switching, parsing filter
  apply, Chinese labels and light/dark tooltip contrast. No page JavaScript errors.
  Temporary fixture files removed and browser closed.
- Real uploads, parse jobs, destructive actions and permission writes against
  shared test data are left for user acceptance.
