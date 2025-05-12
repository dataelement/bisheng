"""Tool for the Bing search API."""

from typing import Optional, Type

from pydantic import BaseModel, Field
from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool


class BingSearchInput(BaseModel):
    query: str = Field(description="query to look up in Bing search")


class BingSearchRun(BaseTool):
    """Tool that queries the Bing search API."""

    name: str = "bing_search"
    description: str = (
        "A wrapper around Bing Search. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a search query."
    )
    args_schema: Type[BaseModel] = BingSearchInput
    api_wrapper: BingSearchAPIWrapper

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        return self.api_wrapper.run(query)


class BingSearchResults(BaseTool):
    """Tool that queries the Bing Search API and gets back json."""

    name: str = "bing_search"
    description: str = (
        "A wrapper around Bing Search. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a search query. Output is a JSON array of the query results"
    )
    num_results: int = 5
    args_schema: Type[BaseModel] = BingSearchInput
    api_wrapper: BingSearchAPIWrapper

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        return str(self.api_wrapper.results(query, self.num_results))
