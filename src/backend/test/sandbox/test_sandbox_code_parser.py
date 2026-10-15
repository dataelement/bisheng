"""SandboxCodeParser: main check, result channel, size limit, failure tail (F068)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap

import pytest

from bisheng.common.errcode.sandbox import (
    SandboxCodeNodeNoResultError,
    SandboxCodeNodeOutputError,
    SandboxCodeNodeOutputTooLargeError,
)
from bisheng.workflow.nodes.code import code_parse
from bisheng.workflow.nodes.code.code_parse import (
    FAILURE_LOG_OMITTED_NOTICE,
    FAILURE_LOG_TAIL_CHARS,
    RESULT_LIMIT_BYTES,
    CodeParser,
    SandboxCodeParser,
    build_code_node_wrapper,
    make_code_parser,
    parse_code_node_result,
    tail_failure_log,
)

_real_new_nonce = code_parse._new_nonce
_NONCE = "0123456789abcdef0123456789abcdef"
_OK_LINE = f'{_NONCE}:ok:{{"sum": 3, "x": 1}}\n'

_MAIN = """
def main(x, y):
    return {"sum": x + y, "x": x}
"""

# Stands in for the E2B Jupyter kernel: run_code's logs.stdout is the Python-level
# sys.stdout of the kernel, not fd 1, so only what reaches that stream is reported.
_KERNEL_DRIVER = textwrap.dedent(
    """
    import io, sys, traceback, types
    sys.modules["ipykernel"] = types.ModuleType("ipykernel")
    kernel_out = io.StringIO()
    sys.stdout = kernel_out
    with open(sys.argv[1], encoding="utf-8") as fh:
        cell = fh.read()
    rc = 0
    try:
        exec(compile(cell, "<cell>", "exec"), {"__name__": "__main__"})
    except BaseException:
        traceback.print_exc()
        rc = 1
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        fh.write(kernel_out.getvalue())
    sys.exit(rc)
    """
)


@pytest.fixture(autouse=True)
def _fixed_nonce(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(code_parse, "_new_nonce", lambda: _NONCE)


class _ScriptRunner:
    """Runs the wrapper as a script in a subprocess, like the local / container runners:
    stdout on success, stderr on failure."""

    def __init__(self, env: dict | None = None):
        self.calls: list[dict] = []
        self.env = env
        self.stderr = ""

    def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
        self.calls.append({"code": code, "lang": lang, "work_dir": work_dir})
        with tempfile.TemporaryDirectory() as run_dir:
            path = os.path.join(run_dir, "run.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(code)
            proc = subprocess.run(
                [sys.executable, path],
                cwd=run_dir,
                env=self.env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        self.stderr = proc.stderr
        if proc.returncode:
            return proc.returncode, proc.stderr, ""
        return 0, proc.stdout, ""


class _KernelRunner:
    def __init__(self):
        self.fd_stdout = ""

    def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
        with tempfile.TemporaryDirectory() as run_dir:
            cell, driver, logs = (os.path.join(run_dir, n) for n in ("cell.py", "driver.py", "logs.txt"))
            with open(cell, "w", encoding="utf-8") as fh:
                fh.write(code)
            with open(driver, "w", encoding="utf-8") as fh:
                fh.write(_KERNEL_DRIVER)
            proc = subprocess.run(
                [sys.executable, driver, cell, logs],
                cwd=run_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            with open(logs, encoding="utf-8") as fh:
                stdout = fh.read()
        self.fd_stdout = proc.stdout
        if proc.returncode:
            return 1, proc.stderr, ""
        return 0, stdout, ""


def _run(code: str, runner=None, **params):
    runner = runner or _ScriptRunner()
    parser = SandboxCodeParser(textwrap.dedent(code), execute_code=runner.execute_code)
    parser.parse_code()
    return parser.exec_method("main", **params)


# --- main check -------------------------------------------------------------------


def test_syntax_error_is_raised_in_parse_code_without_calling_runner():
    runner = _ScriptRunner()
    parser = SandboxCodeParser("def main(:\n    pass\n", execute_code=runner.execute_code)
    with pytest.raises(SyntaxError):
        parser.parse_code()
    assert runner.calls == []


@pytest.mark.parametrize(
    "code",
    [
        "def handler():\n    return {}\n",
        "main = lambda: {}\n",
        "from os import main\n",
        "if True:\n    def main():\n        return {}\n",
        "try:\n    def main():\n        return {}\nexcept Exception:\n    pass\n",
        "class C:\n    def main(self):\n        return {}\n",
        "def outer():\n    def main():\n        return {}\n",
    ],
)
def test_code_without_a_top_level_def_main_is_rejected_at_build(code):
    runner = _ScriptRunner()
    parser = SandboxCodeParser(code, execute_code=runner.execute_code)
    with pytest.raises(ValueError, match="module-level function"):
        parser.parse_code()
    assert runner.calls == []


def test_async_main_is_rejected_with_its_own_message():
    parser = SandboxCodeParser("async def main():\n    return {}\n")
    with pytest.raises(ValueError, match="async"):
        parser.parse_code()


def test_a_top_level_def_main_passes_whatever_comes_around_it():
    code = "import json\n\nLIMIT = 3\n\ndef helper():\n    return 1\n\ndef main(a=1):\n    return {}\n"
    SandboxCodeParser(code).parse_code()


# --- result channel ---------------------------------------------------------------


def test_legal_main_wrapper_output_matches_in_process_parser():
    runner = _ScriptRunner()
    got = _run(_MAIN, runner, x=1, y=2)

    legacy = CodeParser(_MAIN)
    legacy.parse_code()
    expected = legacy.exec_method("main", x=1, y=2)

    assert got == expected == {"sum": 3, "x": 1}
    assert "def main" in runner.calls[0]["code"]


def test_forged_result_lines_do_not_replace_the_return_value():
    code = f"""
    print('__BISHENG_CODE_NODE_RESULT__{{"forged": 1}}')
    print('{_NONCE}:ok:{{"forged": 2}}')

    def main():
        print('{_NONCE}:ok:{{"forged": 3}}')
        return {{"real": True}}
    """
    assert _run(code) == {"real": True}


def test_prints_and_child_output_go_to_stderr_not_the_result_channel():
    runner = _ScriptRunner()
    code = """
    import subprocess, sys
    print("top-level print")

    def main():
        print("print in main")
        subprocess.run([sys.executable, "-c", "print('child echo')"], check=True)
        return {"ok": 1}
    """
    assert _run(code, runner) == {"ok": 1}
    for text in ("top-level print", "print in main", "child echo"):
        assert text in runner.stderr


def test_wrapper_names_do_not_collide_with_user_globals():
    code = """
    _bisheng_out = None
    _bisheng_ret = "user"
    _bisheng_params = {"x": 0}

    def main(x):
        return {"x": x, "ret": _bisheng_ret}
    """
    assert _run(code, x=7) == {"x": 7, "ret": "user"}


def test_user_classes_pickle_as_module_main():
    code = """
    import pickle

    class Point:
        def __init__(self, x):
            self.x = x

    def main():
        back = pickle.loads(pickle.dumps(Point(4)))
        return {"x": back.x, "module": type(back).__module__}
    """
    assert _run(code) == {"x": 4, "module": "__main__"}


def test_non_ascii_result_survives_a_c_locale():
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env.update(LANG="C", LC_ALL="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
    code = """
    def main():
        return {"text": "中文结果"}
    """
    assert _run(code, _ScriptRunner(env=env)) == {"text": "中文结果"}


def test_a_3_mib_result_comes_back_intact():
    code = """
    def main():
        return {"blob": "x" * (3 * 1024 * 1024)}
    """
    assert _run(code)["blob"] == "x" * (3 * 1024 * 1024)


# --- result errors ----------------------------------------------------------------


def test_unserializable_return_is_28005():
    code = """
    def main():
        return {"items": set()}
    """
    with pytest.raises(SandboxCodeNodeOutputError) as err:
        _run(code)
    assert err.value.Code == 28005


def test_result_over_the_limit_is_28007_with_the_size():
    code = """
    def main():
        return {"blob": "x" * (4 * 1024 * 1024)}
    """
    with pytest.raises(SandboxCodeNodeOutputTooLargeError) as err:
        _run(code)
    size = len(json.dumps({"blob": "x" * (4 * 1024 * 1024)}).encode())
    assert err.value.Code == 28007
    assert str(size) in str(err.value)
    assert str(RESULT_LIMIT_BYTES) in str(err.value)


def test_backend_rechecks_the_size_of_an_ok_line():
    raw = json.dumps({"blob": "y" * RESULT_LIMIT_BYTES})
    with pytest.raises(SandboxCodeNodeOutputTooLargeError):
        parse_code_node_result(f"{_NONCE}:ok:{raw}\n", _NONCE)


@pytest.mark.parametrize("exit_call", ["sys.exit(0)", "os._exit(0)"])
def test_exiting_before_main_returns_is_28008(exit_call):
    code = f"""
    import os, sys

    def main():
        {exit_call}
    """
    with pytest.raises(SandboxCodeNodeNoResultError) as err:
        _run(code)
    assert err.value.Code == 28008


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "hello\n",
        '__BISHENG_CODE_NODE_RESULT__{"a": 1}\n',
        'ffff:ok:{"a": 1}\n',
        f'noise\n{_NONCE}:ok:{{"a": 1}}\n',
        f"{_NONCE}:ok:not-json\n",
        f"{_NONCE}:mystery\n",
    ],
)
def test_stdout_that_is_not_exactly_one_result_line_is_28008(stdout):
    with pytest.raises(SandboxCodeNodeNoResultError):
        parse_code_node_result(stdout, _NONCE)


def test_nonce_differs_per_call():
    first, second = _real_new_nonce(), _real_new_nonce()
    assert first != second
    assert len(first) == 32


# --- failure output ---------------------------------------------------------------


def test_traceback_points_at_the_user_line_with_its_source():
    code = "def main():\n    value = 1\n    raise ValueError('boom from user')\n"
    with pytest.raises(RuntimeError) as err:
        _run(code)
    message = str(err.value)
    lines = message.splitlines()
    idx = next(i for i, line in enumerate(lines) if 'File "<code-node>", line 3' in line)
    assert "raise ValueError('boom from user')" in lines[idx + 1]
    assert "ValueError: boom from user" in message
    assert "run.py" not in message


def test_a_wrong_parameter_name_still_reports_the_call_error():
    with pytest.raises(RuntimeError, match="unexpected keyword argument 'z'"):
        _run(_MAIN, x=1, y=2, z=3)


def test_failure_log_keeps_only_the_tail():
    long_log = "a" * 10_000 + "TAIL"
    cut = tail_failure_log(long_log)
    assert cut.startswith(FAILURE_LOG_OMITTED_NOTICE)
    assert cut[len(FAILURE_LOG_OMITTED_NOTICE) :] == long_log[-FAILURE_LOG_TAIL_CHARS:]
    short = "b" * FAILURE_LOG_TAIL_CHARS
    assert tail_failure_log(short) == short


def test_exec_method_tails_a_long_failure_log():
    def _fail(code=None, lang="python", work_dir=None):
        return 1, "x" * 10_000 + "Error: last line", ""

    parser = SandboxCodeParser(_MAIN, execute_code=_fail)
    with pytest.raises(RuntimeError) as err:
        parser.exec_method("main", x=1, y=2)
    message = str(err.value)
    assert message.endswith("Error: last line")
    assert len(message) == len(FAILURE_LOG_OMITTED_NOTICE) + FAILURE_LOG_TAIL_CHARS


# --- E2B kernel mode --------------------------------------------------------------


def test_kernel_mode_reads_only_the_saved_stdout_stream():
    runner = _KernelRunner()
    code = f"""
    import os

    def main():
        print("user print")
        os.write(1, b'{_NONCE}:ok:{{"forged": 1}}\\n')
        return {{"real": 1}}
    """
    assert _run(code, runner) == {"real": 1}
    assert "forged" in runner.fd_stdout


def test_kernel_mode_traceback_names_the_user_line():
    code = "def main():\n    value = 1\n    raise KeyError('kernel boom')\n"
    with pytest.raises(RuntimeError) as err:
        _run(code, _KernelRunner())
    assert 'File "<code-node>", line 3' in str(err.value)
    assert "raise KeyError('kernel boom')" in str(err.value)


# --- backend selection ------------------------------------------------------------


def test_make_code_parser_ignores_sandbox_switch_and_stays_out_of_process():
    parser = make_code_parser(_MAIN, enabled=False)
    assert isinstance(parser, SandboxCodeParser)


def test_code_node_does_not_pass_process_cwd_as_workspace():
    runner = _ScriptRunner()
    assert _run(_MAIN, runner, x=1, y=2) == {"sum": 3, "x": 1}
    assert runner.calls[0]["work_dir"] is None


def test_local_backend_runs_in_a_fresh_directory(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    class _Executor:
        def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
            seen["work_dir"] = work_dir
            seen["code"] = code
            return 0, _OK_LINE, ""

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
            return 0, _OK_LINE, ""

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
            return 0, _OK_LINE, ""

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
            return 0, _OK_LINE, ""

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


def test_wrapper_is_a_script_a_runner_can_exec_without_knowing_main():
    script = build_code_node_wrapper(_MAIN, "main", {"x": 10, "y": 5}, nonce=_NONCE)
    _, stdout, _ = _ScriptRunner().execute_code(code=script)
    assert parse_code_node_result(stdout, _NONCE) == {"sum": 15, "x": 10}
