from .base import BaseErrorCode


# Permission module error codes, module code: 190
class PermissionDeniedError(BaseErrorCode):
    Code: int = 19000
    Msg: str = "Permission denied"


class PermissionCheckFailedError(BaseErrorCode):
    Code: int = 19001
    Msg: str = "Permission check failed"


class PermissionServiceUnavailableError(BaseErrorCode):
    Code: int = 19002
    Msg: str = "Authorization service unavailable"


# Backward-compatible symbol for the historical infrastructure-specific name.
PermissionFGAUnavailableError = PermissionServiceUnavailableError


class PermissionInvalidResourceError(BaseErrorCode):
    Code: int = 19003
    Msg: str = "Invalid resource type or ID"


class PermissionTupleWriteError(BaseErrorCode):
    Code: int = 19004
    Msg: str = "Failed to write authorization tuple"


class PermissionInvalidRelationError(BaseErrorCode):
    Code: int = 19005
    Msg: str = "Invalid permission relation"


class PermissionRelationModelNameExistsError(BaseErrorCode):
    Code: int = 19006
    Msg: str = "Relation model name already exists"


class PermissionLastOwnerError(BaseErrorCode):
    Code: int = 19007
    Msg: str = "Cannot remove the last owner of the resource"


# F048 permission Catalog / Grant errors. These codes intentionally use the
# feature-reserved 250xx range while the legacy 190xx errors remain available
# to endpoints that have not migrated to the new contract yet.
class InvalidCatalogActionError(BaseErrorCode):
    Code: int = 25001
    Msg: str = "Invalid or unavailable permission action"


class PermissionVersionConflictError(BaseErrorCode):
    Code: int = 25002
    Msg: str = "Permission data version conflict"


class ImmutableStandardModelError(BaseErrorCode):
    Code: int = 25003
    Msg: str = "Standard permission model fields are immutable"


class PermissionModelStateConflictError(BaseErrorCode):
    Code: int = 25004
    Msg: str = "Permission model state does not allow this operation"


class GrantLevelForbiddenError(BaseErrorCode):
    Code: int = 25005
    Msg: str = "Permission grant exceeds the operator grant level"


class ProtectedAssignmentMutationError(BaseErrorCode):
    Code: int = 25006
    Msg: str = "Protected permission assignment cannot be changed"


class InvalidPermissionModeError(BaseErrorCode):
    Code: int = 25007
    Msg: str = "Invalid resource permission mode"


class PermissionPublishNotReadyError(BaseErrorCode):
    Code: int = 25008
    Msg: str = "Permission catalog or resource scope is not ready for writes"


class PermissionProjectionFailedError(BaseErrorCode):
    Code: int = 25009
    Msg: str = "Permission projection could not be confirmed"


class PermissionMigrationBlockedError(BaseErrorCode):
    Code: int = 25010
    Msg: str = "Permission migration is blocked"


class AuthorizationModelMismatchError(BaseErrorCode):
    Code: int = 25011
    Msg: str = "OpenFGA store or authorization model pin does not match"


class PermissionImpactExpiredError(BaseErrorCode):
    Code: int = 25012
    Msg: str = "Permission impact analysis has expired"


class PermissionMutationTooLargeError(BaseErrorCode):
    Code: int = 25013
    Msg: str = "Permission mutation exceeds the atomic tuple limit"


class PermissionEnumerationIncompleteError(BaseErrorCode):
    Code: int = 25014
    Msg: str = "Permission object enumeration did not complete"


class SameLevelGrantRequiresManagePermissionError(BaseErrorCode):
    Code: int = 25015
    Msg: str = "Same-level grants require the manage_permission action"
