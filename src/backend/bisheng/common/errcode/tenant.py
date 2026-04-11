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
