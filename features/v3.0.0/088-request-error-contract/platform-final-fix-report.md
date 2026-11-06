# T003 fix round 2 report

Status: **DONE** for the assigned round-2 scope. Final focused regression: **9 files / 25 tests pass**, changed-path ESLint passes, scoped diff whitespace check passes. No global Git writes, commits or subagents; no parent-owned Workbench or request foundation changes.

## Live chains and behavior

1. `bench/DailyChatConfig.tsx` renders `OrgKbConfig` and `ToolsConfig`. Failed knowledge/tool reads now preserve existing lists, store the original failure, delegate canonical notices to `showApiError`, and show shared Alert with existing localized retry copy. Initial failure no longer appears as a successful empty picker. Canceled/global errors do not create an inline failure alert. Knowledge search keeps prior successful rows when the subsequent search fails. Tool cache/bucket semantics are unchanged; pending reads have loading state. An optional `loading` / `loadErrorContent` slot passes through `ToolSelectorContainer` into `ToolSelector` so tool tabs remain usable and failed empty buckets suppress “no tools found” copy. This slot is inert for other consumers.
2. `KnowledgePage/qas.tsx` generic batch-enable/batch-disable catch and individual status-update catch now pass the same error to `showApiError`. Existing status rollback remains unchanged. Named allSettled per-batch partial-success/failure summaries remain intact; these were deliberately not replaced by a generic notice.
3. Live workflow `FlowChat/ChatInput` uses `ChatFiles`; upload catch now delegates the original error, including cancellation/global presentation, instead of displaying another upload-failed notice. Existing removal, counters and attachment completion callbacks are retained. Tests fail one attachment and then successfully upload another to verify cleanup/recovery.
4. `SimpleUpload` is live in `DataSetPage/CreateDataSet` and `KnowledgePage/components/ImportQa`. Its Dropzone upload now has a terminal catch; failure cannot invoke success. The success callback is awaited so a returned rejection also reaches the boundary. API failures during pre-check use canonical presentation; ordinary local spreadsheet/size validation keeps its existing localized copy. Added explicit optional Props types; preCheck accepts unknown return values to remain compatible with the existing Excel Promise<unknown> validator. Removed unused destructured callbacks that had no behavior or live caller.
5. `AudioPlayComponent` is live in workflow markdown, form chat messages and shared platform voice controls. Wrapped TTS ApiError is delegated unchanged; ordinary local player/invalid-path failures retain playback-unavailable copy. Both cases keep loading/current-playing cleanup.
6. `SkillUploadDialog` / `SkillFormDrawer` mutations already use `silent:true`. Their named local validation remains specialized through `showSkillError`: skip canceled/global/already-presented canonical failures; otherwise present existing translated skill/size copy and mark ApiError presentation once. Upload and unpacked limits retain their distinct live-limit interpolation. Optional slug suggestions and upload-cap metadata fallback are unchanged named recoveries.

Native-fetch `WebSearchFrom` remains excluded. No new translation keys or visual styles were introduced.

## Test typing corrections

- `useApprovalController.errors.test.tsx`: getRolesApi fixtures now use `{ data: [] }`, matching its declared return type.
- `FinetuneDetail.errors.test.tsx`: rename response mock is defined at the vi.fn module-mocking boundary, avoiding an invalid AxiosResponse assignment while matching the wrapped runtime result. No new any or ignore directives.

## Changed paths (platform src)

Production: `pages/BuildPage/bench/{OrgKbConfig,ToolsConfig}.tsx`; `components/LinSight/{ToolSelectorContainer,ToolSelector}.tsx`; `pages/KnowledgePage/qas.tsx`; `pages/BuildPage/flow/FlowChat/ChatFiles.tsx`; `components/bs-ui/upload/simple.tsx`; `components/voiceFunction/audioPlayButton.tsx`; `components/LinSight/skill/{skillErrors.ts,SkillFormDrawer.tsx,SkillUploadDialog.tsx}`.

Added tests: `pages/BuildPage/bench/pickerErrors.test.tsx`; `pages/BuildPage/flow/FlowChat/ChatFiles.errors.test.tsx`; `pages/KnowledgePage/qas.errors.test.tsx`; `components/bs-ui/upload/simple.errors.test.tsx`; `components/voiceFunction/audioPlayButton.errors.test.tsx`. Extended `test/skillErrorLimitCopy.test.ts` and corrected the two round-1 tests above.

## Verification

RED evidence: picker/upload/playback tests initially reported **5 failures / 2 existing-path passes**, `/private/tmp/f088-platform-round2-red.log`; specialized skill presentation test initially failed, `/private/tmp/f088-platform-round2-skill-red.log`. QA fixtures were corrected to include the page's required update timestamp; knowledge search test uses the actual SearchInput placeholder rather than a textbox role.

Final command from platform:

```sh
pnpm exec vitest run src/pages/BuildPage/bench/pickerErrors.test.tsx src/components/bs-ui/upload/simple.errors.test.tsx src/components/voiceFunction/audioPlayButton.errors.test.tsx src/test/skillErrorLimitCopy.test.ts src/pages/ApprovalPage/useApprovalController.errors.test.tsx src/pages/ModelPage/components/FinetuneDetail.errors.test.tsx src/pages/BuildPage/flow/FlowChat/ChatFiles.errors.test.tsx src/pages/KnowledgePage/qas.errors.test.tsx src/components/bs-comp/appChat/composerToolbar.test.tsx
```

**9 files / 25 tests pass, no unhandled errors**, 4.09s; `/private/tmp/f088-platform-round2-focused.log`. Expected React Router warnings and mock-child ref warnings are non-failing. Covers retry, retained prior list, canonical versus local validation, no upload success after failure, TTS/local player cleanup, specialized one-time skill validation, QA rollback and batch summary, canceled/global/already-toasted attachment recovery, and existing composer integration.

ESLint across **all 19 changed production/test paths** passes using existing suppressions with `--pass-on-unpruned-suppressions`; `/private/tmp/f088-platform-round2-lint.log` is empty. No suppression edits/widening in this round. Scoped `git diff --check` passes. No full-suite or root TypeScript rerun; parent owns final quality gates and independent review. The earlier unrelated API-index baseline issue remains documented in round 1 and was not touched here.

Ready for one independent parent-coordinated review of round 2.
