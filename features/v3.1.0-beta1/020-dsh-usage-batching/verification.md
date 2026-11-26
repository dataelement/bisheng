# Verification and review

Date: 2026-11-08. Scope: local working diff against HEAD on `v3.0.0-fix-dsh`.
No commit, push or deployment performed.

## Results

Isolated real Redis with AOF and SQLite: **72 passed, 1 skipped**, 9.43 seconds.
Selection: `test_usage_dispatch`, `test_quota_maintenance`,
`test_task_request_context`, `test_quota_admission`, `test_quota_settlement`,
`test_operations_runtime`, `test_unified_credit_ledger`, `test_projection_worker`,
`test_usage_repository`, all under `src/backend/test/dsh/`.
The skipped repository test requires isolated MySQL.

Ruff check, Ruff format check (11 Python files), architecture guard and
`git diff --check` passed.

| Acceptance | Evidence |
| --- | --- |
| AC-01 | Admission + settlement coalesce four events into one user marker; first score preserved; invalid index type rejected before ledger mutation. Automatic recovery marks replayed events in the unified credit ledger test. |
| AC-02 | 30 idle dispatcher invocations perform no SCAN; bounded multi-user consumption yields after two users and restores tenant context. Real Celery registration subprocess verifies dispatch every 2 seconds and repair every 60 seconds. |
| AC-03 | Concurrent writes before/after finish, expired owner fencing, SQL rollback, ACK loss, pending reclaim, disappeared streams and expired projection leases covered. |
| AC-04 | Null lag + empty reads complete without continuation; other consumer pending work waits. No new dispatch/repair path publishes per-user tasks. |
| AC-05 | Repair rediscovers a marker-less legacy stream; normal projection does not call retention. |
| AC-06 | Healthy direct Redis-to-SQL batch completes below 10 seconds locally. Failure backoff survives concurrent writes. This does not measure scheduler queue latency. |

The E2E skill is adapted to the internal ledger-to-SQL pipeline: real Redis,
real SQLite, real Lua/projection logic, plus real Celery registration. There is
no new page or endpoint. A running broker/Beat/worker end-to-end latency and CPU
measurement has not been performed.

## Existing test limitation

The older `test_automatic_quota_recovery` fixture lacks the `tenant` table needed
by the current unified policy repository. Its SQLite full-loss case fails before
reaching event replay. Replacing `AutomaticQuotaRecovery.ensure` with the HEAD
version in a temporary pytest plugin reproduces the same missing-table error.
The current unified credit fixture successfully exercises full-loss recovery,
weighted totals and the new pending marker. The old fixture was left unchanged.

## Review

| Dimension | Result |
| --- | --- |
| Boundary conditions | PASS: missing streams, empty work, unknown lag, bounded user count. |
| Permission/auth | PASS: trusted partition validation and per-user tenant scope; legacy header checks retained. |
| Concurrency | PASS: atomic event/marker, snapshot completion, owner fencing, commit-before-ACK and failure backoff. |
| Information leakage | PASS: no credentials or payload logging introduced. |
| Test coverage | PASS for local implementation; production acceptance remains below. |
| Code style | PASS: focused infrastructure/service/task responsibilities and checks. |
| Documentation | PASS: design records topology, failure boundaries, internal contracts and rollout requirements. |

Overall: PASS for local implementation. Release acceptance requires production
validation; this report is not merge or deployment approval.

## Rollout / remaining acceptance

Update API writers, Celery workers and Beat together. Update explicitly configured
old beat schedules to the new tasks; only one Beat instance should run. Observe
queue depth, batch duration, pending age, CPU and admission-to-SQL delay at real
load. Old streams are repaired incrementally; outage and overload delay can
exceed 10 seconds. MySQL/DM8 and full broker/worker execution remain unverified.
