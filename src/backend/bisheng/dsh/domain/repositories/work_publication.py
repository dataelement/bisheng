"""Strict tenant-scoped publication and safe Work audit records."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.dsh.domain.models.work_publication import DshWorkPublication
from bisheng.dsh.domain.repositories.admin_operation import require_tenant


class WorkPublicationRepository:
    @staticmethod
    def _tenant(tenant_id):
        if require_tenant() != tenant_id:
            raise ValueError("Work requires the authenticated tenant context")

    async def list_enabled(self, tenant_id: int, kind: str) -> set[int]:
        self._tenant(tenant_id)
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                rows = await session.exec(
                    select(DshWorkPublication).where(
                        DshWorkPublication.kind == kind,
                        DshWorkPublication.enabled == True,  # noqa: E712
                    )
                )
                values = list(rows)
                if any(row.tenant_id != tenant_id for row in values):
                    raise ValueError("Work publication tenant mismatch")
                return {row.resource_id for row in values}

    async def save(self, tenant_id: int, kind: str, resource_id: int, enabled: bool) -> None:
        self._tenant(tenant_id)
        key = f"{tenant_id}:{kind}:{resource_id}"
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                # A competing first publication may insert the same stable key.
                for attempt in range(2):
                    row = await session.get(DshWorkPublication, key)
                    if row is None:
                        row = DshWorkPublication(key=key, tenant_id=tenant_id, kind=kind, resource_id=resource_id)
                    if row.tenant_id != tenant_id:
                        raise ValueError("Work publication tenant mismatch")
                    row.enabled = enabled
                    session.add(row)
                    try:
                        await session.commit()
                        return
                    except IntegrityError:
                        await session.rollback()
                        if attempt:
                            raise

    async def audit(self, user, action, kind, resource_id, metadata):
        self._tenant(user.tenant_id)
        from bisheng.database.models.audit_log import AuditLogDao

        await AuditLogDao.ainsert_v2(
            tenant_id=user.tenant_id,
            operator_id=user.user_id,
            operator_tenant_id=user.tenant_id,
            operator_name=getattr(user, "user_name", None),
            action=f"dsh.work.{action}",
            target_type=kind,
            target_id=str(resource_id),
            metadata=metadata,
        )
