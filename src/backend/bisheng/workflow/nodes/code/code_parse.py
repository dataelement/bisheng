import ast
import importlib
import inspect
import json
from typing import Any, Union

from bisheng.common.errcode.sandbox import SandboxCodeNodeOutputError

SENTINEL_OK = "__BISHENG_CODE_NODE_RESULT__"
SENTINEL_BAD = "__BISHENG_CODE_NODE_UNSERIALIZABLE__"


def build_code_node_wrapper(user_code: str, method_name: str, params: dict) -> str:
    """User source + json.loads inputs → call ``method_name`` → sentinel json.dumps.

    The isolation environment does not know what a workflow node is; it only execs
    this script. ``method_name`` must be a Python identifier.
    """
    if not method_name.isidentifier():
        raise ValueError(f"Invalid method name: {method_name!r}")
    payload = json.dumps(params, ensure_ascii=False)
    return (
        user_code
        + "\n\n"
        + "import json as _bisheng_json\n"
        + f"_bisheng_params = _bisheng_json.loads({payload!r})\n"
        + f"_bisheng_ret = {method_name}(**_bisheng_params)\n"
        + "try:\n"
        + "    _bisheng_out = _bisheng_json.dumps(_bisheng_ret, ensure_ascii=False)\n"
        + "except (TypeError, ValueError):\n"
        + f"    print({SENTINEL_BAD!r})\n"
        + "else:\n"
        + f"    print({SENTINEL_OK!r} + _bisheng_out)\n"
    )


def _parse_sentinel(logs: str):
    if SENTINEL_BAD in logs:
        raise SandboxCodeNodeOutputError()
    idx = logs.rfind(SENTINEL_OK)
    if idx < 0:
        return None
    raw = logs[idx + len(SENTINEL_OK) :].splitlines()[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxCodeNodeOutputError() from exc


def make_code_parser(code: str, *, execute_code=None, enabled: bool | None = None):
    """CodeParser (in-process) or SandboxCodeParser. Only the system switch rolls back."""
    if enabled is None:
        from bisheng.common.services.config_service import settings

        enabled = settings.sandbox_conf.code_node_enabled
    if enabled:
        return SandboxCodeParser(code, execute_code=execute_code)
    return CodeParser(code)


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
        # Syntax only. Do not exec / importlib — those run inside the isolation
        # environment. Keeps save-time failure on SyntaxError (AC-20).
        ast.parse(self.code)
        return self.data

    def exec_method(self, method_name: str, *args, **kwargs):
        if args:
            raise TypeError("code node isolation exec_method only accepts keyword arguments")
        wrapper = build_code_node_wrapper(self.code, method_name, kwargs)
        exitcode, logs, _ = self._invoke_execute(wrapper)
        logs = logs or ""
        result = _parse_sentinel(logs)
        if result is None:
            if exitcode:
                raise RuntimeError(logs or f"code node exited {exitcode}")
            raise SandboxCodeNodeOutputError()
        return result

    def _invoke_execute(self, wrapper: str):
        fn = self._execute_code
        if fn is None:
            from bisheng.common.services.config_service import settings
            from bisheng_langchain.gpts.tools.code_interpreter.container_executor import (
                ContainerExecutor,
            )

            fn = ContainerExecutor(
                minio={},
                sandbox_conf=settings.sandbox_conf,
                keep_session=False,
            ).execute_code
            self._execute_code = fn
        return fn(code=wrapper, lang="python")
