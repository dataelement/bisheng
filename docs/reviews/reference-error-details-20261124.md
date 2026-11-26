# Resource reference error diagnostics review

- Date: 2026-11-24
- Base: `feat/3.1.0-beta2`, `8e99ac1558c1018214f432a4f2615af03a25c604`
- Branch: `codex/beta2-reference-error-details-20261124`
- Scope: fix incomplete diagnostics for existing 10996 failures. Existing error code and authorization/admission rules remain; optional error data is additive and the previous publication field stays compatible. No schema, data migration, deployment or model replacement.
- Design: `features/v3.1.0-beta2/006-reference-hints/design.md` §4.9.

## Problem and resulting behavior

The execution reader discarded failed target facts and raised only `reference_target_invalid`. The platform publication formatter handled only two reasons; the client had no equivalent formatter, and its JSON-string WebSocket errors lost `data`. Several local presenters translated the numeric error code again, replacing more specific HTTP error copy.

The reported workflow now renders, when the Owner reports missing model 375:

> 节点“大模型”（llm_b1ef4）引用的模型（ID：375）不存在，请在应用配置中重新选择后保存或发布。

A missing model has no live model name to retrieve. The message identifies its saved ID, and node labels/IDs come only from the caller's already authorized graph. No model-name reconstruction or additional lookup is performed.

## Audit and implemented coverage

| Path | Diagnostic behavior |
| --- | --- |
| Saved workflow, transient preview and sync/async source execution reads | Preserve exact target lifecycle/scope facts and all affected node locations, bounded to five distinct details |
| Workflow publication/version validation | Same node-location extractor; preserve old `workflow_reference_errors` alongside new state-bearing details |
| Assistant new knowledge selection and model selection | Return selected unavailable IDs; do not falsely identify filtered/unavailable rows as deleted |
| Default-model read/save validation | Identify selected model IDs and distinguish unavailable, offline and wrong model type |
| Legacy binding execution validation | Preserve verified receipt target IDs and states |
| Knowledge processing admission | Replace undifferentiated target reason with processing configuration unavailability |
| Both HTTP presenters | Shared safe reason/detail rendering, retaining the complete rejected error envelope |
| Client conversation WS and platform workflow debug WS | Retain data in object/string envelopes and show node/model diagnostics |
| Platform assistant chat and prompt stream | Reuse known reference reasons; 10996 no longer appends raw exception text |
| Hosted application management preview rejection | Preserve specific reference diagnostics instead of replacing them with numeric-code copy |
| Both knowledge parse presenters, import failures, client uploads and task failure summaries | Reuse the same formatter when structured error evidence is available |

Static AST audit of production Python found **282 literal 10996 reasons**, all assigned once to **34 localized cause groups** in `packages/api-client/src/referenceReasons.ts`. Direct error constructions all supply a reason or forward the original error kwargs. This inventory is source-level coverage, not a claim to have triggered every internal invariant in a running deployment. Tests verify that every allowlisted reason has Chinese, English and Japanese copy.

Reasons cover missing/unavailable resources, legacy model identity, model defaults, scope/ownership, workflow version/configuration, channel time/rule/folder selection, deletion selection/evidence, stale configuration, processing plans, and invalid verification/execution context. Unknown future reasons and historical records that retain only the numeric code explicitly report missing failure details. Exact causes cannot be reconstructed from an error code alone; no raw reason/exception is used as display copy.

Existing task failure reasons (`model_unavailable`, file/schema changes, etc.) already have specific messages and remain in use. The code-only historic task fallback intentionally cannot identify a node or model ID that was never persisted.

## Validation

- Backend targeted suite: **232 passed, 1 failed**; adjacent processing/default-model suites: **58 passed** (total **290 passed, 1 known baseline failure**). The failure is `test_wf_published_admission.py::test_only_admitted_graph_is_queued_and_override_is_not_applied_twice`, caused by SQLite engine initialization rejecting `max_overflow/pool_timeout`. The exact test also fails on unmodified base `8e99ac1558` in the earlier clean integration worktree.
- Backend added coverage: saved sync/async reads and transient preview, precise lifecycle/scope states, multiple nodes sharing a target, valid targets omitted, post-read identity failure precedence, repair inspection, bounds, unknown node fallback, offline/type mismatch defaults.
- Frontend: client **43 passed**, platform **38 passed**, shared API client **33 passed**. Includes HTTP envelope preservation, both WS envelope forms, parser/task/import summaries, legacy publication compatibility, all three languages, malformed/unknown data, bounds and private diagnostic exclusion.
- Frontend lint: passed; one pre-existing unused eslint-disable warning in `BatchTagDraftDialog.tsx`.
- Frontend workspace `pnpm typecheck` and `pnpm check-i18n`: passed. Targeted lint also passed after the final typed translation-key fixes.
- Python changed files: Ruff format/check passed. Changed files: architecture guard passed with no violations. `git diff --check` passed.

## Review

| Dimension | Result | Evidence |
| --- | --- | --- |
| Boundary conditions | PASS | Strict positive decimal IDs, bounded labels/details, malformed/unknown diagnostics rejected; old publication field supported |
| Permission and auth | PASS | Existing authorization and source revalidation order preserved; no new lookup or relaxed admission |
| Concurrency | PASS | Existing transaction/CAS/identity checks stay authoritative; no writes introduced by formatting |
| Information disclosure | PASS | Only selected IDs and authorized node labels; fixed reasons/states; no exception/SQL/path interpolation |
| Tests | PASS with known baseline failure | Targeted results above; failed baseline reproduced independently |
| Style and layering | PASS | Shared pure frontend formatter; shared backend location/default validators; no new dependencies |
| Documentation | PASS | Current data flow, additive error fields, limitations and troubleshooting synchronized to design §4.9 |

## Deployment acceptance still required

After deploying both backend and frontend, open the reported workflow as the authorized super administrator and attempt a new conversation. Expect the node/model-375 missing message and no model invocation. Verify the same target in builder preview/publication. With controlled test resources, check deleted knowledge, scope-unavailable model and a corrected published model. These browser/deployment steps were **not performed** in this code change; 116's saved workflow/model data was not modified.
