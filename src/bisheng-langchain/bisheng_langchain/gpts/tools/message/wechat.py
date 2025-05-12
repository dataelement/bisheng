from typing import Any

import requests
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    url: str = Field(description="企业微信机器人的webhook地址")
    message: str = Field(description="需要发送的消息")


class WechatMessageTool(BaseModel):

    def send_message(self, message: str, url: str) -> str:
        """
        发送企业微信机器人消息
        
        Args:
            webhook_url: 机器人的 webhook 地址
            message: 要发送的消息内容
        
        Returns:
            dict: 钉钉接口的响应结果
        """
        # 构建请求头
        headers = {"Content-Type": "application/json"}
        # 构建请求体
        data = {"msgtype": "text", "text": {"content": message}}

        try:
            # 发送 POST 请求
            response = requests.post(url=url, headers=headers, json=data)
            return response.json()
        except requests.exceptions.RequestException as e:
            return f"发送消息失败: {str(e)}"

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "WechatMessageTool":
        attr_name = name.split("_", 1)[-1]
        c = WechatMessageTool(**kwargs)
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
