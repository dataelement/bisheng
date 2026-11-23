"""Public execution loaders must never select backend-host local execution."""

from unittest.mock import Mock

import pytest

from bisheng.common.errcode.sandbox import SandboxConfigurationError


@pytest.mark.parametrize("extra", [{}, {"config": {"local": {}}}])
def test_factory_local_refused_before_constructor(monkeypatch, extra):
    from bisheng_langchain.gpts.tools.code_interpreter import factory

    local = Mock()
    monkeypatch.setattr(factory, "LocalExecutor", local)
    with pytest.raises(SandboxConfigurationError):
        factory.build_code_executor("local", **extra)
    local.assert_not_called()


def test_tool_loader_missing_kind_is_not_host_execution(monkeypatch):
    from bisheng_langchain.gpts import load_tools

    with pytest.raises(SandboxConfigurationError):
        load_tools._get_native_code_interpreter(minio={})


def test_code_node_default_backend_refused_without_executing(monkeypatch):
    from bisheng.workflow.nodes.code import code_parse

    monkeypatch.setattr(code_parse, "load_code_interpreter_extra", lambda: {})
    parser = code_parse.SandboxCodeParser("def main():\n return {}")
    parser.parse_code()
    with pytest.raises(SandboxConfigurationError):
        parser.exec_method("main")


@pytest.mark.parametrize("kind", ["container", "e2b"])
def test_explicit_external_backends_still_selected_without_network(monkeypatch, kind):
    from bisheng_langchain.gpts.tools.code_interpreter import factory

    external = Mock(return_value=object())
    monkeypatch.setattr(factory, "ContainerExecutor" if kind == "container" else "E2bCodeExecutor", external)
    monkeypatch.setattr(factory, "load_sandbox_conf", lambda: object())
    result = factory.build_code_executor(kind, minio={}, api_key="unit-fixture")
    assert result is external.return_value
    external.assert_called_once()
