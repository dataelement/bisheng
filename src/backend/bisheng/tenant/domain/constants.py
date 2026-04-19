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


class DeletionSource(str, Enum):
    """Origin of a department deletion event that DepartmentDeletionHandler
    must fan out. Kept separate from ``TenantAuditAction`` because it is
    metadata payload, not the action itself.
    """

    SSO_REALTIME = 'sso_realtime'
    CELERY_RECONCILE = 'celery_reconcile'
    MANUAL = 'manual'
