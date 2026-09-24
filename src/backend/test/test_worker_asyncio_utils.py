"""已完成的业务超时必须传回调用方, 不能当作轮询超时空转。"""

import concurrent.futures
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "worker_asyncio_under_test", Path(__file__).parents[1] / "bisheng/worker/_asyncio_utils.py"
)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def test_completed_timeout_is_propagated_without_polling_forever(monkeypatch):
    future = concurrent.futures.Future()
    error = concurrent.futures.TimeoutError("upstream timed out")
    future.set_exception(error)
    monkeypatch.setattr(subject.concurrent.futures, "Future", lambda: future)
    monkeypatch.setattr(subject, "get_worker_loop", lambda: SimpleNamespace(call_soon_threadsafe=lambda _: None))
    # 限定故障复现的循环次数, 避免旧实现挂住测试进程。
    monkeypatch.setattr(subject, "_die_if_loop_dead", Mock(side_effect=[None, AssertionError("busy polling")]))
    with pytest.raises(concurrent.futures.TimeoutError) as caught:
        subject.run_async_task(lambda: None)
    assert caught.value is error
