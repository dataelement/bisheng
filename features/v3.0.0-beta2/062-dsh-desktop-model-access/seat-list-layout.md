# Seat list layout — 2026-09-15

Scope: DSH Desktop → License and seats. This change preserves the seat API, filters, cursor pagination and command behavior. Selected branch: `codex/dsh-user-grants-switch`; source baseline `7ca5d4122`, verified 3006 running release `9cfe13d22`.

| Before | After | Why |
| --- | --- | --- |
| Search input wrapper takes the full row; filters wrap below it. | Fixed-width input wrapper, search and both selects form a right-aligned row. | Layout width belongs to the actual wrapper. Existing controls and visual styling remain intact. |
| Previous and next are left-aligned and always rendered, disabled at boundaries. | The seat list opts into a bottom-right pager that renders available directions only. | First page shows next, last page shows previous, middle pages show both; a single or empty page shows neither. |
| All DSH lists share the pager default. | Seat list uses explicit layout and visibility options. Other pager consumers retain their current behavior. | Keep the requested change bounded to the seat list. |

## Verification

- PASS: 37 tests across the DSH management module, including first/middle/last/single/empty page visibility, search reset, cursor navigation and stale-response cancellation.
- PASS: scoped ESLint, architecture guard, i18n parity, `git diff --check`, Vite production build.
- PASS: isolated Chrome acceptance with mocked read-only APIs; bounding-box assertions verified same-row filter alignment and bottom-right pagination, first/middle/last/single page transitions and search reset. Screenshots and results: `outputs/dsh-seat-layout-3006-20260915/`.
- Typecheck: three existing errors outside this change (`Departments.tsx`, `f048DashboardPermissions.test.tsx`, `routeFilterPurity.test.ts`); changed files passed scoped ESLint.
- PASS: deployed `7059261a2` to 3006, rollback release `9cfe13d22`; only frontend recreated. Backend remains healthy, Gateway keeps its prior process.
- PASS: served `/dsh` index SHA-256 equals the build (`e59fbb773eee49bbdf2b4c58b334e7b7e381aa6cf05b1ce8c967b39dcd869b74`); `/dsh`, `/workspace/`, browser config return 200; anonymous seat management returns 401.
- PASS: logged-in Chrome at `/dsh?tab=license` confirms three right-aligned filters on one row and the current single-seat page hides both pagination buttons. Existing seat data remains intact. Multi-page behavior was verified with isolated fixtures.
- Backend, Gateway, license, user authorization and seat mutations are outside this layout change.
