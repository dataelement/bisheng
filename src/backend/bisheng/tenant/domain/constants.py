"""F011 tenant tree shared constants.

Single source of truth for strings that span the mount / unmount / migrate /
orphan flows and land in ``audit_log.action`` (spec §5.4.2). Using the enum
(value) consistently prevents the "action name typo silently hides the
audit row" class of bug that plain strings allow.
"""

from __future__ import annotations

from enum import Enum


class TenantAuditAction(str, Enum):
    """Structured ``audit_log.action`` values owned by F011.

    Additional actions reserved for downstream features are documented in
    spec §5.4.2 and must be registered there before being emitted. Adding
    a member here is the code-level counterpart to that registration.
    """

    MOUNT = 'tenant.mount'
    UNMOUNT = 'tenant.unmount'
    DISABLE = 'tenant.disable'
    ORPHANED = 'tenant.orphaned'
    RESOURCE_MIGRATE = 'resource.migrate_tenant'
    # v2.5.1 F012 — primary-department change → leaf tenant relocation
    USER_TENANT_RELOCATED = 'user.tenant_relocated'
    USER_TENANT_RELOCATE_BLOCKED = 'user.tenant_relocate_blocked'
    # v2.5.1 F014 — existing non-SSO account adopted by an SSO login sync
    USER_SOURCE_MIGRATED = 'user.source_migrated'
    # F018 (v2.5.1) — owner transfer within a tenant's visible set.
    RESOURCE_TRANSFER_OWNER = 'resource.transfer_owner'
    # F017 (v2.5.1) — Root resource share toggle (AC-01 / AC-05).
    RESOURCE_SHARE_ENABLE = 'resource.share_enable'
    RESOURCE_SHARE_DISABLE = 'resource.share_disable'
    # F019 (v2.5.1) — admin tenant-scope switch (Redis, non-JWT); AC-14.
    ADMIN_SCOPE_SWITCH = 'admin.scope_switch'


class DeletionSource(str, Enum):
    """Origin of a department deletion event that DepartmentDeletionHandler
    must fan out. Kept separate from ``TenantAuditAction`` because it is
    metadata payload, not the action itself.
    """

    SSO_REALTIME = 'sso_realtime'
    CELERY_RECONCILE = 'celery_reconcile'
    MANUAL = 'manual'


class UserTenantSyncTrigger(str, Enum):
    """Why ``UserTenantSyncService.sync_user`` was invoked — goes into
    ``audit_log.metadata.trigger`` so operators can tell a login-time sync
    apart from a primary-dept-change sync apart from a Celery reconcile.
    """

    LOGIN = 'login'
    DEPT_CHANGE = 'dept_change'
    CELERY_RECONCILE = 'celery_reconcile'
    MANUAL = 'manual'
