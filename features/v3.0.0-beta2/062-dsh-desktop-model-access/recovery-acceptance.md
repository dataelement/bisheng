# T113 local failure and visibility acceptance

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

Date: 2026-09-09. Implementation branch: `feat/3.0.0-beta2-pre`.

## Executed environment and scope

The test ran against real local Redis 7.2.7 (isolated DB15, AOF, noeviction), real MySQL 8 (`dsh_test_quota`), and a dedicated MinIO service with a newly created versioned bucket. It used seven independently launched Python processes plus the pytest controller. No production endpoints or stores were used. Test cleanup removed only its own SQL fixture tables, Redis prefix and object bucket.

`test/dsh/test_dsh_failure_acceptance.py` passed: **1 passed in 4.65s**. Semantic assertions do not depend on elapsed-time thresholds.

## Failure observations

| Fault / boundary | Executed check | Observed result |
|---|---|---|
| No approval in fresh process | Construct production OperationsRuntime without configured shared approval | Activation denied; topology remained closed |
| Wrong approval digest in fresh process | Read the actual immutable MinIO approval version with a changed expected digest | Activation denied |
| Existing process loses physical Redis connection | Disconnect its real connection pool after activation, then read quota and try activation again | Read failed closed; the runtime latch rejected reuse of its old approval |
| Settlement process exits after durable writes | Twelve actual Lua settlements completed, then the independent process exited with status 23 before returning normal success | Redis retained all settlements; exactly 84 tokens |
| New process repeats the same settlements | A separate process read the configured immutable MinIO approval and retried the twelve original request/version payloads | Usage remained 84; Stream retained exactly 24 events (12 admissions + 12 settlements) |
| Projector dies after SQL commit and before ACK | A separate process committed the projection transaction, then exited with status 24 at the XACK boundary | SQL contained exactly 84 tokens; events remained pending |
| New projector reclaims pending events | Another process activated from the shared approval, reclaimed and replayed all 24 events | SQL remained 84; Redis pending count reached zero |

The settlement failure is an injected process exit after a successful Redis Lua reply. It proves durable-write/retry behavior across process death; it does not claim a captured TCP reply was dropped. The projection exit occurs at the real SQL-commit-before-Redis-ACK boundary. The physical disconnect check closes an actual Redis connection; it does not restart or promote Redis.

Shared recovery authority was an actual versioned MinIO object and its SHA-256, published through MinioQuotaApprovalStore for the isolated controlled fixture. Child processes received the reference and digest. Local JSON output below is measurement output only, never ledger or approval authority. The first-install and complete recovery algorithms have separate real-store coverage in `test_quota_bootstrap.py` and `test_quota_shards.py`.

## Latency measurements

For each of the 12 actual settlements, the settling process sampled `perf_counter_ns()` immediately after `QuotaRedis.record_usage` returned and again after `DshUsageService.read_usage` returned a coherent live Redis snapshot. This measures the delay from a successful settlement reply to an internal usage snapshot becoming observable on the same host. It includes the snapshot read. It excludes HTTP routing, Nginx/Gateway, browser refresh and client rendering.

| Observation | This run |
|---|---:|
| Requests / reliable tokens per request | 12 / 7 |
| Live visibility median | 0.484 ms |
| Live visibility nearest-rank p95 | 1.901 ms |
| Live visibility maximum | 1.901 ms |
| Last settlement to controller-observed SQL usage | 892.428 ms |
| SQL commit-boundary observation to controller read | 5.329 ms |

Live samples in milliseconds (sorted): `0.444708, 0.460542, 0.478417, 0.479583, 0.481042, 0.482000, 0.485375, 0.502209, 0.522125, 0.528167, 0.561417, 1.900667`.

SQL timings use the same host's monotonic performance clock across subprocesses. The first interval includes settlement-replay process startup/execution, projector process startup, SQL work, process exit and the controller's confirming query. Projection was explicitly invoked by the test, so these values do **not** measure Celery Beat's scheduled wait or queue contention. With only 12 samples, nearest-rank p95 equals the maximum; it is not a production percentile estimate.

## Reproduction

Use the backend virtual environment and `pytest --confcutdir=test/dsh test/dsh/test_dsh_failure_acceptance.py -q -s`. Provide the isolated test database URL via `DSH_TEST_DATABASE_URL` with `DSH_TEST_DATABASE_ISOLATED=1`, Redis DB15 via `DSH_TEST_REDIS_URL` and `DSH_TEST_REDIS_ISOLATED=1`, and a mode-0600 MinIO credential JSON path via `DSH_TEST_MINIO_CONFIG` with `DSH_TEST_MINIO_ISOLATED=1`. Optional `DSH_ACCEPTANCE_RESULTS` records non-secret measurement JSON. Do not print credentials or put them on the command line.

## Limits and remaining deployment acceptance

This is a bounded local functional/failure sample, not a load test or production SLA. It does not cover a real DSH client, Nginx/Gateway transport, full login/seat/model invocation, live Celery broker/Beat scheduling, database failover, deployment Redis fencing/AOF-loss proof, network partitions, MinIO production TLS/ACL, or DM8. Those require the deployment E2E environment. The tests make no inference that a local sub-millisecond Redis read predicts production display latency.


## Additional review repairs and actual primary changes

`test_quota_safety_review.py` adds cross-replica regression for SQL-epoch-before-READY ordering, matching event/gate epoch, recovery receipt owner/digest fencing, and uncertain settlement quarantine. `test_quota_maintenance.py` exercises actual memory/high-watermark denial with display consistency, in-flight completion under capacity pressure, SQL/ACK/retention proof, UNKNOWN and RUNNING preservation, protection of older pending events, missing-index rejection, and a 503-event bounded projection continuation.

`test_quota_primary_failure.py` passed **2 tests in 8.93 seconds** in an isolated run. It starts its own Redis 7.2.7 processes on dynamically allocated loopback ports with separate AOF directories. One case stops and restarts the original process on its original port/AOF directory. The other waits for actual replication, terminates the old primary, and promotes its own replica using `REPLICAOF NO ONE`. The shared Redis on port 16362 is untouched. Each case verifies copied/persisted READY exists, the original process connection fails closed, a fresh runtime rejects the old immutable MinIO approval's run ID, and complete versioned evidence plus a successful MySQL epoch CAS permits a new approval. Reprojection retains exactly 300 reliable tokens; new admission carries epoch two. Fixture cleanup terminates only its own recorded process IDs and removes only its own SQL tables/MinIO bucket.

These are real Redis lifecycle and replication transitions, not mocked run IDs. Stopping the owned primary proves localhost process fencing for this test; it does not certify production network fencing, split-brain exclusion, arbitrary AOF tail loss or a deployment failover controller. Two API replicas with 50 concurrent calls and the deployment admission percentile target remain unexecuted, so T113 remains open. The 12-request timing table above remains the original explicitly measured run and is not a performance estimate for the new lifecycle tests.


Final regression checkpoint after these repairs: quota/reconciliation/worker/cross-process suite **62 passed in 49.47s**, configuration/foundation group **12 passed in 5.00s**. The separate owned-primary lifecycle run above remains **2 passed** and was not repeated. These are separate runs with explicit scopes, not one combined load/performance test.


Per-model allowance revision: the full updated quota/worker/recovery/lifecycle scope passed **68 tests in 40.47s**, followed by **7 per-model tests in 1.26s** (the latter includes three added SQL/month/removal checks and overlaps the earlier scope). Recovery manifests and SQL epoch CAS now bind the full `model_configs` list. Identical model IDs and aggregate allowance with swapped individual limits do not authorize recovery; aggregate-only legacy manifests are rejected. The lifecycle and cross-process tests were migrated to the typed per-model policy and remain included in the 68-case run. DM8 runtime testing is explicitly waived by the user for this iteration; this report does not claim that such testing occurred.
