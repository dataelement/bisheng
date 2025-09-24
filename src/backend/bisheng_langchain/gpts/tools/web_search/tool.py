from abc import abstractmethod, ABC
from typing import Type

import requests
from langchain_community.utilities import BingSearchAPIWrapper
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

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
    def invoke(self, query: str, **kwargs) -> (str, list):
        """
        Invoke the search tool with the given query.
        returns
            - str: The search result as a string.
            - list: A list of search result link info.
        """

        # Here you would implement the actual search logic
        # For demonstration purposes, we'll just return a dummy response
        raise NotImplementedError()

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

    def invoke(self, query: str, **kwargs) -> (str, list):
        bingtool = BingSearchResults(api_wrapper=BingSearchAPIWrapper(bing_subscription_key=self.api_key,
                                                                      bing_search_url=self.base_url),
                                     num_results=10)
        res = bingtool.invoke({'query': query})
        if isinstance(res, str):
            res = eval(res)
        search_res = ''
        web_list = []
        for index, result in enumerate(res):
            # 处理搜索结果
            snippet = result.get('snippet')
            search_res += f'[webpage ${index} begin]\n${snippet}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': result.get('title'),
                'url': result.get('link'),
                'snippet': snippet
            })
        return search_res, web_list


class BoChaSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://api.bochaai.com/v1/web-search'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def invoke(self, query: str, **kwargs) -> (str, list):
        # Implement the search logic for BoCha here
        # For demonstration purposes, we'll just return a dummy response
        result = self._requests(self.base_url, method='POST', json={'query': query, 'summary': True},
                                headers=self.headers)
        if result.get('code') != 200:
            raise Exception(f"BoCha Error: {result}")
        web_pages = result.get('data', {}).get('webPages', {}).get('value', [])
        # parse result
        search_res = ''
        web_list = []
        for index, item in enumerate(web_pages):
            search_res += f'[webpage ${index} begin]\n${item.get("snippet")}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': item.get('name'),
                'url': item.get('url'),
                'snippet': item.get('snippet')
            })
        return search_res, web_list


class JinaDeepSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://deepsearch.jina.ai/v1/chat/completions'
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def invoke(self, query: str, **kwargs) -> (str, list):
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
        search_res = ''
        web_list = []
        for index, item in enumerate(choices):
            item_message = item.get('message', {})
            search_res += f'[webpage ${index} begin]\n${item_message.get("content")}\n[webpage ${index} end]\n\n'
            for one_web in item_message.get('annotations', []):
                one_web_info = one_web.get('url_citation', {})
                web_list.append({
                    'title': one_web_info.get('title'),
                    'url': one_web.get('url'),
                    'snippet': one_web.get('exactQuote')
                })
        return search_res, web_list


class SerpSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://serpapi.com/search.json'

    def invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='GET', params={'q': query, 'api_key': self.api_key})

        answer_result = result.get('organic_results', [])
        search_res = ''
        web_list = []
        for index, item in enumerate(answer_result):
            search_res += f'[webpage ${index} begin]\n${item.get("snippet")}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': item.get('title'),
                'url': item.get('link'),
                'snippet': item.get('snippet')
            })
        return search_res, web_list


class TavilySearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.base_url = 'https://api.tavily.com/search'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='POST', json={'query': query}, headers=self.headers)

        answers = result.get('results', [])

        # parse result
        search_res = ''
        web_list = []
        for index, item in enumerate(answers):
            search_res += f'[webpage ${index} begin]\n${item.get("content")}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': item.get('title'),
                'url': item.get('url'),
                'snippet': item.get('content')
            })
        return search_res, web_list


class CloudswaySearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = kwargs.get('api_key')
        self.endpoint = kwargs.get('endpoint')
        self.base_url = f'https://searchapi.cloudsway.net/search/{self.endpoint}/smart'
        self.headers = {'Authorization': f'Bearer {self.api_key}'}

    def invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(self.base_url, method='GET', params={'q': query}, headers=self.headers)

        answers = result.get('webPages', {}).get('value', [])

        # parse result
        search_res = ''
        web_list = []
        for index, item in enumerate(answers):
            search_res += f'[webpage ${index} begin]\n${item.get("snippet")}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': item.get('name'),
                'url': item.get('url'),
                'snippet': item.get('snippet')
            })
        return search_res, web_list


class SearXNGSearch(SearchTool):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.base_url = kwargs.get('server_url').rstrip('/')

    def invoke(self, query: str, **kwargs) -> (str, list):
        result = self._requests(f'{self.base_url}/search', method='GET',
                                params={'q': query, 'format': 'json'})

        answers = result.get('results', [])

        # parse result
        search_res = ''
        web_list = []
        for index, item in enumerate(answers):
            search_res += f'[webpage ${index} begin]\n${item.get("content")}\n[webpage ${index} end]\n\n'
            web_list.append({
                'title': item.get('title'),
                'url': item.get('url'),
                'snippet': item.get('content')
            })
        return search_res, web_list
