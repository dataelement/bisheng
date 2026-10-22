"""覆盖 AC: AC-15、AC-27、AC-46、AC-47、AC-48. Material authority is independent of tickets."""

import hashlib
from datetime import UTC, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeDelivery,
    RuntimeNode,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource, RuntimeMaterialDelegation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_material_protocol import MaterialProtocolError, signed_headers
from bisheng.app_runtime.domain.services.runtime_protocol import ServiceIdentity, canonical_json, content_digest
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import MANAGER, REF, document
from test.app_runtime.test_runtime_kubernetes_service import control as control

P = "/internal/app-runtime/v2/material-access"
KEY_ID = "material-pod-a"


@pytest.fixture
async def materials(control):
    from bisheng.app_runtime.domain.services.runtime_material_service import RuntimeMaterialService

    control_svc, repository, op = control
    clock = {"now": NOW, "nonce_available": True}
    seen = set()
    app = SimpleNamespace(
        id=op.app_id, tenant_id=1, state="draft", current_version_id=None, pending_version_id="version-a"
    )
    previews = {}

    async def app_loader(app_id):
        return app if app_id == app.id else None

    async def preview_loader(session_id):
        return previews.get(session_id)

    async def nonce_store(key, ttl):
        assert ttl == 120
        if not clock["nonce_available"]:
            raise RuntimeError("fixture-secret-store-detail")
        if key in seen:
            return False
        seen.add(key)
        return True

    op.version_id = "version-a"
    op.deadline = NOW + timedelta(minutes=10)
    content = {**op.payload["resolved_delivery"]}
    for kind in ("compiled", "dependencies"):
        artifact = await repository.save(
            RuntimeArtifact(
                tenant_id=1,
                app_id=op.app_id,
                scope_key=f"1/{op.app_id}",
                kind=kind,
                sha256=hashlib.sha256(kind.encode()).hexdigest(),
                size_bytes=0,
                state="verified",
                confirmed_at=NOW,
                object_key="fixture/" + kind,
            )
        )
        key = "dependency_artifact_id" if kind == "dependencies" else "compiled_artifact_id"
        content[key] = artifact.id
    delivery = await repository.save(
        RuntimeDelivery(
            tenant_id=1,
            app_id=op.app_id,
            version_id=op.version_id,
            execution_mode="bundle",
            resolved_platform="linux/amd64",
            delivery_digest=content_digest(content),
            content=content,
        )
    )
    op.payload = {**op.payload, "resolved_delivery": content}
    await repository.save(op)
    await control_svc.register_resource(MANAGER, document(op))
    signer = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    service = RuntimeMaterialService(
        repository,
        clock=lambda: clock["now"],
        nonce_store=nonce_store,
        app_loader=app_loader,
        preview_loader=preview_loader,
        proxy_key=b"fixture-proxy-key-for-material-tests",
    )
    body = {
        "operation_id": op.id,
        "exec_ref": REF,
        "key_id": KEY_ID,
        "public_key": signer.public_key().public_bytes_raw().hex(),
    }
    return SimpleNamespace(
        svc=service,
        control=control_svc,
        repo=repository,
        op=op,
        app=app,
        delivery=delivery,
        content=content,
        clock=clock,
        seen=seen,
        signer=signer,
        body=body,
        previews=previews,
    )


async def create(materials):
    return await materials.svc.create_delegation(MANAGER, materials.body)


async def bind(materials, grant):
    await materials.control.observe_resource(
        MANAGER,
        REF,
        {
            "action": "bind",
            "holder_id": "controller-a",
            "controller_epoch": 1,
            "uid": UID,
            "node_name": "worker-a",
        },
    )
    return await materials.svc.bind_delegation(MANAGER, grant["delegation_id"], pod_uid=UID)


async def request(materials, grant, *, artifact_id=None, nonce=None, pod_uid=UID, action="download", **extra):
    body = canonical_json(
        {
            "action": action,
            **(
                {"artifact_id": artifact_id or materials.content["compiled_artifact_id"]}
                if action == "download"
                else extra
            ),
        }
    )
    headers = signed_headers(
        "POST",
        P + "/exchange",
        body,
        private_key=materials.signer,
        delegation_id=grant["delegation_id"],
        key_id=KEY_ID,
        pod_uid=pod_uid,
        timestamp=int(materials.clock["now"].replace(tzinfo=UTC).timestamp()),
        nonce=nonce or uuid4().hex,
    )
    return await materials.svc.authenticate_request("POST", P + "/exchange", body, headers)


async def serving(materials):
    materials.op.status = "completed"
    materials.op.deadline = NOW - timedelta(seconds=1)
    await materials.repo.save(materials.op)
    materials.app.state, materials.app.current_version_id, materials.app.pending_version_id = (
        "online",
        "version-a",
        None,
    )
    await materials.repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id=materials.op.app_id,
            operation_id=materials.op.id,
            route_key="app:" + materials.op.app_id,
            version_id="version-a",
            node_id="node-a",
            exec_ref=REF,
            generation=1,
            owner_epoch=1,
            status="serving",
            target={"host": "10.96.0.10", "port": 8080},
        )
    )


async def test_scope_is_derived_from_the_frozen_delivery_and_keeps_no_private_key(materials):
    grant = await create(materials)
    row = await materials.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
    assert row.scope_kind == "deployment-init" and row.expires_at is None
    assert set(row.allowed_artifacts) == {
        materials.content["compiled_artifact_id"],
        materials.content["dependency_artifact_id"],
    }
    assert row.allowed_actions == ["download"]
    assert row.delivery_id == materials.delivery.id and row.public_key == materials.body["public_key"]
    assert "private_key" not in row.model_dump()
    assert row.proxy_credential_hash == hashlib.sha256(grant["proxy"]["token"].encode()).hexdigest()


async def test_creation_retry_is_idempotent_including_the_proxy_handle(materials):
    first = await create(materials)
    assert await create(materials) == first
    altered = {**materials.body, "public_key": "ff" * 32}
    with pytest.raises(RuntimeConflict):
        await materials.svc.create_delegation(MANAGER, altered)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", 2),
        ("allowed_artifacts", ["foreign"]),
        ("allowed_actions", ["upload"]),
        ("scope_kind", "deployment-init"),
        ("private_key", "must-not-store"),
    ],
)
async def test_caller_cannot_select_authority_or_supply_a_private_key(materials, field, value):
    with pytest.raises(RuntimeConflict):
        await materials.svc.create_delegation(MANAGER, {**materials.body, field: value})


async def test_a_workload_cannot_bind_its_own_uid(materials):
    grant = await create(materials)
    with pytest.raises(MaterialProtocolError) as error:
        await request(materials, grant)
    assert error.value.status_code == 409
    with pytest.raises(RuntimeConflict):
        await materials.svc.bind_delegation(MANAGER, grant["delegation_id"], pod_uid=UID)
    await bind(materials, grant)
    proof, scope = await request(materials, grant)
    assert proof.pod_uid == UID and scope.delegation.id == grant["delegation_id"]


async def test_bind_requires_manager_role_and_the_previously_observed_resource_uid(materials):
    grant = await create(materials)
    await bind(materials, grant)
    with pytest.raises(RuntimeConflict):
        await materials.svc.bind_delegation(
            ServiceIdentity("app", "node-a", ("entry",)), grant["delegation_id"], pod_uid=UID
        )
    with pytest.raises(RuntimeConflict):
        await materials.svc.bind_delegation(MANAGER, grant["delegation_id"], pod_uid=str(uuid4()))


async def test_completed_deployment_can_initialize_while_the_manager_is_offline(materials):
    grant = await create(materials)
    await bind(materials, grant)
    await serving(materials)
    node = await materials.repo.get(RuntimeNode, "node-a")
    node.lease_until = NOW - timedelta(seconds=1)
    node.heartbeat_at = NOW - timedelta(hours=1)
    await materials.repo.save(node)
    _, scope = await request(materials, grant)
    assert scope.delegation.scope_kind == "deployment-init" and scope.deadline is None


@pytest.mark.parametrize(
    "change",
    ["revoked", "new-generation", "stop-requested", "deleted", "unapproved-version", "delivery-changed", "wrong-uid"],
)
async def test_current_ownership_is_rechecked_on_every_signed_exchange(materials, change):
    grant = await create(materials)
    await bind(materials, grant)
    if change == "revoked":
        row = await materials.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
        row.revoked_at = NOW
        await materials.repo.save(row)
    elif change == "new-generation":
        owner = (await materials.repo.find(RuntimeAssignment, app_id=materials.op.app_id))[0]
        owner.generation += 1
        await materials.repo.save(owner)
    elif change == "stop-requested":
        row = await materials.repo.get(RuntimeExecutionResource, REF)
        row.stop_requested_at = NOW
        await materials.repo.save(row)
    elif change == "deleted":
        materials.app.state = "deleted"
    elif change == "unapproved-version":
        materials.app.pending_version_id = "other-version"
    elif change == "delivery-changed":
        materials.delivery.content = {**materials.content, "compiled_artifact_id": "foreign"}
        await materials.repo.save(materials.delivery)
    with pytest.raises(MaterialProtocolError):
        await request(materials, grant, pod_uid=str(uuid4()) if change == "wrong-uid" else UID)


async def test_an_init_identity_never_gets_upload_or_foreign_material_permission(materials):
    grant = await create(materials)
    await bind(materials, grant)
    with pytest.raises(MaterialProtocolError):
        await request(materials, grant, artifact_id="foreign")
    with pytest.raises(MaterialProtocolError):
        await request(
            materials, grant, action="upload", kind="snapshot", sha256="a" * 64, size_bytes=0, platform="", metadata={}
        )


async def test_nonce_replay_and_unknown_store_fail_closed(materials):
    grant = await create(materials)
    await bind(materials, grant)
    await request(materials, grant, nonce="0" * 32)
    with pytest.raises(MaterialProtocolError) as replay:
        await request(materials, grant, nonce="0" * 32)
    assert replay.value.status_code == 409
    materials.clock["nonce_available"] = False
    with pytest.raises(MaterialProtocolError) as unavailable:
        await request(materials, grant)
    assert unavailable.value.status_code == 503 and "fixture-secret" not in str(unavailable.value)


async def reframe(materials, kind, purpose):
    materials.op.kind = kind
    await materials.repo.save(materials.op)
    resource = await materials.repo.get(RuntimeExecutionResource, REF)
    frame = document(materials.op, purpose=purpose)["template"]
    resource.purpose, resource.name = purpose, frame["metadata"]["name"]
    resource.approved_template, resource.spec_digest = frame, content_digest(frame)
    await materials.repo.save(resource)


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "timed_out"])
async def test_operation_identity_never_outlives_its_operation(materials, terminal):
    await reframe(materials, "probe", "probe")
    grant = await create(materials)
    await bind(materials, grant)
    row = await materials.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
    assert row.scope_kind == "operation" and row.expires_at <= materials.op.deadline
    materials.op.status = terminal
    await materials.repo.save(materials.op)
    with pytest.raises(MaterialProtocolError):
        await request(materials, grant)


async def test_operation_identity_expires_at_its_original_deadline(materials):
    await reframe(materials, "probe", "probe")
    grant = await create(materials)
    await bind(materials, grant)
    materials.clock["now"] = materials.op.deadline + timedelta(seconds=1)
    with pytest.raises(MaterialProtocolError):
        await request(materials, grant)


@pytest.mark.parametrize("invalid", ["expired", "reclaimed", "approval-ended", "other-tenant", "other-version"])
async def test_preview_identity_requires_the_current_live_review_session(materials, invalid):
    await reframe(materials, "preview", "preview")
    session = SimpleNamespace(
        id="preview-a",
        tenant_id=1,
        app_id=materials.op.app_id,
        version_id="version-a",
        approver_user_id=42,
        status="running",
        approval_active=True,
        expires_at=NOW + timedelta(hours=1),
    )
    materials.previews[session.id] = session
    materials.op.payload = {
        **materials.op.payload,
        "session_id": session.id,
        "preview_expires_at": session.expires_at.isoformat(),
    }
    await materials.repo.save(materials.op)
    grant = await create(materials)
    await bind(materials, grant)
    await request(materials, grant)
    if invalid == "expired":
        session.expires_at = NOW - timedelta(seconds=1)
    elif invalid == "reclaimed":
        session.status = "reclaimed"
    elif invalid == "approval-ended":
        session.approval_active = False
    elif invalid == "other-tenant":
        session.tenant_id = 2
    else:
        session.version_id = "other-version"
    with pytest.raises(MaterialProtocolError):
        await request(materials, grant)


async def test_foreign_node_or_resource_identity_cannot_create_a_delegation(materials):
    with pytest.raises(RuntimeConflict):
        await materials.svc.create_delegation(ServiceIdentity("other", "node-b", ("manager",)), materials.body)
    with pytest.raises(RuntimeConflict):
        await materials.svc.create_delegation(ServiceIdentity("admission", "node-a", ("admission",)), materials.body)
    with pytest.raises(RuntimeConflict):
        await materials.svc.create_delegation(MANAGER, {**materials.body, "exec_ref": str(uuid4())})


async def test_preview_init_uses_the_live_session_after_the_start_operation_completes(materials):
    await reframe(materials, "preview", "preview")
    session = SimpleNamespace(
        id="preview-b",
        tenant_id=1,
        app_id=materials.op.app_id,
        version_id="version-a",
        approver_user_id=42,
        status="running",
        approval_active=True,
        expires_at=NOW + timedelta(hours=1),
    )
    materials.previews[session.id] = session
    materials.op.payload = {
        **materials.op.payload,
        "session_id": session.id,
        "preview_expires_at": session.expires_at.isoformat(),
    }
    await materials.repo.save(materials.op)
    grant = await create(materials)
    await bind(materials, grant)
    materials.op.status = "completed"
    materials.op.deadline = NOW - timedelta(seconds=1)
    await materials.repo.save(materials.op)
    _, scope = await request(materials, grant)
    assert scope.deadline == session.expires_at


async def test_public_offline_material_requires_an_explicit_matching_profile(materials):
    from bisheng.core.context.tenant import tenant_execution_scope

    await reframe(materials, "prepare", "prepare-download")
    with tenant_execution_scope(2):
        public = await materials.repo.save(
            RuntimeArtifact(
                tenant_id=2,
                app_id="foreign",
                scope_key="2/foreign",
                kind="offline",
                visibility="public",
                sha256="f" * 64,
                state="verified",
                confirmed_at=NOW,
                platform="linux/amd64",
                metadata_={},
            )
        )
    materials.op.payload = {**materials.op.payload, "delivery": {"dependencies": {"offline_artifacts": [public.id]}}}
    await materials.repo.save(materials.op)
    with pytest.raises(RuntimeConflict):
        await create(materials)


@pytest.mark.parametrize("field", ["platform", "metadata"])
async def test_upload_control_types_are_validated_before_consuming_the_nonce(materials, field):
    await reframe(materials, "prepare", "prepare-upload")
    grant = await create(materials)
    await bind(materials, grant)
    upload = {"kind": "compiled", "sha256": "a" * 64, "size_bytes": 0, "platform": "linux/amd64", "metadata": {}}
    upload[field] = []
    with pytest.raises(MaterialProtocolError) as error:
        await request(materials, grant, action="upload", **upload)
    assert error.value.status_code == 400 and not materials.seen
