"""Capture and recheck a single received version; never perform remote I/O here."""

from dataclasses import dataclass

from sqlalchemy import select, update

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as B
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as G
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as I
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as M
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op
from bisheng.permission.domain.models import PermissionProjectionOperation as Projection
from bisheng.permission.domain.models import ResourcePermissionMode as Mode


@dataclass(frozen=True, slots=True)
class ProcessingTarget:
    tenant_id: int
    space_id: int
    instance_id: int
    remote_scope_id: str
    remote_kb_id: str
    generation: int
    operation_id: str
    epoch: int
    file_id: int
    document_id: int
    version_id: int
    remote_id: str
    checksum: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    target: ProcessingTarget
    mapping_id: int
    mapping_revision: int
    binding_revision: int
    generation_revision: int
    permission_version: int
    projection_id: int


class ProcessingReadinessRepository:
    async def alist_pending(self, db, *, tenant_id, limit):
        """Uploads that were accepted but still await their processing proof.

        Only the ledger and the local mapping are read here; the provider is
        never queried from this bounded scan.
        """
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or tenant != tenant_id or is_tenant_filter_bypassed():
            return ()
        if type(limit) is not int or not 1 <= limit <= 500:
            return ()
        query = (
            select(Op.operation_id, Op.actor_user_id)
            .join(
                M,
                (M.tenant_id == Op.tenant_id)
                & (M.space_id == Op.space_id)
                & (M.generation == Op.generation)
                & (M.operation_epoch == Op.operation_epoch),
            )
            .where(
                Op.tenant_id == tenant,
                Op.kind == "upload",
                Op.state == "succeeded",
                M.tenant_id == tenant,
                M.resource_type == "file",
                M.lifecycle_state == "received",
                M.tombstoned_at.is_(None),
                M.ready_revision.is_(None),
            )
            .order_by(Op.create_time, Op.operation_id)
            .limit(limit)
        )
        return tuple((await db.execute(query)).all())

    async def snapshot(self, db, operation_id, *, locked=False):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            return None

        def reading(query):
            return query.with_for_update() if locked else query

        op = await db.scalar(
            reading(
                select(Op).where(
                    Op.tenant_id == tenant,
                    Op.operation_id == operation_id,
                    Op.kind == "upload",
                    Op.state == "succeeded",
                )
            )
        )
        if not op or len(op.target_manifest) != 1:
            return None
        (item,) = op.target_manifest
        file, version, doc = item["file_id"], item["version_id"], item["document_id"]
        # A positive row requires the still-primary local chain and current
        # finalized, target-specific F048 create projection, not just an ACK.
        parent = item["parent_id"]
        query = (
            select(M, B, G, Mode.version, Projection.id)
            .select_from(M)
            .join(B, (B.tenant_id == M.tenant_id) & (B.space_id == M.space_id) & (B.active_generation == M.generation))
            .join(G, (G.tenant_id == M.tenant_id) & (G.space_id == M.space_id) & (G.generation == M.generation))
            .join(I, (I.id == G.provider_instance_id) & (I.tenant_id == M.tenant_id))
            .join(
                File,
                (File.id == M.local_resource_id) & (File.tenant_id == M.tenant_id) & (File.knowledge_id == M.space_id),
            )
            .join(Version, (Version.id == M.version_id) & (Version.knowledge_file_id == File.id))
            .join(
                Doc,
                (Doc.id == M.logical_document_id)
                & (Doc.primary_version_id == Version.id)
                & (Doc.id == Version.document_id)
                & (Doc.knowledge_id == M.space_id),
            )
            .join(
                Mode,
                (Mode.tenant_id == M.tenant_id)
                & (Mode.resource_type == "knowledge_file")
                & (Mode.resource_id == str(file)),
            )
            .join(Projection, (Projection.id == Mode.operation_id) & (Projection.tenant_id == tenant))
            .where(
                M.tenant_id == tenant,
                M.space_id == op.space_id,
                M.generation == op.generation,
                M.resource_type == "file",
                M.local_resource_id == file,
                M.version_id == version,
                M.logical_document_id == doc,
                M.operation_epoch == op.operation_epoch,
                M.lifecycle_state == "received",
                M.tombstoned_at.is_(None),
                M.ready_revision.is_(None),
                B.state == "ready",
                B.pending_write_operation_id.is_(None),
                I.state == "ready",
                I.provider_key == B.provider_key,
                I.id == op.provider_instance_id,
                I.remote_scope_id == op.remote_scope_id,
                I.capability_revision == op.capability_revision,
                G.remote_scope_id == op.remote_scope_id,
                G.remote_kb_id == op.remote_kb_id,
                File.file_type == FileType.FILE.value,
                Version.is_primary.is_(True),
                Mode.projection_state == "CURRENT",
                Mode.parent_type == ("folder" if parent is not None else "knowledge_space"),
                Mode.parent_id == str(parent or op.space_id),
                Projection.scope_key == f"knowledge_file:{file}",
                Projection.status == "FINALIZED",
                Projection.target_version == Mode.version,
            )
        )
        row = (await db.execute(reading(query))).one_or_none()
        if not row:
            return None
        m, b, g, permission, projection = row
        key = ProcessingTarget(
            tenant,
            op.space_id,
            op.provider_instance_id,
            op.remote_scope_id,
            op.remote_kb_id,
            op.generation,
            op.operation_id,
            op.operation_epoch,
            file,
            doc,
            version,
            m.remote_object_id,
            item["sha256"],
            item["byte_count"],
        )
        return Snapshot(key, m.id, m.revision, b.revision, g.revision, permission, projection)

    async def activate(self, db, snapshot, ready_revision):
        key = snapshot.target
        if await self.snapshot(db, key.operation_id, locked=True) != snapshot:
            return False
        changed = await db.execute(
            update(M)
            .where(
                M.tenant_id == key.tenant_id,
                M.id == snapshot.mapping_id,
                M.revision == snapshot.mapping_revision,
                M.lifecycle_state == "received",
                M.operation_epoch == key.epoch,
                M.tombstoned_at.is_(None),
            )
            .values(lifecycle_state="active", ready_revision=ready_revision, revision=M.revision + 1)
        )
        if changed.rowcount != 1:
            return False
        # Directory listing reads knowledgefile.status; keep it aligned with active readiness.
        await db.execute(
            update(File)
            .where(
                File.id == key.file_id,
                File.tenant_id == key.tenant_id,
                File.knowledge_id == key.space_id,
                File.file_type == FileType.FILE.value,
                # A resend can succeed after a rejected remote attempt, so only
                # an already-successful row is left untouched.
                File.status != KnowledgeFileStatus.SUCCESS.value,
            )
            .values(status=KnowledgeFileStatus.SUCCESS.value)
        )
        generation = await db.scalar(
            select(G)
            .where(G.tenant_id == key.tenant_id, G.space_id == key.space_id, G.generation == key.generation)
            .with_for_update()
        )
        if ready_revision > generation.content_revision:
            generation.content_revision = ready_revision
            generation.revision += 1
        return True

    async def mark_rejected(self, db, snapshot):
        """The provider itself reported this upload as failed or cancelled.

        The mapping stays ``received`` so a client resend still owns its row;
        only the visible file state becomes terminal, which also stops this
        file from being re-probed on every scan.
        """
        key = snapshot.target
        if await self.snapshot(db, key.operation_id, locked=True) != snapshot:
            return False
        changed = await db.execute(
            update(File)
            .where(
                File.id == key.file_id,
                File.tenant_id == key.tenant_id,
                File.knowledge_id == key.space_id,
                File.file_type == FileType.FILE.value,
                File.status.in_(
                    (
                        KnowledgeFileStatus.WAITING.value,
                        KnowledgeFileStatus.PROCESSING.value,
                    )
                ),
            )
            .values(status=KnowledgeFileStatus.FAILED.value)
        )
        return changed.rowcount == 1
