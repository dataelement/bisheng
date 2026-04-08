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
