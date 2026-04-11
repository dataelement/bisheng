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
