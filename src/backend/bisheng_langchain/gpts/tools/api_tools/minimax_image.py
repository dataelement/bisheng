import json
from typing import Any, Literal

import requests
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase, MultArgsSchemaTool
from bisheng_langchain.gpts.tools.api_tools.minimax_image_core import (
    build_image_generation_payload,
    parse_image_generation_response,
)


class MiniMaxImageInput(BaseModel):
    prompt: str = Field(description="Text description of the image", min_length=1, max_length=1500)
    model: Literal["image-01", "image-01-live"] = "image-01"
    aspect_ratio: Literal["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"] | None = None
    width: int | None = Field(default=None, ge=512, le=2048, multiple_of=8)
    height: int | None = Field(default=None, ge=512, le=2048, multiple_of=8)
    response_format: Literal["url", "base64"] = "url"
    seed: int | None = None
    n: int = Field(default=1, ge=1, le=9)
    prompt_optimizer: bool = False

    @model_validator(mode="after")
    def validate_dimensions(self) -> "MiniMaxImageInput":
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be provided together")
        return self


class MiniMaxImage(APIToolBase):
    minimax_api_key: str = Field(description="MiniMax API key")
    minimax_base_url: str = Field(default="https://api.minimax.io", description="MiniMax API base URL")

    def generate(
        self,
        prompt: str,
        model: str = "image-01",
        aspect_ratio: str | None = None,
        width: int | None = None,
        height: int | None = None,
        response_format: str = "url",
        seed: int | None = None,
        n: int = 1,
        prompt_optimizer: bool = False,
    ) -> str:
        """Generate images from a text prompt with MiniMax."""
        payload = build_image_generation_payload(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            width=width,
            height=height,
            response_format=response_format,
            seed=seed,
            n=n,
            prompt_optimizer=prompt_optimizer,
        )
        response = requests.post(
            f"{self.minimax_base_url.rstrip('/')}/v1/image_generation",
            json=payload,
            headers={"Authorization": f"Bearer {self.minimax_api_key}", "Content-Type": "application/json"},
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        result = parse_image_generation_response(response.json(), response_format)
        return json.dumps(result, ensure_ascii=False)

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> BaseTool:
        instance = cls(**kwargs)
        return MultArgsSchemaTool(
            name=name,
            description=instance.generate.__doc__,
            func=instance.generate,
            args_schema=MiniMaxImageInput,
        )
