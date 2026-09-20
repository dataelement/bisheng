# Usage filter interaction revision

## Scope

The usage page uses the existing tenant-scoped read APIs and permission rules. The heatmap, model grants, seat allocation and usage aggregation contracts retain their current behavior.

## Acceptance criteria

- Opening the user selector immediately loads tenant users. The result area has a 240 px height with native vertical scrolling, and additional pages append to the current list.
- Search filters users remotely; clearing search restores the tenant list. Loading, empty, request failure and retry states remain explicit. Stale requests cannot replace newer search results.
- The initial dimension is user. The current signed-in user is selected when present in the tenant-scoped results, with the first available user as fallback. Explicit selection survives date changes and dimension switches.
- The dimension toggle, target selector, date selector and refresh action share the top row with the DSH section tabs and align to the right. The row wraps naturally when its contents exceed the available width.
- Tab changes remove the usage toolbar; returning to usage restores the appropriate controls. Other DSH sections retain their existing content and actions.
- Automated interaction tests and an authenticated read-only browser check cover the resulting layout and selectors before deployment is reported as verified.

## Implementation

The DSH page provides a stable header target. The usage view renders its existing toolbar into that target using a React portal; filter state remains owned by the usage view. Legacy standalone rendering keeps an inline toolbar. Existing Popover and Command primitives provide the searchable list.

## Status

Implementation complete. All 56 frontend DSH/API regression tests, changed-file ESLint, architecture guard, i18n checks and Vite production build pass. Strict TypeScript retains the three baseline errors outside this change.

An isolated Chromium check verified the shared header center line at 1536 px, a 240 px user list, scrolling from 20 to 35 users, search and clear, default/current user selection, section-switch cleanup and a wrapped toolbar at 900 px. Fixture screenshots are in `outputs/dsh-usage-filter-20260915/`. Authenticated deployment acceptance remains pending, coordinated with the separate user-grant autosave task.

The implementation is committed as `ca1549cc4`. Integration with the published user-grant autosave commit `d939732d6` produced `a042da16c`; all 86 combined regression tests and the production build pass.

Deployment is pending explicit user approval to upload the scoped UI source/test/documentation delta, frontend build and release verification files to `192.168.106.119:3006`. Security review blocked the transfer before upload. The live release remains `d939732d6`; this task created only an empty `artifacts/a042da16c` directory and kept the current link and services unchanged. Authenticated acceptance of the new filters is NOT_RUN.
