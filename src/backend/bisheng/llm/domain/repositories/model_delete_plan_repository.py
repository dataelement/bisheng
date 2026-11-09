"""Model-only confirmation storage; this repository grants no target authority.

The business Owner supplies verified revisions and a stable actor reference,
and must reauthorize/reverify before execution. The caller owns the transaction.
No provider request, credential secret or processing file manifest is stored.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeOperationPlanExpiredError
from bisheng.core.context.tenant import (
    get_current_tenant_id,
    is_management_all_tenants,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.resource_reference.application.contracts import TargetKey, TargetType, canonical_target_id

ModelDeleteOperation = Literal["model_update_server", "model_delete_server"]
_OPERATIONS = frozenset({"model_update_server", "model_delete_server"})
_ACTOR_FIELDS = frozenset({"tenant_id", "actor_user_id", "credential_reference", "data_scope"})
_WEB_FIELDS = frozenset({"kind", "user_id", "tenant_id", "token_version", "expires_at"})


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc(value: datetime) -> datetime:
    value = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    return value.replace(microsecond=0)


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _digest(value) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("a canonical SHA256 digest is required")
    return value


@dataclass(frozen=True, slots=True)
class ModelDeleteConfirmation:
    confirmation_id: str
    operation: ModelDeleteOperation
    plan_digest: str
    expires_at: datetime


class ModelDeletePlanRepository:
    def __init__(self, *, clock=_now):
        self.clock = clock

    @staticmethod
    def _tenant(session) -> int:
        if not isinstance(session, AsyncSession):
            raise TypeError("model confirmation requires a native AsyncSession")
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed() or is_management_all_tenants():
            raise ValueError("model confirmation requires one concrete trusted tenant")
        return tenant

    @staticmethod
    def _operation(operation):
        if operation not in _OPERATIONS:
            raise ValueError("a model update/delete operation is required")
        return operation

    @staticmethod
    def _actor(reference, tenant):
        if (
            not isinstance(reference, Mapping)
            or not _ACTOR_FIELDS <= set(reference)
            or set(reference) - (_ACTOR_FIELDS | {"management_tenant_id"})
        ):
            raise ValueError("a stable original actor reference is required")
        actor = deepcopy(dict(reference))
        if (
            type(actor["tenant_id"]) is not int
            or actor["tenant_id"] != tenant
            or type(actor["actor_user_id"]) is not int
            or actor["actor_user_id"] <= 0
            or not isinstance(actor["data_scope"], str)
            or actor["data_scope"] not in {DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL}
            or (
                "management_tenant_id" in actor
                and (type(actor["management_tenant_id"]) is not int or actor["management_tenant_id"] != tenant)
            )
        ):
            raise ValueError("actor reference does not match the concrete tenant")
        credential = actor["credential_reference"]
        if (
            not isinstance(credential, Mapping)
            or set(credential) != _WEB_FIELDS
            or credential["kind"] != "web_session"
            or type(credential["user_id"]) is not int
            or credential["user_id"] != actor["actor_user_id"]
            or type(credential["tenant_id"]) is not int
            or credential["tenant_id"] <= 0
            or type(credential["token_version"]) is not int
            or credential["token_version"] < 0
            or not isinstance(credential["expires_at"], str)
            or (credential["tenant_id"] != tenant and actor.get("management_tenant_id") != tenant)
        ):
            raise ValueError("model confirmations require the original closed web credential reference")
        # Parsing is only a shape check. Current credential validity and the
        # original home identity/management authority are rechecked upstream.
        datetime.fromisoformat(credential["expires_at"])
        actor["credential_reference"] = dict(credential)
        return actor

    @staticmethod
    def _manifest(targets):
        values = []
        for target in targets:
            if isinstance(target, TargetKey):
                kind, identifier = target.target_type.value, target.target_id
            elif isinstance(target, Mapping) and set(target) == {"target_type", "target_id"}:
                kind, identifier = target["target_type"], target["target_id"]
            else:
                raise ValueError("model manifest requires exact model target identities")
            if (
                kind != TargetType.MODEL.value
                or not isinstance(identifier, str)
                or canonical_target_id(identifier) != identifier
            ):
                raise ValueError("model manifest cannot contain file/space or noncanonical identities")
            values.append({"target_type": "model", "target_id": identifier})
        if len({value["target_id"] for value in values}) != len(values):
            raise ValueError("model manifest must not contain duplicate targets")
        return sorted(values, key=lambda value: int(value["target_id"]))

    @staticmethod
    def _revisions(revisions, manifest):
        if not isinstance(revisions, Mapping):
            raise ValueError("real Owner revision hashes are required")
        values = dict(revisions)
        if any(
            not isinstance(key, str) or re.fullmatch(r"(?:model|server):[1-9][0-9]*", key) is None for key in values
        ):
            raise ValueError("revision keys must be canonical model/server identities")
        models = {key for key in values if key.startswith("model:")}
        if (
            models != {f"model:{value['target_id']}" for value in manifest}
            or sum(key.startswith("server:") for key in values) != 1
        ):
            raise ValueError("revisions must cover the exact models and one complete provider")
        return {key: _digest(value) for key, value in values.items()}

    @staticmethod
    def _payload(row):
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
    def _plan_digest(row):
        return _hash({"id": row.id, "request_hash": row.request_hash, "expires_at": _utc(row.expires_at).isoformat()})

    def _validate(self, row, *, expiry=True):
        try:
            self._operation(row.operation)
            manifest = self._manifest(row.target_manifest)
            self._revisions(row.target_revisions, manifest)
            actor = self._actor(row.actor_reference, row.tenant_id)
            if (
                row.space_id is not None
                or row.source_revisions != {}
                or row.target_manifest != manifest
                or row.actor_user_id != actor["actor_user_id"]
                or set(row.parameters) != {"command_digest"}
                or set(row.impact) != {"inbound_digest", "coverage_epoch", "inventory_hash"}
                or type(row.impact["coverage_epoch"]) is not int
                or row.impact["coverage_epoch"] <= 0
                or row.request_hash != _hash(self._payload(row))
                or row.plan_digest != self._plan_digest(row)
                or (row.operation_id is None) != (row.consumed_at is None)
            ):
                raise ValueError("model plan payload changed")
            _digest(row.parameters["command_digest"])
            _digest(row.impact["inbound_digest"])
            _digest(row.impact["inventory_hash"])
        except (TypeError, ValueError, KeyError) as error:
            raise KnowledgeOperationPlanChangedError() from error
        if expiry and row.operation_id is None and _utc(row.expires_at) <= _utc(self.clock()):
            raise KnowledgeOperationPlanExpiredError()

    async def acreate_model_delete_plan(
        self,
        session: AsyncSession,
        *,
        operation: ModelDeleteOperation,
        actor_reference,
        command_digest,
        targets,
        target_revisions,
        inbound_digest,
        coverage_epoch,
        inventory_hash,
        expires_at: datetime,
    ) -> ModelDeleteConfirmation:
        tenant = self._tenant(session)
        actor = self._actor(actor_reference, tenant)
        manifest = self._manifest(targets)
        if type(coverage_epoch) is not int or coverage_epoch <= 0 or _utc(expires_at) <= _utc(self.clock()):
            raise ValueError("complete coverage and a future confirmation expiry are required")
        now = _utc(self.clock())
        row = KnowledgeOperationPlan(
            tenant_id=tenant,
            actor_user_id=actor["actor_user_id"],
            actor_reference=actor,
            operation=self._operation(operation),
            space_id=None,
            target_manifest=manifest,
            target_revisions=self._revisions(target_revisions, manifest),
            source_revisions={},
            parameters={"command_digest": _digest(command_digest)},
            impact={
                "inbound_digest": _digest(inbound_digest),
                "coverage_epoch": coverage_epoch,
                "inventory_hash": _digest(inventory_hash),
            },
            request_hash="",
            plan_digest="",
            expires_at=_utc(expires_at),
            create_time=now,
            update_time=now,
        )
        row.request_hash = _hash(self._payload(row))
        row.plan_digest = self._plan_digest(row)
        session.add(row)
        await session.flush()
        return ModelDeleteConfirmation(row.id, operation, row.plan_digest, row.expires_at)

    async def aget_model_delete_plan_for_execution(
        self,
        session: AsyncSession,
        *,
        confirmation_id: str,
        operation: ModelDeleteOperation,
        actor_reference,
        command_digest: str,
        plan_digest: str,
    ) -> KnowledgeOperationPlan:
        tenant = self._tenant(session)
        self._operation(operation)
        try:
            actor = self._actor(actor_reference, tenant)
        except (TypeError, ValueError) as error:
            raise KnowledgeOperationPlanChangedError() from error
        with strict_tenant_filter():
            row = (
                await session.execute(
                    select(KnowledgeOperationPlan)
                    .where(KnowledgeOperationPlan.id == confirmation_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
        if row is None or row.tenant_id != tenant:
            raise KnowledgeOperationPlanChangedError()
        self._validate(row, expiry=False)
        if (
            row.operation != operation
            or row.actor_reference != actor
            or row.parameters["command_digest"] != command_digest
            or row.plan_digest != plan_digest
        ):
            raise KnowledgeOperationPlanChangedError()
        self._validate(row)
        return row

    async def aconsume_model_delete_plan(
        self,
        session: AsyncSession,
        *,
        confirmation_id: str,
        operation: ModelDeleteOperation,
        actor_reference,
        command_digest: str,
        plan_digest: str,
        operation_id: str,
    ) -> KnowledgeOperationPlan:
        if (
            not isinstance(operation_id, str)
            or not operation_id.strip()
            or len(operation_id) > 64
            or "\x00" in operation_id
        ):
            raise ValueError("a durable model mutation operation identity is required")
        row = await self.aget_model_delete_plan_for_execution(
            session,
            confirmation_id=confirmation_id,
            operation=operation,
            actor_reference=actor_reference,
            command_digest=command_digest,
            plan_digest=plan_digest,
        )
        if row.operation_id not in {None, operation_id}:
            raise KnowledgeOperationPlanChangedError()
        if row.operation_id is None:
            row.operation_id, row.consumed_at = operation_id, _utc(self.clock())
            row.update_time = _utc(self.clock())
            await session.flush()
        return row
