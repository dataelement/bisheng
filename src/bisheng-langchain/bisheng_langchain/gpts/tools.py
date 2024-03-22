from enum import Enum
import requests
import json
import os
from functools import lru_cache
from typing import Optional
from langchain.tools import tool
from langchain.pydantic_v1 import BaseModel, Field
from langchain.tools.retriever import create_retriever_tool
from langchain_community.retrievers import WikipediaRetriever

from langchain_community.retrievers.you import YouRetriever
from langchain_community.tools import ArxivQueryRun
from langchain_community.utilities.arxiv import ArxivAPIWrapper
from typing_extensions import TypedDict


class ArxivInput(BaseModel):
    query: str = Field(description="search query to look up")


arxiv_tool = ArxivQueryRun(api_wrapper=ArxivAPIWrapper(), args_schema=ArxivInput)


@tool("calculator")
def calculate_tool(operation):
    """Useful to perform any mathematical calculations,
    like sum, minus, multiplication, division, etc.
    The input to this tool should be a mathematical
    expression, a couple examples are `200*7` or `5000/2*10`
    """
    try:
        return eval(operation)
    except SyntaxError:
        return "Error: Invalid syntax in mathematical expression"


class AvailableTools(str, Enum):
    ARXIV = "arxiv"
    CALCULATE = "calculate"


TOOLS = {
    AvailableTools.ARXIV: arxiv_tool,
    AvailableTools.CALCULATE: calculate_tool,
}
