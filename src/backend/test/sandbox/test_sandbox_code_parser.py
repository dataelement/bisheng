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


def test_make_code_parser_ignores_sandbox_switch_and_stays_out_of_process():
    parser = make_code_parser(_MAIN, enabled=False)
    assert isinstance(parser, SandboxCodeParser)


def test_code_node_does_not_pass_process_cwd_as_workspace():
    fake = _FakeRunner()
    parser = SandboxCodeParser(_MAIN, execute_code=fake.execute_code)
    parser.parse_code()
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert fake.calls
    assert fake.calls[0]["work_dir"] is None


def test_local_backend_runs_in_a_fresh_directory(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _Executor:
        def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
            seen["work_dir"] = work_dir
            seen["code"] = code
            return 0, SENTINEL_OK + '{"sum": 3, "x": 1}', ""

        def close(self):
            seen["closed"] = True

    def _build(kind, **kwargs):
        seen["kind"] = kind
        seen["kwargs"] = kwargs
        return _Executor()

    monkeypatch.setattr(
        "bisheng.workflow.nodes.code.code_parse.load_code_interpreter_extra",
        lambda: {"type": "local", "config": {"local": {"local_sync_path": "/tmp/session"}}},
    )
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.build_code_executor",
        _build,
    )
    parser = SandboxCodeParser(_MAIN)
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert seen["kind"] == "local"
    assert seen["work_dir"]
    assert seen["work_dir"] != "/tmp/session"
    assert "local_sync_path" not in seen["kwargs"]
    assert seen["closed"] is True


def test_container_backend_does_not_copy_the_worker_cwd(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _Executor:
        def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
            seen["work_dir"] = work_dir
            return 0, SENTINEL_OK + '{"sum": 3, "x": 1}', ""

        def close(self):
            return None

    def _build(kind, **kwargs):
        seen["kind"] = kind
        seen["kwargs"] = kwargs
        return _Executor()

    monkeypatch.setattr(
        "bisheng.workflow.nodes.code.code_parse.load_code_interpreter_extra",
        lambda: {"type": "container", "config": {"container": {"keep_session": True, "token": "from-extra"}}},
    )
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.build_code_executor",
        _build,
    )
    parser = SandboxCodeParser(_MAIN)
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert seen["kind"] == "container"
    assert seen["work_dir"] is None
    assert seen["kwargs"]["keep_session"] is False


def test_e2b_backend_forwards_only_credentials(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _Executor:
        def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
            seen["called_execute"] = True
            return 0, SENTINEL_OK + '{"sum": 3, "x": 1}', ""

        def run(self, code):
            raise AssertionError("code node must not call executor.run")

        def close(self):
            return None

    def _build(kind, **kwargs):
        seen["kind"] = kind
        seen["kwargs"] = kwargs
        return _Executor()

    monkeypatch.setattr(
        "bisheng.workflow.nodes.code.code_parse.load_code_interpreter_extra",
        lambda: {
            "type": "e2b",
            "config": {
                "e2b": {
                    "api_key": "k",
                    "domain": "https://e2b.internal",
                    "type": "private",
                    "local_sync_path": "/tmp/session",
                    "file_list": ["a"],
                }
            },
        },
    )
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.build_code_executor",
        _build,
    )
    parser = SandboxCodeParser(_MAIN)
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert seen["called_execute"] is True
    assert seen["kind"] == "e2b"
    assert seen["kwargs"]["api_key"] == "k"
    assert seen["kwargs"]["domain"] == "https://e2b.internal"
    assert seen["kwargs"]["keep_sandbox"] is False
    assert "type" not in seen["kwargs"]
    assert "local_sync_path" not in seen["kwargs"]
    assert "file_list" not in seen["kwargs"]


def test_missing_type_defaults_to_local(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _Executor:
        def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
            return 0, SENTINEL_OK + '{"sum": 3, "x": 1}', ""

        def close(self):
            return None

    monkeypatch.setattr(
        "bisheng.workflow.nodes.code.code_parse.load_code_interpreter_extra",
        lambda: {},
    )

    def _build(kind, **kwargs):
        seen["kind"] = kind
        return _Executor()

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.build_code_executor",
        _build,
    )
    parser = SandboxCodeParser(_MAIN)
    assert parser.exec_method("main", x=1, y=2) == {"sum": 3, "x": 1}
    assert seen["kind"] == "local"


def test_unknown_type_raises_and_does_not_run_local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "bisheng.workflow.nodes.code.code_parse.load_code_interpreter_extra",
        lambda: {"type": "cloud"},
    )

    def _build(kind, **kwargs):
        raise ValueError(f"Unknown code interpreter type: {kind!r}")

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.code_interpreter.factory.build_code_executor",
        _build,
    )
    parser = SandboxCodeParser(_MAIN)
    with pytest.raises(ValueError, match="Unknown code interpreter type"):
        parser.exec_method("main", x=1, y=2)


def test_empty_tool_row_reads_category_type(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
    from bisheng.workflow.nodes.code.code_parse import load_code_interpreter_extra

    monkeypatch.setattr(
        GptsToolsDao,
        "get_tool_by_tool_key",
        lambda tool_key: SimpleNamespace(extra=None, type=6, tool_key=tool_key),
    )
    monkeypatch.setattr(
        GptsToolsDao,
        "get_one_tool_type",
        lambda tool_type_id: SimpleNamespace(extra='{"type": "container", "config": {"container": {}}}'),
    )
    assert load_code_interpreter_extra()["type"] == "container"


def test_tool_row_type_wins_over_category(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
    from bisheng.workflow.nodes.code.code_parse import load_code_interpreter_extra

    monkeypatch.setattr(
        GptsToolsDao,
        "get_tool_by_tool_key",
        lambda tool_key: SimpleNamespace(extra='{"type": "local"}', type=6),
    )

    def _category(tool_type_id):
        raise AssertionError("category extra must not be read when the tool row has extra")

    monkeypatch.setattr(GptsToolsDao, "get_one_tool_type", _category)
    assert load_code_interpreter_extra()["type"] == "local"


def test_wrapper_is_a_script_the_runner_can_exec_without_knowing_main():
    script = build_code_node_wrapper(_MAIN, "main", {"x": 10, "y": 5})
    buf = io.StringIO()
    with redirect_stdout(buf):
        exec(script, {}, {})
    line = buf.getvalue()
    assert SENTINEL_OK in line
    assert "15" in line
