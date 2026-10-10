"""Use the robot's assistant executor without its transport or persistence."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.domain.schemas.execution import AssistantEntryPoint, AssistantExecutionContext
from bisheng.eplus.domain.schemas.debug import DebugContext, DebugRunRequest
from bisheng.eplus.infrastructure.debug_trace import DebugTrace, is_robot_knowledge_tool, observe_robot_tool


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class DebugAssistantRuntime:
    def __init__(self, agent_factory=AssistantAgent):
        self.agent_factory = agent_factory

    async def run(self, context: DebugContext, request: DebugRunRequest, trace: DebugTrace) -> AsyncIterator[str]:
        if os.getenv("BISHENG_RECORD_HISTORY"):
            raise RuntimeError("robot debug refuses local history recording")
        task = asyncio.current_task()
        execution_context = AssistantExecutionContext(
            entry_point=AssistantEntryPoint.EPLUS,
            user_id=context.test_user_id,
            external_user_id=context.external_user_id,
            content=request.query,
            robot_scope=context.robot_scope,
            cancellation_check=lambda: task is not None and bool(task.cancelling()),
        )
        agent = self.agent_factory(context.assistant, f"eplus-debug-{uuid.uuid4().hex}", context.test_user_id)
        agent.execution_context = execution_context
        await agent.init_llm()
        await agent.init_tools(context=execution_context)
        formal_tools = tuple(agent.tools)
        agent.tools = [observe_robot_tool(t, trace) for t in formal_tools if is_robot_knowledge_tool(t)]
        if not agent.tools:
            raise RuntimeError("robot-bound knowledge tool unavailable")
        await agent.init_agent()
        trace.emit(
            "context",
            {
                **context.public_view(),
                "execution_mode": agent.current_agent_executor,
                "model_name": getattr(agent.llm, "model_name", type(agent.llm).__name__),
                "test_tools": [t.name for t in agent.tools],
                "disabled_tools": [t.name for t in formal_tools if not is_robot_knowledge_tool(t)],
            },
        )
        history = []
        for turn in request.history:
            history.extend((HumanMessage(content=turn.question), AIMessage(content=turn.answer)))
        async for messages in agent.astream("", history, context=execution_context):
            message = messages[-1] if isinstance(messages, list) and messages else messages
            if isinstance(message, (AIMessage, AIMessageChunk)):
                text = text_content(message.content)
                if text:
                    yield text
