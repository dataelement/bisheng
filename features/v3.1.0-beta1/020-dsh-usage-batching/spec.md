# DSH usage projection batching

The user approved coalesced user work and batch consumption, with approximately
10 seconds of normal-load SQL visibility delay. Redis admission and settlement
remain synchronous. This is an internal scheduling change, without new APIs.

- AC-01: event writes atomically mark a user pending; repeated writes coalesce
  without postponing the first scheduled processing opportunity.
- AC-02: the dispatcher claims durable work in bounded batches every 2 seconds;
  idle operation does not enumerate historical streams or fan out Celery tasks.
- AC-03: SQL commits before ACK. Concurrent writes, failed SQL transactions,
  worker crashes and expired owners cannot lose pending work.
- AC-04: unknown Redis consumer lag and empty reads never cause recursive
  Celery publication. Unclaimed pending deliveries wait for reclaim eligibility.
- AC-05: one-time, resumable inventory discovers legacy work. Low-frequency
  paginated repair discovers missed work and runs orphan inspection and retention
  independently of normal projection, without traversing unrelated Redis keys.
- AC-06: normal-load admission/settlement-to-SQL completes within 10 seconds
  with a healthy consumer. Failures retain work with backoff; this is not a
  latency guarantee during downstream outages or overload.
