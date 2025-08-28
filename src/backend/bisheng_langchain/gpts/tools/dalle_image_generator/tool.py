import logging
from typing import Optional, Type

from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng_langchain.utils.azure_dalle_image_generator import AzureDallEWrapper

logger = logging.getLogger(__name__)


class DallEInput(BaseModel):
    query: str = Field(description="Description about image.")


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
