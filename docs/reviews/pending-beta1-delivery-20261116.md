# Pending beta1 delivery — 2026-11-16

## Scope and integration

User requested all 42 pending files be committed/pushed to `feat/3.1.0-beta1`, then merged into `release`. Original working tree was based on `498337864a` and 126 commits behind remote beta1. The exact original state is preserved in commit `3ec08fb2e3`; this integration merge retains that commit as a parent. Conflict resolution uses latest beta1 `754cf11e0f` layouts and preserves its upload wizard, workspace list/card modes, navigation, and current permission rules.

Included behavior: retry uses the current model; each loaded directory/search page asynchronously inspects download eligibility without blocking selection; direct download no longer depends on opening the menu; department search does not flex-shrink; optional workflow fields submit empty values; metadata empty/loading states and upload progress presentation are retained with staged/remove/registration guards.

The withdrawn department-policy recovery patch is excluded. No deployment or server state changes are part of this delivery.

## Verification

- Frontend workspace `pnpm lint`: passed.
- Frontend workspace `pnpm typecheck`: passed.
- Client retry, reconciliation, and status regression: 31 passed.
- Backend retry endpoint HTTP/dispatch/rollback/authorization regression: 7 passed; Ruff check and format check passed.
- Shared workflow form: 5 passed.
- Combined platform selection: 135 passed, 2 failed. Both failures reproduce on the pre-merge HEAD implementation and original history test via temporary Vite load snapshots: 11 passed, the same 2 failed. No new failures in this selection.
- Existing failures: `retains the original multiversion/nonfolder gate: { is_multi_version: false }`; `retires history if a refreshed file stops being multiversion`. They assert the old multiversion-only gate while latest beta1 already enables history for every file when the feature is enabled.

## Original-file accounting

Every original path is listed below. “Latest implementation retained” means its old layout-only change conflicts with the newer replacement; the original edit remains in the merge history, while the current implementation stays in the final tree.

| Original path | Resolution |
| --- | --- |
| `features/v3.1.0-beta1/118-knowledge-space-unification/design.md` | Integrated, adapted to latest beta1 where needed |
| `src/backend/bisheng/linsight/api/endpoints/linsight.py` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/api/linsight.ts` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.retry.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/hooks/mapSessionVersionStatus.test.ts` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/hooks/reconcileLinsightFromServer.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/hooks/useLinsightManager.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/packages/chat/src/components/WorkflowForm.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/packages/chat/src/components/WorkflowForm.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/eslint-suppressions.json` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/public/locales/en-US/knowledge.json` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/public/locales/ja/knowledge.json` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/public/locales/zh-Hans/knowledge.json` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/components/bs-comp/department/LazyDepartmentTree.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/components/bs-comp/knowledgeUploadComponent/DropZone.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/controllers/API/knowledgeBatch.ts` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/Header.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceDirectoryRow.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceDirectoryToolbar.tsx` | Latest implementation retained |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceFileTools.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceFileUploadPanel.tsx` | Latest implementation retained |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceIndexEditDialog.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceUploadProgress.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/detail.tsx` | Latest implementation retained |
| `src/frontend/platform/src/pages/KnowledgePage/filesUpload.tsx` | Latest implementation retained |
| `src/frontend/platform/src/test/f118SpaceDetail.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceDirectory.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceDirectoryHistory.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceDirectoryUpload.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceFileTools.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceVersionHistory.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceVersionOperations.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `docs/reviews/knowledge-file-download-20261113.md` | Integrated, adapted to latest beta1 where needed |
| `docs/reviews/task-retry-current-model-20261113.md` | Integrated, adapted to latest beta1 where needed |
| `src/backend/test/linsight/test_retry_model_selection.py` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/client/src/hooks/retryLinsightModel.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/components/SpaceIndexEditDialog.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/pages/KnowledgePage/hooks/useDirectoryDownloadPermissions.ts` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/f118SpaceDownloads.test.tsx` | Integrated, adapted to latest beta1 where needed |
| `src/frontend/platform/src/test/helpers/knowledgeSpaceFixtures.ts` | Integrated, adapted to latest beta1 where needed |
