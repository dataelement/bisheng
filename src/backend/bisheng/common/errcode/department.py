from .base import BaseErrorCode


# Department module error codes, module code: 210
class DepartmentNotFoundError(BaseErrorCode):
    Code: int = 21000
    Msg: str = 'Department not found'


class DepartmentNameDuplicateError(BaseErrorCode):
    Code: int = 21001
    Msg: str = 'Department name already exists at this level'


class DepartmentHasChildrenError(BaseErrorCode):
    Code: int = 21002
    Msg: str = 'Cannot delete department with children'


class DepartmentHasMembersError(BaseErrorCode):
    Code: int = 21003
    Msg: str = 'Cannot delete department with members'


class DepartmentCircularMoveError(BaseErrorCode):
    Code: int = 21004
    Msg: str = 'Cannot move department to its own subtree'


class DepartmentSourceReadonlyError(BaseErrorCode):
    Code: int = 21005
    Msg: str = 'Third-party synced department is read-only'


class DepartmentRootExistsError(BaseErrorCode):
    Code: int = 21006
    Msg: str = 'Root department already exists for this tenant'


class DepartmentMemberExistsError(BaseErrorCode):
    Code: int = 21007
    Msg: str = 'User is already a member of this department'


class DepartmentMemberNotFoundError(BaseErrorCode):
    Code: int = 21008
    Msg: str = 'User is not a member of this department'


class DepartmentPermissionDeniedError(BaseErrorCode):
    Code: int = 21009
    Msg: str = 'No permission for this department operation'


class DepartmentInvalidPasswordError(BaseErrorCode):
    Code: int = 21010
    Msg: str = 'Password must be at least 8 characters and include upper, lower, digit and symbol'


class DepartmentInvalidRolesError(BaseErrorCode):
    Code: int = 21011
    Msg: str = 'One or more roles are not assignable in this department'


class DepartmentOpenFGAUnavailableError(BaseErrorCode):
    Code: int = 21012
    Msg: str = (
        'OpenFGA is not available; department admin changes cannot be persisted. '
        'Ensure OpenFGA is deployed and the backend connected successfully.'
    )


class DepartmentMemberDeleteBlockedError(BaseErrorCode):
    Code: int = 21014
    Msg: str = 'Cannot delete user while data assets exist'


class DepartmentMemberDeleteForbiddenError(BaseErrorCode):
    Code: int = 21015
    Msg: str = 'Only local accounts may be deleted from organization management'


class DepartmentNotArchivedError(BaseErrorCode):
    Code: int = 21016
    Msg: str = 'Only archived departments can be permanently deleted'
