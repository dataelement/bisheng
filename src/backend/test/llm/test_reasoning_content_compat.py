import unittest

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, LLMResult

from bisheng.llm.domain.utils import extract_reasoning_content, normalize_reasoning_content
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler


class _DummyCallback(BaseCallback):
    pass


class TestReasoningContentCompat(unittest.TestCase):
    def test_extract_prefers_reasoning_content_over_reasoning(self):
        message = AIMessageChunk(
            content="hello",
            additional_kwargs={
                "reasoning": "fallback reasoning",
                "reasoning_content": "preferred reasoning",
            },
        )

        self.assertEqual(extract_reasoning_content(message), "preferred reasoning")

    def test_extract_falls_back_to_reasoning(self):
        message = AIMessageChunk(
            content="hello",
            additional_kwargs={"reasoning": "fallback reasoning"},
        )

        self.assertEqual(extract_reasoning_content(message), "fallback reasoning")

    def test_normalize_chat_generation_chunk_sets_reasoning_content(self):
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="hello",
                additional_kwargs={"reasoning": "chunk reasoning"},
            )
        )

        normalize_reasoning_content(chunk)

        self.assertEqual(
            chunk.message.additional_kwargs.get("reasoning_content"),
            "chunk reasoning",
        )

    def test_normalize_llm_result_sets_reasoning_content(self):
        result = LLMResult(
            generations=[[
                ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="hello",
                        response_metadata={"reasoning": "result reasoning"},
                    )
                )
            ]]
        )

        normalize_reasoning_content(result)

        self.assertEqual(
            result.generations[0][0].message.additional_kwargs.get("reasoning_content"),
            "result reasoning",
        )

    def test_llm_callback_uses_reasoning_fallback(self):
        callback = LLMNodeCallbackHandler(
            callback=_DummyCallback(),
            unique_id="u1",
            node_id="n1",
            node_name="node",
            output=True,
            output_key="output",
        )
        response = LLMResult(
            generations=[[
                ChatGeneration(
                    message=AIMessage(
                        content="answer",
                        additional_kwargs={"reasoning": "callback reasoning"},
                    )
                )
            ]]
        )

        callback.on_llm_end(response)

        self.assertEqual(callback.reasoning_content, "callback reasoning")


if __name__ == "__main__":
    unittest.main()
