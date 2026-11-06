"""Exact provider removal candidates in the caller's native transaction.

This read/lock boundary never mutates sharing or business configuration. Model
membership is checked against the complete owned provider, not a client list.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_management_all_tenants,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import TargetKey


def _revision(row) -> str:
    value = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelRemovalSnapshot:
    server_id: int
    owner_tenant_id: int
    all_model_ids: tuple[int, ...]
    retained_model_ids: tuple[int, ...]
    targets: tuple[TargetKey, ...]
    server_revision: str
    model_revisions: tuple[tuple[str, str], ...]


class ModelDeletionRepository:
    async def alock_removal_targets(
        self, session: AsyncSession, *, server_id: int, retained_model_ids, delete_server: bool = False
    ) -> ModelRemovalSnapshot:
        if not isinstance(session, AsyncSession):
            raise TypeError("model removal requires a native AsyncSession")
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed() or is_management_all_tenants():
            raise LLMModelNotAccessibleError()
        retained = tuple(retained_model_ids)
        if (
            type(server_id) is not int
            or server_id <= 0
            or type(delete_server) is not bool
            or any(type(value) is not int or value <= 0 for value in retained)
            or len(set(retained)) != len(retained)
            or (delete_server and retained)
        ):
            raise ValueError("an exact provider and unique retained model IDs are required")
        # Read no provider configuration before checking its real ownership.
        # This exact-ID projection is the only pre-ownership cross-scope read.
        with session.no_autoflush, bypass_tenant_filter():
            owner = (
                await session.execute(select(LLMServer.tenant_id).where(LLMServer.id == server_id))
            ).scalar_one_or_none()
        if owner == ROOT_TENANT_ID and owner != tenant:
            raise LLMModelSharedReadonlyError()
        if owner != tenant:
            raise LLMModelNotAccessibleError()
        with session.no_autoflush, strict_tenant_filter():
            server = (
                await session.execute(
                    select(LLMServer)
                    .where(LLMServer.id == server_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
        if server is None or server.tenant_id != tenant:
            raise LLMModelNotAccessibleError()
        # Exact verified parent limits this integrity read. Raw columns keep a
        # corrupt child tenant from being silently removed by the SELECT hook.
        physical = LLMModel.__table__
        with session.no_autoflush, bypass_tenant_filter():
            rows = (
                await session.execute(
                    select(*physical.c)
                    .where(physical.c.server_id == server.id)
                    .order_by(physical.c.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        models = tuple(LLMModel(**dict(row._mapping)) for row in rows)
        if any(row.tenant_id != tenant for row in models):
            raise ResourceReferenceInvalidError(reason="model_provider_owner_mismatch")
        model_ids = tuple(row.id for row in models)
        retained_set = frozenset(retained)
        if not retained_set <= set(model_ids):
            raise ResourceReferenceInvalidError(reason="model_retained_identity_invalid")
        return ModelRemovalSnapshot(
            server.id,
            tenant,
            model_ids,
            tuple(sorted(retained)),
            tuple(TargetKey("model", str(value)) for value in model_ids if value not in retained_set),
            _revision(server),
            tuple((str(row.id), _revision(row)) for row in models),
        )
