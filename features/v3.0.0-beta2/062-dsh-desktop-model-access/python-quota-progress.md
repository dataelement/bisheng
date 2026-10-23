# Python quota implementation handoff — 2026-09-09

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

Scope: T046–T053; expanded by the coordinating agent to T062–T065 and T076–T077, plus T089 usage reads and production quota activation. Shared `tasks.md` and `design.md` are intentionally left to the coordinating agent.

## Implemented

- `domain/schemas/usage.py`: complete, validated request events; NULL usage is unresolved, reliable terminal usage has an evidence source, UTC timestamps, immutable admission identity. Internal reconciliation operation/generation fields do not alter client API 0.1.0.
- `domain/repositories/usage.py`: caller-owned SQL transaction; policy-row locks serialize concurrent first request/month insertion; request-version merge, same-version conflict detection, terminal-before-running delivery, monthly model deltas once per batch. No direct Service SQL and no vendor-specific upsert. `persisted_usage`, `new_month_proof`, `recovery_snapshot` are tenant-scoped read/proof methods.
- `infrastructure/quota_redis.py` and Lua scripts: user hash-tagged keys, no expiry/reservation, actual admission, exact decimal int64 accumulation (avoids Lua double rounding), UNKNOWN per-request reasons across months, complete Stream snapshots, version/ownership CAS. A persistent write-in-progress gate prevents other processes admitting after a partial Lua failure. Duplicate admission returns `request_already_started`, never permission to resend upstream.
- Policy integration: `ensure_new_user`, `block_policy`, `install_policy`, `finish_policy`; SQL version-zero ownership proof is mandatory for new users. A policy install retains historical model counters and only adds zero-valued model counters after verifying component sum equals user total. Old lease generations cannot finish another worker's operation. UNKNOWN reasons remain.
- New month initialization: SQL proves no monthly requests/summaries; an approved live ledger, permanent initialized-month marker, and Redis request/Stream history are independently checked. A missing previously initialized month fails closed. Initialization preserves UNKNOWN reasons.
- `quota_topology.py`: dedicated physical Redis connection, retries disabled, reconnect forbidden after approval, run-id/role/AOF/noeviction checks. Use `create_quota_redis(url)`; normal `Redis.from_url` is deliberately rejected.
- `quota_recovery.py`, `quota_operations.py`, `quota_activation.py`: SHA-256 checked immutable evidence; SQL/Stream subset validation; reconstruction by original month; RUNNING becomes UNKNOWN; user/month counters and epoch restore; shared immutable MinIO approval publication. Every API/Worker activates from the same explicit object version and digest. Old run-id approval cannot authorize a restarted primary.
- `services/projection.py`: batches ≤500, PEL claiming, commit-before-XACK, repeat-delivery idempotency, tenant/user partition validation, timed-out RUNNING inspection. Admission Lua independently reads Stream/PEL lag so a completely stopped Worker cannot leave admission open indefinitely.
- `services/reconciliation.py`, `repositories/reconciliation.py`, `evidence_store.py`: current administrative authorization, immutable request-level evidence, SQL operation ownership, Redis lease-generation fencing, reliable settlement once, wait for SQL projection before SUCCEEDED. The request retains `reconciliation_operation_id` for permanent audit. A known cancellation remains CANCELLED; an indeterminate result becomes FAILED. Revoked authorization leaves the unresolved request frozen.
- CLI: `python -m bisheng.dsh.cli.reconcile submit|status` and `python -m bisheng.dsh.cli.quota initialize|recover`. Both require `--tenant-id`; administrator JWT is read with `getpass`, never accepted on argv. CLI outputs only operation status/audit completion fields or approval object reference/digest.
- Worker adapters: trusted tenant header must exactly match payload, ContextVar restored in `finally` on both success/failure. Registration functions are supplied; shared worker startup is owned by the coordinating agent.

## Verification

Red evidence was recorded before each implementation: missing usage repository, missing quota module, missing settlement script (4 failures), missing recovery service, missing projection service, missing reconciliation repository and CLI.

Focused suite: **47 passed** against real MySQL 8 at the isolated local `dsh_test_quota` database plus real Redis 7.2.7 DB15, with AOF and noeviction. This includes real concurrent first-month insertion, SQL rollback, lost ACK/redelivery, 900+300+300=1500, repeated settlement, UNKNOWN independent unfreeze, int64 >2^53, stale reconciliation workers, bad Redis types, stopped projector backpressure, physical reconnect closure, incomplete recovery evidence rejection, tenant headers, and CLI input restrictions. Final UTC normalization received the same focused suite rerun; see coordinating agent's latest tool evidence.

Tests require explicit test Redis environment. MySQL fixture checks the exact local host/port/database and proves the three managed tables absent before creation; it removes only those newly created tables. Initial auto-review rejected pre-test table deletion; a read-only empty-database inspection and this safer fixture resolved the issue. No existing application tables were modified.

Ruff and architecture guard pass on scoped files. Both CLI `--help` commands run without loading application YAML. No commits or pushes.

## Required coordinating integration

- `reconciliation_cli_runtime()` is an async context manager in `bisheng.dsh.runtime`; yield `.reconciliation`, async `authenticate_admin(jwt, *, tenant_id)`, and async `recover_quota(...)`. Authentication must verify a current global super-admin and the selected active tenant; runtime teardown restores all tenant/admin ContextVars.
- `register_usage_tasks(app, projection_runtime_factory)` expects a context manager yielding `DshProjectionService`.
- `register_reconciliation_tasks(app, runtime_factory)` expects a context manager yielding `.reconciliation`.
- Invoke `repository.new_month_proof(user_id, month)` + `quota.ensure_month(..., proof=...)` only through the controlled month-initialization path. Normal `read_usage`/admission never inserts missing balances.
- Usage DTO: `used`, `limit`, `remaining`, `source` (`live` or `sql_estimate`), `as_of`, `quota_state` (`ready`, `blocked`, `unavailable`), `models`. HTTP layer adds month/timezone/reset boundaries and maps frozen wire enum values. A missing trustworthy SQL snapshot raises, rather than fabricating zero.
- Sync Design's internal model column `dsh_model_call.reconciliation_operation_id` and internal Stream `operation_generation`. The eight-table and 26-HTTP-interface counts remain unchanged.

## Material limits / pending evidence

- DM8 runtime execution was explicitly waived by the user for this iteration. Business persistence remains SQLAlchemy/SQLModel ORM; no MySQL-specific business SQL was introduced.
- Production MinIO credentials/versioning/ACL and externally verifiable fencing/AOF completeness remain operational requirements; fake object adapters in unit tests do not prove real MinIO deployment.
- Legacy embedded manifests retain a 10,000-event bound. The sharded path supports larger complete inventories: 500 events / 4 MiB per shard, root/index up to 32 MiB, SQL/Stream pages of 500, and fenced Redis write batches of 500. Complete inventory memory must fit the recovery process; it is not a constant-memory streaming merge.
- The production CLI factory and Celery registration are implemented and import-tested. Real MinIO/FGA/Gateway startup and full client E2E still require the deployment environment; the scoped module suite does not claim those external checks.


## Production runtime and scheduler assembly

- `operations_runtime.py` provides `reconciliation_cli_runtime()` (re-exported by the shared runtime), `operations_worker_runtime()`, `projection_worker_runtime()`, `administration_worker_runtime()` and `close_operations_worker_runtime()`. Runtime objects persist across Celery tasks on the existing worker event-loop bridge. An activation attempt is latched; reconnect cannot reuse an old approval. Shutdown closes the owned clients.
- CLI authentication reuses `AuthJwt` signature/expiry validation and `LoginUser`, checks fresh SQL token version/membership, verifies current global authority through the permission API, validates the selected active tenant, then binds and restores tenant/admin/visible/bypass/strict context variables. Authentication failures leave the previous context intact.
- `worker/dsh/registry.py` registers seven DSH tasks via existing `worker/__init__.py`; `worker/config.py` schedules projection scans every 5 seconds, orphan inspections every 60 seconds (RUNNING timeout 1 hour), durable operation scans every 5 seconds, and profile repairs every 30 minutes. Existing task imports remain exported.
- Real subprocess import of `bisheng.worker` confirms all seven task names and four Beat entries; the existing JWT signer/decoder accepts a genuine signed token and rejects a changed signature. Additional tests verify stale administrator tokens, non-global authority, selected-tenant restoration, and denied reuse of failed topology approval.
- Usage snapshots now include internal `unknown_pending`, counting every UNKNOWN blocker across months without exposing request identifiers. SQL fallback reports a cross-month count with `source=sql_estimate` and `quota_state=unavailable`; client wire serialization remains frozen.


## First-install and large-inventory recovery verification

- Ordinary first UPDATE_POLICY creates an immutable SQL operation and disabled version-zero placeholder before activation. A missing approval leaves PROCESSING without committed policy or a Redis gate; controlled empty initialization then allows the same operation to finish after approval distribution/restart. `test_quota_bootstrap.py` proves this with real MySQL and Redis.
- `RecoveryManifest.shards` and `RecoveryShard` support immutable ordered object descriptors, exact shard/total counts, per-object SHA and canonical full-inventory SHA. Missing, duplicate, wrong-order or corrupted evidence is refused before writes.
- `quota_restore.py` and `recover_shard.lua` keep the shared gate FROZEN through bounded writes, preserve unrelated blockers, inspect every surviving request/Stream event, and fence every batch by recovery owner/cursor. Lost intermediate or final responses can resume the same audited inventory.
- SQL recovery snapshot uses keyset pages instead of the former 10,001-row ceiling. `complete_recovery` atomically updates the policy quota epoch only if policy version/limit/models/owner/previous epoch still match; failed CAS re-freezes Redis and prevents approval publication.
- Real MySQL+Redis tests restore **10,001 reliable request records** and exact total usage, verify SQL epoch advancement, refuse missing/hash/duplicate/full-digest/index errors, and resume lost intermediate/final write responses. The scoped suite including production registration/authentication contains 47 passing cases.

Final supplemental SQL check: `test_usage_repository.py` reports **6 passed** on real MySQL after adding a stale-policy recovery-epoch CAS regression. This adds one case to the earlier full 47-case run; production code changes after that full run were documentation only.


## T113 independent-process local acceptance

`test_dsh_failure_acceptance.py`: **1 passed** with real Redis DB15, MySQL and a new versioned MinIO bucket. Seven independent processes exercised missing/tampered approvals, physical-disconnect activation latch, twelve durable settlements followed by process exit, twelve idempotent settlement replays, SQL commit-before-ACK exit, and replay of all 24 pending events in a new process. Redis and SQL remained at exactly 84 tokens; pending returned to zero. Timing method, actual samples and excluded production/SLA claims are recorded in `recovery-acceptance.md`. No production code was changed for this acceptance addition.


## Completion-review repairs (2026-09-09, supersedes earlier scoped totals)

The review identified implementation gaps, rather than classifying them as deployment-only checks. These are now addressed:

- Recovery reconstruction stays FROZEN until the SQL policy epoch CAS commits. READY requires a matching owner/full-manifest digest/version/epoch receipt; a stale owner cannot finish another recovery. Admission rejects an event whose SQL epoch differs from the approved topology epoch. Legacy and sharded recovery inspect surviving request hashes as well as Stream records.
- Uncertain settlement uses a separate control connection that may confirm only the original run ID/master and exact complete terminal event, or add a persistent UNKNOWN blocker. RUNNING can transition atomically to UNKNOWN with a Stream event on that same proven primary. Unknown/new primaries cannot confirm success or reopen the gate. Other already-running requests still settle.
- Finite memory budget/headroom and configurable event/age limits are evaluated by one shared read-only Lua pressure function in admission and live display. `maxmemory=0` does not mean unbounded safe capacity. Pressure denials emit a bounded structured warning (`event=dsh_quota_backpressure`); deployment alert routing remains operational configuration.
- Per-user RUNNING sorted index/count replaces repeated per-user full-keyspace inspection. Missing/inconsistent metadata closes admission and inspection. Recovery converts all retained RUNNING to UNKNOWN, rebuilds the index, and recomputes retained Stream counts from every surviving/reconstructed event, including legacy data.
- SQL commit precedes an exact event/time projection confirmation, followed by ACK. Bounded cleanup requires a reliable terminal, identical SQL-confirmed event, elapsed retention, all consumer groups' delivery/ACK and retained-event count. It preserves UNKNOWN, RUNNING, PEL, missing proof and SQL audit/monthly rows; request hashes remain until their final retained event is removed.
- User projection tasks drain at most configured batches/time between transactions, then yield and dispatch continuation; owner leases coordinate replicas. Global scan chains carry a distinct fenced owner/cursor, and the low-frequency inspection scan also cleans quiet partitions. SQL event-version idempotence remains authoritative if a stalled batch outlives its lease.

### Actual validation

- First recovery/settlement tests initially failed in three cases; after repairs the cross-replica safety suite passed five real Redis/MySQL tests.
- Capacity and backlog tests initially failed twice because admission ignored the new thresholds; final maintenance suite includes eight cases covering those regressions, 503-event continuation, legacy/missing index handling, cleanup PEL ordering and post-cleanup availability.
- Final grouped quota/reconciliation/production-worker/cross-process suite: **62 passed in 49.47 seconds**, no failures or skips, using isolated real Redis DB15, empty dedicated MySQL schema, and versioned MinIO objects. This includes the 10,001-record sharded recovery and seven-process failure test. It deliberately excludes the separately passed owned Redis lifecycle tests.
- Owned Redis actual restart and replica promotion: **2 passed in 8.93 seconds** in the earlier isolated lifecycle run. Old READY data plus old approval is rejected; new complete MinIO evidence, SQL epoch CAS and immutable approval permit epoch-two admission. Only test-owned PIDs were terminated; shared port 16362 was untouched.
- Configuration and foundation contracts: **12 passed in 5.00 seconds**. New `test_config_contracts.py` verifies disabled defaults/invalid capacity rejection and enabled API/worker factory parity in an isolated subprocess with a test YAML; no Redis connection is opened by construction.
- Scoped Ruff check and format check pass. Full Java/front-end results are owned by root; root reports Gateway **48 tests plus package**, platform **42 tests plus lint/typecheck/i18n** at this checkpoint. No DM8 or deployment performance result is implied.

### Exact changed areas in this review follow-up

`src/backend/bisheng/dsh/config.py`, `runtime.py` and `operations_runtime.py` (quota parameters only); `domain/services/{projection,quota_recovery,quota_operations}.py`; `infrastructure/{quota_redis,quota_restore}.py`; `infrastructure/lua/{admit,settle,read_usage,initialize_user,recover,recover_shard,finish_recovery,quarantine,pressure,confirm_projection,cleanup}.lua`; `src/backend/bisheng/worker/dsh/{usage,registry}.py`; `src/backend/test/dsh/test_{quota_admission,quota_recovery,quota_safety_review,quota_maintenance,quota_primary_failure,config_contracts}.py`.

Operational defaults and bounds are in `quota-operations.md`; lifecycle evidence and remaining deployment gates are in `recovery-acceptance.md`. DM8 runtime was explicitly waived by the user for this iteration; deployment fencing/concurrency/performance evidence remains separate from local regression results. Shared Design/tasks/HTML/completion/code-review documents remain root-owned. No commit or push was performed.


## User-confirmed per-model allowance revision

Canonical policy is now the root-owned strong `DshModelQuotaConfig` list. Updated quota installation, admission Lua, recovery manifests/receipts, SQL recovery CAS, new-month proofs, and live/SQL usage snapshots to bind each model's individual allowance. Aggregate allowance is informational only; deleted model usage remains in history and does not consume another model's configured allowance. No rate-limiting fields or behavior were introduced. UNKNOWN still blocks the whole user conservatively; in-flight requests continue to settle after limit reductions/model removal.

Changed implementation paths in this revision: `domain/repositories/usage.py`, `domain/services/{quota_recovery,quota_operations}.py`, `infrastructure/{quota_redis,quota_restore}.py`, and `infrastructure/lua/{admit,policy,read_usage,initialize_month,recover,recover_shard}.lua`. Root-owned Schema/ORM/policyRepository/admin_runtime/core Settings were not edited.

Migrated quota fixture and recovery/first-install/lifecycle/cross-process tests to the canonical configuration. New `test_model_quota.py` covers independent limits, zero limit, concurrent actual excess, removed/lowered-model history, full recovery CAS despite identical totals, legacy aggregate-proof rejection, SQL remaining semantics, exact new-month configuration, and settlement of a model removed after admission.

Actual validation: the updated real Redis15/MySQL/MinIO combined quota/worker/recovery/cross-process/lifecycle suite passed **68 tests in 40.47s**. That run included the first four new per-model cases. A subsequent `test_model_quota.py` run passed **7 tests in 1.26s**, including the additional SQL/month/removal checks. Results are separate scopes and are not summed as independent executions. The MySQL test schema was empty before fixture creation; no preexisting tables were deleted or safety gates relaxed. Gateway SQL/DM compatibility review belongs to the separately assigned agent; no Gateway file was changed by this quota task.
