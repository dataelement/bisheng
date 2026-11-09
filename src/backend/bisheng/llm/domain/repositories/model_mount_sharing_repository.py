"""Actual mounted-child facts used only by the original LLM share command."""

from dataclasses import dataclass

from sqlalchemy import select

from bisheng.common.errcode.tenant_tree import TenantTreeMountConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMServer
from bisheng.llm.domain.repositories.model_delete_plan_repository import _hash
from bisheng.llm.domain.repositories.model_provider_operation_repository import (
    ACTIVE_STATES,
    ModelProviderOperationRepository,
)
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True, init=False)
class MountedModelShare:
    root_dept_id: int
    child_id: int
    tenant_code: str
    tenant_name: str
    auto_distribute: bool

    def digest(self, server_id):
        return _hash(
            {
                "operation": "model_share_server",
                "server_id": server_id,
                "enabled": True,
                "child_id": self.child_id,
                "mount": {name: getattr(self, name) for name in self.__dataclass_fields__},
            }
        )


class ModelMountSharingRepository:
    @staticmethod
    def _check(session, tenant, transaction):
        transaction.assert_current(session)
        if tenant != ROOT_TENANT_ID or ReferenceRepository.current_tenant_id() != tenant:
            raise TenantTreeMountConflictError()

    async def aread_mount(self, session, *, root_dept_id, child_id, tenant_code, tenant_name, auto_distribute):
        tenant, transaction = ModelProviderOperationRepository._native(session)
        if (
            type(root_dept_id) is not int
            or root_dept_id <= 0
            or type(child_id) is not int
            or child_id <= 0
            or auto_distribute is not True
        ):
            raise TenantTreeMountConflictError()
        self._check(session, tenant, transaction)
        with session.no_autoflush, bypass_tenant_filter():
            child = (await session.execute(select(Tenant).where(Tenant.id == child_id))).scalar_one_or_none()
        self._check(session, tenant, transaction)
        with session.no_autoflush, bypass_tenant_filter():
            dept = (await session.execute(select(Department).where(Department.id == root_dept_id))).scalar_one_or_none()
        self._check(session, tenant, transaction)
        if (
            child is None
            or dept is None
            or child.parent_tenant_id != ROOT_TENANT_ID
            or child.status != "active"
            or child.root_dept_id != root_dept_id
            or child.tenant_code != tenant_code
            or child.tenant_name != tenant_name
            or dept.tenant_id != ROOT_TENANT_ID
            or dept.is_tenant_root != 1
            or dept.mounted_tenant_id != child_id
            or dept.parent_id is None
        ):
            raise TenantTreeMountConflictError()
        facts = object.__new__(MountedModelShare)
        for name, value in zip(
            facts.__dataclass_fields__, (root_dept_id, child_id, tenant_code, tenant_name, True), strict=True
        ):
            object.__setattr__(facts, name, value)
        return facts, child

    async def apending_candidates(self, session):
        """Bounded provider-index lookups, without a scan of historical Plan JSON."""
        tenant, transaction = ModelProviderOperationRepository._native(session)
        self._check(session, tenant, transaction)
        result, after = [], 0
        while True:
            with session.no_autoflush, strict_tenant_filter():
                ids = tuple(
                    (
                        await session.execute(
                            select(LLMServer.id)
                            .where(
                                LLMServer.tenant_id == tenant,
                                LLMServer.id > after,
                            )
                            .order_by(LLMServer.id)
                            .limit(200)
                        )
                    ).scalars()
                )
            self._check(session, tenant, transaction)
            if not ids:
                return tuple(result)
            with session.no_autoflush, strict_tenant_filter():
                rows = (
                    (
                        await session.execute(
                            select(KnowledgeOperationPlan).where(
                                KnowledgeOperationPlan.tenant_id == tenant,
                                KnowledgeOperationPlan.model_server_id.in_(ids),
                                KnowledgeOperationPlan.model_execution_state.in_(ACTIVE_STATES),
                                KnowledgeOperationPlan.operation == "model_share_server",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            self._check(session, tenant, transaction)
            result.extend(rows)
            after = ids[-1]
