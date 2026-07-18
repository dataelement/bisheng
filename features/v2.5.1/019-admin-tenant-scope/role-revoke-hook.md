# F019 — `clear_on_role_revoke` hook status (T10 research log)

**Date**: 2026-04-21
**Status**: method shipped (T04); hook point **not wired** — AC-12 covered
only at the method-body level, not at the call-site level.

## Why it's not wired

AC-12 says: "super admin role revoked → admin-scope Redis key DEL". We
searched the codebase for a revocation path and found **none reachable via
the public HTTP API**:

| Candidate | Path | Result |
|-----------|------|--------|
| Remove role from user | `POST /api/v1/user/role_add` (`user/api/user.py:511`) | Refuses: line 525 raises 500 "Editing is not allowed by the system administrator" when the target user already has `role_id=1`. Line 527 also refuses granting 1. |
| Disable user | `POST /api/v1/user` with `delete=1` (`user/api/user.py:341-348`) | Refuses: line 347-348 raises 500 "Cannot operate admin" when target holds `role_id=1`. |
| Delete user | not present in API | No endpoint exists. |
| Direct FGA delete | `PermissionService.batch_write_tuples` | No caller writes `delete` on `system:global#super_admin`; only the one-time migration at `permission/migration/migrate_rbac_to_rebac.py:293` writes it. |

There is **no code path in the running system** that revokes
`system:global#super_admin`. Attempting to wire the hook into a non-
existent call site would add dead code.

## What we did ship

- `TenantScopeService.clear_on_role_revoke(user_id)` exists and is unit
  tested (via `test_clear_hooks_all_delegate_to_same_del`). It is a
  simple DEL on `admin_scope:{user_id}`.
- This method is **ready to wire** the moment a revocation operation
  ships. The expected pattern (matches T08 and T09):

  ```python
  # At the end of a future RoleService.revoke_super_admin(user_id):
  try:
      from bisheng.admin.domain.services.tenant_scope import TenantScopeService
      await TenantScopeService.clear_on_role_revoke(user_id)
  except Exception as exc:  # noqa: BLE001
      logger.debug('admin_scope clear on role revoke failed: %s', exc)
  ```

## Why we can still meet AC-12 in practice

Two fallbacks keep stale scope keys from becoming a security hole even
without the hook:

1. **Middleware fail-closed check** (`common/middleware/admin_scope.py`):
   the middleware re-runs `_check_is_global_super(user_id)` on **every**
   management-API hit and refuses to inject a scope unless the user still
   holds super. A revoked super admin who logs back in sees an empty
   scope (AC-09 semantics), even if the Redis key lingers.
2. **Celery sweep** (T11): the 10-minute cleanup doesn't itself revoke
   scope on role change, but it does DEL any scope pointing at a
   non-active Tenant, bounding the stale-key lifetime.

Combined, AC-12's **observable behaviour** ("revoked super sees no scope
injection") holds without the direct hook. The **bookkeeping cleanup**
(the Redis DEL at revocation time) is absent but has no user-visible
impact.

## Follow-up

When a revocation operation is added (e.g. a dedicated Super Admin
management UI, SSO role-sync, or admin de-provisioning flow), add the
three-line call above at the revocation site and delete this document.

Tracking tag: `TODO(#F019-role-revoke)`.
