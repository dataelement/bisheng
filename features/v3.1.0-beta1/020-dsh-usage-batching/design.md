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

Every 60 seconds repair visits one SCAN page (COUNT 20 is a hint), persisting its
cursor only after the page succeeds. It repairs pending work, inspects running
requests and cleans retention. These maintenance delays depend on Redis keyspace
size. On upgrade existing backlog is discovered incrementally; the 10-second
target applies to new writes with the new writer and consumer running.

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
| Repair is incremental over the whole keyspace | Legacy discovery and orphan/retention latency grow with keyspace; reconsider a separate maintenance index if this becomes operationally significant. |
| Throughput exceeds 16 users per invocation | The 10-second target requires enough worker capacity; reconsider measured batch bounds or dedicated consumers under sustained backlog. |

## Revision history

- 2026-11-08: implement approved coalesced batching to remove historical scan
  fan-out and unknown-lag continuation loops; no API, DB table or dependency added.

## Deployment regression check

The registered `dsh.dispatch_usage` Celery entry point must call the bounded
`UsageDispatcher.dispatch()` through `projection_worker_runtime`; testing the
dispatcher class alone does not cover registration errors. The legacy inspection
callback must preserve the returned continuation cursor. These entry points are
covered by `test/dsh/test_usage_task_registration.py`.
