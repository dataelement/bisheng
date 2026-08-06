"""F048 Celery single-model and tenant-context runtime contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.openfga.worker_runtime import ensure_worker_fga_runtime
from bisheng.permission.application.process_runtime import (
    bind_f048_process_runtime,
)


def _load_tenant_context():
    module_path = Path(__file__).parents[2] / "bisheng" / "worker" / "tenant_context.py"
    spec = importlib.util.spec_from_file_location(
        "f048_worker_tenant_context_under_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_tenant_context = _load_tenant_context()
PermissionTaskTenantContextError = _tenant_context.PermissionTaskTenantContextError
inject_tenant_header = _tenant_context.inject_tenant_header
reset_tenant_context = _tenant_context.reset_tenant_context
restore_tenant_context = _tenant_context.restore_tenant_context


class _Manager:
    def __init__(self, readiness, *, healthy=True) -> None:
        self._readiness = readiness
        self.healthy = healthy
        self.initialized = 0
        self.heartbeats = 0

    async def async_get_instance(self):
        self.initialized += 1
        return object()

    async def heartbeat(self):
        self.heartbeats += 1
        return self.healthy

    def readiness(self):
        return self._readiness


class _BindingManager(_Manager):
    def __init__(self, readiness, *, healthy=True) -> None:
        super().__init__(readiness, healthy=healthy)
        self.bound = []

    async def bind_catalog_runtime(
        self,
        resolver,
    ):
        self.bound.append(resolver)


class _PermissionRuntime:
    async def current_catalog(self):
        return object()


def _ready() -> dict:
    return {
        "ready": True,
        "store_id": "store-live",
        "model_id": "model-f048",
        "model_checksum": "a" * 64,
        "catalog_release_id": 9,
        "catalog_checksum": "b" * 64,
        "instance_role": "celery",
    }


@pytest.mark.asyncio
async def test_worker_requires_one_complete_f048_runtime_pin() -> None:
    manager = _Manager(_ready())

    readiness = await ensure_worker_fga_runtime(manager)

    assert readiness["store_id"] == "store-live"
    assert readiness["model_id"] == "model-f048"
    assert manager.initialized == manager.heartbeats == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "readiness",
    (
        {**_ready(), "model_id": ""},
        {**_ready(), "catalog_release_id": None},
        {**_ready(), "ready": False},
        {**_ready(), "instance_role": "api"},
    ),
)
async def test_worker_rejects_missing_or_mismatched_runtime_pin(readiness) -> None:
    with pytest.raises(RuntimeError, match="F048 OpenFGA runtime"):
        await ensure_worker_fga_runtime(_Manager(readiness))

    with pytest.raises(RuntimeError, match="F048 OpenFGA runtime"):
        await ensure_worker_fga_runtime(_Manager(_ready(), healthy=False))


@pytest.mark.asyncio
async def test_process_binding_registers_dynamic_catalog_before_heartbeat() -> None:
    manager = _BindingManager(_ready())
    runtime = _PermissionRuntime()

    readiness = await bind_f048_process_runtime(
        manager,
        runtime,
    )

    assert readiness == _ready()
    assert manager.bound == [runtime.current_catalog]
    assert manager.heartbeats == 1


@pytest.mark.asyncio
async def test_process_binding_fails_closed_when_initial_heartbeat_fails() -> None:
    manager = _BindingManager(_ready(), healthy=False)

    with pytest.raises(RuntimeError, match="heartbeat"):
        await bind_f048_process_runtime(
            manager,
            _PermissionRuntime(),
        )


def test_permission_publish_writes_current_tenant_header() -> None:
    token = set_current_tenant_id(7)
    try:
        headers = {}
        inject_tenant_header(
            sender="bisheng.worker.permission.reconcile",
            headers=headers,
        )
    finally:
        current_tenant_id.reset(token)

    assert headers == {
        "tenant_id": 7,
        "f048_permission_task": True,
    }


def test_permission_publish_without_tenant_fails_closed() -> None:
    token = current_tenant_id.set(None)
    try:
        with pytest.raises(PermissionTaskTenantContextError):
            inject_tenant_header(
                sender="bisheng.worker.permission.reconcile",
                headers={},
            )
    finally:
        current_tenant_id.reset(token)


def test_legacy_failed_tuple_retry_remains_tenant_agnostic() -> None:
    task_name = "bisheng.worker.permission.retry_failed_tuples.retry_failed_tuples"
    token = current_tenant_id.set(None)
    try:
        headers = {}
        inject_tenant_header(sender=task_name, headers=headers)
        assert headers == {}

        sender = SimpleNamespace(
            name=task_name,
            request=SimpleNamespace(headers={}),
        )
        restore_tenant_context(sender=sender)
        assert get_current_tenant_id() == DEFAULT_TENANT_ID
        reset_tenant_context(sender=sender)
        assert get_current_tenant_id() is None
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("tenant_id", (None, 0, -1, "bad", True))
def test_permission_prerun_rejects_missing_or_invalid_tenant(tenant_id) -> None:
    headers = {"f048_permission_task": True}
    if tenant_id is not None:
        headers["tenant_id"] = tenant_id
    sender = SimpleNamespace(
        name="bisheng.worker.permission.reconcile",
        request=SimpleNamespace(headers=headers),
    )

    with pytest.raises(PermissionTaskTenantContextError):
        restore_tenant_context(sender=sender)
    assert get_current_tenant_id() is None


def test_permission_prerun_restores_and_postrun_resets_context() -> None:
    sender = SimpleNamespace(
        name="bisheng.worker.permission.reconcile",
        request=SimpleNamespace(
            headers={
                "f048_permission_task": True,
                "tenant_id": "8",
            }
        ),
    )

    restore_tenant_context(sender=sender)
    assert get_current_tenant_id() == 8
    reset_tenant_context(sender=sender)
    assert get_current_tenant_id() is None


def test_worker_runtime_does_not_register_data_migration_task() -> None:
    worker_root = Path(__file__).parents[2] / "bisheng" / "worker"
    source = "\n".join(path.read_text(encoding="utf-8") for path in worker_root.rglob("*.py"))
    assert "migrate_f048_permission_data" not in source
    assert "register_f048_permission_runtime_context" in source
    assert "while True:\n            time.sleep(_WORKER_BEAT_SLEEP)" not in source
