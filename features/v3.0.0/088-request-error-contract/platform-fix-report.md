# T003 fix round 1 report

Status: **DONE_WITH_CONCERNS** — assigned functional fixes and focused acceptance regressions pass; the touched legacy API index retains preexisting lint baseline drift.

## Verified live chains and repairs

1. **H1 / approval and skill notices.** `/approval` renders the controller and view. All 12 generic request catches in `useApprovalController.ts`, and the exception retry/cancel catches in `useApprovalExceptions.ts`, now delegate to `showApiError` with the original object. Local validation and successful-operation messages remain owned locally. `SkillDetailSheet.tsx` asset clicks likewise use the deduplicating reporter; asset reads keep the existing default request policy.
2. **H2 / approval load ownership.** Mount catches its rejected initial load; tab refresh, scenario mouse/keyboard selection, and flow-selector callbacks now have UI terminals. Reusable loaders still reject. Page load/selection retains the original `loadError`; the shared Alert displays failure with a retry action and clears only after success. Canceled/global failures do not display that inline alert. Flow loading fetches nodes before clearing drafts/selection, and confirmation-based flow switching returns the pending request and changes editor state only after success. Exception timeline failure reports once, clears loading in finally and collapses instead of showing an empty successful timeline.
3. **H3 / knowledge details → workflow creation.** Sole production hook consumer is `FileUploadStep4.tsx`. Manual detail requests retain rejection and previous successful details; initial failure is exposed as the original error state. The quick-start action retries/awaits details before loading the default model or generating/creating a workflow. A successful but missing-name response is an invalid-response error, rather than a workflow containing a blank knowledge-base name. The action's existing UI terminal handles the original request failure.
4. **H4 / finetune inline rename.** The actual FinetuneDetail caller passes its rejecting rename Promise directly to EditLabel. EditLabel awaits success before closing, preserves the input on failure, reports once and resets its pending lock in finally. Enter/blur cannot dispatch duplicate pending saves. No ModelConfig, WorkbenchModel, KnowledgeModel PromptDialog or parent request-layer files were edited.
5. **H5 / preview callbacks.** Both wrapped preview-create and preview-status request catches deliver `onEvent('error', originalError)` without replacement or object spreading. ApiError identity therefore retains status_code/data/response/cause/presentation. Existing domain-task-status error envelopes and processing/completed/closed/canceled protocol remain unchanged. PreviewResult still resolves the original structured ASR failure into existing specialized inline copy without adding a second notice. Canceled requests remain silent.

## Changed paths

Production (platform `src/`):

- `pages/ApprovalPage/{useApprovalController.ts,useApprovalExceptions.ts,ApprovalPageView.tsx,FlowManagementPanel.tsx}`
- `components/LinSight/skill/SkillDetailSheet.tsx`
- `controllers/hooks/knowledge.ts`
- `pages/KnowledgePage/components/FileUploadStep4.tsx`
- `components/bs-ui/editLabel/index.tsx`
- `pages/ModelPage/components/FinetuneDetail.tsx`
- `controllers/API/index.ts` (only two cancellation checks and two original-error callback lines)

Added focused tests alongside EditLabel, SkillDetailSheet, knowledge hook, preview API, approval controller, FileUploadStep4 and FinetuneDetail. Extended existing PreviewResult test with its specialized original-error display regression.

## Verification evidence

Initial RED: 3 files / 4 failures in `/private/tmp/f088-platform-fix-round-1-red.log`, followed by 3 files / 4 failures plus the expected initial-load unhandled rejection in `/private/tmp/f088-platform-fix-round-1-ui-red.log`. These reproduced defects rather than merely asserting implementation details.

Final command from `src/frontend/platform`:

```sh
pnpm exec vitest run src/components/bs-ui/editLabel/index.test.tsx src/controllers/hooks/knowledge.errors.test.tsx src/controllers/API/previewFileSplit.errors.test.ts src/pages/ApprovalPage/useApprovalController.errors.test.tsx src/components/LinSight/skill/SkillDetailSheet.errors.test.tsx src/pages/KnowledgePage/components/FileUploadStep4.errors.test.tsx src/pages/ModelPage/components/FinetuneDetail.errors.test.tsx src/pages/KnowledgePage/components/PreviewResult.test.tsx src/test/approvalPage.test.tsx src/pages/ModelPage/components/FinetuneHead.test.tsx
```

**10 files / 30 tests pass, no unhandled errors**, final duration 5.28s. Log: `/private/tmp/f088-platform-fix-round-1-focused.log`. Covers actual finetune parent/child Promise wiring, retained draft/retry/pending lock, full hook failure state/refresh rejection, blocked dependent workflow creation, approval initial failure/retry and mutation notice delegation, preview original identity/cause on both phases, cancellation, specialized preview inline copy, and 15 existing approval-page behaviors.

Scoped ESLint across all 18 production/test paths produced **63 no-explicit-any errors solely in `controllers/API/index.ts`**. All other changed paths pass with existing suppressions (`--pass-on-unpruned-suppressions`; `/private/tmp/f088-platform-fix-round-1-lint-scoped.log` is empty). Full scoped output: `/private/tmp/f088-platform-fix-round-1-lint.log`. HEAD-source stdin lint independently also reports **63 no-explicit-any** diagnostics (`/private/tmp/f088-platform-fix-round-1-api-head-lint.log`); stdin does not apply the existing file suppressions equivalently, so its additional legacy diagnostics are not claimed as an equivalent full count. Current suppression allows 58; both HEAD and current source contain the identical 67 any-bearing lines. The four-line production diff introduces no any and no new Chinese copy. No suppression file was manually edited or widened in this round.

Scoped `git diff --check` passes. Production HOC scan still finds only its definition in `controllers/request.ts`; this is supplementary evidence, not the completion criterion for these live chains. No full suite/typecheck rerun, as instructed; prior full-suite/typecheck concerns remain in task-1-report.md and are not reclassified as verified here.

## Remaining concerns / handoff

- Parent should account for the existing API-index explicit-any/suppression drift in final quality gates; broad cleanup of that 1,000+ line file was deliberately outside this fix round.
- Parent owns review H4's prompt branch, H6, compatibility-matrix M1 and AGENTS example M2; this report claims only the assigned subscopes above.
- All edits stayed in the designated shared worktree; no global Git writes, commits or subagents. Ready for independent re-review.

## H2 atomic scenario-switch follow-up

Parent's final review identified a remaining H2 state consistency defect: the route and flow readers each committed state before `Promise.all` completed. With A selected, switching to B could display B's successful half alongside A after the other half failed.

Changed only `useApprovalController.ts` and its focused errors test. Route/flow loaders now return data without state writes; the flow reader includes its node read. Scenario selection commits route list, flow list, node list, selection and draft reset together only after both readers succeed. Page refresh likewise completes all required reads before committing page/scenario data. Existing route mutation refreshes explicitly commit the returned routes, and flow mutation refreshes use the shared successful-flow commit helper, preserving their prior behavior.

Added three regressions: from fully loaded A with an active dirty node draft, fail B's routes, flows or nodes while the other reader succeeds. Each case preserves all A selections/data/drafts and the original failure; a subsequent successful B retry commits all B data and clears the draft/error together. Initial RED: 3 new failures / 2 existing passes, `/private/tmp/f088-platform-h2-atomic-red.log`.

Final focused command:

```sh
pnpm exec vitest run src/pages/ApprovalPage/useApprovalController.errors.test.tsx src/test/approvalPage.test.tsx
```

**2 files / 20 tests pass**, no unhandled errors; `/private/tmp/f088-platform-h2-atomic-green.log`. ESLint on the two changed paths passes with the existing baseline (`--pass-on-unpruned-suppressions`), `/private/tmp/f088-platform-h2-atomic-lint.log` empty. Scoped diff whitespace check passes. No other product source, full-suite run or parent-owned Workbench changes in this follow-up. Follow-up status: **DONE**; earlier API-index baseline concern remains unchanged.
