"""F026 request wiring across workflow and controlled retrieval."""
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text

from bisheng.knowledge.application.provider_retrieval import WeKnoraSearchPort, RetrievalSelection
from bisheng.knowledge.domain.services import space_flow_retrieval as flow
from test.knowledge.test_f026_search import case, retrieve  # noqa: F401


async def test_nil_go_slice_is_empty_not_protocol_failure():
    async with httpx.AsyncClient(base_url='https://fixture/', transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'success':True,'data':None}))) as c:
        assert await WeKnoraSearchPort(c, NS(remote_kb_id='kb')).recall('q', {'A'}) == []


@pytest.mark.parametrize('statement,unusable', [('update knowledge_provider_generation set state=\'retired\'', True), ('update knowledge_provider_mapping set ready_revision=9',False)])
async def test_generation_proof_before_recall(case, statement, unusable):
    async with case[0].provider_retrieval.repository.session() as s:
        await s.execute(text(statement)); await s.commit()
    if unusable:
        with pytest.raises(ValueError): await retrieve(case, RetrievalSelection())
    else:
        assert await retrieve(case, RetrievalSelection()) == []
    assert not case[2]


async def test_workflow_identity_and_revocation(case, monkeypatch):
    providers, space = case[0].provider_retrieval, case[1]
    @asynccontextmanager
    async def runtime():
        yield providers
    monkeypatch.setattr(flow, 'request_provider_retrieval', runtime)
    monkeypatch.setattr('bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id', AsyncMock(return_value=space))
    permissions={7:{1}, 9:{3}}
    def visibility(request, identity):
        async def allowed(space_id, ids): return permissions[identity.user_id] & set(ids)
        return NS(post_filter_visible_files=allowed)
    monkeypatch.setattr('bisheng.knowledge.domain.services.knowledge_file_visibility_service.KnowledgeFileVisibilityService', visibility)
    for user, scope, expected in [(7,'per_user',[1]),(9,'shared',[3]),(7,'per_user',[])]:
        hits = await flow.aretrieve_space_documents(space_ids=[2],query='q',max_content=256,identity_user=NS(user_id=user),access_scope=scope)
        assert [(d.metadata['document_id'], d.metadata['access_scope']) for d in hits] == [(i,scope) for i in expected]
        permissions[user].clear()


async def test_real_runtime_constrains_authorized_remote_ids(case, monkeypatch):
    from bisheng.knowledge.application.provider_runtime import request_provider_retrieval
    repo=case[0].provider_retrieval.repository
    async with repo.session() as s:
        for stmt in ("alter table knowledge_provider_instance add endpoint", "alter table knowledge_provider_instance add credential_ref", "update knowledge_provider_instance set endpoint='https://server/api/v1/',credential_ref='env:BISHENG_PROVIDER_FIXTURE'", "update knowledge_provider_generation set remote_scope_id=cast('17' as blob)", "update knowledge_provider_instance set remote_scope_id=cast('17' as blob)"):
            await s.execute(text(stmt))
        await s.commit()
    monkeypatch.setenv('BISHENG_PROVIDER_FIXTURE','fixture-token')
    calls=[]
    def respond(req):
        assert req.headers['X-API-Key']=='fixture-token' and 'X-Tenant-ID' not in req.headers
        calls.append(req.url.path)
        if req.method=='GET':
            key=req.url.path.rsplit('/',1)[1]
            assert key in ('R1','R3')
            return httpx.Response(200,json={'success':True,'data':{'id':key,'knowledge_base_id':'kb','tenant_id':17,'tags':[{'id':'tag','knowledge_base_id':'kb'}] if key=='R1' else []}})
        import json
        assert json.loads(req.content)['knowledge_ids']==['R1']
        return httpx.Response(200,json={'success':True,'data':None})
    @asynccontextmanager
    async def client(route):
        async with httpx.AsyncClient(base_url='https://server/api/v1/', transport=httpx.MockTransport(respond), headers={'X-API-Key':'fixture-token'}) as c: yield c
    async with request_provider_retrieval(repository=repo, client_factory=client) as service:
        engine=case[0]; engine.provider_retrieval=service
        assert not await retrieve(case, RetrievalSelection(tag_ref_ids=(8,)))
    assert calls == ['/api/v1/knowledge/R1','/api/v1/knowledge/R3','/api/v1/knowledge-bases/kb/hybrid-search','/api/v1/knowledge/R1','/api/v1/knowledge/R3']
