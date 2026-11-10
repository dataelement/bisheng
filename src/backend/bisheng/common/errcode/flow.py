from .base import BaseErrorCode


# Skill service related return error code, function module code:105
class NotFoundVersionError(BaseErrorCode):
    Code: int = 10500
    Msg: str = "Skill version information not found"


class CurVersionDelError(BaseErrorCode):
    Code: int = 10501
    Msg: str = "Version currently in use cannot be deleted"


class VersionNameExistsError(BaseErrorCode):
    Code: int = 10502
    Msg: str = "Version name already exists"


class WorkFlowOnlineEditError(BaseErrorCode):
    Code: int = 10525
    Msg: str = "Workflow is live and not editable"


class WorkFlowInitError(BaseErrorCode):
    Code: int = 10526
    Msg: str = "Workflow initialization failed"


class WorkFlowWaitUserTimeoutError(BaseErrorCode):
    Code: int = 10527
    Msg: str = "Workflow timed out waiting for user input"


class WorkFlowNodeRunMaxTimesError(BaseErrorCode):
    Code: int = 10528
    Msg: str = "Node exceeds maximum number of executions"


class WorkflowNameExistsError(BaseErrorCode):
    Code: int = 10529
    Msg: str = "Duplicate workflow name"


class FlowTemplateNameError(BaseErrorCode):
    Code: int = 10530
    Msg: str = "Template Name Already Exists"


class WorkFlowNodeUpdateError(BaseErrorCode):
    Code: int = 10531
    Msg: str = "<Node name>The feature has been upgraded and needs to be deleted and dragged back in."


class WorkFlowVersionUpdateError(BaseErrorCode):
    Code: int = 10532
    Msg: str = "The workflow version has been upgraded, please contact the creator to reschedule"


class WorkFlowTaskBusyError(BaseErrorCode):
    Code: int = 10540
    Msg: str = "Server thread count is full, please try again later"


# Workflow Task Other Errors
class WorkFlowTaskOtherError(BaseErrorCode):
    Code: int = 10541
    Msg: str = "Workflow task execution failed"


class WorkflowMediaFileCountLimitError(BaseErrorCode):
    Code: int = 10542
    Msg: str = "Upload file count cannot exceed 5"


# The v2 multi-turn input does not match the message that waits for input
class WorkFlowInvalidUserInputError(BaseErrorCode):
    Code: int = 10543
    Msg: str = "Invalid user input for the waiting workflow"


class AppWriteAuthError(BaseErrorCode):
    Code: int = 10599
    Msg: str = "No Apply Write Permission"


# F027: cursor-based pagination — cursor parsing/version/context/key-length failed
class AppInvalidCursorError(BaseErrorCode):
    Code: int = 10550
    Msg: str = "Invalid pagination cursor"


class PlatformAgentError(BaseErrorCode):
    """公开错误不承接底层异常、调用凭据或上游报文。"""

    http_status = 502

    def __init__(self, exception=None, msg=None, **kwargs):
        super().__init__()


class PlatformAgentConfigurationError(PlatformAgentError):
    Code: int = 10551
    Msg: str = "Platform Agent configuration is invalid"
    http_status = 422


class PlatformAgentVersionError(PlatformAgentError):
    Code: int = 10552
    Msg: str = "Platform Agent version is unavailable or has changed"
    http_status = 409


class PlatformAgentPublicationError(PlatformAgentError):
    Code: int = 10553
    Msg: str = "Workflow changed during publication"
    http_status = 409


class PlatformAgentNotReadyError(PlatformAgentError):
    Code: int = 10554
    Msg: str = "Platform Agent real integration is not ready"
    http_status = 503


class PlatformAgentPermissionError(PlatformAgentError):
    Code: int = 10555
    Msg: str = "Platform Agent access is denied"
    http_status = 403


class PlatformAgentUpstreamError(PlatformAgentError):
    Code: int = 10556
    Msg: str = "Platform Agent execution failed"


class PlatformAgentUnknownError(PlatformAgentError):
    Code: int = 10557
    Msg: str = "Platform Agent response timed out or remote result is unknown"
    http_status = 504


class PlatformAgentOutputError(PlatformAgentError):
    Code: int = 10558
    Msg: str = "Platform Agent output does not match the bound version"


class PlatformAgentNonterminalError(PlatformAgentError):
    Code: int = 10559
    Msg: str = "Asynchronous Platform Agent results are not supported in this phase"
    http_status = 409


class PlatformAgentExecutionError(PlatformAgentError):
    Code: int = 10560
    Msg: str = "Platform Agent execution is duplicated or no longer active"
    http_status = 409


class PlatformAgentEnvironmentError(PlatformAgentError):
    Code: int = 10561
    Msg: str = "Platform Agent source or policy has changed"
    http_status = 409


class PlatformAgentDisabledError(PlatformAgentError):
    Code: int = 10562
    Msg: str = "Platform Agent is disabled"
    http_status = 503


class PlatformKnowledgeError(BaseErrorCode):
    """昆联检索公开错误。底层异常由调用方转换。"""


class PlatformKnowledgeConfigurationError(PlatformKnowledgeError):
    Code: int = 10563
    Msg: str = "Invalid knowledge retrieval configuration"
    http_status = 400


class PlatformKnowledgePermissionError(PlatformKnowledgeError):
    Code: int = 10564
    Msg: str = "Knowledge retrieval access is denied"
    http_status = 403


class PlatformKnowledgeResourceError(PlatformKnowledgeError):
    Code: int = 10565
    Msg: str = "The knowledge base is unavailable"
    http_status = 409


class PlatformKnowledgeNotReadyError(PlatformKnowledgeError):
    Code: int = 10566
    Msg: str = "Kunlian knowledge retrieval is unavailable"
    http_status = 503


class PlatformKnowledgeUpstreamError(PlatformKnowledgeError):
    Code: int = 10567
    Msg: str = "The knowledge retrieval service failed"
    http_status = 502


class PlatformKnowledgeOutputError(PlatformKnowledgeError):
    Code: int = 10568
    Msg: str = "The knowledge retrieval response is invalid"
    http_status = 502


class PlatformKnowledgeExecutionError(PlatformKnowledgeError):
    Code: int = 10569
    Msg: str = "The knowledge retrieval execution is no longer active"
    http_status = 409


class PlatformKnowledgeTimeoutError(PlatformKnowledgeError):
    Code: int = 10570
    Msg: str = "Knowledge retrieval timed out"
    http_status = 504


def knowledge_error_from_reason(reason: str | None) -> PlatformKnowledgeError:
    for error_type in PlatformKnowledgeError.__subclasses__():
        if error_type.Msg == reason:
            return error_type()
    return PlatformKnowledgeExecutionError()


class WorkflowRegistrationError(BaseErrorCode):
    """昆联工作流登记的安全业务错误。"""


class WorkflowRegistrationConflict(WorkflowRegistrationError):
    Code: int = 10571
    Msg: str = "Workflow changed or the registration request conflicts"
    http_status = 409


class WorkflowRegistrationPending(WorkflowRegistrationError):
    Code: int = 10572
    Msg: str = "Workflow creation is pending; retry the same request"
    http_status = 503


class WorkflowRegistrationCursorExpired(WorkflowRegistrationError):
    Code: int = 10573
    Msg: str = "Workflow registration cursor is invalid; rebuild the snapshot"
    http_status = 410


class WorkflowRegistrationDenied(WorkflowRegistrationError):
    Code: int = 10574
    Msg: str = "Workflow registration access is denied"
    http_status = 403


class WorkflowRegistrationUnavailable(WorkflowRegistrationError):
    Code: int = 10575
    Msg: str = "Workflow registration is unavailable"
    http_status = 503
