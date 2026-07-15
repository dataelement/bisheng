from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MISSING = object()


def _load_space_migrate_worker() -> ModuleType:
    stubs = {
        "bisheng.worker.main": SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda *args, **kwargs: lambda func: func),
        ),
    }
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in stubs}
    try:
        sys.modules.update(stubs)
        module_path = BACKEND_ROOT / "bisheng" / "worker" / "knowledge" / "space_migrate_worker.py"
        spec = importlib.util.spec_from_file_location("space_migrate_async_bridge_test", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


space_migrate_module = _load_space_migrate_worker()


def test_space_migrate_submits_delete_to_shared_bridge_without_timeout(monkeypatch) -> None:
    delete_source = AsyncMock()
    rollback = Mock()
    submitted: dict[str, object] = {}

    def _run_async_safe(coro, *, timeout):
        submitted["timeout"] = timeout
        coro.close()

    monkeypatch.setattr(space_migrate_module, "_do_migrate", Mock())
    monkeypatch.setattr(space_migrate_module, "_delete_source_space", delete_source)
    monkeypatch.setattr(space_migrate_module, "run_async_safe", _run_async_safe)
    monkeypatch.setattr(space_migrate_module.KnowledgeDao, "update_state", rollback)

    result = space_migrate_module.space_migrate_celery({"source_id": 1, "target_id": 2, "op_user_id": 5})

    assert result == "space migrate done"
    assert submitted == {"timeout": None}
    delete_source.assert_called_once_with(1, 5)
    rollback.assert_not_called()


def test_space_migrate_worker_has_no_transient_asyncio_run() -> None:
    source = inspect.getsource(space_migrate_module)

    assert "asyncio.run(" not in source
