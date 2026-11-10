"""Existing RRT facts from registered target Owner scopes, without authority.

The business caller owns the common SAVEPOINT and performs actual deletion.
These methods never start/end a transaction, inspect sources, or grant force.
"""

from datetime import UTC, datetime
from itertools import groupby

from sqlalchemy import bindparam, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_management_all_tenants
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    ReferenceState,
    TargetType,
    TransactionIdentity,
)
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import OwnerTargetScope, ReferenceRepository

_OPERATIONS = {
    "model_update_server": frozenset({TargetType.MODEL}),
    "model_delete_server": frozenset({TargetType.MODEL}),
    "knowledge_file_delete": frozenset({TargetType.KNOWLEDGE_FILE}),
    "knowledge_space_clear": frozenset({TargetType.KNOWLEDGE_FILE}),
    "knowledge_space_delete": frozenset({TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE}),
}
_STAGES = {"deleting": 1, "deleted": 2}


def _invalid():
    raise ResourceReferenceInvalidError(reason="reference_target_deletion_invalid")


def _now():
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


class _Context:
    def __init__(self, repository, session, operation_id, operation_type, actor):
        if (
            not isinstance(repository, ReferenceRepository)
            or repository.verifier is None
            or not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or type(operation_id) is not str
            or not operation_id.strip()
            or "\x00" in operation_id
            or len(operation_id) > 64
            or type(operation_type) is not str
            or operation_type not in _OPERATIONS
            or not isinstance(actor, PermissionActor)
            or actor.subject_type not in {"user", "service_account"}
            or type(actor.subject_id) is not int
            or actor.subject_id <= 0
        ):
            _invalid()
        self.repository, self.session = repository, session
        self.verifier = repository.verifier
        self.tenant = repository.current_tenant_id()
        self.transaction = TransactionIdentity.capture(session)
        self.actor, self.actor_type, self.actor_id = actor, actor.subject_type, actor.subject_id
        self.operation_id, self.operation_type = operation_id, operation_type
        self.scope = None
        self.check()

    def check(self):
        try:
            self.transaction.assert_current(self.session)
        except (TypeError, ValueError):
            _invalid()
        if (
            self.repository.current_tenant_id() != self.tenant
            or is_management_all_tenants()
            or self.repository.verifier is not self.verifier
            or type(self.actor.subject_id) is not int
            or self.actor.subject_type != self.actor_type
            or self.actor.subject_id != self.actor_id
            or self.session.new
            or self.session.dirty
            or self.session.deleted
        ):
            _invalid()
        if self.scope is not None and (
            self.scope.targets is not self.raw_targets
            or self.scope._receipts is not self.raw_receipts
            or self.scope._authority is not self.authority
            or self.scope.owner_tenant_id != self.tenant
            or self.repository._issued_scopes.get(self.scope) is not self.registration
            or self.registration() is not self.scope
        ):
            _invalid()

    def bind(self, scope):
        self.repository._check_scope(self.session, scope)
        self.scope = scope
        self.raw_targets, self.raw_receipts = scope.targets, scope._receipts
        self.authority = scope._authority
        self.registration = self.repository._issued_scopes.get(scope)
        self.check()


class TargetDeletionRepository:
    def __init__(self, repository: ReferenceRepository, *, clock=_now):
        # No native context or IO is acquired during Source-runtime construction.
        self.repository, self.clock = repository, clock

    def _context(self, session, *, operation_id, operation_type, actor):
        return _Context(self.repository, session, operation_id, operation_type, actor)

    async def aprepare(
        self,
        session: AsyncSession,
        *,
        scope: OwnerTargetScope,
        operation_id: str,
        operation_type: str,
        actor: PermissionActor,
    ) -> int:
        return await self._apply(session, scope, operation_id, operation_type, actor, finalize=False)

    async def afinalize(
        self,
        session: AsyncSession,
        *,
        scope: OwnerTargetScope,
        operation_id: str,
        operation_type: str,
        actor: PermissionActor,
    ) -> int:
        return await self._apply(session, scope, operation_id, operation_type, actor, finalize=True)

    @staticmethod
    def _facts(context):
        facts = {}
        for receipt in context.raw_receipts:
            target = receipt.target
            key = target.key.target_type.value, target.key.target_id
            if (
                key in facts
                or target.target_tenant_id != context.tenant
                or target.key.target_type not in _OPERATIONS[context.operation_type]
                or target.state not in {ReferenceState.VALID, ReferenceState.DELETING, ReferenceState.INVALID_DELETED}
            ):
                _invalid()
            if target.state != ReferenceState.VALID:
                evidence = target.evidence
                if (
                    type(evidence) is not DeletionEvidence
                    or evidence.target != target.key
                    or evidence.target_tenant_id != context.tenant
                    or evidence.operation_id != context.operation_id
                    or evidence.stage.value not in _STAGES
                ):
                    _invalid()
            facts[key] = target
        if set(facts) != {(key.target_type.value, key.target_id) for key in context.raw_targets}:
            _invalid()
        return facts

    @staticmethod
    def _row(context, row, facts, found):
        key = row["target_type"], row["target_id"]
        if (
            key not in facts
            or key in found
            or type(row["id"]) is not int
            or row["id"] <= 0
            or row["tenant_id"] != context.tenant
            or row["target_tenant_id"] != context.tenant
            or row["operation_id"] != context.operation_id
            or row["operation_type"] != context.operation_type
            or row["actor_type"] != context.actor_type
            or row["actor_id"] != str(context.actor_id)
            or row["stage"] not in _STAGES
            or (row["stage"] == "deleting" and row["deleted_at"] is not None)
            or (
                row["stage"] == "deleted"
                and (not isinstance(row["deleted_at"], datetime) or row["deleted_at"].tzinfo is not None)
            )
        ):
            _invalid()
        evidence = facts[key].evidence
        if evidence is not None and _STAGES[row["stage"]] < _STAGES[evidence.stage.value]:
            _invalid()
        found[key] = row

    async def _apply(self, session, scope, operation_id, operation_type, actor, *, finalize):
        context = self._context(session, operation_id=operation_id, operation_type=operation_type, actor=actor)
        context.bind(scope)
        facts = self._facts(context)
        table = ResourceReferenceTombstone.__table__
        found = {}
        # The physical unique index is lexicographic, independently of business IDs.
        for kind, values in groupby(sorted(facts), key=lambda key: key[0]):
            ids = tuple(key[1] for key in values)
            for start in range(0, len(ids), 200):
                context.check()
                statement = (
                    select(table)
                    .where(table.c.target_type == kind, table.c.target_id.in_(ids[start : start + 200]))
                    .order_by(table.c.target_type, table.c.target_id, table.c.target_tenant_id, table.c.id)
                    .with_for_update()
                )
                # Exact trusted target keys only. Do not hide NULL/foreign owners.
                with session.no_autoflush, bypass_tenant_filter():
                    result = await session.execute(statement)
                context.check()
                for row in result.mappings():
                    self._row(context, row, facts, found)
        missing = sorted(set(facts) - set(found))
        if any(finalize or facts[key].state != ReferenceState.VALID for key in missing):
            _invalid()
        changes = [found[key] for key in sorted(found) if finalize and found[key]["stage"] == "deleting"]
        self.repository._check_scope(session, scope)
        context.check()
        if missing or changes:
            now = self.clock()
            if not isinstance(now, datetime):
                _invalid()
            now = now.astimezone(UTC).replace(tzinfo=None, microsecond=0) if now.tzinfo else now.replace(microsecond=0)
            for start in range(0, len(missing), 200):
                parameters = [
                    {
                        "tenant_id": context.tenant,
                        "target_type": kind,
                        "target_id": identifier,
                        "target_tenant_id": context.tenant,
                        "operation_id": operation_id,
                        "operation_type": operation_type,
                        "stage": "deleting",
                        "actor_type": context.actor_type,
                        "actor_id": str(context.actor_id),
                        "deleted_at": None,
                        "create_time": now,
                        "update_time": now,
                    }
                    for kind, identifier in missing[start : start + 200]
                ]
                context.check()
                with session.no_autoflush:
                    result = await session.execute(insert(table), parameters)
                context.check()
                if result.rowcount != len(parameters):
                    _invalid()
            statement = (
                update(table)
                .where(
                    table.c.id == bindparam("rrt_pk"),
                    table.c.target_type == bindparam("rrt_kind"),
                    table.c.target_id == bindparam("rrt_target"),
                    table.c.tenant_id == context.tenant,
                    table.c.target_tenant_id == context.tenant,
                    table.c.stage == "deleting",
                    table.c.deleted_at.is_(None),
                    table.c.operation_id == operation_id,
                    table.c.operation_type == operation_type,
                    table.c.actor_type == context.actor_type,
                    table.c.actor_id == str(context.actor_id),
                )
                .values(stage="deleted", deleted_at=now, update_time=now)
            )
            for start in range(0, len(changes), 200):
                parameters = [
                    {"rrt_pk": row["id"], "rrt_kind": row["target_type"], "rrt_target": row["target_id"]}
                    for row in changes[start : start + 200]
                ]
                context.check()
                with session.no_autoflush:
                    result = await session.execute(statement, parameters)
                context.check()
                if result.rowcount != len(parameters):
                    _invalid()
        self.repository._check_scope(session, scope)
        context.check()
        return len(missing) + len(changes)
