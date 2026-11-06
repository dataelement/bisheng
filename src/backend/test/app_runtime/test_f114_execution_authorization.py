"""Frozen origins contain references only and are revalidated before each effect."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.identity import PermissionActor
from test.app_runtime import test_runtime_delivery_repository as ledger_tests

runtime_repo = ledger_tests.runtime_repo


@pytest.fixture
def origin(monkeypatch):
    from bisheng.app_runtime.domain.services import runtime_authorization_service as mod

    app = SimpleNamespace(id="target", tenant_id=3, owner_user_id=81, state="online", current_version_id="approved")
    actor = SimpleNamespace(
        user_id=42,
        tenant_id=3,
        token_version=7,
        _runtime_credential_reference={
            "kind": "web_session",
            "tenant_id": 3,
            "user_id": 42,
            "token_version": 7,
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )
    monkeypatch.setattr(
        mod.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_id=42, tenant_id=3)),
    )
    monkeypatch.setattr(mod, "get_current_open_api_principal", lambda: None)
    monkeypatch.setattr(mod.AppAuthorizationService, "authorize_loaded_app", AsyncMock(return_value=app))
    return mod, app, actor


async def test_capture_is_not_a_permanent_allow_or_owner_impersonation(origin):
    mod, app, actor = origin
    context = await mod.RuntimeAuthorizationService.capture_user(actor, app, "config_restart", version_id="approved")
    assert context["actor"]["subject_id"] == 42
    assert context["self_review_user_id"] == 42
    assert context["target"] == {"tenant_id": 3, "app_id": "target", "version_id": "approved"}
    assert set(context["required_actions"]) == {"edit", "publish"}
    assert "token" not in repr(context).replace("token_version", "")
    assert "allowed" not in context


async def test_missing_web_reference_cannot_create_delayed_authority(origin):
    mod, app, actor = origin
    actor._runtime_credential_reference = None
    with pytest.raises(PermissionDeniedError):
        await mod.RuntimeAuthorizationService.capture_user(actor, app, "approved_start", version_id="approved")


async def test_current_actions_are_rechecked_after_freezing(origin, monkeypatch):
    mod, app, actor = origin
    context = await mod.RuntimeAuthorizationService.capture_user(actor, app, "config_restart", version_id="approved")
    monkeypatch.setattr(mod, "resolve_web_runtime_identity", AsyncMock(return_value=actor))
    mod.AppAuthorizationService.authorize_loaded_app.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await mod.RuntimeAuthorizationService.validate_user(context, app, version_id="approved")


@pytest.mark.parametrize(
    "mutation", [{"schema": 2}, {"origin_kind": "system_recovery"}, {"required_actions": []}, {"purpose": "unknown"}]
)
async def test_unknown_or_tampered_user_context_is_denied(origin, mutation):
    mod, app, actor = origin
    context = await mod.RuntimeAuthorizationService.capture_user(actor, app, "config_restart", version_id="approved")
    context.update(mutation)
    with pytest.raises(PermissionDeniedError):
        await mod.RuntimeAuthorizationService.validate_user(context, app, version_id="approved")


async def test_maintenance_denial_has_no_route_or_fact_side_effect(runtime_repo, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeExecutionFact, RuntimeOperation, RuntimeRoute
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    repo = runtime_repo
    op = await repo.save(
        RuntimeOperation(
            id="new",
            tenant_id=1,
            app_id="target",
            scope_key="1/target",
            idempotency_key="new",
            request_digest="a" * 64,
            kind="deploy",
            node_id="node-a",
            deadline=datetime.utcnow() + timedelta(minutes=2),
            payload={},
        )
    )
    await repo.save(
        RuntimeRoute(
            id="route",
            tenant_id=1,
            app_id="target",
            route_key="app:target",
            operation_id="old",
            version_id="approved",
            node_id="node-a",
            exec_ref="old-exec",
            generation=1,
            owner_epoch=1,
            status="serving",
        )
    )
    monkeypatch.setattr(
        RuntimeAuthorizationService, "validate_operation", AsyncMock(side_effect=PermissionDeniedError())
    )
    svc = RuntimeOperationService(repo)
    identity = SimpleNamespace(node_id="node-a", roles=("manager",), key_id="manager")
    body = ExecutionFactInput(sequence=1, node_id="node-a", generation=1, owner_epoch=1, phase="maintenance")
    with pytest.raises(RuntimeConflict, match="authorization"):
        await svc.fact(op, identity, body)
    route = (await repo.find(RuntimeRoute, route_key="app:target"))[0]
    assert route.status == "serving" and route.route_epoch == 1
    assert await repo.find(RuntimeExecutionFact, operation_id=op.id) == []


async def test_maintenance_fact_replay_has_no_second_projection(runtime_repo, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute
    from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    repo = runtime_repo
    op = await repo.save(
        RuntimeOperation(
            id="new",
            tenant_id=1,
            app_id="target",
            scope_key="1/target",
            idempotency_key="new",
            request_digest="a" * 64,
            kind="deploy",
            node_id="node-a",
            deadline=datetime.utcnow() + timedelta(minutes=2),
            payload={},
        )
    )
    await repo.save(
        RuntimeRoute(
            id="route",
            tenant_id=1,
            app_id="target",
            route_key="app:target",
            operation_id="old",
            version_id="approved",
            node_id="node-a",
            exec_ref="old-exec",
            generation=1,
            owner_epoch=1,
            status="serving",
        )
    )
    validate = AsyncMock()
    monkeypatch.setattr(RuntimeAuthorizationService, "validate_operation", validate)
    svc = RuntimeOperationService(repo)
    identity = SimpleNamespace(node_id="node-a", roles=("manager",), key_id="manager")
    body = ExecutionFactInput(sequence=1, node_id="node-a", generation=1, owner_epoch=1, phase="maintenance")
    first = await svc.fact(op, identity, body)
    validate.side_effect = PermissionDeniedError()
    again = await svc.fact(op, identity, body)
    assert first == again
    route = (await repo.find(RuntimeRoute, route_key="app:target"))[0]
    assert route.status == "maintenance" and route.route_epoch == 2
    validate.assert_awaited_once()


@pytest.mark.parametrize("kind,allowed", [("probe", True), ("preview", True), ("deploy", False)])
async def test_admitted_ephemeral_start_does_not_skip_formal_maintenance(runtime_repo, monkeypatch, kind, allowed):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode, RuntimeOperation
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    node = await runtime_repo.get(RuntimeNode, "node-a")
    node.status = "ready"
    await runtime_repo.save(node)
    op = RuntimeOperation(
        id="admitted",
        tenant_id=1,
        app_id="target",
        scope_key="1/target",
        idempotency_key="start",
        request_digest="a" * 64,
        kind=kind,
        node_id="node-a",
        stage="admitted",
        status="running",
        deadline=datetime.utcnow() + timedelta(minutes=1),
        payload={},
    )
    monkeypatch.setattr(RuntimeAuthorizationService, "validate_operation", AsyncMock())
    service = RuntimeOperationService(runtime_repo)
    identity = SimpleNamespace(node_id="node-a", roles=("manager",), key_id="manager")
    if allowed:
        await service._authorize_effect(op, identity, "starting")
    else:
        with pytest.raises(RuntimeConflict, match="phase"):
            await service._authorize_effect(op, identity, "starting")
