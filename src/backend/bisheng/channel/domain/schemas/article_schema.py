"""
文章搜索相关的请求/响应 Schema
"""
from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, Field


class ArticleDocument(BaseModel):
    """ES 文章文档模型"""
    source_type: int = Field(..., description='信源类型：0-公众号，1-网站')
    source_id: str = Field(..., description='信源唯一标识')
    title: str = Field(..., description='文章标题')
    content: str = Field(default='', description='纯文本格式正文')
    content_html: str = Field(default='', description='文章HTML内容')
    cover_image: Optional[str] = Field(None, description='文章封面图URL')
    publish_time: Optional[datetime] = Field(None, description='发布时间')
    source_url: Optional[str] = Field(None, description='原文URL')
    create_time: Optional[datetime] = Field(default_factory=datetime.now, description='创建时间')
    update_time: Optional[datetime] = Field(default_factory=datetime.now, description='更新时间')


class ArticleSearchResultItem(BaseModel):
    """单篇文章搜索结果（含高亮）"""
    doc_id: str = Field(..., description='ES 文档 ID')
    source_type: int = Field(..., description='信源类型：0-公众号，1-网站')
    source_id: str = Field(..., description='信源唯一标识')
    source_info: Optional[Dict[str, str]] = Field(None, description='信源信息，包含名称、简介等')
    title: str = Field(..., description='文章标题')
    content: str = Field(default='', description='纯文本格式正文')
    cover_image: Optional[str] = Field(None, description='文章封面图URL')
    publish_time: Optional[datetime] = Field(None, description='发布时间')
    source_url: Optional[str] = Field(None, description='原文URL')
    create_time: Optional[datetime] = Field(None, description='创建时间')
    update_time: Optional[datetime] = Field(None, description='更新时间')
    score: Optional[float] = Field(None, description='搜索相关性得分')
    highlight: Optional[Dict[str, List[str]]] = Field(None, description='高亮字段，key为字段名，value为高亮片段列表')
    is_read: Optional[bool] = Field(False, description='是否已读')


class ArticleDetailResponse(ArticleSearchResultItem):
    """文章详情响应"""
    content_html: str = Field(default='', description='文章HTML内容')


class ArticleSearchPageResponse(BaseModel):
    """文章搜索分页响应"""
    data: List[ArticleSearchResultItem] = Field(default_factory=list, description='搜索结果列表')
    total: int = Field(default=0, description='匹配的总文章数')
    page: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=20, description='每页数量')
