from typing import Any, Optional

import requests
from loguru import logger
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import (APIToolBase,
                                                         MultArgsSchemaTool)


class InputArgs(BaseModel):
    prompt: str = Field(description="text to image prompt ")
    negative_prompt: Optional[str] = Field(default=None,description="text to image negative_prompt")


class SiliconFlow(APIToolBase):

    siliconflow_api_key: str = Field(description="params api key")

    def stable_diffusion(self, negative_prompt: str, prompt: str) -> str:
        """silicon stable diffusion api"""
        url = "https://api.siliconflow.cn/v1/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.siliconflow_api_key,
        }
        params = {
            "model": "stabilityai/stable-diffusion-3-5-large",
            "prompt": prompt,
            "negative_prompt": negative_prompt,
        }

        response = requests.post(url, json=params, headers=headers)
        return response.text

    def flux(self, prompt: str) -> str:
        """silicon flux api"""
        url = "https://api.siliconflow.cn/v1/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.siliconflow_api_key,
        }
        params = {
            "model": "black-forest-labs/FLUX.1-pro",
            "prompt": prompt,
        }

        response = requests.post(url, json=params, headers=headers)
        return response.text

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "SiliconFlow":
        attr_name = name.split("_", 1)[-1]
        c = SiliconFlow(**kwargs)
        class_method = getattr(c, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )
