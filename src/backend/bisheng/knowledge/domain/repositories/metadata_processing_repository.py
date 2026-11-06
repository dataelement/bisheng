"""Complete metadata scope and schema CAS in the caller's native transaction."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field, replace

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget


def metadata_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MetadataScopeItem:
    target: ResourceVersionTarget
    parent_id: int | None
    status: int
    source_revision: str
    values_revision: str
    user_metadata: dict | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class MetadataScope:
    tenant_id: int
    space_id: int
    schema_revision: int
    model_config_revision: int
    index_generation: str | None
    schema_fields: tuple[dict, ...] = field(repr=False)
    items: tuple[MetadataScopeItem, ...]


class MetadataProcessingRepository:
    @staticmethod
    def _context(session, space_id):
        if not isinstance(session, AsyncSession):
            raise TypeError("metadata processing requires the caller's native AsyncSession")
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="metadata_concrete_tenant_required")
        if type(space_id) is not int or space_id <= 0:
            raise SpaceNotFoundError()
        return tenant

    @staticmethod
    def _parent(path):
        if path in (None, "", "/"):
            return None
        try:
            parents = tuple(int(value) for value in path.strip("/").split("/"))
            if any(value <= 0 for value in parents):
                raise ValueError("invalid parent identity")
            return parents[-1]
        except (AttributeError, ValueError, TypeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="metadata_folder_path_invalid") from error

    @staticmethod
    def _locked(query, for_update):
        return query.with_for_update() if for_update else query

    async def aload_scope(self, session, space_id, *, for_update=False) -> MetadataScope:
        tenant = self._context(session, space_id)
        if type(for_update) is not bool:
            raise TypeError("for_update must be explicit")
        fields = (
            "id",
            "tenant_id",
            "metadata_fields",
            "metadata_schema_revision",
            "model_config_revision",
            "index_generation",
            "state",
            "model_transition",
        )
        root_query = select(*(getattr(Knowledge, name) for name in fields)).where(
            Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        # Column snapshots read current SQL facts without discarding unrelated
        # pending identity-map work or autoflushing another business operation.
        with session.no_autoflush, strict_tenant_filter():
            root = (await session.execute(self._locked(root_query, for_update))).mappings().one_or_none()
            if root is None or root["tenant_id"] != tenant:
                raise SpaceNotFoundError()
            schema = root["metadata_fields"]
            if schema is not None and (
                not isinstance(schema, list) or any(not isinstance(value, dict) for value in schema)
            ):
                raise KnowledgeOperationPlanConflictError(reason="metadata_schema_invalid")
            if (
                root["state"] in {KnowledgeState.COPYING.value, KnowledgeState.REBUILDING.value}
                or root["model_transition"]
            ):
                raise KnowledgeProcessingConflictError(reason="metadata_space_processing")
            active_query = (
                select(KnowledgeProcessingJob.id)
                .where(
                    KnowledgeProcessingJob.space_id == space_id,
                    KnowledgeProcessingJob.state.in_(("accepted", "running")),
                )
                .limit(1)
            )
            if (await session.exec(self._locked(active_query, for_update))).first() is not None:
                raise KnowledgeProcessingConflictError(reason="metadata_processing_conflict")
            physical, document, version = (
                KnowledgeFile.__table__,
                KnowledgeDocument.__table__,
                KnowledgeDocumentVersion.__table__,
            )
            # Selecting the owned Root anchors C3. Raw child columns retain
            # broken tenant/space links so integrity failures cannot vanish.
            files_query = (
                select(Knowledge.id, *physical.c, *document.c, *version.c)
                .select_from(Knowledge)
                .join(physical, physical.c.knowledge_id == Knowledge.id)
                .outerjoin(version, version.c.knowledge_file_id == physical.c.id)
                .outerjoin(document, document.c.id == version.c.document_id)
                .where(Knowledge.id == space_id)
                .order_by(physical.c.id, version.c.id)
            )
            documents_query = (
                select(Knowledge.id, document.c.id, document.c.primary_version_id, version.c.id)
                .select_from(Knowledge)
                .join(document, document.c.knowledge_id == Knowledge.id)
                .outerjoin(version, version.c.document_id == document.c.id)
                .where(Knowledge.id == space_id)
                .order_by(document.c.id, version.c.id)
            )
            rows = (await session.execute(self._locked(files_query, for_update))).all()
            chains = (await session.execute(self._locked(documents_query, for_update))).all()
        seen_files, seen_versions, primaries, items = set(), set(), {}, []
        for joined in rows:
            mapping = joined._mapping
            raw = {column.name: mapping[column] for column in physical.c}
            doc = {column.name: mapping[column] for column in document.c}
            ver = {column.name: mapping[column] for column in version.c}
            if raw["file_type"] == FileType.DIR.value:
                if ver["id"] is not None:
                    raise KnowledgeOperationPlanConflictError(reason="metadata_version_scope_incomplete")
                continue
            if (
                raw["tenant_id"] != tenant
                or raw["file_type"] != FileType.FILE.value
                or raw["id"] in seen_files
                or doc["id"] is None
                or doc["knowledge_id"] != space_id
                or ver["id"] is None
                or ver["version_no"] <= 0
            ):
                raise KnowledgeOperationPlanConflictError(reason="metadata_version_scope_incomplete")
            if raw["status"] not in {2, 3, 6, 7}:
                raise KnowledgeProcessingConflictError(reason="metadata_file_processing")
            seen_files.add(raw["id"])
            seen_versions.add(ver["id"])
            primary = primaries.setdefault(doc["id"], [])
            if ver["is_primary"]:
                primary.append(ver["id"])
            source = {
                key: raw[key]
                for key in (
                    "id",
                    "tenant_id",
                    "knowledge_id",
                    "file_type",
                    "file_source",
                    "object_name",
                    "md5",
                    "file_size",
                    "file_name",
                    "file_level_path",
                )
            }
            source["document_id"], source["version_id"], source["version_no"] = doc["id"], ver["id"], ver["version_no"]
            values = deepcopy(raw["user_metadata"])
            if values is not None and not isinstance(values, dict):
                raise KnowledgeOperationPlanConflictError(reason="metadata_values_invalid")
            items.append(
                MetadataScopeItem(
                    ResourceVersionTarget(file_id=raw["id"], document_id=doc["id"], version_id=ver["id"]),
                    self._parent(raw["file_level_path"]),
                    raw["status"],
                    metadata_digest(source),
                    metadata_digest(values),
                    values,
                )
            )
        actual_versions = set()
        for _, document_id, primary_id, version_id in chains:
            if (
                document_id not in primaries
                or version_id not in seen_versions
                or primaries[document_id] != [primary_id]
            ):
                raise KnowledgeOperationPlanConflictError(reason="metadata_version_scope_incomplete")
            actual_versions.add(version_id)
        if actual_versions != seen_versions:
            raise KnowledgeOperationPlanConflictError(reason="metadata_version_scope_incomplete")
        return MetadataScope(
            tenant,
            space_id,
            root["metadata_schema_revision"],
            root["model_config_revision"],
            root["index_generation"],
            tuple(deepcopy(root["metadata_fields"] or [])),
            tuple(items),
        )

    async def areplace_schema(self, session, scope: MetadataScope, *, after_schema: tuple[dict, ...]) -> MetadataScope:
        self._context(session, scope.space_id)
        current = await self.aload_scope(session, scope.space_id, for_update=True)
        if current != scope:
            raise KnowledgeOperationPlanConflictError(reason="metadata_scope_changed")
        fields = deepcopy(list(after_schema))
        query = (
            update(Knowledge)
            .where(
                Knowledge.id == scope.space_id,
                Knowledge.tenant_id == scope.tenant_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.metadata_schema_revision == scope.schema_revision,
                Knowledge.model_config_revision == scope.model_config_revision,
                Knowledge.index_generation == scope.index_generation,
            )
            .values(metadata_fields=fields, metadata_schema_revision=scope.schema_revision + 1)
            .execution_options(synchronize_session=False)
        )
        with session.no_autoflush:
            result = await session.execute(query)
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="metadata_schema_changed")
        await session.flush()
        return replace(current, schema_revision=current.schema_revision + 1, schema_fields=tuple(deepcopy(fields)))
