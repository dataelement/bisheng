from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.database.models.flow import FlowType


def get_session_app_type(flow_type: int) -> ApplicationTypeEnum:
    """Convert flow_type int to ApplicationTypeEnum."""
    if flow_type == FlowType.WORKFLOW.value:
        return ApplicationTypeEnum.WORKFLOW
    if flow_type == FlowType.ASSISTANT.value:
        return ApplicationTypeEnum.ASSISTANT
    if flow_type == FlowType.LINSIGHT.value:
        return ApplicationTypeEnum.LINSIGHT
    return ApplicationTypeEnum.DAILY_CHAT
