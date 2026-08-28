from .base import BaseErrorCode


# Label module related return error code, function module code:107
class TagExistError(BaseErrorCode):
    Code: int = 10700
    Msg: str = "Tag already exist"


class TagNotExistError(BaseErrorCode):
    Code: int = 10701
    Msg: str = "No tags found"


class ReviewTagParamIsEmptyError(BaseErrorCode):
    Code: int = 10702
    Msg: str = "Review tag param is empty"


class ReviewTagTypeMismatchError(BaseErrorCode):
    Code: int = 10703
    Msg: str = "Review tag type mismatch"


class ReviewTagNotFoundError(BaseErrorCode):
    Code: int = 10704
    Msg: str = "Review tag not found"


class NewTagExistedError(BaseErrorCode):
    Code: int = 10705
    Msg: str = "New tag already exist"


class OriginalTagNotFoundError(BaseErrorCode):
    Code: int = 10706
    Msg: str = "Original tag not found"


class TagLibraryNotFoundError(BaseErrorCode):
    Code: int = 10707
    Msg: str = "Tag library not found"


class TargetTagInUsedError(BaseErrorCode):
    Code: int = 10708
    Msg: str = "Target tag is in used"


class TagNameParamsIsEmptyError(BaseErrorCode):
    Code: int = 10709
    Msg: str = "Tag name params is empty"


class TagPageParamsIsError(BaseErrorCode):
    Code: int = 10710
    Msg: str = "Tag page params is error"


class TagPageSizeParamsIsError(BaseErrorCode):
    Code: int = 10711
    Msg: str = "Tag page size params is error"


class ReviewTagPermissionDeniedError(BaseErrorCode):
    """Caller has no tag-review capacity (not space admin/creator, org admin, or platform admin)."""

    Code: int = 10712
    Msg: str = "No permission to review tags"


class ReviewTagSpaceOutOfScopeError(BaseErrorCode):
    """Reviewer attempted to act on a tag/space outside their ReviewTagScope."""

    Code: int = 10713
    Msg: str = "Review tag is outside managed review scope"


class ReviewTagSimilarAckRequiredError(BaseErrorCode):
    """Approve blocked because similar tags exist and ack_similar was not sent."""

    Code: int = 10714
    Msg: str = "Similar tags exist in the target library; confirmation is required"


class TagBlacklistLimitExceededError(BaseErrorCode):
    """Inserting the rejected names would push the tenant blacklist past 1000 rows."""

    Code: int = 10715
    Msg: str = "Tag blacklist would exceed the 1000-item limit"


class TagBlacklistNotFoundError(BaseErrorCode):
    Code: int = 10716
    Msg: str = "Tag blacklist entry not found"


class TagBlacklistAlreadyExistError(BaseErrorCode):
    Code: int = 10717
    Msg: str = "Tag is already in the blacklist"
