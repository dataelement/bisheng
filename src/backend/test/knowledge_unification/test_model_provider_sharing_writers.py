"""Original provider sharing and status writers share the deletion fence."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.database.models import tenant as tenant_module
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application import model_sharing
from bisheng.llm.domain.models import llm_server as model_module
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel
from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


async def install_sharing(business, monkeypatch):
    factory, deletion, references, plans, _ = business
    app = model_sharing.ModelSharingApplication(
        references=references,
        plans=plans,
        session_factory=factory,
        sharing_factory=deletion.sharing_factory,
    )

    async def application():
        return app

    monkeypatch.setattr(model_sharing, "get_model_sharing_application", application)
    monkeypatch.setattr(tenant_module, "get_async_db_session", factory)
    monkeypatch.setattr(model_module, "get_async_db_session", factory)
    async with factory() as session:
        async with session.begin():
            await session.execute(sa.update(Tenant).where(Tenant.id.in_((101, 202))).values(parent_tenant_id=1))
    return app


async def test_original_share_entry_reserves_even_zero_delta_and_revokes_inactive_history_without_coverage(
    business, monkeypatch
):
    factory, _, references, _, client = business
    await install_sharing(business, monkeypatch)
    references.coverage_factory = None  # Ordinary sharing must not acquire the deletion Coverage gate.
    client.rows = {("tenant:900001", "shared_with", "llm_server:2")}
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        assert await ResourceShareService.enable_sharing("llm_server", "2", operator=user) == [101, 202]
        assert len(client.rows) == 3
        writes = len(client.writes)
        assert await ResourceShareService.enable_sharing("llm_server", "2", operator=user) == [101, 202]
        assert len(client.writes) == writes
        assert await ResourceShareService.disable_sharing("llm_server", "2", operator=user) == [101, 202, 900001]
        assert not client.rows
        async with factory() as session:
            rows = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()
            assert len(rows) == 3 and all(row.model_execution_state == "COMPLETED" for row in rows)
            assert all(row.operation == "model_share_server" and not row.target_manifest for row in rows)


async def test_real_share_reservation_blocks_status_online_and_competing_deletion_until_same_command_resumes(
    business, monkeypatch
):
    factory, deletion, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original = app._permission

    async def unavailable(*args, **kwargs):
        raise ConnectionError("permission transport unavailable after durable reserve")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        monkeypatch.setattr(app, "_permission", unavailable)
        with pytest.raises(ConnectionError):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
        for mutation in (
            lambda: LLMDao.aupdate_model_status(22, 1, "probe"),
            lambda: LLMDao.aupdate_model_online(22, False),
            lambda: deletion.adelete_server(identity=user, server_id=2),
        ):
            with pytest.raises(KnowledgeProcessingConflictError):
                await mutation()
        async with factory() as session:
            row = await session.get(LLMModel, 22)
            assert row.online is True and row.status == 2
        monkeypatch.setattr(app, "_permission", original)
        user.token_version = 4
        user._runtime_credential_reference = {**user._runtime_credential_reference, "token_version": 4}
        assert await app.aset_sharing(identity=user, server_id=2, enabled=True) == [101, 202]
        await LLMDao.aupdate_model_online(22, False)
        assert len(client.rows) == 2


async def test_unidentified_internal_llm_share_cannot_create_a_reservation_or_transport_mutation(business):
    factory, _, _, _, client = business
    with pytest.raises(ValueError, match="original authorized operator"):
        await ResourceShareService.enable_sharing("llm_server", "2")
    async with factory() as session:
        assert not (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()
    assert not client.writes
