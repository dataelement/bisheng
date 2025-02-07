from typing import Any, Dict, Type

import requests

from langchain_core.pydantic_v1 import BaseModel, Field, root_validator

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    api_key: str = Field(description="apikey")
    target_url: str = Field(description="params target_url")
    max_depth: str = Field(description="params maxDepth")
    limit: str = Field(description="params limit")


class FireCrawl(BaseModel):

    @classmethod
    def search_crawl(
        cls, api_key: str, target_url: str, timeout: int, max_depth: int, limit: int
    ) -> "FireCrawl":
        """crawl from firecrawl"""
        url = "https://api.firecrawl.dev/v1/crawl"
        input_key = "word"
        params = {
            "url": target_url,
            "timeout": timeout,
            "maxDepth": max_depth,
            "limit": limit,
            "webhook": "",
            "scrapeOptions": {
                "formats": ["markdown"],
                "headers": {},
            },
        }
        response = requests.post(url, json=params, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            return response.json()

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @classmethod
    def search_scrape(
        cls, api_key: str, target_url: str, timeout: int, max_depth: int, limit: int
    ) -> "FireCrawl":
        """scrape from firecrawl"""
        url = "https://api.firecrawl.dev/v1/scrape"
        input_key = "word"
        params = {
            "url": target_url,
            "formats": ["markdown"],
            "timeout": timeout,
            "maxDepth": max_depth,
            "limit": limit,
        }

        response = requests.post(url, json=params, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            return response.json()

        return cls(url=url, api_key=api_key, input_key=input_key, params=params)

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "FireCrawl":
        attr_name = name.split("_", 1)[-1]
        class_method = getattr(cls, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
