from langchain_core.messages import HumanMessage

from bisheng.core.ai.llm.chat_qwen import ChatQwen


def test_qwen_payload_converts_standard_base64_image_block_to_image_url():
    llm = ChatQwen(
        model="qwen-vl-max",
        openai_api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    payload = llm._get_request_payload(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": "describe this image"},
                    {
                        "type": "image",
                        "source_type": "base64",
                        "mime_type": "image/png",
                        "data": "abc123",
                    },
                ]
            )
        ]
    )

    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "describe this image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
    ]


def test_qwen_payload_converts_standard_url_image_block_to_image_url():
    llm = ChatQwen(
        model="qwen-vl-max",
        openai_api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    payload = llm._get_request_payload(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": "describe this image"},
                    {
                        "type": "image",
                        "source_type": "url",
                        "url": "https://example.com/a.png",
                    },
                ]
            )
        ]
    )

    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "describe this image"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
    ]
