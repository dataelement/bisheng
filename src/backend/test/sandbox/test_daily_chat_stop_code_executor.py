"""Daily chat: a torn-down turn stops its sandbox run (F068 D7, contract C4)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from bisheng.workstation.domain.services import chat_service
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


class _RecordingContainer(ContainerExecutor):
    def __init__(self):
        super().__init__(minio={}, endpoints=["http://runner-a:8080"], token="t")
        self.closed = threading.Event()
        self.close_thread: str | None = None

    def close(self) -> None:
        self.close_thread = threading.current_thread().name
        self.closed.set()


def test_interrupted_turn_closes_container_executors_off_the_loop_thread():
    container = _RecordingContainer()
    wrapped = SimpleNamespace(name="wrapper", tool_instance=SimpleNamespace(executor=container))
    local = LocalExecutor(minio={})
    local_closed = []
    local.close = lambda: local_closed.append(True)
    tools = [wrapped, SimpleNamespace(name="local", executor=local), SimpleNamespace(name="web_search")]

    chat_service._stop_code_executors(tools)

    assert container.closed.wait(5)
    assert container.close_thread == "code-executor-stop"
    assert container.close_thread != threading.current_thread().name
    assert local_closed == []


def test_close_failure_is_logged_not_raised():
    class _Boom:
        def close(self):
            raise RuntimeError("runner gone")

    # Runs inline here; on the cancel path it runs on the daemon thread.
    chat_service._close_quietly(_Boom())
