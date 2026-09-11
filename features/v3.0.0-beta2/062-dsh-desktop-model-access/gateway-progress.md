> 2026-09-11 修订：本文保留历史实施记录。安装 ID、License 激活与副本 ACK 相关段落已被 [解绑修订](./installation-unbinding-revision.md) 和 [验证记录](./installation-unbinding-validation.md) 替代；不再执行旧激活命令。

# Gateway implementation progress

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

Branch: `feat/dsh-access`, repository `/Users/zhangguoqing/works/bisheng-gateway`. No commit/push/deployment.

## Wave 1 / 2 foundation

- T004: Maven Java 17 compilation passed, explicit fixture root and isolated external-store profile retained. No production configuration loaded.
- T008/T009: Four MyBatis entities mirror the four designed tables; UUID primary keys, scoped seat uniqueness, immutable refresh digest history, UTC timestamps; no License duplicate table or foreign keys.
- T010: `docker/db/update_dsh_mysql.sql` / `update_dsh_dm.sql` create only four additive tables and indexes. Existing table names fail loudly. Rollback retains authorization/audit data. Real MySQL/DM8 execution remains unverified.
- T012: Optional default-off DSH properties validate fixed HTTPS origins and independent trust keys without network IO; no changes to old BishengConfig. Strict JSON DTO uses decimal-string identity IDs and current display projections. Default access lifetime is 300 seconds.
- T016/T017: Independent RS256 verifier passes 15 signed fixture vectors including altered outer fields, invalid integer types, unknown kid/schema/audience, expired trial with valid DSH. Duplicate keys, trailing JSON roots, unknown claims, noncanonical base64url, unsafe numbers and malformed UTF-8 fail closed. No customer keys or private test signing key persisted.
- T018/T019: Loader preserves RSA decrypt invocation, old trial expiry-day and non-trial pro branches, and old holder response. Separate DSH state observes decoded plaintext and recalculates capability expiry on each read. Extension failure does not expire old commercial status. Error logs no longer include raw exception stack content.
- T020/T021: Shared Redis activation gate pauses all DSH admissions, counts in-flight protected transactions, requires every deployment-declared replica to acknowledge the same version/digest, and resumes only after drain. Mismatch/invalid state forces paused. 5-second ReloadTask observation heartbeat cannot automatically resume. Lost permits require operator reconciliation rather than unsafe TTL release. No License/seat records are reset on downgrade.
- T022/T023: Direction-specific HMAC SHA256 signs exact body hash, method/path, instance, key id, timestamp and nonce. Replay protection uses atomic shared Redis NX/120 seconds; ±60 second skew; generic secret-free failures. Fixed HTTPS IdentityClient uses raw strict snapshots, two-second deadline and 64 KiB response limit; inactive and dependency failures never become active.

Validation (2026-09-09): Maven `Dsh*Test,LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest` passed **20 tests, zero failures/errors/skips**. The activation integration test used isolated local Redis 7.2.7 DB13, AOF always/noeviction; this proves shared Redis behavior, not real SQL capacity serialization. Maven dependency cache lives only at `/private/tmp/f062-m2`.

L1 review: Java layering keeps SQL out of services; DTO/persistence mappings explicit; new secrets only deployment configuration; no old private material copied. SQL dialects are explicit. Tasks/design status updates are owned by the root agent. T010 cannot be checked complete without real dual-store migration evidence. Target old issuer/artifact and near-limit RSA ciphertext block compatibility remain release gates.

## Wave 3

T026/T027 source/tests added: single-origin authorization URL, dynamic IPv4 loopback callback only, S256 challenge/verifier binding, server-generated auth_id, client state bound unchanged, Redis NX with 300-second lifetime. Public authorization alone never assigns a seat. Further verification and seat/session work in progress.

## Final Gateway handoff for this development wave

2026-09-09 15:58 (+08): **37 focused tests passed, zero failures/errors/skips**, plus the previously executed **one 50,000-seat scale test passed**. All Gateway production/test sources compiled with project Maven dependencies and Java 17. Final non-scale command selected `Dsh*Test,LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest` with `excludedGroups=scale`. Existing unrelated application-context/demo tests were not executed because they load the legacy default runtime configuration. `git diff --check` passed. No commit/push.

Implemented additional task scope: T026–T039, T066/T067, T080–T085. Task checkmarks remain root-agent-owned and must retain the DM8/issuer/E2E limitations below.

### Actual evidence

- MySQL 8 isolated `dsh_test_gateway`: four-table additive DDL executed. Eleven concurrent first-time users obtain exactly ten fixed seats; existing ASSIGNED user remains reusable under reduced capacity. MyBatis SERIALIZABLE count/write and bounded conflict retries are used, including the initially empty instance.
- Real MySQL session tests: duplicate `auth_id` cannot create another family; two concurrent refreshes yield exactly one rotated generation and one replay rejection; replay commits whole-family revocation while preserving the USED digest and absolute session expiry. Logout does not revoke the fixed seat.
- Real MySQL command tests: same-ID retry returns original result; changed payload is rejected; REVOKE/REASSIGN increments grant versions; full capacity leaves the revoked seat unchanged; historical sessions do not revive; actual actor ID remains in operation audit.
- Real MySQL token-flow test: identity adapter mocked at its external boundary, actual seat/session repositories and RSA signer used. First exchange and refresh match the frozen token-response field set and current display snapshot; refresh secrets rotate, absolute session expiry is preserved, old refresh replay revokes the family.
- Scale: 50,000 seats across two tenants, equal sorting timestamps, nonoverlapping keyset pages, tenant/filter-bound signed cursor rejection, monotonic profile update, missing-user no-op, cross-tenant projection denial. EXPLAIN uses an index and no filesort for global latest-seat query. Added `(installation_id,state,created_at,seat_id)` index to both dialect scripts. Scale ran once (~4 minutes); subsequent unrelated HTTP edits did not repeat it.
- Real Spring WebFlux/mapper context with isolated MySQL + Redis: production DSH components and MyBatis mappers are discovered. Boot with `dsh.enabled=false` and retained public trust material still serves JWKS and authenticated logout without a private signing key. Old expired License retains legacy `200/status_code=11001` behavior on old paid endpoints and hands only the eleven exact DSH routes to DSH authentication/error handling.
- Signed internal HTTP operations/read returns `UNKNOWN`, not success, for an absent operation. HMAC replay returns 401, tenant management escape returns 403. Authorization resolve reads body + remaining PTTL atomically; response `expires_in` is 1..300, and less than one second remaining returns `authorization_expired`.
- Actual legacy GlobalFilter chain preserves both DSH SSE data chunks byte-for-byte, even with a broad legacy rate URL pattern. `PathRateGlobalFilter` and `CustomResponseFilter` explicitly pass DSH backend paths so old 200-error wrapping/body logging and response rewriting cannot capture these requests.

### Lifecycle / route contract

- Four public routes: POST `/api/dsh/authorizations`, POST `/api/dsh/token`, POST `/api/dsh/logout`, GET `/api/dsh/jwks`.
- Seven internal POST routes: `/api/internal/dsh/introspect`, `/authorizations/resolve`, `/management/read`, `/seats/revoke`, `/seats/reassign`, `/operations/read`, `/profiles/upsert` (all suffixes under `/api/internal/dsh`). They authenticate exact raw body via independent HMAC before parsing the strict local DTO.
- Resolve wire fields are `challenge,redirect_uri,client_id,instance,state,expires_in` (coordinated with Python). Internal persistence Authorization record additionally retains auth_id and device_name; those extra fields are not emitted by resolve.
- Stateful verification/read/revocation beans are created when installation_id is configured. New authorization/token issuance/identity-client beans remain enabled-only. No installation configuration means no DSH remote-store setup; always-present public controller returns `dsh_disabled`, with empty JWKS where no trust is configured.
- Retain instance/public verification keys/inbound service-auth configuration during disable/rollback so prior sessions can be revoked. Private signing key is not required for disabled verification. Default access lifetime 300s, session absolute lifetime 30d. `dsh.access-issuer` must exactly match Python `dsh.access_issuer`; audience is `bisheng-dsh-model`, access typ is `bisheng-dsh-access+jwt`.
- Rate limiting is shared and coarse per direct peer (does not trust arbitrary X-Forwarded-For): configurable authorization/token requests per minute default 1200/6000. Deployments behind a shared proxy should size these explicitly. No plaintext credentials are persisted or logged by DSH.
- License activation methods live in DshActivationService: `pause(version,digest,replicas)`, `acknowledge`, `resume`, `admit`, `admitRevocation`. Redis `PAUSED` represents explicit maintenance; `INVALID` preserves read/revoke ability for a failed/expired capability. Neither a single replica observation nor hourly reload resumes the cluster. Operational invocation/runbook remains a release integration item.

### Remaining evidence / integration limitations

- DM8 source/DDL exists; no live DM8 runner available. MySQL success is not claimed as DM8 success.
- Actual old issuer / old Gateway binary / extended RSA outer ciphertext and near-limit blocks remain unverified. Existing legacy decoded-input semantics and old holder/filter tests passed; this is not historical-binary compatibility proof.
- Real Python-over-TLS identity roundtrip, Nginx routing, browser/desktop Agent end-to-end and vendor model interactions are not established by these Java tests. External E2E may be skipped for environment reasons per user, with the gap retained.
- User tenant migration is intentionally not an automatic profile effect. `profiles/upsert` never changes seat.tenant_id; current reassign requires the same stored tenant and REVOKED state. A cross-tenant explicit migration policy requires a separate confirmed contract before relaxing it.
- Management recent activity is observed through per-session 60-second-throttled Redis markers and current-page batch reads. SQL periodic last_seen MAX projection is not added in this wave; missing observation remains null and does not affect authorization.

## Root integration final verification (2026-09-09)

The latest source includes the local activation CLI, Unicode profile compatibility and management Saga corrections. Final `package` using Java 17 and the actual project dependencies passed **45 tests, failures/errors/skips 0**, excluding only the separately executed scale tag. The existing 50,000-seat scale result remains a distinct earlier run; it was not repeated after unrelated API/command changes.

- `DshActivationCommand` supports explicit local pause/status/resume from the executable Spring Boot JAR. The command does not forge acknowledgements or force drain. The packaged entry was smoke-tested using PropertiesLauncher; absent test installation correctly produced UNINITIALIZED/exit 2. Final JAR rebuilt after the subsequent fixes.
- Profile names accept the Python User model's 255 Unicode code points. Normalized search values may expand on lowercase, so MySQL columns are 510 characters and DM8 columns 2040 bytes; actual MySQL accepts long dotted-I, emoji and Chinese cases without truncation.
- Trusted REASSIGN prechecks persist license/instance/disabled rejections as immutable FAILED operations. Existing payload mismatch remains a strict 409 conflict, and activation/infra uncertainty does not become a false business rejection. The tests prove changing the License later does not rewrite an old terminal result.
- Python management recovery replays the exact stored intent after reading a remote terminal status, ensuring the Gateway durable payload hash confirms actor/target/action/version before local completion. Confirmation timeout remains PROCESSING.

All remaining deployment, historical issuer/binary and DM8 limitations above still apply. Current rollout and compatibility reports supersede the initial operational-invocation and Maven gaps recorded earlier in this progress file.

## 完成性复核增量（2026-09-09）

修复可信身份票据 invalid_grant 的精确映射、logout 的 refresh/session 过期期限与 device_name 的 1–100 Unicode 码点约束。新增 DshCompletionContractTest 三项，保持七个冻结 Desktop 接口不变。最终指定 Dsh*Test、LicenseStatusHolderTest、LicenseExpiredGlobalFilterTest（排除 scale）执行 package：48 tests，0 failure/error/skip，BUILD SUCCESS。旧发行二进制和密文兼容性仍待外部样本。
