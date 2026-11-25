"""Provider upload: independent items; no storage or native processing in the stream path."""

import asyncio
from dataclasses import replace
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderQuota as Quota
from test.knowledge_unification import test_kn_space_upload_application as fixture

native, database, case = fixture.native, fixture.database, fixture.case


@pytest.mark.parametrize("scenario", ["accepted", "unavailable", "stale", "resend", "retired"])
async def test_real_registration_before_first_byte_and_lost_ack_replay(case, monkeypatch, scenario):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import bisheng.permission.application.access as access
    from bisheng.knowledge.application.provider_upload_quota import UploadReceipt
    from bisheng.knowledge.domain.models import provider_control as models
    from bisheng.knowledge.infrastructure.providers.registry import PortContext

    app = fixture.app(case, monkeypatch)
    monkeypatch.setattr(access, "get_f048_resource_adapter", AsyncMock(return_value=case.adapter))
    async with case.database.engine.begin() as conn:
        for cls in (
            models.KnowledgeProviderInstance,
            models.KnowledgeProviderGeneration,
            models.KnowledgeProviderBinding,
            models.KnowledgeProviderOperation,
            models.KnowledgeProviderQuota,
            models.KnowledgeProviderMapping,
        ):
            await conn.run_sync(cls.__table__.create)
    sessions = async_sessionmaker(case.database.engine, expire_on_commit=False)
    async with sessions.begin() as db:
        db.add(
            models.KnowledgeProviderInstance(
                id=1,
                tenant_id=101,
                provider_key="weknora",
                state="unavailable" if scenario == "unavailable" else "ready",
                capability_revision=2,
                endpoint="server",
                credential_ref="secret-ref",
                remote_scope_id="scope",
            )
        )
        db.add(
            models.KnowledgeProviderGeneration(
                tenant_id=101,
                space_id=9700,
                generation=1,
                state="retired" if scenario == "retired" else "ready",
                provider_instance_id=1,
                remote_scope_id="scope",
                remote_kb_id="lib",
            )
        )
        db.add(
            models.KnowledgeProviderBinding(
                tenant_id=101, space_id=9700, provider_key="weknora", state="ready", active_generation=1
            )
        )
    context = PortContext(101, 9700, "weknora", "upload", 1, 1, "scope", "lib")

    async def source():
        yield b"abc"

    async def send(*, identity, chunks, chunking):
        assert not case.active
        async with sessions.begin() as db:
            op = await db.get(models.KnowledgeProviderOperation, identity.operation_id)
            assert op.target_manifest[0]["version_id"] == identity.version_id and op.state == "sending"
            assert len((await db.scalars(select(Quota))).all()) == 2
        assert [part async for part in chunks] == [b"abc"]
        raise TimeoutError()

    async def lookup(*, identity):
        if scenario == "resend" and identity.operation_epoch == 1:
            return UploadReceipt(identity, "not_received", None)
        return UploadReceipt(identity, "accepted", "opaque-remote-id")

    port = SimpleNamespace(
        capability_revision=1 if scenario == "stale" else 2,
        context=context,
        validate_upload=Mock(),
        send=AsyncMock(side_effect=send),
        lookup=AsyncMock(side_effect=lookup),
    )
    kwargs = {
        "knowledge": case.knowledge,
        "parent_id": 11,
        "request_key": "req",
        "file_name": "test.txt",
        "byte_count": 3,
        "checksum": intent().sha256,
        "port": port,
        "user_limit": 3,
        "tenant_limit": 3,
    }
    if scenario in {"unavailable", "stale", "retired"}:
        with pytest.raises(ValueError):
            await app.acreate_provider_file(**kwargs, chunks=source())
        port.send.assert_not_awaited()
        async with sessions.begin() as db:
            assert not (await db.scalars(select(Quota))).all()
        return
    if scenario == "resend":
        original = await app.acreate_provider_file(**kwargs, chunks=source())
        assert original.state == "reupload_required"
        with pytest.raises(ValueError):
            await app.acreate_provider_file(**(kwargs | {"tenant_limit": 2}), chunks=source())
    for _ in range(2):
        result = await app.acreate_provider_file(**kwargs, chunks=source())
        assert result.state == "accepted" and result.file_id in case.projection and result.version_id > 0
        assert not hasattr(result, "remote_id")
    if scenario == "resend":
        assert result == replace(original, state="accepted")
        assert [call.kwargs["identity"].operation_epoch for call in port.send.await_args_list] == [1, 2]
    assert port.send.await_count == port.lookup.await_count == (2 if scenario == "resend" else 1)
    assert not case.blobs and len(case.projection) == 1
    async with sessions.begin() as db:
        row = (await db.scalars(select(models.KnowledgeProviderMapping))).one()
        assert (
            row.local_resource_id in case.projection
            and row.lifecycle_state == "received"
            and row.ready_revision is None
        )
        assert [q.state for q in (await db.scalars(select(Quota))).all()] == ["charged", "charged"]

    await check_processing(sessions, result, case)


async def check_processing(sessions, result, case):
    from bisheng.knowledge.application.provider_processing_readiness import ProcessingProof, reconcile_processed_upload
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
    from bisheng.knowledge.domain.repositories.provider_retrieval_repository import ProviderRetrievalRepository
    from bisheng.permission.domain.models import PermissionProjectionOperation as Op
    from bisheng.permission.domain.models import ResourcePermissionMode as Mode

    async with case.database.engine.begin() as conn:
        for model in (Op, Mode):
            await conn.run_sync(model.__table__.create)
    async with sessions.begin() as db:
        instance = await db.get(Instance, 1)
        instance.state = "ready"
        file_id = str(result.file_id)
        db.add(
            Op(
                id=1,
                tenant_id=101,
                idempotency_key="key",
                request_checksum="a" * 64,
                operation_type="RESOURCE_CREATE",
                scope_type="resource",
                scope_key="knowledge_file:" + file_id,
                expected_version=0,
                target_version=1,
                store_id="store",
                model_id="model",
                status="FINALIZED",
                before_checksum="a" * 64,
                after_checksum="b" * 64,
                operator_id=7,
            )
        )
        db.add(
            Mode(
                id=1,
                tenant_id=101,
                resource_type="knowledge_file",
                resource_id=file_id,
                parent_type="folder",
                parent_id="11",
                mode="INHERIT",
                version=1,
                operation_id=1,
                projection_state="CURRENT",
            )
        )
    args = {"sessions": sessions, "operation_id": result.operation_id}
    retrieval = ProviderRetrievalRepository(sessions)

    async def candidates():
        route = await retrieval.route(case.knowledge)
        rows, _ = await retrieval.load_candidates(route, file_ids=[result.file_id], tag_ref_ids=[])
        return rows

    assert not await candidates()
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as Mapping

    # The epoch this upload froze (a resend attempt bumped it). Fault fixtures
    # below mutate/advance it; every "healthy" retry must restore exactly this.
    async with sessions.begin() as db:
        frozen_epoch = (await db.scalars(select(Mapping))).one().operation_epoch
    assert not await reconcile_processed_upload(**args, read_proof=AsyncMock(return_value=None))

    async def wrong(target):
        return ProcessingProof(replace(target, version_id=target.version_id + 1), "succeeded", 2)

    assert not await reconcile_processed_upload(**args, read_proof=wrong)

    async def failed(target):
        return ProcessingProof(target, "failed", 2)

    assert not await reconcile_processed_upload(**args, read_proof=failed)

    async def revoked(target):
        async with sessions.begin() as db:
            (await db.get(Mode, 1)).projection_state = "PENDING"
        return ProcessingProof(target, "succeeded", 2)

    assert not await reconcile_processed_upload(**args, read_proof=revoked)
    assert not await candidates()
    async with sessions.begin() as db:
        (await db.get(Mode, 1)).projection_state = "CURRENT"

    from datetime import datetime

    async def tombstoned(target):
        async with sessions.begin() as db:
            row = (await db.scalars(select(Mapping))).one()
            row.tombstoned_at = datetime(2026, 1, 1)
            row.operation_epoch += 1
        return ProcessingProof(target, "succeeded", 2)

    assert not await reconcile_processed_upload(**args, read_proof=tombstoned)
    assert not await candidates()
    # Reset fault fixture for the independent success branch. The epoch is the
    # one this upload registered with (a resend attempt bumped it), never a
    # hard-coded value: the proof must match the frozen operation epoch.
    async with sessions.begin() as db:
        row = (await db.scalars(select(Mapping))).one()
        row.tombstoned_at = None
        row.operation_epoch = frozen_epoch

    async def healthy(target):
        return ProcessingProof(target, "succeeded", 2)

    assert await reconcile_processed_upload(**args, read_proof=healthy)
    assert (await candidates())[0].ready_revision == 2


def intent():
    from bisheng.knowledge.application.provider_upload_quota import UploadIdentity

    return UploadIdentity(1, 2, 3, 4, 5, "scope", "lib", "req", "op", 6, 7, 8, 3, sha256(b"abc").hexdigest())


async def test_concurrent_reservations_share_tenant_budget_and_release_only_own_version(tmp_path):
    from bisheng.knowledge.application.provider_upload_quota import ProviderUploadQuota, QuotaExceeded

    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "quota.db"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("create table tenant(id integer primary key)"))
            await conn.execute(text("insert into tenant values (1)"))
            await conn.run_sync(Quota.__table__.create)
        ledger = ProviderUploadQuota()
        first = intent()
        second = replace(first, user_id=10, operation_id="op2", version_id=12)

        async def reserve(key):
            async with sessions.begin() as db:
                await ledger.reserve(db, key, user_limit=3, tenant_limit=5)
                return key

        results = await asyncio.gather(reserve(first), reserve(second), return_exceptions=True)
        assert sum(isinstance(r, QuotaExceeded) for r in results) == 1
        winner = next(r for r in results if not isinstance(r, Exception))
        loser = first if winner == second else second
        await reserve(winner)
        with pytest.raises(ValueError):
            async with sessions.begin() as db:
                await ledger.release(db, replace(winner, operation_id="foreign"))
        async with sessions.begin() as db:
            await ledger.release(db, winner)
        await reserve(loser)
        async with sessions.begin() as db:
            await ledger.verify(db, loser)
            assert [r.state for r in (await db.scalars(select(Quota).order_by(Quota.id))).all()] == ["released"] * 2 + [
                "charged"
            ] * 2
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("own", "accepted"),
        ("lost", "unknown"),
        ("foreign", "conflict"),
        ("absent", "reupload_required"),
        ("cut", "unknown"),
    ],
)
async def test_receipt_must_belong_to_original_request_before_exposing_success(mode, expected):
    from bisheng.knowledge.application.provider_upload_quota import UploadReceipt, forward_provider_stream

    key = intent()
    consumed = []

    async def source():
        yield b"a"
        if mode == "cut":
            raise ConnectionError("disconnected")
        yield b"bc"

    async def send(*, identity, chunks, chunking):
        assert identity == key and chunking == {"chunk_size": 100, "chunk_overlap": 0}
        async for chunk in chunks:
            consumed.append(chunk)
        if mode != "own":
            raise TimeoutError()
        return UploadReceipt(key, "accepted", "object")

    receipt = None
    if mode == "foreign":
        receipt = UploadReceipt(replace(key, request_key="foreign"), "accepted", "secret-id")
    elif mode == "absent":
        receipt = UploadReceipt(key, "not_received", None)
    lookup = AsyncMock(return_value=receipt)
    result = await forward_provider_stream(key, source(), {"chunk_size": 100, "chunk_overlap": 0}, send, lookup)
    assert result.state == expected
    assert result.remote_id == ("object" if mode == "own" else None)
    assert consumed == ([b"a"] if mode == "cut" else [b"a", b"bc"])


async def test_space_application_denies_before_stream_or_registration():
    from bisheng.knowledge.application.space_upload import SpaceUploadApplication

    app = object.__new__(SpaceUploadApplication)
    app._admit_destination = AsyncMock(side_effect=PermissionError())
    with pytest.raises(PermissionError):
        await app.acreate_provider_file(
            knowledge=object(),
            parent_id=4,
            request_key="req",
            file_name="one",
            byte_count=3,
            checksum=intent().sha256,
            chunks=None,
            port=None,
            user_limit=3,
            tenant_limit=5,
        )
    app._admit_destination.assert_awaited_once()


async def test_invalid_chunking_rejected_before_consumption_or_remote_call():
    from bisheng.knowledge.application.provider_upload_quota import forward_provider_stream

    send = AsyncMock()
    with pytest.raises(ValueError):
        await forward_provider_stream(intent(), None, {"unsupported": 1}, send, AsyncMock())
    send.assert_not_awaited()
