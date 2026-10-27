# Fix round 2 report — export/import/upload terminal consumers

Status: DONE. Changes are confined to the five parent-assigned production files and three new focused tests. No commits, repository-wide Git writes, subagents, dependencies, locale JSON writes, request-policy changes, or further CRUD expansion.

Brief: `.superpowers/sdd/client-final-migration-plan/fix-round-2-brief.md` (updated with the parent's HTTP retry clarification and additional same-file duplicate/delete catch authorization).

## Changed production paths

Relative to `src/frontend/client/src/`:

- `components/Chat/MessageSelection/MessageSelectionToolbar.tsx`
- `components/Chat/MessageSelection/ExportFormatSheet.tsx`
- `components/Chat/ChatView.tsx`
- `pages/appChat/ChatView.tsx`
- `pages/knowledge/hooks/useFileUpload.ts`

The existing daily ChatView `historyError`/`retryHistory`/`isClearing` wiring remains intact. Existing parent changes to upload quota interpolation, rename behavior, and deletion success-after-commit remain intact.

## Four export/import UI endpoints

The desktop toolbar export, mobile sheet export, daily-chat import, and app-chat import catches now distinguish canonical `ApiError` from local failures:

- `ApiError` is passed directly to `showApiError(error)` using the exact original object. No partial reconstruction of `status_code`/`status_message` remains in these catches, so `data`, original `response`, `cause`, cancellation kind, and presentation ownership are preserved.
- Global/canceled/already-presented errors go through the canonical helper without adding an unconditional local toast.
- Non-API local/browser download failures retain the existing localized `workstation.messageExport.renderFailed` fallback.
- Export pending flags reset in `finally`; the export sheet closes only after successful download. Both import modals and selection remain open on failure and only complete after a successful import.
- Removed the sheet's hardcoded Chinese no-selection fallback, using the existing `workstation.messageExport.noSelection` localization; no new key needed.

Tests render the actual four endpoint components, mock only APIs and unrelated heavy children/providers, and assert exact identity with `.toBe(error)`, absence of extra ordinary toast, reset/retained UI state, local fallback, and successful continuation.

## Upload and registration

Actual production chain: knowledge `SpaceDetail` input/drop callbacks → `handleUploadFile` / `handleUploadFolder` → shared `uploadFilesSequential` → `uploadFileToServerApi`, followed by `addFilesApi` / `uploadFolderApi`.

- Sequential upload immediately rethrows the same global/canceled ApiError, stops the batch, and never includes it in ordinary aggregation. A prior successful body does not allow partial registration after that terminal failure.
- Ordinary per-file failures now retain an `error: unknown` evidence field containing the exact original error in addition to their existing display reason/code. Existing 18024/19402/19403 early-stop and named quota aggregation remain unchanged. Ordinary non-collapsible failures continue with the remaining files and keep their per-file report.
- File upload wraps the full upload/register operation in terminal `catch` + `finally`: API failures go to `showApiError`, local registration failures retain the old localized fallback, placeholders always clear, and quota is refreshed after any attempted batch.
- Folder upload consumes propagated errors in its outer UI catch, always releases the reentry lock and placeholder in `finally`, and refreshes quota whenever body uploads started, including a cancellation/global error after partial byte storage. The regression first showed folder abort skipped this quota refresh; the finalizer now preserves it.
- The folder duplicate-name precheck keeps its established ordinary failure fall-through. Global/canceled errors are rethrown to the outer terminal handler instead of resuming uploads.
- File registration retains the existing **one retry** budget for canonical HTTP/network/timeout failures using `isApiError(firstErr) && shouldRetryApiError(firstErr)`. It does not retry business, canceled, global, invalid-response, or ordinary local Error failures. File bodies are not uploaded again during registration retry.
- Per explicit parent follow-up, duplicate-file overwrite and single-delete catches in this same file also now delegate ApiError to the canonical helper and retain their local fallbacks. Existing duplicate cleanup and optimistic single-delete rollback/reload remain; delete success is still announced only after the backend commits.

## Focused tests and red/green evidence

New tests:

- `components/Chat/MessageSelection/exportFailureContract.test.tsx`: 10 tests. Initial original-code run had 6 expected failures for missing canonical ownership; 4 local/success tests already passed. Final all 10 pass.
- `components/Chat/importFailureContract.test.tsx`: 8 tests through both real ChatViews. Negative control temporarily restored the previous unconditional-toast behavior in only those catches: 6 canonical ApiError assertions failed, 2 local/success cases passed. Both fixes were immediately restored in `finally`; final all 8 pass.
- `pages/knowledge/hooks/uploadTerminalErrors.test.tsx`: 22 tests. Initial run reproduced batch continuation, lost evidence, inappropriate retry, missing terminal cleanup, and precheck fall-through (12 failures). The later explicitly authorized duplicate/delete cases were separately observed red (4 missing-canonical-presentation assertions) before implementation. The partial-folder quota-refresh assertions were separately observed red (2 cases) before their finalizer correction.
- Existing `pages/knowledge/hooks/uploadFailureContract.test.ts` quota regression: 1 test remains green.

Final command (cwd `src/frontend/client`):

```sh
JEST_JUNIT_OUTPUT_DIR=/private/tmp/f088-child pnpm exec jest src/components/Chat/MessageSelection/exportFailureContract.test.tsx src/components/Chat/importFailureContract.test.tsx src/pages/knowledge/hooks/uploadTerminalErrors.test.tsx src/pages/knowledge/hooks/uploadFailureContract.test.ts --runInBand --coverage=false --forceExit
```

**Final result: 4 suites / 41 tests passed, exit 0** (last run 8.701 s). No test warnings/errors other than Jest's expected `--forceExit` advisory.

Changed-file ESLint includes the five production files and three new tests, with the existing `eslint-suppressions.json` and `--pass-on-unpruned-suppressions`: **exit 0, no diagnostics**. Suppression pruning remains parent-owned; no suppression file or strict-ignore header was added/edited.

`git diff --check` for the five production files: exit 0.

## Scope and remaining verification

No known unresolved issue in this assigned round. Per parent instruction, no full client/frontend suite or full typecheck was run by this child for round 2; the parent will execute the unified final gates after these focused tests are green. Existing large ChatView/useFileUpload files were kept in scope and reduced slightly rather than expanded into an unrelated structural refactor.
