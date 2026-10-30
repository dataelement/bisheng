"""System recovery proves the current approved intent, without a historical user."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError


@pytest.fixture
def recovery():
    from bisheng.app_runtime.domain.models.runtime_delivery import (
        RuntimeDelivery,
        RuntimeExecutionFact,
        RuntimeOperation,
        RuntimeRoute,
    )
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService as Policy
    from bisheng.app_runtime.domain.services.runtime_protocol import content_digest

    app = SimpleNamespace(id="target", tenant_id=3, state="online", current_version_id="approved")
    route = SimpleNamespace(
        id="route",
        operation_id="old",
        version_id="approved",
        node_id="node",
        exec_ref="exec",
        generation=1,
        owner_epoch=1,
        route_epoch=4,
        status="serving",
        app_id=app.id,
        tenant_id=3,
    )
    content = {"mode": "bundle", "profile": {"digest": "fixed"}}
    delivery = SimpleNamespace(content=content, delivery_digest=content_digest(content))
    old = SimpleNamespace(
        id="old",
        tenant_id=3,
        app_id=app.id,
        version_id="approved",
        kind="deploy",
        request_digest="a" * 64,
        payload={"resolved_delivery": content},
    )
    op = SimpleNamespace(
        id="new",
        tenant_id=3,
        app_id=app.id,
        version_id="approved",
        node_id="node",
        generation=2,
        owner_epoch=1,
        payload={"resolved_delivery": content},
        kind="deploy",
    )
    observation = {
        "node_id": "node",
        "key_id": "manager",
        "operation_id": "old",
        "exec_ref": "exec",
        "generation": 1,
        "owner_epoch": 1,
        "route_epoch": 4,
    }
    context = Policy.capture_system(app, route, old, delivery, observation)
    op.payload["authorization_context"] = context

    async def get(model, key, **_):
        return old if model is RuntimeOperation and key == "old" else None

    async def find(model, **_):
        if model is RuntimeDelivery:
            return [delivery]
        if model is RuntimeRoute:
            return [route]
        if model is RuntimeExecutionFact:
            return [SimpleNamespace(sequence=9, phase="maintenance", node_id="node", generation=2, owner_epoch=1)]
        return []

    repo = SimpleNamespace(get=AsyncMock(side_effect=get), find=AsyncMock(side_effect=find))
    return Policy, app, route, old, op, context, repo


async def test_native_serving_source_needs_no_historical_actor(recovery):
    policy, app, _route, _old, op, context, repo = recovery
    assert "actor" not in context and "credential_ref" not in context
    await policy.validate_system(context, app, op, repo)


async def test_only_own_precise_maintenance_transition_is_accepted(recovery):
    policy, app, route, _old, op, context, repo = recovery
    before = policy.route_snapshot(route)
    route.status = "maintenance"
    route.route_epoch += 1
    with pytest.raises(PermissionDeniedError):
        await policy.validate_system(context, app, op, repo)
    op.payload["maintenance_transition"] = {
        "operation_id": op.id,
        "generation": 2,
        "owner_epoch": 1,
        "fact_sequence": 9,
        "before": before,
        "after": policy.route_snapshot(route),
    }
    await policy.validate_system(context, app, op, repo)
    op.payload["maintenance_transition"]["operation_id"] = "other"
    with pytest.raises(PermissionDeniedError):
        await policy.validate_system(context, app, op, repo)


@pytest.mark.parametrize("change", ["stop", "version", "delivery", "route", "source"])
async def test_superseded_or_unproven_recovery_is_denied(recovery, change):
    policy, app, route, old, op, context, repo = recovery
    if change == "stop":
        app.state = "stopped"
    elif change == "version":
        app.current_version_id = "other"
    elif change == "delivery":
        op.payload["resolved_delivery"] = {"mode": "changed"}
    elif change == "route":
        route.exec_ref = "other"
    elif change == "source":
        old.request_digest = "changed"
    with pytest.raises(PermissionDeniedError):
        await policy.validate_system(context, app, op, repo)
