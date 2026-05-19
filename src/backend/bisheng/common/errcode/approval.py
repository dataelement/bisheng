from .base import BaseErrorCode


class ApprovalRequestNotFoundError(BaseErrorCode):
    Code: int = 18100
    Msg: str = 'Approval request does not exist'


class ApprovalRequestPermissionDeniedError(BaseErrorCode):
    Code: int = 18101
    Msg: str = 'You do not have permission to access this approval request'


class ApprovalRequestAlreadyProcessedError(BaseErrorCode):
    Code: int = 18102
    Msg: str = 'Approval request has already been processed'


class ApprovalRejectReasonRequiredError(BaseErrorCode):
    Code: int = 18103
    Msg: str = 'Reject reason is required'


class ApprovalSettingsPermissionDeniedError(BaseErrorCode):
    Code: int = 18104
    Msg: str = 'Only super admin can modify approval settings'


class ApprovalGrantNotRevokableError(BaseErrorCode):
    Code: int = 18110
    Msg: str = 'Current menu grant cannot be revoked'


class ApprovalMenuApplyDisabledError(BaseErrorCode):
    Code: int = 18111
    Msg: str = 'Menu approval mode is disabled for this menu request'
