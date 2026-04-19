# F016 AC Verification Record

> Execution status tracked here; template created during T08. T09 (手工 QA
> execution on 114) updates the "Executed Results" section with actual
> evidence. Pending items (衍生数据归属, storage quota 真实上传触发) remain ⏳
> until F017 / real file upload flow is available.

---

## Execution Environment

| Layer | Used | Notes |
|-------|------|-------|
| Local mac | partial | AST `py_compile` only; no BiShengVENV conda env; base python lacks celery so full import fails |
| Test server (192.168.106.114) | ⏳ pending T09 | `uv sync --extra test` then `.venv/bin/pytest test/test_quota_service*.py test/e2e/test_e2e_tenant_quota_hierarchy.py -v` |
| Real OpenFGA store | ⏳ pending T09 | F013 store `bisheng` already in place; shared_to tuples for Root resources written by business layer (F017 — pending) |

---

## AC ↔ Coverage Map

| AC | Description | Auto Coverage | Manual QA |
|----|-------------|--------------|-----------|
| AC-01 | Create resource checks leaf + Root chain | `test_quota_service_check_chain.py::test_check_quota_leaf_exceeded` + `test_quota_exceeded_raises` (migrated in T06) | §7-1 — set Child `quota_config.knowledge_space=2`, create 2 via UI, 3rd returns 19401 |
| AC-02 | Root shared resource not counted in Child | `test_quota_service_tenant_tree.py::test_count_usage_strict_excludes_sibling_tenants` | §7-3 — create shared knowledge as super admin on Root; as Child user query `/tenants/{child_id}/quota` — Child `knowledge_space.used` unchanged |
| AC-03 | PUT /tenants/{id}/quota accepts new keys | E2E `test_put_quota_accepts_storage_gb` + `test_put_quota_rejects_unknown_key` | §7-8 — admin UI adjust quota_config including storage_gb, verify saved |
| AC-04 | Storage 100% blocks upload with 19403 | covered by `test_check_quota_storage_raises_19403` + `test_knowledge_space_file_raises_19403_not_19401` (chain cap blocker → storage errcode) | Real upload flow: upload files until storage_gb used == limit, next upload returns 19403; not fully automated because upload requires real MinIO + file |
| AC-05 | Delete resource releases quota | (no new code) | §7-9 — delete knowledge resource on Child, recount via `/tenants/{child_id}/quota` shows decrement |
| AC-06 | GET /tenants/quota/tree returns tree | E2E `test_quota_tree_returns_root_and_active_children` + `test_quota_tree_forbidden_for_non_super_admin` | admin UI loads tree view; Child Admin sees 403 |
| AC-07 | Root usage = Root self + Σ active Child | `test_quota_service_tenant_tree.py::test_aggregate_root_sums_self_plus_active_children` + `test_aggregate_root_excludes_archived_children` | §7-4 — set up Child A with 30 KS, Child B with 50, Root with 20, GET tree, assert root.usage[knowledge_space].used=100 |
| AC-08 | Root hardcap blocks Child creation | `test_check_quota_root_hardcap_blocks_child` + `test_root_hardcap_msg_contains_group_exhausted` | §7-2 / §7-5 — set Root `knowledge_space=5`, fill to 5 (Root itself 2 + Child 3), Child creates 4th → 19401 with msg "集团总量已耗尽" |
| AC-09 | strict_tenant_filter wraps all tenant-level counts | `test_count_usage_strict_wraps_in_strict_filter` (CM entered/exited) | §7-6 — inspect SQL logs during `/tenants/{child_id}/quota` to confirm WHERE tenant_id=<child> without OR tenant_id IN (...) |
| AC-10 | model_tokens_monthly derived data tenancy | E2E `test_model_tokens_monthly_stub_returns_zero` (stub); full flow depends on F017 | §7-7 — after F017 lands, Child user calls Root shared LLM model, observe `/tenants/{child_id}/quota.usage[model_tokens_monthly]` increment, Root unchanged |

---

## Manual QA Checklist (spec §7)

Execute on 114 after `uv sync` + `.venv/bin/uvicorn bisheng.main:app --port 7860` with `multi_tenant.enabled=true`.

### §7-1 Single-tenant 100% quota blocks

- [ ] Create Child tenant `f016-qa-c1` with `quota_config={'knowledge_space': 2}`
- [ ] Login as a user in that Child
- [ ] Create 2 knowledge spaces — expect success
- [ ] Create 3rd knowledge space — expect HTTP 200 + `status_code=19401`
- [ ] Message contains the blocker tenant id (Child)

### §7-2 Root<Child hardcap triggers Root-limit

- [ ] Set Root `quota_config={'knowledge_space': 5}`
- [ ] Keep Child `quota_config.knowledge_space=10` (well above Root)
- [ ] Create 2 KS on Root, 3 on Child A (total 5 = Root limit)
- [ ] Child A user creates 4th KS → HTTP 200 + `status_code=19401`
- [ ] `status_message` contains `集团总量已耗尽`

### §7-3 Shared resource excluded from Child strict count

- [ ] Root super admin creates 1 knowledge space with `tenant_id=1` (Root)
- [ ] (Requires F017) F017 writes `tenant:1#shared_to → tenant:<child>#shared_to`
- [ ] Child user queries `/tenants/{child_id}/quota` — `knowledge_space.used` does not include Root's shared resource
- [ ] Confirm via direct DB query: `SELECT tenant_id FROM knowledge WHERE ...` — only Root row has tenant_id=1

### §7-4 Root aggregate 30 + 50 + 20 = 100

- [ ] Child A creates 30 knowledge spaces (all Child A tenant_id)
- [ ] Child B creates 50 knowledge spaces
- [ ] Root creates 20 knowledge spaces
- [ ] GET `/tenants/quota/tree` as super admin
- [ ] `root.usage[knowledge_space].used == 100`
- [ ] `children[child_a].usage[knowledge_space].used == 30`
- [ ] `children[child_b].usage[knowledge_space].used == 50`

### §7-5 Root saturation blocks any Child creation

- [ ] Set Root `quota_config={'knowledge_space': 100}`
- [ ] Create 100 KS across Root+Children to saturate
- [ ] Any Child user attempts create 101st → HTTP 200 + `status_code=19401` with `集团总量已耗尽`

### §7-6 strict_tenant_filter no IN-list leak

- [ ] Enable SQL log (uvicorn `--log-level=debug` or MySQL general_log)
- [ ] Root super admin creates 1 shared KS
- [ ] Child Admin GETs `/tenants/{child_id}/quota`
- [ ] Inspect emitted SQL: `SELECT COUNT(*) FROM knowledge WHERE tenant_id=<child> AND ...` — no `OR tenant_id IN (...)`
- [ ] Returned `knowledge_space.used` reflects only Child's rows

### §7-7 Derived data attribution (⏳ requires F017)

- [ ] Wait for F017 §5.4 to land (ChatMessageService / LLMTokenTracker writes `tenant_id = get_current_tenant_id()`)
- [ ] Child user calls Root shared LLM model
- [ ] After call: `SELECT tenant_id FROM llm_token_log WHERE user_id=<child>` — all rows have `tenant_id=<child>`, not 1
- [ ] GET `/tenants/quota/tree`: Child `model_tokens_monthly.used` increments; Root unchanged

### §7-8 Super admin manually adjusts quota_config

- [ ] PUT `/tenants/{id}/quota` with new `storage_gb=100`
- [ ] Response shows new value
- [ ] GET `/tenants/quota/tree` reflects new limit immediately (no cache)

### §7-9 Delete resource releases quota

- [ ] Child near 100% on knowledge_space
- [ ] Delete 1 knowledge space via UI
- [ ] Next create attempt succeeds

### Additional: unlimited (-1) allows repeated creation

- [ ] Set `quota_config.workflow=-1`
- [ ] Create 30 workflows on Child — none blocked

---

## Executed Results (to be filled during T09)

| Item | Result | Evidence |
|------|--------|----------|
| pytest `test_quota_service*.py` | ⏳ | `.venv/bin/pytest test/test_quota_service.py test/test_quota_service_tenant_tree.py test/test_quota_service_check_chain.py test/test_require_quota_decorator.py -v` |
| pytest `test_e2e_tenant_quota_hierarchy.py` (5 active) | ⏳ | `.venv/bin/pytest test/e2e/test_e2e_tenant_quota_hierarchy.py -v -k 'not skip'` |
| §7-1 Single-tenant 100% | ⏳ | |
| §7-2 Root<Child hardcap | ⏳ | |
| §7-3 Shared not in Child | ⏳ | |
| §7-4 Aggregate 100 | ⏳ | |
| §7-5 Root saturation | ⏳ | |
| §7-6 strict filter SQL | ⏳ | |
| §7-7 Derived data (F017) | ⏳ blocked-by-F017 | |
| §7-8 PUT quota | ⏳ | |
| §7-9 Delete releases | ⏳ | |
| Unlimited (-1) | ⏳ | |

---

## Code-Review Context

- Branch `feat/v2.5.1/016-tenant-quota-hierarchy` branched from `2.5.0-PM`.
- 7 commits T01→T07 (errcode, SQL templates, chain helpers, check_quota rewire, tree API, regression, E2E skeleton); 2 commits docs (spec+tasks baseline, T08).
- No DDL changes (F016 reads existing `tenant.quota_config` JSON only).
- Cross-feature interaction points:
  - F011 DAO: `TenantDao.aget_children_ids_active(root_id)` used by `_aggregate_root_usage`
  - F012 CM: `strict_tenant_filter()` wraps `get_tenant_resource_count` in `_count_usage_strict`
  - F013 FGA: read-only — `tenant:1#shared_to` tuples (written by F017/F020) not created by F016
  - F017: `model_tokens_monthly` SQL template uses `llm_token_log` table; stub-safe when table missing
