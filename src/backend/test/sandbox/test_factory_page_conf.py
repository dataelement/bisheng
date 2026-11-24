"""Container executors read the page sandbox config (F086)."""

from __future__ import annotations

import pytest

from bisheng.common.errcode.sandbox import SandboxUnreachableError
from bisheng.core.config.settings import SandboxConf
from bisheng_langchain.gpts.tools.code_interpreter.factory import build_code_executor


def _patch_page(monkeypatch: pytest.MonkeyPatch, conf: SandboxConf):
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.load_sandbox_conf",
        lambda: conf,
    )


def test_container_uses_page_conf_not_deployment(monkeypatch: pytest.MonkeyPatch):
    page = SandboxConf(endpoints=["http://page:8080"], token="page-token")
    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return page

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.load_sandbox_conf",
        fake,
    )
    executor = build_code_executor(
        "container",
        endpoints=["http://caller:8080"],
        token="caller-token",
        discover_host_pattern="code-runner-{n}",
    )
    assert executor.endpoints == ["http://page:8080"]
    assert executor.token == "page-token"
    assert calls["n"] == 1


def test_built_executor_keeps_its_snapshot(monkeypatch: pytest.MonkeyPatch):
    holder = {"conf": SandboxConf(endpoints=["http://a:8080"], token="t1")}
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.load_sandbox_conf",
        lambda: holder["conf"],
    )
    executor = build_code_executor("container")
    holder["conf"] = SandboxConf(endpoints=["http://b:8080"], token="t2")
    assert executor.endpoints == ["http://a:8080"]
    assert executor.token == "t1"


def test_empty_page_endpoints_are_unreachable(monkeypatch: pytest.MonkeyPatch):
    _patch_page(monkeypatch, SandboxConf(endpoints=[], token=""))
    executor = build_code_executor("container")
    with pytest.raises(SandboxUnreachableError):
        executor._ensure_lease()


def test_local_and_e2b_do_not_read_sandbox_conf(monkeypatch: pytest.MonkeyPatch):
    def boom():
        raise AssertionError("sandbox conf should not be read")

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.load_sandbox_conf",
        boom,
    )
    build_code_executor("local")
    build_code_executor("e2b", minio={}, api_key="k")
