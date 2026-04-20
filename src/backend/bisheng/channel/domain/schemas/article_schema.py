"""
Article Search Request/Response Schema
"""
from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, Field


class ArticleDocument(BaseModel):
    """ES Article Document Model"""
    source_type: int = Field(..., description='Source type: 0-WeChat Official Account, 1-Website')
    source_id: str = Field(..., description='Source unique identifier')
    title: str = Field(..., description='Article title')
    content: str = Field(default='', description='Plain text content')
    content_preview: str = Field(default='', description='Truncated plain text content for search list')
    content_html: str = Field(default='', description='Article HTML content')
    cover_image: Optional[str] = Field(None, description='Article cover image URL')
    publish_time: Optional[datetime] = Field(None, description='Publish time')
    source_url: Optional[str] = Field(None, description='Original article URL')
    create_time: Optional[datetime] = Field(default_factory=datetime.now, description='Creation time')
    update_time: Optional[datetime] = Field(default_factory=datetime.now, description='Update time')


class ArticleSearchResultItem(BaseModel):
    """Single Article Search Result (with highlights)"""
    doc_id: str = Field(..., description='ES document ID')
    source_type: int = Field(..., description='Source type: 0-WeChat Official Account, 1-Website')
    source_id: str = Field(..., description='Source unique identifier')
    source_info: Optional[Dict[str, str]] = Field(None, description='Source information including name, description, etc.')
    title: str = Field(..., description='Article title')
    content: str = Field(default='', description='Plain text content')
    cover_image: Optional[str] = Field(None, description='Article cover image URL')
    publish_time: Optional[datetime] = Field(None, description='Publish time')
    source_url: Optional[str] = Field(None, description='Original article URL')
    create_time: Optional[datetime] = Field(None, description='Creation time')
    update_time: Optional[datetime] = Field(None, description='Update time')
    score: Optional[float] = Field(None, description='Search relevance score')
    highlight: Optional[Dict[str, List[str]]] = Field(None, description='Highlight fields, key is field name, value is list of highlighted fragments')
    is_read: Optional[bool] = Field(False, description='Whether the article has been read')


class ArticleDetailResponse(ArticleSearchResultItem):
    """Article Detail Response"""
    content_html: str = Field(default='', description='Article HTML content')


class ArticleSearchPageResponse(BaseModel):
    """Article Search Paginated Response"""
    data: List[ArticleSearchResultItem] = Field(default_factory=list, description='Search result list')
    total: int = Field(default=0, description='Total matching articles')
    page: int = Field(default=1, description='Current page number')
    page_size: int = Field(default=20, description='Page size')
