"""SandboxCodeParser wrapper / ast.parse / 28005 / switch (F068 T021)."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from bisheng.common.errcode.sandbox import SandboxCodeNodeOutputError
from bisheng.workflow.nodes.code.code_parse import (
    SENTINEL_OK,
    CodeParser,
    SandboxCodeParser,
    build_code_node_wrapper,
    make_code_parser,
)

_MAIN = """
def main(x, y):
    return {"sum": x + y, "x": x}
"""


class _FakeRunner:
    def __init__(self):
        self.calls: list[dict] = []

    def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
        self.calls.append({"code": code, "lang": lang, "work_dir": work_dir})
        buf = io.StringIO()
        ns: dict = {}
        with redirect_stdout(buf), redirect_stderr(buf):
            exec(code, ns, ns)
        return 0, buf.getvalue(), ""


def test_syntax_error_is_raised_in_parse_code_without_calling_runner():
    fake = _FakeRunner()
    parser = SandboxCodeParser("def main(:\n    pass\n", execute_code=fake.execute_code)
    with pytest.raises(SyntaxError):
        parser.parse_code()
    assert fake.calls == []


def test_legal_main_wrapper_output_matches_in_process_parser():
    fake = _FakeRunner()
    sandboxed = SandboxCodeParser(_MAIN, execute_code=fake.execute_code)
    sandboxed.parse_code()
    got = sandboxed.exec_method("main", x=1, y=2)

    legacy = CodeParser(_MAIN)
    legacy.parse_code()
    expected = legacy.exec_method("main", x=1, y=2)

    assert got == expected == {"sum": 3, "x": 1}
    assert fake.calls
    wrapper = fake.calls[0]["code"]
    assert "json.loads" in wrapper
    assert "json.dumps" in wrapper
    assert SENTINEL_OK in wrapper
    assert "def main" in wrapper


def test_unserializable_return_is_28005_not_empty_dict():
    fake = _FakeRunner()
    code = """
class _NotJson:
    pass

def main():
    return {"obj": _NotJson()}
"""
    parser = SandboxCodeParser(code, execute_code=fake.execute_code)
    parser.parse_code()
    with pytest.raises(SandboxCodeNodeOutputError) as err:
        parser.exec_method("main")
    assert err.value.Code == 28005
    assert err.value.Code != 0


def test_code_node_disabled_uses_in_process_exec_not_http(monkeypatch: pytest.MonkeyPatch):
    http_calls: list = []

    def _boom(*_a, **_k):
        http_calls.append(1)
        raise AssertionError("isolation execute_code must not run when the switch is off")

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.container_executor.ContainerExecutor.execute_code",
        _boom,
    )
    parser = make_code_parser(_MAIN, enabled=False)
    assert isinstance(parser, CodeParser)
    assert not isinstance(parser, SandboxCodeParser)
    parser.parse_code()
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert http_calls == []


def test_wrapper_is_a_script_the_runner_can_exec_without_knowing_main():
    script = build_code_node_wrapper(_MAIN, "main", {"x": 10, "y": 5})
    buf = io.StringIO()
    with redirect_stdout(buf):
        exec(script, {}, {})
    line = buf.getvalue()
    assert SENTINEL_OK in line
    assert "15" in line
