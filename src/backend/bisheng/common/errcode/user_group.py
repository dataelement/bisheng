from .base import BaseErrorCode


# User group module error codes, module code: 230
class UserGroupNotFoundError(BaseErrorCode):
    Code: int = 23000
    Msg: str = 'User group not found'


class UserGroupNameDuplicateError(BaseErrorCode):
    Code: int = 23001
    Msg: str = 'User group name already exists in this tenant'


class UserGroupDefaultProtectedError(BaseErrorCode):
    Code: int = 23002
    Msg: str = 'Cannot delete or rename default user group'


class UserGroupHasMembersError(BaseErrorCode):
    Code: int = 23003
    Msg: str = 'Cannot delete user group with members'


class UserGroupMemberExistsError(BaseErrorCode):
    Code: int = 23004
    Msg: str = 'User is already a member of this group'


class UserGroupMemberNotFoundError(BaseErrorCode):
    Code: int = 23005
    Msg: str = 'User is not a member of this group'


class UserGroupPermissionDeniedError(BaseErrorCode):
    Code: int = 23006
    Msg: str = 'No permission for this user group operation'
