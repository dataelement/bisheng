# Design

Implements the user-approved discussion. Constitution C1/C2/C3/C4/C6/C8 apply;
there are no database schema, permission, API or local shared-state changes.

The existing Lua ledger mutation and a `ZADD NX` pending-stream marker execute
in one Redis invocation. The index uses quota Redis server time. The supported
deployment remains standalone or Sentinel, not Redis Cluster: the shared index
and per-user ledger intentionally span hash tags.

Every 2 seconds one Celery dispatch task processes at most 16 users or 4 seconds
between users. A user is claimed immediately before processing; a 30-second
lease score keeps the marker durable through crashes. A random owner fences
completion after reclaim. The existing projection lease and SQL idempotence
protect overlapping consumers. Synchronous SQL calls can exceed the batch time
budget; the budget is checked between users, not an interrupting DB timeout.

Completion compares the stream's last-generated-id against the claimed snapshot
inside Lua. Concurrent event writes retain ready work; unchanged, drained work
is removed. Pending deliveries use the existing reclaim delay. Exceptions are
logged and retained with 30-second backoff. No consumer publishes itself again.

Every event-producing Lua call also registers its stream in the persistent
`projection_work:partitions` set, after preflighting the index type. Every 60
seconds repair visits one SSCAN page of this set (COUNT 100), persists its cursor
after success, repairs pending work, inspects running requests and cleans
retention. Normal projection and maintenance do not enumerate the Redis DB.

Legacy stream discovery is an explicit offline migration, never a Worker startup
or periodic task. Stop all API, Celery/Beat and Linsight producers/consumers and
run `scripts/backfill_redis_processing_indexes.py --apply --services-stopped`,
then `--verify` before starting the new consumers. The script registers all
retained streams, queues unread/pending partitions, invalidates only old work
owners and verifies coverage. It never changes payloads, consumer group offsets,
ACK state, quota counters or SQL. Checkpoint indexes are migrated by the same
command. Interruption is handled by repeating the migration while still stopped.
New installations need no discovery; new writes maintain their indexes atomically.
Redis restarts do not trigger keyspace discovery. After a partial index restore,
repeat the offline migration before reopening traffic. There is no runtime
inventory cursor, generation marker or migration gate in application health.

Rejected: raising the scan interval alone does not fix recursive publication;
one Celery message per event amplifies load; a separate consumer process adds an
unnecessary deployment role at this stage. Multiple Beat processes remain an
operational error; atomic claims prevent duplicate ownership but not their
fixed scheduler overhead. Existing explicit beat_schedule overrides must be
updated to dispatch_usage every 2 seconds and scan_usage every 60 seconds.

Validation: isolated real Redis plus SQLite exercise admission, settlement,
claims, SQL writes and ACK. Production CPU/latency and MySQL/DM8 acceptance need
deployment measurement; local tests do not establish those results.

## Module and internal contracts

- `quota_redis.py` and automatic recovery append the shared work key only to
  event-producing Lua invocations; the existing request/response contracts stay intact.
- `usage_work.py` / `usage_work.lua` own mark, claim and fenced completion.
  Claims contain stream key, owner token and last-generated-id snapshot.
- `usage_dispatch.py` owns bounded cross-tenant consumption and paginated repair.
  It restores tenant context after each user. SQL projection still owns commit/ACK.
- `worker/dsh/registry.py` exposes periodic dispatch and maintenance; old queued
  project/scan/inspection task signatures remain accepted without recursive publication.

## Known boundaries and reconsideration

| Boundary | Consequence and handling |
| --- | --- |
| Redis group `lag` may be null after trimming | `lag != 0` can perpetually request continuation; scheduling now checks actual unread entries. |
| New events arrive while work is claimed | Completion compares the stream ID atomically; the marker survives. Failure backoff takes priority even if writes continue. |
| Index or claimed work survives a worker exit | Durable lease score allows recovery after 30 seconds; owner tokens fence stale completion. |
| Another consumer holds pending events | Wait for the existing 60-second reclaim age rather than spin. |
| SQL transaction outlives a lease | Existing SQL idempotence remains necessary; batch bounds do not interrupt SQL. |
| Legacy stream discovery requires a complete DB pass | Only the stopped-service migration scans the DB. Verify complete coverage before starting new consumers; runtime never discovers old keys. |
| Throughput exceeds 16 users per invocation | The 10-second target requires enough worker capacity; reconsider measured batch bounds or dedicated consumers under sustained backlog. |

## Revision history

- 2026-11-08: implement approved coalesced batching to remove historical scan
  fan-out and unknown-lag continuation loops; no API, DB table or dependency added.

- 2026-11-16: fix the incomplete Celery dispatch registration and inspection
  cursor binding; register maintenance partitions atomically and replace
  recurring full-DB scans with SSCAN. Real Redis/SQLite regressions cover
  10,000/100,000 unrelated keys and fenced queue completion.

- 2026-11-16: per explicit user direction, remove automatic startup/generation
  discovery entirely. Move legacy usage/checkpoint indexing and coverage
  verification into one stopped-service migration command.
