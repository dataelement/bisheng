from typing import Any, Dict, Type
from langchain_core.pydantic_v1 import BaseModel, Field, root_validator
from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase


class FireCrawlArg(BaseModel):
    api_key: str = Field(description="apikey")
    target_url: str = Field(description="params target_url")
    max_depth: str = Field(description="params maxDepth")
    limit: str = Field(description="params limit")


class FireCrawl(APIToolBase):
    """Manage FireCrawl api"""
    api_key: str = None
    args_schema: Type[BaseModel] = FireCrawlArg

    @classmethod
    def search_crawl(cls,  api_key: str, target_url: str,timeout:int,max_depth:int,limit:int) -> "FireCrawl":
        """crawl from firecrawl"""
        url = "https://api.firecrawl.dev/v1/crawl"
        input_key = "word"
        params = {
            "url": target_url,
            "timeout":timeout,
            "maxDepth": max_depth,
            "limit": limit,
            "webhook": "",
            "scrapeOptions": {
                "formats": ["markdown"],
                "headers": {},
            },
        }

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @classmethod
    def search_scrape(cls, api_key: str, target_url: str,timeout:int,max_depth:int,limit:int) -> "FireCrawl":
        """scrape from firecrawl"""
        url = "https://api.firecrawl.dev/v1/scrape"
        input_key = "word"
        params = {
            "url": target_url,
            "formats": ["markdown"],
            "timeout":timeout,
            "maxDepth": max_depth,
            "limit": limit,
        }

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @root_validator(pre=True)
    def build_header(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Build headers that were passed in."""
        if not values.get("api_key"):
            raise ValueError("Parameters api_key should be specified give.")

        headers = values.get("headers", {})
        headers.update({"Authorization": values["api_key"]})
        values["headers"] = headers
        return values
