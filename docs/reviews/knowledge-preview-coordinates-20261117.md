# Knowledge preview coordinates hotfix — 2026-11-17

## Cause and change

The preview mounts before the independent coordinate request completes. It retained its initial empty coordinate object, so later responses never produced PDF overlays or a scroll target. Read the latest partitions prop in conversion, selection and overwrite handlers; invalidate edited-label caches when partitions change and clear overlays for empty replacements.

## Verification

- Regression tests failed before the fix (3/3), then passed. Both async arrival orders and empty replacement are covered using the real component, store and coordinate conversion.
- Focused preview, file-detail and PDF suites: 15 passed.
- Workspace `pnpm lint` and `pnpm typecheck`: passed. ESLint suppression pruning removed one obsolete any suppression.
- Architecture guard and `git diff --check`: passed.
- Independent code review: PASS.
- Platform full suite: 380 files, 2,515 passed / 60 failed; all 60 failures reproduced in the unmodified beta1 baseline f97b4feb2b. Two unhandled ApiError rejections in IconUploadSection also reproduce in that baseline.
- Updated base to f584817988 before delivery; the two intervening commits only change backend workbench guides and their tests.
- No changes deployed to 116.

## Existing failures reproduced on baseline

### pages/publicEntries.test.tsx

- shows a soft limit while keeping the accessible form label

### test/approvalPage.test.tsx

- ApprovalPage renders page title and loads scenario/route/node data on mount
- ApprovalPage opens add-scenario dialog and creates scenario on confirm
- ApprovalPage switches to exception tab and retries an exception
- ApprovalPage assigns checked users to an exception with the same retry payload
- ApprovalPage requires a cancellation reason and trims it before submitting
- ApprovalPage uses historical tasks when an exception has no flow snapshot

### test/citationFailure.test.ts

- citation request failures preserves expired reasons on directly rejected business envelopes

### test/departmentPageRefresh.test.tsx

- DepartmentPage member refresh retries a failed branch in place without changing the current department

### test/f048PermissionDialog.test.tsx

- F048 PermissionDialog keeps the legacy subject tabs, search, add action, and roster layout

### test/f114ConcreteScope.test.tsx

- protects only dedicated management writes; shared reads and calls keep their contract

### test/f118ProcessingManagementScope.test.ts

- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for GET /api/v1/knowledge/space/42/processing-settings
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for GET /api/v1/knowledge/space/42/processing-jobs
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for GET /api/v1/knowledge/space/42/processing-jobs/job-42
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for GET /api/v1/knowledge/space/42/processing-jobs/job-42/items
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/batch-delete
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/move
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for PUT /api/v1/knowledge/space/42/files/10
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for PUT /api/v1/knowledge/space/42/files/10/encoding
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/10/tag
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/batch-download
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/batch-tag
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/batch-retry
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/files/retry
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/folders
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for POST /api/v1/knowledge/space/42/folders/upload
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for PUT /api/v1/knowledge/space/42/folders/10
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for DELETE /api/v1/knowledge/space/42/folders/10
- F118 processing command management scope AC-33/35/84: preserves the existing ordinary-call boundary for DELETE /api/v1/knowledge/space/42/files/10

### test/f118SpaceDirectoryHistory.test.tsx

- retains the original multiversion/nonfolder gate: { is_multi_version: false }
- retires history if a refreshed file stops being multiversion

### test/hostedAppDeleteEligibility.test.tsx

- allows platform super admins alongside the original owner (7, false, false)
- allows platform super admins alongside the original owner (8, false, true)
- allows platform super admins alongside the original owner (8, true, true)

### test/hostedAppMenuTrim.test.tsx

- ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) offers manage-permission and delete, and nothing else
- ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) never offers copy or add-to-template, even to an admin who can edit
- ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) greys delete out while the application is online (F054 AC-42)
- ⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53) drops the permission entry for a caller who may not manage it

### test/knowledgeSpaceGrantSubjects.test.tsx

- permission subject discovery business boundary adds a department carrying the current include-children flag when toggled on

### test/knowledgeUploadsContract.test.ts

- uses the real wrapped request's conditional staging pin and no registration management header

### test/knowledgeVersionsContract.test.ts

- uses the wrapped request transport and leaves backend error normalization intact

### utils/dshRequestError.test.ts

- DSH management error messages preserves business error 26112 in direct and HTTP envelopes
- DSH management error messages preserves business error 26113 in direct and HTTP envelopes
- DSH management error messages preserves seat_limit_reached in operation receipts and HTTP errors
- DSH management error messages preserves seat_revoked in operation receipts and HTTP errors

### pages/DataSetPage/CreateDataSet.test.tsx

- clears a previous file when switching to QA and submits only selected libraries
- loads further QA pages and preserves selections when searching
- keeps the newest search result when an older request finishes later
- reports a failed QA load and allows retry by reopening the selector

### controllers/API/knowledgeDeletion.test.ts

- pins all new reads and writes with the current server-learned management scope

### pages/BuildPage/bench/IconUploadSection.test.tsx

- workbench logo upload keeps the original logo and shows the server error, then retries the same file
- workbench logo upload restores the picker after an image decoding failure and accepts the same file again
- workbench logo upload keeps the current icon while a request is in flight and restores the picker afterward
- workbench logo upload preserves an absolute uploaded image URL

### pages/BuildPage/hostedApp/publish/AppSecretSettings.test.tsx

- environment settings opens confirmation without calling rebuild and gives administrators no write buttons

### pages/BuildPage/hostedApp/publish/DangerZoneCard.test.tsx

- delete visibility and state guard (7, false, stopped)
- delete visibility and state guard (8, true, stopped)
- delete visibility and state guard (8, true, online)

### pages/ModelPage/manage/dsh/ModelAccessDialog.test.tsx

- saves visibility without sending a credit multiplier

