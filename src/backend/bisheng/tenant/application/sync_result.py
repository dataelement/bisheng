"""Post-commit organization synchronization must not report complete success on failure."""

from bisheng.common.errcode.tenant_resolver import TenantResolveFailedError


def assert_subtree_sync_complete(result, *, tenant_id=None):
    if result.get("failed"):
        raise TenantResolveFailedError(
            msg="Organization saved; some user tenant synchronization remains incomplete",
            committed=True,
            tenant_id=tenant_id,
            failed_user_ids=[int(row[0]) for row in result["failed"]],
        )
