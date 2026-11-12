"""Permission projection failure rolls back the actual SQL/R2 create transaction.

The original regression was an orphan resource after a failed permission mirror.
The create now leaves Knowledge and bindings uncommitted until projection succeeds;
no compensating DAO transaction is needed. Index transports remain isolated.
"""

from unittest.mock import Mock

import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from test.knowledge_unification import test_kn_model_bindings as bindings
from test.knowledge_unification import test_kn_model_creation as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
creation = fixtures.creation


def _new(*, kind=KnowledgeTypeEnum.QA.value):
    return Knowledge(name="123123123", type=kind, model="11")


async def test_a_failed_permission_mirror_takes_the_row_back_out(creation) -> None:
    context, projection = creation
    before = bindings.state(context)
    projection.side_effect = RuntimeError("authorization_model_migration_required")
    with pytest.raises(RuntimeError, match="authorization_model_migration_required"):
        await KnowledgeService.acreate_knowledge_base(None, context.user, _new())
    assert bindings.state(context) == before
    KnowledgeService._init_knowledge_indices_sync.assert_not_called()
    fixtures.module.KnowledgeRag.init_knowledge_milvus_vectorstore.assert_not_called()


async def test_a_successful_create_keeps_the_row(creation) -> None:
    context, projection = creation
    created = await KnowledgeService.acreate_knowledge_base(None, context.user, _new())
    facts = bindings.state(context)
    assert any(row["id"] == created.id for row in facts["knowledge"])
    assert any(row["source_id"] == str(created.id) for row in facts["business_resource_reference"])
    projection.assert_awaited_once_with(context.user, created)


async def test_the_mirror_is_built_before_any_external_store(creation) -> None:
    """A failed or uncommitted create must never provision external indices."""
    context, projection = creation
    order = []

    async def project(*args, **kwargs):
        order.append("mirror")

    async def milvus(*args, **kwargs):
        assert order == ["mirror"]
        assert any(row["id"] == kwargs["knowledge"].id for row in bindings.state(context)["knowledge"])
        order.append("milvus")
        return Mock()

    async def es(*args, **kwargs):
        order.append("es")
        return Mock()

    projection.side_effect = project
    fixtures.module.KnowledgeRag.init_knowledge_milvus_vectorstore.side_effect = milvus
    fixtures.module.KnowledgeRag.init_knowledge_es_vectorstore.side_effect = es
    await KnowledgeService.acreate_knowledge_base(None, context.user, _new(kind=KnowledgeTypeEnum.NORMAL.value))
    assert order == ["mirror", "milvus", "es"]


async def test_skip_hook_still_skips_the_mirror(creation) -> None:
    """An internal projection owner can opt out; SQL/R2 remains mandatory."""
    context, projection = creation
    projection.reset_mock()
    created = await KnowledgeService.acreate_knowledge_base(None, context.user, _new(), skip_hook=True)
    projection.assert_not_awaited()
    facts = bindings.state(context)
    assert any(row["id"] == created.id for row in facts["knowledge"])
    assert any(row["source_id"] == str(created.id) for row in facts["business_resource_reference"])
