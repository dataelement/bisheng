"""Real legacy creation joins Knowledge/R2/projection before its one commit.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
External model/index transports are doubles; SQL, target verification and the
legacy service entry points are real. No middleware connection is permitted.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeNoEmbeddingError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services import knowledge_service as module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
def creation(business, monkeypatch):
    @contextmanager
    def sync_sessions():
        with Session(business.sync, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def async_sessions():
        async with business.sessions() as session:
            yield session

    monkeypatch.setattr(module, "get_sync_db_session", sync_sessions, raising=False)
    monkeypatch.setattr(module, "get_async_db_session", async_sessions, raising=False)
    # An old DAO call would open an unrelated middleware Session: fail locally.
    monkeypatch.setattr(module.KnowledgeDao, "insert_one", Mock(side_effect=AssertionError("separate DAO insert")))
    monkeypatch.setattr(
        module.KnowledgeDao, "async_insert_one", AsyncMock(side_effect=AssertionError("separate DAO insert"))
    )
    monkeypatch.setattr(KnowledgeService, "_init_knowledge_indices_sync", Mock())
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock())
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", AsyncMock())
    monkeypatch.setattr(KnowledgeService, "ensure_milvus_schema_ready", Mock())
    monkeypatch.setattr(KnowledgeService, "create_knowledge_hook", Mock())
    monkeypatch.setattr(KnowledgeService.audit_telemetry_service, "audit_create_knowledge", Mock())
    monkeypatch.setattr(KnowledgeService.audit_telemetry_service, "telemetry_new_knowledge", Mock())
    projection = AsyncMock()
    monkeypatch.setattr(KnowledgeService, "_project_library_created", projection)
    return business, projection


async def create(context, *, asynchronous, model="11", kind=1):
    row = Knowledge(name="actual created", type=kind, model=model)
    if asynchronous:
        actual = await KnowledgeService.acreate_knowledge_base(None, context.user, row)
    else:
        actual = await asyncio.to_thread(KnowledgeService.create_knowledge_base, None, context.user, row)
    return row, actual


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_actual_legacy_creation_persists_one_exact_source_before_index_io(creation, asynchronous):
    context, projection = creation
    before = fixtures.state(context)
    row, actual = await create(context, asynchronous=asynchronous)
    assert actual is row and row.id is not None
    projection.assert_awaited_once_with(context.user, row)
    after = fixtures.state(context)
    assert len(after["knowledge"]) == len(before["knowledge"]) + 1
    refs = [item for item in after["business_resource_reference"] if item["source_id"] == str(row.id)]
    assert [(item["slot_key"], item["target_id"]) for item in refs] == [("model", "11")]
    assert row.tenant_id == 101 and row.user_id == context.user.user_id


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_permission_projection_failure_rolls_back_actual_row_and_refs(creation, asynchronous):
    context, projection = creation
    before = fixtures.state(context)
    projection.side_effect = RuntimeError("projection unavailable")
    with pytest.raises(RuntimeError, match="projection unavailable"):
        await create(context, asynchronous=asynchronous)
    assert fixtures.state(context) == before
    KnowledgeService._init_knowledge_indices_sync.assert_not_called()
    module.KnowledgeRag.init_knowledge_milvus_vectorstore.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_actual_wrong_model_kind_is_not_projected_or_persisted(creation, asynchronous):
    context, projection = creation
    before = fixtures.state(context)
    with pytest.raises(KnowledgeNoEmbeddingError):
        await create(context, asynchronous=asynchronous, model="33")
    assert fixtures.state(context) == before
    projection.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_selected_management_tenant_not_identity_home_owns_created_source(creation, asynchronous):
    context, _ = creation
    # The authoritative pin remains 101 while a super administrator's JWT home
    # may be Root. Preserve this actual object and its ambient actor unchanged.
    context.user.tenant_id = 1
    row, actual = await create(context, asynchronous=asynchronous)
    assert actual is row and row.tenant_id == 101
    assert context.user.tenant_id == 1
