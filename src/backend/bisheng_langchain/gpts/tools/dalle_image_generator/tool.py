import logging
from typing import Optional, Type, Any

from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from langchain_community.utils.openai import is_openai_v1
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from bisheng_langchain.utils.azure_dalle_image_generator import AzureDallEWrapper

logger = logging.getLogger(__name__)


class DallEInput(BaseModel):
    query: str = Field(description="Description about image.")


class ProxyDallEAPIWrapper(DallEAPIWrapper):
    """Wrapper for OpenAI's DALL-E Image Generator with proxy support."""

    http_async_client: Any

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        """Validate that api key and python package exists in environment."""
        try:
            import openai

        except ImportError:
            raise ImportError(
                "Could not import openai python package. "
                "Please install it with `pip install openai`."
            )

        if is_openai_v1():
            client_params = {
                "api_key": self.openai_api_key.get_secret_value()
                if self.openai_api_key
                else None,
                "organization": self.openai_organization,
                "base_url": self.openai_api_base,
                "timeout": self.request_timeout,
                "max_retries": self.max_retries,
                "default_headers": self.default_headers,
                "default_query": self.default_query,
            }

            if not self.client:
                self.client = openai.OpenAI(**client_params,
                                            http_client=self.http_client).images  # type: ignore[arg-type, arg-type, arg-type, arg-type, arg-type, arg-type, arg-type, arg-type]
            if not self.async_client:
                self.async_client = openai.AsyncOpenAI(**client_params,
                                                       http_client=self.http_async_client).images  # type: ignore[arg-type, arg-type, arg-type, arg-type, arg-type, arg-type, arg-type, arg-type]
        elif not self.client:
            self.client = openai.Image  # type: ignore[attr-defined]
        else:
            pass
        return self


class DallEImageGenerator(BaseTool):
    name: str = "dalle_image_generator"
    description: str = (
        "A wrapper around OpenAI DALL-E API. Useful for when you need to generate images from a text description. Input should be an image description."
    )
    args_schema: Type[BaseModel] = DallEInput
    api_wrapper: DallEAPIWrapper | AzureDallEWrapper

    def _run(
            self,
            query: str,
            run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        return self.api_wrapper.run(query)
