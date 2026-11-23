"""Actual model selections, independent of reverse-reference storage."""

from dataclasses import dataclass

from sqlalchemy import select

from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import TargetKey


@dataclass(frozen=True, slots=True)
class SelectedModel:
    key: TargetKey
    tenant_id: int
    server_id: int
    model_type: str
    status: int


class ModelSelectionRepository:
    @staticmethod
    def statement(tenant_id, ids):
        if get_current_tenant_id() != tenant_id or is_tenant_filter_bypassed():
            raise ValueError("model selection tenant changed")
        return (
            select(LLMModel.id, LLMModel.tenant_id, LLMModel.server_id, LLMModel.model_type, LLMModel.status)
            .join(LLMServer, LLMServer.id == LLMModel.server_id)
            .where(
                LLMModel.id.in_(ids),
                LLMModel.tenant_id.in_(tuple({tenant_id, 1})),
                LLMServer.tenant_id == LLMModel.tenant_id,
            )
            .order_by(LLMServer.id, LLMModel.id)
        )

    @staticmethod
    def values(rows):
        return {
            TargetKey("model", str(row.id)): SelectedModel(
                TargetKey("model", str(row.id)), row.tenant_id, row.server_id, row.model_type, row.status
            )
            for row in rows
        }

    async def aread(self, session, tenant_id, ids):
        if not ids:
            return {}, False
        statement = self.statement(tenant_id, ids)
        with bypass_tenant_filter():
            rows = tuple(await session.execute(statement))
            parent = (
                (
                    await session.execute(select(Tenant.parent_tenant_id).where(Tenant.id == tenant_id))
                ).scalar_one_or_none()
                if tenant_id != 1 and any(row.tenant_id == 1 for row in rows)
                else None
            )
        return self.values(rows), parent == 1

    def read(self, session, tenant_id, ids):
        if not ids:
            return {}, False
        statement = self.statement(tenant_id, ids)
        with bypass_tenant_filter():
            rows = tuple(session.execute(statement))
            parent = (
                session.execute(select(Tenant.parent_tenant_id).where(Tenant.id == tenant_id)).scalar_one_or_none()
                if tenant_id != 1 and any(row.tenant_id == 1 for row in rows)
                else None
            )
        return self.values(rows), parent == 1
