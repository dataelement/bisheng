from typing import Any

from pydantic import Field
from loguru import logger

from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase, MultArgsSchemaTool

class InputArgs:
    api_key: str = Field(description="apikey")
    target_url: str = Field(description="params target_url")
    max_depth: str = Field(description="params maxDepth")
    limit: str = Field(description="params limit")

class SiliconFlow(APIToolBase):


    @classmethod
    def stable_diffusion(cls, api_key: str, prompt: str) -> "SiliconFlow":
        """silicon stable diffusion api"""
        url = "https://api.siliconflow.cn/v1/images/generations"
        input_key = "prompt"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        }
        params= {
            "model": "stabilityai/stable-diffusion-3-5-large",
            "prompt": prompt,
            "seed": 4999999999,
        }

        return cls(url=url, api_key=api_key, input_key=input_key, headers=headers,params=params)

    @classmethod
    def flux(cls, api_key: str, prompt: str) -> "SiliconFlow":
        """silicon flux api"""
        url = "https://api.siliconflow.cn/v1/images/generations"
        input_key = "prompt"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        }
        params= {
            "model": "black-forest-labs/FLUX.1-pro",
            "prompt": prompt,
            "seed": 4999999999,
        }

        return cls(url=url, api_key=api_key, input_key=input_key, headers=headers,params=params)

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "SiliconFlow":
        attr_name = name.split("_", 1)[-1]
        class_method = getattr(cls, attr_name)

        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=InputArgs,
        )

