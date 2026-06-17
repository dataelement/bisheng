import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

base_service_stub = types.ModuleType('bisheng.common.services.base')


class _BaseService:
    pass


base_service_stub.BaseService = _BaseService
sys.modules['bisheng.common.services.base'] = base_service_stub
workstation_service = importlib.reload(
    importlib.import_module('bisheng.workstation.domain.services.workstation_service')
)

from bisheng.api.v1.schema.chat_schema import APIChatCompletion, UseKnowledgeBaseParam
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.workstation.domain.services import chat_service

chat_service.WorkStationService = workstation_service.WorkStationService


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=7, user_name='tester')


def test_chat_schema_accepts_optional_files_scope_and_keeps_old_payload_valid():
    legacy = UseKnowledgeBaseParam(knowledge_space_ids=[7101])
    scoped = UseKnowledgeBaseParam(
        knowledge_space_ids=[7101, 7102],
        knowledge_scope={
            'mode': 'files',
            'folder_refs': [{'knowledge_space_id': 7101, 'folder_id': 3001}],
            'file_refs': [{'knowledge_space_id': 7102, 'file_id': 9201}],
        },
    )

    assert legacy.knowledge_scope is None
    assert scoped.knowledge_scope.mode == 'files'
    assert scoped.knowledge_scope.folder_refs[0].folder_id == 3001
    assert scoped.knowledge_scope.file_refs[0].knowledge_space_id == 7102


@pytest.mark.asyncio
async def test_pre_retrieve_passes_resolved_file_filters_to_query_chunks(monkeypatch):
    query_chunks = AsyncMock(return_value=([], [], []))
    monkeypatch.setattr(chat_service.WorkStationService, 'queryChunksFromDB', query_chunks, raising=False)

    await chat_service._retrieve_selected_knowledge_context(
        question='只查选中的文件',
        knowledge_bases_info=[
            {
                'id': 7101,
                'source': 'space',
                'type': KnowledgeTypeEnum.SPACE.value,
            }
        ],
        max_token=15000,
        login_user=_login_user(),
        citation_collector=MagicMock(),
        file_ids_by_space={7101: [9001, 9002]},
    )

    assert query_chunks.await_args.kwargs['file_ids_by_space'] == {7101: [9001, 9002]}


@pytest.mark.asyncio
async def test_resolve_user_kb_file_filters_uses_knowledge_space_service(monkeypatch):
    data = APIChatCompletion(
        clientTimestamp='2026-06-17T10:00:00',
        model='10',
        text='问答',
        use_knowledge_base=UseKnowledgeBaseParam(
            knowledge_space_ids=[7101],
            knowledge_scope={
                'mode': 'files',
                'folder_refs': [{'knowledge_space_id': 7101, 'folder_id': 3001}],
                'file_refs': [{'knowledge_space_id': 7101, 'file_id': 9001}],
            },
        ),
    )

    class _FakeKnowledgeSpaceService:
        def __init__(self, request, login_user):
            self.request = request
            self.login_user = login_user

        async def resolve_qa_scope_file_ids(self, *, folder_refs, file_refs, max_files):
            assert folder_refs[0].folder_id == 3001
            assert file_refs[0].file_id == 9001
            assert max_files == 20
            return {7101: [9001, 9002]}

    monkeypatch.setattr(chat_service, 'KnowledgeSpaceService', _FakeKnowledgeSpaceService, raising=False)

    result = await chat_service._resolve_user_kb_file_filters(
        request=SimpleNamespace(),
        data=data,
        login_user=_login_user(),
    )

    assert result == {7101: [9001, 9002]}


@pytest.mark.asyncio
async def test_query_chunks_applies_file_filter_to_vector_and_es_and_post_filters(monkeypatch):
    captured_kwargs = {}

    async def _split_ids(**_kwargs):
        return [], [7101]

    async def _get_vectors(*, invoke_user_id, knowledge_ids, **_kwargs):
        if not knowledge_ids:
            return {}
        return {
            7101: {
                'milvus': object(),
                'es': object(),
                'knowledge': SimpleNamespace(name='团队知识库'),
            }
        }

    class _FakeTool:
        def __init__(self, vector_retriever=None, elastic_retriever=None, **_kwargs):
            captured_kwargs['milvus'] = vector_retriever.search_kwargs
            captured_kwargs['es'] = elastic_retriever.search_kwargs

        async def ainvoke(self, _payload):
            return [
                Document(page_content='允许文件内容', metadata={'knowledge_id': 7101, 'document_id': 9001}),
                Document(page_content='越界文件内容', metadata={'knowledge_id': 7101, 'document_id': 9999}),
            ]

    class _FakeMultiRetriever:
        def __init__(self, *, vectors=None, search_kwargs=None, finally_k=None):
            self.vectors = vectors
            self.search_kwargs = search_kwargs
            self.finally_k = finally_k

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_split_retrieval_knowledge_ids_by_type',
        AsyncMock(side_effect=_split_ids),
    )
    monkeypatch.setattr(workstation_service.KnowledgeRag, 'get_multi_knowledge_vectorstore', _get_vectors)
    monkeypatch.setattr(workstation_service, 'MultiRetriever', _FakeMultiRetriever)
    monkeypatch.setattr(workstation_service, 'KnowledgeRetrieverTool', _FakeTool)

    _formatted, docs, failures = await workstation_service.WorkStationService.queryChunksFromDB(
        question='流程',
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=[7101]),
        max_token=15000,
        login_user=_login_user(),
        file_ids_by_space={7101: [9001]},
    )

    assert failures == []
    assert [doc.metadata['document_id'] for doc in docs] == [9001]
    assert captured_kwargs['milvus'][0]['expr'] == 'document_id in [9001]'
    assert captured_kwargs['es'][0]['filter'] == [{'terms': {'metadata.document_id': [9001]}}]


@pytest.mark.asyncio
async def test_query_chunks_skips_spaces_missing_file_filter_when_file_scope(monkeypatch):
    queried_kbs = []

    async def _split_ids(**_kwargs):
        return [], [7101, 7102]

    async def _get_vectors(*, invoke_user_id, knowledge_ids, **_kwargs):
        if not knowledge_ids:
            return {}
        return {
            kb_id: {
                'milvus': f'milvus-{kb_id}',
                'es': f'es-{kb_id}',
                'knowledge': SimpleNamespace(name=f'知识库{kb_id}'),
            }
            for kb_id in knowledge_ids
        }

    class _FakeTool:
        def __init__(self, vector_retriever=None, elastic_retriever=None, **_kwargs):
            self.kb_id = int(str(vector_retriever.vectors[0]).split('-')[-1])
            queried_kbs.append(self.kb_id)

        async def ainvoke(self, _payload):
            return [
                Document(
                    page_content=f'知识库{self.kb_id}内容',
                    metadata={'knowledge_id': self.kb_id, 'document_id': 9001 if self.kb_id == 7101 else 9201},
                )
            ]

    class _FakeMultiRetriever:
        def __init__(self, *, vectors=None, search_kwargs=None, finally_k=None):
            self.vectors = vectors
            self.search_kwargs = search_kwargs
            self.finally_k = finally_k

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_split_retrieval_knowledge_ids_by_type',
        AsyncMock(side_effect=_split_ids),
    )
    monkeypatch.setattr(workstation_service.KnowledgeRag, 'get_multi_knowledge_vectorstore', _get_vectors)
    monkeypatch.setattr(workstation_service, 'MultiRetriever', _FakeMultiRetriever)
    monkeypatch.setattr(workstation_service, 'KnowledgeRetrieverTool', _FakeTool)

    _formatted, docs, failures = await workstation_service.WorkStationService.queryChunksFromDB(
        question='流程',
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=[7101, 7102]),
        max_token=15000,
        login_user=_login_user(),
        file_ids_by_space={7101: [9001]},
    )

    assert failures == []
    assert queried_kbs == [7101]
    assert [doc.metadata['knowledge_id'] for doc in docs] == [7101]
