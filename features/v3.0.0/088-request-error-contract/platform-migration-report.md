# Task 1 report — F088 platform consumer migration

Status: **DONE_WITH_CONCERNS**. Work performed only in /Users/shanghang/.codex/worktrees/request-error-contract/bisheng; no commits, no repository-wide Git writes, no subagents, and no unsafe migration script. Production migration was scoped manually to inspected API → consumer → UI chains.

## Delivered behavior

- All production imports/calls of captureAndAlertRequestErrorHoc have been removed. Final scan `rg -n captureAndAlertRequestErrorHoc src/frontend/platform/src --glob '!*.test.*'` returns only the parent-owned deprecated definition in controllers/request.ts. Parent has switched that compatibility helper to notice + reject.
- Requests remain rejecting inside reusable APIs/hooks and sequential operations. UI events/effects consume rejection with showApiError or handleUiRequest. Default notices are deduplicated through error.presentation; cancellations are handled by the shared helper.
- Dashboard: save → publish and save → leave stop on failure; busy state unlocks through mutation settlement; inputs and dirty state remain after save failure. Publish/create/copy/rename/delete/component-copy error callbacks use showApiError. Delete confirmation waits for mutateAsync. Chart query failures remain React Query error state and display operationFailed rather than noDataInChart. Query keys, retry configuration, and isInitialLoading remain unchanged.
- Confirmation singleton: awaits returned async work, prevents Radix automatic close, disables repeated confirmation while pending, catches only at this UI boundary, and releases the lock on failure. Every migrated confirmation now returns/awaits its request and calls next only after success. Workflow inline version rename similarly preserves the draft and unlocks retry after failure.
- Build/workflow/assistant: failed save blocks publication, version switching, leave, preview, and follow-up state writes; direct API rejections propagate through inner save functions. Creation/editor forms and test runners use finally for busy flags. Optimistic template ordering and app/card status changes restore prior state on rejection.
- Workbench settings: policy saves and dependent config saves remain rejecting until actual UI events. Preview awaits success. Failed configuration load cannot silently save a blank replacement in AppCenter, KnowledgeSpace, Subscribe, or system YAML config; existing explicit blind-overwrite confirmation in the daily config is preserved.
- Knowledge: create/edit failures preserve open forms; failed QA/segment/tag writes preserve user input and selection; failed copies clear the local copy lock; uploads do not advance stages on request failure. Parent-child default upload save retains its Promise so the actual upload button can recover loading in finally.
- Department/tenant/system/service account: mutations no longer execute success notices, close dialogs, refresh as success, or change displayed status after failure. Account optimistic toggles restore previous status. Batch resource grants preserve uncompleted selections and refresh already completed work after partial failure. Role menu load failure keeps its existing failure flag and prevents invalid save.
- API wrapper audit found two non-HOC generic swallow points: selectable knowledge-space union returned partial successful data after one request failed, and the editor write-permission check returned undefined after failure. Both now preserve the original rejection; both were reproduced with RED tests first and their active UI consumers were updated.
- Existing named recoveries were retained: optional license status/best-effort license reporting; permission-summary fail-closed behavior; inherited-admin summary fallbacks; restore current admin selection when a post-save refresh is unavailable; generic tag-delete warning when usage lookup is unavailable; callback/SSE parsing error channels. The unused getRepoStars helper has no production caller (`rg` finds its definition only); no live success flow relies on its legacy null return.
- i18n: extracted the touched hardcoded app permission warning and tag editor strings. Added build.editPermissionRequired and knowledge.tagEditor.{addPlaceholder,existingTags,emptyTags} in en-US / zh-Hans / ja; reused existing editTag/cancel/confirm keys. No styles or design specs changed.

## Verification

1. Full platform Vitest (after production/API migration, before the final isolated inline-rename regression):
   - 180 test files: 179 passed / 1 failed.
   - 907 tests: **905 passed / 2 failed**; no unhandled errors.
   - Log: /private/tmp/f088-platform-completion-tests.log.
2. Final focused regressions after inline-rename recovery:
   - 6 files / **12 tests passed** (confirmation retry, inline version rename, Dashboard save/publish failure and retry, dataset creation failure, original API wrapper rejection, account-toggle rollback).
   - Log: /private/tmp/f088-platform-regressions.log.
   - Additional 5 files / 14 tests passed covering Dashboard, API wrappers, department settings, workbench page, and knowledge selector: /private/tmp/f088-platform-last-focused.log.
   - Service-account mutations + personal token + account rollback: 3 files / 14 tests passed.
3. Changed-platform-file ESLint with the repository suppression file: **exit 0**. Ran the supported --prune-suppressions command; no hand editing. The suppression file shrank (64-line diff, 53 removals / 11 additions from regenerated counts).
4. Platform pnpm typecheck: only the known untouched baseline failure remains: src/test/clientVoiceDraft.test.tsx:47 TS2554, Expected 0 arguments but got 1. Parent-owned request test errors seen earlier were fixed by parent.
5. Root pnpm check-i18n: **OK — no new i18n drift**.
6. git diff --check: clean.
7. Relevant skills read: test-driven-development and writing-good-tests, i18n-localizer, approval-module for menu-access request context. UI docs index/component overview read. Existing source-only account-toggle test was replaced with runtime behavioral regression coverage.

## Outstanding concerns / baseline failures

- Full suite has two existing expectation drifts in src/test/knowledgeSpaceGrantSubjects.test.tsx:
  - “adds a department carrying the current include-children flag when toggled on”: expected only {type,id,name,include_children}, but unchanged SubjectSearchDepartment includes departmentPath, departmentTreePath, externalId.
  - “loads the user groups grantable on this resource”: expected pageSize 200 without paging/signal, but unchanged SubjectSearchUserGroup sends keyword, page 1, pageSize 50, signal.
  - `git diff HEAD -- src/frontend/platform/src/components/bs-comp/permission/SubjectSearchDepartment.tsx src/frontend/platform/src/components/bs-comp/permission/SubjectSearchUserGroup.tsx src/frontend/platform/src/components/bs-comp/selectComponent/useSubjectSearch.ts` is empty. These tests previously failed at missing legacy request mocks; fixing those mocks exposed the stale assertions. Their unrelated expectations were left unchanged.
- Strict baseline clientVoiceDraft.test.tsx:47 remains unmodified as instructed.
- No browser or middleware E2E was run in this subtask; controller must complete overall feature E2E/independent review before merge.
- Platform AGENTS.md still shows the old HOC consumer pattern in its API example; controller should update that verified contract documentation when finalizing the overall feature.
- Full suite ran before the last isolated inline-rename change; that last change was validated with the final focused 12-test run, strict typecheck, lint, and diff check.

## Changed paths owned by this subtask

Parent-owned request foundation, model-manage migration, manifests, generated error artifacts, and voice test are excluded below. The deleted source-only memberTableToggleErrorToast.test.ts is replaced with .test.tsx.

- src/frontend/platform/eslint-suppressions.json
- src/frontend/platform/public/locales/en-US/bs.json
- src/frontend/platform/public/locales/en-US/knowledge.json
- src/frontend/platform/public/locales/ja/bs.json
- src/frontend/platform/public/locales/ja/knowledge.json
- src/frontend/platform/public/locales/zh-Hans/bs.json
- src/frontend/platform/public/locales/zh-Hans/knowledge.json
- src/frontend/platform/src/components/LinSight/skill/SkillManagement.tsx
- src/frontend/platform/src/components/VariablesComponent/index.tsx
- src/frontend/platform/src/components/bs-comp/apiComponent/ChatLink.tsx
- src/frontend/platform/src/components/bs-comp/cardComponent/index.tsx
- src/frontend/platform/src/components/bs-comp/department/TreeDepartmentSelect.tsx
- src/frontend/platform/src/components/bs-comp/department/useLazyDepartmentTree.ts
- src/frontend/platform/src/components/bs-comp/selectComponent/DepartmentUsersSelect.tsx
- src/frontend/platform/src/components/bs-comp/selectComponent/LabelSelect.tsx
- src/frontend/platform/src/components/bs-comp/selectComponent/knowledge.tsx
- src/frontend/platform/src/components/bs-ui/alertDialog/useConfirm.test.tsx
- src/frontend/platform/src/components/bs-ui/alertDialog/useConfirm.tsx
- src/frontend/platform/src/components/bs-ui/input/textInput.test.tsx
- src/frontend/platform/src/components/bs-ui/input/textInput.tsx
- src/frontend/platform/src/contexts/tabsContext.tsx
- src/frontend/platform/src/contexts/userContext.tsx
- src/frontend/platform/src/controllers/API/businessWrappers.errors.test.ts
- src/frontend/platform/src/controllers/API/finetune.ts
- src/frontend/platform/src/controllers/API/flow.ts
- src/frontend/platform/src/controllers/API/knowledgeSpace.ts
- src/frontend/platform/src/layout/MainLayout.tsx
- src/frontend/platform/src/modals/codeAreaModal/index.tsx
- src/frontend/platform/src/pages/BuildPage/CardSelectVersion.tsx
- src/frontend/platform/src/pages/BuildPage/CreateApp.tsx
- src/frontend/platform/src/pages/BuildPage/CreateTemp.tsx
- src/frontend/platform/src/pages/BuildPage/appTemps.tsx
- src/frontend/platform/src/pages/BuildPage/apps.tsx
- src/frontend/platform/src/pages/BuildPage/assistant/CreateAssistant.tsx
- src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/index.tsx
- src/frontend/platform/src/pages/BuildPage/bench/AppCenter.tsx
- src/frontend/platform/src/pages/BuildPage/bench/DailyChatConfig.tsx
- src/frontend/platform/src/pages/BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog.tsx
- src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpace.tsx
- src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpaceSensitivePolicy.tsx
- src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpaceTagLibrarySection.tsx
- src/frontend/platform/src/pages/BuildPage/bench/Preview.tsx
- src/frontend/platform/src/pages/BuildPage/bench/Subscribe.tsx
- src/frontend/platform/src/pages/BuildPage/bench/SubscriptionSensitivePolicy.tsx
- src/frontend/platform/src/pages/BuildPage/bench/WorkbenchSensitivePolicy.tsx
- src/frontend/platform/src/pages/BuildPage/bench/index.tsx
- src/frontend/platform/src/pages/BuildPage/flow/FlowNode/RunTest.tsx
- src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem.tsx
- src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/ReportWordEdit.tsx
- src/frontend/platform/src/pages/BuildPage/flow/Header.tsx
- src/frontend/platform/src/pages/BuildPage/flow/index.tsx
- src/frontend/platform/src/pages/BuildPage/tools/EditMcp.tsx
- src/frontend/platform/src/pages/BuildPage/tools/EditTool.tsx
- src/frontend/platform/src/pages/BuildPage/tools/index.tsx
- src/frontend/platform/src/pages/Dashboard/components/charts/ChartContainer.test.tsx
- src/frontend/platform/src/pages/Dashboard/components/charts/ChartContainer.tsx
- src/frontend/platform/src/pages/Dashboard/components/config/EnumMultiSelect.tsx
- src/frontend/platform/src/pages/Dashboard/components/dashboard/DashboardSidebar.tsx
- src/frontend/platform/src/pages/Dashboard/components/editor/EditorCanvas.tsx
- src/frontend/platform/src/pages/Dashboard/components/editor/EditorHeader.errors.test.tsx
- src/frontend/platform/src/pages/Dashboard/components/editor/EditorHeader.tsx
- src/frontend/platform/src/pages/Dashboard/hook.ts
- src/frontend/platform/src/pages/Dashboard/index.tsx
- src/frontend/platform/src/pages/DataSetPage/CreateDataSet.test.tsx
- src/frontend/platform/src/pages/DataSetPage/CreateDataSet.tsx
- src/frontend/platform/src/pages/DataSetPage/index.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/AddMemberDialog.test.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/AddMemberDialog.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/CreateDepartmentDialog.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/CreateLocalMemberDialog.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/DepartmentSettings.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/DepartmentSettingsView.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/DepartmentTrafficControl.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/MemberTable.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/MountTenantDialog.tsx
- src/frontend/platform/src/pages/DepartmentPage/components/OrganizationMemberEditDialog.tsx
- src/frontend/platform/src/pages/DepartmentPage/index.tsx
- src/frontend/platform/src/pages/EvaluationPage/EvaluationCreate.test.tsx
- src/frontend/platform/src/pages/EvaluationPage/EvaluationCreate.tsx
- src/frontend/platform/src/pages/EvaluationPage/index.test.tsx
- src/frontend/platform/src/pages/EvaluationPage/index.tsx
- src/frontend/platform/src/pages/KnowledgePage/AdjustFilesUpload.tsx
- src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx
- src/frontend/platform/src/pages/KnowledgePage/KnowledgeQa.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/DepartmentSpaceDialog.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/EditQa.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/FileUploadParagraphs.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/FileUploadStep1.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/FileUploadStep4.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/Header.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/ImportQa.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeLibraryDialog.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/ParagraphEdit.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/Paragraphs.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/PreviewResult.test.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/PreviewResult.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/QaLibraryDialog.tsx
- src/frontend/platform/src/pages/KnowledgePage/components/tags/KnowledgeTagSelect.tsx
- src/frontend/platform/src/pages/KnowledgePage/detail.tsx
- src/frontend/platform/src/pages/KnowledgePage/filesUpload.tsx
- src/frontend/platform/src/pages/KnowledgePage/qas.tsx
- src/frontend/platform/src/pages/LabelPage/AddSimilarQuestions.tsx
- src/frontend/platform/src/pages/LabelPage/SaveQaLibForm.tsx
- src/frontend/platform/src/pages/LabelPage/annotationForms.test.tsx
- src/frontend/platform/src/pages/LabelPage/index.test.tsx
- src/frontend/platform/src/pages/LabelPage/index.tsx
- src/frontend/platform/src/pages/LabelPage/taskAppChats.test.tsx
- src/frontend/platform/src/pages/LabelPage/taskAppChats.tsx
- src/frontend/platform/src/pages/LogPage/useAppLog/appChatDetail.tsx
- src/frontend/platform/src/pages/LoginPage/TenantSelect.tsx
- src/frontend/platform/src/pages/LoginPage/UserPwdModal.tsx
- src/frontend/platform/src/pages/LoginPage/login.tsx
- src/frontend/platform/src/pages/LoginPage/resetPwd.tsx
- src/frontend/platform/src/pages/MenuPermissionPlaceholder.tsx
- src/frontend/platform/src/pages/ModelPage/components/CreateTask.tsx
- src/frontend/platform/src/pages/ModelPage/components/FinetuneDetail.tsx
- src/frontend/platform/src/pages/ModelPage/components/RTConfig.tsx
- src/frontend/platform/src/pages/ModelPage/finetune.tsx
- src/frontend/platform/src/pages/SystemPage/components/Config.tsx
- src/frontend/platform/src/pages/SystemPage/components/CreateUser.tsx
- src/frontend/platform/src/pages/SystemPage/components/Departments.tsx
- src/frontend/platform/src/pages/SystemPage/components/OrgSync/index.tsx
- src/frontend/platform/src/pages/SystemPage/components/PersonalToken/index.tsx
- src/frontend/platform/src/pages/SystemPage/components/Roles.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ApiKeysTab.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/KeyIssueDialog.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/OverviewTab.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ResourceGrantDialog.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ResourceGrantsTab.tsx
- src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/index.tsx
- src/frontend/platform/src/pages/SystemPage/components/UserGroup.tsx
- src/frontend/platform/src/pages/SystemPage/components/UserRoleModal.tsx
- src/frontend/platform/src/pages/SystemPage/components/Users.tsx
- src/frontend/platform/src/pages/SystemPage/theme/BrandAssetUpload.tsx
- src/frontend/platform/src/pages/SystemPage/theme/BrandCustomization.tsx
- src/frontend/platform/src/pages/SystemPage/theme/WorkbenchThemeSettings.tsx
- src/frontend/platform/src/pages/TenantPage/components/CreateTenantDialog.tsx
- src/frontend/platform/src/pages/TenantPage/components/TenantQuotaDialog.tsx
- src/frontend/platform/src/pages/TenantPage/components/TenantUserDialog.tsx
- src/frontend/platform/src/pages/TenantPage/index.tsx
- src/frontend/platform/src/pages/TenantPage/tenantModule.test.tsx
- src/frontend/platform/src/pages/publicEntries.test.tsx
- src/frontend/platform/src/test/departmentKnowledgeSpaceDialogs.test.tsx
- src/frontend/platform/src/test/departmentPageRefresh.test.tsx
- src/frontend/platform/src/test/departmentSettingsPayload.test.tsx
- src/frontend/platform/src/test/departmentUsersSelectScope.test.tsx
- src/frontend/platform/src/test/knowledgeSpaceGrantSubjects.test.tsx
- src/frontend/platform/src/test/mainLayoutSystemNavChildAdmin.test.tsx
- src/frontend/platform/src/test/mainLayoutWorkspaceMenu.test.tsx
- src/frontend/platform/src/test/memberTableToggleErrorToast.test.ts
- src/frontend/platform/src/test/memberTableToggleErrorToast.test.tsx
- src/frontend/platform/src/test/personalTokenSettingsInteraction.test.tsx
- src/frontend/platform/src/test/serviceAccountResourceGrantMutations.test.tsx
- src/frontend/platform/src/test/serviceAccountResourceGrants.test.tsx
- src/frontend/platform/src/test/systemDepartmentsArchivedDelete.test.tsx
- src/frontend/platform/src/test/toolLazyPermissions.test.tsx
