"""Exact global physical facts for explicit migration, never R2 authority.

The closed revision covers these scalar facts and related timestamps/R/G.
It is deliberately not a provider/full business configuration checksum.
"""

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
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey, TargetType, canonical_target_id


def _blocked():
    raise KnowledgeOperationPlanConflictError(reason="migration_knowledge_target_input_invalid")


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
            or not isinstance(key.target_type, TargetType)
            or key.target_type not in {TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE}
            or not isinstance(key.target_id, str)
        ):
            _blocked()
        try:
            if canonical_target_id(key.target_id) != key.target_id:
                _blocked()
        except ValueError as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_knowledge_target_input_invalid") from error
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
class KnowledgeMigrationTargetFact:
    key: TargetKey
    exists: bool
    target_tenant_id: int | None
    knowledge_id: int | None
    knowledge_type: int | None
    file_type: int | None
    space_exists: bool
    space_tenant_id: int | None
    revision_digest: str


class KnowledgeMigrationTargetRepository:
    @staticmethod
    async def _rows(session, statement):
        # The only cross-scope window is an exact <=200 PK projection. This
        # cannot make a filtered foreign row look like a globally missing row.
        with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            return {row["id"]: row for row in (await session.execute(statement)).mappings()}

    async def ainspect(
        self, session, *, source_key: SourceKey, targets: tuple[TargetKey, ...]
    ) -> tuple[KnowledgeMigrationTargetFact, ...]:
        keys = _inputs(session, source_key, targets)
        spaces, files = {}, {}
        space_ids = sorted(int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_SPACE)
        file_ids = sorted(int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE)
        if space_ids:
            spaces = await self._rows(
                session,
                select(
                    Knowledge.id,
                    Knowledge.tenant_id,
                    Knowledge.type,
                    Knowledge.model_config_revision,
                    Knowledge.index_generation,
                    Knowledge.update_time,
                ).where(Knowledge.id.in_(space_ids)),
            )
        if file_ids:
            files = await self._rows(
                session,
                select(
                    KnowledgeFile.id,
                    KnowledgeFile.tenant_id,
                    KnowledgeFile.knowledge_id,
                    KnowledgeFile.file_type,
                    KnowledgeFile.update_time,
                    Knowledge.id.label("space_id"),
                    Knowledge.tenant_id.label("space_tenant"),
                    Knowledge.type.label("space_type"),
                    Knowledge.model_config_revision,
                    Knowledge.index_generation,
                    Knowledge.update_time.label("space_update_time"),
                )
                .outerjoin(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                .where(KnowledgeFile.id.in_(file_ids)),
            )
        result = []
        for key in keys:
            if key.target_type == TargetType.KNOWLEDGE_SPACE:
                row = spaces.get(int(key.target_id))
                result.append(
                    KnowledgeMigrationTargetFact(
                        key,
                        row is not None,
                        row["tenant_id"] if row else None,
                        int(key.target_id),
                        row["type"] if row else None,
                        None,
                        row is not None,
                        row["tenant_id"] if row else None,
                        _digest(key, dict(row) if row else None),
                    )
                )
            else:
                row = files.get(int(key.target_id))
                result.append(
                    KnowledgeMigrationTargetFact(
                        key,
                        row is not None,
                        row["tenant_id"] if row else None,
                        row["knowledge_id"] if row else None,
                        row["space_type"] if row else None,
                        row["file_type"] if row else None,
                        bool(row is not None and row["space_id"] is not None),
                        row["space_tenant"] if row else None,
                        _digest(key, dict(row) if row else None),
                    )
                )
        return tuple(result)
