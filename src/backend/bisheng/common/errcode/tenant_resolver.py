from .base import BaseErrorCode


# Tenant resolver module error codes, module code: 191
# Assigned by F012-tenant-resolver (v2.5.1). Covers the user leaf-tenant
# derivation, JWT token_version invalidation and primary-department change flow.


class TenantRelocateBlockedError(BaseErrorCode):
    Code: int = 19101
    Msg: str = (
        'Primary department change blocked: user still owns resources under '
        'the old tenant; transfer resources first or disable '
        'user_tenant_sync.enforce_transfer_before_relocate'
    )


class TenantResolveFailedError(BaseErrorCode):
    Code: int = 19102
    Msg: str = (
        'Failed to resolve leaf tenant: no primary department and no '
        'default tenant available'
    )


class TokenVersionMismatchError(BaseErrorCode):
    Code: int = 19103
    Msg: str = 'JWT token_version does not match the current user state; please re-login'


class TenantCycleDetectedError(BaseErrorCode):
    Code: int = 19104
    Msg: str = (
        'Tenant cycle detected while resolving leaf tenant: primary '
        'department path contains a self-referential mount point'
    )
