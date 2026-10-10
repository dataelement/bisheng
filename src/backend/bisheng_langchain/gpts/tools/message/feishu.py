# Tool descriptions are model-facing Chinese copy, so full-width punctuation is
# intentional and RUF001/RUF002 (ambiguous unicode) would flag every sentence.
# ruff: noqa: RUF001, RUF002

import json
from typing import Any

import requests
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import MultArgsSchemaTool

# One schema per method. The field set of a schema MUST stay identical to the
# signature of the method it is bound to: LangChain's _parse_input injects a
# value for every field that carries a default, so a field the method does not
# accept arrives as an unexpected keyword argument and raises TypeError, while a
# missing field leaves a parameter unfilled. Field descriptions mirror the
# api_params of the matching preset rows in database/data/t_gpts_tools.json.


class SendMessageInput(BaseModel):
    message: str = Field(description="发送的文本消息内容")
    receive_id: str = Field(description="消息接收者的id")
    receive_id_type: str = Field(
        description="用户id类型，可选值：open_id（标识一个用户在某个应用中的身份）；"
        "union_id（标识一个用户在某个应用开发商下的身份）；user_id（标识一个用户在某个租户内的身份）；"
        "email（以用户的真实邮箱来标识用户）；chat_id（以群 ID 来标识群聊）"
    )


class GetChatMessagesInput(BaseModel):
    container_id: str = Field(description="单聊或群聊的id，或话题 id")
    container_id_type: str = Field(
        description="容器类型。 可选值有： chat：包含单聊（p2p）和群聊（group）； thread：话题 。"
    )
    start_time: str | None = Field(
        default=None,
        description="待查询历史信息的起始时间，秒级时间戳。 注意：thread 容器类型暂不支持获取指定时间范围内的消息。",
    )
    end_time: str | None = Field(
        default=None,
        description="待查询历史信息的结束时间，秒级时间戳。注意：thread 容器类型暂不支持获取指定时间范围内的消息。",
    )
    page_size: int | None = Field(
        default=20, description="分页大小，单次请求所返回的数据条目数，默认值20，取值范围1~50。"
    )
    page_token: str | None = Field(
        default=None,
        description="分页标记，第一次请求不填，表示从头开始遍历；分页查询结果还有更多项时会同时返回新的 page_token，"
        "下次遍历可采用该 page_token 获取查询结果",
    )
    sort_type: str | None = Field(
        default="ByCreateTimeAsc",
        description="可选值有：ByCreateTimeAsc（按消息创建时间升序排列）；ByCreateTimeDesc（按消息创建时间降序排列）",
    )


ARGS_SCHEMAS: dict[str, type[BaseModel]] = {
    "send_message": SendMessageInput,
    "get_chat_messages": GetChatMessagesInput,
}


class FeishuMessageTool(BaseModel):
    API_BASE_URL: str = "https://open.feishu.cn/open-apis"
    app_id: str = Field(description="app_id")
    app_secret: str = Field(description="app_secret")

    def send_message(self, message: str, receive_id: str, receive_id_type: str) -> str:
        """
        向指定用户或者群聊发送飞书消息

        Args:
            message: 发送的文本消息内容
            receive_id: 消息接收者的id
            receive_id_type: 用户id类型，可选值：open_id、union_id、user_id、email、chat_id

        Returns:
            dict: 飞书接口的响应结果
        """
        # 构建请求头
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.get_access_token()}"}
        # 构建请求体
        url = f"{self.API_BASE_URL}/im/v1/messages?receive_id_type={receive_id_type}"
        content = {"text": message}
        payload = {"receive_id": receive_id, "msg_type": "text", "content": json.dumps(content, ensure_ascii=False)}
        try:
            # 发送 POST 请求
            response = requests.post(url=url, headers=headers, json=payload)

            # 检查响应状态
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            return f"发送消息失败: {e!s}"

    def get_chat_messages(
        self,
        container_id: str,
        container_id_type: str,
        start_time: str | None = None,
        end_time: str | None = None,
        page_size: int | None = 20,
        page_token: str | None = None,
        sort_type: str | None = "ByCreateTimeAsc",
    ) -> str:
        """
        获取飞书单聊或群聊的历史消息记录，支持在单聊或群聊中快速获取相关内容

        Args:
            container_id: 单聊或群聊的id，或话题 id
            container_id_type: 容器类型，可选值：chat（单聊和群聊）、thread（话题）
            start_time: 待查询历史信息的起始时间，秒级时间戳
            end_time: 待查询历史信息的结束时间，秒级时间戳
            page_size: 分页大小，取值范围1~50
            page_token: 分页标记，第一次请求不填
            sort_type: 排序方式，可选值：ByCreateTimeAsc、ByCreateTimeDesc

        Returns:
            dict: 飞书接口返回的消息数据
        """
        url = f"{self.API_BASE_URL}/im/v1/messages"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.get_access_token()}"}
        params = {
            "container_id": container_id,
            "container_id_type": container_id_type,
            "start_time": start_time,
            "end_time": end_time,
            "page_token": page_token,
        }
        if page_size:
            params["page_size"] = page_size
        if sort_type:
            params["sort_type"] = sort_type
        try:
            response = requests.get(url=url, headers=headers, params=params)
        except requests.exceptions.RequestException as e:
            return f"获取消息失败: {e!s}"

        if response.json()["code"] != 0:
            return f"获取消息失败: {response.json()}"

        return response.json()["data"]

    def get_access_token(self) -> str:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        params = {"app_id": self.app_id, "app_secret": self.app_secret}
        response = requests.post(url, json=params)
        if response.json()["code"] != 0:
            raise Exception("app_id or app_secret error")
        return response.json()["tenant_access_token"]

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> MultArgsSchemaTool:
        attr_name = name.split("_", 1)[-1]
        args_schema = ARGS_SCHEMAS.get(attr_name)
        if args_schema is None:
            raise ValueError(f"unsupported feishu tool: {name}")
        c = FeishuMessageTool(**kwargs)
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=args_schema,
        )
