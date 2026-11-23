"""Tenant-scoped snapshots and ordinary replacement of existing hint tables."""

from sqlalchemy import delete, select

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.application.contracts import SourceType, TargetType, reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


class ReferenceSyncRepository:
    @staticmethod
    def context(tenant_id):
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or get_current_tenant_id() != tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise ValueError("reference sync requires an explicit tenant scope")

    @staticmethod
    async def rows(session, statement):
        return tuple((await session.execute(statement)).mappings())

    async def aload_root(self, session, tenant_id, kind, source_id):
        self.context(tenant_id)
        kind = SourceType(kind)
        if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
            return ()
        if kind == SourceType.WORKFLOW_VERSION:
            root = (
                await session.execute(
                    select(Flow.id).where(
                        Flow.id == source_id, Flow.tenant_id == tenant_id, Flow.is_delete == 0, Flow.flow_type == 10
                    )
                )
            ).first()
            if root is None:
                return ()
            rows = await self.rows(
                session,
                select(FlowVersion.__table__).where(
                    FlowVersion.tenant_id == tenant_id, FlowVersion.flow_id == source_id, FlowVersion.is_delete == 0
                ),
            )
            return tuple({"version": str(row["id"]), "data": row["data"]} for row in rows)
        if kind == SourceType.ASSISTANT:
            rows = await self.rows(
                session,
                select(Assistant.__table__).where(
                    Assistant.tenant_id == tenant_id, Assistant.id == source_id, Assistant.is_delete == 0
                ),
            )
            if not rows:
                return ()
            links = await self.rows(
                session,
                select(AssistantLink.knowledge_id).where(
                    AssistantLink.tenant_id == tenant_id, AssistantLink.assistant_id == source_id
                ),
            )
            return (
                {
                    "version": "current",
                    "model_name": rows[0]["model_name"],
                    "knowledge_ids": [row["knowledge_id"] for row in links if row["knowledge_id"]],
                },
            )
        if kind == SourceType.HOSTED_APP_VERSION:
            root = (
                await session.execute(
                    select(App.id).where(App.id == source_id, App.tenant_id == tenant_id, App.state != "deleted")
                )
            ).first()
            if root is None:
                return ()
            rows = await self.rows(session, select(AppVersion.__table__).where(AppVersion.app_id == source_id))
            return tuple(
                {"version": row["id"], "capabilities": row["capabilities"], "injections": row["injections"]}
                for row in rows
            )
        if kind == SourceType.CHANNEL_SYNC:
            root = (
                await session.execute(select(Channel.id).where(Channel.id == source_id, Channel.tenant_id == tenant_id))
            ).first()
            if root is None:
                return ()
            rows = await self.rows(
                session, select(ChannelKnowledgeSync.__table__).where(ChannelKnowledgeSync.channel_id == source_id)
            )
            return ({"version": "current", "rows": tuple(dict(row) for row in rows)},)
        if kind == SourceType.KNOWLEDGE:
            rows = await self.rows(
                session,
                select(Knowledge.model, Knowledge.model_transition).where(
                    Knowledge.id == int(source_id), Knowledge.tenant_id == tenant_id
                ),
            )
            return tuple({"version": "current", **row} for row in rows)
        rows = await self.rows(
            session,
            select(TenantSystemModelConfig.value).where(
                TenantSystemModelConfig.tenant_id == tenant_id, TenantSystemModelConfig.key == source_id
            ),
        )
        return tuple({"version": "current", "value": row["value"]} for row in rows)

    @staticmethod
    def root_filter(model, tenant_id, kind, source_id):
        return (model.tenant_id == tenant_id, model.source_type == kind.value, model.source_id == source_id)

    async def aold(self, session, tenant_id, kind, source_id):
        self.context(tenant_id)
        rows = tuple(
            (
                await session.execute(
                    select(BusinessResourceReference).where(
                        *self.root_filter(BusinessResourceReference, tenant_id, kind, source_id)
                    )
                )
            ).scalars()
        )
        sets = tuple(
            (
                await session.execute(
                    select(BusinessReferenceSet).where(
                        *self.root_filter(BusinessReferenceSet, tenant_id, kind, source_id),
                        BusinessReferenceSet.record_kind == "source",
                    )
                )
            ).scalars()
        )
        return rows, {row.source_version: row.source_revision for row in sets}

    async def atargets(self, session, references):
        found = {}
        for kind, model in (
            (TargetType.MODEL, LLMModel),
            (TargetType.KNOWLEDGE_SPACE, Knowledge),
            (TargetType.KNOWLEDGE_FILE, KnowledgeFile),
        ):
            ids = sorted({int(ref.target.target_id) for ref in references if ref.target.target_type == kind})
            for offset in range(0, len(ids), 200):
                fields = [model.id, model.tenant_id]
                if kind == TargetType.KNOWLEDGE_FILE:
                    fields.append(model.knowledge_id)
                # Owner lookup only: exact configured IDs, never a visibility grant.
                with bypass_tenant_filter():
                    rows = await self.rows(session, select(*fields).where(model.id.in_(ids[offset : offset + 200])))
                for row in rows:
                    found[(kind.value, str(row["id"]))] = (
                        row["tenant_id"],
                        str(row["knowledge_id"])
                        if kind == TargetType.KNOWLEDGE_FILE
                        else str(row["id"])
                        if kind == TargetType.KNOWLEDGE_SPACE
                        else None,
                    )
        return found

    async def areplace(self, session, tenant_id, kind, source_id, snapshots, old, revisions, targets):
        self.context(tenant_id)
        previous = {(row.source_version, row.slot_key, row.target_type, row.target_id): row for row in old}
        prepared_rows, prepared_sets = [], []
        skipped = 0
        for version, references, extractor, complete in snapshots:
            revision = revisions.get(version, 0) + 1
            persisted = []
            for ref in references:
                old_row = previous.get((version, ref.slot_key, ref.target.target_type.value, ref.target.target_id))
                ownership = targets.get((ref.target.target_type.value, ref.target.target_id))
                legacy = {}
                if ownership is None:
                    if old_row is None or (old_row.target_tenant_id is None and not old_row.legacy_invalid_reason):
                        complete = False
                        skipped += 1
                        continue
                    ownership = (old_row.target_tenant_id, old_row.target_space_id)
                    legacy = {
                        key: getattr(old_row, key)
                        for key in ("legacy_invalid_reason", "legacy_run_id", "legacy_evidence_key")
                    }
                prepared_rows.append(
                    BusinessResourceReference(
                        tenant_id=tenant_id,
                        source_type=kind.value,
                        source_id=source_id,
                        source_version=version,
                        slot_key=ref.slot_key,
                        target_type=ref.target.target_type.value,
                        target_id=ref.target.target_id,
                        target_tenant_id=ownership[0],
                        target_space_id=ownership[1],
                        source_revision=revision,
                        **legacy,
                    )
                )
                persisted.append(ref)
            prepared_sets.append(
                BusinessReferenceSet(
                    tenant_id=tenant_id,
                    source_type=kind.value,
                    source_id=source_id,
                    source_version=version,
                    record_kind="source",
                    source_revision=revision,
                    extractor_version=extractor,
                    digest=reference_set_digest(tuple(persisted)),
                    effective=True,
                    ready=complete,
                )
            )
        # Ordinary task-local transaction; no business lock, ledger or fence.
        await session.execute(
            delete(BusinessResourceReference).where(
                *self.root_filter(BusinessResourceReference, tenant_id, kind, source_id)
            )
        )
        await session.execute(
            delete(BusinessReferenceSet).where(
                *self.root_filter(BusinessReferenceSet, tenant_id, kind, source_id),
                BusinessReferenceSet.record_kind == "source",
            )
        )
        session.add_all([*prepared_sets, *prepared_rows])
        await session.flush()
        return {"sources": len(prepared_sets), "references": len(prepared_rows), "skipped": skipped}
