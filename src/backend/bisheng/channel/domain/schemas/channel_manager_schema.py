from typing import List, Optional

from pydantic import BaseModel, Field

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum, ChannelFilterRules


class CreateChannelRequest(BaseModel):
    name: str = Field(..., description='Channel Name')
    source_list: List[str] = Field(default_factory=list, description='Data Source List')
    visibility: ChannelVisibilityEnum = Field(..., description='Channel Visibility')
    filter_rules: Optional[List[ChannelFilterRules]] = Field(default_factory=list, description='Filter Conditions')
    is_released: bool = Field(default=False, description='Whether the channel is released')
