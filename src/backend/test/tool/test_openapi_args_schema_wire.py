"""Custom API tools send a standard argument schema to the model.

Before the fix, parse_args_schema() wrote every argument at the top level of the dict
and left "properties" empty. Function calling sent
``{"type": "object", "properties": {}, "required": ["query"], "query": {...}}`` and the
ReAct prompt rendered ``args: {}``. These tests build the tool the way ToolExecutor
does, capture the real HTTP body that ChatOpenAI sends (httpx.MockTransport, no
network, fake key), and check the tool still sends the same upstream request.
"""

import json
from unittest.mock import AsyncMock

import httpx
from langchain_core.tools import render_text_description_and_args
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.tool.domain.services.openapi import OpenApiSchema

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "demo", "description": "demo"},
    "servers": [{"url": "https://fixture.example"}],
    "paths": {
        "/search": {
            "post": {
                "operationId": "search_docs",
                "summary": "Search documents",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {
                                    "query": {"type": "string", "description": "search keywords"},
                                    "count": {"type": "integer", "nullable": True, "description": "max results"},
                                    "tags": {"type": "array", "items": {"type": "string"}, "description": "tags"},
                                    "filter": {
                                        "type": "object",
                                        "description": "filter",
                                        "properties": {
                                            "lang": {"type": "string", "description": "language"},
                                            "years": {"type": "array", "items": {"type": "integer"}},
                                        },
                                    },
                                },
                            }
                        }
                    }
                },
            }
        }
    },
}

EXPECTED_PARAMETERS = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "description": "search keywords"},
        "count": {"type": ["integer", "null"], "description": "max results"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "tags"},
        "filter": {
            "type": "object",
            "description": "filter",
            "properties": {
                "lang": {"type": "string", "description": "language"},
                "years": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
}


def build_tool(async_client=None):
    """Saved tool -> ToolExecutor._init_by_tool_and_type, the path every model entry uses."""
    schema = OpenApiSchema(SPEC)
    schema.parse_server()
    api = schema.parse_paths()[0]
    tool = GptsTools(
        id=1,
        name="search_docs",
        tool_key="tool_type_1_search_docs",
        desc="Search documents",
        extra=json.dumps(api),
        is_preset=0,
        type=1,
    )
    tool_type = GptsToolsType(id=1, name="demo", server_host="https://fixture.example", auth_method=0, extra="{}")
    kwargs = {}
    if async_client is not None:

        def factory(name, **params):
            from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools

            return OpenApiTools.get_api_tool(name, async_client=async_client, **params)

        kwargs["api_tool_factory"] = factory
    return ToolExecutor._init_by_tool_and_type(
        tool=tool,
        tool_type=tool_type,
        app_id="app",
        app_name="app",
        app_type=ApplicationTypeEnum.ASSISTANT,
        user_id=1,
        **kwargs,
    )


# A final answer that both the function-calling agents and the ReAct output parser accept.
FINAL_ANSWER = '```json\n{"action": "Final Answer", "action_input": "ok"}\n```'


def mock_llm(captured):
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": FINAL_ANSWER},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return ChatOpenAI(
        model="m",
        api_key="sk-fake",
        base_url="http://mock.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_function_parameters_are_standard_json_schema():
    parameters = convert_to_openai_tool(build_tool())["function"]["parameters"]
    assert parameters == EXPECTED_PARAMETERS


def test_function_calling_request_body_carries_the_arguments():
    # BishengLLM.bind_tools converts with convert_to_openai_tool and binds the result.
    captured = []
    tool = build_tool()
    mock_llm(captured).bind(tools=[convert_to_openai_tool(tool)]).invoke("hi")
    assert captured[-1]["tools"][0]["function"]["parameters"] == EXPECTED_PARAMETERS

    # The assistant FC mode and the workflow agent node use langgraph create_react_agent.
    from langgraph.prebuilt import create_react_agent

    create_react_agent(mock_llm(captured), [tool]).invoke({"messages": [("user", "hi")]})
    assert captured[-1]["tools"][0]["function"]["parameters"] == EXPECTED_PARAMETERS


def test_react_prompt_lists_the_arguments():
    tool = build_tool()
    assert set(tool.args) == {"query", "count", "tags", "filter"}
    rendered = render_text_description_and_args([tool])
    assert "args: {}" not in rendered
    assert "args: {'query': {" in rendered
    assert "'description': 'search keywords'" in rendered

    # The assistant ReAct mode: the system prompt sent to the model lists the arguments.
    from bisheng_langchain.gpts.agent_types.llm_react_agent import get_react_agent_executor

    captured = []
    executor = get_react_agent_executor([tool], mock_llm(captured), "system", False)
    executor.invoke({"input": "hi", "chat_history": []})
    system_prompt = captured[-1]["messages"][0]["content"]
    assert "search keywords" in system_prompt
    assert "max results" in system_prompt


async def test_model_arguments_reach_the_upstream_unchanged():
    client = AsyncMock()
    client.apost.return_value = "ok"
    tool = build_tool(async_client=client)
    args = {"query": "bisheng", "count": "3", "tags": ["a"], "filter": {"lang": "zh", "years": [2025]}}
    await tool.tool_instance.ainvoke(args)
    call = client.apost.await_args
    assert call.args == ("https://fixture.example/search",)
    assert call.kwargs["params"] == {}
    assert call.kwargs["json"] == {
        "query": "bisheng",
        "count": 3,
        "tags": ["a"],
        "filter": {"lang": "zh", "years": [2025]},
    }

    await tool.tool_instance.ainvoke({"query": "bisheng", "count": None, "tags": ""})
    # null is allowed for a nullable field; a blank optional array is not sent.
    assert client.apost.await_args.kwargs["json"] == {"query": "bisheng", "count": None}
