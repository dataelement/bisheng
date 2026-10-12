# Model access panel layout — 2026-09-15

Scope: user, department and role panels in the model permissions dialog. Branch `codex/dsh-user-grants-switch`, source baseline `108782eaa`, live 3006 baseline verified as `7059261a2`.

| Before | After | Why |
| --- | --- | --- |
| Dialog height depends on content; each tab owns a different scrolling wrapper. | Bounded 88vh dialog, capped at viewport minus 64px. All three tabs use the same flex-sized bordered scrolling panel. | Switching among long, short, empty and loading content retains panel geometry; header, search and save stay visible. |
| Department rows communicate depth using inline padding alone; roots start collapsed. | Roots expand initially and load direct members. Nested groups use a fixed left gutter with vertical and horizontal tree connectors. | Parent-child relationships are explicit; children remain individually expandable. Existing department selection and inherited quota rules are preserved. |
| Global pending-help sentence occupies a row under the toolbar. | The sentence is removed. Pending row state and querying the original operation via Save remain available. | Apply the requested copy simplification while keeping pending operations distinct from successful saves. |
| Inherited child departments show an extra `继承` badge beside the department name. | The badge is removed. Inherited children remain selected and read-only, and continue to display the effective quota from the selected ancestor. | The existing selection and quota state already communicates the outcome; removing the implementation term keeps the tree focused on departments and values. |

## Verification

- PASS: 76 tests across model access and DSH management; covers default root expansion, nested connectors, collapse/search, shared panel styles, pending operation query, draft saves and prior seat pagination behavior.
- PASS: scoped ESLint, architecture guard, i18n parity and diff whitespace checks.
- PASS: isolated Chrome with read-only mocked APIs. At 1440×950, each panel is exactly 1110×716 and each dialog 1152×836. Nested departments have increasing x positions and 1px tree connectors. Long user list scrolls to Load more. At 1280×600, dialog height is 528 with top/bottom 36px.
- Full typecheck retains three existing errors outside the changed files: `Departments.tsx`, `f048DashboardPermissions.test.tsx`, `routeFilterPurity.test.ts`.
- PASS: Vite production build; deployed release `e1ce7b6e0` to 3006 with rollback release `7059261a2`. Only frontend recreated; backend stays healthy and Gateway keeps its original process.
- PASS: served index matches SHA-256 `23e20bc92edaeca7db445ca4e9008ebf25360102b04f64165480d21b61bf26e6`; `/dsh`, `/workspace/` and browser config return 200; anonymous model subjects return 401.
- PASS: logged-in Chrome shows the real organization root expanded with tree lines to its children. Users, departments and the one-row role panel share identical bounds. The global pending-help sentence is absent after loading admin's pending operation; its row state and Save query remain visible.
- PASS: inherited child departments remain selected, read-only and bound to the ancestor quota in automated coverage, while the `继承` badge is absent.
- PASS: merged the then-current 3006 release `e9279ebf9` before deployment, retaining its usage heatmap changes. Deployed frontend release `5eccab8bc`; backend and Gateway processes were preserved.
- PASS: logged-in Chrome reload of 3006 reports zero exact `继承` labels in the department panel. `/dsh`, `/workspace/` and browser config return 200; served index SHA-256 is `434746c253f54c035484a2a45158eac5c499505ac4fe74bc00ac03e3fc6f56d2`.
- Live authorization writes: NOT_RUN. Existing backend recovery behavior remains outside this layout change.

Evidence: `outputs/dsh-panel-layout-3006-20260915/` (layout browser script, screenshots and measurements) and `outputs/dsh-hide-inherited-3006-20260916-merged/` (merged release artifacts and deployment report).
