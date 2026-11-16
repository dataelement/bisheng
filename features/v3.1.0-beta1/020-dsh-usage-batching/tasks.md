# Implementation tasks

- [x] Preserve real-time quota settlement and add atomic coalesced scheduling.
- [x] Replace per-user recursive publication with bounded batch dispatch.
- [x] Split low-frequency paginated maintenance from projection.
- [x] Verify crash recovery, concurrent writes, pending reclaim and empty reads.
- [x] Run existing quota/projection regression, architecture guard and review.
- [x] Record verification results and deployment limitations.

- [x] 2026-11-16: complete dispatch registration, preserve old task signatures,
  and replace normal maintenance SCAN with an atomically registered partition index.
- [x] 2026-11-16: verify resumable legacy inventory and steady-state operation
  with 10,000/100,000 unrelated Redis keys; keep production validation separate.
