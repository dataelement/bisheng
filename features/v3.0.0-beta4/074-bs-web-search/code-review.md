# F074 Code Review

Date: 2026-10-15. Local self-review against beta4 db23811133, including the working
implementation and confirmed feature documents. No independent/CI review claim.
Overall: PASS_WITH_WARNINGS for local commit; deployed acceptance remains PARTIAL.

| Dimension | Local result | Evidence / limitation |
| --- | --- | --- |
| Boundary conditions | PASS | Closed arguments, strict scalars, byte/depth/node caps, JSON once, all search rows checked |
| Permission/authentication | PASS_WITH_WARNINGS | Existing signed DSH access dependency, strict tenant facts before shortcuts, current edit/use; live FGA/browser admission unverified |
| Concurrency | PASS_WITH_WARNINGS | Real Redis atomic caps/cooldown/owner cleanup; SQL row-lock admission source reviewed, MySQL/DM8 races unverified |
| Information disclosure | PASS | Safe envelopes, no payload/config logging, private HTTP log scope, ambient callbacks bypassed |
| Tests | PASS_WITH_WARNINGS | 106 combined regressions; 70 core tests on Python 3.11; complete deployment gaps in e2e-report.md |
| Style/architecture | PASS | Ruff, F821, arch guard; repository-only SQL, no new ORM or frontend component |
| Design synchronization | PASS | Current implementation, helper boundaries, wire examples and runtime pitfalls documented |

## Findings Resolved Before Commit

1. Category extra merged over imported tool parameters could alter the executed
   path after schema validation. The strict factory now receives the verified
   destination/method/parameters explicitly. The two-schema HTTP story injects a
   conflicting category path and still verifies the original saved operation.
2. An empty callback list did not prevent ambient runnable trace collectors from
   receiving data. Execute the existing ToolExecutor._arun metadata wrapper only
   after full schema validation, and disable LangSmith tracing. A collector and
   inherited-callback regression asserts that no payload is observed.
3. httpx's INFO records could disclose saved query authentication. A task-local
   filter suppresses HTTP library logs only during strict execution; the regression
   checks both non-disclosure and unaffected ordinary request logging.
4. Initial body handling used only the global byte ceiling. Preflight now reads
   the current tenant publication before streaming and applies its cap/deadline;
   locked admission revalidates current state/limits. Admin PUT enforces 16 KiB.
5. Search publication could have allowed extra declared fields or required
   maxResults. It now requires query with only optional maxResults, with dedicated
   rejection tests. Generic tools continue using their own saved schemas.

No unresolved source blocker was found in the reviewed scope. The warnings above
are verification gaps, not successful acceptance: real database concurrency,
Gateway/identity/FGA, installed Work and a compatible provider still need execution.
Redis failover with silent acknowledged-write rollback needs the documented
operational drain. No claim of exactly-once upstream side effects is made.

The original checkout's .drone.yml and blog WIP remain outside this change. The
feature branch is isolated and based on the beta4 release, not updated main.
