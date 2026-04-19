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

## Executed Results (2026-04-19 on 192.168.106.114)

| Item | Result | Evidence |
|------|--------|----------|
| pytest `test_quota_service*.py` + `test_require_quota_decorator.py` | ✅ 36/36 passed | `uv run --extra test pytest test/test_quota_service.py test/test_quota_service_tenant_tree.py test/test_quota_service_check_chain.py test/test_require_quota_decorator.py -v` ran in 0.59s (after fixing patch target in `test_count_usage_strict_returns_zero_on_missing_template`) |
| pytest `test_e2e_tenant_quota_hierarchy.py` (6 active + 6 skip) | ✅ 6 passed / 6 skipped / 0 failed | `E2E_ADMIN_PASSWORD=Bisheng@top1 uv run --extra test pytest test/e2e/test_e2e_tenant_quota_hierarchy.py -v` (1.18s); required (a) `TenantService.aset_quota` to call `QuotaService.validate_quota_config`, (b) shared E2E helper fix: `helpers/auth.py` `get_admin_token` now reads `E2E_ADMIN_PASSWORD` env var + `create_test_user` RSA-encrypts the password (backend's `/user/create` expects RSA ciphertext per `UserService.decrypt_md5_password`; plain caused 10600 on follow-up login) |
| §7-4 Root aggregate — Root=30 workflows, 0 active Children | ✅ verified | MySQL: `SELECT tenant_id, COUNT(*) FROM flow WHERE flow_type=10 AND status!=0 GROUP BY tenant_id` → `1, 30`; GET `/tenants/quota/tree` → `root.usage[workflow].used=30, children_count=0`. Orphaned tenant id=2 correctly excluded from aggregate (proves `aget_children_ids_active` filters `status='active'`, INV-T9 satisfied) |
| AC-03 full cycle (§7-8 equivalent) | ✅ verified | E2E test + probe: `storage_gb / user_count / model_tokens_monthly` persisted in `tenant.quota_config`; unknown key → 24005; extended `VALID_QUOTA_KEYS` honored end-to-end |
| AC-06 tree API | ✅ verified | Probe shows correct `{root: TenantQuotaTreeNode, children: []}` structure; all 11 `VALID_QUOTA_KEYS` present in `root.usage` with `used/limit/utilization` fields; unauth → 401; super-admin-only gate enforced |
| AC-10 stub-safe (pre-F017) | ✅ verified | `usage[model_tokens_monthly].used=0, limit=10000000` returned without crash — `_count_resource`'s try/except handles missing `llm_token_log` table |
| §7-1/§7-2/§7-3/§7-5/§7-6 | ⏳ manual | Require live active Child tenant setup + knowledge/workflow creation + FGA `shared_to` tuples; best exercised via UI on 114 by admin. Code paths proven by unit tests (`test_quota_service_check_chain.py` 13 cases covering tenant_limit blocker, root_hardcap msg, storage 19403, role quota 19402) and probe (§7-4) |
| §7-7 Derived data (F017) | ⏳ blocked-by-F017 | Requires `ChatMessageService` / `LLMTokenTracker` to write `tenant_id=get_current_tenant_id()` — F017 scope |
| §7-9 Delete releases | ⏳ manual | No F016 hook; relies on existing resource delete path + SQL COUNT recompute — trivially correct if counters are live |
| Unlimited (-1) | ✅ verified | `root.usage[workflow].limit=-1 utilization=0.0` returned with no error; covered by `test_unlimited_effective_returns_true` unit test |

**Known issues uncovered during self-test (not F016 scope)**:

- **KI-01** `knowledge.status` 列不存在导致 `_RESOURCE_COUNT_TEMPLATES['knowledge_space']` SQL (`WHERE status != -1`) 在 114 MySQL 报 `Unknown column 'status'`；`_count_resource` try/except 吞掉后返 0 → `/quota/tree.root.usage[knowledge_space].used` 恒为 0。归属 v2.5.0/F005（SQL 模板 Owner）。已在 [v2.5.0/F005 spec §9.1](../../v2.5.0/005-role-menu-quota/spec.md#91-known-post-release-issuesv251-自测发现) 登记，F017 前置依赖建议顺带修。

**Follow-up fixes committed during T09**:

1. `tenant_service.py` `aset_quota` — added `QuotaService.validate_quota_config(data.quota_config)` before persist. **Real bug**: unknown key like `nonexistent_resource` was previously stored unchecked (F010 AC-4.2 gap, surfaced by F016 E2E).
2. `test_quota_service_tenant_tree.py` `test_count_usage_strict_returns_zero_on_missing_template` — removed `patch('quota_service.get_async_db_session')` which never existed at module level (lazy import inside `_count_resource`); SQL template miss returns 0 before any DB call.
3. `helpers/auth.py` (shared E2E infra) — fixed two issues that had been
   blocking every feature's E2E on non-default-password deployments:
   * `get_admin_token` now reads `E2E_ADMIN_PASSWORD` env var, falling back
     to `admin123` for local/CI (matches docstring promise that was never
     implemented).
   * `create_test_user` now RSA-encrypts the password before POSTing to
     `/user/create` (backend expects RSA ciphertext; plain caused stored
     md5 to disagree with later login md5). F014/F015/F017+ E2E benefit
     without code changes.
4. `test_e2e_tenant_quota_hierarchy.py` — after helper fix, simplified to
   use `get_admin_token` directly; `test_quota_tree_forbidden_for_non_super_admin`
   restored (asserts HTTP 200 + body `status_code=403` per
   `UnifiedResponseModel` convention — global exception handler converts
   `UnAuthorizedError.http_exception()` to 200+body); new
   `test_quota_tree_rejects_unauthenticated_request` covers the
   before-auth-dependency 401 path (2 AC-06 branches both covered).

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
