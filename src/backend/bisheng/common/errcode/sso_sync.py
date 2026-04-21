from .base import BaseErrorCode


# SSO / org-sync realtime module error codes, module code: 193
# Assigned by F014-sso-org-realtime-sync and shared with F015-ldap-reconcile-celery (v2.5.1).
# Covers HMAC-authenticated Gateway callbacks for SSO login + bulk department sync.


class SsoHmacInvalidError(BaseErrorCode):
    Code: int = 19301
    Msg: str = 'HMAC signature missing or invalid; reject request'


class SsoDeptMountConflictError(BaseErrorCode):
    Code: int = 19302
    Msg: str = (
        'tenant_mapping cannot mount department: parent chain already carries '
        'a mount point (INV-T1: only 2-level tenant tree is supported)'
    )


class SsoTenantDisabledError(BaseErrorCode):
    Code: int = 19303
    Msg: str = 'Leaf tenant is not active (disabled/archived/orphaned); login blocked'


class SsoCrossSourceUserError(BaseErrorCode):
    Code: int = 19304
    Msg: str = 'Existing user with conflicting source cannot be reused for SSO'


class SsoTsConflictSkippedError(BaseErrorCode):
    Code: int = 19310
    Msg: str = 'Incoming ts is older than last_sync_ts; operation skipped (INV-T12)'


class SsoUserLockBusyError(BaseErrorCode):
    Code: int = 19311
    Msg: str = 'Another SSO login for the same external_user_id is in progress'


class SsoDeptParentMissingError(BaseErrorCode):
    Code: int = 19312
    Msg: str = (
        'Department parent chain missing in bisheng; Gateway must push parents '
        'via /api/v1/departments/sync before login-sync'
    )


class SsoPrimaryDeptMissingError(BaseErrorCode):
    Code: int = 19313
    Msg: str = 'primary_dept_external_id is required for SSO login-sync'


# ---------------------------------------------------------------------------
# F015-ldap-reconcile-celery (shared module MMM=193)
# ---------------------------------------------------------------------------


class SsoReconcileLockBusyError(BaseErrorCode):
    Code: int = 19314
    Msg: str = (
        'Another reconcile run for the same org_sync_config is in progress; '
        'skip this trigger (Redis SETNX lock busy)'
    )


class SsoRelinkStrategyUnsupportedError(BaseErrorCode):
    Code: int = 19315
    Msg: str = (
        'Unknown relink matching_strategy; expected external_id_map or '
        'path_plus_name'
    )


class SsoRelinkConflictUnresolvedError(BaseErrorCode):
    Code: int = 19316
    Msg: str = (
        'relink conflict candidate list is empty or the chosen '
        'new_external_id is not among stored candidates'
    )


class SsoSameTsRemoveAppliedWarnError(BaseErrorCode):
    Code: int = 19317
    Msg: str = (
        'Same-ts upsert/remove collision resolved by applying remove '
        '(INV-T12 AC-11); audit_log written, admin notified'
    )


class SsoReconcileReservedError(BaseErrorCode):
    Code: int = 19318
    Msg: str = 'Reserved for future reconcile error paths'
