# Task 1 report — remaining default client HTTP UI chains

Status: DONE_WITH_CONCERNS (owned implementation complete; parent-owned suppression pruning/full gates remain, and one existing test has a Node/global-setup incompatibility).

Worktree: `/Users/shanghang/.codex/worktrees/request-error-contract/bisheng` only. No commits, repository-wide Git writes, dependency changes, global request-policy changes, or shared locale edits were made. Parent authorized the adjacent article controller extraction after the original component was measured at 813 lines.

## Changed production paths

All paths below are relative to the worktree:

- `src/frontend/client/src/pages/appChat/hooks/useAppSidebar.ts`
- `src/frontend/client/src/pages/appChat/SideNav.tsx`
- `src/frontend/client/src/pages/standaloneChat/hooks/useStandaloneSidebar.ts`
- `src/frontend/client/src/pages/standaloneChat/StandaloneSideNav.tsx`
- `src/frontend/client/src/pages/Subscription/hooks/useSourceManager.ts`
- `src/frontend/client/src/pages/Subscription/CreateChannel/AddSourceDropdown.tsx`
- `src/frontend/client/src/pages/Subscription/ArticleList/ArticleList.tsx`
- `src/frontend/client/src/pages/Subscription/ArticleList/useArticleList.ts` (new, parent-authorized adjacent controller)
- `src/frontend/client/src/components/Nav/Nav.tsx`

## Actual API → consumer → UI behavior

1. `getAppConversationsApi` → `useAppSidebar` / `useStandaloneSidebar` → `SideNav` / `StandaloneSideNav`:
   - Server-list rejection retains and rethrows the same full error, sets `listError`, preserves the last list, and no longer returns fake successful `[]`.
   - Existing `ApiRequestFailure` renders persistent failure with retry. Failure/loading is distinct from successful empty history.
   - Initial app placeholder creation, standalone active-chat selection, and standalone `historyLoaded` now follow successful list retrieval only. Explicit retry executes the still-pending successful initialization.
   - Reviewer-requested regression reproduced initial A failure → user creates/navigates to B → retry returning stale A. Retry now reads the latest `conversationIdRef` and `localizeRef`, preserving B without adding unstable navigation/localization dependencies to the initialization effect. The regression failed with `[failed-a]` before the fix and passes with `[draft]` afterward.
   - Mount effect consumes its terminal rejected Promise. Every rename/delete refresh callback catches its terminal Promise. Failed refresh after deletion does not navigate/select from a fabricated empty result.
   - Guest local-storage list/rename/delete behavior and the standalone module-level unsaved draft merge remain. Test exercises auth and guest draft preservation.
   - Removed the old auth resolved-403 branch because `skip403Redirect=true` already made it unreachable; no new business-layer 403 policy was added. Existing guest `resolveGuestAccessState` catch remains unchanged.
   - Removed four hardcoded Chinese strings from `useAppSidebar`: three reuse existing translations; `com_app.history_deleted` was added in all three locales by the parent after coordination. No direct shared JSON edit by this child.

2. `listManagerSourcesApi` / `searchManagerSourcesApi` → `useSourceManager` → `AddSourceDropdown`:
   - Initial list, initial search, list pagination, and search pagination now retain complete errors in `sourceListError` and preserve available rows.
   - Picker renders `ApiRequestFailure` and retries either page 1 or the failed next page. Pagination numbers only advance on success.
   - Unknown/failed search no longer presents a successful no-result/crawl suggestion. Loading and failure retain list mode; ordinary successful no-result semantics remain.
   - Source-list and search effect cleanup ignores stale completions; pagination checks its captured query key. Automatic scrolling stops on failure until explicit retry.
   - Preserved the parent's WeChat normalized business/canceled/global catch. Added one verified stale-request fix: changing from a running pasted WeChat link to an ordinary search invalidates the old token on cleanup. The regression test first failed because the old rejection incorrectly opened the unrecognized-link dialog; it now stays quiet. Existing business/canceled/global tests remain green.

3. `getArticlesApi` → extracted `useArticleList` → `ArticleList`:
   - Main page-1 and load-more failures have separate complete-error states and explicit retry. Existing articles survive failed refresh/pagination; page counters and row changes occur only after success.
   - Failed initial load is distinct from successful no content. Failed pagination stops automatic retries; retry loads the failed page and keeps prior rows.
   - Query-key/request-sequence checks prevent a previous filter/channel request from overwriting the current load state.
   - Channel switching still drops the previous channel's articles and resets filters before its next load. Source defaults, article-read updates, query keys, copy/share behavior, and unread-count best-effort fallback remain.
   - Existing unread badge fallback remains `subChannelUnreadCounts || {}` with `?? 0`, `retry: false`; it was not converted to a main-list failure.
   - Extracted existing data/controller/mapping code to meet the 600-line cap: `ArticleList.tsx` 541 lines; `useArticleList.ts` 331 lines. Existing mapping exports remain re-exported for compatibility. No new Recoil application imports were introduced.

4. `listConversations` → `useConversationsInfiniteQuery` → `Nav`:
   - Consumes the existing query's `isError/error`, displays persistent `ApiRequestFailure`, and retries via the existing `refetch`.
   - Successful empty history gets the existing empty-history copy. Cached rows stay visible with the error during failed background/page loads.
   - Automatic normal-history pagination stops while failed. Search results and their pagination remain driven by the existing search query response and are not replaced by the normal-history failure.
   - Existing query keys, API rejection metadata, and deletion-confirm behavior were untouched.

## Test changes and red/green evidence

- New `pages/appChat/hooks/sidebarRequestErrors.test.tsx` (4 tests): original code failed the first two tests because `listError` did not exist and server failures completed initialization as empty success. Now verifies same-error rejection, list preservation, successful-only initialization, retry, auth drafts, and guest local history/drafts.
- Extended existing `pages/Subscription/hooks/useSourceManagerErrors.test.ts` (8 tests total): original list/search/pagination paths failed the four added load/error tests; stale WeChat test separately reproduced the late-error dialog. Now all pass, including original normalized business/canceled/global recovery checks.
- New `pages/Subscription/ArticleList/ArticleListErrors.test.tsx` (2 tests): original main loader logged and cleared rows; failure text/retry was absent. Now verifies initial error vs successful empty, previous articles on failed reload, failed next-page recovery, and continued successful append.
- New `components/Nav/NavRequestErrors.test.tsx` (2 tests): original component lacked error and successful-empty UI. Now verifies persistent error/retry, successful empty state, and preserved search results. Retry assertion clears the mount refetch call before clicking, so a disconnected retry handler cannot pass it.

Final focused command (cwd `src/frontend/client`):

```sh
JEST_JUNIT_OUTPUT_DIR=/private/tmp/f088-child pnpm exec jest src/pages/appChat/hooks/sidebarRequestErrors.test.tsx src/pages/Subscription/hooks/useSourceManagerErrors.test.ts src/pages/Subscription/ArticleList/ArticleListErrors.test.tsx src/components/Nav/NavRequestErrors.test.tsx --runInBand --coverage=false --forceExit
```

Result: **4 suites / 16 tests passed**, exit 0 (final run after reviewer correction: 3.286 s).

Additional guest recovery regression:

```sh
JEST_JUNIT_OUTPUT_DIR=/private/tmp/f088-child pnpm exec jest src/pages/standaloneChat/guestAccessError.test.ts --setupFilesAfterEnv=@testing-library/jest-dom/extend-expect --runInBand --coverage=false --forceExit
```

Result: **1 suite / 9 tests passed**, exit 0. The same existing test under the repository's default setup fails before running tests: its `@jest-environment node` encounters unmodified `test/setupTests.js:59`, which reads `Element.prototype` without a Node guard. No out-of-scope setup edit was made. The explicit setup override isolates the pure guest-recovery tests; it does not hide an assertion failure.

Scoped ESLint command used all nine production files and four focused test files with `--suppressions-location eslint-suppressions.json --pass-on-unpruned-suppressions`: **exit 0, no diagnostics**. Without `--pass-on-unpruned-suppressions`, the same zero-diagnostic run exits 2 only because localization/extraction shrank existing suppression counts. Parent was notified and owns the global `pnpm lint:prune`/quality file.

`pnpm typecheck` from client: **final run passed all 1490 strict files**, exit 0 (after reviewer-requested stale-conversation correction). An intermediate concurrent run had failed only in parent-owned `src/hooks/chatHistoryErrors.test.tsx:40` (`TS2554: Expected 2 arguments, but got 1`); the parent repaired that test before the final passing run. No owned file produced a type diagnostic. `git diff --check` on all owned tracked paths: exit 0.

## Remaining checks / concerns

- Parent explicitly owns and will execute full client/frontend gates, suppression pruning, E2E, and independent review. This report closes only the assigned active chains; it does not claim all client AC-21 consumers are verified.
- Known default Node-test setup incompatibility above must remain visible in the full-gate result; it is unrelated to these implementation paths.
- No browser/manual backend validation was performed by this child. Focused tests execute real hooks/components, mock the external API boundary and unrelated heavy providers, and use the shared real Alert-based `ApiRequestFailure` where the component is exercised.
