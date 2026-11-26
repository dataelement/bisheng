"""The deferred-workspace wrapper must work on the tool shape production builds.

Production hands the interpreter to the agent as ``ToolExecutor(tool_instance=<tool>)``.
``ToolExecutor`` forwards attribute reads to the inner tool but is a pydantic model
without an ``executor`` field, so assigning ``tool.executor`` on it raises. The first
real direct run on a deployed box failed on exactly that (114, 2026-11-18).
"""

from typing import Any

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from bisheng.linsight.domain.services.tool_assembly import (
    CODE_INTERPRETER_TOOL_KEY,
    _DeferredWorkspaceExecutor,
    defer_workspace_preparation,
)
from bisheng.tool.domain.services.executor import ToolExecutor


class _Args(BaseModel):
    python_code: str


class _Executor:
    def __init__(self) -> None:
        self.ran: list[str] = []

    async def arun(self, code: str) -> dict:
        self.ran.append(code)
        return {"exitcode": 0}


class _Interpreter(BaseTool):
    name: str = CODE_INTERPRETER_TOOL_KEY
    description: str = "run code"
    args_schema: type[BaseModel] = _Args
    executor: Any = None

    def _run(self, python_code: str) -> dict:
        raise AssertionError("sync call")

    async def _arun(self, python_code: str) -> dict:
        return await self.executor.arun(python_code)


def _platform_tool(inner: BaseTool) -> ToolExecutor:
    app_type = next(iter(ToolExecutor.model_fields["app_type"].annotation))
    return ToolExecutor(
        app_id="a",
        app_name="a",
        app_type=app_type,
        user_id=1,
        tool_id=1,
        tool_is_preset=1,
        tool_name=inner.name,
        name=inner.name,
        description=inner.description,
        args_schema=inner.args_schema,
        tool_instance=inner,
    )


async def test_wraps_the_executor_behind_a_platform_tool():
    executor = _Executor()
    inner = _Interpreter(executor=executor)
    tool = _platform_tool(inner)
    prepared: list[int] = []

    async def prepare() -> None:
        prepared.append(1)

    assert defer_workspace_preparation([tool], prepare) == 1
    assert isinstance(inner.executor, _DeferredWorkspaceExecutor)
    # Reads through the platform wrapper see the same deferred executor.
    assert tool.executor is inner.executor
    assert prepared == []

    await inner.executor.arun("print(1)")
    assert prepared == [1] and executor.ran == ["print(1)"]
    # Wrapping twice is a no-op.
    assert defer_workspace_preparation([tool], prepare) == 0


async def test_unknown_shape_fails_loudly():
    class _Opaque(BaseTool):
        name: str = CODE_INTERPRETER_TOOL_KEY
        description: str = "x"

        def _run(self) -> None:
            return None

        def __getattr__(self, item: str) -> Any:
            if item == "executor":
                return _Executor()
            raise AttributeError(item)

    async def prepare() -> None:
        return None

    with pytest.raises(TypeError):
        defer_workspace_preparation([_Opaque()], prepare)
