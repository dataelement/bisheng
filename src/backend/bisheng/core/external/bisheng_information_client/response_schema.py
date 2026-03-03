from typing import Optional, List

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
    name: str
    url: str
    icon: Optional[str] = None
    article_links: List[str] = []
