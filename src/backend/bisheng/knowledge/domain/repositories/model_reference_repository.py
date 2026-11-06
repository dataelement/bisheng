"""Owned Knowledge model configuration in the caller's native transaction."""

from copy import deepcopy

from sqlalchemy import inspect, update
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import ReferenceState, TargetType


class KnowledgeModelReferenceRepository:
    """No Session factory, begin, commit or rollback; both modes are native."""

    _protected = ("model", "model_transition", "model_config_revision", "index_generation")

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

    def _statement(self, knowledge_id=None, *, spaces=False, for_update=False):
        self._tenant_id()
        query = select(Knowledge)
        query = (
            query.where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
            if spaces
            else query.where(Knowledge.id == knowledge_id)
        )
        query = query.order_by(Knowledge.id)
        return query.with_for_update().execution_options(populate_existing=True) if for_update else query

    def get(self, session, knowledge_id, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            row = session.exec(self._statement(knowledge_id, for_update=for_update)).one_or_none()
        return row if row is not None and row.tenant_id == self._tenant_id() and self._kind(row) else None

    async def aget(self, session, knowledge_id, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.exec(self._statement(knowledge_id, for_update=for_update))).one_or_none()
        return row if row is not None and row.tenant_id == self._tenant_id() and self._kind(row) else None

    def list_spaces(self, session, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            rows = session.exec(self._statement(spaces=True, for_update=for_update)).all()
        return tuple(row for row in rows if row.tenant_id == self._tenant_id())

    async def alist_spaces(self, session, *, for_update=False):
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.exec(self._statement(spaces=True, for_update=for_update))).all()
        return tuple(row for row in rows if row.tenant_id == self._tenant_id())

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

    async def adelete(self, session, row):
        self._bound(session, row)
        await session.delete(row)
        await session.flush()
