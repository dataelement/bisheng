from typing import Any, Dict

from langchain_core.pydantic_v1 import BaseModel, Extra, Field
from loguru import logger


class APIToolBase(BaseModel):
    """Manage tianyancha company client."""

    client: Any = Field(default=None, exclude=True)  #: :meta private:
    async_client: Any = Field(default=None, exclude=True)  #: :meta private:
    headers: Dict[str, Any] = {}
    request_timeout: int = 30
    url: str = None
    params: Dict[str, Any] = Field(default_factory=dict)
    input_key: str = 'keyword'

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    def run(self, query: str) -> str:
        """Run query through api and parse result."""
        self.params[self.input_key] = query
        param = '&'.join([f'{k}={v}' for k, v in self.params.items()])
        resp = self.client.get(self.url + '?' + param)
        if resp.status_code != 200:
            logger.info('api_call_fail res={}', resp.text)
        return resp.text

    async def arun(self, query: str) -> str:
        """Run query through api and parse result."""
        self.params[self.input_key] = query
        param = '&'.join([f'{k}={v}' for k, v in self.params.items()])
        resp = await self.async_client.aget(self.url + '?' + param)
        logger.info(resp)
        return resp
