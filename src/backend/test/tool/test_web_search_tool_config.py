import unittest

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.tools.web_search.tool import (
    BoChaSearch,
    SearchTool,
    SearXNGSearch,
    TavilySearch,
)


class TestWebSearchToolConfig(unittest.TestCase):
    def test_searxng_supports_base_url_alias_from_frontend_config(self):
        tool = SearchTool.init_search_tool("searXNG", base_url="https://searx.example.com/")

        self.assertIsInstance(tool, SearXNGSearch)
        self.assertEqual(tool.base_url, "https://searx.example.com")

    def test_fixed_endpoint_providers_allow_base_url_override(self):
        bocha_tool = SearchTool.init_search_tool(
            "bocha",
            api_key="test-key",
            base_url="https://proxy.example.com/bocha",
        )
        tavily_tool = SearchTool.init_search_tool(
            "tavily",
            api_key="test-key",
            base_url="https://proxy.example.com/tavily",
        )

        self.assertIsInstance(bocha_tool, BoChaSearch)
        self.assertEqual(bocha_tool.base_url, "https://proxy.example.com/bocha")
        self.assertIsInstance(tavily_tool, TavilySearch)
        self.assertEqual(tavily_tool.base_url, "https://proxy.example.com/tavily")

    def test_load_tools_passes_frontend_web_search_config_through_to_provider(self):
        tool = load_tools(
            {
                "web_search": {
                    "type": "searXNG",
                    "config": {
                        "searXNG": {
                            "base_url": "https://searx.internal.example",
                        }
                    },
                }
            }
        )[0]

        self.assertEqual(tool.name, "web_search")
        self.assertIsInstance(tool.api_wrapper, SearXNGSearch)
        self.assertEqual(tool.api_wrapper.base_url, "https://searx.internal.example")
