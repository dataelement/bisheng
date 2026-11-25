"""Frozen control-plane inputs for an explicitly selected provider batch of files."""

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
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
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderTagRef as Tag,
)


async def snapshot(db, space, command, *, lock):
    tenant = get_current_tenant_id()

    async def query(stmt):
        return await db.execute(stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt)

    stmt = (
        select(Binding, Generation, Instance)
        .select_from(Binding)
        .join(
            Knowledge,
            (Knowledge.id == Binding.space_id)
            & (Knowledge.tenant_id == tenant)
            & (Knowledge.type == KnowledgeTypeEnum.SPACE.value),
        )
        .join(
            Generation,
            (Generation.tenant_id == tenant)
            & (Generation.space_id == space)
            & (Generation.generation == Binding.active_generation),
        )
        .join(
            Instance,
            (Instance.tenant_id == tenant)
            & (Instance.id == Generation.provider_instance_id)
            & (Instance.provider_key == Binding.provider_key)
            & (Instance.remote_scope_id == Generation.remote_scope_id),
        )
        .where(
            Binding.space_id == space,
            Binding.tenant_id == tenant,
            Binding.provider_key != "native",
            Binding.state == "ready",
            Generation.state == "ready",
            Instance.state == "ready",
            Binding.pending_write_operation_id.is_(None),
        )
    )
    row = (await query(stmt)).one_or_none()
    if not row:
        raise KnowledgeOperationPlanChangedError(reason="provider_batch_unavailable")
    b, g, i = row
    ids = [s.id for s in command.items if s.type == "file"]
    rows = await query(
        select(Mapping, File.status)
        .select_from(Mapping)
        .join(
            File,
            (File.id == Mapping.local_resource_id)
            & (File.tenant_id == tenant)
            & (File.knowledge_id == space)
            & (File.file_type == FileType.FILE.value),
        )
        .join(
            Document,
            (Document.id == Mapping.logical_document_id)
            & (Document.knowledge_id == space)
            & (Document.primary_version_id == Mapping.version_id),
        )
        .join(
            Version,
            (Version.id == Mapping.version_id)
            & (Version.document_id == Document.id)
            & (Version.knowledge_file_id == File.id)
            & Version.is_primary.is_(True),
        )
        .where(
            Mapping.tenant_id == tenant,
            Mapping.space_id == space,
            Mapping.generation == g.generation,
            Mapping.local_resource_id.in_(ids),
            Mapping.resource_type == "file",
            Mapping.tombstoned_at.is_(None),
        )
        .order_by(Mapping.local_resource_id)
    )
    tags = (
        (
            await query(
                select(Tag)
                .where(
                    Tag.tenant_id == tenant,
                    Tag.space_id == space,
                    Tag.generation == g.generation,
                    Tag.state == "active",
                    Tag.tag_ref_id.in_(command.tag_ids),
                )
                .order_by(Tag.tag_ref_id)
            )
        )
        .scalars()
        .all()
        if command.tag_ids
        else []
    )
    if len(tags) != len(command.tag_ids) or command.new_tag_names:
        raise KnowledgeOperationPlanChangedError(reason="provider_batch_existing_tag_refs_required")
    return {
        "binding": {
            "tenant_id": tenant,
            "space_id": space,
            "provider_key": b.provider_key,
            "generation": g.generation,
            "instance_id": i.id,
            "remote_scope_id": g.remote_scope_id,
            "remote_kb_id": g.remote_kb_id,
            "state": b.state,
        },
        "revision": [b.revision, g.revision, g.content_revision, i.revision, i.capability_revision],
        "tags": [[t.tag_ref_id, t.revision, t.remote_tag_id] for t in tags],
        "files": [
            {
                "file_id": m.local_resource_id,
                "document_id": m.logical_document_id,
                "version_id": m.version_id,
                "revision": m.revision,
                "epoch": m.operation_epoch,
                "remote_id": m.remote_object_id,
                "lifecycle": m.lifecycle_state,
                "status": status,
            }
            for m, status in rows
        ],
    }
