import uuid
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import BaseEventData


class UserGroupInfo(BaseModel):
    user_group_id: int
    user_group_name: str


class UserRoleInfo(BaseModel):
    role_id: int
    role_name: str
    group_id: int | None = 0


class UserDepartmentInfo(BaseModel):
    department_id: int
    department_name: str


class UserContext(BaseModel):
    user_id: int = Field(..., description="Unique identifier for the user")
    user_name: str = Field(..., description="Name of the user")
    user_group_infos: list[UserGroupInfo] = Field(default_factory=list)
    user_role_infos: list[UserRoleInfo] = Field(default_factory=list)
    user_department_infos: list[UserDepartmentInfo] = Field(default_factory=list)


T_EventData = TypeVar("T_EventData", bound=BaseEventData)


class BaseTelemetryEvent(BaseModel, Generic[T_EventData]):
    """Base model for telemetry events, including common fields and event-specific data."""

    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: BaseTelemetryTypeEnum = Field(..., description="Type of the telemetry event")
    timestamp: int = Field(default_factory=lambda: int(datetime.now(tz=UTC).timestamp()))
    user_context: UserContext = Field(..., description="User context information")
    trace_id: str | None = Field(default=None, description="Trace identifier for correlating events")
    event_data: T_EventData | None = Field(None, description="Event-specific data payload")

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to exclude None values by default."""

        dict_data = super().model_dump(*args, **kwargs)

        if self.event_data is None:
            return dict_data

        # Use the enum's `.value` explicitly: since Python 3.11, f-string formatting of a
        # str-mixed Enum member returns its repr (e.g. "BaseTelemetryTypeEnum.APPLICATION_PROCESS")
        # instead of its value, which would corrupt the event_data keys.
        event_name = self.event_data.event_name.value

        dict_data["event_data"] = {f"{event_name}_{k}": v for k, v in dict_data["event_data"].items()}

        return dict_data
