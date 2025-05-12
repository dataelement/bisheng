from typing import List, Optional
from uuid import UUID

from pydantic import field_validator, BaseModel


class TagResponse(BaseModel):
    id: UUID
    name: Optional[str] = None


class UsersLikesResponse(BaseModel):
    likes_count: Optional[int] = None
    liked_by_user: Optional[bool] = None


class CreateComponentResponse(BaseModel):
    id: UUID


class TagsIdResponse(BaseModel):
    tags_id: Optional[TagResponse] = None


class ListComponentResponse(BaseModel):
    id: Optional[UUID] = None
    name: Optional[str] = None
    description: Optional[str] = None
    liked_by_count: Optional[int] = None
    liked_by_user: Optional[bool] = None
    is_component: Optional[bool] = None
    metadata: Optional[dict] = {}
    user_created: Optional[dict] = {}
    tags: Optional[List[TagResponse]] = None
    downloads_count: Optional[int] = None
    last_tested_version: Optional[str] = None
    private: Optional[bool] = None

    # tags comes as a TagsIdResponse but we want to return a list of TagResponse
    @field_validator('tags', mode="before")
    @classmethod
    def tags_to_list(cls, v):
        # Check if all values are have id and name
        # if so, return v else transform to TagResponse
        if not v:
            return v
        if all(['id' in tag and 'name' in tag for tag in v]):
            return v
        else:
            return [TagResponse(**tag.get('tags_id')) for tag in v if tag.get('tags_id')]


class ListComponentResponseModel(BaseModel):
    count: Optional[int] = 0
    authorized: bool
    results: Optional[List[ListComponentResponse]] = None


class DownloadComponentResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[dict] = None
    is_component: Optional[bool] = None
    metadata: Optional[dict] = {}


class StoreComponentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    data: dict
    tags: Optional[List[str]] = None
    parent: Optional[UUID] = None
    is_component: Optional[bool] = None
    last_tested_version: Optional[str] = None
    private: Optional[bool] = True
