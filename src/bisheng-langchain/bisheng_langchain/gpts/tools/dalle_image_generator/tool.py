from typing import Optional, Type

from langchain.pydantic_v1 import BaseModel, Field
from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool


class DallEInput(BaseModel):
    query: str = Field(description="Description about image.")


class DallEImageGenerator(BaseTool):

    name: str = "Dall-E-Image-Generator"
    description: str = (
        "A wrapper around OpenAI DALL-E API. Useful for when you need to generate images from a text description. Input should be an image description."
    )
    args_schema: Type[BaseModel] = DallEInput
    api_wrapper: DallEAPIWrapper

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        return self.api_wrapper.run(query)
