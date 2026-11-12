"""Bounded original resource facts for M2, without migration authority.

The caller owns the native transaction and invokes the global integrity probes
once per run. Unowned document/version rows have no trustworthy tenant; those
probes diagnose them before the tenant-anchored pages are consumed.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy import Integer, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.tag import Tag, TagLink
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.repositories.unification_inventory_repository import InventoryPage

RESOURCE_COLUMNS = (
    "user_id",
    "tenant_id",
    "name",
    "type",
    "description",
    "model",
    "collection_name",
    "index_name",
    "state",
    "is_released",
    "auth_type",
    "is_shared",
    "auto_tag_enabled",
    "auto_tag_library_id",
    "metadata_fields",
    "create_time",
    "update_time",
    "id",
    "creation_request_id",
    "creation_payload_hash",
)
NEUTRAL_COLUMNS = (
    "processing_defaults",
    "processing_config_version",
    "metadata_schema_revision",
    "model_config_revision",
    "model_transition",
    "index_generation",
    "migration_origin",
)
FILE_COLUMNS = (
    "user_id",
    "user_name",
    "knowledge_id",
    "thumbnails",
    "file_name",
    "file_type",
    "file_source",
    "level",
    "file_level_path",
    "abstract",
    "file_size",
    "md5",
    "parse_type",
    "split_rule",
    "preview_file_object_name",
    "bbox_object_name",
    "status",
    "object_name",
    "user_metadata",
    "remark",
    "file_encoding",
    "simhash",
    "similar_status",
    "updater_id",
    "updater_name",
    "tenant_id",
    "create_time",
    "update_time",
    "id",
)
DOCUMENT_COLUMNS = (
    "knowledge_id",
    "file_level_path",
    "level",
    "primary_version_id",
    "create_time",
    "update_time",
    "id",
)
VERSION_COLUMNS = ("document_id", "knowledge_file_id", "version_no", "is_primary", "create_time", "update_time", "id")
QA_COLUMNS = (
    "user_id",
    "knowledge_id",
    "questions",
    "answers",
    "source",
    "status",
    "extra_meta",
    "remark",
    "tenant_id",
    "create_time",
    "update_time",
    "id",
)
TAG_COLUMNS = ("name", "business_type", "business_id", "user_id", "tenant_id", "create_time", "update_time", "id")
LINK_COLUMNS = ("tag_id", "resource_id", "resource_type", "user_id", "tenant_id", "create_time", "update_time", "id")
LIBRARY_COLUMNS = (
    "tenant_id",
    "name",
    "description",
    "tags",
    "tag_count",
    "is_builtin",
    "owner_knowledge_id",
    "user_id",
    "create_time",
    "update_time",
    "id",
)
DEPARTMENT_COLUMNS = (
    "tenant_id",
    "department_id",
    "space_id",
    "created_by",
    "approval_enabled",
    "sensitive_check_enabled",
    "is_hidden",
    "create_time",
    "update_time",
    "id",
)
ANCESTOR_COLUMNS = ("id", "tenant_id", "knowledge_id", "file_type", "level", "file_level_path", "update_time")
JSON_COLUMNS = frozenset(
    {"metadata_fields", "processing_defaults", "model_transition", "user_metadata", "questions", "tags"}
)


def _blocked(reason, **facts):
    raise KnowledgeOperationPlanConflictError(reason=f"unification_resource_{reason}", **facts)


def _scope(session):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
    ):
        _blocked("native_transaction_scope_required")
    return tenant


def _canonical(value):
    def scalar(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError("unsupported original scalar")

    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=scalar
        ).encode()
    except (TypeError, ValueError, RecursionError):
        _blocked("invalid_original_json")


def _values(row, columns):
    values = {name: deepcopy(row[name].value if isinstance(row[name], Enum) else row[name]) for name in columns}
    for name in JSON_COLUMNS.intersection(values):
        _canonical(values[name])
    return values


@dataclass(frozen=True, slots=True)
class NeutralKnowledgeFacts:
    processing_defaults: dict | None = field(repr=False)
    processing_config_version: int
    metadata_schema_revision: int
    model_config_revision: int
    model_transition: dict | None = field(repr=False)
    index_generation: str | None
    migration_origin: str | None


@dataclass(frozen=True, slots=True)
class ResourceRow:
    user_id: int | None
    tenant_id: int
    name: str = field(repr=False)
    type: int
    description: str | None = field(repr=False)
    model: str | None = field(repr=False)
    collection_name: str | None = field(repr=False)
    index_name: str | None = field(repr=False)
    state: int | None
    is_released: bool
    auth_type: str
    is_shared: bool
    auto_tag_enabled: bool
    auto_tag_library_id: int | None
    metadata_fields: list[dict] | None = field(repr=False)
    create_time: datetime | None
    update_time: datetime | None
    id: int
    creation_request_id: str | None = field(repr=False)
    creation_payload_hash: str | None = field(repr=False)
    neutral: NeutralKnowledgeFacts
    old_business_digest: str


@dataclass(frozen=True, slots=True)
class FileRow:
    user_id: int | None
    user_name: str | None = field(repr=False)
    knowledge_id: int
    thumbnails: str | None = field(repr=False)
    file_name: str = field(repr=False)
    file_type: int
    file_source: str | None = field(repr=False)
    level: int | None
    file_level_path: str | None = field(repr=False)
    abstract: str | None = field(repr=False)
    file_size: int | None
    md5: str | None = field(repr=False)
    parse_type: str | None = field(repr=False)
    split_rule: str | None = field(repr=False)
    preview_file_object_name: str | None = field(repr=False)
    bbox_object_name: str | None = field(repr=False)
    status: int | None
    object_name: str | None = field(repr=False)
    user_metadata: dict | None = field(repr=False)
    remark: str | None = field(repr=False)
    file_encoding: str | None = field(repr=False)
    simhash: str | None = field(repr=False)
    similar_status: int
    updater_id: int | None
    updater_name: str | None = field(repr=False)
    tenant_id: int
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class DocumentRow:
    knowledge_id: int
    file_level_path: str | None
    level: int | None
    primary_version_id: int | None
    create_time: datetime | None
    update_time: datetime | None
    id: int
    parent_tenant_id: int | None
    parent_knowledge_type: int | None


@dataclass(frozen=True, slots=True)
class VersionRow:
    document_id: int
    knowledge_file_id: int
    version_no: int
    is_primary: bool
    create_time: datetime | None
    update_time: datetime | None
    id: int
    knowledge_id: int | None
    parent_tenant_id: int | None
    file_knowledge_id: int | None
    file_tenant_id: int | None
    file_type: int | None
    file_space_tenant_id: int | None


@dataclass(frozen=True, slots=True)
class QARow:
    user_id: int | None
    knowledge_id: int
    questions: list | None = field(repr=False)
    answers: str | None = field(repr=False)
    source: int | None
    status: int | None
    extra_meta: str | None = field(repr=False)
    remark: str | None = field(repr=False)
    tenant_id: int
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class TagRow:
    name: str | None = field(repr=False)
    business_type: str
    business_id: str | None
    user_id: int
    tenant_id: int
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class TagLinkRow:
    tag_id: int
    resource_id: str
    resource_type: int
    user_id: int
    tenant_id: int
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class TagLibraryRow:
    tenant_id: int
    name: str = field(repr=False)
    description: str | None = field(repr=False)
    tags: list = field(repr=False)
    tag_count: int
    is_builtin: bool
    owner_knowledge_id: int | None
    user_id: int
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class DepartmentSpaceRow:
    tenant_id: int
    department_id: int
    space_id: int
    created_by: int
    approval_enabled: bool
    sensitive_check_enabled: bool
    is_hidden: bool
    create_time: datetime | None
    update_time: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class FileAncestorFact:
    id: int
    exists: bool
    tenant_id: int | None
    knowledge_id: int | None
    file_type: int | None
    level: int | None
    file_level_path: str | None
    update_time: datetime | None


class UnificationResourceRepository:
    @staticmethod
    async def _read(session, statement, *, global_facts=False):
        _scope(session)
        with session.no_autoflush, strict_tenant_filter():
            try:
                if global_facts:
                    with bypass_tenant_filter():
                        return tuple((await session.execute(statement)).mappings())
                return tuple((await session.execute(statement)).mappings())
            except (ValueError, TypeError):
                _blocked("invalid_original_json")

    async def _page(self, session, model, columns, row_type, after_id, limit, *, statement=None, extra=()):
        tenant = _scope(session)
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or (after_id is not None and (type(after_id) is not int or after_id <= 0))
        ):
            _blocked("invalid_page")
        query = select(*(getattr(model, name) for name in columns)) if statement is None else statement
        if after_id is not None:
            query = query.where(model.id > after_id)
        rows = await self._read(session, query.order_by(model.id).limit(limit + 1))
        for row in rows:
            owner = row.get("tenant_id", row.get("parent_tenant_id"))
            if owner != tenant:
                _blocked("page_tenant_mismatch", id=row["id"])
        items = []
        for row in rows[:limit]:
            values = _values(row, columns)
            if row_type is ResourceRow:
                items.append(
                    ResourceRow(
                        **values,
                        neutral=NeutralKnowledgeFacts(**_values(row, NEUTRAL_COLUMNS)),
                        old_business_digest=hashlib.sha256(_canonical(values)).hexdigest(),
                    )
                )
            else:
                items.append(row_type(**values, **{name: row[name] for name in extra}))
        return InventoryPage(tuple(items), items[-1].id if len(rows) > limit else None)

    async def alist_resources(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[ResourceRow]:
        query = select(*(getattr(Knowledge, name) for name in (*RESOURCE_COLUMNS, *NEUTRAL_COLUMNS)))
        return await self._page(session, Knowledge, RESOURCE_COLUMNS, ResourceRow, after_id, limit, statement=query)

    async def alist_files(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[FileRow]:
        return await self._page(session, KnowledgeFile, FILE_COLUMNS, FileRow, after_id, limit)

    async def aload_retention_rows(self, session, *, resource_ids=(), file_ids=()):
        tenant = _scope(session)
        output = []
        for model, ids, columns, row_type in (
            (Knowledge, resource_ids, RESOURCE_COLUMNS, ResourceRow),
            (KnowledgeFile, file_ids, FILE_COLUMNS, FileRow),
        ):
            if (
                type(ids) is not tuple
                or len(ids) > 199
                or len(set(ids)) != len(ids)
                or any(type(v) is not int or v <= 0 for v in ids)
            ):
                _blocked("invalid_retention_row_ids")
            if not ids:
                output.append(())
                continue
            selected = (*columns, *NEUTRAL_COLUMNS) if model is Knowledge else columns
            rows = await self._read(
                session,
                select(*(getattr(model, name) for name in selected))
                .where(model.tenant_id == tenant, model.id.in_(ids))
                .order_by(model.id),
            )
            if {row["id"] for row in rows} != set(ids):
                _blocked("retention_row_missing")
            values = []
            for row in rows:
                raw = _values(row, columns)
                if row_type is ResourceRow:
                    values.append(
                        ResourceRow(
                            **raw,
                            neutral=NeutralKnowledgeFacts(**_values(row, NEUTRAL_COLUMNS)),
                            old_business_digest=hashlib.sha256(_canonical(raw)).hexdigest(),
                        )
                    )
                else:
                    values.append(FileRow(**raw))
            output.append(tuple(values))
        return tuple(output)

    async def acount_resource_files(self, session: AsyncSession, *, resource_ids: tuple[int, ...]):
        """Count every managed file/folder in one native tenant snapshot."""
        tenant = _scope(session)
        if (
            type(resource_ids) is not tuple
            or not 1 <= len(resource_ids) <= 199
            or len(set(resource_ids)) != len(resource_ids)
            or any(type(ident) is not int or ident <= 0 for ident in resource_ids)
        ):
            _blocked("invalid_file_count_resources")
        resources = await self._read(
            session,
            select(Knowledge.id).where(Knowledge.tenant_id == tenant, Knowledge.id.in_(resource_ids)),
        )
        if {row["id"] for row in resources} != set(resource_ids):
            _blocked("file_count_resource_scope_changed")
        rows = await self._read(
            session,
            select(KnowledgeFile.knowledge_id, func.count().label("file_count"))
            .where(KnowledgeFile.tenant_id == tenant, KnowledgeFile.knowledge_id.in_(resource_ids))
            .group_by(KnowledgeFile.knowledge_id),
        )
        counts = dict.fromkeys(resource_ids, 0)
        for row in rows:
            counts[row["knowledge_id"]] = row["file_count"]
        return counts

    async def avalidate_retained_index_bindings(self, session: AsyncSession, *, bindings: tuple):
        tenant = _scope(session)
        if type(bindings) is not tuple or not bindings:
            _blocked("retained_index_bindings_required")
        for offset in range(0, len(bindings), 199):
            batch = bindings[offset : offset + 199]
            if any(type(row) is not tuple or len(row) != 3 for row in batch):
                _blocked("invalid_retained_index_binding")
            ids = tuple(row[0] for row in batch)
            counts = await self.acount_resource_files(session, resource_ids=ids)
            rows = await self._read(
                session,
                select(Knowledge.id, Knowledge.type, Knowledge.index_name, Knowledge.collection_name).where(
                    Knowledge.tenant_id == tenant, Knowledge.id.in_(ids)
                ),
            )
            expected = {ident: (index, collection) for ident, index, collection in batch}
            if any(
                row["type"] not in {0, 3}
                or counts[row["id"]] != 0
                or (row["index_name"], row["collection_name"]) != expected[row["id"]]
                for row in rows
            ):
                _blocked("retained_index_live_state_changed")

    async def alist_documents(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[DocumentRow]:
        tenant = _scope(session)
        parent = Knowledge.__table__.alias("m2_document_space")
        query = (
            select(
                *(getattr(KnowledgeDocument, name) for name in DOCUMENT_COLUMNS),
                parent.c.tenant_id.label("parent_tenant_id"),
                parent.c.type.label("parent_knowledge_type"),
            )
            .outerjoin(parent, parent.c.id == KnowledgeDocument.knowledge_id)
            .where(parent.c.tenant_id == tenant)
        )
        return await self._page(
            session,
            KnowledgeDocument,
            DOCUMENT_COLUMNS,
            DocumentRow,
            after_id,
            limit,
            statement=query,
            extra=("parent_tenant_id", "parent_knowledge_type"),
        )

    async def alist_versions(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[VersionRow]:
        tenant = _scope(session)
        doc, space = (
            KnowledgeDocument.__table__.alias("m2_version_document"),
            Knowledge.__table__.alias("m2_version_space"),
        )
        physical, file_space = (
            KnowledgeFile.__table__.alias("m2_version_file"),
            Knowledge.__table__.alias("m2_version_file_space"),
        )
        extra = (
            "knowledge_id",
            "parent_tenant_id",
            "file_knowledge_id",
            "file_tenant_id",
            "file_type",
            "file_space_tenant_id",
        )
        query = (
            select(
                *(getattr(KnowledgeDocumentVersion, name) for name in VERSION_COLUMNS),
                doc.c.knowledge_id.label("knowledge_id"),
                space.c.tenant_id.label("parent_tenant_id"),
                physical.c.knowledge_id.label("file_knowledge_id"),
                physical.c.tenant_id.label("file_tenant_id"),
                physical.c.file_type.label("file_type"),
                file_space.c.tenant_id.label("file_space_tenant_id"),
            )
            .outerjoin(doc, doc.c.id == KnowledgeDocumentVersion.document_id)
            .outerjoin(space, space.c.id == doc.c.knowledge_id)
            .outerjoin(physical, physical.c.id == KnowledgeDocumentVersion.knowledge_file_id)
            .outerjoin(file_space, file_space.c.id == physical.c.knowledge_id)
            .where(space.c.tenant_id == tenant)
        )
        return await self._page(
            session,
            KnowledgeDocumentVersion,
            VERSION_COLUMNS,
            VersionRow,
            after_id,
            limit,
            statement=query,
            extra=extra,
        )

    async def alist_qa(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[QARow]:
        return await self._page(session, QAKnowledge, QA_COLUMNS, QARow, after_id, limit)

    async def alist_tags(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[TagRow]:
        return await self._page(session, Tag, TAG_COLUMNS, TagRow, after_id, limit)

    async def alist_tag_links(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[TagLinkRow]:
        return await self._page(session, TagLink, LINK_COLUMNS, TagLinkRow, after_id, limit)

    async def alist_tag_libraries(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[TagLibraryRow]:
        return await self._page(session, KnowledgeSpaceTagLibrary, LIBRARY_COLUMNS, TagLibraryRow, after_id, limit)

    async def alist_department_spaces(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[DepartmentSpaceRow]:
        return await self._page(
            session, DepartmentKnowledgeSpace, DEPARTMENT_COLUMNS, DepartmentSpaceRow, after_id, limit
        )

    async def _probe(self, session, statement, reason):
        rows = await self._read(session, statement.limit(1), global_facts=True)
        if rows:
            _blocked(reason, id=rows[0]["id"])

    async def avalidate_global_integrity(self, session: AsyncSession) -> None:
        _scope(session)
        for model in (
            Knowledge,
            KnowledgeFile,
            QAKnowledge,
            Tag,
            TagLink,
            KnowledgeSpaceTagLibrary,
            DepartmentKnowledgeSpace,
        ):
            source, tenant = model.__table__.alias("m2_scope_row"), Tenant.__table__.alias("m2_scope_tenant")
            await self._probe(
                session,
                select(source.c.id)
                .outerjoin(tenant, tenant.c.id == source.c.tenant_id)
                .where(or_(source.c.tenant_id.is_(None), source.c.tenant_id <= 0, tenant.c.id.is_(None))),
                f"invalid_tenant_{model.__tablename__}",
            )
        creation = Knowledge.__table__.alias("m2_projected_creation")
        target_type = case((creation.c.type == 0, 3), else_=creation.c.type)
        # The database column's collation defines the actual UNIQUE semantics.
        # Empty and padded strings remain keys; only SQL NULL is exempt.
        await self._probe(
            session,
            select(func.min(creation.c.id).label("id"))
            .where(
                creation.c.type.in_((0, 3)),
                creation.c.user_id.is_not(None),
                creation.c.creation_request_id.is_not(None),
            )
            .group_by(creation.c.tenant_id, creation.c.user_id, target_type, creation.c.creation_request_id)
            .having(func.count() > 1),
            "projected_creation_conflict",
        )
        physical, space = KnowledgeFile.__table__.alias("m2_file_row"), Knowledge.__table__.alias("m2_file_parent")
        await self._probe(
            session,
            select(physical.c.id)
            .outerjoin(space, space.c.id == physical.c.knowledge_id)
            .where(or_(space.c.id.is_(None), space.c.tenant_id != physical.c.tenant_id)),
            "file_parent_invalid",
        )
        doc, doc_space = KnowledgeDocument.__table__.alias("m2_doc_row"), Knowledge.__table__.alias("m2_doc_parent")
        await self._probe(
            session,
            select(doc.c.id).outerjoin(doc_space, doc_space.c.id == doc.c.knowledge_id).where(doc_space.c.id.is_(None)),
            "document_parent_invalid",
        )
        version = KnowledgeDocumentVersion.__table__.alias("m2_version_row")
        query = (
            select(version.c.id)
            .outerjoin(doc, doc.c.id == version.c.document_id)
            .outerjoin(doc_space, doc_space.c.id == doc.c.knowledge_id)
            .outerjoin(physical, physical.c.id == version.c.knowledge_file_id)
            .outerjoin(space, space.c.id == physical.c.knowledge_id)
            .where(
                or_(
                    doc.c.id.is_(None),
                    doc_space.c.id.is_(None),
                    physical.c.id.is_(None),
                    space.c.id.is_(None),
                    physical.c.tenant_id != doc_space.c.tenant_id,
                    space.c.tenant_id != doc_space.c.tenant_id,
                    physical.c.knowledge_id != doc.c.knowledge_id,
                    physical.c.file_type.is_(None),
                    physical.c.file_type != FileType.FILE.value,
                )
            )
        )
        await self._probe(session, query, "version_parent_invalid")
        await self._probe(
            session,
            select(doc.c.id)
            .outerjoin(version, version.c.id == doc.c.primary_version_id)
            .where(
                doc.c.primary_version_id.is_not(None), or_(version.c.id.is_(None), version.c.document_id != doc.c.id)
            ),
            "primary_pointer_invalid",
        )
        link = TagLink.__table__.alias("m2_relation_link")
        tag = Tag.__table__.alias("m2_relation_tag")
        owner = Knowledge.__table__.alias("m2_tag_owner")
        knowledge_id = case((tag.c.business_type == "knowledge", cast(tag.c.business_id, Integer)), else_=None)
        related = or_(
            link.c.resource_type.in_((8, 9)),
            and_(tag.c.business_type == "knowledge", owner.c.type == 0, owner.c.tenant_id == tag.c.tenant_id),
        )
        await self._probe(
            session,
            select(link.c.id)
            .outerjoin(tag, tag.c.id == link.c.tag_id)
            .outerjoin(owner, owner.c.id == knowledge_id)
            .where(related, or_(tag.c.id.is_(None), tag.c.tenant_id != link.c.tenant_id)),
            "tag_parent_invalid",
        )
        linked_file = KnowledgeFile.__table__.alias("m2_linked_file")
        file_id = case((link.c.resource_type.in_((8, 9)), cast(link.c.resource_id, Integer)), else_=None)
        await self._probe(
            session,
            select(link.c.id)
            .outerjoin(linked_file, linked_file.c.id == file_id)
            .where(
                link.c.resource_type.in_((8, 9)),
                or_(linked_file.c.id.is_(None), linked_file.c.tenant_id != link.c.tenant_id),
            ),
            "tag_file_parent_invalid",
        )

    async def ainspect_file_ancestors(
        self, session: AsyncSession, *, file_ids: tuple[int, ...]
    ) -> tuple[FileAncestorFact, ...]:
        _scope(session)
        if type(file_ids) is not tuple or any(type(ident) is not int or ident <= 0 for ident in file_ids):
            _blocked("invalid_ancestor_ids")
        ids = tuple(dict.fromkeys(file_ids))
        if len(ids) > 500:
            _blocked("invalid_ancestor_ids")
        table = KnowledgeFile.__table__.alias("m2_exact_ancestor")
        facts = {}
        for offset in range(0, len(ids), 200):
            rows = await self._read(
                session,
                select(*(table.c[name] for name in ANCESTOR_COLUMNS)).where(table.c.id.in_(ids[offset : offset + 200])),
                global_facts=True,
            )
            facts.update((row["id"], FileAncestorFact(**dict(row), exists=True)) for row in rows)
        return tuple(
            facts[ident] if ident in facts else FileAncestorFact(ident, False, None, None, None, None, None, None)
            for ident in ids
        )
