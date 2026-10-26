"""Check that a long web_fetch result is written to /large_tool_results/.

Does not call a model, the sandbox, or the live 网页读取 API. The release
model's context window is unknown, so the budget middleware is not mounted and
the live line is FilesystemMiddleware's default: 20000 tokens, 4 characters
each. 网页读取 truncates to max_chars (default 20000) before that line, so
this script feeds a longer result through the same writer.

Run from src/backend:

    uv run python test/sandbox/release/check_large_tool_results.py
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from deepagents.middleware.filesystem import NUM_CHARS_PER_TOKEN, FilesystemMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

_PARSE = Path(__file__).with_name("parse.py")
_spec = importlib.util.spec_from_file_location("release_parse", _PARSE)
_parse = importlib.util.module_from_spec(_spec)
sys.modules["release_parse"] = _parse
_spec.loader.exec_module(_parse)
offload_from_text = _parse.offload_from_text

_PAGES: dict[str, str] = {}


@tool
def web_fetch(url: str) -> str:
    """Read one page and return its body."""
    return _PAGES[url]


class _Scripted(BaseChatModel):
    replies: list = []

    @property
    def _llm_type(self) -> str:
        return "large-tool-result-check"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(message, SystemMessage) for message in messages):
            raise RuntimeError("scripted model saw no system message")
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def _char_limit() -> int:
    default_tokens = (
        inspect.signature(FilesystemMiddleware.__init__).parameters["tool_token_limit_before_evict"].default
    )
    return int(default_tokens) * NUM_CHARS_PER_TOKEN


def _long_page(limit_chars: int) -> str:
    """A multi-line page one step past the framework's character line."""
    first = "PAGE-FIRST"
    last = "PAGE-LAST"
    line = "x" * 80
    lines = [first]
    while sum(len(item) + 1 for item in lines) + len(last) <= limit_chars:
        lines.append(line)
    lines.append(last)
    return "\n".join(lines)


def _run(url: str, call_id: str) -> dict:
    model = _Scripted(
        replies=[
            AIMessage("", tool_calls=[{"name": "web_fetch", "args": {"url": url}, "id": call_id}]),
            AIMessage("done"),
        ]
    )
    agent = create_deep_agent(
        model=model,
        tools=[web_fetch],
        state_schema=DeepAgentState,
        backend=StateBackend(),
        checkpointer=InMemorySaver(),
    )
    return agent.invoke(
        {"messages": [{"role": "user", "content": "read the page"}]},
        {"configurable": {"thread_id": call_id}},
    )


def _tool_message(result: dict, call_id: str) -> ToolMessage:
    return next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == call_id
    )


def _stored_text(entry) -> str:
    if isinstance(entry, str):
        return entry
    content = entry.get("content") if isinstance(entry, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(line) for line in content)
    raise RuntimeError(f"unrecognized stored file: {type(entry).__name__}")


def _check_long(limit_chars: int) -> None:
    body = _long_page(limit_chars)
    _PAGES["long"] = body
    result = _run("long", "call-long")
    message = _tool_message(result, "call-long")
    text = message.content if isinstance(message.content, str) else str(message.content)
    notice = offload_from_text(text)
    if notice is None:
        raise SystemExit(f"长结果没有转到 large_tool_results，正文 {len(body)} 字符，门槛 {limit_chars}")
    path = "/" + notice["path"]
    files = result.get("files") or {}
    if path not in files:
        raise SystemExit(f"预览指向 {path}，状态里没有这个文件")
    stored = _stored_text(files[path])
    stored_lines = stored.splitlines()
    original_lines = body.splitlines()
    if stored != body:
        raise SystemExit(
            f"转存文件与原文不一致：文件 {len(stored)} 字符、{len(stored_lines)} 行，"
            f"原文 {len(body)} 字符、{len(original_lines)} 行"
        )
    if notice["count"] != len(original_lines):
        raise SystemExit(f"预览行数 {notice['count']}，原文 {len(original_lines)} 行")
    if notice["first"] != original_lines[0] or notice["last"] != original_lines[-1]:
        raise SystemExit(f"预览首末行是 {notice['first']!r} / {notice['last']!r}")
    print(f"长结果已转存：{len(body)} 字符、{len(original_lines)} 行，门槛 {limit_chars} 字符，路径 {notice['path']}")


def _check_short() -> None:
    _PAGES["short"] = "短正文"
    result = _run("short", "call-short")
    message = _tool_message(result, "call-short")
    text = message.content if isinstance(message.content, str) else str(message.content)
    if text != "短正文":
        raise SystemExit(f"短结果被改写了：{text[:200]!r}")
    files = result.get("files") or {}
    if any(str(path).startswith("/large_tool_results/") for path in files):
        raise SystemExit("短结果也被写进了 large_tool_results")
    print("短结果留在工具消息里")


def main() -> None:
    limit_chars = _char_limit()
    _check_long(limit_chars)
    _check_short()


if __name__ == "__main__":
    main()
