from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel


class McpTool(BaseTool):

    args_schema: Type[BaseModel] = BaseModel

    pass
