import os
import unittest

from bisheng.core.ai import ChatOpenAICompatible


class TestQwenProvider(unittest.TestCase):
    def setUp(self):
        self.api_key = os.environ.get("QWEN_API_KEY")

    def test_qwen35(self):
        llm = ChatOpenAICompatible(api_key=self.api_key, model="qwen3.5-plus",
                                   base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        result = llm.invoke("hello")
        print(result)
