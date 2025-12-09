from typing import Literal

from pydantic import BaseModel

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, StatusEnum, ApplicationTypeEnum


class BaseEventData(BaseModel):
    """All event-specific data models should inherit from this base class for type constraints."""

    @property
    def event_name(self) -> BaseTelemetryTypeEnum:
        return self._event_name


class UserLoginEventData(BaseEventData):
    """Data model for user login events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.USER_LOGIN

    method: str


class NewMessageSessionEventData(BaseEventData):
    """Data model for new message session events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION

    session_id: str
    # 应用类型
    app_type: ApplicationTypeEnum
    # 应用名称
    app_name: str
    # 应用id
    app_id: str
    # 会话来源 平台、API
    source: Literal["platform", "api"]


class ToolInvocationEventData(BaseEventData):
    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.TOOL_INVOKE

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum
    tool_id: int
    tool_name: str
    tool_type: int  # 什么类型的工具，比如：API、MCP、预置.
    status: StatusEnum


class DeleteMessageSessionEventData(BaseEventData):
    """Data model for delete message session events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.DELETE_MESSAGE_SESSION

    session_id: str


class NewApplicationEventData(BaseEventData):
    """Data model for new application events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.NEW_APPLICATION

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum


class NewKnowledgeBaseEventData(BaseEventData):
    """Data model for new knowledge base events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.NEW_KNOWLEDGE_BASE

    kb_id: int
    kb_name: str
    kb_type: int


class FileParseEventData(BaseEventData):
    """Data model for file parse events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.FILE_PARSE

    parse_type: Literal['etl4lm', 'un_etl4lm']
    status: Literal['success', 'failed', 'parse_failed']
    app_type: ApplicationTypeEnum


class MessageFeedbackEventData(BaseEventData):
    """Data model for message feedback events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.MESSAGE_FEEDBACK

    message_id: int
    operation_type: Literal['like', 'dislike', 'copy']

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum


class ModelInvokeEventData(BaseEventData):
    """Data model for model invoke events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.MODEL_INVOKE

    model_id: int
    model_name: str
    model_type: str
    model_server_id: int
    model_server_name: str

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum

    start_time: int
    end_time: int
    first_token_cost_time: int  # ms

    status: StatusEnum
    is_stream: bool
    input_token: int  # 输入token数
    output_token: int  # 输出token数
    cache_token: int  # 缓存token数
    total_token: int  # 总token数


class ApplicationAliveEventData(BaseEventData):
    """Data model for websocket alive events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.APPLICATION_ALIVE

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum

    chat_id: str | None

    start_time: int
    end_time: int


class ApplicationProcessEventData(BaseEventData):
    """Data model for application invoke events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.APPLICATION_PROCESS

    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum

    chat_id: str | None

    start_time: int
    end_time: int
    process_time: int
