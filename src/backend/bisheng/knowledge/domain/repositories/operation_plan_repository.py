"""Knowledge confirmation storage; the application owns validation and commit.

Plans contain a frozen business manifest and identity references, never bearer
credentials. Creating a plan does not fence or mutate its business resources.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeOperationPlanExpiredError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.schemas.processing_job import OperationItem, OperationPrecheck, ResourceVersionTarget


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _copy(value):
    copied = deepcopy(value)

    def check(item):
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str) or key.casefold() in {
                    "token",
                    "bearer",
                    "access_token",
                    "refresh_token",
                    "api_key",
                    "password",
                    "secret",
                    "authorization",
                }:
                    raise ValueError("confirmation plans cannot contain credentials")
                check(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                check(nested)

    check(copied)
    _digest(copied)
    return copied


class OperationPlanRepository:
    def __init__(self, *, clock: Callable[[], datetime] = _now):
        self.clock = clock

    @staticmethod
    def _tenant() -> int:
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0:
            raise RuntimeError("confirmation plans require a concrete tenant")
        return tenant

    @classmethod
    def _actor(cls, reference: Mapping[str, Any]) -> dict:
        value = _copy(dict(reference))
        if (
            value.get("tenant_id") != cls._tenant()
            or type(value.get("actor_user_id")) is not int
            or value["actor_user_id"] <= 0
        ):
            raise ValueError("confirmation plans require a trusted tenant and actor")
        return value

    @staticmethod
    def _payload(row: KnowledgeOperationPlan) -> dict:
        return {
            "tenant_id": row.tenant_id,
            "actor_user_id": row.actor_user_id,
            "actor_reference": row.actor_reference,
            "operation": row.operation,
            "space_id": row.space_id,
            "targets": row.target_manifest,
            "target_revisions": row.target_revisions,
            "source_revisions": row.source_revisions,
            "parameters": row.parameters,
            "impact": row.impact,
        }

    @staticmethod
    def _plan_digest(row: KnowledgeOperationPlan) -> str:
        return _digest({"id": row.id, "request_hash": row.request_hash, "expires_at": _utc(row.expires_at).isoformat()})

    def _validate(self, row: KnowledgeOperationPlan, *, check_expiry: bool = True) -> None:
        if row.request_hash != _digest(self._payload(row)) or row.plan_digest != self._plan_digest(row):
            raise KnowledgeOperationPlanChangedError()
        if (row.operation_id is None) != (row.consumed_at is None):
            raise KnowledgeOperationPlanChangedError()
        if check_expiry and row.operation_id is None and _utc(row.expires_at) <= _utc(self.clock()):
            raise KnowledgeOperationPlanExpiredError()

    async def acreate(
        self,
        session: AsyncSession,
        *,
        operation: str,
        space_id: int,
        actor_reference: Mapping[str, Any],
        targets: Sequence[ResourceVersionTarget | Mapping[str, Any]],
        target_revisions: Mapping[str, Any],
        source_revisions: Mapping[str, Any],
        parameters: Mapping[str, Any],
        impact: Mapping[str, Any],
        expires_at: datetime,
    ) -> OperationPrecheck:
        tenant = self._tenant()
        actor = self._actor(actor_reference)
        if (
            not isinstance(operation, str)
            or not operation.strip()
            or len(operation) > 48
            or "\x00" in operation
            or type(space_id) is not int
            or space_id <= 0
            or _utc(expires_at) <= _utc(self.clock())
        ):
            raise ValueError("a bounded operation, concrete space and future expiry are required")
        manifest = [
            ResourceVersionTarget.model_validate(
                value.model_dump(mode="json") if isinstance(value, ResourceVersionTarget) else value
            ).model_dump(mode="json")
            for value in targets
        ]
        manifest.sort(key=lambda value: (value["file_id"], value["version_id"], value["document_id"]))
        if len({(value["file_id"], value["version_id"]) for value in manifest}) != len(manifest):
            raise ValueError("duplicate version targets")
        now = _utc(self.clock())
        row = KnowledgeOperationPlan(
            tenant_id=tenant,
            actor_user_id=actor["actor_user_id"],
            actor_reference=actor,
            operation=operation,
            space_id=space_id,
            target_manifest=manifest,
            target_revisions=_copy(dict(target_revisions)),
            source_revisions=_copy(dict(source_revisions)),
            parameters=_copy(dict(parameters)),
            impact=_copy(dict(impact)),
            request_hash="",
            plan_digest="",
            expires_at=_utc(expires_at),
            create_time=now,
            update_time=now,
        )
        row.request_hash = _digest(self._payload(row))
        row.plan_digest = self._plan_digest(row)
        session.add(row)
        await session.flush()
        return OperationPrecheck(
            confirmation_id=row.id,
            plan_digest=row.plan_digest,
            expires_at=row.expires_at,
            check_complete=True,
            can_execute=bool(manifest),
            valid_items=[OperationItem(id=target["file_id"], type="file") for target in manifest],
            impact=_copy(row.impact),
        )

    async def _locked(self, session: AsyncSession, plan_id: str) -> KnowledgeOperationPlan:
        tenant = self._tenant()
        with strict_tenant_filter():
            row = (
                await session.exec(
                    select(KnowledgeOperationPlan)
                    .where(KnowledgeOperationPlan.id == plan_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        if row is None or row.tenant_id != tenant:
            raise KnowledgeOperationPlanChangedError()
        self._validate(row, check_expiry=False)
        return row

    async def aget_for_execution(
        self,
        session: AsyncSession,
        confirmation_id: str,
        *,
        space_id: int,
        operation: str,
        actor_reference: Mapping[str, Any],
        plan_digest: str,
    ) -> KnowledgeOperationPlan:
        row = await self._locked(session, confirmation_id)
        if (
            row.space_id != space_id
            or row.operation != operation
            or row.plan_digest != plan_digest
            or row.actor_reference != self._actor(actor_reference)
        ):
            raise KnowledgeOperationPlanChangedError()
        self._validate(row)
        return row

    async def aconsume(
        self,
        session: AsyncSession,
        plan_id: str,
        *,
        operation_id: str,
        expected_digest: str,
    ) -> None:
        if (
            not isinstance(operation_id, str)
            or not operation_id.strip()
            or len(operation_id) > 64
            or "\x00" in operation_id
        ):
            raise ValueError("a bounded durable operation identity is required")
        row = await self._locked(session, plan_id)
        if row.plan_digest != expected_digest or row.operation_id not in {None, operation_id}:
            raise KnowledgeOperationPlanChangedError()
        self._validate(row)
        if row.operation_id is None:
            row.operation_id = operation_id
            row.consumed_at = row.update_time = _utc(self.clock())
            await session.flush()
