from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    jina_api_key: str = Field(description="jina api key")
    target_url: Optional[str] = Field(default=None,description="params target_url")


class JinaTool(BaseModel):

    @classmethod
    def get_markdown(cls, target_url: str, jina_api_key: str) -> Any:
        """get url from jina api"""
        url = "https://r.jina.ai/" + target_url

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + jina_api_key,
        }

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text

        return cls()

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "JinaTool":
        attr_name = name.split("_", 1)[-1]
        class_method = getattr(cls, attr_name)

        input_args = InputArgs(**kwargs)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=input_args,
        )
