from enum import Enum
from typing import Optional

import httpx
from aiohttp import ClientTimeout

from bisheng.common.errcode.channel import BishengInformationUnAuthorizedError, BishengInformationServiceError
from bisheng.core.external.bisheng_information_client.response_schema import InformationSourceResponse, \
    CrawlWebsiteResponse, InformationArticlesResponse
from bisheng.core.external.http_client.client import AsyncHttpClient


class BusinessType(str, Enum):
    """Business types for information sources."""
    WECHAT = 'wechat'
    WEBSITE = 'website'


class InformationSourceAddError(Exception):
    """Exception raised when adding an information source fails."""
    pass


class InformationSourceListError(Exception):
    """Exception raised when listing information sources fails."""
    pass


class InformationSourceSubscribeError(Exception):
    """Exception raised when subscribing to an information source fails."""
    pass


class BishengInformationClient(object):

    def __init__(self, http_client: AsyncHttpClient, base_url: str, api_key: str, **kwargs):
        self.http_client = http_client
        self.base_url = base_url
        self.api_key = api_key

        self.timeout = None

        if kwargs.get("timeout"):
            self.timeout = ClientTimeout(total=kwargs["timeout"])

    async def add_website_information_source(self, url: str) -> InformationSourceResponse:
        """Add a new information source by URL."""
        endpoint = f"{self.base_url}/information/add_website"
        headers = {"X-API-Key": self.api_key}
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise BishengInformationServiceError()

        code = response.body.get("code", -1)
        if code == 401:
            raise BishengInformationUnAuthorizedError()

        elif code != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to list information sources: {response.status_code} - {response.error}")

        information_source_data = InformationSourceResponse.model_validate(response.body.get("data"))

        return information_source_data

    async def add_wechat_information_source(self, url: str) -> InformationSourceResponse:
        """Add a new WeChat information source by URL."""
        endpoint = f"{self.base_url}/information/add_wechat"
        headers = {"X-API-Key": self.api_key}
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise BishengInformationServiceError()

        code = response.body.get("code", -1)
        if code == 401:
            raise BishengInformationUnAuthorizedError()

        elif code != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to list information sources: {response.status_code} - {response.error}")

        information_source_data = InformationSourceResponse.model_validate(response.body.get("data"))

        return information_source_data

    async def search_information_sources(self, query: str, business_type: Optional[BusinessType] = None, page: int = 1,
                                         page_size: int = 20) -> list[
        InformationSourceResponse]:
        """Search information sources by keyword."""
        endpoint = f"{self.base_url}/information/search"
        headers = {"X-API-Key": self.api_key}

        params = {
            "keyword": query,
            "business_type": business_type.value if business_type else None,
            "page": page,
            "page_size": page_size
        }

        response = await self.http_client.get(endpoint, headers=headers, params=params, timeout=self.timeout)

        if response.status_code != 200:
            raise InformationSourceListError(
                f"Failed to search information sources: {response.status_code} - {response.error}")

        information_sources_data = response.body.get("data", [])

        return [InformationSourceResponse.model_validate(item) for item in information_sources_data]

    async def get_information_source_by_ids(self, source_ids: list[str]) -> list[InformationSourceResponse]:
        """Get information sources by a list of source IDs."""
        endpoint = f"{self.base_url}/information/source_by_ids"
        headers = {"X-API-Key": self.api_key}
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise BishengInformationServiceError()

        code = response.body.get("code", -1)
        if code == 401:
            raise BishengInformationUnAuthorizedError()

        elif code != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to list information sources: {response.status_code} - {response.error}")

        information_sources_data = response.body.get("data", [])
        return [InformationSourceResponse.model_validate(item) for item in information_sources_data]

    async def list_information_sources(self, business_type: BusinessType, page: int = 1, page_size: int = 20) -> tuple[
        list[InformationSourceResponse], int]:
        """List all information sources."""
        endpoint = f"{self.base_url}/information/list"
        headers = {"X-API-Key": self.api_key}

        params = {
            "business_type": business_type.value,
            "page": page,
            "page_size": page_size
        }

        response = await self.http_client.get(endpoint, headers=headers, params=params, timeout=self.timeout)

        if response.status_code != 200:
            raise BishengInformationServiceError()

        code = response.body.get("code", -1)
        if code == 401:
            raise BishengInformationUnAuthorizedError()
        elif code != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to list information sources: {response.status_code} - {response.error}")

        information_sources_data = response.body.get("data", [])
        total = response.body.get("totalCount", 0)
        res = [InformationSourceResponse.model_validate(item) for item in information_sources_data]

        return res, total

    async def subscribe_information_source(self, source_ids: list[str]) -> None:
        """Subscribe to an information source by source_id."""
        endpoint = f"{self.base_url}/information/subscribe"
        headers = {"X-API-Key": self.api_key}
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise InformationSourceSubscribeError(
                f"Failed to subscribe to information source: {response.status_code} - {response.error}")

        code = response.body.get("code", -1)
        if code == 401:
            raise BishengInformationUnAuthorizedError()
        elif code != 200:
            raise InformationSourceSubscribeError(
                f"Failed to subscribe to information source: {response.status_code} - {response.error}")

    async def unsubscribe_information_source(self, source_ids: list[str]) -> None:
        """Unsubscribe from an information source by source_id."""
        endpoint = f"{self.base_url}/information/unsubscribe"
        headers = {"X-API-Key": self.api_key}
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise InformationSourceSubscribeError(
                f"Failed to unsubscribe from information source: {response.status_code} - {response.error}")

    async def crawl_website(self, url: str) -> CrawlWebsiteResponse:
        """Crawl a website by URL."""
        endpoint = f"{self.base_url}/information/crawl"
        headers = {"X-API-Key": self.api_key}
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            raise Exception(
                f"Failed to crawl website: {response.status_code} - {response.error}")

        result = response.body.get("data", {})

        return CrawlWebsiteResponse.model_validate(result)

    def get_information_articles(self, information_id: str, return_information: bool = False,
                                 min_create_time: int = None, page: int = 1, page_size: int = 20) \
            -> InformationArticlesResponse:
        """Get articles of an information source by source_id."""
        endpoint = f"{self.base_url}/information/articles/{information_id}"
        headers = {"X-API-Key": self.api_key}

        params = {
            "return_information": return_information,
            "page": page,
            "page_size": page_size,
        }
        if min_create_time:
            params["min_create_time"] = min_create_time
        with httpx.Client() as client:
            response = client.get(endpoint, headers=headers, params=params)

        if response.status_code != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to get information articles: {response.status_code} - {response.text}")
        result = response.json()
        if result.get("code") != 200:
            raise BishengInformationServiceError(
                msg=f"Failed to get information articles: {response.status_code} - {response.text}")
        return InformationArticlesResponse(information=result.get("data", {}).get("information"),
                                           articles=result.get("data", {}).get("articles", []),
                                           total=result.get("data", {}).get("totalCount", 0))
