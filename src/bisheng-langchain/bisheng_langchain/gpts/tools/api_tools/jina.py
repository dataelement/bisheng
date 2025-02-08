from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    # jina_api_key: Optional[str] = Field(default=None,description="jina api key")
    target_url: Optional[str] = Field(default=None,description="params target_url")


class JinaTool(BaseModel):

    jina_api_key: str = Field(default=None,description="jina api key")

    def get_markdown(self, target_url: str) -> Any:
        """get url from jina api"""
        url = "https://r.jina.ai/" + target_url

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.jina_api_key,
        }

        response = requests.get(url, headers=headers)

        return response.text
        


    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "JinaTool":
        attr_name = name.split("_", 1)[-1]
        c = JinaTool(jina_api_key=kwargs.get('jina_api_key'))
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
