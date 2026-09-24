"""load_tools code-interpreter dispatch (F068 T017). No live runner / E2B session."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bisheng.core.config.settings import SandboxConf
from bisheng_langchain.gpts.load_tools import _get_native_code_interpreter
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

_BACKEND = Path(__file__).resolve().parents[2]
_FIVE_PATHS = (
    _BACKEND / "bisheng/linsight/domain/services/workbench_impl.py",
    _BACKEND / "bisheng/workstation/domain/services/chat_service.py",
    _BACKEND / "bisheng/api/services/assistant_agent.py",
    _BACKEND / "bisheng/workflow/nodes/agent/agent.py",
    _BACKEND / "bisheng/workflow/nodes/tool/tool.py",
)


def test_type_local_builds_local_executor():
    tool = _get_native_code_interpreter(minio={}, type="local")
    assert isinstance(tool.executor, LocalExecutor)


def test_type_container_builds_container_executor():
    tool = _get_native_code_interpreter(minio={}, type="container")
    assert isinstance(tool.executor, ContainerExecutor)


def test_type_e2b_builds_e2b_executor():
    tool = _get_native_code_interpreter(minio={}, type="e2b", config={"e2b": {"api_key": "k"}})
    assert isinstance(tool.executor, E2bCodeExecutor)


def test_missing_type_defaults_to_local_not_container():
    tool = _get_native_code_interpreter(minio={})
    assert isinstance(tool.executor, LocalExecutor)
    assert not isinstance(tool.executor, ContainerExecutor)


def test_unknown_type_raises_and_does_not_fall_through_to_e2b():
    with pytest.raises(ValueError, match="Unknown code interpreter type"):
        _get_native_code_interpreter(minio={}, type="cloud")


def test_e2b_config_type_is_not_an_executor_kwarg(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class _Spy:
        description = "spy"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("bisheng_langchain.gpts.load_tools.E2bCodeExecutor", _Spy)
    _get_native_code_interpreter(
        minio={},
        type="e2b",
        config={"e2b": {"api_key": "k", "type": "official", "domain": ""}},
    )
    assert "type" not in captured
    assert captured.get("api_key") == "k"


def test_container_pool_params_come_from_sandbox_conf_not_extra(monkeypatch: pytest.MonkeyPatch):
    import bisheng_langchain.gpts.load_tools as load_tools_mod

    conf = SandboxConf(endpoints=["http://pool:8080"], token="pool-token")
    monkeypatch.setattr(load_tools_mod, "settings", type("S", (), {"sandbox_conf": conf})())
    tool = _get_native_code_interpreter(
        minio={},
        type="container",
        config={
            "container": {
                "timeout": 120,
                "endpoints": ["http://from-extra:1"],
                "token": "from-extra",
            }
        },
    )
    assert isinstance(tool.executor, ContainerExecutor)
    assert tool.executor.timeout == 120
    assert tool.executor.endpoints == ["http://pool:8080"]
    assert tool.executor.token == "pool-token"


def test_switching_type_does_not_need_process_restart():
    first = _get_native_code_interpreter(minio={}, type="local")
    second = _get_native_code_interpreter(minio={}, type="container")
    assert isinstance(first.executor, LocalExecutor)
    assert isinstance(second.executor, ContainerExecutor)


def test_five_call_sites_go_through_tool_executor_not_local_executor():
    for path in _FIVE_PATHS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            assert name != "LocalExecutor", f"{path} constructs LocalExecutor directly"
        assert "init_by_tool_id" in source, f"{path} must go through ToolExecutor.init_by_tool_id(s)"
