from typing import Any, Dict, Type

import requests

from langchain_core.pydantic_v1 import BaseModel, Field, root_validator

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    target_url: str = Field(description="params target_url")


class FireCrawl(BaseModel):

    api_key: str = Field(description="apikey")
    base_url: str = Field(description="params base_url")
    max_depth: str = Field(description="params maxDepth")
    limit: str = Field(description="params limit")
    timeout: int = Field(description="params timeout")


    def search_crawl(self,  target_url: str) -> "FireCrawl":
        """crawl from firecrawl"""
        url = "https://api.firecrawl.dev/v1/crawl"
        params = {
            "url": target_url,
            "timeout": self.timeout,
            "maxDepth": self.max_depth,
            "limit": self.limit,
            "webhook": "",
            "scrapeOptions": {
                "formats": ["markdown"],
                "headers": {},
            },
        }
        response = requests.post(url, json=params, headers={'Content-Type': 'application/json'})
        return response.json()


    def search_scrape(self, target_url: str) -> "FireCrawl":
        """scrape from firecrawl"""
        url = "https://api.firecrawl.dev/v1/scrape"
        params = {
            "url": target_url,
            "formats": ["markdown"],
            "timeout": self.timeout,
            "maxDepth": self.max_depth,
            "limit": self.limit,
        }

        response = requests.post(url, json=params, headers={'Content-Type': 'application/json'})
        return response.json()


    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "FireCrawl":
        attr_name = name.split("_", 1)[-1]
        c = FireCrawl(**kwargs)
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
