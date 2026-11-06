"""In-place refresh of an assistant's open container executor (F086)."""

from __future__ import annotations

import inspect

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.core.config.settings import SandboxConf
from bisheng.workstation.domain.services.chat_service import _prepare_tools
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.factory import refresh_open_code_executors
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


class _Tool:
    def __init__(self, name: str, executor):
        self.name = name
        self.executor = executor


def _container(**kwargs) -> ContainerExecutor:
    return ContainerExecutor(minio={}, sandbox_conf=SandboxConf(endpoints=["http://old:8080"], token="old"), **kwargs)


def _patch(monkeypatch, conf: SandboxConf) -> None:
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.load_sandbox_conf",
        lambda: conf,
    )


def test_open_lease_is_released_then_updated_in_place(monkeypatch):
    _patch(monkeypatch, SandboxConf(endpoints=["http://new:8080/"], token="new-token"))
    executor = _container()
    executor._bound_url = "http://old:8080"
    executor._session_id = "sid"
    executor._lease_token = "lease"
    order = []

    def release():
        order.append(list(executor.endpoints))
        executor._forget_lease()

    executor._release = release
    tool = _Tool("bisheng_code_interpreter", executor)
    identity = id(executor)
    refresh_open_code_executors([tool])
    assert order == [["http://old:8080"]]
    assert executor._bound_url is None
    assert executor._session_id is None
    assert executor._lease_token is None
    assert executor.endpoints == ["http://new:8080"]
    assert executor.token == "new-token"
    assert id(tool.executor) == identity


def test_keep_session_is_left_alone(monkeypatch):
    _patch(monkeypatch, SandboxConf(endpoints=["http://new:8080"], token="new-token"))
    executor = _container(keep_session=True)
    executor._bound_url = "http://old:8080"
    executor._session_id = "sid"

    def release():
        raise AssertionError("sticky session must not be released")

    executor._release = release
    refresh_open_code_executors([_Tool("bisheng_code_interpreter", executor)])
    assert executor.endpoints == ["http://old:8080"]
    assert executor.token == "old"
    assert executor._session_id == "sid"


def test_shared_executor_updates_both_copies(monkeypatch):
    _patch(monkeypatch, SandboxConf(endpoints=["http://new:8080"], token="new-token"))
    executor = _container()
    first = _Tool("bisheng_code_interpreter", executor)
    second = _Tool("bisheng_code_interpreter", executor)
    refresh_open_code_executors([first, second])
    assert first.executor is second.executor
    assert first.executor.endpoints == ["http://new:8080"]
    assert second.executor.token == "new-token"


def test_local_and_other_names_are_skipped(monkeypatch):
    _patch(monkeypatch, SandboxConf(endpoints=["http://new:8080"], token="new-token"))
    local = LocalExecutor()
    local.endpoints = ["http://local"]
    other = _container()
    refresh_open_code_executors(
        [
            _Tool("bisheng_code_interpreter", local),
            _Tool("other_tool", other),
        ]
    )
    assert local.endpoints == ["http://local"]
    assert other.endpoints == ["http://old:8080"]
    assert other.token == "old"


def test_run_refreshes_before_the_model():
    source = inspect.getsource(AssistantAgent.run)
    refresh_at = source.index("refresh_open_code_executors(self.tools)")
    model_at = min(index for index in (source.find("react_run"), source.find("ainvoke")) if index != -1)
    assert refresh_at < model_at


def test_daily_chat_does_not_refresh():
    assert "refresh_open_code_executors" not in inspect.getsource(_prepare_tools)
