import logging
import os
import unittest

from langchain_core.messages import HumanMessage, AIMessage

from bisheng.core.ai import ChatVoiceEngine

logging.basicConfig(level=logging.DEBUG)


class TestVoiceEngineProvider(unittest.TestCase):
    def setUp(self):
        self.api_key = os.environ.get("ARK_API_KEY")
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"

    def test_websearch(self):
        llm = ChatVoiceEngine(api_key=self.api_key,
                              base_url=self.base_url,
                              model="doubao-seed-2-0-pro-260215",
                              model_kwargs={
                                  "tools": [
                                      {
                                          "type": "web_search"
                                      }
                                  ]
                              },
                              )
        result = llm.invoke([
            HumanMessage("北京今天天气怎么样"),
            AIMessage("暂未找到相关信息"),
            HumanMessage("天津今天天气怎么样")
        ])
        print(result)


class TestVoiceEnginePayloadCompat(unittest.TestCase):
    def setUp(self):
        self.llm = ChatVoiceEngine(
            api_key="test-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model="doubao-test-model",
        )

    def test_add_status_for_assistant_history_when_web_search_enabled(self):
        payload = self.llm._get_request_payload(
            [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
            ],
            tools=[{"type": "web_search"}],
        )
        assistant_messages = [msg for msg in payload["messages"] if msg.get("role") == "assistant"]
        self.assertEqual(len(assistant_messages), 1)
        self.assertEqual(assistant_messages[0].get("status"), "completed")

    def test_keep_existing_status_when_web_search_enabled(self):
        payload = self.llm._get_request_payload(
            [
                {"role": "assistant", "content": "B", "status": "in_progress"},
            ],
            tools=[{"type": "web_search"}],
        )
        self.assertEqual(payload["messages"][0].get("status"), "in_progress")

    def test_do_not_add_status_when_web_search_disabled(self):
        payload = self.llm._get_request_payload(
            [
                {"role": "assistant", "content": "B"},
            ],
            tools=[{"type": "function", "function": {"name": "tool_x"}}],
        )
        self.assertNotIn("status", payload["messages"][0])
