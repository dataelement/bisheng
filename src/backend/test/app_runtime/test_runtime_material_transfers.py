"""覆盖 AC: AC-26、AC-28、AC-29、AC-42、AC-46、AC-47、AC-51. Durable workload transfers."""

import hashlib
from datetime import UTC, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeTransfer
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeMaterialDelegation
from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json
from test.app_runtime.test_runtime_artifacts import MemoryObjects
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import control as control
from test.app_runtime.test_runtime_material_service import KEY_ID, P, bind, create, reframe, request, serving
from test.app_runtime.test_runtime_material_service import materials as materials

DATA = b"0123456789"


@pytest.fixture
async def transfers(materials):
    from bisheng.app_runtime.domain.services.runtime_material_transfer_service import RuntimeMaterialTransferService

    objects = MemoryObjects()
    for field in ("compiled_artifact_id", "dependency_artifact_id"):
        artifact = await materials.repo.get(RuntimeArtifact, materials.content[field])
        artifact.size_bytes, artifact.sha256 = len(DATA), hashlib.sha256(DATA).hexdigest()
        await materials.repo.save(artifact)
        objects.data[artifact.object_key] = DATA
    service = RuntimeMaterialTransferService(materials.svc, object_store=objects)
    return SimpleNamespace(svc=service, m=materials, objects=objects)


async def exchange(t, *, upload=None, grant=None):
    if grant is None:
        if upload is not None:
            prior = await t.m.repo.get(RuntimeArtifact, t.m.content["compiled_artifact_id"])
            prior_bytes = DATA + b"-previous-release"
            prior.sha256, prior.size_bytes = hashlib.sha256(prior_bytes).hexdigest(), len(prior_bytes)
            t.objects.data[prior.object_key] = prior_bytes
            await t.m.repo.save(prior)
            await reframe(t.m, "prepare", "prepare-upload")
        grant = await create(t.m)
        await bind(t.m, grant)
    if upload is None:
        _, scope = await request(t.m, grant)
    else:
        _, scope = await request(t.m, grant, action="upload", **upload)
    return grant, await t.svc.exchange(scope)


def upload(data=DATA, **changes):
    return {"kind": "compiled", "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), **changes}


async def call(t, grant, session, method="GET", *, sub="", query="", body=b"", ticket=None):
    target = f"{P}/transfers/{session['transfer_id']}" + sub + query
    headers = wire.signed_headers(
        method,
        target,
        body,
        private_key=t.m.signer,
        delegation_id=grant["delegation_id"],
        key_id=KEY_ID,
        pod_uid=t.m.body.get("pod_uid", "22222222-2222-4222-8222-222222222222"),
        timestamp=int(t.m.clock["now"].replace(tzinfo=UTC).timestamp()),
        nonce=uuid4().hex,
        ticket=session["ticket"] if ticket is None else ticket,
    )
    proof, scope = await t.m.svc.authenticate_request(
        method,
        target,
        body,
        headers,
        authorize_transfer=lambda proof, scope: t.svc.authorize(proof, scope, method, target, body),
    )
    if sub == "/content" and method == "PUT":
        return await t.svc.append(scope, proof.ticket, session["transfer_id"], int(query.split("=")[1]), body)
    if sub == "/content":
        values = dict(x.split("=") for x in query[1:].split("&"))
        status, response_headers, chunks = await t.svc.content(
            scope, proof.ticket, session["transfer_id"], int(values["offset"]), int(values["length"])
        )
        return status, response_headers, b"".join([chunk async for chunk in chunks])
    if sub == "/finalize":
        return await t.svc.finalize(
            scope,
            proof.ticket,
            session["transfer_id"],
            wire.parse_control(body, allowed={"sha256", "size_bytes"}, required={"sha256", "size_bytes"}),
        )
    return await t.svc.status(scope, proof.ticket, session["transfer_id"])


async def finalize(t, grant, session):
    return await call(
        t,
        grant,
        session,
        "POST",
        sub="/finalize",
        body=canonical_json({"sha256": session["sha256"], "size_bytes": session["size_bytes"]}),
    )


async def test_download_exchange_rotates_ticket_but_not_transfer_or_material(transfers):
    t = transfers
    grant, first = await exchange(t)
    _, second = await exchange(t, grant=grant)
    assert first["transfer_id"] == second["transfer_id"] and first["ticket"] != second["ticket"]
    assert second["action"] == "download" and second["offset"] == 0
    assert second["expires_at"] == int((t.m.clock["now"] + timedelta(seconds=300)).replace(tzinfo=UTC).timestamp())
    row = await t.m.repo.get(RuntimeTransfer, second["transfer_id"])
    assert row.authorization_kind == "deployment-init" and row.authorization_id == grant["delegation_id"]
    assert row.ticket_hash == hashlib.sha256(second["ticket"].encode()).hexdigest()
    with pytest.raises(wire.MaterialProtocolError) as error:
        await call(t, grant, first)
    assert error.value.status_code == 401
    assert "ticket" not in await call(t, grant, second)


async def test_completed_deployment_download_is_independent_of_old_operation_deadline(transfers):
    t = transfers
    grant, session = await exchange(t)
    await serving(t.m)
    t.m.clock["now"] += timedelta(seconds=301)
    with pytest.raises(wire.MaterialProtocolError) as error:
        await call(t, grant, session)
    assert error.value.status_code == 401
    _, renewed = await exchange(t, grant=grant)
    assert renewed["transfer_id"] == session["transfer_id"]
    assert (await call(t, grant, renewed, sub="/content", query="?length=4&offset=2"))[2] == b"2345"


async def test_download_ranges_and_nonempty_eof(transfers):
    t = transfers
    grant, session = await exchange(t)
    status, headers, content = await call(t, grant, session, sub="/content", query="?length=16&offset=7")
    assert (status, content) == (206, b"789")
    assert headers["Content-Range"] == "bytes 7-9/10" and headers["Content-Length"] == "3"
    for offset in (10, 11):
        with pytest.raises(wire.MaterialProtocolError) as error:
            await call(t, grant, session, sub="/content", query=f"?length=4&offset={offset}")
        assert error.value.status_code == 416


async def test_empty_download_is_200_at_zero(transfers):
    t = transfers
    artifact = await t.m.repo.get(RuntimeArtifact, t.m.content["compiled_artifact_id"])
    artifact.size_bytes, artifact.sha256 = 0, hashlib.sha256(b"").hexdigest()
    await t.m.repo.save(artifact)
    t.objects.data[artifact.object_key] = b""
    grant, session = await exchange(t)
    status, headers, content = await call(t, grant, session, sub="/content", query="?length=1&offset=0")
    assert (status, content, headers["Content-Length"]) == (200, b"", "0")


async def test_upload_resume_replay_and_finalize_are_durable(transfers):
    t = transfers
    grant, first = await exchange(t, upload=upload())
    assert first["state"] == "open"
    for _ in range(2):
        assert (await call(t, grant, first, "PUT", sub="/content", query="?offset=0", body=DATA[:4]))["offset"] == 4
    _, second = await exchange(t, grant=grant, upload=upload())
    assert first["transfer_id"] == second["transfer_id"] and second["offset"] == 4
    with pytest.raises(wire.MaterialProtocolError):
        await call(t, grant, first)
    await call(t, grant, second, "PUT", sub="/content", query="?offset=4", body=DATA[4:])
    confirmed = await finalize(t, grant, second)
    assert confirmed["state"] == "verified" and confirmed["confirmed_at"]
    assert (await finalize(t, grant, second))["artifact_id"] == confirmed["artifact_id"]
    artifact = await t.m.repo.get(RuntimeArtifact, confirmed["artifact_id"])
    assert t.objects.data[artifact.object_key] == DATA


@pytest.mark.parametrize("offset,data", [(0, b"wrong"), (6, b"gap"), (1, DATA[1:4])])
async def test_conflicting_or_noncontiguous_upload_never_advances_offset(transfers, offset, data):
    t = transfers
    grant, session = await exchange(t, upload=upload())
    await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=DATA[:4])
    with pytest.raises(wire.MaterialProtocolError) as error:
        await call(t, grant, session, "PUT", sub="/content", query=f"?offset={offset}", body=data)
    assert error.value.status_code == 409
    assert (await call(t, grant, session))["offset"] == 4


async def test_finalize_refuses_incomplete_digest_or_declaration_mismatch(transfers):
    t = transfers
    grant, session = await exchange(t, upload=upload())
    with pytest.raises(wire.MaterialProtocolError) as incomplete:
        await finalize(t, grant, session)
    assert incomplete.value.status_code == 409
    await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=b"abcdefghij")
    with pytest.raises(wire.MaterialProtocolError) as digest:
        await finalize(t, grant, session)
    assert digest.value.status_code == 409
    with pytest.raises(wire.MaterialProtocolError) as changed:
        await call(
            t, grant, session, "POST", sub="/finalize", body=canonical_json({"sha256": "f" * 64, "size_bytes": 10})
        )
    assert changed.value.status_code == 409
    assert (await t.m.repo.get(RuntimeArtifact, session["artifact_id"])).state != "verified"


async def test_empty_upload_needs_no_put(transfers):
    t = transfers
    grant, session = await exchange(t, upload=upload(b""))
    assert (await finalize(t, grant, session))["state"] == "verified"


@pytest.mark.parametrize("action", ["put-download", "finalize-download", "get-upload"])
async def test_ticket_action_cannot_be_changed(transfers, action):
    t = transfers
    grant, session = await exchange(t, upload=upload() if action == "get-upload" else None)
    with pytest.raises(wire.MaterialProtocolError) as error:
        if action == "put-download":
            await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=b"a")
        elif action == "finalize-download":
            await finalize(t, grant, session)
        else:
            await call(t, grant, session, sub="/content", query="?length=1&offset=0")
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"metadata": {"object_key": "other-app/secret"}},
        {"size_bytes": 2**40},
        {"metadata": {"source_artifact_id": "foreign"}},
    ],
)
async def test_upload_declaration_cannot_select_storage_or_exceed_limits(transfers, changes):
    with pytest.raises(wire.MaterialProtocolError):
        await exchange(transfers, upload=upload(**changes))


async def test_same_content_upload_cannot_change_the_bound_platform_or_metadata(transfers):
    t = transfers
    grant, _ = await exchange(t, upload=upload(platform="linux/amd64"))
    with pytest.raises(wire.MaterialProtocolError) as error:
        await exchange(t, grant=grant, upload=upload(platform="linux/arm64"))
    assert error.value.status_code == 409


async def test_revocation_during_object_write_cannot_commit_offset(transfers):
    t = transfers
    grant, session = await exchange(t, upload=upload())
    original = t.objects.put

    async def revoke(key, path, content_type="application/octet-stream"):
        await original(key, path, content_type)
        row = await t.m.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
        row.revoked_at = t.m.clock["now"]
        await t.m.repo.save(row)

    t.objects.put = revoke
    with pytest.raises(wire.MaterialProtocolError):
        await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=DATA)
    assert (await t.m.repo.get(RuntimeTransfer, session["transfer_id"])).offset == 0


async def test_final_object_without_sql_confirmation_cannot_be_reported_as_verified(transfers):
    t = transfers
    grant, session = await exchange(t, upload=upload())
    await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=DATA)
    original = t.objects.put

    async def expire(key, path, content_type="application/octet-stream"):
        await original(key, path, content_type)
        t.m.clock["now"] = t.m.op.deadline + timedelta(seconds=1)

    t.objects.put = expire
    with pytest.raises(wire.MaterialProtocolError):
        await finalize(t, grant, session)
    assert (await t.m.repo.get(RuntimeArtifact, session["artifact_id"])).state != "verified"


async def test_download_rechecks_authority_between_object_chunks(transfers):
    t = transfers
    grant, session = await exchange(t)

    async def chunks(key):
        yield DATA[:3]
        t.m.app.state = "deleted"
        t.m.clock["now"] += timedelta(seconds=5)
        yield DATA[3:]

    t.objects.iter_content = chunks
    with pytest.raises(wire.MaterialProtocolError):
        await call(t, grant, session, sub="/content", query="?length=10&offset=0")


async def test_download_truncation_does_not_complete_a_declared_range(transfers):
    t = transfers
    grant, session = await exchange(t)
    artifact = await t.m.repo.get(RuntimeArtifact, session["artifact_id"])
    t.objects.data[artifact.object_key] = b"short"
    with pytest.raises(wire.MaterialProtocolError):
        await call(t, grant, session, sub="/content", query="?length=10&offset=0")


async def test_existing_verified_content_is_reused_without_uploading_again(transfers):
    t = transfers
    await reframe(t.m, "prepare", "prepare-upload")
    grant = await create(t.m)
    await bind(t.m, grant)
    _, scope = await request(t.m, grant, action="upload", **upload())
    session = await t.svc.exchange(scope)
    assert session["artifact_id"] == t.m.content["compiled_artifact_id"]
    assert session["state"] == "confirmed" and session["offset"] == len(DATA)
    assert (await finalize(t, grant, session))["state"] == "verified"


async def test_ticket_expiry_never_outlives_operation(transfers):
    t = transfers
    t.m.op.deadline = t.m.clock["now"] + timedelta(seconds=30)
    await t.m.repo.save(t.m.op)
    grant, session = await exchange(t, upload=upload())
    assert session["expires_at"] == int(t.m.op.deadline.replace(tzinfo=UTC).timestamp())
    t.m.clock["now"] += timedelta(seconds=31)
    with pytest.raises(wire.MaterialProtocolError):
        await call(t, grant, session)
    with pytest.raises(wire.MaterialProtocolError):
        await exchange(t, grant=grant, upload=upload())


@pytest.mark.parametrize(
    "field,value", [("authorization_id", "foreign"), ("authorization_kind", "operation"), ("node_id", "node-b")]
)
async def test_transfer_identity_is_bound_to_its_authority_before_nonce_use(transfers, field, value):
    t = transfers
    grant, session = await exchange(t)
    row = await t.m.repo.get(RuntimeTransfer, session["transfer_id"])
    setattr(row, field, value)
    await t.m.repo.save(row)
    seen = len(t.m.seen)
    with pytest.raises(wire.MaterialProtocolError) as error:
        await call(t, grant, session)
    assert error.value.status_code == 403 and len(t.m.seen) == seen


async def test_new_authority_can_reuse_identical_bytes_with_its_own_valid_provenance(transfers):
    from test.app_runtime.test_runtime_kubernetes_service import MANAGER

    t = transfers
    t.m.op.payload = {**t.m.op.payload, "source_artifact_id": "source-a"}
    await t.m.repo.save(t.m.op)
    grant, session = await exchange(t, upload=upload())
    await call(t, grant, session, "PUT", sub="/content", query="?offset=0", body=DATA)
    confirmed = await finalize(t, grant, session)
    new_grant = await t.m.svc.create_delegation(MANAGER, {**t.m.body, "key_id": "second-upload"})
    await bind(t.m, new_grant)
    _, scope = await request(t.m, new_grant, action="upload", **upload(metadata={"source_artifact_id": "source-a"}))
    reused = await t.svc.exchange(scope)
    assert reused["artifact_id"] == confirmed["artifact_id"] and reused["state"] == "confirmed"


async def test_same_authority_upload_metadata_is_still_immutable(transfers):
    t = transfers
    t.m.op.payload = {**t.m.op.payload, "source_artifact_id": "source-a"}
    await t.m.repo.save(t.m.op)
    grant, _ = await exchange(t, upload=upload())
    with pytest.raises(wire.MaterialProtocolError) as error:
        await exchange(t, grant=grant, upload=upload(metadata={"source_artifact_id": "source-a"}))
    assert error.value.status_code == 409
