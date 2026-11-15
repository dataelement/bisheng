"""Actual provider/model SQL for the caller-owned deletion transaction."""

from copy import deepcopy

from sqlalchemy import bindparam, delete, select, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.common.errcode.llm import ModelNameRepeatError, ServerExistError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_delete_plan_repository import _hash
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


class ModelMutationRepository:
    @staticmethod
    def _context(session):
        return ModelProviderOperationRepository._native(session)

    @staticmethod
    def _check(session, tenant, transaction):
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant or session.new or session.dirty or session.deleted:
            raise KnowledgeOperationPlanChangedError()

    async def aread_owner_name(self, session):
        tenant, transaction = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            name = (await session.execute(select(Tenant.tenant_name).where(Tenant.id == tenant))).scalar_one_or_none()
        self._check(session, tenant, transaction)
        return name

    async def arequire_unique_name(self, session, *, server_id, name):
        tenant, transaction = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            other = (
                await session.execute(
                    select(LLMServer.id).where(LLMServer.name == name, LLMServer.id != server_id).limit(1)
                )
            ).scalar_one_or_none()
        self._check(session, tenant, transaction)
        if other is not None:
            raise ServerExistError.http_exception(f"<{name}>already exists")

    async def adelete_models(self, session, *, server_id, model_ids):
        tenant, transaction = self._context(session)
        values = tuple(sorted(model_ids))
        if len(values) != len(set(values)) or any(type(value) is not int or value <= 0 for value in values):
            raise KnowledgeOperationPlanChangedError()
        for start in range(0, len(values), 200):
            batch = values[start : start + 200]
            self._check(session, tenant, transaction)
            result = await session.execute(
                delete(LLMModel.__table__).where(
                    LLMModel.__table__.c.tenant_id == tenant,
                    LLMModel.__table__.c.server_id == server_id,
                    LLMModel.__table__.c.id.in_(batch),
                )
            )
            self._check(session, tenant, transaction)
            if result.rowcount != len(batch) or ReferenceRepository.current_tenant_id() != tenant:
                raise KnowledgeOperationPlanChangedError()

    async def adelete_server(self, session, *, server_id, model_ids):
        tenant, transaction = self._context(session)
        await self.adelete_models(session, server_id=server_id, model_ids=model_ids)
        self._check(session, tenant, transaction)
        result = await session.execute(
            delete(LLMServer.__table__).where(
                LLMServer.__table__.c.id == server_id, LLMServer.__table__.c.tenant_id == tenant
            )
        )
        self._check(session, tenant, transaction)
        if result.rowcount != 1 or ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()

    async def aupdate_server(self, session, *, server, merged_config, removed_model_ids, actor_user_id):
        tenant, transaction = self._context(session)
        names = [model.model_name for model in server.models]
        if len(names) != len(set(names)):
            raise ModelNameRepeatError.http_exception()
        await self.arequire_unique_name(session, server_id=server.id, name=server.name)
        await self.adelete_models(session, server_id=server.id, model_ids=removed_model_ids)
        self._check(session, tenant, transaction)
        result = await session.execute(
            update(LLMServer.__table__)
            .where(LLMServer.__table__.c.id == server.id, LLMServer.__table__.c.tenant_id == tenant)
            .values(
                name=server.name,
                description=server.description,
                type=server.type,
                limit_flag=server.limit_flag,
                limit=server.limit,
                config=deepcopy(merged_config),
            )
        )
        self._check(session, tenant, transaction)
        if result.rowcount != 1 or ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        retained, new = [], []
        for model in server.models:
            if model.id is None or (type(model.id) is int and model.id == 0):
                new.append(
                    LLMModel(
                        **model.model_dump(exclude={"id"}),
                        user_id=actor_user_id,
                        tenant_id=tenant,
                        server_id=server.id,
                    )
                )
            elif type(model.id) is int and model.id > 0:
                retained.append(model)
            else:
                raise KnowledgeOperationPlanChangedError()
        physical = LLMModel.__table__
        # Keep the original DAO's writable fields. Existing online/status values
        # are not silently broadened by this transaction refactor.
        statement = (
            update(physical)
            .where(
                physical.c.tenant_id == tenant,
                physical.c.server_id == server.id,
                physical.c.id == bindparam("current_model_id"),
            )
            .values(
                name=bindparam("model_display_name"),
                description=bindparam("model_description"),
                model_name=bindparam("vendor_model_name"),
                model_type=bindparam("model_kind"),
                config=bindparam("model_configuration"),
            )
        )
        for start in range(0, len(retained), 200):
            batch = retained[start : start + 200]
            result = await session.execute(
                statement,
                [
                    {
                        "current_model_id": model.id,
                        "model_display_name": model.name,
                        "model_description": model.description,
                        "vendor_model_name": model.model_name,
                        "model_kind": model.model_type,
                        "model_configuration": deepcopy(model.config),
                    }
                    for model in batch
                ],
            )
            self._check(session, tenant, transaction)
            if result.rowcount != len(batch) or ReferenceRepository.current_tenant_id() != tenant:
                raise KnowledgeOperationPlanChangedError()
        for start in range(0, len(new), 200):
            batch = new[start : start + 200]
            self._check(session, tenant, transaction)
            session.add_all(batch)
            await session.flush()
            self._check(session, tenant, transaction)
            if ReferenceRepository.current_tenant_id() != tenant:
                raise KnowledgeOperationPlanChangedError()
            if settings.dsh.enabled:
                from bisheng.dsh.domain.repositories.new_model_visibility import initialize_new_model_visibility

                await initialize_new_model_visibility(session, batch, actor_user_id)
                self._check(session, tenant, transaction)
        return tuple(model.id for model in new)

    async def aread_result(self, session, *, server_id):
        tenant, transaction = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            server = (
                await session.execute(
                    select(LLMServer).where(LLMServer.id == server_id).execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            self._check(session, tenant, transaction)
        if server is None or server.tenant_id != tenant:
            raise KnowledgeOperationPlanChangedError()
        physical = LLMModel.__table__
        with session.no_autoflush, bypass_tenant_filter():
            rows = (
                await session.execute(
                    select(*physical.c).where(physical.c.server_id == server_id).order_by(physical.c.id)
                )
            ).all()
        self._check(session, tenant, transaction)
        if any(row._mapping["tenant_id"] != tenant for row in rows):
            raise KnowledgeOperationPlanChangedError()
        return server, tuple(LLMModel(**dict(row._mapping)) for row in rows)

    @staticmethod
    def result_digest(server, models):
        # This ACK fingerprint covers the actual written business result. Probe
        # status timestamps may advance after commit; it is not target authority
        # and never replaces the original Owner target/server revisions.
        return _hash(
            {
                "server": server.model_dump(mode="json"),
                "models": [
                    model.model_dump(mode="json", exclude={"status", "remark", "status_update_time", "update_time"})
                    for model in models
                ],
            }
        )

    async def arequire_completed(self, session, *, plan, ack):
        tenant, transaction = self._context(session)
        if tenant != plan.tenant_id:
            raise KnowledgeOperationPlanChangedError()
        if ack["deleted_server"]:
            with session.no_autoflush, bypass_tenant_filter():
                physical_server = LLMServer.__table__.c
                provider = (
                    await session.execute(select(physical_server.id).where(physical_server.id == ack["server_id"]))
                ).first()
            self._check(session, tenant, transaction)
            with session.no_autoflush, bypass_tenant_filter():
                physical_model = LLMModel.__table__.c
                children = (
                    await session.execute(
                        select(physical_model.id).where(physical_model.server_id == ack["server_id"]).limit(1)
                    )
                ).first()
            self._check(session, tenant, transaction)
            if provider is not None or children is not None:
                raise KnowledgeOperationPlanChangedError()
        else:
            provider, models = await self.aread_result(session, server_id=ack["server_id"])
            if self.result_digest(provider, models) != ack["result_digest"]:
                raise KnowledgeOperationPlanChangedError()
        removed = tuple(str(value) for value in ack["removed_model_ids"])
        for start in range(0, len(removed), 200):
            batch = removed[start : start + 200]
            with session.no_autoflush, bypass_tenant_filter():
                physical_model = LLMModel.__table__.c
                physical = (
                    await session.execute(
                        select(physical_model.id)
                        .where(physical_model.id.in_(tuple(int(value) for value in batch)))
                        .limit(1)
                    )
                ).first()
            self._check(session, tenant, transaction)
            if physical is not None:
                raise KnowledgeOperationPlanChangedError()
            with session.no_autoflush, strict_tenant_filter():
                rows = (
                    (
                        await session.execute(
                            select(ResourceReferenceTombstone).where(
                                ResourceReferenceTombstone.target_type == "model",
                                ResourceReferenceTombstone.target_id.in_(batch),
                                ResourceReferenceTombstone.target_tenant_id == tenant,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            self._check(session, tenant, transaction)
            if len(rows) != len(batch) or any(
                row.tenant_id != tenant
                or row.operation_id != plan.operation_id
                or row.operation_type != plan.operation
                or row.stage != "deleted"
                or row.actor_type != "user"
                or row.actor_id != str(plan.actor_user_id)
                or row.deleted_at is None
                for row in rows
            ):
                raise KnowledgeOperationPlanChangedError()
