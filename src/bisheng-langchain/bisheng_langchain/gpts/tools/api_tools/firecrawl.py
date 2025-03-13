import time
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
    maxdepth: int = Field(description="params maxDepth")
    limit: int = Field(description="params limit")
    timeout: int = Field(description="params timeout")


    def search_crawl(self,  target_url: str) -> str:
        """crawl from firecrawl"""
        url = "https://api.firecrawl.dev/v1/crawl"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        params = {
            "url": target_url,
            "maxDepth": self.maxdepth,
            "limit": self.limit,
            "scrapeOptions": {
                "formats": ["markdown"],
            },
        }
        response = requests.post(url, json=params, headers=headers)
        status_url = response.json()["url"]
        start_time = time.time()
        while True:
            response = requests.get(status_url,headers=headers)
            print("wating for completion " + status_url)
            data = response.json()
            if time.time() - start_time > self.timeout:
                return "timeout"
            if data["status"] == "completed":
                return response.text
            elif data["status"] == "failed":
                return "failed"
            else:
                time.sleep(5)



    def search_scrape(self, target_url: str) -> str:
        """scrape from firecrawl"""
        url = "https://api.firecrawl.dev/v1/scrape"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        params = {
            "url": target_url,
            "formats": ["markdown"],
            "timeout": self.timeout,
        }

        response = requests.post(url, json=params, headers=headers)
        return response.text


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
