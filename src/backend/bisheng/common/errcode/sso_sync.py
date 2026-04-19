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
