from typing import Optional, List, Dict

from pydantic import BaseModel


class InformationSourceResponse(BaseModel):
    """Information Source Response Schema for external client"""
    id: str
    source_id: str
    business_type: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    original_url: Optional[str] = None
    follow_num: int = 0


class CrawlWebsiteResponse(BaseModel):
    """Temporary crawling of website returned data"""
    name: str  # 网站名称
    url: str  # 网址
    icon: Optional[str] = None  # 网站icon
    article_links: List[Dict] = []  # 文章链接列表


class ArticleInfo(BaseModel):
    """Article Information Schema for external client"""
    id: str
    title: str
    original_url: str
    icon: Optional[str] = None
    markdown_content: Optional[str] = None
    html_content: Optional[str] = None
    publish_date: Optional[str] = None  # 发布日期，格式为 ISO 8601 字符串
    create_time: Optional[str] = None  # 创建时间，格式为 ISO 8601 字符串
    update_time: Optional[str] = None


class InformationArticlesResponse(BaseModel):
    """Information Source Articles Response Schema for external client"""
    information: Optional[InformationSourceResponse] = None  # 信息源信息
    articles: List[ArticleInfo] = []  # 文章列表
    total: int = 0  # 文章总数
