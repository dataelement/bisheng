"""T584 actual document/QA deletion must survive an unavailable model.

覆盖 AC: AC-68, AC-71, AC-79, AC-83, AC-89, AC-92, AC-94.
Real owned-resource SQL and cleanup constructors; only vector transports are doubles.
"""

import asyncio

import pytest
import sqlalchemy as sa

from bisheng.api.services import knowledge_imp
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.domain.models.llm_server import LLMModel
from test.knowledge_unification import test_kn_cleanup_model_independence as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
rag = fixtures.rag
cleanup = fixtures.cleanup
module = fixtures.module


@pytest.mark.parametrize("qa", [False, True])
async def test_actual_file_and_qa_vector_deletion_does_not_consume_a_deleted_model(cleanup, qa):
    context, actual, _, _ = cleanup
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    if qa:
        result = await asyncio.to_thread(knowledge_imp.delete_vector_data, actual, [61, 62])
    else:
        result = await asyncio.to_thread(knowledge_imp.delete_vector_files, [61, 62], actual)
    assert result is True
    vector = module.MilvusFactory.init_vectorstore.return_value
    es = module.ElasticsearchFactory.init_vectorstore_sync.return_value
    assert module.MilvusFactory.init_vectorstore.call_args.args[0] == "actual_collection"
    assert module.ElasticsearchFactory.init_vectorstore_sync.call_args.args[0] == "actual_index"
    if qa:
        vector.col.delete.assert_called_once_with("file_id in [61, 62]", timeout=10)
        assert es.client.delete_by_query.call_args.kwargs == {
            "index": "actual_index",
            "body": {"query": {"terms": {"metadata.file_id": [61, 62]}}},
        }
    else:
        vector.col.delete.assert_called_once_with(expr="document_id in [61, 62]", timeout=10)
        assert es.client.delete_by_query.call_args.kwargs == {
            "index": "actual_index",
            "query": {"terms": {"metadata.document_id": [61, 62]}},
        }
    module.LLMService.get_bisheng_knowledge_embedding_sync.assert_not_called()
    module.LLMService.get_bisheng_knowledge_embedding.assert_not_awaited()


@pytest.mark.parametrize("qa", [False, True])
@pytest.mark.parametrize("changed", ["tenant_id", "collection_name", "index_name"])
async def test_actual_delete_rejects_a_redirected_resource_before_vector_io(cleanup, qa, changed):
    _, actual, _, _ = cleanup
    setattr(actual, changed, 202 if changed == "tenant_id" else "redirected_index")
    with pytest.raises(ResourceReferenceInvalidError):
        if qa:
            await asyncio.to_thread(knowledge_imp.delete_vector_data, actual, [61])
        else:
            await asyncio.to_thread(knowledge_imp.delete_vector_files, [61], actual)
    module.MilvusFactory.init_vectorstore.assert_not_called()
    module.ElasticsearchFactory.init_vectorstore_sync.assert_not_called()


async def test_empty_document_deletion_still_has_no_external_effect(cleanup):
    _, actual, _, _ = cleanup
    assert knowledge_imp.delete_vector_files([], actual) is True
    module.MilvusFactory.init_vectorstore.assert_not_called()
    module.ElasticsearchFactory.init_vectorstore_sync.assert_not_called()
