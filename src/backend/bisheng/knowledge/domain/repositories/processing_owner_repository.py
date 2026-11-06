"""Actual full-version scope in the caller's native processing transaction."""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.schemas.processing_job import ProcessingTargetInput, ResourceVersionTarget


@dataclass(frozen=True, slots=True)
class ProcessingScopeVersion:
    target: ResourceVersionTarget
    file_name: str
    parent_id: int | None
    file_level_path: str | None
    version_no: int
    is_primary: bool
    status: int | None
    split_rule: str | None
    revision: str


class ProcessingOwnerRepository:
    @staticmethod
    def _parent(path):
        if path in (None, "", "/"):
            return None
        try:
            parents = tuple(int(value) for value in path.strip("/").split("/"))
            if any(value <= 0 for value in parents):
                raise ValueError("invalid folder identity")
            return parents[-1]
        except (TypeError, ValueError, AttributeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="processing_folder_path_invalid") from error

    async def aload_scope(
        self, session, space_id, targets=None, for_update=False
    ) -> tuple[ProcessingScopeVersion, ...]:
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0:
            raise RuntimeError("processing scope requires a concrete tenant")
        if type(for_update) is not bool:
            raise TypeError("for_update must be explicit")
        space_query = select(Knowledge).where(Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if for_update:
            space_query = space_query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            space = (await session.exec(space_query)).one_or_none()
        if space is None or space.tenant_id != tenant:
            raise SpaceNotFoundError()
        requested = None if targets is None else tuple(ProcessingTargetInput.model_validate(value) for value in targets)
        if requested is not None:
            keys = {(value.file_id, value.version_id) for value in requested}
            if len(keys) != len(requested):
                raise KnowledgeOperationPlanConflictError(reason="processing_duplicate_target")
            if not requested:
                return ()
        # Ownership follows the actual root and version FK. The outer join is
        # deliberate: a broken/cross-space physical link is an incomplete plan,
        # never a silently skipped version. Tenant equality is a relationship
        # integrity predicate; C3 still supplies the current candidate scope.
        physical_table = KnowledgeFile.__table__
        query = (
            select(Knowledge, KnowledgeDocument, KnowledgeDocumentVersion, *physical_table.c)
            .join(KnowledgeDocument, KnowledgeDocument.knowledge_id == Knowledge.id)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id)
            .outerjoin(
                physical_table,
                and_(
                    physical_table.c.id == KnowledgeDocumentVersion.knowledge_file_id,
                    physical_table.c.knowledge_id == KnowledgeDocument.knowledge_id,
                    physical_table.c.tenant_id == Knowledge.tenant_id,
                ),
            )
            .where(KnowledgeDocument.knowledge_id == space_id)
            .order_by(physical_table.c.id, KnowledgeDocumentVersion.id, KnowledgeDocument.id)
        )
        if requested is not None:
            version_ids = sorted({value.version_id for value in requested})
            query = query.where(
                or_(
                    *(
                        KnowledgeDocumentVersion.id.in_(version_ids[offset : offset + 500])
                        for offset in range(0, len(version_ids), 500)
                    )
                )
            )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            rows = (await session.exec(query)).all()
        result = []
        for joined in rows:
            root, document, version = joined[:3]
            # C3 scopes the selected owned root. Raw child column projection
            # keeps its integrity-checked OUTER JOIN intact: injecting a child
            # tenant WHERE would hide broken links rather than report them.
            physical = KnowledgeFile(**{column.name: joined._mapping[column] for column in physical_table.c})
            if (
                root.tenant_id != tenant
                or physical.id is None
                or physical.tenant_id != tenant
                or physical.knowledge_id != space_id
                or physical.file_type != FileType.FILE.value
            ):
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_incomplete")
            target = ResourceVersionTarget(file_id=physical.id, document_id=document.id, version_id=version.id)
            facts = {
                "document": document.model_dump(mode="json"),
                "version": version.model_dump(mode="json"),
                "file": physical.model_dump(mode="json"),
            }
            digest = hashlib.sha256(
                json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            result.append(
                ProcessingScopeVersion(
                    target,
                    physical.file_name,
                    self._parent(physical.file_level_path),
                    physical.file_level_path,
                    version.version_no,
                    version.is_primary,
                    physical.status,
                    physical.split_rule,
                    digest,
                )
            )
        if requested is not None:
            actual = {(value.target.file_id, value.target.version_id): value.target.document_id for value in result}
            if set(actual) != keys or any(
                value.document_id is not None and actual.get((value.file_id, value.version_id)) != value.document_id
                for value in requested
            ):
                raise KnowledgeOperationPlanConflictError(reason="processing_version_scope_changed")
        return tuple(result)
