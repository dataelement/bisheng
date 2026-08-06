"""Background processes must install the F048 resource registry, not just the runtime.

Production defect (2026-08-05): Celery and the Linsight worker bootstrapped via
``initialize_f048_background_runtime``, which composes the business-INDEPENDENT
runtime and therefore leaves ``_resource_registry`` unset. The first business
permission check in those processes then raised::

    RuntimeError: F048 resource registry is not configured

reached through ``ToolExecutor.init_by_tool_id`` ->
``_ensure_use_permission_async`` -> ``check_business_action`` ->
``get_f048_resource_registry()``. In Linsight that exception landed inside a
best-effort ``except`` around the code-interpreter init, so every task-mode run
silently dropped the code interpreter the user had selected (observed: a run that
picked the ``docx`` skill, wrote the docx-js script the skill prescribes, then had
no way to execute it). ``init_by_tool_ids`` has no such guard, so any other tool
selection failed the task outright.

These tests pin that background processes install the SAME resource composition
the API does — only the HTTP wiring (catalog / decision / resource APIs) is API-only.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.api.services import f048_permission_runtime as runtime_module
from bisheng.permission.application.resource_authorization import (
    ResourceAuthorizationRegistry,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Every process that runs business code (tool init, resource checks).
BACKGROUND_ENTRYPOINTS = (
    BACKEND_ROOT / "bisheng" / "linsight" / "worker.py",
    BACKEND_ROOT / "bisheng" / "worker" / "main.py",
)


class _PermissionFacade:
    async def get_permission_version(self, **kwargs):
        return 1, "permission-context"

    async def mode_for_target(self, target):
        return SimpleNamespace(mode="CUSTOM")


async def test_worker_runtime_installs_the_resource_registry(monkeypatch):
    facade = _PermissionFacade()
    components = SimpleNamespace(facade=facade, state=object(), projection=object(), marker=object())

    async def _background(client, *, external_scopes):
        assert external_scopes == {"department": "scope"}
        return components

    captured: dict = {}

    def _configure(runtime, *, resource_adapters=None, resource_registry=None):
        captured["runtime"] = runtime
        captured["adapters"] = resource_adapters
        captured["registry"] = resource_registry

    monkeypatch.setattr(runtime_module, "initialize_f048_background_runtime", _background)
    monkeypatch.setattr(runtime_module, "configure_f048_runtime", _configure)
    monkeypatch.setattr(runtime_module, "configure_linsight_skill_owner_projection", lambda *a, **k: None)

    out = await runtime_module.initialize_f048_worker_runtime(
        object(),
        external_scopes={"department": "scope"},
    )

    assert out is components
    assert captured["runtime"] is facade
    assert isinstance(captured["registry"], ResourceAuthorizationRegistry)
    # "tool" is the resource type ToolExecutor checks before binding a tool — the
    # one whose absence disabled the Linsight code interpreter.
    assert "tool" in captured["adapters"]


def test_resource_composition_covers_every_checked_resource_type():
    """The shared composition must register each type business code checks."""
    adapters, registry = runtime_module.build_f048_resource_composition(_PermissionFacade())

    expected = {
        "workflow",
        "assistant",
        "channel",
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "tool",
        "dashboard",
    }
    assert expected <= set(adapters)
    # Re-registering raises, which is the cheapest proof each type is already bound
    # in the returned registry.
    for resource_type in expected:
        with pytest.raises(ValueError):
            registry.register(resource_type, object())


@pytest.mark.parametrize("path", BACKGROUND_ENTRYPOINTS, ids=lambda p: p.name)
def test_background_entrypoints_use_the_worker_composition_root(path):
    """Guard: a process running business code must not bootstrap the bare runtime.

    Calling ``initialize_f048_background_runtime`` directly is what left the
    registry unset; the wrapper is the only correct entry for these processes.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "initialize_f048_worker_runtime" in called, f"{path.name} must bootstrap via the worker composition root"
    assert "initialize_f048_background_runtime" not in called, (
        f"{path.name} calls the bare background runtime — business permission checks will raise "
        '"F048 resource registry is not configured"'
    )
