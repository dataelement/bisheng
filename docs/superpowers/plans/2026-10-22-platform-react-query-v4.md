# Platform React Query v4 maintenance plan

User approved migrating platform from react-query 3.39.3 to the client's resolved
@tanstack/react-query 4.44.0. Native implementation in this session. Work branch:
`codex/platform-react-query-v4`, based on latest origin/feat/3.0.0. No automatic
release synchronization or deployment.

1. Pin the shared query dependency at 4.44.0 in the workspace catalog; use it in
   both applications, remove platform's v3 dependency and update the lockfile.
   Reuse installed workspace dependencies; avoid reinstalling client/canvas.
2. Migrate all production imports, test providers/mocks and string query keys
   (including their cache removal callers). Preserve existing cache lifetimes,
   refresh flags and mutation behavior. Keep v3 request behavior while offline.
3. Cover disabled/manual chart loading, model-list cache key separation,
   publish cache updates, department-tree caching and swallowed config errors.
   Query success must never cache undefined; preserve existing notices/defaults.
4. Run targeted tests serially with one worker, changed-file lint, platform
   strict types against its existing baseline, both app builds and production
   startup smoke. Review the diff and record a business acceptance checklist.
5. Update app/root architecture instructions to describe the unified version;
   retain lint's ban on legacy react-query imports to prevent reintroduction.
   Leave the result on the development branch for acceptance.

Review focus: disabled queries must not stay on a spinner; offline intranet
requests must still execute; label/workflow/model keys and invalidations must
agree; failed workbench config loads must keep the prior fallback behavior;
publish status must update both string/numeric-ID caches without a list visit.

## Verification — 2026-10-22

- Workspace catalog and both applications resolve @tanstack/react-query 4.44.0;
  no platform source imports the removed v3 package. Frozen offline lockfile
  validation passed in an isolated workspace without reinstalling local modules.
- 53 tests across 16 files passed with one worker. Coverage includes disabled
  charts, explicit reload, model cache separation/invalidation, publish caches,
  departments, handled config errors, offline initial requests and reconnect.
- Keep `networkMode: offlineFirst` for queries and mutations, as recommended by
  the official v4 migration guide to preserve v3 initial requests, paused retries
  and reconnect refresh. An observer regression failed with `always` and passed
  after this correction. Independent review found no remaining issues.
- Changed-file ESLint and diff whitespace checks passed. Generated lint
  suppressions only shrank. Full platform lint retains 85 existing violations;
  platform strict typecheck retains the existing clientVoiceDraft.test.tsx:47
  argument-count error and reports no migration errors.
- Platform production build passed. Static production startup rendered the login
  page with no captured console errors; API 404 responses were expected because
  the smoke server serves files only. Temporary server and browser tab stopped.
- Client production build and workspace i18n drift checks passed. Existing build
  warnings (chunk sizes/cycles and CSS syntax) remain outside this migration.

## Business acceptance

1. Model management: switch model types, update status and save workbench/assistant
   configuration; verify lists refresh and saved selections remain correct.
2. Workflow builder: open tool/label/template lists, change a label and reopen;
   verify cached lists refresh correctly.
3. Dashboards: create/open/edit a dashboard, configure and refresh a chart, publish
   directly from the editor, then verify published status in the list.
4. Departments: expand lazy-loaded children, change members and refresh; verify
   counts and selections update. Reconnect after a temporary network interruption
   and verify an open stale list refreshes.
