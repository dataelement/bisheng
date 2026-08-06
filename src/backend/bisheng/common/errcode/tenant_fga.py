from .base import BaseErrorCode

# Tenant FGA tree module error codes, module code: 192
# Owner: F013-tenant-fga-tree (v2.5.1). Declared in CLAUDE.md and
# features/v2.5.1/release-contract.md table 3 (no conflict with F011=220).


class PermissionBackendUnavailableError(BaseErrorCode):
    Code: int = 19201
    Msg: str = "Permission service unavailable"


# Backward-compatible symbol for callers that still import the historical name.
OpenFGAConnectionError = PermissionBackendUnavailableError


class OpenFGAModelNotFoundError(BaseErrorCode):
    Code: int = 19202
    Msg: str = "OpenFGA authorization model not found for given model_id"


class OpenFGATupleCompensationFailedError(BaseErrorCode):
    Code: int = 19203
    Msg: str = "Failed to compensate FGA tuple write after max retries"


class RootTenantAdminNotAllowedError(BaseErrorCode):
    Code: int = 19204
    Msg: str = "Root tenant admin granting is forbidden; use system:global#super_admin instead"
