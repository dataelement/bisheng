from typing import Any

from langchain_core.messages import FunctionMessage, ToolMessage


class LiberalFunctionMessage(FunctionMessage):
    content: Any


class LiberalToolMessage(ToolMessage):
    content: Any
