"""Interactive metadata edits on one actual physical version, outside SQL IO."""

from copy import deepcopy

from bisheng.common.errcode.knowledge import (
    KnowledgeFileNotExistError,
    KnowledgeMetadataFieldExistError,
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
        values = self._values(root, file.user_metadata, request, operation="replace")
        affected = tuple(sorted(set(file.user_metadata or {}) | set(values)))
        return await self._apply_metadata(user, context, root, file, expected, values, affected)

    @staticmethod
    def _values(root, current, request, *, operation):
        schema = {row["field_name"]: row for row in root.metadata_fields or []}
        values = {} if operation == "replace" else deepcopy(current or {})
        if operation == "delete":
            for name in request.field_names:
                if name not in values:
                    raise KnowledgeMetadataFieldNotExistError(field_name=name)
                values.pop(name)
            return values
        for item in request.user_metadata_list:
            name = item.field_name
            if name not in schema or (operation == "patch" and name not in values):
                raise KnowledgeMetadataFieldNotExistError(field_name=name)
            if operation == "add" and name in values:
                raise KnowledgeMetadataFieldExistError(field_name=name)
            kind = schema[name]["field_type"]
            try:
                value = utils.metadata_value_type_convert(value=item.field_value, target_type=kind)
            except (TypeError, ValueError) as error:
                raise KnowledgeMetadataValueTypeConvertError(field_name=name) from error
            if operation == "patch":
                # Original patch preserves the existing field metadata/timestamp.
                values[name]["field_value"] = value
            else:
                values[name] = {"field_value": value, "field_type": kind, "updated_at": item.updated_at}
        return values

    async def abatch_metadata(self, user, knowledge_id, requests, *, operation):
        """Validate the legacy batch before any external or SQL writes.

        Each physical file then uses the existing writer. This does not promise
        cross-file distributed atomicity.
        """
        if operation not in {"add", "patch", "delete"}:
            raise ValueError("Unsupported metadata operation")
        context, prepared, order = self._context(), {}, []
        async with self.sessions() as session:
            root = await self.repository.aread_root(session, knowledge_id)
        if root.type != 3:
            return None  # Keep NORMAL/QA on their existing legacy protocol.
        await require_business_action(
            get_current_open_api_principal() or user,
            resource_type="knowledge_space",
            resource_id=root.id,
            action="edit",
        )
        self._current(context)
        require_space_processing_idle(root, operation="file_user_metadata")
        for request in requests:
            root, file, expected = await self._read(request.knowledge_file_id, identity=user, validate=True)
            self._current(context)
            if root.id != knowledge_id:
                raise KnowledgeFileNotExistError()
            if root.type != 3:
                raise KnowledgeProcessingConflictError(reason="metadata_space_required")
            previous = prepared.get(file.id)
            if previous is not None and previous[2] != expected:
                raise KnowledgeOperationPlanChangedError()
            before = previous[3] if previous is not None else file.user_metadata
            values = self._values(root, before, request, operation=operation)
            fields = set(
                request.field_names
                if operation == "delete"
                else (item.field_name for item in request.user_metadata_list)
            )
            if previous is not None:
                fields.update(previous[4])
            prepared[file.id] = root, file, expected, values, tuple(sorted(fields))
            order.append(file.id)
        results = {}
        for file_id, (root, file, expected, values, affected) in prepared.items():
            results[file_id] = await self._apply_metadata(user, context, root, file, expected, values, affected)
        return [results[file_id] for file_id in order]

    async def _apply_metadata(self, user, context, root, file, expected, values, affected):

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
