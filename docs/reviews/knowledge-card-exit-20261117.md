# Knowledge space exit rules — 2026-11-17

## Approved behavior

- A user may exit a space held through their own direct personal grant or active subscription.
- Current department or user-group authorization prevents exit, including mixed personal and organizational grants. The creator cannot exit. Existing organization membership workflows remain unchanged.
- Cards and detail use the same server-owned eligibility; execution revalidates current source facts. A list category is not evidence of authorization provenance.

## Implementation

GET `/api/v1/knowledge/space/{space_id}/exit-status` returns `can_exit` and a nullable reason (`creator`, `organization_grant`, `no_personal_grant`). The existing unsubscribe endpoint remains unchanged. Both delegate through one knowledge exit service to the F048 permission runtime.

The runtime narrows removal to the requesting user, current tenant, and verified knowledge-space target. It rejects matched organizational usersets and protected creator sources before changing anything. It removes all supported local personal contributions across permission models through existing version/catalog CAS, projection and audit infrastructure. Sources belonging to other users and organization-wide grants are preserved. Independently copied personal snapshots are local contributions, so removal never changes the source space.

Permission projection completes before legacy membership cleanup. A lost-response retry with no remaining personal grants is a safe no-op. Failed projections do not delete membership facts. Unsupported foreign provenance, non-CUSTOM modes, unverifiable models and more than 50 personal contributions fail closed rather than partially revoke or report success. Current known supported personal provenance is DIRECT, SPACE_MEMBERSHIP and SNAPSHOT_FROM_PARENT.

One identity/tenant-scoped client hook owns eligibility for both card and detail. Missing, loading, refreshing or failed results cannot authorize Exit. Cards load lazily on menu open. Successful exit removes the space from all current list caches and refreshes all space lists; both card and detail refresh shared eligibility after success or refusal. A joined-space action never becomes Delete when exit is denied. The organization refusal uses actual backend error code 18080.

## Verification

All resource-intensive commands ran serially after the user's global serial-execution instruction; subagents performed only code reads/edits/reviews during this continuation.

- Backend test-first qualification cases failed before implementation; final core and HTTP transport checks: 42 passed.
- Related joined/revoked regression checks passed. Five preexisting subscribe-quota tests failed identically on unmodified beta1 188678789d (listed below).
- Frontend card, detail, shared status, cache and responsive integration suites: 11 suites / 85 tests passed.
- Regression checks exposed three additional UI issues and were verified red before fixes: source-category click gating, missing detail eligibility refresh, and stale department-list cache after exit.
- Prior blanket-denial tests were replaced by explicit personal/organization/mixed/creator qualification cases.
- Independent final security/spec/code review: PASS after all findings were fixed.
- Workspace frontend lint and typecheck: passed. Backend Ruff format/check, architecture guard for all changed/new code files, and `git diff --check`: passed.
- No database/schema changes, no grant mutation on 116, and no deployment to 116.

## Existing baseline failures

`test/knowledge/test_knowledge_space_subscribe_quota.py`:

- test_resource_is_countable_dimension
- test_subscribe_count_joins_knowledge_to_skip_orphans
- test_no_roles_falls_back_to_default_100
- test_multi_role_takes_max
- test_role_unlimited_returns_unlimited

These failures concern existing quota contracts and reproduce with the same environment against the unmodified branch. They are outside the approved exit-policy change.
