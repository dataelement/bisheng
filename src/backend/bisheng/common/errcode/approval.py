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


class ApprovalHandlerNotRegisteredError(BaseErrorCode):
    Code: int = 18104
    Msg: str = 'No handler registered for this approval scenario'


class ApprovalScenarioDuplicateError(BaseErrorCode):
    Code: int = 18105
    Msg: str = 'Approval scenario already exists for this tenant'


class ApprovalScenarioDisabledError(BaseErrorCode):
    Code: int = 18106
    Msg: str = '此功能未开放申请'


class ApprovalRouteNotMatchedError(BaseErrorCode):
    Code: int = 18107
    Msg: str = 'No matching route rule found for this approval request'


class ApprovalApproverEmptyError(BaseErrorCode):
    Code: int = 18108
    Msg: str = 'No approvers resolved for this approval node'


class ApprovalDuplicatePendingError(BaseErrorCode):
    Code: int = 18109
    Msg: str = 'A pending approval already exists for this request'


class ApprovalGrantNotRevokableError(BaseErrorCode):
    Code: int = 18110
    Msg: str = 'Current menu grant cannot be revoked'


class ApprovalMenuApplyDisabledError(BaseErrorCode):
    Code: int = 18111
    Msg: str = 'Menu approval mode is disabled for this menu request'


class ApprovalSettingsPermissionDeniedError(BaseErrorCode):
    Code: int = 18112
    Msg: str = 'Only super admin can modify approval settings'


class ApprovalRetryNoFlowRouteError(BaseErrorCode):
    Code: int = 18113
    Msg: str = 'No enabled flow route found for this scenario'


class ApprovalRetryNoActiveFlowVersionError(BaseErrorCode):
    Code: int = 18114
    Msg: str = 'No active flow version found for the bound flow'


class ApprovalRetryNoFlowNodesError(BaseErrorCode):
    Code: int = 18115
    Msg: str = 'The approval flow has no nodes configured'


class ApprovalFlowNotFoundError(BaseErrorCode):
    Code: int = 18116
    Msg: str = 'Approval flow not found'
