from pydantic import BaseModel
from typing import Literal, Any

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.database.models.flow import FlowType


class BaseEventData(BaseModel):
    """All event-specific data models should inherit from this base class for type constraints."""

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to exclude None values by default."""

        dict_data = super().model_dump(*args, **kwargs)

        event_name = self._event_name.value

        return {f"{event_name}_{key}": value for key, value in dict_data.items()}


class UserLoginEventData(BaseEventData):
    """Data model for user login events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.USER_LOGIN

    method: str


class NewMessageSessionEventData(BaseEventData):
    """Data model for new message session events."""

    _event_name: BaseTelemetryTypeEnum = BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION

    session_id: str
    # 应用类型
    app_type: FlowType
    # 应用名称
    app_name: str
    # 应用id
    app_id: str
    # 会话来源 平台、API
    source: Literal["platform", "api"]


if __name__ == '__main__':
    # 测试 UserLoginEventData
    login_event = UserLoginEventData(method="oauth")
    print(login_event.model_dump())

    # 测试 NewMessageSessionEventData
    new_session_event = NewMessageSessionEventData(
        session_id="12345",
        app_type=FlowType.FLOW,
        app_name="TestApp",
        app_id="app_001",
        source="platform"
    )
    print(new_session_event.model_dump())