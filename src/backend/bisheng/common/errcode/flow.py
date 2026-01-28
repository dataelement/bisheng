from .base import BaseErrorCode


# Skill service related return error code, function module code:105
class NotFoundVersionError(BaseErrorCode):
    Code: int = 10500
    Msg: str = 'Skill version information not found'


class CurVersionDelError(BaseErrorCode):
    Code: int = 10501
    Msg: str = 'Version currently in use cannot be deleted'


class VersionNameExistsError(BaseErrorCode):
    Code: int = 10502
    Msg: str = 'Version name already exists'


class FlowNameExistsError(BaseErrorCode):
    Code: int = 10503
    Msg: str = 'Duplicate skill name'


class NotFoundFlowError(BaseErrorCode):
    Code: int = 10520
    Msg: str = 'Skill does not exist.'


class FlowOnlineEditError(BaseErrorCode):
    Code: int = 10521
    Msg: str = 'Skills are live and cannot be edited'


class WorkFlowOnlineEditError(BaseErrorCode):
    Code: int = 10525
    Msg: str = 'Workflow is live and not editable'


class WorkFlowInitError(BaseErrorCode):
    Code: int = 10526
    Msg: str = 'Workflow initialization failed'


class WorkFlowWaitUserTimeoutError(BaseErrorCode):
    Code: int = 10527
    Msg: str = 'Workflow timed out waiting for user input'


class WorkFlowNodeRunMaxTimesError(BaseErrorCode):
    Code: int = 10528
    Msg: str = 'Node exceeds maximum number of executions'


class WorkflowNameExistsError(BaseErrorCode):
    Code: int = 10529
    Msg: str = 'Duplicate workflow name'


class FlowTemplateNameError(BaseErrorCode):
    Code: int = 10530
    Msg: str = 'Template Name Already Exists'


class WorkFlowNodeUpdateError(BaseErrorCode):
    Code: int = 10531
    Msg: str = '<Node name>The feature has been upgraded and needs to be deleted and dragged back in.'


class WorkFlowVersionUpdateError(BaseErrorCode):
    Code: int = 10532
    Msg: str = 'The workflow version has been upgraded, please contact the creator to reschedule'


class WorkFlowTaskBusyError(BaseErrorCode):
    Code: int = 10540
    Msg: str = 'Server thread count is full, please try again later'


# Workflow Task Other Errors
class WorkFlowTaskOtherError(BaseErrorCode):
    Code: int = 10541
    Msg: str = 'Workflow task execution failed'


class AppWriteAuthError(BaseErrorCode):
    Code: int = 10599
    Msg: str = 'No Apply Write Permission'
