from pydantic import BaseModel


class InformationSourceResponse(BaseModel):
    """Information Source Response Schema for external client"""

    id: str
    source_id: str
    business_type: str
    name: str
    description: str | None = None
    icon: str | None = None
    original_url: str | None = None
    follow_num: int = 0


class InformationSubscriptionItem(InformationSourceResponse):
    """One item returned by the Information subscription snapshot."""

    subscribed_at: int | None = None
    last_sync_at: int | None = None
    article_list_updated_at: int | None = None


class InformationSubscriptionsPage(BaseModel):
    items: list[InformationSubscriptionItem]
    current_page: int
    page_size: int
    total: int


class CrawlWebsiteResponse(BaseModel):
    """Temporary crawling of website returned data"""

    name: str  # 网站名称
    url: str  # 网址
    icon: str | None = None  # 网站icon
    article_links: list[dict] = []  # 文章链接列表


class ArticleInfo(BaseModel):
    """Article Information Schema for external client"""

    id: str
    title: str
    original_url: str
    icon: str | None = None
    markdown_content: str | None = None
    html_content: str | None = None
    publish_date: str | int | None = None
    create_time: str | int | None = None
    update_time: str | int | None = None


class InformationArticlesResponse(BaseModel):
    """Information Source Articles Response Schema for external client"""

    information: InformationSourceResponse | None = None  # 信息源信息
    articles: list[ArticleInfo] = []  # 文章列表
    total: int = 0  # 文章总数
    current_page: int = 1
    page_size: int = 20
