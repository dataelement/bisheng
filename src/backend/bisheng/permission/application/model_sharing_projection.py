"""Exact provider sharing through the original SQL projection ledger.

The model Owner supplies its business scope port. This permission application
owns every transport call and never imports a model or tenant business table.
"""

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError, PermissionVersionConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.application.sql_runtime import FGAProjectionAdapter
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_plan import (
    HIGHER_CONSISTENCY,
    ProjectionPlan,
    ProjectionTupleDelta,
    normalize_projection_plan,
    projection_request_checksum,
)
from bisheng.permission.domain.services.projection_service import ProjectionScopeDeferred, ProjectionService
from bisheng.resource_reference.application.contracts import TransactionIdentity

MODEL_SHARING_SCOPE = "llm_model_deletion"
__all__ = [
    "MODEL_SHARING_SCOPE",
    "ModelSharingProjectionApplication",
    "PreparedModelSharing",
    "ProjectionScopeDeferred",
    "SharingBatch",
    "SharingSnapshot",
    "get_model_sharing_projection_application",
]


def _blocked(reason):
    raise PermissionPublishNotReadyError(msg="Model sharing projection: " + reason)


def _identifier(value):
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        _blocked("noncanonical identity")
    return value


@dataclass(frozen=True, slots=True)
class SharingSnapshot:
    server_id: int
    store_id: str
    model_id: str
    subjects: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SharingBatch:
    operation_id: int
    request_checksum: str
    plan: ProjectionPlan


@dataclass(frozen=True, slots=True)
class PreparedModelSharing:
    before: SharingSnapshot
    after: tuple[int, ...]
    batches: tuple[SharingBatch, ...]

    def metadata(self):
        return {
            "server_id": self.before.server_id,
            "store_id": self.before.store_id,
            "model_id": self.before.model_id,
            "before": list(self.before.subjects),
            "after": list(self.after),
            "batches": [{"id": batch.operation_id, "checksum": batch.request_checksum} for batch in self.batches],
        }


class _GuardedClient:
    def __init__(self, client, guard):
        self.client, self.guard = client, guard

    @property
    def store_id(self):
        return self.client.store_id

    @property
    def model_id(self):
        return self.client.model_id

    def validate_business_mutation_size(self, size):
        self.guard()
        return self.client.validate_business_mutation_size(size)

    async def write_tuples(self, **kwargs):
        self.guard()
        value = await self.client.write_tuples(**kwargs)
        self.guard()
        return value

    async def read_tuples(self, **kwargs):
        self.guard()
        value = await self.client.read_tuples(**kwargs)
        self.guard()
        return value

    async def iter_tuples(self, **kwargs):
        iterator = self.client.iter_tuples(**kwargs).__aiter__()
        while True:
            self.guard()
            try:
                value = await anext(iterator)
            except StopAsyncIteration:
                self.guard()
                return
            self.guard()
            yield value


class ModelSharingProjectionApplication:
    def __init__(self, *, client, marker, scope, repository=None, guard=None):
        if not isinstance(repository, (ProjectionRepository, type(None))):
            raise TypeError("a real projection repository is required")
        self.guard = guard if guard is not None else scope.check_request
        self.client, self.marker, self.scope = _GuardedClient(client, self.guard), marker, scope
        self.repository = repository if repository is not None else ProjectionRepository()
        self.service = ProjectionService(
            repository=self.repository,
            marker=marker,
            scope_guard=scope,
            fga=FGAProjectionAdapter(self.client),
            finalizer=scope,
        )

    def _pin(self, expected=None):
        self.guard()
        pin = self.client.store_id, self.client.model_id
        if any(not isinstance(value, str) or not value or len(value) > 64 for value in pin):
            _blocked("missing current authorization pin")
        if expected is not None and pin != expected:
            _blocked("authorization pin changed")
        return pin

    async def aread(self, *, server_id: int) -> SharingSnapshot:
        _identifier(server_id)
        pin = self._pin()
        resource = f"llm_server:{server_id}"
        subjects = set()
        async for row in self.client.iter_tuples(
            object=resource, relation="shared_with", consistency=HIGHER_CONSISTENCY
        ):
            self._pin(pin)
            if (
                not isinstance(row, dict)
                or set(row) != {"user", "relation", "object"}
                or row["relation"] != "shared_with"
                or row["object"] != resource
                or not isinstance(row["user"], str)
                or not row["user"].startswith("tenant:")
            ):
                _blocked("invalid existing sharing tuple")
            raw = row["user"][7:]
            if not raw or not raw.isascii() or not raw.isdecimal() or str(int(raw)) != raw:
                _blocked("noncanonical existing tenant")
            value = _identifier(int(raw))
            if value in subjects:
                _blocked("duplicate existing sharing tuple")
            subjects.add(value)
        self._pin(pin)
        return SharingSnapshot(server_id, *pin, tuple(sorted(subjects)))

    async def aprepare(
        self,
        *,
        before: SharingSnapshot,
        after: tuple[int, ...],
        confirmation_id: str,
        actor: PermissionActor,
        tenant_id: int,
        operation: str,
    ) -> PreparedModelSharing:
        if type(before) is not SharingSnapshot or type(after) is not tuple:
            _blocked("typed sharing snapshots required")
        _identifier(before.server_id)
        _identifier(tenant_id)
        if (
            not isinstance(actor, PermissionActor)
            or actor.subject_type != "user"
            or type(actor.subject_id) is not int
            or actor.subject_id <= 0
            or not isinstance(confirmation_id, str)
            or len(confirmation_id) != 36
            or operation not in {"model_update_server", "model_delete_server", "model_share_server"}
            or tuple(sorted({_identifier(value) for value in after})) != after
            or tuple(sorted({_identifier(value) for value in before.subjects})) != before.subjects
        ):
            _blocked("invalid business sharing request")
        self._pin((before.store_id, before.model_id))
        old, new = frozenset(before.subjects), frozenset(after)
        changes = tuple(("DELETE", value) for value in sorted(old - new)) + tuple(
            ("WRITE", value) for value in sorted(new - old)
        )
        batches = []
        for offset in range(0, len(changes), 50):
            chunk = changes[offset : offset + 50]
            ordinal = offset // 50
            identity = sha256(
                f"{confirmation_id}\0{ordinal}\0{before.store_id}\0{before.model_id}".encode()
            ).hexdigest()
            plan = normalize_projection_plan(
                ProjectionPlan(
                    tenant_id=tenant_id,
                    idempotency_key=f"model-sharing:{confirmation_id}:{ordinal}:{identity}",
                    operation_type=operation,
                    scope_type=MODEL_SHARING_SCOPE,
                    scope_key=f"llm_server:{before.server_id}:{confirmation_id}",
                    expected_version=1,
                    target_version=2,
                    store_id=before.store_id,
                    model_id=before.model_id,
                    operator_id=actor.subject_id,
                    change_item_count=len(chunk),
                    deltas=tuple(
                        ProjectionTupleDelta(
                            "COMMIT", index, action, f"tenant:{value}", "shared_with", f"llm_server:{before.server_id}"
                        )
                        for index, (action, value) in enumerate(chunk)
                    ),
                )
            )
            operation_row = await self.service.prepare(plan)
            self._pin((before.store_id, before.model_id))
            if type(operation_row.id) is not int or operation_row.id <= 0:
                _blocked("projection journal missing its real identity")
            batches.append(SharingBatch(operation_row.id, projection_request_checksum(plan), plan))
        return PreparedModelSharing(before, after, tuple(batches))

    async def arequire_before(self, prepared: PreparedModelSharing):
        if await self.aread(server_id=prepared.before.server_id) != prepared.before:
            raise PermissionVersionConflictError(msg="Provider sharing changed before its frozen projection")

    async def arestore(self, metadata, *, confirmation_id, tenant_id, operation, operator_id):
        """One complete, linear reconstruction from the actual frozen journals."""
        if not isinstance(metadata, dict) or set(metadata) != {
            "server_id",
            "store_id",
            "model_id",
            "before",
            "after",
            "batches",
        }:
            _blocked("invalid frozen sharing manifest")
        before = SharingSnapshot(
            _identifier(metadata["server_id"]),
            metadata["store_id"],
            metadata["model_id"],
            tuple(metadata["before"]),
        )
        after = tuple(metadata["after"])
        for subjects in (before.subjects, after):
            if tuple(sorted({_identifier(value) for value in subjects})) != subjects:
                _blocked("invalid frozen subject set")
        self._pin((before.store_id, before.model_id))
        old, new = frozenset(before.subjects), frozenset(after)
        expected = tuple(("DELETE", value) for value in sorted(old - new)) + tuple(
            ("WRITE", value) for value in sorted(new - old)
        )
        bindings = metadata["batches"]
        if not isinstance(bindings, list) or len(bindings) != (len(expected) + 49) // 50:
            _blocked("incomplete frozen sharing batches")
        batches, ids = [], set()
        for ordinal, item in enumerate(bindings):
            if not isinstance(item, dict) or set(item) != {"id", "checksum"}:
                _blocked("invalid frozen batch identity")
            identifier = _identifier(item["id"])
            if identifier in ids:
                _blocked("duplicate frozen batch")
            ids.add(identifier)
            row, plan = await self.service._load_operation_plan(identifier)
            self._pin((before.store_id, before.model_id))
            identity = sha256(
                f"{confirmation_id}\0{ordinal}\0{before.store_id}\0{before.model_id}".encode()
            ).hexdigest()
            chunk = expected[ordinal * 50 : ordinal * 50 + 50]
            if (
                row.request_checksum != item["checksum"]
                or projection_request_checksum(plan) != item["checksum"]
                or plan.tenant_id != tenant_id
                or plan.scope_type != MODEL_SHARING_SCOPE
                or plan.scope_key != f"llm_server:{before.server_id}:{confirmation_id}"
                or plan.operation_type != operation
                or plan.operator_id != operator_id
                or plan.idempotency_key != f"model-sharing:{confirmation_id}:{ordinal}:{identity}"
                or (plan.expected_version, plan.target_version) != (1, 2)
                or (plan.store_id, plan.model_id) != (before.store_id, before.model_id)
                or plan.change_item_count != len(chunk)
                or len(plan.deltas) != len(chunk)
                or any(
                    (delta.phase, delta.sequence, delta.action, delta.user, delta.relation, delta.object)
                    != ("COMMIT", index, action, f"tenant:{subject}", "shared_with", f"llm_server:{before.server_id}")
                    for index, (delta, (action, subject)) in enumerate(zip(plan.deltas, chunk, strict=True))
                )
            ):
                _blocked("frozen journal differs from its full original sharing change")
            batches.append(SharingBatch(identifier, item["checksum"], plan))
        return PreparedModelSharing(before, after, tuple(batches))

    async def arequire_finalized(self, session, prepared: PreparedModelSharing):
        """Lock exact scalar journal facts inside the final business transaction."""
        transaction = TransactionIdentity.capture(session)
        expected = {batch.operation_id: batch.request_checksum for batch in prepared.batches}
        ids = tuple(sorted(expected))
        for start in range(0, len(ids), 200):
            self.guard()
            transaction.assert_current(session)
            with session.no_autoflush, strict_tenant_filter():
                rows = (
                    await session.execute(
                        select(
                            PermissionProjectionOperation.id,
                            PermissionProjectionOperation.request_checksum,
                            PermissionProjectionOperation.status,
                        )
                        .where(PermissionProjectionOperation.id.in_(ids[start : start + 200]))
                        .order_by(PermissionProjectionOperation.id)
                        .with_for_update()
                    )
                ).all()
            self.guard()
            transaction.assert_current(session)
            if len(rows) != len(ids[start : start + 200]) or any(
                row.request_checksum != expected[row.id] or row.status != "FINALIZED" for row in rows
            ):
                _blocked("business SQL requires all original journals finalized")

    async def aexecute(self, prepared: PreparedModelSharing):
        for batch in prepared.batches:
            row = await self.repository.aget_operation(batch.operation_id)
            if row is None or row.request_checksum != batch.request_checksum:
                _blocked("bound projection journal changed")
            outcome = await self.service.reconcile_operation(batch.operation_id)
            self._pin((prepared.before.store_id, prepared.before.model_id))
            if outcome.status != "FINALIZED" or outcome.request_checksum != batch.request_checksum:
                _blocked("bound projection did not finalize")
        await self.arequire_after(prepared)

    async def arequire_after(self, prepared: PreparedModelSharing):
        actual = await self.aread(server_id=prepared.before.server_id)
        if (actual.store_id, actual.model_id) != (
            prepared.before.store_id,
            prepared.before.model_id,
        ) or actual.subjects != prepared.after:
            raise PermissionVersionConflictError(msg="Provider sharing is not the complete frozen AFTER set")


async def get_model_sharing_projection_application(*, scope, repository=None):
    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    runtime = await get_f048_process_runtime()
    components = getattr(runtime, "components", runtime)
    facade = getattr(components, "facade", None)
    if facade is None:
        _blocked("current permission runtime is unavailable")
    # This application is inside the permission boundary: the bound runtime's
    # existing client remains the single Store/model transport.
    await facade.current_catalog()
    return ModelSharingProjectionApplication(
        client=facade._client, marker=components.marker, scope=scope, repository=repository
    )
