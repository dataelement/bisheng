# F088 platform task review

**Feature:** F088 request-error-contract
**Review scope:** T001 common error model; T002 platform request compatibility; T003 platform consumers, including live consumers outside the former HOC search results.
**Baseline:** `bc6ca25ba`; actual implementation is the uncommitted worktree. Reviewed task-1-brief.md, task-1-report.md, task-1-review.diff and current sources. Parent may subsequently repair findings; line references describe the reviewed snapshot.
**Review date:** 2026-10-22

## Verdicts

- **Spec compliance: NEEDS_FIX.** Common model and the inspected T002 request branches implement the intended rejection/evidence contract. T003 does not yet meet AC-05, AC-07, AC-11, AC-12, AC-20 and therefore AC-21. HOC removal is complete but is not equivalent to completing all live consumers.
- **Code quality: NEEDS_FIX.** Remaining Promise ownership errors, discarded failure evidence, premature editor close and duplicate notifications need repair. This is not a claim that the whole platform migration should be redone.

## Seven-dimension summary

| Dimension | High | Medium | Low | Status |
|---|---:|---:|---:|---|
| Boundary conditions / UI error states | 5 | 0 | 0 | NEEDS_FIX |
| Permission and authentication | 0 | 0 | 0 | No concrete defect in inspected branches; full runtime matrix not verified |
| Concurrency safety | 1 | 0 | 0 | NEEDS_FIX |
| Information leakage | 0 | 0 | 0 | No introduced exposure identified; old full-error console logging remains |
| Test coverage | 0 | 1 | 0 | Partial; focused reproductions found uncovered cases |
| Code style / ownership | 0 | 0 | 0 | No independent blocking style issue |
| Documentation sync | 0 | 1 | 0 | Update final implementation/audit claims after fixes |

## HIGH findings

### H1 — Old custom notifications now duplicate the request-layer notification

**Paths:** `src/frontend/platform/src/pages/ApprovalPage/useApprovalController.ts:183-184`; `src/frontend/platform/src/components/LinSight/skill/SkillDetailSheet.tsx:115-119`; source of the new first notice: `src/frontend/platform/src/controllers/request.ts:227` (ordinary business-error branch; exact current line may move).

**Trigger:** In Approval administration, fail the scenario-create request with HTTP 200 + a non-global business error. The request interceptor presents the ApiError, then the controller unconditionally calls notification.open again. The same pattern remains throughout the controller's create/update/delete/save catches. Skill detail has the same defect on loading an additional bundle file: `skillApi.getSkillFile` at `controllers/API/linsight.ts:75` uses the default notification policy, then SkillDetailSheet displays its own error again. Global redirects or cancellations are also not respected by these custom catch blocks.

**Evidence:** A scratch regression using the **real Axios adapter and real Approval controller** returned `{status_code:29999,status_message:'Denied',data:{reason:'test'}}` for create; exactly **two** notification calls occurred. Approval is live at `routes/index.tsx:99`; SkillManagement renders SkillDetailSheet at line 279.

**Required fix:** Establish one notice owner for these actual consumers. Generic catches should use showApiError; custom localized/domain feedback should opt out of the ordinary request notice explicitly and respect canceled/global/already-presented errors. Audit adjacent custom catches, not just former HOC sites.

**AC:** AC-07, AC-10, AC-20, AC-21. The custom catches are old; **duplicate default notices are newly introduced by this change**.

### H2 — Approval initial load and scenario-selection promises have no UI error terminal

**Path:** `src/frontend/platform/src/pages/ApprovalPage/useApprovalController.ts:168-170` (also `selectScenario` at 147-149 and its view callback).

**Trigger:** Enter `/approval` and fail any scenario/preset/exception initial request. The effect fires `void initialLoad.current()` without catch, so loadPage rejects into an unhandled Promise. Its arrays remain initial empty data and no load failure state is stored. Scenario selection similarly returns an async load that the UI must terminate.

**Evidence:** Traced actual route → ApprovalPage → useApprovalController → loadPage → wrapped approval API. Static proof; did not deliberately introduce an unhandled error into the scratch test runner.

**Required fix:** Catch at the effect/event boundary, preserve a failure state and retry path appropriate to the existing page, and keep reusable loading functions rejecting. A toast by the interceptor does not consume the Promise.

**AC:** AC-12, AC-20, AC-21. **Preexisting live omission explicitly included in the F088 whole-consumer requirement**; no new spec is needed.

### H3 — Knowledge detail hook still resolves an empty result after a failed request

**Path:** `src/frontend/platform/src/controllers/hooks/knowledge.ts:14-22`.

**Trigger:** The details request fails during upload completion or a manual refresh. The hook logs the error, sets details to `[]`, and resolves undefined. The caller cannot distinguish failure or retain the original error. The live consumer `pages/KnowledgePage/components/FileUploadStep4.tsx:189-194` then permits “build a knowledge QA app” using `details[0]?.name || ''`, instead of preserving a failed prerequisite.

**Evidence:** Scratch hook regression first loaded `[{id:1,name:'Knowledge'}]`, then rejected a refresh with a structured failure. The returned Promise resolved undefined and prior details became `[]`. Sole production caller verified at FileUploadStep4; this is not dead code.

**Required fix:** Keep previous details, expose the full failure, and handle it at the upload-completion UI; block or retry the dependent create action until the required details are available. Do not replace this with another generic successful-empty fallback.

**AC:** AC-03, AC-05, AC-12, AC-20, AC-21. **Preexisting live omission**, newly audited migration scope.

### H4 — Failed inline/prompt edits still close their editor

**Paths:** `src/frontend/platform/src/pages/ModelPage/components/FinetuneDetail.tsx:213` with `components/bs-ui/editLabel/index.tsx:34-35`; independently `src/frontend/platform/src/pages/ModelPage/manage/tabs/KnowledgeModel.tsx:107-113` with `handleSavePrompt` at 253-260.

**Trigger A:** Rename a fine-tuned model and reject the rename request. EditLabel closes before calling its callback. The newly added handleUiRequest callback returns void, so this control cannot await success. Reopening uses the old server name and loses the entered draft.

**Trigger B:** Edit the knowledge summary or auto-tag prompt and fail its save. PromptDialog clears its dirty flag, calls onSave, closes and changes the parent form immediately. handleSavePrompt itself returns void and catches the failure, so success-only UI continuation cannot be enforced there either.

**Evidence:** Scratch regression against the real EditLabel + actual handleUiRequest reproduced the closed editor and lost draft; live fine-tune route is `routes/index.tsx:95` → finetune.tsx:103. PromptDialog call sites verified at KnowledgeModel's two prompt configuration buttons; static proof.

**Required fix:** Return the request Promise through each save callback, await it in the actual editor boundary, keep editor/draft open on rejection, and only clear dirty state/close/change accepted data on fulfillment. The new workflow TextInput recovery does not fix these other controls.

**AC:** AC-11, AC-20, AC-21. **Preexisting UI defects in chains changed by this migration**; no additional product scope required.

### H5 — Preview's wrapped HTTP failures still lose all structured evidence

**Path:** `src/frontend/platform/src/controllers/API/index.ts:660-667` and `696-703`; `emitError` at 591-596.

**Trigger:** The document-preview creation or status **HTTP request** fails. The wrapper replaces the actual ApiError with `{message:'文档解析失败'}`; emitError then assigns fallback numeric code 10952. HTTP status, actual status_code, data, response and cause are discarded before reaching `pages/KnowledgePage/components/PreviewResult.tsx:88`.

**Evidence:** Verified current implementation uses the wrapped `axios.post('/api/v1/knowledge/preview')` and `axios.get('/api/v1/knowledge/preview/status')`. The old comment mentioning fetch/SSE does not describe current code. This is within F088's unified HTTP scope, not the excluded native-fetch/SSE transport. No runtime repro was needed for the explicit replacement.

**Required fix:** Preserve the existing callback error channel if desired, but carry the original ApiError/evidence with it. Do not synthesize 10952 as the actual transport/business cause of an HTTP request that returned another code. Keep legitimate domain task-status errors distinct from request failures.

**AC:** AC-03, AC-05, AC-19, AC-21. **Preexisting live evidence-loss omission**; preserving a callback channel is a valid compatibility choice, discarding request evidence is not a named domain recovery.

### H6 — Model confirmations detach their Promise, defeating the new pending lock

**Paths:** `src/frontend/platform/src/pages/ModelPage/manage/ModelConfig.tsx:219-225`; `src/frontend/platform/src/pages/ModelPage/manage/tabs/WorkbenchModel.tsx:184-185`; boundary `components/bs-ui/alertDialog/useConfirm.tsx:45-55`.

**Trigger:** Confirm provider deletion or embedding-model configuration save while the request is slow. onOk starts `void ...then(...).catch(...)` and returns undefined. ConfirmWrapper therefore finishes its Promise immediately and re-enables confirm while the mutation is still running. Repeated confirmation dispatches another delete/save. Workbench's background saveload disables its underlying save button, not the confirmation's OK button.

**Evidence:** Traced returned values from both callbacks to ConfirmWrapper's await/settlement implementation. Parent was notified and intends to repair these parent-owned files.

**Required fix:** Return the mutation chain to bsConfirm and let that UI boundary own the catch/lock. Keep next only after actual successful completion. Check other async onOk callbacks for the same detached pattern.

**AC:** AC-11, AC-20, AC-21; relevant concurrency safety. Existing detached calls were not migrated to the newly introduced confirmation contract.

## MEDIUM findings / verification gaps

### M1 — Required platform compatibility matrix is not fully evidenced

The task report's tests cover many valuable chains, and the existing platform request tests exercise ordinary business/HTTP errors, silent, cancellation, binary success and one HTTP401 binary kicked-session case. The inspected platform tests do not provide the planned full matrix for password expiration 10601, legacy 11010, concurrent license throttle/kicked-session ordering, showError=false versus global actions, and the actual consumers above. Do not label all T002 ACs or the whole feature validated solely from the majority of passing tests. Add the relevant focused matrix and these failed UI chains; complete T006 E2E independently. This review did not run browsers/middleware or certify auth with real non-admin accounts.

### M2 — Final docs must reflect implemented consumer boundaries

`src/frontend/platform/AGENTS.md` still recommends captureAndAlertRequestErrorHoc for new component code. Update that verified example to the actual rejection/UI-terminal contract. The migration inventory/report's blanket claim that UI events/effects consume rejection and callbacks retain full evidence is contradicted by H1-H6; update completion claims after repair. Design's successful-write/failed-refresh distinction also needs an explicit checked consumer test before claiming that matrix completed.

## Positive findings and limits

- Common ApiError retains the original cause and response references and distinguishes HTTP status from business code. Decoded binary error evidence is passed independently; response/data are not overwritten. Transport string code remains available. normalizeApiError is idempotent and presentation state supports deduplication.
- Platform ordinary failures reject even after toast; silent preserves the older explicit exception ordering; canceled failures are skipped by showApiError. HTTP401 preserves the session-kick confirmation before generic token-clearing. No concrete new auth/permission regression found in inspected logic, but M1 remains.
- Production HOC callers are removed. Dashboard save→publish and save→leave correctly await mutateAsync and use a UI rejection terminal. Chart error remains React Query error and uses failure copy. The production QueryClient keeps offlineFirst, retry:0 and existing keys; disabled chart loading keeps isInitialLoading.
- Workbench query now rejects instead of caching null, disables new business-error retries, and defers notification to final onError for its explicitly retried query. Cached data survives failed refresh. This is the right direction; it does not repair detached confirmation callbacks or other unrelated UI editors.
- Named license/permission recoveries and callback-driven upload ownership should not be mechanically deleted. H5 asks to preserve evidence inside the callback contract, not to replace the entire polling API.
- Source-only review included the supplied diff, request foundation, query/config chains and sampled migrated page chains plus live paths identified above. This is **not exhaustive runtime certification of every changed file**. No new edits to product source or repository-wide Git writes were made.

## Independent focused reproduction

Scratch files: `/private/tmp/f088-platform-review/review.test.tsx` and `vitest.config.ts` (outside the repository).

Command from platform:
`pnpm exec vitest run /private/tmp/f088-platform-review/review.test.tsx --config /private/tmp/f088-platform-review/vitest.config.ts --maxWorkers=1 --minWorkers=1`

Result: **1 file / 3 tests passed in 916 ms**, deliberately asserting the current defects: duplicate real-adapter Approval notices, failed knowledge refresh resolving empty, and failed inline rename losing its draft. These are defect reproductions, not green acceptance tests.

An initial scratch config accidentally merged include arrays and began selecting repository tests. It was interrupted immediately after discovery, and the config was corrected to replace include. That aborted run is not used as completion evidence; it also encountered a sandbox write denial for the dead-i18n-report artifact. The final focused run above completed cleanly. The implementation report's full-suite results were read rather than rerun to completion.

## Overall: NEEDS_FIX

## Controller follow-up received after report

Parent reports H6's two confirmation Promise returns and H4's KnowledgeModel PromptDialog await/success-only close have now been repaired, with a new prompt regression. They are **reported fixed by controller, not independently re-reviewed here**. H4's Finetune/EditLabel branch and H1-H3/H5 remain handed back to the platform implementer pending parent verification. Parent is also adding stale-detail guards. This reviewer stops expansion here; original findings and reproduce scripts remain for the final coordinator audit.
