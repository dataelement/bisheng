"""Space-scoped, read-only ledger queries, independent of active routing and workers."""

from sqlalchemy import func, select

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op


class ProviderDiagnosticsRepository:
    async def has_space(self, session, tenant_id, space_id):
        # Check the physical owner even where shared/root rows are normally visible.
        stmt = select(Knowledge.id).where(
            Knowledge.tenant_id == tenant_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value, Knowledge.id == space_id
        )
        return await session.scalar(stmt) is not None

    async def list_rows(self, session, tenant_id, space_id, page, page_size):
        scope = (Op.tenant_id == tenant_id, Op.space_id == space_id)
        count = await session.scalar(select(func.count()).select_from(Op).where(*scope))
        # Select only frozen target and diagnostic fields, never the request key,
        # actor, remote task handle, lease token, or provider configuration.
        stmt = (
            select(
                Op.operation_id,
                Op.kind,
                Op.space_id,
                Op.provider_instance_id,
                Op.remote_scope_id,
                Op.remote_kb_id,
                Op.generation,
                Op.phase,
                Op.state,
                Op.last_error_code,
                Op.attempt,
                Op.create_time,
                Op.capability_revision,
            )
            .where(*scope)
            .order_by(Op.create_time.desc(), Op.operation_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await session.execute(stmt)).all()
        versioned = [r.operation_id for r in rows if r.kind in {"upload", "provider_transfer"}]
        # Fetch CLOB/JSON as a plain column (no dialect-specific JSON extraction
        # or CASE on LOBs). Never load manifests from settings/creation records.
        manifests = {}
        if versioned:
            targets = await session.execute(
                select(Op.operation_id, Op.target_manifest).where(
                    *scope, Op.operation_id.in_(versioned), Op.kind.in_(("upload", "provider_transfer"))
                )
            )
            manifests = dict(targets.all())
        return count, rows, manifests
