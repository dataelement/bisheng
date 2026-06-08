# Design: Remove autogen / ragas deps & rebuild Evaluation as a DDD module

Date: 2026-06-06
Branch: `feat/langchain-1x`
Status: Approved (design), pending implementation plan

## Background

The LangChain 0.3 → 1.x upgrade left two same-org third-party packages that have
no 1.x-native release and import removed `langchain.*` paths:

- `bisheng_pyautogen` (`autogen`) — imports removed `langchain.callbacks.*`,
  `langchain.base_language`, `langchain.load.dump`.
- `bisheng-ragas` — imports removed `langchain.callbacks.*`, `langchain.chains.base`,
  `langchain.chat_models.base`, `langchain.schema`, and symbols dropped from
  `langchain_community.chat_models` (`AzureChatOpenAI`/`ChatOpenAI`/...).

Both are currently bridged by a temporary `bisheng_langchain/langchain_compat.py`
`sys.modules` shim. This design removes both packages so the shim can be deleted.

### Findings from code research

- **autogen is dead in the running app.** It is referenced only by legacy dynamic
  chain-loading (`bisheng_langchain.chains.__init__` → `AutoGenChain`,
  `gpts/utils.import_autogenRoles`, `rag/utils` loader) and the unused
  `settings.autogen_roles` config field. No flow / skill template / DB row
  references it; the `bisheng` app import sweep is clean without it.
- **`bisheng-ragas` reduces to a single metric**, `AnswerCorrectnessBisheng`
  (`bisheng/api/services/evaluation.py:299`). The metric is pure:
  few-shot prompt → `BaseChatModel.generate(batch)` → parse JSON → arithmetic.
- **`datasets` (HuggingFace)** is used only by `evaluation.py` (a throwaway
  validation `Dataset.from_dict` in the route, plus the real one in the service)
  and by the dead benchmark script `bisheng_langchain/rag/scoring/ragas_score.py`.
- **`Evaluation` is a multi-tenant table** (`tenant_id` column). Tenant tables are
  auto-discovered from `SQLModel.metadata`, but only for modules listed in
  `core/database/tenant_filter.py::_TENANT_AWARE_MODEL_MODULES` (which force-imports
  them before discovery). `bisheng.database.models.evaluation` is in that list.
- **Blast radius is small.** Importers: `api/services/evaluation` ← only
  `api/v1/evaluation`; `database/models/evaluation` ← `tenant_filter`, the route,
  the service; route registered in `api/v1/__init__`.

## Decisions (locked with user)

1. **Full DDD module** for evaluation (api/router + endpoints, domain/services +
   schemas + repositories + models) — the table model moves into the module's
   `domain/models/`, matching `knowledge`/`linsight`/`llm`/`tool`.
2. **Output byte-identical to ragas** — same 9 fields, same scoring formula, same
   default few-shot prompt, same result-table/xlsx shape. Frontend & stored results
   see no change.
3. **Clean up `datasets` + dead scripts** — delete `rag/scoring/ragas_score.py` and
   drop the `datasets` dependency along with `bisheng-ragas`.

## Part 1 — Remove `bisheng_pyautogen`

**Delete**
- `bisheng_langchain/autogen_role/` (whole package: `__init__`, `assistant`,
  `custom`, `groupchat_manager`, `user`)
- `bisheng_langchain/chains/autogen/` (`auto_gen.py` → `AutoGenChain`)

**Edit**
- `bisheng_langchain/chains/__init__.py` — remove `AutoGenChain` import/export
- `bisheng_langchain/gpts/utils.py` — remove `import_autogenRoles`
- `bisheng_langchain/rag/utils.py` — remove the autogen loader
- `bisheng/core/config/settings.py` — remove `autogen_roles: dict = {}` (unused)
- `pyproject.toml` — remove `bisheng_pyautogen==0.3.2`

## Part 2 — Evaluation DDD module + drop `bisheng-ragas` / `datasets`

### New module layout

```
bisheng/evaluation/
  __init__.py
  api/
    __init__.py
    router.py                          # APIRouter(prefix='/evaluation', ...)
    endpoints/
      __init__.py
      evaluation.py                    # endpoints from api/v1/evaluation.py
  domain/
    models/
      __init__.py
      evaluation.py                    # Evaluation table + ExecType/EvaluationTaskStatus enums
    schemas/
      __init__.py
      evaluation.py                    # EvaluationCreate / EvaluationRead / EvaluationBase DTOs
    repositories/
      __init__.py
      evaluation_repository.py         # replaces EvaluationDao methods
    services/
      __init__.py
      evaluation_service.py            # orchestration from api/services/evaluation.py
      answer_correctness.py            # NEW langchain metric (replaces ragas)
```

### `answer_correctness.py` (langchain reimplementation)

Replaces `bisheng_ragas.evaluate` + `LangchainLLM` + `AnswerCorrectnessBisheng` +
`Dataset`. Behavior is preserved exactly:

- Carry over the `CORRECTNESS_PROMPT` few-shot template verbatim; honor a custom
  `evaluation.prompt` when provided (same precedence as today).
- Build one `ChatPromptTemplate` per (question, answer, ground_truth) row.
- Batch-call the evaluation `BaseChatModel` via `.generate(prompts)` — this is what
  ragas's `LangchainLLM` wrapper did internally.
- Parse each generation's JSON with `json-repair` (already a dependency), replacing
  ragas's `json_loader.safe_load`.
- Compute per row, identical to current code:
  - `tp/fp/fn` = lengths of overlap / answer-only / gt-only statement lists
  - `f1 = tp / (tp + 0.5*(fp + fn))`
  - `precision = tp/(tp+fp)`, `recall = tp/(tp+fn)`, `np.nan` on zero denominators
  - the 9 output fields: `statements_gt_only`, `statements_num_gt_only`,
    `statements_answer_only`, `statements_num_answer_only`, `statements_overlap`,
    `statements_num_overlap`, `answer_f1`, `answer_precision`, `answer_recall`
- Return a dict-of-lists (same keys ragas' `.to_pandas().to_dict(orient="list")`
  produced, plus `question`/`answer`/`ground_truths`) so the downstream result-table
  builder and xlsx export in the service are unchanged.

### Cross-cutting edits

- `core/database/tenant_filter.py` — in `_TENANT_AWARE_MODEL_MODULES` replace
  `'bisheng.database.models.evaluation'` with
  `'bisheng.evaluation.domain.models.evaluation'`. **Required** — omitting it
  silently disables tenant isolation for the table.
- `api/router.py` — register the new evaluation router.
- `api/v1/__init__.py` — remove the old evaluation route registration.
- Update the route's create endpoint to validate uploaded CSV without
  `Dataset.from_dict` (plain column-presence check).

**Delete after move**
- `bisheng/api/v1/evaluation.py`
- `bisheng/api/services/evaluation.py`
- `bisheng/database/models/evaluation.py`

No Alembic migration: table name and columns are unchanged.

### Dependency / shim cleanup

- Delete `bisheng_langchain/rag/scoring/ragas_score.py` (dead benchmark script;
  last user of `datasets` + `ragas`). Leave `llama_index_score.py` (separate).
- `pyproject.toml` — remove `bisheng-ragas` and `datasets`.
- Delete `bisheng_langchain/langchain_compat.py` entirely and remove its import from
  `bisheng/__init__.py` and `bisheng_langchain/__init__.py` (it existed only for
  autogen + ragas).
- `uv lock`.

## Testing

New tests under `test/evaluation/` (per project convention — not `test/` root):

- **Metric unit test** — feed `answer_correctness` a stub `BaseChatModel` returning
  a known JSON payload; assert the 9 fields, counts, and P/R/F1 (including the
  nan-on-zero-denominator branches) match expected values. Include a Chinese-text
  case mirroring the few-shot examples.
- **Repository test** (sqlite) — CRUD + pagination via `EvaluationRepository`.
- **Boot/regression** — confirm `bisheng.main` still imports with the shim removed,
  and the full pytest baseline count is unchanged (currently 2219 passed; no new
  regressions).

## Risks & mitigations

- **Silent tenant leak** if `_TENANT_AWARE_MODEL_MODULES` isn't updated → explicit
  task + a test asserting the table is discovered as tenant-aware.
- **Metric divergence** from ragas → byte-identical formulas + golden-value unit
  test; keep the prompt verbatim.
- **Hidden importers** of moved modules → grep confirmed small; re-run the import
  sweep after the move.
- **Shim removal ordering** — remove the shim only after both autogen and ragas are
  gone, then re-run the import sweep.

## Out of scope

- No change to evaluation request/response contract, DB schema, or frontend.
- `llama_index_score.py` and other optional rag eval scripts.
- Pre-existing unrelated bugs (e.g. `from ast import List` in `dataset_param.py`).
