"""Provider-locked intent and immutable new-receiver manifests."""

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.model_sharing_intent import ModelSharingInitialization, ModelSharingIntent
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


class ModelSharingIntentRepository:
    @staticmethod
    def _context(session):
        tenant, transaction = ModelProviderOperationRepository._native(session)
        if tenant != ROOT_TENANT_ID:
            raise KnowledgeOperationPlanChangedError()
        return tenant, transaction

    @staticmethod
    def _check(session, context):
        tenant, transaction = context
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant or session.new or session.dirty or session.deleted:
            raise KnowledgeOperationPlanChangedError()

    async def aread(self, session, *, server_id):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(select(ModelSharingIntent).where(ModelSharingIntent.server_id == server_id))
            ).scalar_one_or_none()
        self._check(session, context)
        return row

    async def aenabled_server_ids(self, session):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            ids = tuple(
                (
                    await session.execute(
                        select(ModelSharingIntent.server_id)
                        .join(LLMServer, LLMServer.id == ModelSharingIntent.server_id)
                        .where(ModelSharingIntent.enabled.is_(True), LLMServer.tenant_id == ROOT_TENANT_ID)
                        .order_by(ModelSharingIntent.server_id)
                    )
                ).scalars()
            )
        self._check(session, context)
        return ids

    async def aset(self, session, *, server_id, enabled, plan_id):
        context = self._context(session)
        row = await self.aread(session, server_id=server_id)
        if row is None:
            row = ModelSharingIntent(
                server_id=server_id, tenant_id=ROOT_TENANT_ID, enabled=enabled, version=1, plan_id=plan_id
            )
        elif row.plan_id == plan_id:
            if row.enabled != enabled:
                raise KnowledgeOperationPlanChangedError()
            return
        else:
            row.enabled, row.version, row.plan_id = enabled, row.version + 1, plan_id
        session.add(row)
        await session.flush()
        self._check(session, context)

    async def afreeze_initialization(self, session, *, plan_id, server_id, child_ids, retained_ids=None):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            models = tuple(
                (
                    await session.execute(
                        select(LLMModel.id)
                        .where(LLMModel.server_id == server_id, LLMModel.model_type == "llm")
                        .order_by(LLMModel.id)
                    )
                ).scalars()
            )
        self._check(session, context)
        session.add(
            ModelSharingInitialization(
                plan_id=plan_id,
                server_id=server_id,
                tenant_id=ROOT_TENANT_ID,
                child_ids=sorted(set(child_ids)),
                model_ids=[value for value in models if retained_ids is None or value in retained_ids],
            )
        )
        await session.flush()
        self._check(session, context)

    async def aread_initialization(self, session, *, plan_id):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(ModelSharingInitialization).where(ModelSharingInitialization.plan_id == plan_id)
                )
            ).scalar_one_or_none()
        self._check(session, context)
        return row

    async def adialogue_model_ids(self, session, *, server_id, model_ids):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            ids = tuple(
                (
                    await session.execute(
                        select(LLMModel.id)
                        .where(
                            LLMModel.server_id == server_id, LLMModel.id.in_(model_ids), LLMModel.model_type == "llm"
                        )
                        .order_by(LLMModel.id)
                    )
                ).scalars()
            )
        self._check(session, context)
        return ids

    async def aactive_children(self, session):
        context = self._context(session)
        with session.no_autoflush, bypass_tenant_filter():
            ids = tuple(
                (
                    await session.execute(
                        select(Tenant.id)
                        .where(Tenant.parent_tenant_id == ROOT_TENANT_ID, Tenant.status == "active")
                        .order_by(Tenant.id)
                    )
                ).scalars()
            )
        self._check(session, context)
        return ids
