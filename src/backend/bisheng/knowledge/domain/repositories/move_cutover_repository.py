"""Same-transaction move reservations and native, projection-proven cutover."""

from copy import deepcopy
from dataclasses import dataclass, field, fields
from typing import Protocol
from uuid import uuid4
from weakref import WeakKeyDictionary

from sqlalchemy import and_, delete, or_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_scope_repository import MoveScopeRepository, path_ids, revision
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository, _digest, _now, _utc
from bisheng.knowledge.domain.schemas.move_processing import DOC_FIELDS, FILE_FIELDS, VERSION_FIELDS, MoveScope
from bisheng.resource_reference.application.contracts import TransactionIdentity


class MoveProjectionEvidenceVerifier(Protocol):
    def assert_current(self, evidence, session, *, job_id, expected_changes, changes_digest) -> None: ...


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class MoveReservation:
    tenant_id: int
    job_id: str
    plan_id: str
    plan_digest: str
    plan_request_hash: str
    actor_reference_digest: str
    source_space_id: int
    destination_space_id: int
    scope_digest: str
    index_item_count: int
    actor_reference: dict = field(repr=False)
    _scope: MoveScope = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedMoveCutover:
    tenant_id: int
    job_id: str
    plan_id: str
    plan_digest: str
    request_hash: str
    claim_generation: int
    lease_token: str = field(repr=False)
    scope: MoveScope = field(repr=False)
    position: str

    @property
    def expected_changes(self):
        return self.scope.parent_changes


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class MoveLogicalReceipt:
    tenant_id: int
    job_id: str
    plan_id: str
    request_hash: str
    after_scope_digest: str
    projection_evidence_digest: str
    index_item_count: int
    claim_generation: int
    lease_token: str = field(repr=False)
    _prepared: PreparedMoveCutover = field(repr=False)
    _evidence: object = field(repr=False)


class MoveCutoverRepository:
    def __init__(self, *, scope_repository=None, projection_verifier=None, plans=None, clock=_now):
        self.scope = scope_repository if scope_repository is not None else MoveScopeRepository()
        self.projection_verifier, self.plans, self.clock = (
            projection_verifier,
            plans or OperationPlanRepository(clock=clock),
            clock,
        )
        self._issued = WeakKeyDictionary()

    @staticmethod
    def _clean(session):
        if not isinstance(session, AsyncSession):
            raise TypeError("move mutation requires native AsyncSession")
        native = session.sync_session
        if native.new or native.dirty or native.deleted:
            raise KnowledgeOperationPlanConflictError(reason="move_caller_pending_changes")

    @staticmethod
    def _signature(receipt):
        value = {}
        for item in fields(receipt):
            actual = getattr(receipt, item.name)
            if isinstance(actual, MoveScope):
                value[item.name] = {
                    "parameters": actual.to_parameters(),
                    "scope_digest": actual.scope_digest,
                    "changes_digest": actual.changes_digest,
                }
            elif isinstance(actual, PreparedMoveCutover):
                value[item.name] = id(actual)
            elif item.name == "_evidence":
                value[item.name] = id(actual)
            else:
                value[item.name] = actual
        return _digest(value)

    def _issue(self, receipt, session):
        self._issued[receipt] = [TransactionIdentity.capture(session), self._signature(receipt), False]
        return receipt

    def _assert(self, receipt, session, expected_type):
        try:
            actual = self._issued.get(receipt) if type(receipt) is expected_type else None
            if actual is None or actual[2] or actual[1] != self._signature(receipt):
                raise ValueError("invalid receipt")
            actual[0].assert_current(session)
            self.scope._context(session)
            if receipt.tenant_id != self.scope._context(session):
                raise ValueError("different tenant")
        except (TypeError, ValueError, KeyError) as error:
            raise KnowledgeOperationPlanConflictError(reason="move_receipt_invalid") from error
        return actual

    def assert_reservation_current(self, receipt, session):
        self._assert(receipt, session, MoveReservation)

    async def _read(self, session, query):
        with session.no_autoflush, strict_tenant_filter():
            return (await session.execute(query)).mappings().all()

    async def _header(self, session, condition):
        tenant = self.scope._context(session)
        table = KnowledgeOperationPlan.__table__
        rows = await self._read(
            session,
            select(table.c.id, table.c.parameters)
            .where(table.c.tenant_id == tenant, table.c.operation == "move", condition)
            .limit(2),
        )
        if len(rows) != 1:
            raise KnowledgeOperationPlanChangedError()
        return rows[0]

    @staticmethod
    def _restore(parameters):
        try:
            return MoveScope.from_parameters(
                parameters, scope_digest=_digest(parameters), changes_digest=_digest(parameters["parent_changes"])
            )
        except (ValueError, TypeError, KeyError) as error:
            raise KnowledgeOperationPlanChangedError() from error

    async def aprepare_reservation(
        self, session, *, scope, confirmation_id, plan_digest, actor_user_id, actor_reference
    ):
        self._clean(session)
        header = await self._header(session, KnowledgeOperationPlan.__table__.c.id == confirmation_id)
        stored = self._restore(header["parameters"])
        await self.scope._roots(session, stored.source_space_id, stored.destination_space_id, lock=True)
        plan = await self.plans.aget_for_execution(
            session,
            confirmation_id,
            space_id=stored.source_space_id,
            operation="move",
            actor_reference=actor_reference,
            plan_digest=plan_digest,
        )
        if (
            plan.operation_id is not None
            or plan.actor_user_id != actor_user_id
            or stored.to_parameters() != scope.to_parameters()
            or stored.scope_digest != scope.scope_digest
        ):
            raise KnowledgeOperationPlanChangedError()
        current = await self.scope.aload_scope(
            session,
            source_space_id=stored.source_space_id,
            destination_space_id=stored.destination_space_id,
            roots=stored.roots,
            destination_folder_id=stored.destination_folder_id,
            for_update=True,
        )
        expected = sorted(
            (leaf.target.model_dump(mode="json") for leaf in current.leaves),
            key=lambda item: (item["file_id"], item["version_id"], item["document_id"]),
        )
        if current.to_parameters() != stored.to_parameters() or plan.target_manifest != expected:
            raise KnowledgeOperationPlanChangedError()
        return self._issue(
            MoveReservation(
                stored.tenant_id,
                str(uuid4()),
                plan.id,
                plan.plan_digest,
                plan.request_hash,
                _digest(actor_reference),
                stored.source_space_id,
                stored.destination_space_id,
                stored.scope_digest,
                sum(leaf.participates for leaf in stored.leaves),
                deepcopy(actor_reference),
                deepcopy(stored),
            ),
            session,
        )

    async def aconsume_reservation(self, session, receipt):
        issued = self._assert(receipt, session, MoveReservation)
        await self._configuration(session, receipt._scope)
        if await self._position(session, receipt._scope) != "before":
            raise KnowledgeOperationPlanChangedError()
        await self.plans.aconsume(
            session, receipt.plan_id, operation_id=receipt.job_id, expected_digest=receipt.plan_digest
        )
        issued[2] = True

    async def _job(self, session, job_id, lease):
        table = KnowledgeProcessingJob.__table__
        names = (
            "id",
            "tenant_id",
            "space_id",
            "kind",
            "state",
            "request_hash",
            "actor_reference",
            "expected_model_config_revision",
            "accepted_model_config_revision",
            "expected_index_generation",
            "total_count",
            "lease_token",
            "claim_generation",
            "lease_until",
        )
        rows = await self._read(
            session, select(*(table.c[name] for name in names)).where(table.c.id == job_id).with_for_update()
        )
        if len(rows) != 1:
            raise KnowledgeOperationPlanChangedError()
        job = rows[0]
        if (
            job["tenant_id"] != self.scope._context(session)
            or job["kind"] != "move_index"
            or job["state"] != "running"
            or lease.job_id != job_id
            or job["lease_token"] != lease.lease_token
            or job["claim_generation"] != lease.claim_generation
            or job["lease_until"] is None
            or _utc(job["lease_until"]) <= _utc(self.clock())
        ):
            raise KnowledgeOperationPlanConflictError(reason="move_current_job_lease_required")
        return job

    async def _position(self, session, scope, *, lock=False):
        positions = set()
        for model, projection, expected in (
            (KnowledgeFile, FILE_FIELDS, scope.files),
            (KnowledgeDocument, DOC_FIELDS, scope.documents),
        ):
            rows = await self.scope._by_ids(session, model, projection, [row.file_id for row in expected], lock=lock)
            current = {row["id"]: row for row in rows}
            if len(current) != len(expected):
                raise KnowledgeOperationPlanChangedError()
            for row in expected:
                actual = current[row.file_id]
                if actual == row.before:
                    positions.add("before")
                elif revision(actual) == revision(row.after) and (
                    model is KnowledgeDocument
                    or actual["status"] == row.after["status"]
                    or (row.before["status"] == 2 and actual["status"] in (2, 3, 4))
                ):
                    positions.add("after")
                else:
                    raise KnowledgeOperationPlanChangedError()
        versions = {
            row["id"]: row
            for row in await self.scope._by_ids(
                session,
                KnowledgeDocumentVersion,
                VERSION_FIELDS,
                [row.file_id for row in scope.documents],
                key="document_id",
            )
        }
        # A duplicate/moved-in Version must not hide behind a formerly valid File.
        attached = await self.scope._by_ids(
            session,
            KnowledgeDocumentVersion,
            VERSION_FIELDS,
            [row.file_id for row in scope.files],
            key="knowledge_file_id",
        )
        versions.update({row["id"]: row for row in attached})
        if versions != {row["id"]: row for row in scope.versions} or len(positions) != 1:
            raise KnowledgeOperationPlanChangedError()
        if lock:
            locked = await self.scope._by_ids(session, KnowledgeDocumentVersion, VERSION_FIELDS, versions, lock=True)
            if {row["id"]: row for row in locked} != versions:
                raise KnowledgeOperationPlanChangedError()
        position = positions.pop()
        if position == "before":
            await self._before_closure(session, scope, lock=lock)
        return position

    async def _before_closure(self, session, scope, *, lock):
        files, documents = {row.file_id: row for row in scope.files}, {row.file_id for row in scope.documents}
        prefixes = [
            "/" + "/".join(map(str, (*path_ids(files[root.id].before["file_level_path"]), root.id)))
            for root in scope.roots
            if root.type == "folder"
        ]
        for offset in range(0, len(prefixes), 200):
            for model, allowed in ((KnowledgeFile, files), (KnowledgeDocument, documents)):
                table = model.__table__
                paths = or_(
                    *(
                        or_(
                            table.c.file_level_path == path,
                            table.c.file_level_path.startswith(path + "/", autoescape=True),
                        )
                        for path in prefixes[offset : offset + 200]
                    )
                )
                rows = await self.scope._rows(
                    session, model, ("id",), and_(table.c.knowledge_id == scope.source_space_id, paths)
                )
                if any(row["id"] not in allowed for row in rows):
                    raise KnowledgeOperationPlanChangedError()
        keys, tags = sorted(str(key) for key in files), {}
        table = TagLink.__table__
        for offset in range(0, len(keys), 200):
            query = and_(
                table.c.resource_id.in_(keys[offset : offset + 200]),
                table.c.resource_type == ResourceTypeEnum.SPACE_FILE.value,
            )
            tags.update(
                {row["id"]: row for row in await self.scope._rows(session, TagLink, ("id", "tenant_id"), query)}
            )
        if set(tags) != set(scope.tag_link_ids) or any(row["tenant_id"] != scope.tenant_id for row in tags.values()):
            raise KnowledgeOperationPlanChangedError()
        if lock:
            await self.scope._by_ids(session, TagLink, ("id", "tenant_id"), tags, lock=True)

    async def _configuration(self, session, scope):
        source, target = await self.scope._roots(session, scope.source_space_id, scope.destination_space_id)
        if source != scope.source or target != scope.destination:
            raise KnowledgeOperationPlanChangedError()
        if scope.destination_folder_id is not None:
            root = next((row for row in scope.files if row.file_id == scope.roots[0].id), None)
            if root is None:
                raise KnowledgeOperationPlanChangedError()
            path = path_ids(root.after["file_level_path"])
            rows = await self.scope._by_ids(session, KnowledgeFile, FILE_FIELDS, path)
            actual = {row["id"]: row for row in rows}
            if not path or path[-1] != scope.destination_folder_id or len(actual) != len(path):
                raise KnowledgeOperationPlanChangedError()
            for level, key in enumerate(path):
                row = actual[key]
                if (row["tenant_id"], row["knowledge_id"], row["file_type"], row["level"]) != (
                    scope.tenant_id,
                    scope.destination_space_id,
                    0,
                    level,
                ) or path_ids(row["file_level_path"]) != path[:level]:
                    raise KnowledgeOperationPlanChangedError()

    async def aprepare_cutover(self, session, *, job_id, lease):
        self._clean(session)
        header = await self._header(session, KnowledgeOperationPlan.__table__.c.operation_id == job_id)
        scope = self._restore(header["parameters"])
        source, target = await self.scope._roots(session, scope.source_space_id, scope.destination_space_id, lock=True)
        plan = await self.plans._locked(session, header["id"])
        job = await self._job(session, job_id, lease)
        if (
            plan.operation_id != job_id
            or plan.parameters != scope.to_parameters()
            or source != scope.source
            or target != scope.destination
            or job["space_id"] != scope.destination_space_id
            or job["actor_reference"] != plan.actor_reference
            or job["expected_model_config_revision"] != target["model_config_revision"]
            or job["accepted_model_config_revision"] != target["model_config_revision"]
            or job["expected_index_generation"] != target["index_generation"]
        ):
            raise KnowledgeOperationPlanChangedError()
        table = KnowledgeProcessingItem.__table__
        names = ("id", "tenant_id", "file_id", "document_id", "version_id", "expected_space_id", "expected_parent_id")
        items = await self.scope._rows(session, KnowledgeProcessingItem, names, table.c.job_id == job_id, lock=True)
        expected = {
            (
                leaf.target.file_id,
                leaf.target.document_id,
                leaf.target.version_id,
                scope.destination_space_id,
                leaf.destination_parent_id,
            )
            for leaf in scope.leaves
            if leaf.participates
        }
        actual = {
            (row["file_id"], row["document_id"], row["version_id"], row["expected_space_id"], row["expected_parent_id"])
            for row in items
        }
        if (
            len(items) != job["total_count"]
            or len(items) != len(expected)
            or actual != expected
            or any(row["tenant_id"] != scope.tenant_id for row in items)
        ):
            raise KnowledgeOperationPlanChangedError()
        position = await self._position(session, scope, lock=True)
        return self._issue(
            PreparedMoveCutover(
                scope.tenant_id,
                job_id,
                plan.id,
                plan.plan_digest,
                job["request_hash"],
                job["claim_generation"],
                job["lease_token"],
                scope,
                position,
            ),
            session,
        )

    def _proof(self, session, prepared, evidence):
        if self.projection_verifier is None:
            raise KnowledgeOperationPlanConflictError(reason="move_projection_verifier_required")
        self.projection_verifier.assert_current(
            evidence,
            session,
            job_id=prepared.job_id,
            expected_changes=prepared.expected_changes,
            changes_digest=prepared.scope.changes_digest,
        )

    async def aapply_logical(self, session, *, prepared, projection_evidence):
        self._clean(session)
        self._assert(prepared, session, PreparedMoveCutover)
        self._proof(session, prepared, projection_evidence)
        scope = prepared.scope
        await self._configuration(session, scope)
        lease = prepared
        # Prepared keeps the original lease identity; Job's actual expiry wins.
        await self._job(session, prepared.job_id, lease)
        position = await self._position(session, scope)
        if position != prepared.position:
            raise KnowledgeOperationPlanChangedError()
        async with session.begin_nested():
            if position == "before":
                for model, rows, writable in (
                    (
                        KnowledgeFile,
                        scope.files,
                        ("knowledge_id", "file_level_path", "level", "user_metadata", "status"),
                    ),
                    (KnowledgeDocument, scope.documents, ("knowledge_id", "file_level_path", "level")),
                ):
                    table = model.__table__
                    for row in rows:
                        values = {
                            name: deepcopy(row.after[name]) for name in writable if row.before[name] != row.after[name]
                        }
                        if not values:
                            continue
                        query = update(table).where(
                            table.c.id == row.file_id, table.c.knowledge_id == scope.source_space_id
                        )
                        if model is KnowledgeFile:
                            query = query.where(table.c.tenant_id == scope.tenant_id)
                        result = await session.execute(query.values(**values))
                        if result.rowcount != 1:
                            raise KnowledgeOperationPlanChangedError()
                table = TagLink.__table__
                for offset in range(0, len(scope.tag_link_ids), 200):
                    await session.execute(
                        delete(table).where(
                            table.c.id.in_(scope.tag_link_ids[offset : offset + 200]),
                            table.c.tenant_id == scope.tenant_id,
                        )
                    )
            await session.flush()
            if await self._position(session, scope) != "after":
                raise KnowledgeOperationPlanChangedError()
            await self._job(session, prepared.job_id, lease)
            await self._configuration(session, scope)
        receipt = MoveLogicalReceipt(
            scope.tenant_id,
            prepared.job_id,
            prepared.plan_id,
            prepared.request_hash,
            _digest(
                {
                    "files": [revision(row.after) for row in scope.files],
                    "documents": [row.after for row in scope.documents],
                    "versions": scope.versions,
                }
            ),
            _digest(projection_evidence.coverage),
            sum(leaf.participates for leaf in scope.leaves),
            prepared.claim_generation,
            prepared.lease_token,
            prepared,
            projection_evidence,
        )
        return self._issue(receipt, session)

    def assert_logical_current(self, receipt, session):
        self._assert(receipt, session, MoveLogicalReceipt)
        self._assert(receipt._prepared, session, PreparedMoveCutover)
        self._proof(session, receipt._prepared, receipt._evidence)

    def consume_logical(self, receipt, session):
        self.assert_logical_current(receipt, session)
        self._issued[receipt][2] = True
