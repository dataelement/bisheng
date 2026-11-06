import os
import unittest

from bisheng.core.ai import ChatOpenAICompatible
from bisheng.llm.domain.llm.llm import _get_qwen_params


class TestQwenProvider(unittest.TestCase):
    def setUp(self):
        self.api_key = os.environ.get("QWEN_API_KEY")

    @unittest.skipUnless(os.environ.get("QWEN_API_KEY"), "QWEN_API_KEY not set")
    def test_qwen35(self):
        llm = ChatOpenAICompatible(
            api_key=self.api_key, model="qwen3.5-plus", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        result = llm.invoke("hello")
        print(result)


class TestQwenParamsFunction(unittest.TestCase):
    """Unit tests for Qwen provider parameter assembly."""

    _qwen_params_fn = staticmethod(_get_qwen_params)

    def test_uses_frontend_configured_base_url(self):
        result = self._qwen_params_fn(
            {"model": "qwen-plus"},
            {
                "openai_api_key": "key",
                "openai_api_base": "https://proxy.example.com/compatible-mode/v1/",
            },
            {},
        )
        self.assertEqual(result["base_url"], "https://proxy.example.com/compatible-mode/v1")

    def test_falls_back_to_dashscope_default(self):
        result = self._qwen_params_fn({"model": "qwen-plus"}, {"openai_api_key": "key"}, {})
        self.assertEqual(result["base_url"], "https://dashscope.aliyuncs.com/compatible-mode/v1")

    def test_preserves_qwen_extra_body_flags(self):
        result = self._qwen_params_fn(
            {"model": "qwen-plus", "streaming": True, "model_kwargs": {"enable_thinking": True}},
            {"openai_api_key": "key"},
            {"enable_web_search": True},
        )
        self.assertTrue(result["extra_body"]["enable_search"])
        self.assertTrue(result["extra_body"]["incremental_output"])
        self.assertTrue(result["extra_body"]["enable_thinking"])
