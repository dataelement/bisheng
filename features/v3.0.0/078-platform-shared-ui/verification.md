# Verification — platform shared UI first batch

Base: `d8326651b4` on `feat/3.0.0`. No backend changes.

User acceptance: passed on 2026-10-19. Subsequent migration proceeds by business
module, with each page and its related dialogs accepted together.

Local testing: API, license, and object requests must use the existing
`http://192.168.106.120:3002` test entry. Port 3001 on that host serves a separate
environment and returns 404 for `/api/v1/settings`. With the corrected proxy,
the unauthenticated settings request returns 401; web config and env return 200.

## Completed checks

- Shared adapter and theme bridge checks: 32 passing tests (14 migration, 4 theme, 14 seat-toolbar regression tests).
- Full platform suite: 682 passed, 16 failed. All 16 failures reproduced with identical test names on a clean archive of the base commit.
- Modified source files: scoped ESLint passes; suppressions pruned by ESLint, shrink-only.
- Final platform typecheck: all 589 strict files passed, including the theme bridge.
- Final production build passed in 30.39s, including the theme bridge. An earlier build also passed after correcting a stale local react-router-dom symlink (installed 6.17.0 versus the already declared/locked 6.30.4). No router dependency version change.
- `node scripts/check-i18n.mjs`: no new i18n drift.
- Independent read-only review: textarea sizing and token load-order findings fixed; final theme bridge review had no actionable findings.
- Actual Chromium checks against a compiled temporary fixture: default brand/radius, loading disabled, native max length, password visibility, chat textarea height cap, custom primary plus hover, dark hover ramp, Toast and Notification containers. No page errors. Browser and temporary server closed afterward.

## Existing lint failures

Full platform lint reports 95 errors and one warning, also reproduced on the clean base archive. They are outside the changed source files. Files include CitationReferencesDrawer, DepartmentUsersSelect, useSubjectSearch, controllers/API/index.ts and license.ts, WorkbenchSensitivePolicy, FlowChat/MessageMarkDown, and f067LicenseBannerCopy.test.ts.

## Existing test failures

- `src/pages/SystemPage/dsh/commercialLicense.test.tsx` — commercial License request prepares the same complete request for preview, email and clipboard
- `src/test/approvalPage.test.tsx` — ApprovalPage deletes a route via the delete button
- `src/test/approvalPage.test.tsx` — ApprovalPage edits a route via the edit button and updates route
- `src/test/approvalPage.test.tsx` — ApprovalPage enters edit mode, adds a node in draft, and saves via set_flow_nodes
- `src/test/approvalPage.test.tsx` — ApprovalPage opens add-scenario dialog and creates scenario on confirm
- `src/test/approvalPage.test.tsx` — ApprovalPage opens flow dialog and creates a new flow when no flow is preselected
- `src/test/approvalPage.test.tsx` — ApprovalPage opens route dialog, creates a route and reloads routes
- `src/test/approvalPage.test.tsx` — ApprovalPage renders page title and loads scenario/route/node data on mount
- `src/test/approvalPage.test.tsx` — ApprovalPage switches to exception tab and retries an exception
- `src/test/departmentKnowledgeSpaceDialogs.test.tsx` — department knowledge space dialogs does not render approval settings controls in the department knowledge space list
- `src/test/departmentUsersSelectScope.test.tsx` — DepartmentUsersSelect candidate eligibility applies eligibility to name search as well as browsing
- `src/test/departmentUsersSelectScope.test.tsx` — DepartmentUsersSelect candidate eligibility keeps unvalidated candidates hidden when filtering fails
- `src/test/departmentUsersSelectScope.test.tsx` — DepartmentUsersSelect — rootDeptId scope renders the backend-resolved department_path for user search, with no per-dept path-tree
- `src/test/departmentUsersSelectScope.test.tsx` — DepartmentUsersSelect — rootDeptId scope uses the target subtree for scoped user-name search
- `src/test/knowledgeSpaceGrantSubjects.test.tsx` — permission subject discovery business boundary adds a department carrying the current include-children flag when toggled on
- `src/test/knowledgeSpaceGrantSubjects.test.tsx` — permission subject discovery business boundary loads the user groups grantable on this resource

## Browser artifacts

- [Light controls](/Users/shanghang/.codex/visualizations/2026/10/16/01a1448f-1d37-7932-9a39-ef6d105ad9e8/platform-ui-light.png)
- [Mapped theme, dark controls and notices](/Users/shanghang/.codex/visualizations/2026/10/16/01a1448f-1d37-7932-9a39-ef6d105ad9e8/platform-ui-theme-dark.png)

These are isolated compiled control checks, not authenticated full business-flow E2E tests. Live backend workflows, mobile WebViews, and customer browsers were not exercised.
