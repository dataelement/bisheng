"""覆盖 AC: AC-15、AC-36、AC-37、AC-43、AC-48. Backend-only owner signatures."""

import importlib.util
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment, RuntimeOperation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.common.errcode.app_factory import AppDataBusyError, AppDataForbiddenError
from bisheng.database.models.app import App
from test.app_runtime.test_runtime_data_sessions import UID
from test.app_runtime.test_runtime_data_sessions import repo as repo
from test.app_runtime.test_runtime_data_sessions import session as session

KEY = Ed25519PrivateKey.from_private_bytes(b"d" * 32)
KEYS = {"active_key_id": "data-key", "private_keys": {"data-key": "64" * 32}}


@pytest.fixture
async def signed_session(session, request):
    c = session
    async with c.repo.transaction() as db:
        connection = await db.connection()
        await connection.run_sync(App.__table__.create)
    await c.repo.save(
        App(id=c.app.id, slug="fixture-app", name="fixture", owner_user_id=1, tenant_id=1, state="stopped")
    )
    action, parameters = getattr(request, "param", ("tables", {}))
    op = await c.svc._start(c.app, c.actor, action, parameters)
    op.status, op.stage = "running", "ready"
    await c.repo.save(op)
    target = await c.repo.save(
        RuntimeExecutionResource(
            tenant_id=1,
            app_id=c.app.id,
            operation_id=op.id,
            node_id=op.node_id,
            cluster_id="cluster-a",
            namespace="namespace-a",
            name="app-a",
            uid=UID,
            kind="Pod",
            purpose="data",
            generation=op.generation,
            owner_epoch=op.owner_epoch,
            controller_epoch=1,
            spec_digest="a" * 64,
            status_policy_revision="v1",
        )
    )
    c.op, c.target = op, {"exec_ref": target.id, "pod_uid": target.uid, "online": False, "key_ids": ["data-key"]}
    from bisheng.app_runtime.domain.services.runtime_data_grant_service import RuntimeDataGrantService

    c.issuer = RuntimeDataGrantService(c.repo, keyring=KEYS)
    return c


async def test_signature_is_accepted_by_the_independent_runtime_verifier(signed_session):
    c = signed_session
    ticket = await c.issuer.issue(c.app, c.actor, c.op, c.target, "tables", {})
    path = Path(__file__).resolve().parents[3] / "runtime-manager/runtime_manager/data_grant.py"
    spec = importlib.util.spec_from_file_location("f059_independent_data_grant", path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    public = KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    claims = verifier.verify_grant(
        ticket,
        {},
        {"data-key": public},
        app_id=c.app.id,
        exec_ref=c.target["exec_ref"],
        pod_uid=UID,
        now=ticket["claims"]["issued_at"],
    )
    assert claims["not_after"] - claims["issued_at"] <= 5
    assert claims["deadline"] <= int(c.op.deadline.replace(tzinfo=UTC).timestamp())
    stored = await c.repo.get(RuntimeOperation, c.op.id)
    assert stored.payload["data_grant_not_after"] == claims["not_after"]
    assert "private_key" not in str(ticket) and claims["actor_ref"] == "user:1"


async def test_fresh_owner_recheck_blocks_transferred_apps(signed_session):
    c = signed_session
    app = await c.repo.get_application(c.app.id)
    app.owner_user_id = 2
    await c.repo.save(app)
    with pytest.raises(AppDataForbiddenError):
        await c.issuer.issue(c.app, c.actor, c.op, c.target, "tables", {})


@pytest.mark.parametrize(
    "mutation", ["uid", "node", "generation", "mutex", "action", "parameters", "finished", "key_not_projected"]
)
async def test_stale_or_widened_session_cannot_get_signed(signed_session, mutation):
    c = signed_session
    action, parameters = "tables", {}
    if mutation == "uid":
        c.target["pod_uid"] = str(uuid4())
    elif mutation == "key_not_projected":
        c.target["key_ids"] = ["other"]
    elif mutation in {"node", "generation"}:
        row = await c.repo.get(RuntimeExecutionResource, c.target["exec_ref"])
        if mutation == "node":
            row.node_id = "other"
        else:
            row.generation += 1
        await c.repo.save(row)
    elif mutation == "mutex":
        owner = await c.repo.get(RuntimeAssignment, c.owner.id)
        owner.data_operation_id = str(uuid4())
        await c.repo.save(owner)
    elif mutation == "action":
        action = "update"
    elif mutation == "parameters":
        parameters = {"table": "other"}
    elif mutation == "finished":
        c.op.payload = {**c.op.payload, "data_action_finished": "unknown"}
        await c.repo.save(c.op)
    with pytest.raises(AppDataBusyError):
        await c.issuer.issue(c.app, c.actor, c.op, c.target, action, parameters)


async def test_readonly_public_keys_never_expose_signing_material(signed_session):
    document = signed_session.issuer.public_keys()
    assert set(document) == {"data-key"}
    assert document["data-key"] != KEYS["private_keys"]["data-key"]


@pytest.mark.parametrize(
    "signed_session",
    [("update", {"table": "items", "key": "1", "values": {"name": "new"}})],
    indirect=True,
)
@pytest.mark.parametrize("cancelled", [False, True])
async def test_owner_cancellation_blocks_fresh_grants_without_releasing_the_session(signed_session, cancelled):
    """覆盖 AC: AC-36、AC-43、AC-48、AC-49、AC-55."""
    from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService

    c = signed_session
    parameters = {"table": "items", "key": "1", "values": {"name": "new"}}
    original_deadline = c.op.deadline
    if cancelled:
        outcome = await RuntimeManagementService(c.repo, objects=object()).cancel(c.app.id, c.op.id, c.actor)
        assert outcome == {"operation_id": c.op.id, "cancel_requested": True}
        assert "cancel_requested" not in c.op.payload  # The caller still has the pre-cancel snapshot.
        with pytest.raises(AppDataBusyError):
            await c.issuer.issue(c.app, c.actor, c.op, c.target, "update", parameters)
    else:
        ticket = await c.issuer.issue(c.app, c.actor, c.op, c.target, "update", parameters)
        assert ticket["claims"]["action"] == "update"
        assert ticket["claims"]["not_after"] <= int(original_deadline.replace(tzinfo=UTC).timestamp())
    current = await c.repo.get(RuntimeOperation, c.op.id)
    owner = await c.repo.get(RuntimeAssignment, c.owner.id)
    assert current.deadline == original_deadline
    assert (current.status, current.stage, current.cleanup_status) == ("running", "ready", "pending")
    assert owner.data_operation_id == current.id
    if cancelled:
        assert current.payload["cancel_requested"] is True
        assert "data_grant_not_after" not in current.payload
