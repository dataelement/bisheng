import unittest

from langchain_core.messages import AIMessageChunk, HumanMessage

from bisheng.core.ai.llm.chat_openai_compatible import ChatOpenAICompatible
from bisheng.core.ai.llm.chat_openai_reasoning import ChatOpenAIReasoning


class TestChatOpenAIReasoning(unittest.TestCase):
    def test_openai_compatible_only_keeps_max_tokens_compat(self):
        llm = ChatOpenAICompatible(api_key="test", model="test-model")

        payload = llm._get_request_payload(
            [HumanMessage(content="question")],
            max_completion_tokens=123,
        )

        self.assertEqual(payload.get("max_tokens"), 123)
        self.assertNotIn("max_completion_tokens", payload)

    def test_create_chat_result_keeps_reasoning_content(self):
        llm = ChatOpenAIReasoning(api_key="test", model="test-model")

        result = llm._create_chat_result(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning": "result reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": "test-model",
            }
        )

        self.assertEqual(
            result.generations[0].message.additional_kwargs.get("reasoning_content"),
            "result reasoning",
        )

    def test_create_chat_result_prefers_reasoning_content(self):
        llm = ChatOpenAIReasoning(api_key="test", model="test-model")

        result = llm._create_chat_result(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning": "fallback reasoning",
                            "reasoning_content": "preferred reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": "test-model",
            }
        )

        self.assertEqual(
            result.generations[0].message.additional_kwargs.get("reasoning_content"),
            "preferred reasoning",
        )

    def test_convert_chunk_to_generation_chunk_keeps_reasoning_content(self):
        llm = ChatOpenAIReasoning(api_key="test", model="test-model")

        chunk = llm._convert_chunk_to_generation_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "partial answer",
                            "reasoning_content": "stream reasoning",
                        },
                        "finish_reason": None,
                    }
                ]
            },
            AIMessageChunk,
            {},
        )

        self.assertIsNotNone(chunk)
        self.assertEqual(
            chunk.message.additional_kwargs.get("reasoning_content"),
            "stream reasoning",
        )

    def test_convert_chunk_to_generation_chunk_falls_back_to_reasoning(self):
        llm = ChatOpenAIReasoning(api_key="test", model="test-model")

        chunk = llm._convert_chunk_to_generation_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "partial answer",
                            "reasoning": "fallback stream reasoning",
                        },
                        "finish_reason": None,
                    }
                ]
            },
            AIMessageChunk,
            {},
        )

        self.assertIsNotNone(chunk)
        self.assertEqual(
            chunk.message.additional_kwargs.get("reasoning_content"),
            "fallback stream reasoning",
        )


if __name__ == "__main__":
    unittest.main()
