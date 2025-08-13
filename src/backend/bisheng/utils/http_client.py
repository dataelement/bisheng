import logging
from typing import Dict, Optional, Union, Any, AsyncGenerator, Literal

from aiohttp import ClientSession, ClientTimeout, TCPConnector

logger = logging.getLogger(__name__)


class AsyncHttpClient(object):
    def __init__(self, timeout: int = 120, keep_alive: bool = True, limit_per_host: int = 100,
                 headers: Dict[str, str] = None, loop=None):
        """
        Asynchronous HTTP client using aiohttp.
        :param timeout: Timeout in seconds for the requests.
        :param max_retries: Maximum number of retries for failed requests.
        :param keep_alive: Whether to keep the connection alive.
        :param limit_per_host: Maximum number of connections per host.
        :param headers:
        :param loop:
        """
        self.headers = headers or self._get_default_headers()
        self.timeout = timeout
        self.keep_alive = keep_alive
        self.limit_per_host = limit_per_host
        self.loop = loop
        self._aiohttp_client: Optional[ClientSession] = None

    @staticmethod
    def _get_default_headers() -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "aiohttp-client",
        }

    def add_custom_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def clear_custom_headers(self) -> None:
        self.headers = self._get_default_headers()

    async def get_aiohttp_client(self, loop=None) -> ClientSession:

        loop = loop or self.loop

        if self._aiohttp_client is None:
            timeout = ClientTimeout(total=self.timeout)
            connector = TCPConnector(keepalive_timeout=self.timeout, limit_per_host=self.limit_per_host, loop=loop)
            self._aiohttp_client = ClientSession(timeout=timeout, connector=connector,
                                                 headers=self.headers, loop=loop)
        return self._aiohttp_client

    async def close_aiohttp_client(self) -> None:
        if self._aiohttp_client:
            await self._aiohttp_client.close()
            self._aiohttp_client = None

    async def _execute_request(
            self,
            method: str,
            url: str,
            headers: Dict[str, str],
            params: Optional[Dict[str, Union[str, int]]] = None,
            body: Optional[Union[Dict[str, Any], str, bytes, Any]] = None,
            data_type: Literal["json", "text", "binary"] = "json",
            destroy_session: bool = False,
            clear_headers: bool = False
    ) -> Dict[str, Any]:
        """
        Execute an HTTP request.
        :param method: HTTP method (GET, POST, PUT, DELETE, etc.)
        :param url: URL for the request.
        :param headers: Headers for the request.
        :param params: Query parameters for the request.
        :param body: Body of the request.
        :param data_type: Type of data to return (json, text, binary).
        :param destroy_session: Whether to close the session after the request.
        :param clear_headers: Whether to clear custom headers after the request.
        :return: Response as a dictionary with status_code, body, and error.
        """
        client = await self.get_aiohttp_client()
        response: Dict[str, Any] = {"status_code": None, "body": None, "error": None}
        headers = headers or self.headers
        try:
            async with client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=body if isinstance(body, dict) else None,
                    data=body if isinstance(body, str) or isinstance(body, bytes) else None,
            ) as http_response:
                response["status_code"] = http_response.status
                if data_type == "json":
                    response["body"] = await http_response.json()
                elif data_type == "text":
                    response["body"] = await http_response.text()
                elif data_type == "binary":
                    response["body"] = await http_response.read()
                http_response.raise_for_status()
        except Exception as error:
            logger.error(f"Error during {method} request to {url}: {error}")
            response["error"] = str(error)
            response["status_code"] = 500
        finally:
            if destroy_session:
                await self.close_aiohttp_client()

            if clear_headers:
                self.clear_custom_headers()
        return response

    async def get(self, url: str, params: Optional[Dict[str, Union[str, int]]] = None,
                  data_type: Literal["json", "text", "binary"] = "json", destroy_session: bool = False,
                  headers: Dict = None, clear_headers: bool = False) -> Dict[str, Any]:
        return await self._execute_request("GET", url=url, headers=headers, params=params, data_type=data_type,
                                           destroy_session=destroy_session, clear_headers=clear_headers)

    async def post(self, url: str, body: Optional[Union[Dict[str, Any], str, bytes, Any]] = None,
                   data_type: Literal["json", "text", "binary"] = "json", destroy_session: bool = False,
                   headers: Dict = None, clear_headers: bool = False) -> Dict[str, Any]:
        return await self._execute_request("POST", url=url, headers=headers, body=body, data_type=data_type,
                                           destroy_session=destroy_session, clear_headers=clear_headers)

    async def put(self, url: str, body: Optional[Union[Dict[str, Any], str, bytes, Any]] = None,
                  data_type: Literal["json", "text", "binary"] = "json", destroy_session: bool = False,
                  headers: Dict = None, clear_headers: bool = False) -> Dict[str, Any]:
        return await self._execute_request("PUT", url=url, headers=headers, body=body, data_type=data_type,
                                           destroy_session=destroy_session, clear_headers=clear_headers)

    async def patch(self, url: str, body: Optional[Union[Dict[str, Any], str, bytes, Any]] = None,
                    data_type: Literal["json", "text", "binary"] = "json", destroy_session: bool = False,
                    headers: Dict = None, clear_headers: bool = False) -> Dict[str, Any]:
        return await self._execute_request("PATCH", url=url, headers=headers, body=body, data_type=data_type,
                                           destroy_session=destroy_session, clear_headers=clear_headers)

    async def delete(self, url: str, params: Optional[Dict[str, Union[str, int]]] = None,
                     data_type: Literal["json", "text", "binary"] = "json", destroy_session: bool = False,
                     headers: Dict = None, clear_headers: bool = False) -> Dict[str, Any]:
        return await self._execute_request("DELETE", url=url, headers=headers, params=params, data_type=data_type,
                                           destroy_session=destroy_session, clear_headers=clear_headers)

    async def stream(
            self, method: Literal["GET", "POST", "PUT", "PATCH"],
            url: str,
            headers: Dict[str, str] = None,
            params: Optional[Dict[str, Union[str, int]]] = None,
            body: Optional[Union[Dict[str, Any], str]] = None, chunk_size: int = 1024 * 1024 * 10,
            destroy_session: bool = False,
            clear_headers: bool = False
    ) -> AsyncGenerator[bytes, None]:
        """
        流式请求
        """
        client = await self.get_aiohttp_client()

        try:
            async with client.request(method=method,
                                      url=url,
                                      headers=headers or self.headers,
                                      params=params,
                                      json=body if isinstance(body, dict) else None,
                                      data=body if isinstance(body, str) else None, ) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
        except Exception as error:
            logger.error(f"Error during streaming from {url}: {error}")
            raise error

        finally:
            if destroy_session:
                await self.close_aiohttp_client()
            if clear_headers:
                self.clear_custom_headers()
