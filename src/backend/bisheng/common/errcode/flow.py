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


# F086: nested workflow (subflow node)
class WorkFlowSubflowRunError(BaseErrorCode):
    Code: int = 10560
    Msg: str = "Subflow {subflow_name} failed at node {node_name}: {reason}"


class WorkFlowSubflowNotFoundError(BaseErrorCode):
    Code: int = 10561
    Msg: str = "The subflow does not exist or has been deleted"


class WorkFlowSubflowOutputMissingError(BaseErrorCode):
    Code: int = 10562
    Msg: str = "Subflow {subflow_name} did not return the result {output_name}"


class WorkFlowSubflowForbiddenNodeError(BaseErrorCode):
    Code: int = 10563
    Msg: str = "Subflow {subflow_name} reached node {node_name}, which cannot run inside a subflow"


class WorkFlowSubflowOnlineCheckError(BaseErrorCode):
    Code: int = 10564
    Msg: str = "Subflow {subflow_name} contains nodes or return results that cannot be used in a subflow: {reasons}"


class WorkFlowReferencedDeleteError(BaseErrorCode):
    Code: int = 10565
    Msg: str = "This workflow is used as a subflow by {referenced_by} and cannot be deleted"


class WorkFlowSubflowNoPermissionError(BaseErrorCode):
    Code: int = 10566
    Msg: str = "No permission to edit workflow {subflow_name}, so it cannot be used as a subflow"
