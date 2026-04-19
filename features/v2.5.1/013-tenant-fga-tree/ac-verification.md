# F013 AC Verification Record

> Template populated at end of T10. Auto-covered items reference the
> automated tests; items requiring a real OpenFGA store are queued for
> execution on the test server (192.168.106.114) with docker-compose.

---

## Execution Environment

| Layer | Used | Notes |
|-------|------|-------|
| Local mac | partial | syntax + Python smoke; pytest not installed in mac default env |
| Test server (192.168.106.114) | pending | needs `docker compose -p bisheng up -d openfga` then `pytest test/` |
| Real OpenFGA | pending | required for AC-01 CLI verify, AC-10 latency, AC-09 dual-model live switch |

---

## AC ↔ Coverage Map

| AC | Description | Auto Coverage | Manual QA |
|----|-------------|--------------|-----------|
| AC-01 | New authorization model accepted by OpenFGA store | T02 `test_openfga_authorization_model.py` (DSL shape) + T09 `test_ac_01_dsl_v2_structure` | §9.1 — `fga model write --store-id=$STORE_ID --file=<exported>.json` then `fga model get` returns new model_id |
| AC-02 | Super admin short-circuits Child resource access | T08 `test_l1_super_admin_still_short_circuits` + T09 `test_ac_02_super_admin_short_circuits` | §9.2 step 1 — log in as super admin, GET workflow in Child |
| AC-03 | Child Admin accesses own Child resource | T08 `test_l4_child_admin_returns_true` + T09 `test_ac_03_child_admin_accesses_own_child` | §9.2 step 2 |
| AC-04 | Child Admin denied cross-Child resource | T09 `test_ac_04_child_admin_denied_cross_child` | §9.2 step 3 |
| AC-05 | Normal user has no tenant#admin | T07 `test_list_admins_*` + T09 `test_ac_05_normal_user_no_tenant_admin` | §9.2 step 4 — direct fga check returns False |
| AC-06 | Super admin still has no `tenant:1#admin` tuple | T09 `test_ac_06_root_tenant_no_admin_tuple` + T07 `test_list_admins_returns_empty_for_root` | §9.2 step 5 — `fga query check user:1 admin tenant:1` → False; super admin authority via `system:global#super_admin` |
| AC-07 | Business user reaches Root shared resource via shared_to | T09 `test_ac_07_shared_resource_reachable` (mocked); F017 will provide real shared_to writes | §9.3 — needs real F017 deployment; verify Child user sees Root-shared knowledge_space |
| AC-08 | Business user accesses Root non-shared via IN-list | T09 `test_ac_08_root_non_shared_in_list_visible` | §9.3 — Child user with owner permission on Root resource still resolves |
| AC-09 | Dual-model gray release write/check | T05 `test_fga_client_dual_write.py` (5 cases) | §9.5 — toggle `openfga.dual_model_mode=true` + set `legacy_model_id`, write tuple, verify both models receive it via `fga read` |
| AC-10 | Single check P99 < 10ms cached / < 50ms uncached | not auto (mock can't measure real latency) | §9.4 — wrk/locust against real FGA store, 10k tuples seeded |
| AC-11 | Mount Child writes minimal tuples (only Child#admin) | T07 `test_grant_success_for_child_tenant` + T09 `test_ac_11_grant_writes_only_child_admin` | §9.2 step 6 — call `POST /tenants/{child_id}/admins` and inspect `fga read` for Child only |
| AC-12 | Plain Tenant member has no default access to peer resources | T02 `test_resource_manager_excludes_tenant` + T02 `test_resource_editor_excludes_tenant` + T09 `test_ac_12_member_not_in_resource_manager_or_editor` | §9.3 — Child user without owner/dept/group grant cannot read peer's workflow |
| AC-13 | Direct Root admin grant returns 19204 | T07 `test_grant_rejects_root_*` + T09 `test_ac_13_direct_root_admin_grant_rejected` | §9.2 step 7 — `POST /tenants/1/admins` returns 403 + body code 19204 |

---

## Manual QA Checklist (spec §9)

### §9.1 DSL Upgrade

- [ ] Export current authorization_model.py to JSON via `python -c "import json, bisheng.core.openfga.authorization_model as m; print(json.dumps(m.get_authorization_model()))"` > /tmp/model_v2.json
- [ ] Deploy: `fga model write --store-id=$STORE_ID --file=/tmp/model_v2.json`
- [ ] Verify: `fga model get --store-id=$STORE_ID --model-id=$NEW_MODEL_ID` shows tenant.shared_to relation
- [ ] Verify legacy model still readable: `fga model get --store-id=$STORE_ID --model-id=$OLD_MODEL_ID`
- **Status**: ⏳ pending real OpenFGA store
- **Run by**: TBD
- **Result**: TBD

### §9.2 Two-tier Admin Behavior

- [ ] Super admin (system:global#super_admin tuple writer) accesses any Child resource → True
- [ ] Child Admin (tenant:5#admin tuple) accesses workflow with tenant_id=5 → True
- [ ] Child Admin (tenant:5#admin tuple) accesses workflow with tenant_id=7 → False
- [ ] Normal user `fga check user:99 admin tenant:5` → False (no tuple)
- [ ] `fga check user:1 admin tenant:1` → False (Root has no admin tuples)
- [ ] `POST /tenants/5/admins` body `{"user_id": 10}` → success; `fga read tenant:5#admin` returns user:10; `fga read tenant:1#admin` returns nothing
- [ ] `POST /tenants/1/admins` body `{"user_id": 10}` → HTTP 403, response body `{"status_code": 19204}`
- **Status**: ⏳ pending; relies on Tenant Admin endpoint wiring (likely F011 follow-up)
- **Run by**: TBD
- **Result**: TBD

### §9.3 IN-list Visibility

- [ ] Child user (leaf=5) sees Root-shared workflow (tenant_id=1, shared_to writes from F017 mounted)
- [ ] Child user (leaf=5) does NOT see Root non-shared workflow (tenant_id=1, no shared_to write) unless they own / are dept member / are user_group member
- [ ] Child A user (leaf=5) does NOT see Child B workflow (tenant_id=7) under any path except shared_to (which only Root → Child currently writes)
- **Status**: ⏳ pending F017 shared_to writes
- **Run by**: TBD
- **Result**: TBD

### §9.4 Performance

- [ ] Seed 100k tuples (workflow viewer × 10k users × 10 resources sample) into real OpenFGA store
- [ ] Run `wrk -t4 -c100 -d30s` (or similar) against `/api/v1/workflow/{id}` GET endpoint
- [ ] Measure P99 latency:
  - Cached relations (e.g., viewer): < 10ms target
  - Uncached relations (e.g., manager admin-only): < 50ms target
- **Status**: ⏳ pending; requires test server load test setup
- **Run by**: TBD
- **Result**: TBD

### §9.5 Gray Release

- [ ] Set `openfga.dual_model_mode=true` and `openfga.legacy_model_id=<old_id>` in config
- [ ] Restart backend; logs show `FGAClient initialized: ... legacy=<old_id> dual=True`
- [ ] Trigger any tuple write (e.g., create workflow → owner tuple); use `fga read --authorization-model-id=<old_id>` to verify shadow tuple present
- [ ] Verify check still uses new model: temporarily delete a tuple in new model only; check returns False
- [ ] Roll back: set `openfga.model_id=<old_id>`, restart; verify behavior reverts to old model
- **Status**: ⏳ pending; requires real OpenFGA + dual model deployed
- **Run by**: TBD
- **Result**: TBD

---

## Pending Items Summary

All 5 manual QA categories require the test server (192.168.106.114) with running OpenFGA Docker. Recommended sequence on the test server:

1. `cd /Users/lilu/Projects/bisheng/docker && docker compose -p bisheng up -d openfga`
2. SSH to 114, `cd /opt/bisheng/src/backend && .venv/bin/pytest test/test_openfga_authorization_model.py test/test_fga_client_dual_write.py test/test_user_payload_tenant.py test/test_tenant_admin_service.py test/test_permission_service_f013.py test/test_f013_tenant_fga_tree.py -v`
3. Manually walk through §9.1-§9.5 above and tick the boxes; capture log snippets / screenshots in `evidence/` subdirectory if needed.

When done, update statuses above to ✅ + record date + executor handle.

---

## Sign-off

| Reviewer | Date | Outcome |
|---------|------|---------|
| TBD | TBD | TBD |
