"""Static validator for the workflow Code node, plus the in-jail runner source.

This file is a security patch payload for BiSheng v2.0.0 - v2.6.0. It replaces
the original ``code_parse.py``, which executed user code at parse time
(``importlib.import_module`` on every import, ``compile`` + ``exec`` on every
function and class). Here nothing user-supplied is ever imported or executed in
the backend process: ``CodeParser.parse_code`` only walks the AST and rejects
anything outside a small allowlist. The actual execution happens in a chroot
jail, driven by ``code.py`` using ``RUNNER_SOURCE`` below.

Target runtime is the interpreter already in the on-site image, which is
Python 3.10 on v2.0.0 - v2.5.0 and 3.11 on v2.6.0, so this file stays within
3.10 syntax and the standard library.

The allowlist, the banned names and the safe builtins live in a single source
string (``_CHECKER_SOURCE``). The backend process ``exec``s it into this
module's namespace, and the runner prepends the very same string to its own
body, so the parent-side check and the in-jail check can never drift apart.
"""

import inspect
from typing import Union

# --- shared checker: used by the parent (validate) and by the jail runner ----
# Kept as source text so both sides run byte-for-byte the same rules.
_CHECKER_SOURCE = r'''
import ast

# Modules a code node may import. Deliberately small: no filesystem, network,
# subprocess, or reflection modules.
ALLOWED_MODULES = frozenset({
    "json", "math", "re", "datetime", "time", "random", "collections",
    "itertools", "functools", "decimal", "base64", "hashlib",
})

# Names that must never appear (as a call target or as a bare reference that
# could be handed around and called later).
DISALLOWED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "breakpoint", "memoryview",
})

# Only calling these is rejected; they are common variable names, and none of
# them exists in the sandbox builtins anyway.
DISALLOWED_CALLS = frozenset({"input"})

# Attribute names that walk the Python object graph out of the sandbox.
DISALLOWED_ATTRS = frozenset({
    "gi_frame", "gi_code", "f_globals", "f_locals", "f_back", "f_builtins",
    "tb_frame", "tb_next", "cr_frame", "ag_frame", "__globals__", "__code__",
    "__closure__", "__subclasses__", "__bases__", "__mro__", "__class__",
    "__dict__", "__builtins__", "__getattribute__", "__reduce__",
    "__reduce_ex__",
})

# Builtins handed to user code. No import machinery, no file access, no eval.
SAFE_BUILTIN_NAMES = (
    "len", "range", "dict", "str", "int", "float", "bool", "list", "tuple",
    "set", "frozenset", "min", "max", "sum", "abs", "round", "enumerate",
    "zip", "map", "filter", "sorted", "reversed", "isinstance", "issubclass",
    "print", "repr", "any", "all", "divmod", "pow", "chr", "ord", "hex",
    "oct", "bin", "format", "True", "False", "None",
    # Exception types, so ordinary try/except and raise keep working. Their
    # reflective members are all underscore attributes, rejected above.
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ZeroDivisionError", "ArithmeticError", "LookupError", "RuntimeError",
    "StopIteration", "AttributeError", "NotImplementedError",
)


class CodeRejected(Exception):
    """Raised when user code is outside the allowlist."""


def _reject(message):
    raise CodeRejected(message)


def _check_import(node):
    if getattr(node, "level", 0):
        _reject("relative import is not allowed")
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        names = [node.module or ""]
    for name in names:
        top = name.split(".")[0]
        if top not in ALLOWED_MODULES:
            _reject("import of %r is not allowed" % name)
        if "." in name:
            _reject("submodule import %r is not allowed" % name)


def _check_function(node):
    if node.decorator_list:
        _reject("decorators are not allowed")
    args = node.args
    defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
    for default in defaults:
        if not isinstance(default, ast.Constant):
            _reject("only constant default arguments are allowed")


def _check_toplevel(stmt):
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return False
    if isinstance(stmt, ast.FunctionDef):
        if stmt.name != "main":
            _reject("the only top-level function may be 'main'")
        return True
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if not isinstance(target, ast.Name):
                _reject("top-level assignments must bind a plain name")
        try:
            ast.literal_eval(stmt.value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            _reject("top-level assignments must be constant")
        return False
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return False  # module docstring
    _reject("unsupported top-level statement: %s" % type(stmt).__name__)


def validate(code):
    """Raise CodeRejected unless ``code`` is a single allowlisted module.

    Allowed at top level: allowlisted imports, a ``main`` function, constant
    assignments, and a docstring. Rejected everywhere: class definitions,
    async defs, decorators, non-constant defaults, disallowed names and
    attributes, and non-allowlisted or relative imports.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        _reject("syntax error: %s" % exc)

    has_main = False
    for stmt in tree.body:
        if _check_toplevel(stmt):
            has_main = True
    if not has_main:
        _reject("a top-level 'main' function is required")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _check_import(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.AsyncFunctionDef):
                _reject("async functions are not allowed")
            _check_function(node)
        elif isinstance(node, ast.ClassDef):
            _reject("class definitions are not allowed")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DISALLOWED_CALLS:
                _reject("calling %r is not allowed" % func.id)
        elif isinstance(node, ast.Name):
            if node.id in DISALLOWED_NAMES or node.id.startswith("__"):
                _reject("use of %r is not allowed" % node.id)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in DISALLOWED_ATTRS:
                _reject("access to attribute %r is not allowed" % node.attr)
'''

# Populate this module with ALLOWED_MODULES / DISALLOWED_* / SAFE_BUILTIN_NAMES /
# CodeRejected / validate. The source is trusted (it is this file), never user
# input.
exec(_CHECKER_SOURCE, globals())


# --- in-jail runner ----------------------------------------------------------
# Appended after the checker so ``validate`` and the allowlist are already
# defined when this runs. Executed by ``code.py`` as:
#   chroot --userspec=U:U --groups=U /opt/code-root /usr/bin/python \
#       -I -S -B -X utf8 -c RUNNER_SOURCE
# It reads {"code", "input"} as JSON on stdin and writes the JSON result dict
# to the file descriptor that was fd 1 at start-up (the "result channel").
_RUNNER_MAIN = r'''
import builtins as _builtins
import importlib
import json
import os
import resource
import sys
import traceback

# Resource ceilings, applied after this process has already dropped to the
# per-run uid. The parent still enforces a wall-clock timeout; these bound CPU,
# memory, spawning and disk regardless of it.
_CPU_SECONDS = 25
_ADDRESS_SPACE = 1024 * 1024 * 1024  # 1 GiB
_MODULE_TYPE = type(os)


def _lower_limit(kind, value):
    # Only ever lower a limit, never raise it past the inherited hard limit.
    # A failure here aborts the run: weaker containment is not acceptable.
    _soft, hard = resource.getrlimit(kind)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    resource.setrlimit(kind, (value, value))


def _set_limits():
    _lower_limit(resource.RLIMIT_CPU, _CPU_SECONDS)
    _lower_limit(resource.RLIMIT_AS, _ADDRESS_SPACE)
    _lower_limit(resource.RLIMIT_FSIZE, 0)
    _lower_limit(resource.RLIMIT_NPROC, 1)


class _ModuleProxy:
    """Read-only view over an allowlisted module.

    Hides dunder / underscore attributes and nested submodules. This is attack
    surface reduction, not the security boundary; the boundary is the jail.
    """

    def __init__(self, module):
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(object.__getattribute__(self, "_module"), name)
        if isinstance(value, _MODULE_TYPE):
            raise AttributeError(name)
        return value

    def __setattr__(self, name, value):
        raise AttributeError("module proxy is read-only")

    def __repr__(self):
        return "<module %r>" % object.__getattribute__(self, "_module").__name__


def _build_proxies():
    proxies = {}
    for name in ALLOWED_MODULES:
        proxies[name] = _ModuleProxy(importlib.import_module(name))
    return proxies


def _make_import(proxies):
    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0:
            raise ImportError("relative import is not allowed")
        if "." in name or name not in proxies:
            raise ImportError("import of %r is not allowed" % name)
        return proxies[name]

    return _restricted_import


def _run():
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw.decode("utf-8"))
    user_code = payload["code"]
    user_input = payload.get("input") or {}

    _set_limits()
    validate(user_code)

    # Preserve the result channel (fd 1 at start-up), then redirect stdout to
    # stderr so user prints cannot forge or corrupt the result.
    result_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    proxies = _build_proxies()
    safe_builtins = {}
    for bname in SAFE_BUILTIN_NAMES:
        if hasattr(_builtins, bname):
            safe_builtins[bname] = getattr(_builtins, bname)
    safe_builtins["__import__"] = _make_import(proxies)

    sandbox_globals = {"__builtins__": safe_builtins, "__name__": "__main__"}
    sandbox_globals.update(proxies)

    compiled = compile(user_code, "<code-node>", "exec")
    exec(compiled, sandbox_globals)

    main = sandbox_globals.get("main")
    if not callable(main):
        raise RuntimeError("main function is required")

    result = main(**user_input)
    if not isinstance(result, dict):
        raise RuntimeError("main function output must be dict")

    data = json.dumps(result, ensure_ascii=False).encode("utf-8")
    view = memoryview(data)
    while view:
        written = os.write(result_fd, view)
        view = view[written:]
    os.close(result_fd)


try:
    _run()
except BaseException:
    traceback.print_exc()
    sys.exit(1)
sys.exit(0)
'''

# The complete program passed to the jailed interpreter via ``-c``.
RUNNER_SOURCE = _CHECKER_SOURCE + "\n" + _RUNNER_MAIN


class CodeParser:
    """Static gate over a code node's source.

    Kept name-compatible with the original class so ``code.py`` can construct it
    the same way, but it no longer imports or executes anything: ``parse_code``
    only runs the AST allowlist check.
    """

    def __init__(self, code: Union[str, type]) -> None:
        if isinstance(code, type):
            if not inspect.isclass(code):
                raise ValueError("The provided code must be a class.")
            code = inspect.getsource(code)
        self.code = code

    def parse_code(self) -> dict:
        """Validate the source. Raise CodeRejected if it is not allowed."""
        validate(self.code)  # noqa: F821 - provided by _CHECKER_SOURCE exec
        return {"validated": True}
