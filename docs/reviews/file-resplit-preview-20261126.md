# File resegmentation preview hotfix review

- Date: 2026-11-26 (Asia/Taipei)
- Target: `feat/3.1.0`, based on `ae37dc3b87`
- Track: hotfix; restores the existing preview contract without backend or schema changes.
- Scope: frontend preview identity, visible failure feedback, retry, and regression coverage.

## Problem and change

On 116, space 3733 / file 94860 reached the comparison step with an empty chunk panel and a disabled confirmation button. The original Markdown download returned HTTP 200. The preview request sent only its signed URL and omitted the existing file identity. The task status returned `error`, code `10952`, with `404: This resource does not exist`.

`FileProcessingPreview` now attaches the existing file ID after the wizard strategy conversion. The existing `PreviewResult` adapter sends `preview_file_id`, `preview_source=original`, and the matching `knowledge-preview-file:<id>:original` identity. The browser URL remains available for the original document viewer. Backend tenant and download authorization checks remain in force.

The chunk panel now displays the localized parse failure instead of the empty-result placeholder. File resegmentation offers a retry after failure; retry clears readiness and creates a new preview request. Only a completed preview marks the result ready for confirmation. Preview chunks remain read-only in this flow.

## Review

| Dimension | Result | Evidence |
| --- | --- | --- |
| Boundary conditions | PASS | Existing-file identity and original URL retain distinct purposes; document/table rules continue through the same strategy. |
| Permission and authentication | PASS | Existing backend source resolution remains unchanged; no URL-only bypass or authorization fallback. |
| Concurrency | PASS | Retry increments the preview generation, cancels the previous subscription through existing cleanup, and keeps confirmation unavailable until completion. |
| Information leakage | PASS | Error text uses the existing localized resolver; no credentials or signed URLs added to source. |
| Tests | PASS | Real `FileProcessingPreview` → wizard conversion → `PreviewResult` chain tested at the preview API boundary; existing confirmation tests also pass. |
| Code style | PASS | Frontend lint/type checks and architecture guard pass; obsolete Chinese-console-string suppression automatically pruned. |
| Documentation | PASS | Existing contract restored; hotfix does not require new spec/design/tasks. This report records behavior and validation. |

Overall: **PASS**.

## Validation

- Six targeted Vitest files: 31 tests passed. Includes authorized source parameters, successful readiness, failure feedback, original viewer fallback, retry without cached results, upload preview compatibility, and confirmation gating.
- `pnpm lint`: passed. One pre-existing unused-disable warning in `BatchTagDraftDialog.tsx` remains outside this change.
- `pnpm typecheck`: passed across the frontend workspace.
- `pnpm check-i18n`: passed; no new translation keys or drift.
- `pnpm build:platform`: passed. Existing large-chunk build warning remains.
- Architecture guard on changed TypeScript files and `git diff --check`: passed.

The repair has not been deployed to 116 or production. Live acceptance with the repaired frontend remains a deployment-time check. No file overwrite, backend restart, database migration, or production configuration change is part of this delivery.
