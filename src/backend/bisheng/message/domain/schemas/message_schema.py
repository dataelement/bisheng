from datetime import datetime
from enum import Enum
from typing import List, Optional, Any, Dict

from pydantic import BaseModel, Field


class MessageContentItem(BaseModel):
    """Single content item within a message's content array."""
    type: str = Field(...,
                      description='Content type: text, system_text, user, business_url, tooltip_text, agree_reject_button')
    content: str = Field(default='', description='Display content text')
    metadata: Optional[Dict[str, Any]] = Field(default=None, description='Additional metadata for the content item')

    def to_message(self) -> Dict[str, Any]:
        if self.metadata:
            return {'type': self.type, 'content': self.content, 'metadata': self.metadata}
        return {'type': self.type, 'content': self.content}


class BusinessContentItem(MessageContentItem):
    """Single business item within a message's content array."""
    type: str = "business_url"
    business_type: str = Field(..., description='Business type')
    business_id: str = Field(..., description='Business ID')

    @property
    def metadata(self) -> Dict[str, Any]:
        return {'business_type': self.business_type, 'business_id': self.business_id}


class UserContentItem(MessageContentItem):
    type: str = "user"
    user_name: str = Field(..., description='User display name')
    user_id: int = Field(..., description='User ID')

    def to_message(self) -> Dict[str, Any]:
        return {'type': self.type, 'content': self.user_name, 'metadata': {'user_id': self.user_id}}


class TabTypeEnum(str, Enum):
    """Message list tab type."""
    ALL = "all"
    REQUEST = "request"


class ApprovalActionEnum(str, Enum):
    """Approval action type."""
    AGREE = "agree"
    REJECT = "reject"


class ApprovalSectionEnum(str, Enum):
    """Approval section within request tab."""
    PENDING = "pending"
    PROCESSED = "processed"


class MessageListRequest(BaseModel):
    """Request schema for querying the message list."""
    tab: TabTypeEnum = Field(default=TabTypeEnum.ALL, description='Tab type: all or request')
    only_unread: bool = Field(default=False, description='Show only unread messages')
    keyword: Optional[str] = Field(default=None, description='Search keyword')
    page: int = Field(default=1, ge=1, description='Page number')
    page_size: int = Field(default=20, ge=1, le=100, description='Page size')


class MarkReadRequest(BaseModel):
    """Request schema for marking messages as read."""
    message_ids: List[int] = Field(..., min_length=1, description='List of message IDs to mark as read')


class ApprovalActionRequest(BaseModel):
    """Request schema for approval actions (agree/reject)."""
    message_id: int = Field(..., description='Message ID to approve or reject')
    action: ApprovalActionEnum = Field(..., description='Action: agree or reject')


class MessageItemResponse(BaseModel):
    """Response schema for a single message item."""
    id: int = Field(..., description='Message ID')
    content: List[Any] = Field(default_factory=list, description='Message content array')
    sender: int = Field(..., description='Sender user ID')
    sender_name: Optional[str] = Field(default=None, description='Sender display name')
    message_type: str = Field(..., description='Message type: notify or approve')
    status: str = Field(..., description='Message status')
    action_code: Optional[str] = Field(default=None, description='Approval action code for handler routing')
    operator_user_id: Optional[int] = Field(default=None, description='User ID who approved/rejected')
    is_read: bool = Field(default=False, description='Whether the message has been read by current user')
    create_time: Optional[datetime] = Field(default=None, description='Creation time')
    update_time: Optional[datetime] = Field(default=None, description='Update time')


class MessagePageResponse(BaseModel):
    """Paginated response for message list."""
    data: List[MessageItemResponse] = Field(default_factory=list, description='Message list')
    total: int = Field(default=0, description='Total count')


class UnreadCountResponse(BaseModel):
    """Response schema for unread message counts."""
    total: int = Field(default=0, description='Total unread count')
    notify: int = Field(default=0, description='Unread notification count')
    approve: int = Field(default=0, description='Unread approval count')
