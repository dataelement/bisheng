# DSH quota operator workflow

Only a current global super-administrator may select a target tenant. The CLI prompts for the current administrator JWT without echo. Evidence is stored in a controlled, versioned MinIO bucket; no local file is recovery authority.

## Normal user/month creation

An existing approved quota primary is required. A first UPDATE_POLICY operation owns a SQL version-zero placeholder and produces a proof that no SQL usage exists. `ensure_new_user` independently rejects Redis request/Stream history before installing version zero, limit zero. The ordinary policy operation then installs version one and its model/limit configuration. Subsequent users do not need disaster-recovery CLI commands.

At a billing-month transition the controlled initializer obtains `DshUsageRepository.new_month_proof`, verifies no current-month Redis history and no prior initialized-month marker, and atomically creates the month. Unknown-usage audit records from older months remain; they do not block admission. Deleting a month key is never a way to reset usage.

## Initial shard approval or audited recovery

1. Close affected admission, isolate the old primary, and obtain a documented fencing attestation. Verify the target primary uses noeviction and AOF. Preserve AOF/Stream evidence before changing data.
2. Store a complete audited request-event array as an immutable evidence object. Store a `RecoveryManifest` object with its exact object version/digest, target Redis `run_id`, increased `epoch`, previous epoch, tenant/user IDs, current committed SQL row versions (`model_versions`, including disabled rows), their sum as `policy_version`, and active model configuration objects (each model ID and its independent monthly token limit), billing month, and request count. For first initialization the inventory is empty, previous epoch is zero, and the SQL placeholder row may be version zero with empty `model_configs` and `model_versions` containing that model at version zero. Existing data always uses recovery, never initialize.
3. Run one of the following in the configured backend runtime. Replace angle-bracket placeholders with the reviewed objects; JWT is entered only at the prompt.

```sh
python -m bisheng.dsh.cli.quota initialize --tenant-id <tenant> --manifest-object <object-key@immutable-version> --manifest-sha256 <sha256> --isolation-attestation <operations-case>
python -m bisheng.dsh.cli.quota recover --tenant-id <tenant> --manifest-object <object-key@immutable-version> --manifest-sha256 <sha256> --isolation-attestation <operations-case>
```

4. The service verifies current authority, the manifest digest, exact SQL policy, retained SQL detail/month-summary consistency, and surviving Stream coverage. A lost or unprovable tail stays closed. Restored RUNNING requests become UNKNOWN; UNKNOWN records remain diagnostic only across months.
5. Successful recovery publishes a new immutable topology approval in MinIO and prints its `object` and `sha256`. Set `dsh.quota_approval_object` and `dsh.quota_approval_sha256` on every API and Worker to that exact reference/digest; the production factories call `activate_from_approval`. Each process pins its own physical Redis connection to the approved run-id/epoch. Automatic reconnect cannot approve a new primary.
6. Verify live usage, pending Stream projection, UNKNOWN counts, and current epoch before allowing client traffic. No force-unfreeze or estimated settlement option exists.

Legacy embedded event arrays retain a 10,000-request bound. Larger inventories use the complete sharded format below; there is no 10,000-request total limit on that path. The root manifest/audit index is bounded to 32 MiB, each event shard to 500 requests and 4 MiB, and per-request reconciliation evidence to 1 MiB. SQL and Redis are scanned in bounded pages without truncating retained history.

## UNKNOWN request reconciliation

Store an immutable per-request provider record containing local request ID, provider request ID if present, original model/start time and reliable input/output/total tokens. An aggregate invoice is insufficient. Compute its SHA-256 and submit:

```sh
python -m bisheng.dsh.cli.reconcile submit --tenant-id <tenant> --request-id <request> --operation-id <operation> --expected-event-version <version> --evidence-object <object-key@immutable-version> --evidence-sha256 <sha256> --input-tokens <measured-input> --output-tokens <measured-output> --total-tokens <measured-total> --reason <provider-case>
python -m bisheng.dsh.cli.reconcile status --tenant-id <tenant> --operation-id <operation>
```

PROCESSING may mean the usage was already applied in Redis and is awaiting SQL projection. Resume the same operation; never create a replacement request or call the model again. SUCCEEDED requires SQL projection confirmation. Only that request is removed from the unknown-usage diagnostic index. UNKNOWN never blocks new calls; independent policy or storage recovery gates still apply. Reconciliation is optional.


## Runtime and worker configuration

Run the commands from the backend environment with the same `config` YAML path and database/object-storage configuration used by the application. `reconciliation_cli_runtime` initializes and closes the application contexts and registers the existing permission runtime. The selected tenant is explicit; it is never inferred from the global administrator's Root tenant.

With `dsh.enabled: true`, the existing Celery worker imports all DSH tasks. Run the normal worker and Beat entry points; no separate DSH process is required. Beat schedules projection and durable-operation scans every 5 seconds, orphan inspection every 60 seconds, and profile directory repair every 30 minutes. Orphan inspection marks RUNNING requests older than one hour UNKNOWN; it never retries an upstream model invocation. Each partition task receives a checked tenant header and restores tenant scope when it finishes.

After an approval or quota Redis connection failure, stop admission and complete controlled recovery before distributing the new immutable approval reference and restarting affected runtimes. A running process cannot silently reconnect and reapprove itself from the failed approval. MinIO bucket versioning, narrowly scoped credentials and retained immutable evidence remain deployment requirements.


## First installation with no SQL policy or approval

1. Enable the configured DSH feature and submit the first ordinary administrator UPDATE_POLICY request with `expected_version=0` and a new operation ID. The SQL transaction commits an immutable intent and disabled version-zero policy (`monthly_token_limit=0`, `enabled=0`, `PENDING`) before any Redis activation attempt. With no approval, the operation remains PROCESSING with `committed_at=null`; no model call is admitted.
2. Prepare the audited empty inventory and a manifest for this same tenant/user, SQL policy version zero, empty `model_configs`, and `model_versions` containing every placeholder model at version zero, previous epoch zero and epoch one. Run `quota initialize` as a current global administrator for that tenant. No hand-written SQL is needed.
3. Distribute the returned immutable approval object and SHA-256 in configuration, restart API/worker runtimes, and let the durable worker resume the same operation after its lease/retry becomes due. It installs policy version one, preserves the original operation ID, and clears only its own POLICY_SYNC blocker.

The automated bootstrap test exercises this sequence with fresh policy tables and empty Redis keys, including the failed initial activation and successful same-operation continuation.

## Complete sharded inventory format

For a sharded manifest, omit `events` (or use `[]`) and include `shards`, `request_count`, and `inventory_sha256`. Each shard descriptor contains `index` (contiguous, zero based), immutable `object`, SHA-256 `sha256`, and exact `request_count` (1–500). The `evidence_object` points to a separately retained audit index whose JSON is exactly `{request_count, inventory_sha256, shards}`; `evidence_sha256` covers its raw bytes. Root manifest and all referenced objects must use the controlled tenant-scoped versioned object path.

Every shard contains a JSON array of complete UsageEvent records. Sort the entire audited inventory by `request_id` and then divide it into consecutive shards. The total digest is SHA-256 of the concatenation of `UsageEvent.model_validate_json(json.dumps(record)).model_dump_json() + "\n"` in that order, encoded as UTF-8. This canonicalizes timestamps and optional fields through the same strict schema used for recovery. A missing/extra shard, noncontiguous index, wrong per-shard or total count/digest, duplicate or unordered request, foreign tenant/user, or omitted SQL/Stream survivor causes rejection.

Recovery first validates every immutable shard and all retained SQL details/month totals. It then freezes the shared user gate, checks surviving Stream and request records, writes month counters and request batches of at most 500, and keeps the gate FROZEN until the last batch. Each Redis phase checks the recovery owner and cursor; interrupted batches can resume from the same unchanged audit, including a lost final response. RUNNING records become UNKNOWN. Redis reconstruction leaves the user FROZEN. The service first commits the SQL policy epoch with a policy/owner CAS, then publishes READY only through a Redis receipt CAS over recovery owner, full-manifest digest, policy version and epoch, and finally publishes the immutable topology approval. A changed SQL policy or stale recovery receipt leaves the user closed.

The complete inventory is retained in the recovery process for cross-source comparison, so memory must fit the audited user history; allocation/read failures fail closed. This path bounds individual object reads, SQL/Stream pages and Lua writes; it does not claim constant total memory. Allow projection workers to consume the reconstructed Stream and verify backlog before reopening admission.


## Capacity, retention, and bounded maintenance

All API and worker processes must use the same capacity settings. Capacity is a storage safety margin, independent of token accounting; it neither reserves tokens nor subtracts from actual usage.

| `dsh` setting | Default | Purpose |
|---|---:|---|
| `quota_memory_budget_bytes` | 536870912 (512 MiB) | Finite budget for the dedicated Redis process |
| `quota_memory_headroom_bytes` | 67108864 (64 MiB) | Space left for in-flight settlement and recovery/control writes |
| `quota_backlog_high_watermark` | 10000 | Per-user unread plus pending Stream event stop threshold |
| `backlog_stop_seconds` | 30 | Oldest unread/pending event stop age |
| `quota_retention_seconds` | 2592000 (30 days) | Minimum retention after exact SQL projection confirmation; configurable minimum one day |
| `quota_projection_max_batches` | 10 | At most ten batches of 500 events in one user task |
| `quota_projection_max_seconds` | 1.0 | Yield after a completed batch when its task time budget is reached |

Admission and live usage display execute the same atomic Redis memory/backlog calculation. The effective memory budget is the smaller of the configured budget and Redis `maxmemory` when positive. `maxmemory=0` does not bypass the configured finite budget. Used memory at budget minus headroom denies new admission and displays unavailable; pressure rejection emits a structured `dsh_quota_backpressure` warning for operational alert routing; settlement continues independently of those thresholds. Size headroom for the measured peak in-flight population; a finite margin is not proof against arbitrary concurrency or an externally full disk. Redis errors and incomplete Lua writes still fail closed, and uncertain settlement uses a separate connection that may only confirm the exact terminal event on the original approved primary or add a persistent STORAGE_UNCERTAIN blocker for unconfirmed ledger writes. It cannot approve another primary or remove a freeze.

Admission maintains a per-user RUNNING sorted set plus a gate count. Terminal/UNKNOWN settlement removes the index member; recovery converts all retained RUNNING to UNKNOWN and rebuilds an empty, marked index. Missing or mismatched index/count rejects new admission and inspection, instead of silently omitting in-flight requests. Inspection reads at most 100 expired IDs per task and resumes through the queue, rather than scanning every Redis key for each user. Existing pre-index ledgers require controlled evidence recovery; never invent an empty index in a live deployment.

Projection commits SQL before writing an exact event confirmation and Redis server timestamp, and ACK remains later. Cleanup scans at most 100 Stream entries per maintenance pass, keeping a cursor. It may delete an event only when the request is a reliable terminal, its exact event has SQL confirmation older than retention, every consumer group has delivered and ACKed that entry, and a retained-event count is present. The request hash stays until its last retained event is deleted; this also protects an older PEL event when a newer terminal event was already ACKed. UNKNOWN, RUNNING, unconfirmed, unacknowledged and legacy records without proof remain. Controlled recovery recomputes retained-event counts from the full surviving/reconstructed Stream before publishing READY, including pre-count legacy history. SQL audit rows and monthly counters are never deleted. Cleanup errors preserve data; they do not weaken proof requirements.

A projection task holds an owner lease, completes bounded batches, and queues a continuation when fresh backlog remains. Beat still discovers partitions every five seconds. Global projection/inspection scans use distinct owner leases with cursor continuation, preventing repeated Beat ticks from starting overlapping scan chains; stale scan owners stop. The 60-second inspection pass also runs retention cleanup for quiet users. Lease expiry after a stalled process permits recovery; SQL version idempotence and commit-before-ACK remain the correctness guards if a stalled batch outlives its lease. Task time bounds apply between SQL batches, not by aborting an in-progress SQL transaction.


## Independent per-user/model monthly allowances

SQL authority is one `dsh_user_policy` row per tenant/user/model. The transient recovery manifest field is `model_configs: [{model_id, monthly_token_limit}, ...]`, validated through `DshModelQuotaConfig`. A model ID appears once, each limit is a nonnegative int64, and the informational sum fits int64. This phase has no RPM, concurrency-rate or other rate-limiting configuration.

Redis keeps each configured limit separately as `limit:<model_id>` in the user gate. Admission compares only the selected model's actual current-month counter to that limit. A zero allowance denies that model's new requests. An exhausted or removed model cannot spend another model's allowance, and its historical usage does not deny other configured models. No allowance is reserved at request start. Previously admitted requests settle actual usage even if the policy subsequently lowers their limit or removes the model; the resulting excess remains recorded.

Internal live and SQL-estimate snapshots return `models` (all retained model usage) and `model_limits` (current configured limits). `used` includes historical removed-model usage; `limit` is only the informational sum of current model allowances. `remaining` is the sum of `max(model_limit - model_used, 0)` over current configured models, so it can be positive even when historical aggregate `used` exceeds current aggregate `limit`. Client serialization is handled by the API contract layer. UNKNOWN only marks missing usage in call details; it never freezes any user or model.

Recovery manifests must contain complete active `model_configs` and `model_versions` for every SQL row, including revoked/placeholder rows; the old `monthly_limit` plus `model_ids` format is rejected. Immutable manifest digests, SQL policy CAS, same-version Redis policy replay and new-month proofs bind every model/limit pair. Two configurations with identical model IDs and aggregate allowance but swapped individual allowances are different policies and cannot reuse an old proof. Audited recovery preserves all model histories and rebuilds each configured limit independently. Existing aggregate-only Redis ledgers require a controlled recovery from a reviewed per-model SQL policy and new-format proof; limits are never guessed by splitting an old aggregate.
