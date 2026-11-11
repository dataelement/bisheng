"""Bounded native candidates for the original flat document-file protocol."""

from sqlalchemy import String, cast
from sqlmodel import and_, or_, select

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File


class LegacyFileReadRepository:
    def __init__(self, session_factory=None):
        self.sessions = session_factory or get_async_db_session

    async def acandidates(
        self, *, space_id, keyword=None, status=None, file_ids=None, after=None, limit=100, order="id"
    ):
        if type(get_current_tenant_id()) is not int or get_current_tenant_id() <= 0 or is_tenant_filter_bypassed():
            raise PermissionInvalidResourceError()
        if type(limit) is not int or not 1 <= limit <= 100 or order not in {"id", "update"}:
            raise ValueError("invalid legacy file candidate window")
        root = select(Knowledge.id).where(Knowledge.id == File.knowledge_id, Knowledge.type == 3).exists()
        registered = select(Version.id).where(Version.knowledge_file_id == File.id).exists()
        primary = (
            select(Version.id)
            .join(Document, Document.id == Version.document_id)
            .where(
                Version.knowledge_file_id == File.id,
                Version.is_primary == True,  # noqa: E712
                Document.primary_version_id == Version.id,
                Document.knowledge_id == File.knowledge_id,
            )
            .exists()
        )
        statement = select(File).where(
            File.knowledge_id == space_id, File.file_type == FileType.FILE.value, root, or_(~registered, primary)
        )
        if status:
            statement = statement.where(File.status.in_(status))
        if file_ids:
            statement = statement.where(File.id.in_(file_ids))
        if keyword:
            tagged = (
                select(TagLink.id)
                .join(Tag, Tag.id == TagLink.tag_id)
                .where(
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE,
                    TagLink.resource_id == cast(File.id, String),
                    TagLink.tenant_id == File.tenant_id,
                    Tag.tenant_id == File.tenant_id,
                    Tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                    Tag.business_id == str(space_id),
                    Tag.name.like(f"%{keyword}%"),
                )
                .exists()
            )
            statement = statement.where(or_(File.file_name.like(f"%{keyword}%"), tagged))
        if order == "id":
            if after is not None:
                statement = statement.where(File.id < after)
            statement = statement.order_by(File.id.desc())
        else:
            if after is not None:
                stamp, ident = after
                statement = statement.where(
                    or_(File.update_time < stamp, and_(File.update_time == stamp, File.id > ident))
                )
            statement = statement.order_by(File.update_time.desc(), File.id.asc())
        with strict_tenant_filter():
            async with self.sessions() as session:
                return list((await session.exec(statement.limit(limit))).all())
