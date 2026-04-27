from enum import Enum
from typing import Callable, Optional

import httpx
from aiohttp import ClientTimeout

from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.common.errcode.channel import BishengInformationUnAuthorizedError, BishengInformationServiceError, \
    InformationSourceParseError, InformationSourceAuthError, InformationSourcePageError, \
    InformationSourceCrawlLimitError, InformationSourceSubscriptionLimitError, \
    InformationSourceWechatSearchLimitError
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

    def __init__(self, http_client: Optional[AsyncHttpClient],
                 get_conf: Callable[[], IntelligenceCenterConf]):
        self.http_client = http_client
        self._get_conf = get_conf

    @property
    def conf(self) -> IntelligenceCenterConf:
        return self._get_conf()

    @staticmethod
    def _build_timeout(conf: IntelligenceCenterConf) -> Optional[ClientTimeout]:
        timeout = (conf.kwargs or {}).get("timeout")
        if timeout:
            return ClientTimeout(total=timeout)
        return None

    def _build_request_options(self) -> tuple[str, dict, Optional[ClientTimeout]]:
        conf = self.conf
        return conf.base_url.rstrip("/"), {"X-API-Key": conf.api_key}, self._build_timeout(conf)

    @staticmethod
    def _raise_limit_error(code: int) -> None:
        if code == 10010:
            raise InformationSourceCrawlLimitError()
        if code == 10011:
            raise InformationSourceSubscriptionLimitError()
        if code == 10012:
            raise InformationSourceWechatSearchLimitError()

    @staticmethod
    def _raise_parse_error(code: int) -> None:
        if code == 10000:
            raise InformationSourceParseError()
        if code == 10001:
            raise InformationSourceAuthError()
        if code == 10002:
            raise InformationSourcePageError()

    def _handle_common_response_code(
            self,
            response_body: dict,
            default_error_message: str,
            *,
            include_parse_errors: bool = False,
            unknown_error_handler: Optional[Callable[[dict], None]] = None,
    ) -> None:
        code = response_body.get("code", -1)
        if code == 200:
            return
        if code == 401:
            raise BishengInformationUnAuthorizedError()

        self._raise_limit_error(code)
        if include_parse_errors:
            self._raise_parse_error(code)

        if unknown_error_handler:
            unknown_error_handler(response_body)
        raise BishengInformationServiceError(msg=f"{default_error_message}: {response_body}")

    @staticmethod
    def _get_response_body(response) -> dict:
        if hasattr(response, "body"):
            return response.body or {}
        return response.json()

    def _handle_response(
            self,
            response,
            default_error_message: str,
            *,
            include_parse_errors: bool = False,
            unknown_error_handler: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        if response.status_code != 200:
            raise BishengInformationServiceError(
                msg=f"{default_error_message}: {response.status_code} - {getattr(response, 'text', None) or self._get_response_body(response)}"
            )

        response_body = self._get_response_body(response)
        self._handle_common_response_code(
            response_body,
            default_error_message,
            include_parse_errors=include_parse_errors,
            unknown_error_handler=unknown_error_handler,
        )
        return response_body

    @staticmethod
    def _raise_subscribe_error(response, action: str) -> None:
        raise InformationSourceSubscribeError(
            f"Failed to {action} information source: {response.status_code} - "
            f"{getattr(response, 'body', None) or getattr(response, 'text', None)}"
        )

    async def add_website_information_source(self, url: str) -> InformationSourceResponse:
        """Add a new information source by URL."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/add_website"
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)

        response_body = self._handle_response(
            response,
            "Failed to add website information source",
            include_parse_errors=True,
        )

        information_source_data = InformationSourceResponse.model_validate(response_body.get("data"))

        return information_source_data

    async def add_wechat_information_source(self, url: str) -> InformationSourceResponse:
        """Add a new WeChat information source by URL."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/add_wechat"
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)

        response_body = self._handle_response(
            response,
            "Failed to add wechat information source",
            include_parse_errors=True,
        )

        information_source_data = InformationSourceResponse.model_validate(response_body.get("data"))

        return information_source_data

    async def search_information_sources(self, query: str, business_type: Optional[BusinessType] = None, page: int = 1,
                                         page_size: int = 20) -> tuple[list[InformationSourceResponse], int]:
        """Search information sources by keyword."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/search"

        params = {
            "keyword": query,
            "page": page,
            "page_size": page_size
        }

        if business_type:
            params["business_type"] = business_type.value

        response = await self.http_client.get(endpoint, headers=headers, params=params, timeout=timeout)
        response_body = self._handle_response(response, "Failed to search information sources")

        information_sources_data = response_body.get("data", [])
        total = response_body.get("totalCount", 0)

        return [InformationSourceResponse.model_validate(item) for item in information_sources_data], total

    async def get_information_source_by_ids(self, source_ids: list[str]) -> list[InformationSourceResponse]:
        """Get information sources by a list of source IDs."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/source_by_ids"
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)
        response_body = self._handle_response(response, "Failed to get information sources by ids")

        information_sources_data = response_body.get("data", [])
        return [InformationSourceResponse.model_validate(item) for item in information_sources_data]

    async def list_information_sources(self, business_type: BusinessType, page: int = 1, page_size: int = 20) -> tuple[
        list[InformationSourceResponse], int]:
        """List all information sources."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/list"

        params = {
            "business_type": business_type.value,
            "page": page,
            "page_size": page_size
        }

        response = await self.http_client.get(endpoint, headers=headers, params=params, timeout=timeout)
        response_body = self._handle_response(response, "Failed to list information sources")

        information_sources_data = response_body.get("data", [])
        total = response_body.get("totalCount", 0)
        res = [InformationSourceResponse.model_validate(item) for item in information_sources_data]

        return res, total

    async def subscribe_information_source(self, source_ids: list[str]) -> None:
        """Subscribe to an information source by source_id."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/subscribe"
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)
        self._handle_response(
            response,
            "Failed to subscribe to information source",
            unknown_error_handler=lambda _: self._raise_subscribe_error(response, "subscribe to"),
        )

    async def unsubscribe_information_source(self, source_ids: list[str]) -> None:
        """Unsubscribe from an information source by source_id."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/unsubscribe"
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)
        self._handle_response(
            response,
            "Failed to unsubscribe from information source",
            unknown_error_handler=lambda _: self._raise_subscribe_error(response, "unsubscribe from"),
        )

    async def crawl_website(self, url: str) -> CrawlWebsiteResponse:
        """Crawl a website by URL."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/crawl"
        data = {"url": url}
        response = await self.http_client.post(endpoint, body=data, headers=headers, timeout=timeout)
        response_body = self._handle_response(
            response,
            "Failed to crawl website",
            include_parse_errors=True,
        )

        result = response_body.get("data", {})

        return CrawlWebsiteResponse.model_validate(result)

    def get_information_articles(self, information_id: str, return_information: bool = False,
                                 min_create_time: int = None, page: int = 1, page_size: int = 20) \
            -> InformationArticlesResponse:
        """Get articles of an information source by source_id."""
        base_url, headers, timeout = self._build_request_options()
        endpoint = f"{base_url}/information/articles/{information_id}"

        params = {
            "return_information": return_information,
            "page": page,
            "page_size": page_size,
        }
        if min_create_time:
            params["min_create_time"] = min_create_time
        timeout_value = timeout.total if timeout else None
        with httpx.Client() as client:
            response = client.get(endpoint, headers=headers, params=params, timeout=timeout_value)
        response_body = self._handle_response(response, "Failed to get information articles")
        return InformationArticlesResponse(information=response_body.get("data", {}).get("information"),
                                           articles=response_body.get("data", {}).get("articles", []),
                                           total=response_body.get("totalCount", 0))
