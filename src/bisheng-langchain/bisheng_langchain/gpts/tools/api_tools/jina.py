from typing import Any

import requests
from pydantic import BaseModel

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    input_key: str


class JinaTool(APIToolBase):

    @classmethod
    def get_url(cls, url: str, input_key: str) -> "JinaTool":
        """get url from jina api"""
        url = "https://r.jina.ai/".join(url)

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + input_key,
        }

        response = requests.get(url, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            return response.json()

        return cls(url=url, headers=headers)

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "JinaTool":
        attr_name = name.split("_", 1)[-1]
        class_method = getattr(cls, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
