# Audit source Excel preview hotfix

Date: 2026-11-24. Base: beta2 `dfa513b8c4`. Scope: one preview-dispatch logic file, regression tests, no API or authorization contract change.

## Confirmation

The supplied successful `/api/v1/qa/chunk` response for message 443408 contains 16 chunks. After the existing grouping and score sort, file **98273**, `Excel双表头.xlsx`, ranks first at **0.43**. Its original and preview URL paths are `/object/bisheng/original/98273.xlsx` and `/object/bisheng/preview/98273.xlsx`. The Word file 97553 mentioned at the start of the source text ranks below it at 0.23. Signed query parameters and source document contents are not copied into this report or tests.

`ResultPanne` opens the first sorted file. `FileViewPanne` handled other modern formats but had no XLS/XLSX case, so the selected workbook reached the unsupported branch before any workbook viewer could load it. The component also requested the `knowledge` namespace only through a translation call, without registering it with `useTranslation`; direct audit navigation could render the raw `fileNotSupported` key.

## Change

- Dispatch modern XLS and XLSX sources to the existing shared `ExcelPreview`, already used by knowledge preview. No direct spreadsheet parser dependency is added to the platform.
- Use the existing resolved `fileUrl`: preview URL preferred, original URL used when no preview exists. Signed URL parameters are passed intact.
- Register both `bs` and `knowledge` namespaces. Reuse existing translated messages; no new translation keys.
- PDF/session behavior, other formats, sorting, backend source access and file permissions remain unchanged.

## Verification

- Targeted Vitest: **8 passed**. The new tests exercise the real source grouping/sorting adapter with sanitized response shapes, assert Excel dispatcher URL selection for preview and XLS/XLSX original fallback, and verify lazy namespace loading using a real i18next instance. Existing PDF session stability and source-content security tests pass.
- The Excel child is mocked in routing tests; these tests do not claim to decode the live workbook or provide deployed-browser acceptance.
- Frontend workspace `pnpm lint`, `pnpm typecheck`, `pnpm check-i18n`, architecture guard and `git diff --check`: passed. Lint retains the unrelated pre-existing unused-disable warning in `BatchTagDraftDialog.tsx`.
- Read-only HTTP checks of both supplied workbook URLs: **200**, **18,079 bytes** each, valid ZIP with `xl/workbook.xml` and **1 worksheet**. No file contents or signed URL parameters were printed or persisted.

## Review

| Dimension | Result |
| --- | --- |
| Boundary cases | Preview/original URLs, both XLS/XLSX and unsupported fallback covered |
| Permission and tenancy | No access or signing changes; existing authorized API result is consumed |
| Concurrency | No request/state lifecycle changes; PDF mount regression retained |
| Disclosure | Existing text sanitization tests retained; no live signed URLs committed |
| Test coverage | Source adapter to viewer dispatch and real lazy translation loading tested |
| Style/layering | Reuse shared viewer; no new dependency or duplicated parser |
| Documentation | Cause, behavior and deployment boundary recorded here as a hotfix |

After deploying the frontend, reopen audit source for message 443408 and verify that file 98273 displays its workbook and sheet controls. Browser rendering/decoding and deployment acceptance remain pending; 116 deployment/data were not changed by this hotfix.
