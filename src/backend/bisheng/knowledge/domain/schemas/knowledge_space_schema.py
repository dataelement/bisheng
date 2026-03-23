from typing import Optional, List, Dict

from pydantic import BaseModel, Field

from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeBase


class KnowledgeSpaceCreateReq(BaseModel):
    name: str = Field(..., max_length=200, description="Knowledge Space Name")
    description: Optional[str] = Field(None, description="Knowledge Space Description")
    icon: Optional[str] = Field(None, description="Icon Object Name")
    auth_type: AuthTypeEnum = Field(AuthTypeEnum.PUBLIC, description="Authentication Type")
    is_released: bool = Field(default=False, description="Knowledge Space Status")


class KnowledgeSpaceInfoResp(KnowledgeBase):
    id: int = Field(..., description="Knowledge Space ID")
    is_pinned: bool = Field(default=False, description="Knowledge Space pinned by current user or not")
    user_name: str = Field(default="", description="Knowledge Space creator name")
    avatar: Optional[str] = Field(default=None, description="Knowledge Space creator avatar")
    follower_num: int = Field(1, description="Follower Number")
    file_num: int = Field(1, description="Total File Number")
    is_followed: bool = Field(default=False, description="Knowledge Space followed by current user or not")
    is_pending: bool = Field(default=False, description="Knowledge Space pending or not")
    user_role: Optional[UserRoleEnum] = Field(default=None, description="Knowledge Space user role")


class KnowledgeSpaceUpdateReq(BaseModel):
    name: Optional[str] = Field(None, max_length=200, description="Knowledge Space Name")
    description: Optional[str] = Field(None, description="Knowledge Space Description")
    icon: Optional[str] = Field(None, description="Icon Object Name")
    auth_type: Optional[AuthTypeEnum] = Field(None, description="Authentication Type")
    is_released: bool = Field(default=False, description="Knowledge Space Status")


class FolderCreateReq(BaseModel):
    name: str = Field(..., description="Folder Name")
    parent_id: Optional[int] = Field(None, description="Parent Folder ID")


class FolderRenameReq(BaseModel):
    name: str = Field(..., description="New Folder Name")


class FileCreateReq(BaseModel):
    file_path: List[str] = Field(..., description="File Path")
    parent_id: Optional[int] = Field(None, description="Parent Folder ID")


class FileRenameReq(BaseModel):
    name: str = Field(..., description="New File Name")


class BatchDeleteReq(BaseModel):
    file_ids: List[int] = Field(default_factory=list, description="List of file IDs to delete")
    folder_ids: List[int] = Field(default_factory=list, description="List of folder IDs to delete")


class BatchDownloadReq(BaseModel):
    file_ids: List[int] = Field(default_factory=list, description="List of file IDs to download")
    folder_ids: List[int] = Field(default_factory=list, description="List of folder IDs to download")


class ChatReq(BaseModel):
    query: str = Field(..., description="User Query")


class ChatFolderReq(ChatReq):
    folder_id: int = Field(default=0, description="Folder ID")
    chat_id: str = Field(..., description="Chat ID")
    tags: Optional[List[Dict]] = Field(None, description="List of Tag info for filtering")


class SubscribeSpaceResp(BaseModel):
    status: str = Field(..., description="Subscription status: 'subscribed' or 'pending'")
    space_id: int = Field(..., description="Knowledge Space ID")


class SpaceListReq(BaseModel):
    parent_id: Optional[int] = Field(None, description="Parent Folder ID; omit for root level")
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(20, ge=1, le=200, description="Items per page")
