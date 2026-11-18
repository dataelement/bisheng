"""Original copy recovery through real HTTP routes and native SQL/projections."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.knowledge.api.endpoints import processing as endpoints
from bisheng.knowledge.api.endpoints import space_copy as copy_endpoints
from bisheng.knowledge.application import move_processing_access, space_copy, space_copy_access
from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.domain.models import PermissionProjectionOperation
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_kn_copy import (
    admission as admission,
)
from test.knowledge_unification.test_kn_copy import (
    application as application,
)
from test.knowledge_unification.test_kn_copy import (
    business as business,
)
from test.knowledge_unification.test_kn_copy import (
    command,
)
from test.knowledge_unification.test_kn_copy import (
    copying as copying,
)
from test.knowledge_unification.test_kn_copy import (
    job_tenant as job_tenant,
)
from test.knowledge_unification.test_kn_copy import (
    processing as processing,
)
from test.knowledge_unification.test_kn_copy import (
    store as store,
)
from test.knowledge_unification.test_kn_copy import (
    tenant as tenant,
)

initialize_indexes = SpaceCopyOwner._initialize


async def test_http_recovers_uninitialized_copy_without_target_permission_or_duplicate_resources(
    copying, monkeypatch, actual_processing_task
):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="HTTP recovery", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    sid, jid = accepted["knowledge"].id, accepted["processing_job"].job_id
    owner = SpaceCopyOwner(app)
    failed = await owner.afail(jid, 0, error_code=25009)
    monkeypatch.setattr(
        space_copy_access, "require_business_action", AsyncMock(side_effect=PermissionPublishNotReadyError())
    )
    monkeypatch.setattr(move_processing_access, "batch_check_business_actions", AsyncMock(return_value={}))
    access = SpaceCopyAccess(owner)
    monkeypatch.setattr(endpoints, "SpaceCopyAccess", lambda: access)
    monkeypatch.setattr(copy_endpoints, "SpaceCopyAccess", lambda: access)
    actor = AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=101))
    monkeypatch.setattr(space_copy_access, "resolve_permission_actor", actor)
    web = FastAPI()
    web.include_router(endpoints.router, prefix="/api/v1/knowledge/space")
    web.include_router(copy_endpoints.router, prefix="/api/v1/knowledge/space")
    web.dependency_overrides[UserPayload.get_login_user] = lambda: ctx.user
    web.dependency_overrides[endpoints.get_processing_service] = lambda: None

    @web.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    async def write_scope(request, identity):
        assert identity is ctx.user and request.headers["X-Management-Tenant"] == "101"

    monkeypatch.setattr(endpoints, "_write_scope", write_scope)
    path = f"/api/v1/knowledge/space/{sid}/processing-jobs"
    async with AsyncClient(transport=ASGITransport(app=web), base_url="http://native") as http:
        pending = (await http.get("/api/v1/knowledge/space/copy/tasks")).json()
        assert pending["status_code"] == 200
        assert pending["data"]["data"][0]["id"] == sid
        assert pending["data"]["data"][0]["phase"] == "failed"
        assert (await http.get("/api/v1/knowledge/space/copy/tasks", params={"page": 0})).status_code == 422
        assert (await http.get("/api/v1/knowledge/space/copy/tasks", params={"space_id": 999})).json()["data"][
            "data"
        ] == []
        actor.return_value = PermissionActor(user_id=8, tenant_id=101)
        assert (await http.get("/api/v1/knowledge/space/copy/tasks")).json()["data"]["data"] == []
        actor.return_value = PermissionActor(user_id=7, tenant_id=101)
        page = (await http.get(path, params={"kind": "space_copy"})).json()
        assert page["status_code"] == 200
        assert page["data"]["total"] == 1 and page["data"]["data"][0]["id"] == jid
        detail = (await http.get(f"{path}/{jid}", params={"kind": "space_copy"})).json()
        assert detail["status_code"] == 200
        assert detail["data"]["retryable"] and detail["data"]["error_code"] == 25009
        with monkeypatch.context() as patch:
            patch.setattr(space_copy, "require_business_action", AsyncMock(side_effect=PermissionDeniedError()))
            denied = (await http.get(f"{path}/{jid}", params={"kind": "space_copy"})).json()
            assert denied["status_code"] == PermissionDeniedError.Code
            assert (await http.get("/api/v1/knowledge/space/copy/tasks")).json()["data"]["data"] == []
        retry = (
            await http.post(
                f"{path}/{jid}/retry",
                params={"kind": "space_copy"},
                headers={"X-Management-Tenant": "101"},
                json={"idempotency_key": "original-http-retry", "expected_job_revision": failed.revision},
            )
        ).json()
        assert retry["status_code"] == 200
        assert retry["data"]["job_id"] == jid and retry["data"]["state"] == "accepted"
    async with ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 0
        assert not (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
    current, _ = await owner.aread(jid)
    await owner.astart(jid, current.revision)
    async with ctx.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Job))).scalar_one() == 1
        assert (await session.get(Knowledge, sid)).state == 1
        operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert len(operations) == 3 and all(row.status == "FINALIZED" for row in operations)


async def test_confirm_http_initializes_permissions_and_indexes_before_exposing_usable_space(copying, monkeypatch):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Background copy", identity=ctx.user)
    monkeypatch.setattr(copy_endpoints, "SpaceCopyApplication", lambda: app)
    monkeypatch.setattr(copy_endpoints, "_write_scope", AsyncMock())
    original = SpaceCopyOwner.aensure_logical
    initialize = AsyncMock(side_effect=original)

    async def initialize_bound(self, *args, **kwargs):
        await initialize(self, *args, **kwargs)

    monkeypatch.setattr(SpaceCopyOwner, "aensure_logical", initialize_bound)
    web = FastAPI()
    web.include_router(copy_endpoints.router, prefix="/api/v1/knowledge/space")
    web.dependency_overrides[UserPayload.get_login_user] = lambda: ctx.user
    async with AsyncClient(transport=ASGITransport(app=web), base_url="http://native") as http:
        response = (await http.post("/api/v1/knowledge/space/40/copy/confirm", json=command(plan).model_dump())).json()
        assert response["status_code"] == 200
        result = response["data"]
        assert result["processing_job"]["accepted"] and not result["completed"]
        repeated = (await http.post("/api/v1/knowledge/space/40/copy/confirm", json=command(plan).model_dump())).json()
        assert repeated["data"]["knowledge"]["id"] == result["knowledge"]["id"]
    assert initialize.await_count == 2
    assert result["knowledge"]["state"] == 1
    async with ctx.sessions() as session:
        job = (await session.execute(sa.select(Job))).scalars().one()
        assert job.pending_dispatch and job.state == "accepted"


async def test_index_model_validation_reuses_the_locked_session(copying, monkeypatch):
    from bisheng.knowledge.domain import knowledge_rag

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Shared transaction", identity=ctx.user)
    result = await app.aconfirm(40, command(plan), identity=ctx.user)
    root = result["knowledge"]
    async with SpaceCopyOwner(app)._logical_target(40, root.id) as (session, locked):

        async def read(ident, **scope):
            assert ident == root.id and scope["session"] is session
            # Model validation must reacquire through this transaction, not a new connection.
            assert (
                await session.execute(sa.select(Knowledge).where(Knowledge.id == ident).with_for_update())
            ).scalar_one().id == ident
            return SimpleNamespace(
                model_id=11,
                read=SimpleNamespace(
                    snapshot=SimpleNamespace(payload_json=json.dumps({"knowledge": locked.model_dump(mode="json")}))
                ),
            )

        require = AsyncMock(side_effect=read)
        monkeypatch.setattr(
            knowledge_rag, "get_knowledge_model_read_runtime", AsyncMock(return_value=SimpleNamespace(arequire=require))
        )
        monkeypatch.setattr(KnowledgeRag, "_embedding", AsyncMock(return_value=object()))
        monkeypatch.setattr(
            KnowledgeRag,
            "init_milvus_vectorstore",
            Mock(return_value=SimpleNamespace(col=SimpleNamespace(load=Mock()))),
        )
        monkeypatch.setattr(
            KnowledgeRag,
            "init_es_vectorstore",
            Mock(
                return_value=SimpleNamespace(
                    _store=SimpleNamespace(_create_index_if_not_exists=Mock()),
                    client=SimpleNamespace(close=AsyncMock()),
                )
            ),
        )
        await initialize_indexes(locked, 7, session=session)
        assert require.await_count == 2


async def test_initialization_claim_is_exclusive_and_failure_uses_original_lease(
    copying, monkeypatch, actual_processing_task
):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Claim first", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        result = await app.aconfirm(40, command(plan), identity=ctx.user)
    jid = result["processing_job"].job_id
    owner = SpaceCopyOwner(app)
    access = SpaceCopyAccess(owner)
    monkeypatch.setattr(
        space_copy_access, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=101))
    )
    assert (await access.alist_owned(identity=ctx.user)).data[0]["phase"] == "preparing"

    async def initialize(*args, **kwargs):
        status = (await access.alist_owned(identity=ctx.user)).data[0]
        assert status["phase"] == "initializing" and status["job_state"] == "running"
        assert await SpaceCopyOwner(app).astart(jid, 0) is None
        raise RuntimeError("index transport failed")

    monkeypatch.setattr(owner, "aensure_logical", initialize)
    with pytest.raises(RuntimeError, match="index transport failed"):
        await owner.astart(jid, 0)
    failed, _ = await owner.aread(jid)
    assert failed.state == "failed" and failed.lease_token is None
    assert (await access.alist_owned(identity=ctx.user)).data[0]["phase"] == "failed"
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(202)
    try:
        assert (await access.alist_owned(identity=ctx.user)).data == []
    finally:
        current_tenant_id.reset(token)


@pytest.fixture
def schema_utils(monkeypatch):
    import importlib.util
    from pathlib import Path

    from bisheng.knowledge.application import space_copy_owner

    # Root conftest replaces KnowledgeUtils with a placeholder. Execute its
    # original implementation under a private name, isolating transports only.
    path = Path(__file__).resolve().parents[2] / "bisheng/knowledge/domain/services/knowledge_utils.py"
    spec = importlib.util.spec_from_file_location("_copy_schema_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(space_copy_owner, "KnowledgeUtils", module.KnowledgeUtils)
    return module


async def test_new_copy_bootstraps_lazy_milvus_collection_before_load(monkeypatch, schema_utils):
    knowledge_utils = schema_utils

    events = []
    collection = SimpleNamespace(load=Mock(side_effect=lambda: events.append("load")))
    vector = SimpleNamespace(col=None)

    def seed(*, texts, metadatas):
        assert texts == ["init_schema"] and metadatas[0]["knowledge_id"] == 50
        assert metadatas[0]["document_id"] == 0
        events.append("seed")
        vector.col = collection
        return ["schema-seed"]

    vector.add_texts = Mock(side_effect=seed)
    vector.delete = Mock(side_effect=lambda **kw: events.append(("delete", kw["ids"])))
    redis = SimpleNamespace(get=Mock(return_value=None), setNx=Mock(return_value=True), set=Mock(), delete=Mock())
    monkeypatch.setattr(knowledge_utils, "get_redis_client_sync", lambda: redis)
    milvus = AsyncMock(return_value=vector)
    es = SimpleNamespace(
        _store=SimpleNamespace(_create_index_if_not_exists=Mock(side_effect=lambda: events.append("es"))),
        client=SimpleNamespace(close=AsyncMock()),
    )
    elastic = AsyncMock(return_value=es)
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_vectorstore", milvus)
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_es_vectorstore", elastic)
    root = Knowledge(id=50, tenant_id=101, name="New copy", type=3, collection_name="new-copy", index_name="new-copy")
    session = object()
    await initialize_indexes(root, 7, session=session)
    assert events == ["seed", ("delete", ["schema-seed"]), "load", "es"]
    assert milvus.call_args.kwargs["reference_session"] is session
    assert elastic.call_args.kwargs["reference_session"] is session
    es.client.close.assert_awaited_once()


async def test_copy_schema_bootstrap_failure_does_not_advance_to_es(monkeypatch, schema_utils):
    knowledge_utils = schema_utils

    def fail(**kwargs):
        raise RuntimeError("embedding bootstrap failed")

    vector = SimpleNamespace(col=None, add_texts=Mock(side_effect=fail))
    redis = SimpleNamespace(get=Mock(return_value=None), setNx=Mock(return_value=True), delete=Mock())
    monkeypatch.setattr(knowledge_utils, "get_redis_client_sync", lambda: redis)
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock(return_value=vector))
    elastic = AsyncMock()
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_es_vectorstore", elastic)
    root = Knowledge(id=50, tenant_id=101, name="New copy", type=3, collection_name="new-copy", index_name="new-copy")
    with pytest.raises(RuntimeError, match="embedding bootstrap failed"):
        await initialize_indexes(root, 7, session=object())
    elastic.assert_not_awaited()
    redis.delete.assert_called_once()
