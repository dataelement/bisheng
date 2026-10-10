"""Request-local observation of the production citation wrapper."""

import asyncio
import json
import threading
import uuid
from contextvars import ContextVar
from typing import Any

from pydantic import Field, PrivateAttr

from bisheng.api.services.assistant_agent import AssistantCitationToolWrapper


class DebugTrace:
    def __init__(self, max_bytes: int = 2 * 1024 * 1024):
        self.run_id = uuid.uuid4().hex
        self.events: list[dict] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.max_bytes = max_bytes
        self._bytes = 0
        self._lock = threading.Lock()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def emit(self, event_type: str, data: dict, *, terminal: bool = False) -> dict:
        with self._lock:
            event = {"run_id": self.run_id, "seq": len(self.events) + 1, "type": event_type, "data": data}
            size = len(json.dumps(event, ensure_ascii=False).encode())
            if self._bytes + size > self.max_bytes and not terminal:
                raise ValueError("debug trace capacity exceeded")
            self._bytes += size
            self.events.append(event)
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self.queue.put_nowait, event)
            else:
                self.queue.put_nowait(event)
            return event

    @property
    def tool_call_count(self) -> int:
        return sum(e["type"] == "tool_start" for e in self.events)


class ObservedRobotTool(AssistantCitationToolWrapper):
    trace: Any = Field(exclude=True)
    original_tool_type: str
    _call: ContextVar = PrivateAttr(default_factory=lambda: ContextVar("debug_tool_call"))

    def _capture_metadata(self, documents):
        call = self._call.get(None)
        if call is not None:
            keys = ("knowledge_id", "kb_id", "document_id", "document_name", "file_name", "chunk_index", "access_scope")
            call["retrieval_metadata"] = [
                {
                    k: d.metadata[k]
                    for k in keys
                    if k in d.metadata and isinstance(d.metadata[k], (str, int, float, bool, type(None)))
                }
                for d in documents
            ]

    async def _aformat_knowledge_results(self, retrieval_result):
        documents = list(retrieval_result or [])
        self._capture_metadata(documents)
        return await super()._aformat_knowledge_results(documents)

    def _format_knowledge_results(self, retrieval_result):
        documents = list(retrieval_result or [])
        self._capture_metadata(documents)
        return super()._format_knowledge_results(documents)

    def _begin(self, query):
        call = {
            "call_id": uuid.uuid4().hex,
            "tool_name": self.name,
            "tool_type": self.original_tool_type,
            "observer_type": f"{type(self).__module__}.{type(self).__name__}",
            "query": query,
        }
        self.trace.emit("tool_start", dict(call))
        return call, self._call.set(call)

    async def _arun(self, query: str, **kwargs):
        call, token = self._begin(query)
        try:
            result = await super()._arun(query, **kwargs)
            self.trace.emit("tool_end", {**call, "model_tool_output": result})
            return result
        except Exception as exc:
            self.trace.emit("tool_error", {"call_id": call["call_id"], "error_type": type(exc).__name__}, terminal=True)
            # ReAct turns tool exceptions into model observations. Never expose provider bodies.
            raise RuntimeError(f"robot knowledge tool failed ({type(exc).__name__})") from None
        finally:
            self._call.reset(token)

    def _run(self, query: str, **kwargs):
        call, token = self._begin(query)
        try:
            result = super()._run(query, **kwargs)
            self.trace.emit("tool_end", {**call, "model_tool_output": result})
            return result
        except Exception as exc:
            self.trace.emit("tool_error", {"call_id": call["call_id"], "error_type": type(exc).__name__}, terminal=True)
            raise RuntimeError(f"robot knowledge tool failed ({type(exc).__name__})") from None
        finally:
            self._call.reset(token)


def is_robot_knowledge_tool(tool) -> bool:
    return isinstance(tool, AssistantCitationToolWrapper) and bool(getattr(tool.tool, "robot_scope_enforced", False))


def observe_robot_tool(tool, trace: DebugTrace):
    if not is_robot_knowledge_tool(tool):
        raise ValueError("only robot-bound knowledge tools can be observed")
    return ObservedRobotTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        tool=tool.tool,
        kb_name_by_id=dict(tool.kb_name_by_id),
        citation_collector=tool.citation_collector,
        trace=trace,
        original_tool_type=f"{type(tool).__module__}.{type(tool).__name__}",
    )
