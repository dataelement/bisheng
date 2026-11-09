"""Bounded native move facts; the existing Job kernel owns leases and counts."""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace

from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_job_ready_repository import MoveJobReadyRepository
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from bisheng.knowledge.domain.repositories.move_row_repository import MoveRowRepository
from bisheng.knowledge.domain.repositories.move_scope_repository import revision
from bisheng.knowledge.domain.schemas.move_processing import (
    FILE_FIELDS,
    ROOT_FIELDS,
    MoveLeaf,
    MoveParentChange,
    MoveRoot,
    MoveScope,
    move_path_ids,
)
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.knowledge.domain.schemas.processing_job_acceptance import ProcessingConfiguration, _digest
from bisheng.resource_reference.application.contracts import TransactionIdentity


@dataclass(frozen=True, slots=True)
class MoveConfiguration:
    source_space_id: int
    source_model_config_revision: int
    source_index_generation: str | None
    source_index_digest: str
    destination_space_id: int
    destination_model_config_revision: int
    destination_index_generation: str | None
    destination_index_digest: str

    @property
    def target(self):
        return ProcessingConfiguration(self.destination_model_config_revision, self.destination_index_generation)


@dataclass(frozen=True, slots=True)
class MoveCurrentFacts:
    header: dict = field(repr=False)
    plan: dict = field(repr=False)
    source: dict | None = field(repr=False)
    destination: dict | None = field(repr=False)

    @property
    def configuration(self):
        values = {}
        for side in ("source", "destination"):
            root = getattr(self, side)
            if root is None:
                _fail("owning_space_missing")
            values.update(
                {
                    side + "_space_id": root["id"],
                    side + "_model_config_revision": root["model_config_revision"],
                    side + "_index_generation": root["index_generation"],
                    side + "_index_digest": _digest([root["index_name"], root["collection_name"]]),
                }
            )
        return MoveConfiguration(**values)


@dataclass(frozen=True, slots=True)
class MoveAttemptFacts:
    job_id: str
    plan_id: str
    scope: MoveScope = field(repr=False)
    position: str


@dataclass(frozen=True, slots=True)
class MoveProjectionFacts:
    file: dict = field(repr=False)
    current: MoveCurrentFacts = field(repr=False)

    @property
    def configuration(self):
        return self.current.configuration


@dataclass(frozen=True, slots=True)
class MoveExecutionSnapshot:
    item_id: str
    leaf: MoveLeaf
    snapshot: dict = field(repr=False)
    checkpoint: dict = field(repr=False)
    file: dict = field(repr=False)
    document: dict = field(repr=False)
    version: dict = field(repr=False)
    primary_version: dict = field(repr=False)
    source: dict = field(repr=False)
    destination: dict = field(repr=False)
    configuration: MoveConfiguration


def _fail(reason):
    raise KnowledgeOperationPlanConflictError(reason="move_execution_" + reason)


class MoveExecutionRepository(MoveRowRepository):
    def __init__(self, *, move_jobs: MoveJobRepository, move_ready: MoveJobReadyRepository):
        if (
            not isinstance(move_jobs, MoveJobRepository)
            or not isinstance(move_ready, MoveJobReadyRepository)
            or move_ready.move_jobs is not move_jobs
            or move_ready.cutover is not move_jobs.cutover
            or not callable(getattr(move_jobs.cutover.projection_verifier, "assert_current", None))
        ):
            raise TypeError("move execution requires the same actual acceptance, ready and P1 issuer")
        self.move_jobs, self.ready, self.cutover = move_jobs, move_ready, move_jobs.cutover
        self.verifier = self.cutover.projection_verifier

    def _context(self, session):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or self.cutover.projection_verifier is not self.verifier
        ):
            _fail("native_context_required")
        try:
            return tenant, TransactionIdentity.capture(session)
        except (TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(reason="move_execution_native_transaction_required") from error

    def _tail(self, session, context):
        if self._context(session)[0] != context[0]:
            _fail("tenant_changed")
        context[1].assert_current(session)

    async def _read(self, session, statement):
        context = self._context(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        self._tail(session, context)
        return tuple(deepcopy(dict(row)) for row in rows)

    @staticmethod
    def _pending(session, ids):
        for row in (*session.new, *session.dirty, *session.deleted):
            state = inspect(row)
            keys = (state.dict.get("id"), *(state.identity or ()))
            related = any(key in ids.get(type(row), ()) for key in keys)
            if isinstance(row, KnowledgeDocumentVersion):
                for name, model in (("knowledge_file_id", KnowledgeFile), ("document_id", KnowledgeDocument)):
                    values = (
                        state.dict.get(name),
                        *state.attrs[name].history.added,
                        *state.attrs[name].history.deleted,
                    )
                    related = related or any(value in ids.get(model, ()) for value in values)
            if related:
                _fail("pending_business_facts")

    async def _prefix(self, session, job_id, *, lock):
        context = self._context(session)
        job, plan = KnowledgeProcessingJob.__table__, KnowledgeOperationPlan.__table__
        names = (
            "id",
            "tenant_id",
            "space_id",
            "kind",
            "parameters",
            "request_hash",
            "idempotency_key",
            "actor_user_id",
            "actor_reference",
            "actor_subject_type",
            "actor_subject_id",
            "revision",
            "total_count",
            "succeeded_count",
            "claim_generation",
            "move_logical_marker",
            "state",
            "lease_token",
            "lease_until",
            "expected_model_config_revision",
            "expected_index_generation",
        )
        self._pending(session, {KnowledgeProcessingJob: {job_id}})
        headers = await self._read(session, select(*(job.c[name] for name in names)).where(job.c.id == job_id))
        if len(headers) != 1 or headers[0]["tenant_id"] != context[0]:
            _fail("job_missing")
        header = headers[0]
        p = self.ready._retry_scope(SimpleNamespace(**header))
        ids = {
            Knowledge: {p["source_space_id"], p["destination_space_id"]},
            KnowledgeProcessingJob: {job_id},
            KnowledgeOperationPlan: {p["confirmation_id"]},
        }
        self._pending(session, ids)
        query = (
            select(
                *(
                    getattr(Knowledge, name)
                    for name in ROOT_FIELDS
                    if name not in {"metadata_fields", "metadata_schema_revision"}
                )
            )
            .where(Knowledge.id.in_(sorted(ids[Knowledge])))
            .order_by(Knowledge.id)
        )
        roots = await self._read(session, query.with_for_update() if lock else query)
        by_id = {root["id"]: root for root in roots if root["tenant_id"] == context[0]}
        names = (
            "id",
            "tenant_id",
            "operation",
            "space_id",
            "operation_id",
            "consumed_at",
            "plan_digest",
            "request_hash",
            "actor_user_id",
            "actor_reference",
        )
        query = select(*(plan.c[name] for name in names)).where(plan.c.id == p["confirmation_id"])
        plans = await self._read(session, query.with_for_update() if lock else query)
        if (
            len(plans) != 1
            or plans[0]["tenant_id"] != context[0]
            or plans[0]["operation"] != "move"
            or plans[0]["space_id"] != p["source_space_id"]
            or plans[0]["operation_id"] != job_id
            or plans[0]["consumed_at"] is None
            or plans[0]["plan_digest"] != p["plan_digest"]
            or plans[0]["request_hash"] != p["plan_request_hash"]
            or plans[0]["actor_user_id"] != header["actor_user_id"]
            or plans[0]["actor_reference"] != header["actor_reference"]
        ):
            _fail("accepted_plan_changed")
        subject = self.ready.retry_subject(
            SimpleNamespace(**header), actor_user_id=header["actor_user_id"], actor_reference=header["actor_reference"]
        )
        if (subject.subject_type, subject.subject_id) != (header["actor_subject_type"], header["actor_subject_id"]):
            _fail("accepted_subject_changed")
        self._pending(session, ids)
        self._tail(session, context)
        return MoveCurrentFacts(header, plans[0], by_id.get(p["source_space_id"]), by_id.get(p["destination_space_id"]))

    async def _alock_prefix(self, session, *, job_id):
        return await self._prefix(session, job_id, lock=True)

    @staticmethod
    def assert_job(current, job):
        for name in (
            "id",
            "tenant_id",
            "space_id",
            "kind",
            "parameters",
            "request_hash",
            "actor_reference",
            "actor_user_id",
            "actor_subject_type",
            "actor_subject_id",
            "total_count",
        ):
            if getattr(job, name) != current.header[name]:
                _fail("locked_job_changed")

    @staticmethod
    def configuration_reason(current):
        expected = current.header["parameters"]["configuration"]
        if type(expected) is not dict or set(expected) != set(MoveConfiguration.__dataclass_fields__):
            _fail("configuration_shape")
        for side in ("source", "destination"):
            root = getattr(current, side)
            if root is None or root["type"] != 3:
                return "move_" + side + "_space_missing"
            for key, actual in (
                ("model_config_revision", root["model_config_revision"]),
                ("index_generation", root["index_generation"]),
                ("index_digest", _digest([root["index_name"], root["collection_name"]])),
            ):
                if actual != expected.get(side + "_" + key):
                    return "move_" + side + "_" + key + "_changed"
            if root["state"] in (2, 3) or root["model_transition"] is not None:
                return "move_" + side + "_space_processing"
        return None

    async def aread_configuration(self, session, *, job_id) -> MoveConfiguration:
        return (await self._prefix(session, job_id, lock=False)).configuration

    async def avalidate_attempt(self, session, *, lease, jobs) -> MoveAttemptFacts | None:
        context = self._context(session)
        job, current = await jobs._execution_job(session, lease.job_id, _move=True)
        if not jobs._active_job_lease(job, lease):
            return None
        if not jobs._check_configuration(job, None, move_current=current):
            await session.flush()
            return None
        p = job.parameters
        accepted = await self.move_jobs.aget_move_request(
            session,
            source_space_id=p["source_space_id"],
            confirmation_id=p["confirmation_id"],
            plan_digest=p["plan_digest"],
            idempotency_key=job.idempotency_key,
            actor_user_id=job.actor_user_id,
            actor_reference=job.actor_reference,
        )
        if accepted is None:
            _fail("acceptance_missing")
        expected = {
            (value["file_id"], value["document_id"], value["version_id"]): value
            for value in accepted.job.scope_manifest
        }
        count = 0
        async for page in self.ready._item_pages(session, job):
            for item in page:
                key = tuple(item[name] for name in ("file_id", "document_id", "version_id"))
                value = expected.pop(key, None)
                if (
                    value is None
                    or any(item[name] != value[name] for name in ("expected_space_id", "expected_parent_id"))
                    or _digest(item["processing_snapshot"]) != value["processing_snapshot_digest"]
                ):
                    _fail("accepted_item_changed")
                if job.move_logical_marker is not None:
                    self.ready.require_item_ready(job, SimpleNamespace(**item))
                count += 1
            self._tail(session, context)
        if expected or count != job.total_count:
            _fail("accepted_item_set_changed")
        prepared = await self.cutover.aprepare_cutover(session, job_id=job.id, lease=lease)
        self._tail(session, context)
        return MoveAttemptFacts(job.id, prepared.plan_id, prepared.scope, prepared.position)

    async def aread_projection(self, session, *, lease, resource_type, resource_id, jobs) -> MoveProjectionFacts | None:
        context = self._context(session)
        job, current = await jobs._execution_job(session, lease.job_id, _move=True)
        if not jobs._active_job_lease(job, lease):
            return None
        if not jobs._check_configuration(job, None, move_current=current):
            await session.flush()
            return None
        rows = await self._by_ids(session, KnowledgeFile, FILE_FIELDS, (resource_id,), lock=True)
        if (
            len(rows) != 1
            or resource_type not in {"folder", "knowledge_file"}
            or rows[0]["file_type"] != (0 if resource_type == "folder" else 1)
            or rows[0]["knowledge_id"] not in {job.parameters["source_space_id"], job.space_id}
        ):
            _fail("projection_resource_changed")
        self._tail(session, context)
        return MoveProjectionFacts(rows[0], current)

    @staticmethod
    def _leaf(item):
        snapshot = item.processing_snapshot
        try:
            if set(snapshot) != {
                "move_schema",
                "leaf",
                "file_before",
                "file_after",
                "document_after",
                "version",
                "metadata_policy",
            }:
                _fail("snapshot_shape")
            value = snapshot["leaf"]
            leaf = MoveLeaf(
                **{
                    **value,
                    "target": ResourceVersionTarget.model_validate(value["target"]),
                    "selected_root": MoveRoot(**value["selected_root"]),
                    "projection_anchor": MoveParentChange(**value["projection_anchor"]),
                }
            )
            if (
                snapshot["move_schema"] != 1
                or not leaf.participates
                or leaf.target.model_dump()
                != {name: getattr(item, name) for name in ("file_id", "document_id", "version_id")}
                or leaf.destination_parent_id != item.expected_parent_id
                or revision(snapshot["file_before"]) != leaf.before_revision
                or revision(snapshot["file_after"]) != leaf.after_revision
            ):
                _fail("snapshot_binding")
            return leaf
        except (KeyError, TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(reason="move_execution_snapshot_invalid") from error

    async def _snapshot(self, session, job, item, current, evidence=None, *, require_evidence):
        context = self._context(session)
        self.ready.require_item_ready(job, item)
        leaf = self._leaf(item)
        path = item.processing_snapshot["file_after"]["file_level_path"]
        ids = {
            Knowledge: {current.header["parameters"]["source_space_id"], job.space_id},
            KnowledgeProcessingJob: {job.id},
            KnowledgeOperationPlan: {current.plan["id"]},
            KnowledgeProcessingItem: {item.id},
            KnowledgeFile: {item.file_id, *move_path_ids(path)},
            KnowledgeDocument: {item.document_id},
            KnowledgeDocumentVersion: {item.version_id},
        }
        self._pending(session, ids)
        file, document, version, primary, primary_file, ancestors = await self.aread_move_target(
            session, target=leaf.target, expected_path=path
        )
        self._tail(session, context)
        if (
            item.expected_space_id != job.space_id
            or file["knowledge_id"] != job.space_id
            or file["tenant_id"] != job.tenant_id
            or file["file_type"] != 1
            or file["status"] not in (2, 3, 4)
            or revision(file) != leaf.after_revision
            or document != item.processing_snapshot["document_after"]
            or version != item.processing_snapshot["version"]
            or document["knowledge_id"] != job.space_id
            or version["knowledge_file_id"] != item.file_id
            or version["document_id"] != item.document_id
            or primary_file["knowledge_id"] != job.space_id
            or primary_file["tenant_id"] != job.tenant_id
            or primary_file["file_type"] != 1
        ):
            _fail("actual_after_changed")
        for level, ancestor in enumerate(ancestors):
            if (
                ancestor["knowledge_id"] != job.space_id
                or ancestor["tenant_id"] != job.tenant_id
                or ancestor["file_type"] != 0
                or ancestor["level"] != level
                or move_path_ids(ancestor["file_level_path"]) != move_path_ids(path)[:level]
            ):
                _fail("after_parent_changed")
        ids[KnowledgeFile].add(primary_file["id"])
        ids[KnowledgeDocumentVersion].add(primary["id"])
        self._pending(session, ids)
        if require_evidence:
            self.verifier.assert_current(
                evidence,
                session,
                job_id=job.id,
                expected_changes=(leaf.projection_anchor,),
                changes_digest=job.parameters["changes_digest"],
            )
        self._tail(session, context)
        return MoveExecutionSnapshot(
            item.id,
            leaf,
            deepcopy(item.processing_snapshot),
            deepcopy(item.checkpoint),
            file,
            document,
            version,
            primary,
            current.source,
            current.destination,
            current.configuration,
        )

    async def aread_item(self, session, *, job_id, item_id) -> MoveExecutionSnapshot:
        current = await self._alock_prefix(session, job_id=job_id)
        job = SimpleNamespace(**current.header)
        table = KnowledgeProcessingItem.__table__
        self._pending(session, {KnowledgeProcessingItem: {item_id}})
        rows = await self._read(
            session, select(table).where(table.c.id == item_id, table.c.job_id == job_id).with_for_update()
        )
        if len(rows) != 1 or rows[0]["tenant_id"] != job.tenant_id:
            _fail("item_missing")
        if self.configuration_reason(current):
            _fail("read_configuration_changed")
        return await self._snapshot(session, job, SimpleNamespace(**rows[0]), current, require_evidence=False)

    async def _aassert_item_after(self, session, job, item, current, *, projection_evidence):
        return await self._snapshot(session, job, item, current, projection_evidence, require_evidence=True)

    async def aguard_item(self, session, lease, *, jobs, projection_evidence) -> MoveExecutionSnapshot | None:
        guarded = await jobs._guard_item(session, lease, None, _move=True, move_projection_evidence=projection_evidence)
        if guarded is None:
            return None
        current = await self._alock_prefix(session, job_id=lease.job.job_id)
        return await self._aassert_item_after(session, *guarded, current, projection_evidence=projection_evidence)

    async def _acomplete_file(self, session, job, item, current, *, succeeded, outcome, error_code):
        context = self._context(session)
        if succeeded:
            if set(outcome) != {"source_count", "milvus_count", "es_count", "source_digest", "target_payload_digest"}:
                _fail("completion_result_shape")
            expected = {
                "schema_version": 1,
                "operation_id": job.id,
                **asdict(current.configuration),
                **{name: getattr(item, name) for name in ("file_id", "document_id", "version_id")},
                "metadata_policy_digest": _digest(
                    {
                        "retained": sorted(item.processing_snapshot["metadata_policy"]["retained_fields"]),
                        "removed": sorted(item.processing_snapshot["metadata_policy"]["removed_fields"]),
                    }
                ),
                "step": "move_source_cleaned",
            }
            checkpoint = item.checkpoint
            if item.step != "move_source_cleaned" or any(
                type(checkpoint.get(k)) is not type(v) or checkpoint.get(k) != v for k, v in expected.items()
            ):
                _fail("source_cleaned_required")
            for name, key in (
                ("source_count", "source_count"),
                ("milvus_count", "target_milvus_count"),
                ("es_count", "target_es_count"),
                ("source_digest", "source_digest"),
                ("target_payload_digest", "target_payload_digest"),
            ):
                value = outcome.get(name)
                if (
                    value != checkpoint.get(key)
                    or type(value) is not type(checkpoint.get(key))
                    or (name.endswith("count") and (type(value) is not int or value < 0))
                    or (
                        name.endswith("digest")
                        and (
                            type(value) is not str
                            or len(value) != 64
                            or any(c not in "0123456789abcdef" for c in value)
                        )
                    )
                ):
                    _fail("completion_result_changed")
            if outcome["source_count"] != outcome["milvus_count"] or outcome["source_count"] != outcome["es_count"]:
                _fail("completion_counts_changed")
        file, version = KnowledgeFile.__table__, KnowledgeDocumentVersion.__table__
        result = await session.execute(
            update(file)
            .where(
                file.c.id == item.file_id,
                file.c.tenant_id == job.tenant_id,
                file.c.knowledge_id == job.space_id,
                select(version.c.id)
                .where(
                    version.c.id == item.version_id,
                    version.c.document_id == item.document_id,
                    version.c.knowledge_file_id == file.c.id,
                )
                .exists(),
            )
            .values(status=2 if succeeded else 3, remark="" if succeeded else json.dumps({"code": error_code}))
        )
        self._tail(session, context)
        if result.rowcount != 1:
            _fail("completion_file_changed")

    async def acomplete_item(
        self,
        session,
        lease,
        *,
        jobs,
        projection_evidence,
        source_count,
        milvus_count,
        es_count,
        source_digest,
        target_payload_digest,
    ) -> bool:
        return await jobs.acomplete_item(
            session,
            lease,
            configuration=None,
            succeeded=True,
            result={
                "source_count": source_count,
                "milvus_count": milvus_count,
                "es_count": es_count,
                "source_digest": source_digest,
                "target_payload_digest": target_payload_digest,
            },
            _move=True,
            move_projection_evidence=projection_evidence,
        )
