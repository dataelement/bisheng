

from typing import Type
from langchain_core.pydantic_v1 import BaseModel, Field, root_validator
from loguru import logger
from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase


class InputArgs(BaseModel):
    """args_schema"""
    url: str = Field(description='钉钉机器人的URL地址')
    message: str = Field(description='需要发送的钉钉消息')

class DingdingMessageTool(APIToolBase):
    name = "dingding_message"
    description = "发送钉钉消息"
    args_schema: Type[BaseModel] = InputArgs

    def run(self, params: InputArgs) -> str:
        """Run query through api and parse result."""
        if params:
            self.params[self.input_key] = {
                'question':params 
            }
        json = {
            "text": {
                "content": params.message
            },
            "msgtype":"text"
        }
        url = self.url
        logger.info('api_call url={}', url)
        resp = self.client.post(params.url, json=json)
        if resp.status_code != 200:
            logger.info('api_call_fail res={}', resp.text)
        return resp.text

    async def arun(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {
                'question': query
            }

        url = self.url
        logger.info('api_call url={}', url)
        resp = await self.async_client.apost(url, json=self.params)
        logger.info(resp)
        return resp

    @classmethod
    def send_message(cls) -> "DingdingMessageTool":
        input_key = "msg"
        params = {
            "text": {
                "content": "message"
            },
            "msgtype":"text"
        }

        return cls()





