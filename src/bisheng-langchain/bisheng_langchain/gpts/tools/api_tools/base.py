from typing import Any, Dict, Tuple, Type, Union

from bisheng_langchain.utils.requests import Requests, RequestsWrapper
from langchain_core.pydantic_v1 import BaseModel, Extra, Field, root_validator
from langchain_core.tools import BaseTool, Tool
from loguru import logger


class ApiArg(BaseModel):
    query: str = Field(description='query to look up in this tool')


class MultArgsSchemaTool(Tool):

    def _to_args_and_kwargs(self, tool_input: Union[str, Dict]) -> Tuple[Tuple, Dict]:
        # For backwards compatibility, if run_input is a string,
        # pass as a positional argument.
        if isinstance(tool_input, str):
            return (tool_input, ), {}
        else:
            return (), tool_input


class APIToolBase(BaseModel):
    """Manage tianyancha company client."""

    client: Any = Field(default=None, exclude=True)  #: :meta private:
    async_client: Any = Field(default=None, exclude=True)  #: :meta private:
    headers: Dict[str, Any] = {}
    request_timeout: int = 30
    url: str = None
    params: Dict[str, Any] = Field(default_factory=dict)
    input_key: str = 'keyword'
    args_schema: Type[BaseModel] = ApiArg

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        timeout = values.get('request_timeout', 30)
        if not values.get('client'):
            values['client'] = Requests(headers=values['headers'], request_timeout=timeout)
        if not values.get('async_client'):
            values['async_client'] = RequestsWrapper(headers=values['headers'],
                                                     request_timeout=timeout)
        return values

    def run(self, query: str, **kwargs) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = query
        if kwargs:
            self.params.update(kwargs)
        if self.params:
            param = '&'.join([f'{k}={v}' for k, v in self.params.items()])
            url = self.url + '?' + param if '?' not in self.url else self.url + '&' + param
        else:
            url = self.url
        logger.info('api_call url={}', url)
        resp = self.client.get(url)
        if resp.status_code != 200:
            logger.info('api_call_fail res={}', resp.text)
        return resp.text[:10000]

    async def arun(self, query: str, **kwargs) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = query
        if kwargs:
            self.params.update(kwargs)
        if self.params:
            param = '&'.join([f'{k}={v}' for k, v in self.params.items()])
            url = self.url + '?' + param if '?' not in self.url else self.url + '&' + param
        else:
            url = self.url
        logger.info('api_call url={}', url)
        resp = await self.async_client.aget(url)
        logger.info(resp[:10000])
        return resp[:10000]

    @classmethod
    def get_api_tool(cls, name, **kwargs: Any) -> BaseTool:
        attr_name = name.split('_', 1)[-1]
        class_method = getattr(cls, attr_name)

        return MultArgsSchemaTool(name=name,
                                  description=class_method.__doc__,
                                  func=class_method(**kwargs).run,
                                  coroutine=class_method(**kwargs).arun,
                                  args_schema=class_method(**kwargs).args_schema)
