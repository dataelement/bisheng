"""Owned Knowledge model configuration in the caller's native transaction."""

from copy import deepcopy

from sqlalchemy import delete, inspect, update
from sqlalchemy.orm import load_only
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob, deletion_now
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import ReferenceState, TargetType


class KnowledgeModelReferenceRepository:
    """No Session factory, begin, commit or rollback; both modes are native."""

    _protected = ("model", "model_transition", "model_config_revision", "index_generation")

    async def aload_disclosure_sources(self, session, *, knowledge_ids: tuple[int, ...]):
        """Only real metadata needed by the existing loaded-target adapter."""
        self._tenant_id()
        if (
            type(knowledge_ids) is not tuple
            or len(knowledge_ids) > 200
            or any(type(value) is not int or value <= 0 for value in knowledge_ids)
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_disclosure_invalid_batch")
        if not knowledge_ids:
            return ()
        ids = frozenset(knowledge_ids)
        for row in (*session.dirty, *session.deleted, *session.new):
            if not isinstance(row, Knowledge):
                continue
            original = inspect(row).identity
            # The current PK can already have been edited. Checking the real
            # persistent identity also avoids lazy loading an expired PK.
            if (original is not None and original[0] in ids) or row.__dict__.get("id") in ids:
                raise ResourceReferenceInvalidError(reason="knowledge_disclosure_unflushed_source_changes")
        fields = (
            Knowledge.id,
            Knowledge.tenant_id,
            Knowledge.name,
            Knowledge.type,
            Knowledge.state,
            Knowledge.user_id,
            Knowledge.update_time,
        )
        statement = (
            select(Knowledge)
            .options(load_only(*fields, raiseload=True))
            .execution_options(populate_existing=True)
            .where(Knowledge.id.in_(sorted(set(knowledge_ids))), Knowledge.type.in_((0, 1, 3)))
            .order_by(Knowledge.id)
        )
        with session.no_autoflush, strict_tenant_filter():
            return tuple((await session.execute(statement)).scalars())

    def _source_statement(self, knowledge_id, *, for_update):
        self._tenant_id()
        fields = (
            "id",
            "tenant_id",
            "type",
            "user_id",
            "name",
            "description",
            "state",
            "model",
            "model_transition",
            "model_config_revision",
            "index_generation",
            "index_name",
            "collection_name",
        )
        query = select(*(getattr(Knowledge, name) for name in fields)).where(
            Knowledge.id == knowledge_id,
            Knowledge.type.in_(
                (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value, KnowledgeTypeEnum.SPACE.value)
            ),
        )
        return query.with_for_update() if for_update else query

    def load_source(self, session, knowledge_id, *, for_update=False):
        # Ordinary C3 candidate scope remains intact. The business SourceOwner
        # still performs the original actor's exact C4 resource decision.
        with session.no_autoflush:
            row = session.execute(self._source_statement(knowledge_id, for_update=for_update)).mappings().one_or_none()
        return deepcopy(dict(row)) if row is not None else None

    async def aload_source(self, session, knowledge_id, *, for_update=False):
        with session.no_autoflush:
            row = (
                (await session.execute(self._source_statement(knowledge_id, for_update=for_update)))
                .mappings()
                .one_or_none()
            )
        return deepcopy(dict(row)) if row is not None else None

    def load_cleanup_identity(self, session, knowledge_id, *, deletion_job=None):
        tenant = self._tenant_id()
        if deletion_job is None:
            row = self.load_source(session, knowledge_id)
            if row is None or row["tenant_id"] != tenant:
                raise ResourceReferenceInvalidError(reason="knowledge_cleanup_resource_not_owned")
            return row
        if not isinstance(deletion_job, KnowledgeSpaceDeleteJob):
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_persisted_job_required")
        model = KnowledgeSpaceDeleteJob
        query = select(
            model.id,
            model.tenant_id,
            model.space_id,
            model.manifest,
            model.state,
            model.lease_token,
            model.lease_until,
            model.attempts,
            model.operation_type,
            model.business_phase,
        ).where(model.id == deletion_job.id)
        with session.no_autoflush, strict_tenant_filter():
            row = session.execute(query).mappings().one_or_none()
        if (
            row is None
            or row["tenant_id"] != tenant
            or deletion_job.tenant_id != tenant
            or row["space_id"] != knowledge_id
            or deletion_job.space_id != knowledge_id
            or row["state"] != "RUNNING"
            or not row["lease_token"]
            or row["lease_token"] != deletion_job.lease_token
            or row["attempts"] != deletion_job.attempts
            or row["lease_until"] is None
            or row["lease_until"] <= deletion_now()
            or row["manifest"] != deletion_job.manifest
            or (row["operation_type"] is not None and row["business_phase"] != "finalized")
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_job_changed")
        knowledge = row["manifest"].get("knowledge") if isinstance(row["manifest"], dict) else None
        if (
            not isinstance(knowledge, dict)
            or knowledge.get("id") != knowledge_id
            or knowledge.get("tenant_id") != tenant
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_manifest_target_changed")
        return deepcopy(knowledge)

    def _embedding_queries(self, session, verifier, source_key, context):
        self._tenant_id()
        # Only original, current-transaction Owner receipts authorize this exact
        # cross-tenant column projection. Targets were locked before the root;
        # this must not acquire a new parent/server lock afterwards.
        targets = verifier.validate_binding_receipts(session, source_key, context.receipts, context.locked_targets)
        return tuple(
            (
                target.key,
                select(LLMModel.model_type)
                .join(LLMServer, LLMServer.id == LLMModel.server_id)
                .where(
                    LLMModel.id == int(target.key.target_id),
                    LLMModel.server_id == int(target.model_server_id),
                    LLMModel.tenant_id == target.target_tenant_id,
                    LLMServer.id == int(target.model_server_id),
                    LLMServer.tenant_id == target.target_tenant_id,
                ),
            )
            for target in targets
            if target.key.target_type == TargetType.MODEL
            and target.state == ReferenceState.VALID
            and target.new_binding_allowed
        )

    def model_kinds(self, session, verifier, source_key, context):
        queries = self._embedding_queries(session, verifier, source_key, context)
        with session.no_autoflush, bypass_tenant_filter():
            return {key: session.exec(query).one_or_none() for key, query in queries}

    async def amodel_kinds(self, session, verifier, source_key, context):
        queries = self._embedding_queries(session, verifier, source_key, context)
        with session.no_autoflush, bypass_tenant_filter():
            return {key: (await session.exec(query)).one_or_none() for key, query in queries}

    @staticmethod
    def _tenant_id():
        tenant_id = _resolve_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="knowledge_model_tenant_required")
        return tenant_id

    @staticmethod
    def _kind(row):
        return row.type in {KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value, KnowledgeTypeEnum.SPACE.value}

    def _statement(self, knowledge_id, *, for_update=False):
        self._tenant_id()
        query = select(Knowledge).where(Knowledge.id == knowledge_id)
        return query.with_for_update().execution_options(populate_existing=True) if for_update else query

    def get(self, session, knowledge_id, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            row = session.exec(self._statement(knowledge_id, for_update=for_update)).one_or_none()
        return row if row is not None and row.tenant_id == self._tenant_id() and self._kind(row) else None

    async def aget(self, session, knowledge_id, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.exec(self._statement(knowledge_id, for_update=for_update))).one_or_none()
        return row if row is not None and row.tenant_id == self._tenant_id() and self._kind(row) else None

    def _new(self, session, row):
        tenant_id = self._tenant_id()
        if row.tenant_id not in (None, tenant_id) or inspect(row).persistent or not self._kind(row):
            raise ResourceReferenceInvalidError(reason="knowledge_model_resource_invalid")
        row.tenant_id = tenant_id
        session.add(row)

    def insert(self, session, row):
        self._new(session, row)
        session.flush()
        return row

    async def ainsert(self, session, row):
        self._new(session, row)
        await session.flush()
        return row

    async def aadd_space_creator(self, session, row, *, user_id):
        """A creator belongs to this actual newly flushed, owned SPACE parent."""
        self._bound(session, row)
        if row.type != KnowledgeTypeEnum.SPACE.value or type(user_id) is not int or row.user_id != user_id:
            raise ResourceReferenceInvalidError(reason="knowledge_space_creator_parent_invalid")
        member = SpaceChannelMember(
            business_id=str(row.id),
            business_type=BusinessTypeEnum.SPACE,
            user_id=user_id,
            user_role=UserRoleEnum.CREATOR,
            status=MembershipStatusEnum.ACTIVE,
        )
        session.add(member)
        await session.flush()
        return member

    def _bound(self, session, row):
        state = inspect(row)
        owner = getattr(session, "sync_session", session)
        if (
            not state.persistent
            or state.session is not owner
            or row.tenant_id != self._tenant_id()
            or not self._kind(row)
            or any(state.attrs[name].history.has_changes() for name in ("tenant_id", "id", "type"))
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_resource_invalid")

    def _metadata(self, session, row):
        self._bound(session, row)
        if any(inspect(row).attrs[name].history.has_changes() for name in self._protected):
            raise ResourceReferenceInvalidError(reason="knowledge_model_write_requires_configuration_cas")

    def save(self, session, row):
        self._metadata(session, row)
        session.flush()
        return row

    async def asave(self, session, row):
        self._metadata(session, row)
        await session.flush()
        return row

    def _configuration_update(
        self, session, row, *, model, transition, expected_revision, expected_generation, new_generation
    ):
        self._metadata(session, row)
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or row.model_config_revision != expected_revision
            or row.index_generation != expected_generation
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
        if not isinstance(new_generation, str) or not new_generation or len(new_generation) > 64:
            raise ValueError("new model configuration requires a bounded index generation")
        # Auto-injected SELECT predicates do not protect this bulk UPDATE.
        # Database CAS also rejects an object read before a competing commit.
        return (
            update(Knowledge)
            .where(
                Knowledge.id == row.id,
                Knowledge.tenant_id == self._tenant_id(),
                Knowledge.model_config_revision == expected_revision,
                Knowledge.index_generation == expected_generation,
            )
            .values(
                model=model,
                model_transition=deepcopy(transition),
                model_config_revision=expected_revision + 1,
                index_generation=new_generation,
            )
            .execution_options(synchronize_session=False)
        )

    def apply_model_configuration(self, session, row, **values):
        query = self._configuration_update(session, row, **values)
        with session.no_autoflush:
            result = session.execute(query)
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
        with strict_tenant_filter():
            session.refresh(row, attribute_names=self._protected)
        return row

    async def aapply_model_configuration(self, session, row, **values):
        query = self._configuration_update(session, row, **values)
        with session.no_autoflush:
            result = await session.execute(query)
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
        with strict_tenant_filter():
            await session.refresh(row, attribute_names=self._protected)
        return row

    def delete(self, session, row):
        self._bound(session, row)
        session.delete(row)
        session.flush()

    def _content_deletes(self, session, row):
        self._metadata(session, row)
        tenant = self._tenant_id()
        # Bulk DML does not receive C3's SELECT injection. The current owned
        # parent and exact tenant protect both files/folders and QA pairs.
        models = (
            (KnowledgeFile, QAKnowledge)
            if row.type in {KnowledgeTypeEnum.QA.value, KnowledgeTypeEnum.SPACE.value}
            else (KnowledgeFile,)
        )
        return tuple(delete(model).where(model.knowledge_id == row.id, model.tenant_id == tenant) for model in models)

    def clear_contents(self, session, row):
        for query in self._content_deletes(session, row):
            session.execute(query)
        session.flush()

    async def aclear_contents(self, session, row):
        for query in self._content_deletes(session, row):
            await session.execute(query)
        await session.flush()

    async def adelete(self, session, row):
        self._bound(session, row)
        await session.delete(row)
        await session.flush()
