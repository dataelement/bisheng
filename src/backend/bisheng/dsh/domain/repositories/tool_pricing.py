"""Repository for unified per-tenant tool pricing configuration."""

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.dsh.domain.models.tool_pricing import DshToolPricing
from bisheng.dsh.domain.models.unified_policy import UnifiedPolicyAudit
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.schemas.pricing import format_micro
from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput


class ToolPricingRepository:
    """Persists per-tenant tool prices with optimistic locking and audit trail."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def serialize(row: DshToolPricing | None, *, tool_id: int) -> dict:
        if row is None:
            return {
                "tool_id": tool_id,
                "pricing_mode": "CREDITS",
                "currency": None,
                "price": "0",
                "price_micro": 0,
                "call_count": 1,
                "version": 0,
            }
        return {
            "tool_id": row.tool_id,
            "pricing_mode": row.pricing_mode,
            "currency": row.currency,
            "price": format_micro(row.price_micro),
            "price_micro": row.price_micro,
            "call_count": row.call_count,
            "version": row.version,
        }

    def list_all(self) -> list[DshToolPricing]:
        require_tenant()
        with strict_tenant_filter():
            return list(self.session.exec(select(DshToolPricing)).all())

    def get_by_tool(self, tool_id: int, *, lock: bool = False) -> DshToolPricing | None:
        require_tenant()
        stmt = select(DshToolPricing).where(DshToolPricing.tool_id == tool_id)
        if lock:
            stmt = stmt.with_for_update()
        with strict_tenant_filter():
            return self.session.exec(stmt).one_or_none()

    def save(self, *, tool_id: int, actor: int, value: ToolPricingInput) -> dict:
        if tool_id < 1:
            raise ValueError("tool_id must be positive")
        tenant = require_tenant()
        DshSubjectPolicyRepository(self.session)._lock_tenant()
        row = self.get_by_tool(tool_id, lock=True)
        before = self.serialize(row, tool_id=tool_id)
        if value.version != before["version"]:
            raise DshOperationConflictError()
        if row is None:
            row = DshToolPricing(
                tenant_id=tenant,
                tool_id=tool_id,
                updated_by=actor,
            )
        row.pricing_mode = value.pricing_mode
        row.currency = value.currency
        row.price_micro = value.price_micro
        row.call_count = value.call_count
        row.version = value.version + 1
        row.updated_by = actor
        self.session.add(row)
        after = self.serialize(row, tool_id=tool_id)
        self.session.add(
            UnifiedPolicyAudit(
                tenant_id=tenant,
                actor_user_id=actor,
                resource=f"tool_pricing:{tool_id}",
                before_values=before,
                after_values=after,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            raise DshOperationConflictError() from error
        return after

    @staticmethod
    def delete_for_tool_ids_sync(session: Session, *, tenant_id: int | None, tool_ids: list[int]) -> None:
        if not tool_ids:
            return
        with bypass_tenant_filter():
            stmt = delete(DshToolPricing).where(DshToolPricing.tool_id.in_(tool_ids))
            if tenant_id is not None:
                stmt = stmt.where(DshToolPricing.tenant_id == tenant_id)
            session.exec(stmt)

    @staticmethod
    async def adelete_for_tool_ids(session, *, tenant_id: int | None, tool_ids: list[int]) -> None:
        if not tool_ids:
            return
        with bypass_tenant_filter():
            stmt = delete(DshToolPricing).where(DshToolPricing.tool_id.in_(tool_ids))
            if tenant_id is not None:
                stmt = stmt.where(DshToolPricing.tenant_id == tenant_id)
            await session.exec(stmt)

    @staticmethod
    async def acopy_for_child_tools(
        session,
        *,
        source_tenant_id: int,
        target_tenant_id: int,
        tool_id_pairs: list[tuple[int, int]],
        actor_user_id: int,
    ) -> int:
        if not tool_id_pairs or source_tenant_id == target_tenant_id:
            return 0
        source_ids = [src for src, _ in tool_id_pairs]
        with bypass_tenant_filter():
            rows = (
                await session.exec(
                    select(DshToolPricing).where(
                        DshToolPricing.tenant_id == source_tenant_id,
                        DshToolPricing.tool_id.in_(source_ids),
                    )
                )
            ).all()
            by_source = {row.tool_id: row for row in rows}
            copied = 0
            for src_id, dst_id in tool_id_pairs:
                src = by_source.get(src_id)
                if src is None or src.price_micro <= 0:
                    continue
                session.add(
                    DshToolPricing(
                        tenant_id=target_tenant_id,
                        tool_id=dst_id,
                        pricing_mode=src.pricing_mode,
                        currency=src.currency,
                        price_micro=src.price_micro,
                        call_count=src.call_count,
                        version=1,
                        updated_by=actor_user_id,
                    )
                )
                copied += 1
            return copied
