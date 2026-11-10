"""昆联登记的 SQL 边界。"""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.errcode.flow import (
    WorkflowNameExistsError,
    WorkflowRegistrationConflict,
    WorkflowRegistrationCursorExpired,
    WorkflowRegistrationDenied,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.models.kunlian_registration import (
    KunlianWorkflowChange,
    KunlianWorkflowCreation,
    KunlianWorkflowStream,
    KunlianWorkflowVersion,
)
from bisheng.workflow.domain.repositories.platform_node_publication import PlatformNodePublication
from bisheng.workflow.domain.schemas.platform_agent import PUBLICATION_KEY as AGENT_BINDING
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import PUBLICATION_KEY as KNOWLEDGE_BINDING


def version_revision(version):
    return canonical_digest([version.name, version.description, version.data, version.is_delete])


def _publication_revision(flow, version):
    return canonical_digest([flow.name, flow.description, version_revision(version)])


class RegistrationRepository:
    def __init__(self, sessions=get_sync_db_session):
        self.sessions = sessions

    @contextmanager
    def transaction(self):
        with self.sessions() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    @staticmethod
    def _flow(session, tenant_id, workflow_id, *, lock=False):
        stmt = select(Flow).where(Flow.id == workflow_id)
        row = session.exec(stmt.with_for_update() if lock else stmt).first()
        if not row or row.tenant_id != tenant_id or row.flow_type != FlowType.WORKFLOW.value:
            raise WorkflowRegistrationDenied()
        return row

    @staticmethod
    def _version(session, flow, version_id, *, lock=False):
        stmt = select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.is_delete == 0)
        row = session.exec(stmt.with_for_update() if lock else stmt).first()
        if not row or row.flow_id != flow.id or row.tenant_id != flow.tenant_id:
            raise WorkflowRegistrationConflict()
        return row

    @staticmethod
    def _creation(session, tenant_id, key):
        row = session.get(KunlianWorkflowCreation, key)
        return row if row and row.tenant_id == tenant_id else None

    @classmethod
    def _creation_result(cls, session, row, digest):
        if row.digest != digest:
            raise WorkflowRegistrationConflict()
        flow = cls._flow(session, row.tenant_id, row.workflow_id)
        version_id = session.exec(
            select(FlowVersion.id).where(FlowVersion.flow_id == flow.id).order_by(FlowVersion.id).limit(1)
        ).one()
        return Flow.model_validate(flow), version_id, row.completed

    def find_creation(self, tenant_id, key, digest):
        with tenant_execution_scope(tenant_id), self.transaction() as session:
            row = self._creation(session, tenant_id, key)
            return self._creation_result(session, row, digest) if row else None

    def create(self, key, digest, flow):
        try:
            with tenant_execution_scope(flow.tenant_id), self.transaction() as session:
                row = self._creation(session, flow.tenant_id, key)
                if row:
                    return self._creation_result(session, row, digest)
                existing = select(Flow.id).where(
                    Flow.name == flow.name,
                    Flow.user_id == flow.user_id,
                    Flow.flow_type == flow.flow_type,
                )
                if session.exec(existing.limit(1)).first():
                    raise WorkflowNameExistsError()
                session.add(
                    KunlianWorkflowCreation(
                        key=key,
                        digest=digest,
                        tenant_id=flow.tenant_id,
                        user_id=flow.user_id,
                        workflow_id=flow.id,
                    )
                )
                version = FlowDao.add_with_initial_version(session, flow, FlowType.WORKFLOW.value)
                return Flow.model_validate(flow), version.id, False
        except (IntegrityError, WorkflowNameExistsError):
            existing = self.find_creation(flow.tenant_id, key, digest)
            if existing:
                return existing
            raise

    def finish_creation(self, tenant_id, key):
        with tenant_execution_scope(tenant_id), self.transaction() as session:
            row = self._creation(session, tenant_id, key)
            if not row:
                raise WorkflowRegistrationConflict()
            row.completed = True

    @staticmethod
    def _creation_by_workflow(session, tenant_id, workflow_id):
        return session.exec(
            select(KunlianWorkflowCreation.completed).where(
                KunlianWorkflowCreation.tenant_id == tenant_id,
                KunlianWorkflowCreation.workflow_id == workflow_id,
            )
        ).first()

    def creation_by_workflow(self, tenant_id, workflow_id):
        with tenant_execution_scope(tenant_id), self.transaction() as session:
            return self._creation_by_workflow(session, tenant_id, workflow_id)

    def workflow_ids_in_tenant(self, tenant_id, workflow_ids):
        if not workflow_ids:
            return set()
        with tenant_execution_scope(tenant_id), self.transaction() as session:
            return set(
                session.exec(
                    select(Flow.id).where(
                        Flow.tenant_id == tenant_id,
                        Flow.flow_type == FlowType.WORKFLOW.value,
                        Flow.id.in_(workflow_ids),
                    )
                ).all()
            )

    def pending_ids(self, tenant_id, workflow_ids):
        with tenant_execution_scope(tenant_id), self.transaction() as session:
            rows = session.exec(
                select(KunlianWorkflowCreation).where(
                    KunlianWorkflowCreation.workflow_id.in_(workflow_ids),
                    KunlianWorkflowCreation.completed == False,  # noqa: E712
                )
            ).all()
            return {row.workflow_id for row in rows if row.tenant_id == tenant_id}

    def manage_offline_version(self, scope, workflow_id, version_id, *, delete=False):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id, lock=True)
            version = self._version(session, flow, version_id, lock=True)
            if delete:
                if version.is_current or session.get(
                    KunlianWorkflowVersion, (scope.tenant_id, scope.connection_id, flow.id, version_id)
                ):
                    raise WorkflowRegistrationConflict()
                version.is_delete = 1
                return
            if flow.status == FlowStatus.ONLINE.value:
                raise WorkflowRegistrationConflict()
            for row in session.exec(select(FlowVersion).where(FlowVersion.flow_id == flow.id)).all():
                row.is_current = int(row.id == version.id)
            flow.data = version.data

    def save_draft(self, scope, workflow_id, version_id, revision, *, name=None, description=None, data=None):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id, lock=True)
            version = self._version(session, flow, version_id, lock=True)
            published = session.get(KunlianWorkflowVersion, (scope.tenant_id, scope.connection_id, flow.id, version_id))
            if published or (flow.status == FlowStatus.ONLINE.value and version.is_current):
                raise WorkflowRegistrationConflict()
            if not revision or revision != version_revision(version):
                raise WorkflowRegistrationConflict()
            if name is not None:
                version.name = name
            if description is not None:
                version.description = description
            if data is not None:
                version.data = PlatformNodePublication.candidate_graph(data)
                if version.is_current:
                    flow.data = version.data
            return {**version.model_dump(), "draft_revision": version_revision(version)}

    def candidate(self, scope, workflow_id, version_id):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id)
            version = self._version(session, flow, version_id)
            return Flow.model_validate(flow), FlowVersion.model_validate(version), _publication_revision(flow, version)

    def invocation_flow(self, session, tenant_id, workflow_id, *, lock=False):
        return self._flow(session, tenant_id, workflow_id, lock=lock)

    def invocation_version(self, session, scope, flow, version_id):
        version = self._version(session, flow, version_id, lock=True)
        row = session.get(KunlianWorkflowVersion, (scope.tenant_id, scope.connection_id, flow.id, version.id))
        descriptor = (
            row.descriptor
            if row and row.connection_id == scope.connection_id and row.current and row.availability == "AVAILABLE"
            else None
        )
        if (
            flow.status != FlowStatus.ONLINE.value
            or not version.is_current
            or not isinstance(descriptor, dict)
            or descriptor.get("workflow_id") != flow.id
            or descriptor.get("workflow_version_id") != str(version.id)
        ):
            raise WorkflowRegistrationConflict()
        return version.data, descriptor

    @staticmethod
    def _stream(session, scope, *, lock=False):
        return session.get(KunlianWorkflowStream, (scope.tenant_id, scope.connection_id), with_for_update=lock)

    def _ensure_stream(self, scope):
        try:
            with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
                if self._stream(session, scope) is None:
                    session.add(KunlianWorkflowStream(tenant_id=scope.tenant_id, connection_id=scope.connection_id))
        except IntegrityError:
            with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
                if self._stream(session, scope) is None:
                    raise

    @staticmethod
    def _current(session, scope, workflow_id):
        row = session.exec(
            select(KunlianWorkflowVersion).where(
                KunlianWorkflowVersion.tenant_id == scope.tenant_id,
                KunlianWorkflowVersion.workflow_id == workflow_id,
                KunlianWorkflowVersion.connection_id == scope.connection_id,
                KunlianWorkflowVersion.current == True,  # noqa: E712
            )
        ).first()
        return row if row and row.tenant_id == scope.tenant_id else None

    @staticmethod
    def _entry(row):
        return {
            "workflow_id": row.workflow_id,
            "workflow_version_id": str(row.version_id),
            "sequence": row.sequence,
            "availability": row.availability,
            "descriptor_digest": (row.descriptor or {}).get("descriptor_digest"),
        }

    def _append(self, session, stream, row, kind, retired=None):
        data = {
            "event_id": uuid4().hex,
            "sequence": stream.sequence,
            "workflow_id": row.workflow_id,
            "change_type": kind,
            "current": self._entry(row),
            "retired_version_id": retired,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        session.add(
            KunlianWorkflowChange(
                tenant_id=row.tenant_id,
                connection_id=row.connection_id,
                sequence=stream.sequence,
                payload=data,
            )
        )
        return data

    def publish(self, scope, workflow_id, version_id, revision, descriptor, agent, knowledge, *, verify_scope=None):
        self._ensure_stream(scope)
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id, lock=True)
            version = self._version(session, flow, version_id, lock=True)
            if _publication_revision(flow, version) != revision:
                raise WorkflowRegistrationConflict()
            if verify_scope and not verify_scope(self._creation_by_workflow(session, scope.tenant_id, workflow_id)):
                raise WorkflowRegistrationConflict()
            stream = self._stream(session, scope, lock=True)
            current = self._current(session, scope, workflow_id)
            row = session.get(KunlianWorkflowVersion, (scope.tenant_id, scope.connection_id, workflow_id, version_id))
            if row:
                previous = version.data or {}
                if (
                    row.descriptor != descriptor
                    or previous.get(AGENT_BINDING, {}) != agent
                    or previous.get(KNOWLEDGE_BINDING, {}) != knowledge
                ):
                    raise WorkflowRegistrationConflict()
            retired = None
            stream.sequence += 1
            if current and current.version_id != version_id:
                current.current = False
                current.availability = "REPLACED"
                current.sequence = stream.sequence
                retired = str(current.version_id)
            if row is None:
                row = KunlianWorkflowVersion(
                    tenant_id=scope.tenant_id,
                    connection_id=scope.connection_id,
                    workflow_id=workflow_id,
                    version_id=version_id,
                    descriptor=descriptor,
                )
                session.add(row)
            row.current = True
            row.sequence = stream.sequence
            row.availability = "AVAILABLE" if descriptor else "INCOMPLETE"
            row.receipt = None
            graph = PlatformNodePublication.candidate_graph(version.data)
            PlatformNodePublication.write_publication(session, flow, version, graph, agent, knowledge)
            return self._append(session, stream, row, "PUBLISHED", retired)

    def unpublish(self, scope, workflow_id, version_id=None):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id, lock=True)
            row = self._current(session, scope, workflow_id)
            if version_id is not None:
                version = self._version(session, flow, version_id, lock=True)
                if flow.status == FlowStatus.ONLINE.value and version.is_current != 1:
                    raise WorkflowRegistrationConflict()
                if flow.status != FlowStatus.ONLINE.value and row and version_id != row.version_id:
                    raise WorkflowRegistrationConflict()
            flow.status = FlowStatus.OFFLINE.value
            if not row or row.availability == "OFFLINE":
                return None
            stream = self._stream(session, scope, lock=True)
            stream.sequence += 1
            row.availability = "OFFLINE"
            row.sequence = stream.sequence
            row.receipt = None
            return self._append(session, stream, row, "UNPUBLISHED")

    def highwater(self, scope):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            stream = self._stream(session, scope)
            return stream.sequence if stream else 0

    def delete_offline(self, scope, workflow_id):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            flow = self._flow(session, scope.tenant_id, workflow_id, lock=True)
            row = self._current(session, scope, workflow_id)
            if flow.status == FlowStatus.ONLINE.value or (row and row.availability != "OFFLINE"):
                raise WorkflowRegistrationConflict()
            for version in session.exec(select(FlowVersion).where(FlowVersion.flow_id == workflow_id)).all():
                version.is_delete = 1
            session.delete(flow)

    @staticmethod
    def _with_live_version(query):
        return (
            query.join(Flow, Flow.id == KunlianWorkflowVersion.workflow_id)
            .join(FlowVersion, FlowVersion.id == KunlianWorkflowVersion.version_id)
            .where(
                Flow.tenant_id == KunlianWorkflowVersion.tenant_id,
                Flow.flow_type == FlowType.WORKFLOW.value,
                Flow.status == FlowStatus.ONLINE.value,
                FlowVersion.tenant_id == KunlianWorkflowVersion.tenant_id,
                FlowVersion.flow_id == Flow.id,
                FlowVersion.is_current == 1,
                FlowVersion.is_delete == 0,
            )
        )

    def _is_live(self, session, row):
        if not row.current:
            return False
        query = select(KunlianWorkflowVersion.version_id).where(
            KunlianWorkflowVersion.tenant_id == row.tenant_id,
            KunlianWorkflowVersion.connection_id == row.connection_id,
            KunlianWorkflowVersion.workflow_id == row.workflow_id,
            KunlianWorkflowVersion.version_id == row.version_id,
        )
        return session.exec(self._with_live_version(query)).first() is not None

    def version(self, scope, workflow_id, version_id):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            row = session.get(KunlianWorkflowVersion, (scope.tenant_id, scope.connection_id, workflow_id, version_id))
            if row is None:
                raise WorkflowRegistrationDenied()
            entry = self._entry(row)
            if row.availability == "AVAILABLE" and not self._is_live(session, row):
                entry["availability"] = "OFFLINE"
            return {**entry, "descriptor": row.descriptor if entry["availability"] == "AVAILABLE" else None}

    def status(self, scope, workflow_id):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            row = self._current(session, scope, workflow_id)
            if row is None:
                return None
            entry = self._entry(row)
            if row.availability == "AVAILABLE" and not self._is_live(session, row):
                return {**entry, "availability": "OFFLINE", "status": "PENDING"}
            return {**entry, "status": (row.receipt or {}).get("status", "PENDING")}

    def draft_versions(self, scope, workflow_id):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            self._flow(session, scope.tenant_id, workflow_id)
            rows = session.exec(
                select(KunlianWorkflowVersion).where(
                    KunlianWorkflowVersion.connection_id == scope.connection_id,
                    KunlianWorkflowVersion.workflow_id == workflow_id,
                )
            ).all()
            frozen = {row.version_id for row in rows if row.tenant_id == scope.tenant_id}
            versions = session.exec(
                select(FlowVersion).where(
                    FlowVersion.flow_id == workflow_id,
                    FlowVersion.is_delete == 0,
                )
            ).all()
            return {
                version.id: {"draft_revision": version_revision(version), "registration_frozen": version.id in frozen}
                for version in versions
                if version.tenant_id == scope.tenant_id
            }

    @staticmethod
    def _check_position(stream, position):
        floor = stream.retained_after if stream else 0
        high = stream.sequence if stream else 0
        if position < floor or position > high:
            raise WorkflowRegistrationCursorExpired()
        return high

    def catalog_page(self, scope, base, after, limit):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            self._check_position(self._stream(session, scope), base)
            query = (
                select(KunlianWorkflowVersion)
                .where(
                    KunlianWorkflowVersion.tenant_id == scope.tenant_id,
                    KunlianWorkflowVersion.connection_id == scope.connection_id,
                    KunlianWorkflowVersion.current == True,  # noqa: E712
                    KunlianWorkflowVersion.availability == "AVAILABLE",
                    KunlianWorkflowVersion.workflow_id > after,
                )
                .order_by(KunlianWorkflowVersion.workflow_id)
                .limit(limit + 1)
            )
            rows = session.exec(self._with_live_version(query)).all()
            return [self._entry(row) for row in rows[:limit]], len(rows) > limit

    def change_page(self, scope, after, high, limit):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            committed = self._check_position(self._stream(session, scope), after)
            high = committed if high is None else high
            if not after <= high <= committed:
                raise WorkflowRegistrationCursorExpired()
            rows = session.exec(
                select(KunlianWorkflowChange)
                .where(
                    KunlianWorkflowChange.tenant_id == scope.tenant_id,
                    KunlianWorkflowChange.connection_id == scope.connection_id,
                    KunlianWorkflowChange.sequence > after,
                    KunlianWorkflowChange.sequence <= high,
                )
                .order_by(KunlianWorkflowChange.sequence)
                .limit(limit + 1)
            ).all()
            if len(rows) != min(high - after, limit + 1) or any(
                row.sequence != expected for expected, row in enumerate(rows, start=after + 1)
            ):
                raise WorkflowRegistrationCursorExpired()
            return [row.payload for row in rows[:limit]], high, len(rows) > limit

    def apply_receipt(self, scope, receipt):
        with tenant_execution_scope(scope.tenant_id), self.transaction() as session:
            # 按发布和下线的顺序加锁。流程删除后仍可确认下线回执。
            session.exec(
                select(Flow.id)
                .where(Flow.id == receipt.workflow_id, Flow.tenant_id == scope.tenant_id)
                .with_for_update()
            ).first()
            row = session.get(
                KunlianWorkflowVersion,
                (
                    scope.tenant_id,
                    scope.connection_id,
                    receipt.workflow_id,
                    int(receipt.workflow_version_id),
                ),
                with_for_update=True,
            )
            if not row:
                raise WorkflowRegistrationDenied()
            if not row.current or receipt.sequence != row.sequence:
                return False
            if row.availability == "AVAILABLE" and not self._is_live(session, row):
                return False
            expected = {"AVAILABLE": "REGISTERED", "OFFLINE": "REMOVED", "INCOMPLETE": "REMOVED"}[row.availability]
            if receipt.status not in {expected, "FAILED"}:
                raise WorkflowRegistrationConflict()
            if (row.receipt or {}).get("status") == expected:
                return receipt.status == expected
            row.receipt = receipt.model_dump(exclude_none=True)
            return True
