from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum, ChannelFilterRules


class SubscribeChannelRequest(BaseModel):
    """Subscribe Channel Request"""
    channel_id: str = Field(..., description='Channel ID')


class CreateChannelRequest(BaseModel):
    name: str = Field(..., description='Channel Name')
    source_list: List[str] = Field(default_factory=list, description='Data Source List')
    visibility: ChannelVisibilityEnum = Field(..., description='Channel Visibility')
    description: Optional[str] = Field(None, description='Channel Description/Brief')
    filter_rules: Optional[List[ChannelFilterRules]] = Field(default_factory=list, description='Filter Conditions')
    is_released: bool = Field(default=False, description='Whether the channel is released')


class UpdateChannelRequest(BaseModel):
    name: Optional[str] = Field(None, description='Channel Name')
    description: Optional[str] = Field(None, description='Channel Description/Brief')
    source_list: Optional[List[str]] = Field(default_factory=list, description='Data Source List')
    visibility: Optional[ChannelVisibilityEnum] = Field(None, description='Channel Visibility')
    filter_rules: Optional[List[ChannelFilterRules]] = Field(default_factory=list, description='Filter Conditions')
    is_released: Optional[bool] = Field(None, description='Whether the channel is released')


class AddInformationSourceRequest(BaseModel):
    url: str = Field(..., description='URL of the information source to add')


class CrawlWebsiteRequest(BaseModel):
    url: str = Field(..., description='URL of the website to crawl')


class QueryTypeEnum(str, Enum):
    """Get My Channels Query Type Enum"""
    CREATED = 'created'
    FOLLOWED = 'followed'


class SortByEnum(str, Enum):
    """Get My Channels Sort By Enum"""
    LATEST_UPDATE = 'latest_update'
    LATEST_ADDED = 'latest_added'
    CHANNEL_NAME = 'channel_name'


class MyChannelQueryRequest(BaseModel):
    """Get My Channels Query Request"""
    query_type: QueryTypeEnum = Field(..., description='Get My Channels query type: created / followed')
    sort_by: SortByEnum = Field(default=SortByEnum.LATEST_UPDATE,
                                description='Get My Channels sort by: latest_update / latest_added / channel_name')


class SetPinRequest(BaseModel):
    """Set Channel Pin Request"""
    channel_id: str = Field(..., description='Channel ID')
    is_pinned: bool = Field(..., description='Whether to pin the channel')


class ChannelItemResponse(BaseModel):
    """Channel List Item Response"""
    id: str = Field(..., description='Channel ID')
    name: str = Field(..., description='Channel Name')
    source_list: List[str] = Field(default_factory=list, description='Data Source List')
    visibility: ChannelVisibilityEnum = Field(..., description='Channel Visibility')
    is_released: bool = Field(default=False, description='Whether the channel is released')
    latest_article_update_time: Optional[datetime] = Field(None, description='Channel Latest Article Update Time')
    create_time: Optional[datetime] = Field(None, description='Channel Creation Time')
    user_role: str = Field(..., description='User Role in Channel: creator / admin / member')
    is_pinned: bool = Field(default=False, description='Whether the channel is pinned by the user')
    subscribed_at: Optional[datetime] = Field(None,
                                              description='The time when the user subscribed to the channel, null if not subscribed')
    unread_count: int = Field(default=0, description='Number of unread articles in this channel')


class ChannelInfoSourceResponse(BaseModel):
    """Channel Info Source Item Response"""
    id: str = Field(..., description='Channel Information Source ID')
    source_name: str = Field(..., description='Information Source Name')
    source_icon: Optional[str] = Field(None, description='Information Source Icon URL')
    source_type: str = Field(..., description='Information Source Type')
    description: Optional[str] = Field(None, description='Information Source Description')


class ChannelDetailResponse(BaseModel):
    """Channel Detail Response"""
    id: str = Field(..., description='Channel ID')
    name: str = Field(..., description='Channel Name')
    description: Optional[str] = Field(None, description='Channel Description/Brief')
    source_infos: List[ChannelInfoSourceResponse] = Field(default_factory=list, description='Data Source List')
    visibility: ChannelVisibilityEnum = Field(..., description='Channel Visibility')
    filter_rules: Optional[List[ChannelFilterRules]] = Field(default_factory=list, description='Filter Conditions')
    is_released: bool = Field(default=False, description='Whether the channel is released')
    latest_article_update_time: Optional[datetime] = Field(None, description='Channel Latest Article Update Time')
    create_time: Optional[datetime] = Field(None, description='Channel Creation Time')
    creator_name: str = Field(..., description='Channel Creator Name')
    subscriber_count: int = Field(default=0, description='Number of subscribers')
    article_count: int = Field(default=0, description='Total number of articles in the main channel')


class ChannelMemberResponse(BaseModel):
    """Channel Member Response"""
    user_id: int = Field(..., description='User ID')
    user_name: str = Field(..., description='User Name')
    user_role: str = Field(..., description='User Role in Channel: creator / admin / member')
    user_groups: List[dict] = Field(default_factory=list,
                                    description='User Groups the member belongs to, each group is represented as a dict with group details')


class ChannelMemberPageResponse(BaseModel):
    """Channel Member Page Response"""
    data: List[ChannelMemberResponse] = Field(default_factory=list,
                                              description='List of channel members in the current page')
    total: int = Field(..., description='Total number of channel members')


class UpdateMemberRoleRequest(BaseModel):
    """Update Channel Member Role Request"""
    channel_id: str = Field(..., description='Channel ID')
    user_id: int = Field(..., description='Target User ID')
    role: Literal['admin', 'member'] = Field(..., description='New Role to Assign: admin / member')


class RemoveMemberRequest(BaseModel):
    """Remove Channel Member Request"""
    channel_id: str = Field(..., description='Channel ID')
    user_id: int = Field(..., description='Target User ID to Remove')


class SubscriptionStatusEnum(str, Enum):
    """Subscription Status Enum"""
    SUBSCRIBED = 'subscribed'
    PENDING = 'pending'
    NOT_SUBSCRIBED = 'not_subscribed'


class ChannelSquareItemResponse(BaseModel):
    """Channel Square List Item Response"""
    id: str = Field(..., description='Channel ID')
    name: str = Field(..., description='Channel Name')
    description: Optional[str] = Field(None, description='Channel Description/Brief')
    visibility: ChannelVisibilityEnum = Field(..., description='Channel Visibility')
    latest_article_update_time: Optional[datetime] = Field(None, description='Latest Article Update Time')
    create_time: Optional[datetime] = Field(None, description='Channel Creation Time')
    update_time: Optional[datetime] = Field(None, description='Channel Update Time')
    subscription_status: SubscriptionStatusEnum = Field(...,
                                                        description='Current user subscription status')
    subscriber_count: int = Field(default=0, description='Number of subscribers')
    article_count: int = Field(default=0, description='Number of articles matching the main channel filters')
    source_infos: List[ChannelInfoSourceResponse] = Field(default_factory=list,
                                                          description='Top 5 data sources for the channel')


class ChannelSquarePageResponse(BaseModel):
    """Channel Square Page Response"""
    data: List[ChannelSquareItemResponse] = Field(default_factory=list,
                                                  description='List of channel square items')
    total: int = Field(..., description='Total number of matching channels')
