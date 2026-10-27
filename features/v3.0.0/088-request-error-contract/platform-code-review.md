# F088 platform fix-closure review

**Scope:** Independent re-review of previous H1–H6 and M1–M2, plus the explicitly assigned round-2 paths documented below, against current uncommitted worktree based on `bc6ca25ba`. This is a scoped closure review, not a fresh exhaustive review or T006 merge approval.

## Verdicts

**Spec compliance: PASS for the reviewed H1–H6/M1–M2 and assigned round-2 closure scope.** The previous blocking findings are repaired. This is not a statement that every F088 AC or T006 gate has been executed.

**Code quality: PASS within this re-review scope.** No remaining HIGH or MEDIUM defect was found in the repaired chains. Whole-feature lint/typecheck/build/E2E status remains with the parent task.

## Seven dimensions

| Dimension | Result within this re-review |
|---|---|
| Boundary conditions | PASS — H1–H5 fixed; failed scenario subrequests preserve the original scenario and draft; successful writes are separated from failed refreshes |
| Permission/authentication | Required compatibility categories added to requestCompatibilityMatrix: 10601, 11010, 11001 throttle, forced routing versus silent, session kick versus subsequent 401, cancellation |
| Concurrency | H6 callbacks return their mutation Promise; confirmation pending lifecycle remains owned by the dialog; EditLabel and PromptDialog prevent repeated pending submit |
| Information leakage | No additional sensitive-data behavior introduced by the reviewed repairs; full error remains local evidence, not a newly added remote diagnostic sink |
| Test coverage | PASS for listed findings — independently executed 14 focused files / 47 tests successfully; runtime E2E remains outside this review |
| Code style | Changes are scoped to existing callback/event/error contracts; no new library or broad refactor; legacy API-index lint baseline remains separately disclosed |
| Documentation | AGENTS request example and confirmation Promise rule now match implementation, with verification references; design/tasks final status sync remains assigned to parent |

## Closure evidence

- **H1:** Approval generic catches and SkillDetailSheet asset error now use showApiError with the original object. The request layer presentation marker owns deduplication and cancellation/global exclusions. Custom success and local-validation messages remain separate.
- **H2:** Initial load, tab reload, scenario keyboard/mouse callbacks and flow selector have explicit Promise terminals. loadError is preserved with retry UI. Flow selection fetches nodes before clearing editor state. Re-review caught partial scenario state publication; the final fix makes both read loaders return data without writing state. selectScenario and loadPage commit only after all required reads succeed. Routes, flows or nodes failure retains the complete prior scenario, selected flow, nodes and dirty draft; all three failures plus successful retry are covered in the final passing regression.
- **H3:** useKnowledgeDetails keeps successful details, exposes initial error and lets manual fetch reject the same failure. FileUploadStep4 awaits/retries details before reading models or creating the workflow; missing required knowledge name is an invalid-response failure instead of an empty-name success.
- **H4:** FinetuneDetail returns its rename Promise directly to EditLabel. EditLabel waits before closing, keeps the draft and resets pending on rejection. Knowledge PromptDialog similarly awaits its rejecting callback, only then changes the accepted value and closes. Both have failure/retry behavior tests.
- **H5:** Preview create and poll catches now pass the exact original failure to the callback; no fabricated 10952 replaces transport/business evidence. Cancellation does not enter the ordinary error event. Existing task-status callback protocol stays intact; PreviewResult still shows specialized ASR failure copy without an additional notice.
- **H6:** ModelConfig deletion and Workbench embedding confirmation both return the Promise to bsConfirm; next is attached to fulfillment, so the confirmation's pending lock covers the request.
- **M1:** Six request compatibility tests cover the categories identified in the prior review. This closes the missing unit/adapter matrix; it does not substitute for live E2E.
- **M2:** Platform AGENTS example now uses rejecting requests plus an explicit UI terminal, documents confirmation Promise ownership, and names the verification tests. Parent is responsible for final design/tasks/inventory updates, so transitional status text is not raised as a new functional defect.

## Verification and boundaries

This reviewer changed no product source and performed no repository-wide Git writes. Exactly one focused test run was executed for this closure review; no full suite was rerun.

Command, from `src/frontend/platform`:

```sh
pnpm exec vitest run src/components/bs-ui/editLabel/index.test.tsx src/controllers/hooks/knowledge.errors.test.tsx src/controllers/API/previewFileSplit.errors.test.ts src/pages/ApprovalPage/useApprovalController.errors.test.tsx src/components/LinSight/skill/SkillDetailSheet.errors.test.tsx src/pages/KnowledgePage/components/FileUploadStep4.errors.test.tsx src/pages/ModelPage/components/FinetuneDetail.errors.test.tsx src/pages/KnowledgePage/components/PreviewResult.test.tsx src/test/approvalPage.test.tsx src/pages/ModelPage/manage/tabs/KnowledgeModel.errors.test.tsx src/pages/ModelPage/manage/tabs/WorkbenchModel.commit.test.tsx src/controllers/requestCompatibilityMatrix.test.ts src/controllers/requestErrors.test.ts src/components/bs-ui/alertDialog/useConfirm.test.tsx --maxWorkers=1 --minWorkers=1
```

**Result:** 14 files / 47 tests passed, process exit 0, duration 12.19 seconds. No unhandled-error summary. Log: `/private/tmp/f088-platform-review-final.log`.

**Additional completed M2 design-contract check:** WorkbenchModel now acknowledges a completed write and updates the accepted-form reference before separately attempting refetch. Refresh rejection presents the refresh error and resolves the completed write path, allowing the confirmation to close; it preserves the current form/cache and does not invoke another write. WorkbenchModel.commit.test.tsx exercises the actual component with the production QueryClient factory and verifies one write, success feedback, separate refresh error, enabled controls and retained cached configuration. The code retains the original rejection for a failed write; it does not convert that failure into success.

Prior baseline concerns remain disclosed rather than certified as fixed: two stale knowledgeSpaceGrantSubjects assertions, untouched clientVoiceDraft strict typecheck parameter error, and legacy frontend lint/suppression drift (including API/index.ts explicit-any diagnostics unchanged by its four-line functional repair). See task-1-report and fix-round-1-report for exact original command evidence. The status of final quality gates belongs to the coordinating task.

No browser, middleware, real-account permission or deployment E2E was executed here. Parent's final E2E checklist/execution and design/tasks synchronization remain required for whole-feature acceptance. This review can clear its listed defects without claiming those separate gates passed.

## Overall: PASS (scoped fix-closure review)

H1–H6 are closed; M1's adapter/unit matrix and M2's verified AGENTS example are closed. Remaining whole-feature documentation synchronization, quality gates and E2E are explicit coordinator tasks, not silently claimed complete here.


## Round 2 final scoped review — 2026-10-22

**Spec compliance: PASS. Code quality: PASS, within the explicitly reviewed paths.** No remaining blocking finding in these repair chains. Previous H1–H6/M1–M2 conclusions stand. This addition does not certify all consumers, all feature ACs or T006 merge gates; no unrelated feature search or full test run was performed.

### Reviewed behavior and evidence

- **BuildPage knowledge/tools pickers:** `OrgKbConfig.tsx` and `ToolsConfig.tsx` now keep request failures separate from successful empty results, delegate the original object to canonical presentation, retain previous successful data, and provide retry. Canceled/global failures do not become new ordinary inline errors. `ToolSelectorContainer.tsx` and `ToolSelector.tsx` pass the optional loading/error slot through and suppress empty-result copy while the slot is present. Existing selected items and category cache behavior are preserved. `pickerErrors.test.tsx` exercises initial failure/retry and knowledge search failure with prior rows.
- **QA:** `qas.tsx` sends original generic failures to `showApiError`; the individual status failure retains its existing rollback, and named batch partial-result summaries remain. The test exercises rollback and the specialized batch warning. This review does not claim to redesign batch accounting or older selection behavior.
- **Workflow attachments:** `ChatFiles.tsx` delegates canonical canceled/global/already-presented upload errors and removes failed attachments. During this re-review, the original cleanup still decremented pending twice: its catch called removal (which decremented) and then decremented again. With A rejected and B pending, this emitted B with an undefined path before B finished. This was a pre-existing defect in the same assigned cleanup chain, not a new spec requirement. It was reported and fixed before this verdict: catch now removes once; removal counts only removed pending items; success ignores already-removed ids; pending count accumulates across batches; published lists contain only completed entries with paths; the duplicate aggregate publication is gone. The new deferred two-file regression verifies the list remains `null` after A fails and publishes only B after B resolves. The three cancellation/global/toast recovery cases still pass. Static inspection covers the pending/manual-removal changes; arbitrary overlapping/manual-removal permutations were not separately executed here.
- **SimpleUpload:** Dropzone's upload and returned success callback are awaited under an explicit terminal. A failed request cannot call success. ApiError precheck failures use canonical presentation while existing local validation messages remain specialized. Tests cover already-presented upload rejection, canceled precheck, and local spreadsheet validation.
- **Audio:** `audioPlayButton.tsx` delegates TTS ApiError unchanged while keeping local playback-unavailable copy for ordinary player failures. Loading and current playback ownership are released in both tested error cases. This tests the button's synchronous playback boundary, not a real audio device.
- **Skill forms:** Both silent mutation forms use `showSkillError`, retaining the existing domain-code/live-size copy while ignoring canceled/global/already-presented canonical failures. Once presented locally, the ApiError is marked `toast`. Static inspection verifies each live save/upload/GitHub mutation catch, and the helper regression verifies deduplication and distinct upload/unpacked limits. Full drawer/browser submission is not independently executed in this round.
- **ModelConfig:** Detail loading failure is now caught, original failure is presented, and the failure/retry screen replaces the editable default form. Its effect cleanup prevents an old resource response from changing the current form. `ModelConfig.errors.test.tsx` executes initial failure, absence of Save, retry, and populated successful form. The stale-id guard was inspected statically; it is not claimed as an independently run stale-id test.
- **Workbench:** The extracted headings use `model.workbenchConversationModels` and `model.workbenchVoiceModel`; all three platform locale files contain them. Previously reviewed write-versus-refresh separation remains covered by the earlier review run.

### Seven dimensions — round-2 delta

| Dimension | Result / limit |
|---|---|
| Boundary conditions | PASS for assigned failures: failed lists are retryable, failed provider detail cannot expose a saveable blank default, upload/precheck/TTS failures reach a terminal, original canonical evidence is retained |
| Permission/authentication | PASS within consumer scope: no new business 403 branch or auth bypass; specialized forms respect global presentation/cancellation. Earlier compatibility matrix remains the evidence for auth/session/license behavior; no real-account test here |
| Concurrency | PASS for the identified attachment premature-completion defect after repair and deferred regression; provider old-resource writes are guarded. This is not exhaustive concurrent-request certification |
| Information leakage | No new sensitive logging or remote diagnostics sink in these deltas. Existing audio logging is outside this scoped fix; no claim of a repository-wide logging audit |
| Tests | Independent final run: 10 files / 27 tests passed, exit 0; no unhandled-error summary. Tests exercise actual consumer boundaries with mocked HTTP dependencies |
| Code style | Scoped reuse of existing presentation helpers and optional component slots; no new dependency. Implementer reports 19 changed-path lint passes; reviewer did not rerun lint/full typecheck/build |
| Documentation | fix-round-2-report records the intended scope/recovery semantics; this report additionally records the found-and-fixed attachment counter issue and evidence. Final design/tasks/inventory synchronization remains the parent's gate |

### One independent focused rerun

From `src/frontend/platform`:

```sh
pnpm exec vitest run src/pages/BuildPage/bench/pickerErrors.test.tsx src/components/bs-ui/upload/simple.errors.test.tsx src/components/voiceFunction/audioPlayButton.errors.test.tsx src/test/skillErrorLimitCopy.test.ts src/pages/ApprovalPage/useApprovalController.errors.test.tsx src/pages/ModelPage/components/FinetuneDetail.errors.test.tsx src/pages/BuildPage/flow/FlowChat/ChatFiles.errors.test.tsx src/pages/KnowledgePage/qas.errors.test.tsx src/components/bs-comp/appChat/composerToolbar.test.tsx src/pages/ModelPage/manage/ModelConfig.errors.test.tsx --maxWorkers=1 --minWorkers=1
```

**Result:** 10 files / 27 tests passed, process exit 0, duration 10.37 seconds. Log: `/private/tmp/f088-platform-review-round2-final.log`. Expected mock-ref/router warnings are not test failures. This is the only test invocation by this reviewer for round 2. Parent's separate RED/GREEN evidence for the two-file defect is recorded in `/private/tmp/f088-upload-batch-green.log` and parent task history.

The baseline limitations in the earlier section remain disclosed, not implicitly fixed by this run. No browser, real backend, real permission account, middleware, deployment or audio-device E2E was executed by this reviewer. Parent owns whole-feature full checks, final baseline classification, and the explicit E2E limitation/checklist. Native-fetch WebSearchFrom and unrelated old features remain excluded.

**Final scoped outcome: Spec PASS / Quality PASS.** The assigned platform repairs, including the final attachment cleanup correction, are closed; broader merge acceptance remains with the coordinator.
