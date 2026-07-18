from .base import BaseErrorCode


# Role module error codes, module code: 240
class RoleNotFoundError(BaseErrorCode):
    Code: int = 24000
    Msg: str = 'Role not found'


class QuotaExceededError(BaseErrorCode):
    Code: int = 24001
    Msg: str = 'Resource quota exceeded'


class RoleNameDuplicateError(BaseErrorCode):
    Code: int = 24002
    Msg: str = 'Role name already exists in this scope'


class RolePermissionDeniedError(BaseErrorCode):
    Code: int = 24003
    Msg: str = 'No permission for this role operation'


class RoleBuiltinProtectedError(BaseErrorCode):
    Code: int = 24004
    Msg: str = 'Built-in role cannot be deleted or have its core attributes modified'


class QuotaConfigInvalidError(BaseErrorCode):
    Code: int = 24005
    Msg: str = 'Invalid quota_config or department_id value'
