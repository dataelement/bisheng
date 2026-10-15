import ast
import importlib
import inspect
import json
import secrets
import tempfile
from typing import Any, Union

from bisheng.common.errcode.sandbox import (
    SandboxCodeNodeNoResultError,
    SandboxCodeNodeOutputError,
    SandboxCodeNodeOutputTooLargeError,
)

# UTF-8 bytes of the result JSON. The local isolation output window keeps the
# first 4 MiB of stdout plus the last 512 KiB, so one such line always survives.
RESULT_LIMIT_BYTES = 4 * 1024 * 1024
FAILURE_LOG_TAIL_CHARS = 4096
FAILURE_LOG_OMITTED_NOTICE = "[... earlier output omitted ...]\n"
USER_CODE_FILENAME = "<code-node>"

_OK = "ok:"
_UNSERIALIZABLE = "unserializable"
_TOO_LARGE = "too_large:"


def _new_nonce() -> str:
    return secrets.token_hex(16)


def check_main_function(code: str) -> None:
    """Require a module-level ``def main``; the wrapper calls it by that name."""
    tree = ast.parse(code)
    has_async = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main":
            has_async = True
    if has_async:
        raise ValueError("main must not be async: the code node calls it synchronously")
    raise ValueError("the code needs a module-level function `def main(...)`")


def build_code_node_wrapper(
    user_code: str, method_name: str, params: dict, *, nonce: str, limit: int = RESULT_LIMIT_BYTES
) -> str:
    """Script that runs ``user_code`` in its own ``__main__`` and writes one result line.

    User prints and child processes are moved to stderr before the user code runs, so
    stdout carries only ``<nonce>:ok:<json>`` / ``<nonce>:unserializable`` /
    ``<nonce>:too_large:<n>``. A script keeps the parent's pipe on a dup of fd 1; the
    E2B Jupyter kernel captures ``sys.stdout`` rather than fd 1, so there the original
    stream object is kept instead.
    """
    if not method_name.isidentifier():
        raise ValueError(f"Invalid method name: {method_name!r}")
    payload = json.dumps(params, ensure_ascii=False)
    return (
        "import json as _bisheng_json\n"
        "import linecache as _bisheng_linecache\n"
        "import os as _bisheng_os\n"
        "import sys as _bisheng_sys\n"
        "import traceback as _bisheng_traceback\n"
        "import types as _bisheng_types\n"
        "\n"
        'if "ipykernel" in _bisheng_sys.modules:\n'
        "    _bisheng_out = _bisheng_sys.stdout\n"
        "    _bisheng_sys.stdout = _bisheng_sys.stderr\n"
        "else:\n"
        '    _bisheng_out = _bisheng_os.fdopen(_bisheng_os.dup(1), "w", encoding="utf-8")\n'
        "    _bisheng_os.dup2(2, 1)\n"
        "    _bisheng_sys.stdout = _bisheng_sys.stderr\n"
        # The built-in hook reads source from disk, not linecache, so "<code-node>"
        # lines would print without their code. Skipping the first frame drops this
        # script's own path when the error comes from user code.
        "    def _bisheng_hook(_t, _v, _tb):\n"
        "        _bisheng_traceback.print_exception(_t, _v, _tb.tb_next if _tb and _tb.tb_next else _tb)\n"
        "    _bisheng_sys.excepthook = _bisheng_hook\n"
        "\n"
        f"_bisheng_src = {user_code!r}\n"
        "_bisheng_lines = _bisheng_src.splitlines(True)\n"
        'if _bisheng_lines and not _bisheng_lines[-1].endswith("\\n"):\n'
        '    _bisheng_lines[-1] += "\\n"\n'
        # mtime None: traceback's checkcache would otherwise stat the name and drop it.
        f"_bisheng_linecache.cache[{USER_CODE_FILENAME!r}] = "
        f"(len(_bisheng_src), None, _bisheng_lines, {USER_CODE_FILENAME!r})\n"
        "\n"
        # A real module, so pickle finds user classes as __main__.<name>.
        '_bisheng_user = _bisheng_types.ModuleType("__main__")\n'
        '_bisheng_sys.modules["__main__"] = _bisheng_user\n'
        f'exec(compile(_bisheng_src, {USER_CODE_FILENAME!r}, "exec"), _bisheng_user.__dict__)\n'
        f"_bisheng_ret = _bisheng_user.__dict__[{method_name!r}](**_bisheng_json.loads({payload!r}))\n"
        "try:\n"
        '    _bisheng_data = _bisheng_json.dumps(_bisheng_ret, ensure_ascii=False).encode("utf-8")\n'
        "except (TypeError, ValueError):\n"
        f"    _bisheng_line = {nonce + ':' + _UNSERIALIZABLE + chr(10)!r}\n"
        "else:\n"
        f"    if len(_bisheng_data) > {int(limit)}:\n"
        f"        _bisheng_line = {nonce + ':' + _TOO_LARGE!r} + str(len(_bisheng_data)) + "
        '"\\n"\n'
        "    else:\n"
        f'        _bisheng_line = {nonce + ":" + _OK!r} + _bisheng_data.decode("utf-8") + "\\n"\n'
        "_bisheng_out.write(_bisheng_line)\n"
        "_bisheng_out.flush()\n"
    )


def parse_code_node_result(stdout: str, nonce: str, limit: int = RESULT_LIMIT_BYTES):
    """Read the single ``<nonce>:…`` line; anything else means no result came back."""
    line = (stdout or "").removesuffix("\n")
    prefix = nonce + ":"
    if "\n" in line or not line.startswith(prefix):
        raise SandboxCodeNodeNoResultError()
    body = line[len(prefix) :]
    if body == _UNSERIALIZABLE:
        raise SandboxCodeNodeOutputError()
    if body.startswith(_TOO_LARGE):
        raise SandboxCodeNodeOutputTooLargeError(size=body[len(_TOO_LARGE) :], limit=limit)
    if not body.startswith(_OK):
        raise SandboxCodeNodeNoResultError()
    raw = body[len(_OK) :]
    size = len(raw.encode("utf-8"))
    if size > limit:
        raise SandboxCodeNodeOutputTooLargeError(size=size, limit=limit)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxCodeNodeNoResultError() from exc


def tail_failure_log(logs: str, limit: int = FAILURE_LOG_TAIL_CHARS) -> str:
    """Keep the last ``limit`` characters; a traceback states its cause at the end."""
    if len(logs) <= limit:
        return logs
    return FAILURE_LOG_OMITTED_NOTICE + logs[-limit:]


# Session bindings the linsight tool adds after reading extra. The code node has
# no workspace, so they must not ride along into the executor.
_SESSION_KEYS = ("local_sync_path", "workspace_prefix", "file_list")
_CODE_INTERPRETER_TOOL_KEY = "bisheng_code_interpreter"


def make_code_parser(code: str, *, execute_code=None, enabled: bool | None = None):
    """Out-of-process parser. Backend kind is read from the tool row at exec time.

    ``enabled`` is ignored. ``sandbox_conf.code_node_enabled`` no longer selects
    an in-process fallback. ``workflow.code_node_enabled`` is the only gate, and
    it is checked before this function runs.
    """
    del enabled
    return SandboxCodeParser(code, execute_code=execute_code)


def load_code_interpreter_extra() -> dict:
    """Preset extra for the built-in code interpreter, in the current tenant.

    Tool-row extra wins. An empty row falls back to the category extra, which is
    where the admin UI stores ``type``. ``t_gpts_tools.type`` is the category id,
    not local/container/e2b.
    """
    from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
    from bisheng.tool.domain.services.executor import ToolExecutor

    tool = GptsToolsDao.get_tool_by_tool_key(_CODE_INTERPRETER_TOOL_KEY)
    if tool is None:
        return {}
    tool_type = None
    type_id = getattr(tool, "type", None)
    if not tool.extra and type_id:
        tool_type = GptsToolsDao.get_one_tool_type(tool_type_id=type_id)
    extra = ToolExecutor.parse_preset_extra(tool, tool_type)
    return extra if isinstance(extra, dict) else {}


class CodeParser:
    """
    A parser for Python source code, extracting code details.
    """

    def __init__(self, code: Union[str, type]) -> None:
        """
        Initializes the parser with the provided code.
        """
        if isinstance(code, type):
            if not inspect.isclass(code):
                raise ValueError("The provided code must be a class.")
            # If the code is a class, get its source code
            code = inspect.getsource(code)
        self.code = code
        self.exec_globals = {}
        self.exec_locals = {}
        self.data: dict[str, Any] = {
            "imports": [],
        }
        self.handlers = {
            ast.Import: self.parse_imports,
            ast.ImportFrom: self.parse_imports,
            ast.FunctionDef: self.parse_functions,
            ast.ClassDef: self.parse_classes,
            ast.Assign: self.parse_global_vars,
        }

    def parse_code(self) -> dict[str, Any]:
        """
        Runs all parsing operations and returns the resulting data.
        """
        tree = self.get_tree()

        for node in ast.walk(tree):
            self.parse_node(node)
        return self.data

    def get_tree(self):
        """
        Parses the provided code to validate its syntax.
        It tries to parse the code into an abstract syntax tree (AST).
        """
        return ast.parse(self.code)

    def parse_node(self, node: Union[ast.stmt, ast.AST]) -> None:
        """
        Parses an AST node and updates the data
        dictionary with the relevant information.
        """
        if handler := self.handlers.get(type(node)):  # type: ignore
            handler(node)  # type: ignore

    def parse_imports(self, node: Union[ast.Import, ast.ImportFrom]) -> None:
        """
        Extracts "imports" from the code, including aliases.
        """
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self.data["imports"].append(f"{alias.name} as {alias.asname}")
                else:
                    self.data["imports"].append(alias.name)
                # Actual Import Module
                try:
                    self.exec_globals[alias.asname or alias.name] = importlib.import_module(alias.name)
                except ModuleNotFoundError as e:
                    raise ModuleNotFoundError(f"Module {alias.name} not found. Please install it and try again.") from e
        elif isinstance(node, ast.ImportFrom):
            try:
                imported_module = importlib.import_module(node.module)
                for alias in node.names:
                    if alias.asname:
                        self.data["imports"].append((node.module, f"{alias.name} as {alias.asname}"))
                    else:
                        self.data["imports"].append((node.module, alias.name))
                    self.exec_globals[alias.name] = getattr(imported_module, alias.name)
            except ModuleNotFoundError:
                raise ModuleNotFoundError(f"Module {node.module} not found. Please install it and try again")

    def parse_functions(self, node: ast.FunctionDef) -> None:
        """
        Extracts "functions" from the code.
        """
        compiled_func = compile(ast.Module(body=[node], type_ignores=[]), "<string>", "exec")
        exec(compiled_func, self.exec_globals, self.exec_locals)

    def parse_classes(self, node: ast.ClassDef) -> None:
        compiled_class = compile(ast.Module(body=[node], type_ignores=[]), "<string>", "exec")
        exec(compiled_class, self.exec_globals, self.exec_locals)
        self.exec_globals[node.name] = self.exec_locals[node.name]

    def parse_global_vars(self, node: ast.Assign) -> None:
        """
        Extracts global variables from the code.
        """
        global_var = {
            "targets": [t.id if hasattr(t, "id") else ast.dump(t) for t in node.targets],
            "value": ast.unparse(node.value),
        }
        if isinstance(node.value, ast.Constant):
            for one in global_var["targets"]:
                self.exec_globals[one] = global_var["value"]

    def exec_method(self, method_name: str, *args, **kwargs):
        """
        Executes the method with the provided arguments and keyword arguments.
        """
        method = self.exec_locals.get(method_name)
        if not method:
            raise AttributeError(f"Method {method_name} not found.")
        return method(*args, **kwargs)

    def init_class(self, class_name: str, *args, **kwargs):
        """
        Initializes the class with the provided arguments and keyword arguments.
        """
        class_ = self.exec_globals.get(class_name)
        if not class_:
            raise AttributeError(f"Class {class_name} not found.")
        return class_(*args, **kwargs)


class SandboxCodeParser(CodeParser):
    """Static ``ast.parse`` plus wrapper → the same ``execute_code`` as interpreters."""

    def __init__(self, code: Union[str, type], *, execute_code=None) -> None:
        super().__init__(code)
        self._execute_code = execute_code

    def parse_code(self) -> dict[str, Any]:
        # Static checks only. Do not exec / importlib — those run inside the isolation
        # environment. Runs whenever the node is built (publish, debug run, workflow
        # run), so a missing main fails there instead of inside the sandbox.
        check_main_function(self.code)
        return self.data

    def exec_method(self, method_name: str, *args, **kwargs):
        if args:
            raise TypeError("code node isolation exec_method only accepts keyword arguments")
        nonce = _new_nonce()
        wrapper = build_code_node_wrapper(self.code, method_name, kwargs, nonce=nonce)
        exitcode, logs, _ = self._invoke_execute(wrapper)
        logs = logs or ""
        if exitcode:
            raise RuntimeError(tail_failure_log(logs) or f"code node exited {exitcode}")
        return parse_code_node_result(logs, nonce)

    def _invoke_execute(self, wrapper: str):
        fn = self._execute_code
        if fn is not None:
            # Inputs are inlined in ``wrapper``. Do not pass the worker cwd —
            # that would copy-in /app (backend sources) as if it were a workspace.
            return fn(code=wrapper, lang="python", work_dir=None)
        extra = load_code_interpreter_extra()
        kind = extra.get("type") or "local"
        config = extra.get("config") if isinstance(extra.get("config"), dict) else {}
        backend = dict(config.get(kind) or {}) if isinstance(config, dict) else {}
        for key in _SESSION_KEYS:
            backend.pop(key, None)
        if kind == "container":
            backend["keep_session"] = False
        elif kind == "e2b":
            backend = {key: backend[key] for key in ("api_key", "domain") if backend.get(key)}
            backend["keep_sandbox"] = False
        from bisheng_langchain.gpts.tools.code_interpreter.factory import build_code_executor

        executor = build_code_executor(kind, minio={}, **backend)
        try:
            if kind == "local":
                # work_dir=None writes into the shared extensions/ directory.
                with tempfile.TemporaryDirectory() as work_dir:
                    return executor.execute_code(code=wrapper, lang="python", work_dir=work_dir)
            return executor.execute_code(code=wrapper, lang="python", work_dir=None)
        finally:
            executor.close()
