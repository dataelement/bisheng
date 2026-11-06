"""T546: native readers borrow an explicitly prepared process permission runtime.

覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89
Execute actual startup helpers with a no-I/O permission initializer double.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application import process_runtime
from bisheng.worker import _asyncio_utils

ROOT = Path(__file__).resolve().parents[2] / "bisheng"
HELPER = "_prepare_native_reference_permissions"


def helper(module, enabled):
    path = ROOT / module
    tree = ast.parse(path.read_text())
    function = next(
        (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == HELPER),
        None,
    )
    assert function is not None, "startup must explicitly prepare native reference permissions"
    namespace = {"settings": SimpleNamespace(openfga=SimpleNamespace(enabled=enabled))}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[HELPER]


@pytest.mark.parametrize("module", ["main.py", "worker/main.py"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_real_helpers_initialize_only_enabled_permission_runtime(monkeypatch, module, enabled):
    initialize = AsyncMock()
    monkeypatch.setattr(process_runtime, "get_f048_process_runtime", initialize)
    factories = []
    monkeypatch.setattr(_asyncio_utils, "run_async_task", lambda factory: factories.append(factory))
    prepare = helper(module, enabled)
    if module == "main.py":
        await prepare()
        assert initialize.await_count == int(enabled)
        assert factories == []
    else:
        prepare()
        assert factories == ([initialize] if enabled else [])
        initialize.assert_not_called()


@pytest.mark.parametrize("module", ["main.py", "worker/main.py"])
async def test_readiness_failure_is_not_swallowed_as_success(monkeypatch, module):
    error = RuntimeError("permission migration is not ready")
    monkeypatch.setattr(process_runtime, "get_f048_process_runtime", AsyncMock(side_effect=error))
    def fail(factory):
        raise error
    monkeypatch.setattr(_asyncio_utils, "run_async_task", fail)
    prepare = helper(module, True)
    with pytest.raises(RuntimeError) as raised:
        if module == "main.py":
            await prepare()
        else:
            prepare()
    assert raised.value is error


@pytest.mark.parametrize(
    "module,caller,register",
    [("main.py", "lifespan", "_register_permission_runtime_contexts"),
     ("worker/main.py", "on_worker_init", "_register_worker_permission_contexts")],
)
def test_prepare_is_called_before_business_composition_and_reception(module, caller, register):
    tree = ast.parse((ROOT / module).read_text())
    function = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == caller)
    calls = sorted(
        ((node.lineno, node.func.id) for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
    )
    names = [name for _, name in calls]
    assert HELPER in names
    assert names.index(register) < names.index(HELPER) < names.index("_register_resource_reference_composition")
