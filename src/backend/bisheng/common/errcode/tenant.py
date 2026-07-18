from .base import BaseErrorCode


# Tenant module error codes, module code: 200
class TenantNotFoundError(BaseErrorCode):
    Code: int = 20000
    Msg: str = 'Tenant not found'


class TenantDisabledError(BaseErrorCode):
    Code: int = 20001
    Msg: str = 'Tenant is disabled'


class UserNotInTenantError(BaseErrorCode):
    Code: int = 20002
    Msg: str = 'User does not belong to this tenant'


class TenantCodeDuplicateError(BaseErrorCode):
    Code: int = 20003
    Msg: str = 'Tenant code already exists'


class NoTenantContextError(BaseErrorCode):
    Code: int = 20004
    Msg: str = 'Missing tenant context'


class TenantHasUsersError(BaseErrorCode):
    Code: int = 20005
    Msg: str = 'Cannot delete tenant with active users'


class TenantAdminRequiredError(BaseErrorCode):
    Code: int = 20006
    Msg: str = 'Cannot remove the last admin of a tenant'


class TenantSwitchForbiddenError(BaseErrorCode):
    Code: int = 20007
    Msg: str = 'User does not belong to the target tenant'


class TenantCreationFailedError(BaseErrorCode):
    Code: int = 20008
    Msg: str = 'Tenant creation failed'


class NoTenantsAvailableError(BaseErrorCode):
    Code: int = 20009
    Msg: str = 'No available tenants for user'
