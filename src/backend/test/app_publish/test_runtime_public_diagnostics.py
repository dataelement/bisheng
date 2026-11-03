"""F119 覆盖 AC: AC-21, AC-22, AC-24, AC-25, AC-26: authority, association and expiry."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize(
    "kind,stage,status,code",
    [
        ("prepare", "preparing", "failed", 16227),
        ("probe", "starting", "failed", 16228),
        ("preview", "starting", "failed", 16228),
        ("deploy", "starting", "failed", 16228),
        ("deploy", "migrating", "failed", 16124),
        ("restore", "snapshot_confirmed", "failed", 16124),
        ("prepare", "preparing", "cancelled", 16124),
        ("deploy", "ready", "timed_out", 16124),
    ],
)
def test_only_actual_startup_failures_use_startup_code(kind, stage, status, code):
    from bisheng.app_runtime.domain.services.runtime_public_diagnostics import runtime_failure_error

    op = SimpleNamespace(
        id="op",
        kind=kind,
        stage="failed",
        status=status,
        failure={
            "reason": "startup_exited",
            "failed_stage": stage,
            "maintenance": True,
            "data_may_have_changed": True,
            "diagnostic_tail": "must not escape",
            "payload": {"private": "secret"},
        },
    )
    error = runtime_failure_error(op)
    assert error.code == code
    assert error.kwargs["details"]["maintenance"] is True
    assert error.kwargs["details"]["data_may_have_changed"] is True
    assert not {"tail", "diagnostic_tail", "payload"} & error.kwargs["details"].keys()


@pytest.mark.parametrize("changed", ["none", "expired", "tenant", "app", "version", "deployment", "missing"])
async def test_publish_reader_checks_expiry_and_exact_association_before_returning_tail(monkeypatch, changed):
    from bisheng.app_runtime.application import authorization, publish_diagnostics

    auth = AsyncMock()
    monkeypatch.setattr(authorization, "authorize_app", auth)
    now = datetime.utcnow()
    op = SimpleNamespace(
        id="op",
        tenant_id=3,
        app_id="app",
        version_id="version",
        deployment_id="deployment",
        diagnostics_until=now + timedelta(days=1),
        failure={"diagnostic_tail": "safe output"},
    )
    if changed == "expired":
        op.diagnostics_until = now
    if changed == "tenant":
        op.tenant_id = 4
    if changed == "app":
        op.app_id = "other"
    if changed == "version":
        op.version_id = "other"
    if changed == "deployment":
        op.deployment_id = "other"
    repository = SimpleNamespace(
        get=AsyncMock(return_value=None if changed == "missing" else op),
        get_application=AsyncMock(return_value=SimpleNamespace(id="app", tenant_id=3)),
    )
    deployment = SimpleNamespace(
        id="deployment",
        app_id="app",
        tenant_id=3,
        version_id="version",
        failure={"code": 16228, "details": {"operation_id": "op", "tail": ["stale copy"]}},
    )
    result = await publish_diagnostics.publish_failure(deployment, actor="actor", repository=repository, now=now)
    assert result["details"]["tail"] == (["safe output"] if changed == "none" else [])
    assert result["details"]["diagnostics_available"] is (changed == "none")
    assert deployment.failure["details"]["tail"] == ["stale copy"]
    auth.assert_awaited_once_with("actor", "app", "log_read")


async def test_publish_only_caller_is_denied_before_operation_read(monkeypatch):
    from bisheng.app_runtime.application import authorization, publish_diagnostics

    monkeypatch.setattr(authorization, "authorize_app", AsyncMock(side_effect=PermissionError("edit required")))
    repo = SimpleNamespace(get=AsyncMock(), get_application=AsyncMock())
    with pytest.raises(PermissionError):
        await publish_diagnostics.publish_failure(
            SimpleNamespace(app_id="app", failure={"details": {"operation_id": "op"}}),
            actor="publish-only",
            repository=repo,
        )
    repo.get.assert_not_awaited()


def test_long_lived_failure_never_copies_nested_diagnostics():
    from bisheng.app_runtime.domain.services.runtime_public_diagnostics import stored_failure

    before = {
        "code": 16228,
        "details": {
            "tail": ["private"],
            "diagnostic_tail": "private",
            "operation_id": "op",
            "nested": {"tail": "private"},
        },
        "diagnostic_tail": "private",
    }
    result = stored_failure(before)
    assert result == {"code": 16228, "details": {"operation_id": "op", "nested": {}}}
    assert before["details"]["tail"] == ["private"]


@pytest.mark.parametrize(
    "reference", ["registry.invalid/runtime@sha256:" + "a" * 64, "https://user:password@private.invalid/image"]
)
def test_missing_image_context_is_safe_and_points_to_the_exact_material(reference):
    from bisheng.app_runtime.domain.services.runtime_public_diagnostics import runtime_failure_error

    op = SimpleNamespace(
        id="op",
        kind="prepare",
        stage="failed",
        status="failed",
        failure={"reason": "image_missing", "image_role": "runtime", "image_ref": reference},
    )
    error = runtime_failure_error(op)
    if reference.startswith("https"):
        assert "image_ref" not in error.kwargs["details"]
        assert "password" not in str(error.kwargs)
    else:
        assert error.kwargs["details"]["image_ref"] == reference
        assert any(reference in hint for hint in error.kwargs["hints"])


async def test_pipeline_storage_and_audit_strip_logs_even_when_an_exception_supplies_them(monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.app_publish.domain.services import publish_pipeline_service as module
    from bisheng.common.errcode.app_publish import AppStartupProbeFailedError

    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def database():
        yield session

    failed, audit = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module, "get_async_db_session", database)
    monkeypatch.setattr(module.AppDeploymentDao, "aset_failed", failed)
    monkeypatch.setattr(module, "write_release_audit", audit)
    deployment = SimpleNamespace(id="deployment", app_id="app", stage="precheck_probe")
    error = AppStartupProbeFailedError(
        details={"operation_id": "op", "tail": ["private"], "diagnostic_tail": "private"}
    )
    await module.PublishPipelineService._fail(deployment, error)
    assert failed.await_args.kwargs["failure"]["details"] == {"operation_id": "op"}
    assert "private" not in str(audit.await_args.kwargs)


@pytest.mark.parametrize("expired", [False, True])
def test_runtime_management_read_enforces_expiry_without_waiting_for_purge(expired):
    from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService

    row = SimpleNamespace(
        failure={"reason": "startup_exited", "diagnostic_tail": "retained output"},
        diagnostics_until=datetime.utcnow() + timedelta(days=-1 if expired else 1),
    )
    failure = RuntimeManagementService._retained_failure(row)
    assert ("diagnostic_tail" in failure) is not expired
    assert row.failure["diagnostic_tail"] == "retained output"


@pytest.mark.parametrize("recovered", [False, True])
async def test_prepare_failure_classification_is_identical_for_new_and_recovered_operations(recovered):
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.common.errcode.app_publish import AppDependencyBuildFailedError

    op = SimpleNamespace(
        id="op",
        kind="prepare",
        status="failed",
        stage="failed",
        payload={"platform": "linux/amd64"},
        failure={"reason": "image_missing", "failed_stage": "preparing"},
    )

    class Repository:
        async def find(self, model, **kwargs):
            return [op] if recovered and model is RuntimeOperation else []

        async def get(self, model, ident):
            return op

        async def get_application(self, ident):
            return SimpleNamespace(id=ident, tenant_id=3, slug="example")

    class Coordinator(RuntimeDeliveryCoordinator):
        async def node(self, app):
            return SimpleNamespace(platform="linux/amd64", executor_kind="docker"), None

        async def source(self, deployment):
            return SimpleNamespace(id="source")

        async def submit(self, *args, **kwargs):
            return op

        async def wake(self, operation):
            pass

    deployment = SimpleNamespace(id="d", tenant_id=3, app_id="a", version_id="v", authorization_context={})
    manifest = AppManifest.model_validate(
        {
            "manifest_version": 2,
            "name": "sample",
            "runtime": "custom-image",
            "port": 8080,
            "delivery": {"mode": "image", "image": "registry.invalid/app@sha256:" + "a" * 64},
        }
    )
    with pytest.raises(AppDependencyBuildFailedError) as caught:
        await Coordinator(Repository()).prepare(
            deployment, manifest, SimpleNamespace(memory_mb=512, cpu_millicores=250)
        )
    assert caught.value.code == 16227
    assert caught.value.kwargs["details"]["reason"] == "image_missing"
