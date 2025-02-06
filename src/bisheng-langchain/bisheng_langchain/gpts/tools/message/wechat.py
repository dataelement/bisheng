
from loguru import logger
from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase


class WechatMessageTool(APIToolBase):
    name = "wechat_message"
    description = "发送企业微信消息"

    def run(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {
                'question': query
            }

        url = self.url
        logger.info('api_call url={}', url)
        resp = self.client.post(url, json=self.params)
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
    def send_message(cls, message: str,url:str) -> "WechatMessageTool":
        input_key = "msg"
        params = {
            "text": {
                "content": message
            },
            "msgtype":"text"
        }

        return cls(url=url, input_key=input_key, params=params)






