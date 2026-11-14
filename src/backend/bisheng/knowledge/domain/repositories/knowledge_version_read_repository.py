"""Bounded native version facts, detached before any permission I/O."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy import case, func, or_
from sqlalchemy.orm import load_only
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class VersionReadBatch(Generic[T]):
    data: tuple[T, ...]
    has_more: bool
    next_after: int | None


@dataclass(frozen=True, slots=True)
class VersionAnchorFacts:
    space: Knowledge
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    file: KnowledgeFile
    version_count: int


@dataclass(frozen=True, slots=True)
class VersionFileFact:
    version: KnowledgeDocumentVersion
    file: KnowledgeFile


@dataclass(frozen=True, slots=True)
class VersionCandidateFact:
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    file: KnowledgeFile
    version_count: int


class KnowledgeVersionReadRepository:
    def __init__(self, session_factory: SessionFactory | None = None):
        self._sessions = session_factory or get_async_db_session

    @staticmethod
    def _id(value):
        if type(value) is not int or not 0 < value <= 9007199254740991:
            raise ValueError("version reads require positive safe IDs")

    @classmethod
    def _scope(cls, tenant_id, ident, after=None, limit=100):
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or tenant_id != get_current_tenant_id()
            or is_tenant_filter_bypassed()
        ):
            raise PermissionDeniedError()
        cls._id(ident)
        if after is not None:
            cls._id(after)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("version batches contain 1..100 rows")

    @staticmethod
    def _files_statement(ids, tenant_id):
        fields = (
            "id",
            "knowledge_id",
            "tenant_id",
            "file_type",
            "file_name",
            "file_encoding",
            "status",
            "user_id",
            "user_name",
            "create_time",
            "update_time",
            "file_level_path",
            "level",
            "simhash",
        )
        return (
            select(KnowledgeFile)
            .where(KnowledgeFile.id.in_(ids), KnowledgeFile.tenant_id == tenant_id)
            .options(load_only(*(getattr(KnowledgeFile, name) for name in fields), raiseload=True))
        )

    @staticmethod
    async def _stats(session, document_ids):
        version = KnowledgeDocumentVersion
        rows = (
            await session.execute(
                select(
                    version.document_id,
                    func.count(version.id),
                    func.count(func.distinct(version.knowledge_file_id)),
                    func.sum(case((version.is_primary.is_(True), 1), else_=0)),
                    func.max(case((version.is_primary.is_(True), version.id), else_=None)),
                    func.min(version.version_no),
                )
                .where(version.document_id.in_(document_ids))
                .group_by(version.document_id)
            )
        ).all()
        return {row[0]: row[1:] for row in rows}

    @staticmethod
    def _check_document(document, stats):
        if (
            document is None
            or stats is None
            or stats[0] < 1
            or stats[0] != stats[1]
            or stats[2] != 1
            or stats[3] != document.primary_version_id
            or stats[4] < 1
        ):
            raise SpaceFileNotFoundError()

    @staticmethod
    async def _check_links(session, document_ids, tenant_id, space_id):
        version = KnowledgeDocumentVersion.__table__
        file = KnowledgeFile.__table__
        other = version.alias("other_version_reference")
        duplicate = (
            select(other.c.id)
            .where(other.c.knowledge_file_id == version.c.knowledge_file_id, other.c.id != version.c.id)
            .exists()
        )
        # Only relationship scalars for the already-owned documents are inspected.
        invalid = (
            select(version.c.id)
            .select_from(version.outerjoin(file, file.c.id == version.c.knowledge_file_id))
            .where(
                version.c.document_id.in_(document_ids),
                or_(
                    file.c.id.is_(None),
                    file.c.tenant_id.is_(None),
                    file.c.tenant_id != tenant_id,
                    file.c.knowledge_id != space_id,
                    file.c.file_type != FileType.FILE.value,
                    duplicate,
                ),
            )
            .limit(1)
        )
        if (await session.execute(invalid)).first() is not None:
            raise SpaceFileNotFoundError()

    @staticmethod
    async def _file_facts(session, versions, tenant_id, space_id):
        if not versions:
            return {}
        ids = [version.knowledge_file_id for version in versions]
        files = (await session.execute(KnowledgeVersionReadRepository._files_statement(ids, tenant_id))).scalars().all()
        by_id = {row.id: row for row in files}
        version = KnowledgeDocumentVersion
        counts = dict(
            (
                await session.execute(
                    select(version.knowledge_file_id, func.count(version.id))
                    .where(version.knowledge_file_id.in_(ids))
                    .group_by(version.knowledge_file_id)
                )
            ).all()
        )
        if any(
            ident not in by_id
            or counts.get(ident) != 1
            or by_id[ident].knowledge_id != space_id
            or by_id[ident].tenant_id != tenant_id
            or by_id[ident].file_type != FileType.FILE.value
            for ident in ids
        ):
            raise SpaceFileNotFoundError()
        return by_id

    async def aget_anchor(self, *, tenant_id: int, file_id: int) -> VersionAnchorFacts | None:
        self._scope(tenant_id, file_id)
        with strict_tenant_filter():
            async with self._sessions() as session:
                with session.no_autoflush:
                    file = (await session.execute(self._files_statement([file_id], tenant_id))).scalars().first()
                    if file is None:
                        return None
                    if file.file_type != FileType.FILE.value:
                        raise SpaceFileNotFoundError()
                    versions = (
                        (
                            await session.execute(
                                select(KnowledgeDocumentVersion)
                                .where(KnowledgeDocumentVersion.knowledge_file_id == file_id)
                                .limit(2)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if len(versions) != 1:
                        raise SpaceFileNotFoundError()
                    version = versions[0]
                    document = (
                        (
                            await session.execute(
                                select(KnowledgeDocument).where(KnowledgeDocument.id == version.document_id)
                            )
                        )
                        .scalars()
                        .first()
                    )
                    space = (
                        (
                            await session.execute(
                                select(Knowledge)
                                .where(
                                    Knowledge.id == file.knowledge_id,
                                    Knowledge.tenant_id == tenant_id,
                                    Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                                )
                                .options(
                                    load_only(
                                        Knowledge.id,
                                        Knowledge.type,
                                        Knowledge.tenant_id,
                                        Knowledge.user_id,
                                        Knowledge.state,
                                    )
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if document is None or space is None or document.knowledge_id != space.id:
                        raise SpaceFileNotFoundError()
                    stats = (await self._stats(session, [document.id])).get(document.id)
                    self._check_document(document, stats)
                    await self._check_links(session, [document.id], tenant_id, space.id)
                    return VersionAnchorFacts(space, document, version, file, int(stats[0]))

    async def alist_chain(
        self, *, tenant_id: int, document_id: int, after_version_id: int | None = None, limit: int = 100
    ) -> VersionReadBatch[VersionFileFact]:
        self._scope(tenant_id, document_id, after_version_id, limit)
        with strict_tenant_filter():
            async with self._sessions() as session:
                with session.no_autoflush:
                    document = (
                        (
                            await session.execute(
                                select(KnowledgeDocument)
                                .join(Knowledge, Knowledge.id == KnowledgeDocument.knowledge_id)
                                .where(
                                    KnowledgeDocument.id == document_id,
                                    Knowledge.tenant_id == tenant_id,
                                    Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if document is None:
                        raise SpaceFileNotFoundError()
                    version = KnowledgeDocumentVersion
                    statement = select(version).where(version.document_id == document_id)
                    if after_version_id is not None:
                        statement = statement.where(version.id > after_version_id)
                    rows = list(
                        (await session.execute(statement.order_by(version.id).limit(limit + 1))).scalars().all()
                    )
                    more, rows = len(rows) > limit, rows[:limit]
                    files = await self._file_facts(session, rows, tenant_id, document.knowledge_id)
                    return VersionReadBatch(
                        tuple(VersionFileFact(row, files[row.knowledge_file_id]) for row in rows),
                        more,
                        rows[-1].id if more else None,
                    )

    async def alist_candidates(
        self, *, tenant_id: int, space_id: int, after_document_id: int | None = None, limit: int = 100
    ) -> VersionReadBatch[VersionCandidateFact]:
        self._scope(tenant_id, space_id, after_document_id, limit)
        with strict_tenant_filter():
            async with self._sessions() as session:
                with session.no_autoflush:
                    exists = (
                        await session.execute(
                            select(Knowledge.id).where(
                                Knowledge.id == space_id,
                                Knowledge.tenant_id == tenant_id,
                                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            )
                        )
                    ).scalar_one_or_none()
                    if exists is None:
                        raise SpaceFileNotFoundError()
                    statement = (
                        select(KnowledgeDocument, KnowledgeDocumentVersion)
                        .outerjoin(
                            KnowledgeDocumentVersion,
                            KnowledgeDocumentVersion.id == KnowledgeDocument.primary_version_id,
                        )
                        .where(KnowledgeDocument.knowledge_id == space_id)
                    )
                    if after_document_id is not None:
                        statement = statement.where(KnowledgeDocument.id > after_document_id)
                    pairs = list(
                        (await session.execute(statement.order_by(KnowledgeDocument.id).limit(limit + 1))).all()
                    )
                    more, pairs = len(pairs) > limit, pairs[:limit]
                    documents = [pair[0] for pair in pairs]
                    if not documents:
                        return VersionReadBatch((), False, None)
                    stats = await self._stats(session, [row.id for row in documents])
                    versions = [pair[1] for pair in pairs if pair[1] is not None]
                    by_id = {row.id: row for row in versions}
                    for document in documents:
                        self._check_document(document, stats.get(document.id))
                        primary = by_id.get(document.primary_version_id)
                        if primary is None or primary.document_id != document.id or not primary.is_primary:
                            raise SpaceFileNotFoundError()
                    await self._check_links(session, [row.id for row in documents], tenant_id, space_id)
                    files = await self._file_facts(session, versions, tenant_id, space_id)
                    return VersionReadBatch(
                        tuple(
                            VersionCandidateFact(
                                row,
                                by_id[row.primary_version_id],
                                files[by_id[row.primary_version_id].knowledge_file_id],
                                int(stats[row.id][0]),
                            )
                            for row in documents
                        ),
                        more,
                        documents[-1].id if more else None,
                    )
