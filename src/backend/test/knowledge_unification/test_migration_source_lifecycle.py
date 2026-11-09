"""Actual R2 hard deletion must remain a supported formal M2/M4 input."""

from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import AsyncMock
import socket
import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import model_reference as model_app
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.permission.application.identity import set_current_permission_actor, reset_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification.test_permission_publication_application import app
from test.knowledge_unification.permission_publication_native import (raw_resource_native as raw_resource_native, resource_native as resource_native, native as native, complete as complete, transport as transport, published_input as published_factory)

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('no network')))

async def real_r2_create_delete(database):
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(LLMServer(id=88, tenant_id=101, name='own', type='openai'))
        session.add(LLMModel(id=88, tenant_id=101, server_id=88, model_name='own embedding', model_type='embedding', online=True))
    verifier = ReferenceTargetVerifier({'model': ModelReferenceTargetOwner()})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7))
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(model_app, 'get_reference_binding_runtime', AsyncMock(return_value=runtime))
            mp.setattr(model_app, 'require_business_action', AsyncMock())
            async with AsyncSession(database.engine) as session, session.begin():
                row = Knowledge(id=50, tenant_id=101, user_id=7, name='created then deleted', type=0, model='88')
                await model_app.KnowledgeModelReferenceApplication.acreate(session, row, login_user=user, project_created=AsyncMock())
            async with AsyncSession(database.engine) as session, session.begin():
                prepared = await model_app.KnowledgeModelReferenceApplication.aprepare_removal(session, 50, login_user=user)
                await model_app.KnowledgeModelReferenceApplication.aapply_removal(session, prepared)
            async with AsyncSession(database.engine) as session, session.begin():
                assert await session.get(Knowledge, 50) is None
                rows = (await session.execute(sa.select(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id=='50'))).mappings().all()
                assert len(rows)==2
                head = next(row for row in rows if row['record_kind']=='source')
                assert head['ready'] and not head['effective'] and head['source_revision']==2
                assert not (await session.execute(sa.select(BusinessResourceReference.id).where(BusinessResourceReference.source_id=='50'))).all()
                print('ACTUAL_R2_AFTER_DELETE',[(row['record_kind'],row['source_revision'],row['effective'],row['ready']) for row in rows])
    finally:
        reset_current_permission_actor(token)

async def freeze(complete, transport, monkeypatch, seed=None):
    request=SimpleNamespace(param={'reference_seed':seed},node=SimpleNamespace(callspec=None))
    return await published_factory.__wrapped__(complete,transport,monkeypatch,request)

async def test_real_deleted_source_is_frozen_and_only_its_empty_index_is_retired(complete,transport,monkeypatch):
    value=await freeze(complete,transport,monkeypatch,real_r2_create_delete)
    result=await app(value).arun_references(**value.input,operator_id=7)
    assert result.complete
    async with value.sessions() as session,session.begin():
        assert not (await session.execute(sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.source_id=='50'))).all()
    assert await app(value).arun_references(**value.input,operator_id=7)==result

async def test_absent_residual_control_still_completes(complete,transport,monkeypatch):
    value=await freeze(complete,transport,monkeypatch)
    assert (await app(value).arun_references(**value.input,operator_id=7)).complete

async def unknown_active(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session,session.begin():
        await session.execute(sa.update(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id=='50',BusinessReferenceSet.record_kind=='source').values(effective=True))

async def half_bundle(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session,session.begin():
        await session.execute(sa.delete(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id=='50',BusinessReferenceSet.record_kind=='source'))

async def hidden_binding(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session,session.begin():
        session.add(BusinessResourceReference(tenant_id=101,source_type='knowledge',source_id='50',source_version='current',slot_key='model',target_type='model',target_id='88',target_tenant_id=101,source_revision=2))

@pytest.mark.parametrize('seed',[unknown_active,half_bundle,hidden_binding])
async def test_unknown_active_half_or_nonempty_residuals_block_before_freeze(complete,transport,monkeypatch,seed):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await freeze(complete,transport,monkeypatch,seed)
