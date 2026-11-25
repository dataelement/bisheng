"""Read-only facts for provider delivery and space-level counters."""

from dataclasses import dataclass, field

from sqlalchemy import and_, exists, func, or_, select

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)
from bisheng.knowledge.infrastructure.providers.registry import PortContext

READY_INSTANCE = "ready"
FOLDER_MAPPING = "folder"


@dataclass(frozen=True, slots=True)
class ReadFact:
    context: PortContext = field(repr=False)
    resource_id: int
    kind: str
    name: str
    parent_id: int | None
    version_id: int | None
    epoch: int
    remote_id: str = field(repr=False)
    status: int | None = None
    file_size: int | None = None
    create_time: object = None
    update_time: object = None


class SqlReadFacts:
    """Select only local metadata. Bind one live instance/library; never route on a client ID."""

    @staticmethod
    def _query(*, tenant_id, space_id, resource_id=None, root_card=False):
        if tenant_id != get_current_tenant_id() or is_tenant_filter_bypassed():
            raise PermissionDeniedError()
        other = Version.__table__.alias("other_version")
        file_chain = and_(
            Mapping.resource_type == "file",
            File.file_type == FileType.FILE.value,
            Doc.id == Mapping.logical_document_id,
            Doc.knowledge_id == space_id,
            Version.id == Mapping.version_id,
            Version.document_id == Doc.id,
            Version.knowledge_file_id == File.id,
            Version.version_no > 0,
            ~exists(select(other.c.id).where(other.c.knowledge_file_id == File.id, other.c.id != Version.id)).correlate(
                File, Version
            ),
        )
        if resource_id is None:  # Directory listings show current primary versions only.
            file_chain = and_(file_chain, Version.is_primary.is_(True), Doc.primary_version_id == Version.id)
        q = (
            select(
                File.id,
                File.file_name,
                File.file_level_path,
                Mapping.resource_type,
                Mapping.version_id,
                Mapping.operation_epoch,
                Mapping.remote_object_id,
                Binding.provider_key,
                Generation.provider_instance_id,
                Generation.generation,
                Generation.remote_scope_id,
                Generation.remote_kb_id,
                File.status, File.file_size, File.create_time, File.update_time,
            )
            .select_from(Binding)
            .join(Knowledge, and_(Knowledge.id == Binding.space_id, Knowledge.tenant_id == Binding.tenant_id))
            .join(
                Generation,
                and_(
                    Generation.tenant_id == Binding.tenant_id,
                    Generation.space_id == Binding.space_id,
                    Generation.generation == Binding.active_generation,
                ),
            )
            .join(
                Instance,
                and_(
                    Instance.id == Generation.provider_instance_id,
                    Instance.tenant_id == Binding.tenant_id,
                    Instance.provider_key == Binding.provider_key,
                    Instance.remote_scope_id == Generation.remote_scope_id,
                ),
            )
            .join(
                Mapping,
                and_(
                    Mapping.tenant_id == Binding.tenant_id,
                    Mapping.space_id == Binding.space_id,
                    Mapping.generation == Generation.generation,
                ),
            )
            .join(
                File,
                and_(
                    File.id == Mapping.local_resource_id,
                    File.tenant_id == Mapping.tenant_id,
                    File.knowledge_id == Mapping.space_id,
                ),
            )
            .outerjoin(Doc, Doc.id == Mapping.logical_document_id)
            .outerjoin(Version, Version.id == Mapping.version_id)
            .where(
                Binding.tenant_id == tenant_id,
                Binding.space_id == space_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Binding.state == "ready",
                Binding.provider_key != "native",
                Instance.state == READY_INSTANCE,
                Mapping.lifecycle_state.in_(("pending", "received", "active"))
                if root_card
                else Mapping.lifecycle_state == "active",
                Mapping.tombstoned_at.is_(None),
                or_(and_(Mapping.resource_type == FOLDER_MAPPING, File.file_type == FileType.DIR.value), file_chain),
            )
        )
        if resource_id is not None:
            q = q.where(File.id == resource_id)
        return q

    async def count_files(self, *, tenant_id, space_id, root_card):
        """Projection only: never return file IDs or names through card/detail metadata."""
        q = self._query(tenant_id=tenant_id, space_id=space_id, root_card=root_card).where(
            Mapping.resource_type == "file"
        )
        if root_card:
            q = q.where(or_(File.file_level_path.is_(None), File.file_level_path == ""))
        else:
            q = q.where(Mapping.ready_revision.is_not(None))
        async with get_async_db_session() as session:
            return (await session.execute(q.with_only_columns(func.count()))).scalar_one()

    async def load(self, *, tenant_id, space_id, resource_id=None):
        q = self._query(tenant_id=tenant_id, space_id=space_id, resource_id=resource_id)
        async with get_async_db_session() as session:
            rows = (await session.execute(q)).all()
        result = []
        for local, name, path, kind, version, epoch, remote, provider, instance, generation, scope, kb, status, size, created, updated in rows:
            parents = tuple(p for p in (path or "").split("/") if p)
            if any(not p.isascii() or not p.isdecimal() or int(p) <= 0 for p in parents):
                continue
            ctx = PortContext(tenant_id, space_id, provider, "read", instance, generation, scope, kb)
            result.append(
                ReadFact(
                    ctx,
                    local,
                    "folder" if kind == "folder" else "knowledge_file",
                    name,
                    int(parents[-1]) if parents else None,
                    version,
                    epoch,
                    remote, status, size, created, updated,
                )
            )
        return result
