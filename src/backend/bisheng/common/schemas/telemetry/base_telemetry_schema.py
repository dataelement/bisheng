import uuid
from datetime import datetime, timezone
from typing import List, Generic, TypeVar, Optional

from pydantic import BaseModel, Field, ConfigDict

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import BaseEventData


class UserGroupInfo(BaseModel):
    user_group_id: int
    user_group_name: str


class UserRoleInfo(BaseModel):
    role_id: int
    role_name: str


class UserContext(BaseModel):
    user_id: int = Field(..., description="Unique identifier for the user")
    user_name: str = Field(..., description="Name of the user")
    user_group_infos: List[UserGroupInfo] = Field(default_factory=list)
    user_role_infos: List[UserRoleInfo] = Field(default_factory=list)


T_EventData = TypeVar("T_EventData", bound='BaseEventData')


class BaseTelemetryEvent(BaseModel, Generic[T_EventData]):
    """Base model for telemetry events, including common fields and event-specific data."""

    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: BaseTelemetryTypeEnum = Field(..., description="Type of the telemetry event")
    timestamp: int = Field(default_factory=lambda: int(datetime.now(tz=timezone.utc).timestamp()))
    user_context: UserContext = Field(..., description="User context information")
    trace_id: str = Field(..., description="Trace identifier for correlating events")
    event_data: T_EventData = Field(..., description="Event-specific data, varies by event type")
