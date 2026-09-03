import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import CHAR, VARCHAR, Boolean, Column, DateTime, Index, Integer, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class ChannelVisibilityEnum(str, Enum):
    """Channel Visibility Enumeration"""

    # Public
    PUBLIC = "public"
    # Private
    PRIVATE = "private"
    # Review required
    REVIEW = "review"


# 单一Rule
class SingleRule(BaseModel):
    """Single Rule Model"""

    type: Literal["single"] = "single"
    rule_type: Literal["include", "exclude"] = PydanticField(..., description="Rule Type: include or exclude")
    keywords: list[str] = PydanticField(..., description="List of keywords for the rule")


# 多Rule组合
class MultiRule(BaseModel):
    """Multi Rule Model"""

    type: Literal["multi"] = "multi"
    relation: Literal["and", "or"] = PydanticField(..., description="Relationship between rules: and or or")
    rules: list[SingleRule] = PydanticField(..., description="List of filter rules")


class ChannelFilterRules(BaseModel):
    """Channel Filter Rules Model"""

    relation: Literal["and", "or"] = PydanticField(..., description="Relationship between rules: and or or")
    rules: list[Annotated[Union[SingleRule, MultiRule], PydanticField(discriminator="type")]] = PydanticField(
        ..., description="List of filter rules"
    )
    channel_type: Literal["main", "sub"] = PydanticField(..., description="Channel type: main or sub")
    name: str | None = PydanticField(None, description="Filter name, required for sub channel")

    @model_validator(mode="after")
    def validate_sub_channel_name(self) -> "ChannelFilterRules":
        if self.channel_type == "sub" and not self.name:
            raise ValueError("Sub channel filter rules require a name")
        return self


class Channel(SQLModelSerializable, table=True):
    """
    Channel Model
    """

    __tablename__ = "channel"
    __table_args__ = (
        Index(
            "uq_channel_creation_request",
            "tenant_id",
            "user_id",
            "creation_request_id",
            unique=True,
        ),
    )

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Channel ID",
        sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True),
    )
    name: str = Field(..., description="Channel Name", sa_column=Column(VARCHAR(255), nullable=False))
    description: str | None = Field(
        None, description="Channel Description/Brief", sa_column=Column(Text, nullable=True)
    )
    source_list: list[str] = Field(
        default_factory=list, description="Data Source List", sa_column=Column(JsonType, nullable=False)
    )
    visibility: ChannelVisibilityEnum = Field(
        ..., sa_column=Column(SQLEnum(ChannelVisibilityEnum)), description="Channel Visibility"
    )
    filter_rules: list[dict] = Field(
        default_factory=list, description="Filter Conditions", sa_column=Column(JsonType, nullable=False)
    )
    user_id: int = Field(..., description="UsersID", foreign_key="user.user_id", nullable=False)
    latest_article_update_time: datetime = Field(
        None, description="Latest Article Update Time", sa_column=Column(DateTime, nullable=True)
    )

    is_pinned: bool = Field(
        default=False, description="Whether the channel is pinned", sa_column=Column(Boolean, nullable=False)
    )

    is_released: bool = Field(
        default=False, description="Whether the channel is released", sa_column=Column(Boolean, nullable=False)
    )

    is_shared: bool = Field(
        default=False,
        description="F017: Root channel shared to all children (mirrors FGA shared_with tuples)",
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )

    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )

    creation_request_id: str | None = Field(
        default=None,
        sa_column=Column(VARCHAR(64), nullable=True),
    )
    creation_payload_hash: str | None = Field(
        default=None,
        sa_column=Column(VARCHAR(64), nullable=True),
    )

    create_time: datetime = Field(
        default_factory=datetime.now,
        description="Creation Time",
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )

    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
