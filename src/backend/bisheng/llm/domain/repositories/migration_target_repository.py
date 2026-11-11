"""Model migration identity facts, without callable/share/legacy authority."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey, TargetType, canonical_target_id


def _blocked():
    raise KnowledgeOperationPlanConflictError(reason="migration_model_target_input_invalid")


def _inputs(session, source_key, targets):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
        or not isinstance(source_key, SourceKey)
        or type(source_key.tenant_id) is not int
        or source_key.tenant_id != tenant
        or type(targets) is not tuple
    ):
        _blocked()
    for key in targets:
        if (
            not isinstance(key, TargetKey)
            or key.target_type is not TargetType.MODEL
            or not isinstance(key.target_id, str)
        ):
            _blocked()
        try:
            if canonical_target_id(key.target_id) != key.target_id:
                _blocked()
        except ValueError as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_model_target_input_invalid") from error
    unique = tuple(dict.fromkeys(targets))
    if len(unique) > 200:
        _blocked()
    return unique


def _digest(key, facts):
    def timestamp(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError("migration revision facts must be closed SQL scalars")

    payload = {"target": (key.target_type.value, key.target_id), "facts": facts}
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=timestamp
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelMigrationTargetFact:
    key: TargetKey
    exists: bool
    target_tenant_id: int | None
    model_type: str | None
    is_online: bool | None
    server_id: int | None
    server_exists: bool
    server_tenant_id: int | None
    revision_digest: str


class ModelMigrationTargetRepository:
    async def ainspect(
        self, session, *, source_key: SourceKey, targets: tuple[TargetKey, ...]
    ) -> tuple[ModelMigrationTargetFact, ...]:
        keys = _inputs(session, source_key, targets)
        if not keys:
            return ()
        statement = (
            select(
                LLMModel.id,
                LLMModel.tenant_id,
                LLMModel.model_type,
                LLMModel.online,
                LLMModel.server_id,
                LLMModel.update_time,
                LLMServer.id.label("parent_id"),
                LLMServer.tenant_id.label("parent_tenant"),
                LLMServer.update_time.label("parent_update_time"),
            )
            .outerjoin(LLMServer, LLMServer.id == LLMModel.server_id)
            .where(LLMModel.id.in_(sorted(int(key.target_id) for key in keys)))
        )
        # Keep the real globally unique parent visible, including wrong owner
        # or absent server; no provider config is loaded to find its identity.
        with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            rows = {row["id"]: row for row in (await session.execute(statement)).mappings()}
        result = []
        for key in keys:
            row = rows.get(int(key.target_id))
            result.append(
                ModelMigrationTargetFact(
                    key,
                    row is not None,
                    row["tenant_id"] if row else None,
                    row["model_type"] if row else None,
                    row["online"] if row else None,
                    row["server_id"] if row else None,
                    bool(row is not None and row["parent_id"] is not None),
                    row["parent_tenant"] if row else None,
                    _digest(key, dict(row) if row else None),
                )
            )
        return tuple(result)
