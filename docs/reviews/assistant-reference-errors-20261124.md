# Assistant saved-reference diagnostics correction

Date: 2026-11-24. Base: beta2 merge `6f3d38fdf8`. Scope: the two omissions found after the earlier reference-error diagnostics change.

## Confirmed cause

The 116 assistant `35d17d20f4424f54af0cda1ebb4e3c34` retained knowledge IDs 4387, 4402 and 4409. A read-only global lookup found no knowledge row 4402. The online button first issues `PUT /api/v1/assistant`; boundary validation rejected the saved selection before the online status request. The 19:49:06 request trace `de04aefd0ed04206b4065605cb187502` recorded `404: This resource does not exist` inside an HTTP 200 envelope. Read-only replay of the boundary method reproduced the same refusal. The previous 10996 formatter therefore could not improve this error.

The platform's `ReferenceStateHint` used `references.invalid_missing` and `references.invalid_scope`, while those keys were absent from all three platform `bs.json` catalogs.

## Correction

- The assistant application keeps the original binding validator. Only its HTTPException 404 refusal opens a diagnostic path.
- Require effective assistant `edit` authorization before inspection. Use the existing source-read inspector and original identity; no target-name lookup, cross-tenant probe, or permission shortcut.
- Report only invalid knowledge targets present both in the authorized saved source and this request. Existing target facts determine missing/deleted/deleting/scope causes. Return 10996 with `reference_errors`, already supported by both HTTP presenters.
- New/unknown IDs and removed saved invalid IDs do not gain a detailed existence response. Permission failures and other HTTP statuses propagate. Successful bindings perform no extra inspection.
- Refusal remains before the business write session. The fix does not save invalid bindings, silently remove selections or publish the assistant.
- Add Chinese, English and Japanese labels for the missing/scope states. A component regression renders all six invalid/unavailable cases with real translation resources in each language.

The reported missing resource now displays its knowledge ID and missing cause using the existing shared formatter. Resource 4402 remains absent; no deployment data is repaired by this code change.

## Validation

- Backend targeted regression: **81 passed, 1 deselected**. Includes the new validator, current assistant save/write and execution paths, original boundary checks and resource diagnostics.
- Frontend targeted regression: **16 passed**. Includes the real translated component in all three languages, assistant save HTTP rejection rendering, and retained hidden selections.
- Frontend workspace `pnpm lint`, `pnpm typecheck` and `pnpm check-i18n`: passed. Lint retains the unrelated existing unused-disable warning in `BatchTagDraftDialog.tsx`.
- Changed Python files: Ruff format/check passed. Changed files: architecture guard and `git diff --check` passed.
- The final changed frontend test files also passed targeted lint.

The legacy boundary test `test_denied_binding_does_not_persist_any_assistant_or_link` was already broken on base: it patches the removed `get_reference_binding_runtime` symbol before exercising production code. It is excluded from the targeted boundary suite. A new regression directly verifies that the current assistant save path raises the detailed failure before opening its business write session.

## Review

| Dimension | Result |
| --- | --- |
| Boundaries | Only match selected saved knowledge IDs; new IDs preserve original refusal |
| Permission/tenant | Edit authorization precedes inspection; existing source identity/scope checks and binding refusal preserved |
| Concurrency | Read-only error explanation before write session; successful path unchanged |
| Disclosure | No names fetched, no SQL/exception interpolation, no new foreign-ID existence oracle |
| Tests | Error propagation, edit denial, exact lifecycle states, no writes, three-language component and HTTP regression |
| Style | Application orchestration around existing domain validator; no new dependency or schema |
| Documentation | Current data flow and compatibility updated in design §4.9 |

116 deployment and real browser acceptance have not been performed for this correction. Database/log checks and earlier replay were read-only.
