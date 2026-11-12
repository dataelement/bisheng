"""Exact original copy journal and source/target Mode in one native TX."""

from types import SimpleNamespace

import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.domain.models import PermissionProjectionOperation as Operation
from bisheng.permission.domain.models import PermissionProjectionTuple as TupleRow
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionRepository


class CopyProjectionRepository(MoveProjectionRepository):
    async def aread_pair(self, session, *, source, target, key):
        tenant, _transaction = self._scope(session)
        if (
            source.tenant_id != tenant
            or target.tenant_id != tenant
            or source.resource_type != target.resource_type
            or source.resource_id == target.resource_id
        ):
            raise PermissionPublishNotReadyError()
        operations = await self._read(
            session,
            sa.select(Operation.__table__)
            .where(Operation.tenant_id == tenant, Operation.idempotency_key == key)
            .limit(2)
            .with_for_update(),
        )
        if len(operations) != 1:
            raise PermissionPublishNotReadyError()
        fact = SimpleNamespace(**operations[0])
        keys = ((source.resource_type, source.resource_id), (target.resource_type, target.resource_id))
        self._pending(session, keys, (fact.id,))
        modes = await self._read(
            session,
            sa.select(Mode.__table__)
            .where(
                Mode.tenant_id == tenant,
                Mode.resource_type == source.resource_type,
                Mode.resource_id.in_((source.resource_id, target.resource_id)),
            )
            .order_by(Mode.resource_id)
            .with_for_update(),
        )
        if len(modes) != 2:
            raise PermissionPublishNotReadyError()
        by_id = {row["resource_id"]: SimpleNamespace(**row) for row in modes}
        tuples = await self._read(
            session,
            sa.select(TupleRow.__table__)
            .where(TupleRow.tenant_id == tenant, TupleRow.operation_id == fact.id)
            .order_by(TupleRow.phase, TupleRow.sequence),
        )
        self._pending(session, keys, (fact.id,))
        return (
            fact,
            by_id[source.resource_id],
            by_id[target.resource_id],
            tuple(SimpleNamespace(**row) for row in tuples),
        )
