import json
from abc import abstractmethod, ABC
from typing import Type

import requests
from langchain_community.utilities import BingSearchAPIWrapper
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from urllib3.util.url import parse_url

from bisheng_langchain.gpts.tools.bing_search.tool import BingSearchResults


class SearchInput(BaseModel):
    query: str = Field(description="Search query")


class SearchTool(ABC):
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def _requests(self, url: str, method: str, **kwargs):
        """Base requests method to handle GET and POST requests."""
        if method == 'GET':
            response = requests.get(url, **kwargs)
        elif method == 'POST':
            response = requests.post(url, **kwargs)
        else:
            raise ValueError("Unsupported HTTP method. Use 'GET' or 'POST'.")

        if response.status_code != 200:
            raise Exception(f"Request {url} failed: {response.status_code} - {response.text}")
        return response.json()

    # 抽象类
    @abstractmethod
    def _invoke(self, query: str, **kwargs) -> (str, list):
        raise NotImplementedError()

    def invoke(self, query: str, **kwargs) -> (str, list):
        """
        Invoke the search tool with the given query.
        returns
            - str: The search result as a string.
            - list: A list of search result link info.
        """

        # Here you would implement the actual search logic
        # For demonstration purposes, we'll just return a dummy response
        result = self._invoke(query, **kwargs)
        return json.dumps(result, ensure_ascii=False)

    @classmethod
    def get_host_from_url(cls, url: str) -> str:
        """Extract the host from a given URL."""
        if not url:
            return ""
        return parse_url(url).host

    @classmethod
    def init_search_tool(cls, name: str, *args, **kwargs) -> "SearchTool":
        """Initialize the search tool with the given name and arguments."""
        tool_class: dict = {
            'bing': BingSearch,
            'bocha': BoChaSearch,
            'jina': JinaDeepSearch,
            'serp': SerpSearch,
            'tavily': TavilySearch,
            'cloudsway': CloudswaySearch,
            'searXNG': SearXNGSearch,
        }
        if name not in tool_class:
            raise ValueError(f"Tool {name} not found.")
        c = tool_class[name](*args, **kwargs)
        return c


class WebSearchTool(BaseTool):
    """web search tools."""
    name: str = "web_search"
    description: str = "使用 query 进行联网检索并返回结果。"
    args_schema: Type[BaseModel] = SearchInput
    api_wrapper: SearchTool = Field(..., description="The search API wrapper to use for web search.")

    def _run(self, query: str, **kwargs) -> str:
        """Use the tool."""
        return self.api_wrapper.invoke(query, **kwargs)


class BingSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = kwargs.get('base_url')

    def _invoke(self, query: str, **kwargs) -> (str, list):
        bingtool = BingSearchResults(api_wrapper=BingSearchAPIWrapper(bing_subscription_key=self.api_key,
                                                                      bing_search_url=self.base_url),
                                     num_results=10)
        res = bingtool.invoke({'query': query})
        if isinstance(res, str):
            res = eval(res)
        web_list = []
        for index, result in enumerate(res):
            # 处理搜索结果
            snippet = result.get('snippet')
            web_list.append({
                'title': result.get('title'),
                'url': result.get('link'),
                'snippet': snippet,
                'thumbnail': result.get('thumbnail'),
                'site_name': self.get_host_from_url(result.get('link'))
            })
        return web_list


class BoChaSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://api.bochaai.com/v1/web-search'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def _invoke(self, query: str, **kwargs) -> (str, list):
        # Implement the search logic for BoCha here
        # For demonstration purposes, we'll just return a dummy response
        result = self._requests(self.base_url, method='POST', json={'query': query, 'summary': True},
                                headers=self.headers)
        if result.get('code') != 200:
            raise Exception(f"BoCha Error: {result}")
        web_pages = result.get('data', {}).get('webPages', {}).get('value', [])
        web_list = []
        for index, item in enumerate(web_pages):
            web_list.append({
                'title': item.get('name'),
                'url': item.get('url'),
                'snippet': item.get('snippet'),
                'thumbnail': item.get('siteIcon'),
                'site_name': item.get('siteName') or self.get_host_from_url(item.get('url')),
            })
        return web_list


class JinaDeepSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://deepsearch.jina.ai/v1/chat/completions'
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _invoke(self, query: str, **kwargs) -> (str, list):
        req_data = {
            "model": "jina-deepsearch-v1",
            "messages": [
                {
                    "role": "user",
                    "content": query
                },
            ],
            "stream": False,
            "reasoning_effort": "low",
            "max_attempts": 1,
            "no_direct_answer": False
        }
        result = self._requests(self.base_url, method='POST', json=req_data, headers=self.headers)

        choices = result.get('choices', [])
        web_list = []
        for index, item in enumerate(choices):
            item_message = item.get('message', {})
            for one_web in item_message.get('annotations', []):
                one_web_info = one_web.get('url_citation', {})
                web_list.append({
                    'title': one_web_info.get('title'),
                    'url': one_web.get('url'),
                    'snippet': one_web.get('exactQuote'),
                    'thumbnail': None,
                    'site_name': self.get_host_from_url(one_web.get('url')),
                })
        return web_list


class SerpSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.engine = kwargs.get('engine')
        self.base_url = 'https://serpapi.com/search.json'

    def _invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='GET', params={'q': query, 'api_key': self.api_key,
                                                                     'engine': self.engine})

        answer_result = result.get('organic_results', [])
        web_list = []
        for index, item in enumerate(answer_result):
            web_list.append({
                'title': item.get('title'),
                'url': item.get('link'),
                'snippet': item.get('snippet'),
                'thumbnail': item.get('source_logo') or item.get('thumbnail'),
                'site_name': self.get_host_from_url(item.get('link')),
            })
        return web_list


class TavilySearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://api.tavily.com/search'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def _invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='POST', json={'query': query}, headers=self.headers)

        answers = result.get('results', [])

        web_list = []
        for index, item in enumerate(answers):
            web_list.append({
                'title': item.get('title'),
                'url': item.get('url'),
                'snippet': item.get('content'),
                'thumbnail': item.get('favicon'),
                'site_name': self.get_host_from_url(item.get('url')),
            })
        return web_list


class CloudswaySearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.endpoint = kwargs.get('endpoint')
        self.base_url = f'https://searchapi.cloudsway.net/search/{self.endpoint}/smart'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def _invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='GET', params={'q': query}, headers=self.headers)

        answers = result.get('webPages', {}).get('value', [])

        # parse result
        web_list = []
        for index, item in enumerate(answers):
            web_list.append({
                'title': item.get('name'),
                'url': item.get('url'),
                'snippet': item.get('snippet'),
                'thumbnail': item.get('thumbnailUrl'),
                'site_name': item.get('siteName') or self.get_host_from_url(item.get('url')),
            })
        return web_list


class SearXNGSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.base_url = kwargs.get('server_url').rstrip('/')

    def _invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(f'{self.base_url}/search', method='GET',
                                params={'q': query, 'format': 'json'})

        answers = result.get('results', [])

        web_list = []
        for index, item in enumerate(answers):
            web_list.append({
                'title': item.get('title'),
                'url': item.get('url'),
                'snippet': item.get('content'),
                'thumbnail': item.get('thumbnail'),
                'site_name': self.get_host_from_url(item.get('url')),
            })
        return web_list
