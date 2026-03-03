from bisheng.core.external.bisheng_information_client.response_schema import InformationSourceResponse, \
    CrawlWebsiteResponse
from bisheng.core.external.http_client.client import AsyncHttpClient


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

    def __init__(self, http_client: AsyncHttpClient, base_url: str, api_key: str):
        self.http_client = http_client
        self.base_url = base_url
        self.api_key = api_key

    async def add_information_source(self, url: str) -> InformationSourceResponse:
        """Add a new information source by URL."""
        endpoint = f"{self.base_url}/information/add"
        headers = {"X-API-Key": self.api_key}
        data = {"url": url}
        response = await self.http_client.post(endpoint, json=data, headers=headers)

        if response.status_code != 200:
            raise InformationSourceAddError(
                f"Failed to add information source: {response.status_code} - {response.error}")

        information_source_data = InformationSourceResponse.model_validate(response.body.get("data"))

        return information_source_data

    async def list_information_sources(self) -> list[InformationSourceResponse]:
        """List all information sources."""
        endpoint = f"{self.base_url}/information/list"
        headers = {"X-API-Key": self.api_key}
        response = await self.http_client.get(endpoint, headers=headers)

        if response.status_code != 200:
            raise InformationSourceListError(
                f"Failed to list information sources: {response.status_code} - {response.error}")

        information_sources_data = response.body.get("data", [])
        return [InformationSourceResponse.model_validate(item) for item in information_sources_data]

    async def subscribe_information_source(self, source_ids: list[str]) -> None:
        """Subscribe to an information source by source_id."""
        endpoint = f"{self.base_url}/information/subscribe"
        headers = {"X-API-Key": self.api_key}
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, json=data, headers=headers)

        if response.status_code != 200:
            raise InformationSourceSubscribeError(
                f"Failed to subscribe to information source: {response.status_code} - {response.error}")

    async def unsubscribe_information_source(self, source_ids: list[str]) -> None:
        """Unsubscribe from an information source by source_id."""
        endpoint = f"{self.base_url}/information/unsubscribe"
        headers = {"X-API-Key": self.api_key}
        data = {"information_ids": source_ids}
        response = await self.http_client.post(endpoint, json=data, headers=headers)

        if response.status_code != 200:
            raise InformationSourceSubscribeError(
                f"Failed to unsubscribe from information source: {response.status_code} - {response.error}")

    async def crawl_website(self, url: str) -> CrawlWebsiteResponse:
        """Crawl a website by URL."""
        endpoint = f"{self.base_url}/information/crawl"
        headers = {"X-API-Key": self.api_key}
        data = {"url": url}
        response = await self.http_client.post(endpoint, json=data, headers=headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to crawl website: {response.status_code} - {response.error}")

        result = response.body.get("data", {})

        return CrawlWebsiteResponse.model_validate(result)
