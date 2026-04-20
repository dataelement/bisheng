"""User-tenant sync configuration model (F012-tenant-resolver)."""

from pydantic import BaseModel, Field


class UserTenantSyncConf(BaseModel):
    """Controls how primary-department changes propagate to leaf-tenant assignment.

    When a user's primary department moves to a department that sits under a
    different Child Tenant mount point, `UserTenantSyncService.sync_user` is
    invoked. `enforce_transfer_before_relocate` controls whether the sync is
    allowed to proceed when the user still owns resources under the old tenant.
    """

    enforce_transfer_before_relocate: bool = Field(
        default=False,
        description=(
            'When True, block primary-department changes for users who still '
            'own resources under the old leaf tenant; the change must be '
            'preceded by a transfer_owner call. When False (default), the '
            'change proceeds and emits an audit + inbox alert.'
        ),
    )
