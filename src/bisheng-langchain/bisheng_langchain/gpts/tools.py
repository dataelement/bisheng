from enum import Enum
from functools import lru_cache
from typing import Optional

from langchain.pydantic_v1 import BaseModel, Field
from langchain.tools.retriever import create_retriever_tool
from langchain_community.agent_toolkits.connery import ConneryToolkit
from langchain_community.retrievers import (
    KayAiRetriever,
    PubMedRetriever,
    WikipediaRetriever,
)
from langchain_community.retrievers.you import YouRetriever
from langchain_community.tools import ArxivQueryRun, DuckDuckGoSearchRun
from langchain_community.tools.connery import ConneryService
from langchain_community.tools.tavily_search import (
    TavilyAnswer as _TavilyAnswer,
)
from langchain_community.tools.tavily_search import (
    TavilySearchResults,
)
from langchain_community.utilities.arxiv import ArxivAPIWrapper
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from typing_extensions import TypedDict



class DDGInput(BaseModel):
    query: str = Field(description="search query to look up")


class ArxivInput(BaseModel):
    query: str = Field(description="search query to look up")


class PythonREPLInput(BaseModel):
    query: str = Field(description="python command to run")


class AvailableTools(str, Enum):
    ACTION_SERVER = "action_server_by_robocorp"
    CONNERY = "ai_action_runner_by_connery"
    DDG_SEARCH = "ddg_search"
    TAVILY = "search_tavily"
    TAVILY_ANSWER = "search_tavily_answer"
    ARXIV = "arxiv"
    YOU_SEARCH = "you_search"
    SEC_FILINGS = "sec_filings_kai_ai"
    PRESS_RELEASES = "press_releases_kai_ai"
    PUBMED = "pubmed"
    WIKIPEDIA = "wikipedia"


class ToolConfig(TypedDict):
    ...


class BaseTool(BaseModel):
    type: AvailableTools
    name: Optional[str]
    description: Optional[str]
    config: Optional[ToolConfig]
    multi_use: Optional[bool] = False


class ActionServerConfig(ToolConfig):
    url: str
    api_key: str


class ActionServer(BaseTool):
    type: AvailableTools = Field(AvailableTools.ACTION_SERVER, const=True)
    name: str = Field("Action Server by Robocorp", const=True)
    description: str = Field(
        (
            "Run AI actions with "
            "[Robocorp Action Server](https://github.com/robocorp/robocorp)."
        ),
        const=True,
    )
    config: ActionServerConfig
    multi_use: bool = Field(True, const=True)


class Connery(BaseTool):
    type: AvailableTools = Field(AvailableTools.CONNERY, const=True)
    name: str = Field("AI Action Runner by Connery", const=True)
    description: str = Field(
        (
            "Connect OpenGPTs to the real world with "
            "[Connery](https://github.com/connery-io/connery)."
        ),
        const=True,
    )


class DDGSearch(BaseTool):
    type: AvailableTools = Field(AvailableTools.DDG_SEARCH, const=True)
    name: str = Field("DuckDuckGo Search", const=True)
    description: str = Field(
        "Search the web with [DuckDuckGo](https://pypi.org/project/duckduckgo-search/).",
        const=True,
    )


class Arxiv(BaseTool):
    type: AvailableTools = Field(AvailableTools.ARXIV, const=True)
    name: str = Field("Arxiv", const=True)
    description: str = Field("Searches [Arxiv](https://arxiv.org/).", const=True)


class YouSearch(BaseTool):
    type: AvailableTools = Field(AvailableTools.YOU_SEARCH, const=True)
    name: str = Field("You.com Search", const=True)
    description: str = Field(
        "Uses [You.com](https://you.com/) search, optimized responses for LLMs.",
        const=True,
    )


class SecFilings(BaseTool):
    type: AvailableTools = Field(AvailableTools.SEC_FILINGS, const=True)
    name: str = Field("SEC Filings (Kay.ai)", const=True)
    description: str = Field(
        "Searches through SEC filings using [Kay.ai](https://www.kay.ai/).", const=True
    )


class PressReleases(BaseTool):
    type: AvailableTools = Field(AvailableTools.PRESS_RELEASES, const=True)
    name: str = Field("Press Releases (Kay.ai)", const=True)
    description: str = Field(
        "Searches through press releases using [Kay.ai](https://www.kay.ai/).",
        const=True,
    )


class PubMed(BaseTool):
    type: AvailableTools = Field(AvailableTools.PUBMED, const=True)
    name: str = Field("PubMed", const=True)
    description: str = Field(
        "Searches [PubMed](https://pubmed.ncbi.nlm.nih.gov/).", const=True
    )


class Wikipedia(BaseTool):
    type: AvailableTools = Field(AvailableTools.WIKIPEDIA, const=True)
    name: str = Field("Wikipedia", const=True)
    description: str = Field(
        "Searches [Wikipedia](https://pypi.org/project/wikipedia/).", const=True
    )


class Tavily(BaseTool):
    type: AvailableTools = Field(AvailableTools.TAVILY, const=True)
    name: str = Field("Search (Tavily)", const=True)
    description: str = Field(
        (
            "Uses the [Tavily](https://app.tavily.com/) search engine. "
            "Includes sources in the response."
        ),
        const=True,
    )


class TavilyAnswer(BaseTool):
    type: AvailableTools = Field(AvailableTools.TAVILY_ANSWER, const=True)
    name: str = Field("Search (short answer, Tavily)", const=True)
    description: str = Field(
        (
            "Uses the [Tavily](https://app.tavily.com/) search engine. "
            "This returns only the answer, no supporting evidence."
        ),
        const=True,
    )


@lru_cache(maxsize=1)
def _get_duck_duck_go():
    return DuckDuckGoSearchRun(args_schema=DDGInput)


@lru_cache(maxsize=1)
def _get_arxiv():
    return ArxivQueryRun(api_wrapper=ArxivAPIWrapper(), args_schema=ArxivInput)


@lru_cache(maxsize=1)
def _get_you_search():
    return create_retriever_tool(
        YouRetriever(n_hits=3, n_snippets_per_hit=3),
        "you_search",
        "Searches for documents using You.com",
    )


@lru_cache(maxsize=1)
def _get_sec_filings():
    return create_retriever_tool(
        KayAiRetriever.create(
            dataset_id="company", data_types=["10-K", "10-Q"], num_contexts=3
        ),
        "sec_filings_search",
        "Search for a query among SEC Filings",
    )


@lru_cache(maxsize=1)
def _get_press_releases():
    return create_retriever_tool(
        KayAiRetriever.create(
            dataset_id="company", data_types=["PressRelease"], num_contexts=6
        ),
        "press_release_search",
        "Search for a query among press releases from US companies",
    )


@lru_cache(maxsize=1)
def _get_pubmed():
    return create_retriever_tool(
        PubMedRetriever(), "pub_med_search", "Search for a query on PubMed"
    )


@lru_cache(maxsize=1)
def _get_wikipedia():
    return create_retriever_tool(
        WikipediaRetriever(), "wikipedia", "Search for a query on Wikipedia"
    )


@lru_cache(maxsize=1)
def _get_tavily():
    tavily_search = TavilySearchAPIWrapper()
    return TavilySearchResults(api_wrapper=tavily_search)


@lru_cache(maxsize=1)
def _get_tavily_answer():
    tavily_search = TavilySearchAPIWrapper()
    return _TavilyAnswer(api_wrapper=tavily_search)


@lru_cache(maxsize=1)
def _get_connery_actions():
    connery_service = ConneryService()
    connery_toolkit = ConneryToolkit.create_instance(connery_service)
    tools = connery_toolkit.get_tools()
    return tools


TOOLS = {
    AvailableTools.CONNERY: _get_connery_actions,
    AvailableTools.DDG_SEARCH: _get_duck_duck_go,
    AvailableTools.ARXIV: _get_arxiv,
    AvailableTools.YOU_SEARCH: _get_you_search,
    AvailableTools.SEC_FILINGS: _get_sec_filings,
    AvailableTools.PRESS_RELEASES: _get_press_releases,
    AvailableTools.PUBMED: _get_pubmed,
    AvailableTools.TAVILY: _get_tavily,
    AvailableTools.WIKIPEDIA: _get_wikipedia,
    AvailableTools.TAVILY_ANSWER: _get_tavily_answer,
}
