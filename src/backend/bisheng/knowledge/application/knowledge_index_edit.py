"""Interactive metadata edits on one actual physical version, outside SQL IO."""

from copy import deepcopy

from bisheng.common.errcode.knowledge import (
    KnowledgeMetadataFieldNotExistError,
    KnowledgeMetadataValueTypeConvertError,
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingConflictError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain import utils
from bisheng.knowledge.domain.repositories.knowledge_index_edit_repository import KnowledgeIndexEditRepository
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import _digest
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import get_current_permission_actor


class KnowledgeIndexEditApplication:
    def __init__(self, *, session_factory=get_async_db_session, writer):
        self.sessions, self.writer = session_factory, writer
        self.repository = KnowledgeIndexEditRepository()
        self.versions = KnowledgeVersionReadRepository(session_factory)

    @staticmethod
    def _context():
        return get_current_tenant_id(), get_current_permission_actor(), get_current_open_api_principal()

    @classmethod
    def _current(cls, context):
        actual = cls._context()
        if actual[0] != context[0] or actual[1] is not context[1] or actual[2] is not context[2]:
            raise KnowledgeOperationPlanChangedError()

    async def _read(self, file_id, *, identity, expected=None, lock=False, session=None, validate=False):
        if session is None:
            async with self.sessions() as active:
                root, file = await self.repository.aread(active, file_id)
                anchor_facts = await self.repository.aanchor(active, root, file) if root.type == 3 else None
        else:
            root, file = await self.repository.aread(session, file_id, lock=lock)
            anchor_facts = await self.repository.aanchor(session, root, file) if root.type == 3 else None
        if root.type != 3:
            return root, file, None
        if session is None:
            actual_identity = get_current_open_api_principal() or identity
            await require_business_action(
                actual_identity, resource_type="knowledge_space", resource_id=root.id, action="edit"
            )
        require_space_processing_idle(root, operation="file_user_metadata")
        if file.status in {1, 4, 5}:
            raise KnowledgeProcessingConflictError(reason="metadata_file_processing")
        if validate:
            anchor = await self.versions.aget_anchor(tenant_id=get_current_tenant_id(), file_id=file.id)
            if (
                anchor is None
                or anchor.space.id != root.id
                or anchor_facts
                != (
                    anchor.version.model_dump(mode="json"),
                    anchor.document.model_dump(mode="json"),
                )
            ):
                raise KnowledgeOperationPlanChangedError()
        facts = _digest(
            {
                "root": {
                    key: getattr(root, key)
                    for key in (
                        "id",
                        "tenant_id",
                        "type",
                        "model_config_revision",
                        "index_generation",
                        "metadata_schema_revision",
                        "metadata_fields",
                        "state",
                        "model_transition",
                    )
                },
                "file": file.model_dump(mode="json"),
                "anchor": anchor_facts,
            }
        )
        if expected is not None and expected != facts:
            raise KnowledgeOperationPlanChangedError()
        return root, file, facts

    async def amodify_metadata(self, user, request):
        context = self._context()
        root, file, expected = await self._read(request.knowledge_file_id, identity=user, validate=True)
        if root.type != 3:
            return None  # Original NORMAL/QA metadata protocol remains its own path.
        self._current(context)
        schema = {row["field_name"]: row for row in root.metadata_fields or []}
        values = {}
        for item in request.user_metadata_list:
            if item.field_name not in schema:
                raise KnowledgeMetadataFieldNotExistError(field_name=item.field_name)
            kind = schema[item.field_name]["field_type"]
            try:
                value = utils.metadata_value_type_convert(value=item.field_value, target_type=kind)
            except (TypeError, ValueError) as error:
                raise KnowledgeMetadataValueTypeConvertError(field_name=item.field_name) from error
            values[item.field_name] = {"field_value": value, "field_type": kind, "updated_at": item.updated_at}
        affected = tuple(sorted(set(file.user_metadata or {}) | set(values)))

        async def guard():
            self._current(context)
            await self._read(file.id, identity=user, expected=expected)
            self._current(context)

        counts = {"milvus_count": 0, "es_count": 0}
        if affected:
            result = await self.writer(
                knowledge=root,
                invoke_user_id=user.user_id,
                file_id=file.id,
                affected_fields=affected,
                after_values=deepcopy(values),
                guard=guard,
            )
            from bisheng.worker.knowledge.metadata_worker import MetadataIndexResult

            if (
                not isinstance(result, MetadataIndexResult)
                or result.file_id != file.id
                or any(type(value) is not int or value < 0 for value in (result.milvus_count, result.es_count))
            ):
                raise KnowledgeOperationPlanChangedError()
            counts = {"milvus_count": result.milvus_count, "es_count": result.es_count}
        await guard()
        async with self.sessions() as session:
            async with session.begin():
                _, current, _ = await self._read(file.id, identity=user, expected=expected, lock=True, session=session)
                changed = await self.repository.awrite_metadata(session, file=current, values=values, user=user)
                self._current(context)
                if session.new or session.dirty or session.deleted:
                    raise KnowledgeOperationPlanChangedError()
        return {**changed.model_dump(mode="json"), "index_update": {"completed": True, **counts}}


def get_knowledge_index_editor():
    from bisheng.worker.knowledge.metadata_worker import apply_metadata_index_item

    return KnowledgeIndexEditApplication(writer=apply_metadata_index_item)
