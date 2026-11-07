"""Native evidence for one accepted move's complete, durable parent projections."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID
from weakref import WeakKeyDictionary

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionPublishNotReadyError, PermissionVersionConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
)
from bisheng.permission.domain.models import (
    PermissionProjectionOperation as Operation,
)
from bisheng.permission.domain.models import (
    PermissionProjectionTuple as TupleRow,
)
from bisheng.permission.domain.models import (
    ResourcePermissionMode as Mode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
)
from bisheng.permission.domain.services.projection_service import restore_projection_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan
from bisheng.resource_reference.application.contracts import TransactionIdentity

_OP_FIELDS = tuple(
    "id tenant_id idempotency_key operation_type scope_type scope_key operator_id expected_version target_version store_id model_id request_checksum before_checksum after_checksum commit_checksum status".split()
)
_TUPLE_FIELDS = tuple(
    "id tenant_id operation_id phase sequence action fga_user relation fga_object tuple_fingerprint inverse_action".split()
)


def _blocked(reason):
    raise PermissionPublishNotReadyError(msg="Knowledge move projection: " + reason)


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        _blocked("invalid checksum")


def _id(value):
    if type(value) not in (int, str) or not str(value).isdigit() or str(int(value)) != str(value) or int(value) <= 0:
        _blocked("invalid resource identifier")
    return str(value)


def operation_key(job_id, resource_type, resource_id):
    if type(job_id) is not str or str(UUID(job_id)) != job_id:
        _blocked("canonical job UUID required")
    if resource_type not in {"folder", "knowledge_file"}:
        _blocked("unsupported move resource")
    key = f"knowledge-move:{job_id}:{resource_type}:{_id(resource_id)}"
    if len(key) > 192:
        _blocked("operation key too long")
    return key


@dataclass(frozen=True, slots=True)
class MoveProjectionExpectation:
    job_id: str
    tenant_id: int
    resource_type: str
    resource_id: str
    before: VerifiedPermissionTarget
    after: VerifiedPermissionTarget
    mode: str
    expected_permission_version: int
    changes_digest: str
    allowed_operator_ids: tuple[int, ...]

    def __post_init__(self):
        operation_key(self.job_id, self.resource_type, self.resource_id)
        _digest(self.changes_digest)
        if (
            type(self.tenant_id) is not int
            or self.tenant_id <= 0
            or type(self.expected_permission_version) is not int
            or self.expected_permission_version < 0
            or self.mode not in {"CUSTOM", "INHERIT"}
            or type(self.allowed_operator_ids) is not tuple
            or not 1 <= len(self.allowed_operator_ids) <= 200
            or len(set(self.allowed_operator_ids)) != len(self.allowed_operator_ids)
            or any(type(ident) is not int or ident <= 0 for ident in self.allowed_operator_ids)
        ):
            _blocked("invalid expected move facts")
        for target in (self.before, self.after):
            if (
                not isinstance(target, VerifiedPermissionTarget)
                or (target.tenant_id, target.resource_type, target.resource_id, target.resource_version)
                != (self.tenant_id, self.resource_type, _id(self.resource_id), self.expected_permission_version)
                or target.parent_type not in {"folder", "knowledge_space"}
            ):
                _blocked("verified business target mismatch")
            _id(target.parent_id)
        if (self.before.parent_type, self.before.parent_id) == (self.after.parent_type, self.after.parent_id):
            _blocked("parent change required")


@dataclass(frozen=True, slots=True)
class MoveParentState:
    resource_type: str
    resource_id: str
    mode: str
    version: int
    parent_type: str | None
    parent_id: str | None
    projection_state: str
    operation_id: int | None


@dataclass(frozen=True, slots=True)
class MoveProjectionFact:
    id: int
    tenant_id: int
    idempotency_key: str
    operation_type: str
    scope_type: str
    scope_key: str
    operator_id: int
    expected_version: int
    target_version: int
    store_id: str
    model_id: str
    request_checksum: str
    before_checksum: str
    after_checksum: str
    commit_checksum: str | None
    status: str
    parent_state: MoveParentState | None


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class MoveProjectionEvidence:
    job_id: str
    changes_digest: str
    count: int
    coverage: tuple[tuple, ...]


def _coverage(value):
    return (
        value.resource_type,
        _id(value.resource_id),
        value.before.parent_type,
        _id(value.before.parent_id),
        value.after.parent_type,
        _id(value.after.parent_id),
        value.mode,
        value.expected_permission_version,
    )


def _expected_changes(values):
    try:
        rows = tuple(
            (
                v.resource_type,
                _id(v.resource_id),
                v.old_parent_type,
                _id(v.old_parent_id),
                v.new_parent_type,
                _id(v.new_parent_id),
                v.mode,
                v.expected_permission_version,
            )
            for v in values
        )
    except (AttributeError, TypeError) as error:
        raise PermissionPublishNotReadyError(msg="Move expected changes are incomplete") from error
    if len({row[:2] for row in rows}) != len(rows):
        _blocked("duplicate expected changes")
    if any(
        row[0] not in {"folder", "knowledge_file"}
        or row[2] not in {"folder", "knowledge_space"}
        or row[4] not in {"folder", "knowledge_space"}
        or row[6] not in {"CUSTOM", "INHERIT"}
        or type(row[7]) is not int
        or row[7] < 0
        for row in rows
    ):
        _blocked("invalid expected changes")
    return tuple(sorted(rows))


class MoveProjectionRepository:
    def __init__(self, *, environment=None):
        if environment is None:
            from bisheng.common.services.config_service import settings

            environment = settings.environment
        if type(environment) is not str or not environment:
            _blocked("environment required")
        self.environment, self._issued = environment, WeakKeyDictionary()

    @staticmethod
    def _scope(session):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
        ):
            _blocked("concrete native transaction required")
        try:
            return tenant, TransactionIdentity.capture(session)
        except (TypeError, ValueError) as error:
            raise PermissionPublishNotReadyError(msg="Move projection requires original SQL transaction") from error

    async def _read(self, session, statement):
        tenant, transaction = self._scope(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        if self._scope(session)[0] != tenant:
            _blocked("tenant changed")
        transaction.assert_current(session)
        return rows

    @staticmethod
    def _pending(session, keys, operation_ids=(), *, catalog_id=None, auth_id=None):
        for item in (*session.new, *session.dirty, *session.deleted):
            state = sa.inspect(item)

            def values(name, state=state):
                attr = state.attrs[name]
                return (*attr.history.added, *attr.history.deleted, state.dict.get(name))

            if (
                (
                    isinstance(item, Mode)
                    and any((t, str(i)) in keys for t in values("resource_type") for i in values("resource_id"))
                )
                or (
                    isinstance(item, Operation)
                    and (
                        any(i in operation_ids for i in values("id"))
                        or any(k in keys for k in values("idempotency_key"))
                    )
                )
                or (isinstance(item, TupleRow) and any(i in operation_ids for i in values("operation_id")))
                or (
                    isinstance(item, PermissionCatalogRelease)
                    and ((catalog_id is not None and catalog_id in values("id")) or "CURRENT" in values("status"))
                )
                or (isinstance(item, AuthorizationModelRelease) and auth_id is not None and auth_id in values("id"))
            ):
                _blocked("pending caller permission facts")

    async def _pin(self, session):
        catalog, auth = PermissionCatalogRelease.__table__, AuthorizationModelRelease.__table__
        rows = await self._read(
            session,
            sa.select(
                catalog.c.id,
                catalog.c.write_fenced,
                auth.c.id.label("auth_id"),
                auth.c.environment,
                auth.c.status,
                auth.c.store_id,
                auth.c.model_id,
            )
            .select_from(catalog.outerjoin(auth, auth.c.id == catalog.c.required_authorization_model_release_id))
            .where(catalog.c.status == "CURRENT")
            .order_by(catalog.c.id)
            .limit(2),
        )
        if (
            len(rows) != 1
            or rows[0]["write_fenced"]
            or rows[0]["status"] != "ACTIVE"
            or rows[0]["environment"] != self.environment
            or not rows[0]["store_id"]
            or not rows[0]["model_id"]
        ):
            _blocked("CURRENT Catalog authorization pin is not ready")
        self._pending(session, (), catalog_id=rows[0]["id"], auth_id=rows[0]["auth_id"])
        return rows[0]["store_id"], rows[0]["model_id"]

    def _expectations(self, session, values, *, bounded=False, job_id=None, changes_digest=None):
        tenant, _ = self._scope(session)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or (bounded and len(values) > 200):
            _blocked("expected change batch must contain at most 200 rows")
        keys = set()
        for value in values:
            if (
                type(value) is not MoveProjectionExpectation
                or value.tenant_id != tenant
                or (job_id is not None and value.job_id != job_id)
                or (changes_digest is not None and value.changes_digest != changes_digest)
            ):
                _blocked("expectation scope mismatch")
            value.__post_init__()
            key = value.resource_type, _id(value.resource_id)
            if key in keys:
                _blocked("duplicate expectation")
            keys.add(key)

    async def _modes(self, session, keys, *, lock=False):
        tenant, _ = self._scope(session)
        self._pending(session, keys)
        table = Mode.__table__
        query = sa.select(table.c.id, *(table.c[name] for name in MoveParentState.__dataclass_fields__))
        query = query.where(
            table.c.tenant_id == tenant,
            sa.or_(*(sa.and_(table.c.resource_type == t, table.c.resource_id == i) for t, i in keys)),
        ).order_by(table.c.id)
        rows = await self._read(session, query.with_for_update() if lock else query)
        result = {
            (row["resource_type"], row["resource_id"]): MoveParentState(
                **{name: row[name] for name in MoveParentState.__dataclass_fields__}
            )
            for row in rows
        }
        if len(result) != len(rows):
            _blocked("duplicate native modes")
        return result

    async def aread_parent_states(self, session, *, targets):
        self._scope(session)
        if type(targets) is not tuple or len(targets) > 200:
            _blocked("parent state batch must contain at most 200 rows")
        keys = tuple((t, _id(i)) for t, i in targets)
        if any(t not in {"folder", "knowledge_file"} for t, _ in keys):
            _blocked("invalid parent state resource")
        if not keys:
            return ()
        rows = await self._modes(session, tuple(dict.fromkeys(keys)))
        if any(key not in rows or rows[key].projection_state != "CURRENT" for key in keys):
            _blocked("Resource permission mode is missing or not CURRENT")
        return tuple(rows[key] for key in keys)

    async def alist_owned_operations(self, session, *, expectations, lock=False):
        self._expectations(session, expectations, bounded=True)
        if not expectations:
            return ()
        return await self._operations(session, expectations, await self._pin(session), lock=lock)

    async def _operations(self, session, expectations, pin, *, lock):
        tenant, _ = self._scope(session)
        table = Operation.__table__
        keys = tuple(operation_key(v.job_id, v.resource_type, v.resource_id) for v in expectations)
        self._pending(session, keys)
        query = (
            sa.select(*(table.c[name] for name in _OP_FIELDS))
            .where(table.c.tenant_id == tenant, table.c.idempotency_key.in_(keys))
            .order_by(table.c.id)
        )
        operations = await self._read(session, query.with_for_update() if lock else query)
        by_key = {row["idempotency_key"]: row for row in operations}
        if len(by_key) != len(operations):
            _blocked("duplicate native operations")
        ids = tuple(row["id"] for row in operations)
        self._pending(session, keys, ids)
        modes = await self._modes(
            session, tuple((v.resource_type, _id(v.resource_id)) for v in expectations), lock=lock
        )
        table, after = TupleRow.__table__, 0
        tuples = {ident: [] for ident in ids}
        while ids:
            rows = await self._read(
                session,
                sa.select(*(table.c[name] for name in _TUPLE_FIELDS))
                .where(table.c.operation_id.in_(ids), table.c.id > after)
                .order_by(table.c.id)
                .limit(200),
            )
            for row in rows:
                if row["tenant_id"] != tenant:
                    _blocked("foreign tuple ledger")
                tuples[row["operation_id"]].append(SimpleNamespace(**row))
            if len(rows) < 200:
                break
            after = rows[-1]["id"]
        facts = []
        for item, key in zip(expectations, keys, strict=True):
            row = by_key.get(key)
            if row is None:
                continue
            if row["operator_id"] not in item.allowed_operator_ids or (row["store_id"], row["model_id"]) != pin:
                _blocked("operation actor or pin mismatch")
            plan = normalize_projection_plan(
                build_move_plan(
                    item.after,
                    old_parent=(item.before.parent_type, item.before.parent_id),
                    new_parent=(item.after.parent_type, item.after.parent_id),
                    mode=item.mode,
                    store_id=pin[0],
                    model_id=pin[1],
                    operator_id=row["operator_id"],
                    idempotency_key=key,
                )
            )
            actual = SimpleNamespace(**row)
            try:
                restored = restore_projection_plan(actual, tuples[row["id"]])
                operation, expected_rows = build_projection_operation(
                    plan, request_checksum=projection_request_checksum(plan)
                )
                if restored != plan or any(
                    getattr(actual, name) != getattr(operation, name)
                    for name in ("request_checksum", "before_checksum", "after_checksum")
                ):
                    _blocked("original plan checksum mismatch")
                fields = (
                    "phase",
                    "sequence",
                    "action",
                    "fga_user",
                    "relation",
                    "fga_object",
                    "tuple_fingerprint",
                    "inverse_action",
                )
                if sorted(tuple(getattr(r, n) for n in fields) for r in expected_rows) != sorted(
                    tuple(getattr(r, n) for n in fields) for r in tuples[row["id"]]
                ):
                    _blocked("tuple ledger differs from original move plan")
            except (TypeError, ValueError, PermissionVersionConflictError) as error:
                raise PermissionPublishNotReadyError(msg="Move projection ledger cannot be restored") from error
            facts.append(MoveProjectionFact(**row, parent_state=modes.get((item.resource_type, _id(item.resource_id)))))
        return tuple(facts)

    async def arequire_finalized(self, session, *, job_id, expectations, changes_digest):
        self._expectations(session, expectations, job_id=job_id, changes_digest=changes_digest)
        _digest(changes_digest)
        operation_key(job_id, "folder", "1")
        pin = await self._pin(session) if expectations else None
        operation_ids = []
        for offset in range(0, len(expectations), 200):
            batch = expectations[offset : offset + 200]
            facts = await self._operations(session, batch, pin, lock=True)
            if len(facts) != len(batch):
                _blocked("missing projection operation")
            for item, fact in zip(batch, facts, strict=True):
                state = fact.parent_state
                if (
                    fact.status != "FINALIZED"
                    or state is None
                    or state.projection_state != "CURRENT"
                    or state.operation_id != fact.id
                    or state.version != fact.target_version
                    or state.mode != item.mode
                    or (state.parent_type, state.parent_id) != (item.after.parent_type, item.after.parent_id)
                ):
                    _blocked("projection has not durably finalized")
                _digest(fact.commit_checksum)
                operation_ids.append(fact.id)
        coverage = tuple(sorted(_coverage(item) for item in expectations))
        evidence = MoveProjectionEvidence(job_id, changes_digest, len(coverage), coverage)
        tenant, transaction = self._scope(session)
        self._issued[evidence] = (transaction, tenant, job_id, changes_digest, coverage, tuple(operation_ids))
        return evidence

    def assert_current(self, evidence, session, *, job_id, expected_changes, changes_digest):
        tenant, _ = self._scope(session)
        issued = self._issued.get(evidence) if type(evidence) is MoveProjectionEvidence else None
        if issued is None:
            _blocked("unissued evidence")
        try:
            issued[0].assert_current(session)
        except (TypeError, ValueError) as error:
            raise PermissionPublishNotReadyError(msg="Move evidence belongs to another SQL transaction") from error
        coverage = _expected_changes(expected_changes)
        if issued[1:5] != (tenant, job_id, changes_digest, coverage) or (
            evidence.job_id,
            evidence.changes_digest,
            evidence.count,
            evidence.coverage,
        ) != (job_id, changes_digest, len(coverage), coverage):
            _blocked("incomplete or changed move evidence")
        self._pending(
            session,
            tuple(row[:2] for row in coverage) + tuple(operation_key(job_id, row[0], row[1]) for row in coverage),
            issued[5],
        )
