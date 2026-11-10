"""Content-block extraction preserves channel boundaries and raw model messages."""

from copy import deepcopy

import pytest
from langchain_core.messages import AIMessageChunk

from bisheng.common.utils.message_content import extract_message_reasoning, extract_message_text


@pytest.mark.parametrize(
    "content, additional_kwargs, expected",
    [
        ("Answer", {"reasoning_content": "Thought"}, ("Answer", "Thought")),
        (["Hello", {"type": "text", "text": " world"}], {}, ("Hello world", "")),
        ([{"type": "output_text", "text": "Answer"}], {}, ("Answer", "")),
        (
            [
                {"type": "reasoning", "reasoning": "First thought"},
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "; next thought"}]},
                {"type": "text", "text": "Answer"},
            ],
            {},
            ("Answer", "First thought; next thought"),
        ),
        (
            [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Thought"}]},
                {"type": "text", "text": "Answer"},
            ],
            {"reasoning_content": "Thought"},
            ("Answer", "Thought"),
        ),
        (
            [
                {"type": "reasoning", "encrypted_content": "opaque data", "summary": []},
                {"type": "function_call", "arguments": "tool input", "text": "not an answer"},
                {"type": "image", "text": "not an answer"},
                {"type": "text", "text": None},
            ],
            {},
            ("", ""),
        ),
        ([], {}, ("", "")),
    ],
)
def test_extracts_only_visible_text_and_reasoning(content, additional_kwargs, expected):
    message = AIMessageChunk(content=content, additional_kwargs=additional_kwargs)
    original = deepcopy(message)

    assert (extract_message_text(message), extract_message_reasoning(message)) == expected
    assert message == original
