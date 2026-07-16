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


def test_chat_schema_accepts_more_than_50_knowledge_spaces():
    knowledge_space_ids = list(range(1, 68))

    payload = APIChatCompletion(
        clientTimestamp='2026-07-16T15:53:21',
        model='821',
        use_knowledge_base={'knowledge_space_ids': knowledge_space_ids},
    )

    assert payload.use_knowledge_base.knowledge_space_ids == knowledge_space_ids


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
    captured_kwargs = {'milvus': [], 'es': []}

    async def _split_ids(**_kwargs):
        return [], [7101]

    knowledge = SimpleNamespace(
        id=7101,
        name='团队知识库',
        model='88',
        collection_name='milvus-7101',
        index_name='es-7101',
    )

    class _FakeEmbeddings:
        async def aembed_query(self, text):
            assert text == '流程'
            return [0.1, 0.2]

    class _FakeMilvus:
        async def asimilarity_search_with_relevance_scores_by_vector(self, _vector, **kwargs):
            captured_kwargs['milvus'].append(kwargs)
            return [
                (Document(page_content='允许文件内容', metadata={'document_id': 9001}), 0.95),
                (Document(page_content='越界文件内容', metadata={'document_id': 9999}), 0.99),
            ]

    class _FakeEs:
        async def asimilarity_search_with_relevance_scores(self, _question, **kwargs):
            captured_kwargs['es'].append(kwargs)
            return [
                (Document(page_content='允许文件内容', metadata={'document_id': 9001}), 0.9),
                (Document(page_content='越界文件内容', metadata={'document_id': 9999}), 1.0),
            ]

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_split_retrieval_knowledge_ids_by_type',
        AsyncMock(side_effect=_split_ids),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_load_retrieval_knowledge_rows',
        AsyncMock(return_value=[knowledge]),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_resolve_workstation_rerank_model_id',
        AsyncMock(return_value=''),
    )
    embedding_factory = AsyncMock(return_value=_FakeEmbeddings())
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_knowledge_embedding',
        embedding_factory,
    )
    monkeypatch.setattr(
        workstation_service.KnowledgeRag,
        'init_milvus_vectorstore',
        lambda *_args, **_kwargs: _FakeMilvus(),
    )
    monkeypatch.setattr(
        workstation_service.KnowledgeRag,
        'init_es_vectorstore',
        lambda *_args, **_kwargs: _FakeEs(),
    )

    _formatted, docs, failures = await workstation_service.WorkStationService.queryChunksFromDB(
        question='流程',
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=[7101]),
        max_token=15000,
        login_user=_login_user(),
        file_ids_by_space={7101: [9001]},
    )

    assert failures == []
    assert [doc.metadata['document_id'] for doc in docs] == [9001]
    assert all(item['expr'] == 'document_id in [9001]' for item in captured_kwargs['milvus'])
    assert captured_kwargs['es'][0]['filter'] == [
        {'terms': {'metadata.document_id': [9001]}}
    ]


@pytest.mark.asyncio
async def test_query_chunks_skips_spaces_missing_file_filter_when_file_scope(monkeypatch):
    queried_kbs = []

    async def _split_ids(**_kwargs):
        return [], [7101, 7102]

    knowledge_rows = [
        SimpleNamespace(
            id=kb_id,
            name=f'知识库{kb_id}',
            model='88',
            collection_name=f'milvus-{kb_id}',
            index_name=f'es-{kb_id}',
        )
        for kb_id in (7101, 7102)
    ]

    class _FakeEmbeddings:
        async def aembed_query(self, _text):
            return [0.1, 0.2]

    class _FakeMilvus:
        def __init__(self, kb_id):
            self.kb_id = kb_id

        async def asimilarity_search_with_relevance_scores_by_vector(self, _vector, **_kwargs):
            queried_kbs.append(self.kb_id)
            return [
                (
                    Document(
                        page_content=f'知识库{self.kb_id}内容',
                        metadata={
                            'knowledge_id': self.kb_id,
                            'document_id': 9001 if self.kb_id == 7101 else 9201,
                        },
                    ),
                    0.9,
                )
            ]

    class _FakeEs:
        async def asimilarity_search_with_relevance_scores(self, _question, **_kwargs):
            return []

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_split_retrieval_knowledge_ids_by_type',
        AsyncMock(side_effect=_split_ids),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_load_retrieval_knowledge_rows',
        AsyncMock(return_value=knowledge_rows),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_resolve_workstation_rerank_model_id',
        AsyncMock(return_value=''),
    )
    embedding_factory = AsyncMock(return_value=_FakeEmbeddings())
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_knowledge_embedding',
        embedding_factory,
    )
    monkeypatch.setattr(
        workstation_service.KnowledgeRag,
        'init_milvus_vectorstore',
        lambda collection_name, *_args, **_kwargs: _FakeMilvus(
            int(collection_name.rsplit('-', 1)[-1])
        ),
    )
    monkeypatch.setattr(
        workstation_service.KnowledgeRag,
        'init_es_vectorstore',
        lambda *_args, **_kwargs: _FakeEs(),
    )

    _formatted, docs, failures = await workstation_service.WorkStationService.queryChunksFromDB(
        question='流程',
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=[7101, 7102]),
        max_token=15000,
        login_user=_login_user(),
        file_ids_by_space={7101: [9001]},
    )

    assert failures == []
    assert set(queried_kbs) == {7101}
    assert [doc.metadata['knowledge_id'] for doc in docs] == [7101]
    embedding_factory.assert_awaited_once()


def test_global_rrf_uses_chunk_identity_instead_of_page_content():
    kb1_vector = Document(
        page_content='相同正文',
        metadata={'knowledge_id': 7101, 'document_id': 9001, 'chunk_index': 0},
    )
    kb1_es = Document(
        page_content='相同正文',
        metadata={'knowledge_id': 7101, 'document_id': 9001, 'chunk_index': 0},
    )
    kb2_vector = Document(
        page_content='相同正文',
        metadata={'knowledge_id': 7102, 'document_id': 9201, 'chunk_index': 0},
    )

    result = workstation_service.WorkStationService._global_rrf_merge(
        [([kb1_vector, kb2_vector], 1.0), ([kb1_es], 1.0)],
        limit=10,
    )

    assert len(result) == 2
    assert [doc.metadata['knowledge_id'] for doc in result] == [7101, 7102]
    assert result[0].metadata['rrf_score'] > result[1].metadata['rrf_score']


def test_final_retrieval_is_truncated_by_global_character_limit():
    docs = [
        Document(page_content='甲' * 40, metadata={'document_name': '一.doc'}),
        Document(page_content='乙' * 40, metadata={'document_name': '二.doc'}),
    ]
    first_block_length = len(
        workstation_service.WorkStationService._format_retrieval_document(docs[0])
    )

    formatted, selected = (
        workstation_service.WorkStationService._truncate_ranked_documents_by_chars(
            docs,
            first_block_length,
        )
    )

    assert selected == [docs[0]]
    assert len('\n'.join(formatted)) == first_block_length


def test_single_oversized_top_chunk_is_shortened_to_character_limit():
    doc = Document(page_content='超长内容' * 100, metadata={'document_name': '长文.doc'})

    formatted, selected = (
        workstation_service.WorkStationService._truncate_ranked_documents_by_chars(
            [doc],
            120,
        )
    )

    assert len('\n'.join(formatted)) <= 120
    assert len(selected) == 1
    assert selected[0].metadata['content_truncated'] is True
    assert len(selected[0].page_content) < len(doc.page_content)


def test_truncated_chunk_keeps_its_citation_marker():
    citation_key = 'citation-id:item-id'
    doc = Document(
        page_content=f'{"正文" * 100}\n\ncitation_key: {citation_key}',
        metadata={'document_name': '长文.doc', 'citation_key': citation_key},
    )

    formatted, selected = (
        workstation_service.WorkStationService._truncate_ranked_documents_by_chars(
            [doc],
            160,
        )
    )

    assert len('\n'.join(formatted)) <= 160
    assert selected[0].page_content.endswith(f'citation_key: {citation_key}')


@pytest.mark.asyncio
async def test_missing_rerank_model_keeps_global_rrf_order(monkeypatch):
    docs = [
        Document(page_content='第一条', metadata={'knowledge_id': 1, 'document_id': 1}),
        Document(page_content='第二条', metadata={'knowledge_id': 2, 'document_id': 2}),
    ]
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_resolve_workstation_rerank_model_id',
        AsyncMock(return_value=''),
    )
    rerank_factory = AsyncMock()
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_rerank',
        rerank_factory,
    )

    result = await workstation_service.WorkStationService._rerank_retrieval_candidates(
        question='问题',
        candidates=docs,
    )

    assert result == docs
    rerank_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_rerank_batches_candidates_and_merges_scores(monkeypatch):
    docs = [
        Document(
            page_content=str(index),
            metadata={'knowledge_id': 1, 'document_id': index},
        )
        for index in range(40)
    ]

    class _FakeRerank:
        async def acompress_documents(self, *, documents, query):
            assert query == '问题'
            for doc in documents:
                doc.metadata['relevance_score'] = float(doc.page_content)
            return list(reversed(documents))

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_resolve_workstation_rerank_model_id',
        AsyncMock(return_value='99'),
    )
    rerank_factory = AsyncMock(return_value=_FakeRerank())
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_rerank',
        rerank_factory,
    )

    result = await workstation_service.WorkStationService._rerank_retrieval_candidates(
        question='问题',
        candidates=docs,
    )

    assert [doc.page_content for doc in result[:3]] == ['39', '38', '37']
    rerank_factory.assert_awaited_once_with(model_id=99)


@pytest.mark.asyncio
async def test_rerank_error_falls_back_to_global_rrf_order(monkeypatch):
    docs = [
        Document(page_content='第一条', metadata={'knowledge_id': 1, 'document_id': 1}),
        Document(page_content='第二条', metadata={'knowledge_id': 2, 'document_id': 2}),
    ]

    class _BrokenRerank:
        async def acompress_documents(self, *, documents, query):
            raise RuntimeError('rerank unavailable')

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_resolve_workstation_rerank_model_id',
        AsyncMock(return_value='99'),
    )
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_rerank',
        AsyncMock(return_value=_BrokenRerank()),
    )

    result = await workstation_service.WorkStationService._rerank_retrieval_candidates(
        question='问题',
        candidates=docs,
    )

    assert result == docs


@pytest.mark.asyncio
async def test_probe_reuses_one_query_embedding_for_spaces_with_same_model(monkeypatch):
    knowledge_rows = [
        SimpleNamespace(
            id=kb_id,
            name=f'知识库{kb_id}',
            model='88',
            collection_name=f'milvus-{kb_id}',
            index_name=f'es-{kb_id}',
        )
        for kb_id in (7101, 7102, 7103)
    ]

    class _FakeEmbeddings:
        def __init__(self):
            self.query_count = 0

        async def aembed_query(self, _text):
            self.query_count += 1
            return [0.1, 0.2]

    class _FakeMilvus:
        def __init__(self, kb_id):
            self.kb_id = kb_id

        async def asimilarity_search_with_relevance_scores_by_vector(self, _vector, **_kwargs):
            return [
                (
                    Document(
                        page_content=f'内容{self.kb_id}',
                        metadata={'document_id': self.kb_id},
                    ),
                    0.9,
                )
            ]

    embeddings = _FakeEmbeddings()
    embedding_factory = AsyncMock(return_value=embeddings)
    monkeypatch.setattr(
        workstation_service.LLMService,
        'get_bisheng_knowledge_embedding',
        embedding_factory,
    )
    monkeypatch.setattr(
        workstation_service.KnowledgeRag,
        'init_milvus_vectorstore',
        lambda collection_name, *_args, **_kwargs: _FakeMilvus(
            int(collection_name.rsplit('-', 1)[-1])
        ),
    )

    infos, failures = (
        await workstation_service.WorkStationService._probe_retrieval_knowledge_rows(
            question='流程',
            knowledge_rows=knowledge_rows,
            login_user=_login_user(),
            file_ids_by_space=None,
        )
    )

    assert failures == []
    assert len(infos) == 3
    embedding_factory.assert_awaited_once_with(invoke_user_id=7, model_id=88)
    assert embeddings.query_count == 1


@pytest.mark.asyncio
async def test_query_only_deep_retrieves_top_twenty_probe_spaces(monkeypatch):
    knowledge_rows = [
        SimpleNamespace(id=kb_id, name=f'知识库{kb_id}')
        for kb_id in range(1, 26)
    ]
    probe_infos = [
        {
            'knowledge': row,
            'probe_score': float(row.id),
            'probe_docs': [
                Document(
                    page_content=f'内容{row.id}',
                    metadata={'knowledge_id': row.id, 'document_id': row.id},
                )
            ],
        }
        for row in knowledge_rows
    ]
    captured_selected_ids = []

    async def _deep_retrieve(*, selected_infos, **_kwargs):
        captured_selected_ids.extend(int(info['knowledge'].id) for info in selected_infos)
        return [
            (
                [doc for info in selected_infos for doc in info['probe_docs']],
                1.0,
            )
        ], []

    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_split_retrieval_knowledge_ids_by_type',
        AsyncMock(return_value=([], list(range(1, 26)))),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_load_retrieval_knowledge_rows',
        AsyncMock(return_value=knowledge_rows),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_probe_retrieval_knowledge_rows',
        AsyncMock(return_value=(probe_infos, [])),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_deep_retrieve_selected_knowledge',
        AsyncMock(side_effect=_deep_retrieve),
    )
    monkeypatch.setattr(
        workstation_service.WorkStationService,
        '_rerank_retrieval_candidates',
        AsyncMock(side_effect=lambda *, candidates, **_kwargs: candidates),
    )

    _formatted, docs, failures = await workstation_service.WorkStationService.queryChunksFromDB(
        question='流程',
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=list(range(1, 26))),
        max_token=100000,
        login_user=_login_user(),
    )

    assert failures == []
    assert captured_selected_ids == list(range(25, 5, -1))
    assert len(docs) == 20
