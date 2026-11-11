"""Verify the original RESOURCE_DELETE journal in the business transaction."""

import re
from collections import defaultdict
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, or_, select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
)
from bisheng.permission.domain.services.projection_service import restore_projection_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan
from bisheng.resource_reference.application.contracts import TransactionIdentity


def blocked(reason):
    raise PermissionPublishNotReadyError(msg="Knowledge delete projection: " + reason)


def delete_key(operation_id, target):
    if (
        type(operation_id) is not str
        or str(UUID(operation_id)) != operation_id
        or target.resource_type not in {"knowledge_space", "folder", "knowledge_file"}
    ):
        blocked("actual deletion UUID and knowledge target required")
    return f"knowledge-delete:{operation_id}:{target.resource_type}:{target.resource_id}"


@dataclass(frozen=True, slots=True)
class DeleteProjectionExpectation:
    operation_id: str
    target: VerifiedPermissionTarget
    operator_id: int


class KnowledgeDeleteProjectionRepository:
    @staticmethod
    def _reader(session):
        tenant, transaction = get_current_tenant_id(), TransactionIdentity.capture(session)
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            blocked("bounded native deletion expectations required")

        async def read(query):
            if session.new or session.dirty or session.deleted:
                blocked("pending permission facts")
            with session.no_autoflush, strict_tenant_filter():
                rows = tuple((await session.execute(query)).mappings())
            transaction.assert_current(session)
            if (
                type(get_current_tenant_id()) is not int
                or get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
            ):
                blocked("context changed")
            return rows

        return tenant, read

    async def _require_pin(self, read, pin):
        names = {"release_id", "release_key", "checksum", "store_id", "model_id", "model_checksum"}
        if type(pin) is not dict or set(pin) != names:
            blocked("complete frozen catalog pin required")

        catalog, auth = PermissionCatalogRelease.__table__, AuthorizationModelRelease.__table__
        rows = await read(
            select(
                catalog.c.id.label("release_id"),
                catalog.c.release_key,
                catalog.c.checksum,
                catalog.c.write_fenced,
                auth.c.status,
                auth.c.store_id,
                auth.c.model_id,
                auth.c.model_checksum,
            )
            .select_from(catalog.join(auth, auth.c.id == catalog.c.required_authorization_model_release_id))
            .where(catalog.c.status == "CURRENT")
            .limit(2)
        )
        if (
            len(rows) != 1
            or rows[0]["write_fenced"]
            or rows[0]["status"] != "ACTIVE"
            or any(rows[0][name] != value for name, value in pin.items())
        ):
            blocked("CURRENT catalog pin changed")

    async def arequire_current(self, session, *, targets, pin):
        tenant, read = self._reader(session)
        if type(targets) is not tuple or len(targets) > 200:
            blocked("bounded current targets required")
        await self._require_pin(read, pin)
        for target in targets:
            if not isinstance(target, VerifiedPermissionTarget) or target.tenant_id != tenant:
                blocked("current business target required")
        if not targets:
            return
        table = ResourcePermissionMode.__table__
        rows = await read(
            select(*table.c)
            .where(
                table.c.tenant_id == tenant,
                or_(
                    *(
                        and_(table.c.resource_type == target.resource_type, table.c.resource_id == target.resource_id)
                        for target in targets
                    )
                ),
            )
            .order_by(table.c.id)
            .with_for_update()
        )
        found = {(row["resource_type"], row["resource_id"]): row for row in rows}
        if len(rows) != len(targets) or len(found) != len(rows):
            blocked("current mode inventory changed")
        for target in targets:
            row = found[(target.resource_type, target.resource_id)]
            if (
                row["version"] != target.resource_version
                or row["projection_state"] != "CURRENT"
                or (row["parent_type"], row["parent_id"]) != (target.parent_type, target.parent_id)
            ):
                blocked("current permission snapshot changed")

    async def arequire_finalized(self, session, *, expectations, pin):
        tenant, read = self._reader(session)
        if type(expectations) is not tuple or len(expectations) > 200:
            blocked("bounded native deletion expectations required")
        await self._require_pin(read, pin)
        expected = {}
        for value in expectations:
            if (
                type(value) is not DeleteProjectionExpectation
                or not isinstance(value.target, VerifiedPermissionTarget)
                or value.target.tenant_id != tenant
                or type(value.operator_id) is not int
                or value.operator_id <= 0
            ):
                blocked("invalid expected business target")
            key = delete_key(value.operation_id, value.target)
            if key in expected:
                blocked("duplicate expected target")
            expected[key] = value
        if not expected:
            return
        operation, tuples, mode = (
            PermissionProjectionOperation.__table__,
            PermissionProjectionTuple.__table__,
            ResourcePermissionMode.__table__,
        )
        operations = await read(
            select(*operation.c)
            .where(operation.c.tenant_id == tenant, operation.c.idempotency_key.in_(tuple(expected)))
            .order_by(operation.c.id)
        )
        if len(operations) != len(expected):
            blocked("complete original deletion journal required")
        by_operation = defaultdict(list)
        ids, after = tuple(row["id"] for row in operations), 0
        while True:
            page = await read(
                select(*tuples.c)
                .where(tuples.c.tenant_id == tenant, tuples.c.operation_id.in_(ids), tuples.c.id > after)
                .order_by(tuples.c.id)
                .limit(200)
            )
            for row in page:
                by_operation[row["operation_id"]].append(SimpleNamespace(**row))
            if len(page) < 200:
                break
            after = page[-1]["id"]
        modes = await read(
            select(*mode.c)
            .where(
                mode.c.tenant_id == tenant,
                or_(
                    *(
                        and_(
                            mode.c.resource_type == value.target.resource_type,
                            mode.c.resource_id == value.target.resource_id,
                        )
                        for value in expectations
                    )
                ),
            )
            .order_by(mode.c.id)
            .with_for_update()
        )
        by_target = {(row["resource_type"], row["resource_id"]): row for row in modes}
        if len(by_target) != len(modes):
            blocked("duplicate mode")
        tuple_fields = (
            "phase",
            "sequence",
            "action",
            "fga_user",
            "relation",
            "fga_object",
            "tuple_fingerprint",
            "inverse_action",
        )
        for row in operations:
            value = expected[row["idempotency_key"]]
            plan = normalize_projection_plan(
                build_delete_plan(
                    value.target,
                    store_id=pin["store_id"],
                    model_id=pin["model_id"],
                    operator_id=value.operator_id,
                    idempotency_key=row["idempotency_key"],
                )
            )
            actual = SimpleNamespace(**row)
            restored = restore_projection_plan(actual, by_operation[row["id"]])
            native, expected_tuples = build_projection_operation(
                plan, request_checksum=projection_request_checksum(plan)
            )
            if (
                restored != plan
                or row["status"] != "FINALIZED"
                or not re.fullmatch(r"[0-9a-fA-F]{64}", row["commit_checksum"] or "")
                or any(
                    getattr(native, name) != row[name]
                    for name in ("request_checksum", "before_checksum", "after_checksum")
                )
            ):
                blocked("original deletion plan not finalized")
            if sorted(tuple(getattr(r, name) for name in tuple_fields) for r in expected_tuples) != sorted(
                tuple(getattr(r, name) for name in tuple_fields) for r in by_operation[row["id"]]
            ):
                blocked("original tuple journal changed")
            state = by_target.get((value.target.resource_type, value.target.resource_id))
            if (
                state is None
                or state["version"] != plan.target_version
                or state["projection_state"] != "CURRENT"
                or state["operation_id"] != row["id"]
                or (state["parent_type"], state["parent_id"]) != (value.target.parent_type, value.target.parent_id)
            ):
                blocked("resource permission state changed")
