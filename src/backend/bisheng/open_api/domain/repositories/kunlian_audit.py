"""Write existing AuditLog rows; never accept arbitrary request payloads."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLog


class KunlianAuditRepository:
    async def begin(self, values):
        row = AuditLog(**values)
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def finish(self, audit_id, http_status):
        # The generated UUID identifies a previously committed intent, including
        # when HTTP cleanup runs after the verified tenant context was restored.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                row = (
                    await session.exec(
                        select(AuditLog)
                        .where(AuditLog.id == audit_id, AuditLog.action == "open_api.kunlian.request")
                        .with_for_update()
                    )
                ).first()
                if row is None:
                    raise RuntimeError("Kunlian audit intent missing")
                metadata = dict(row.audit_metadata or {})
                if metadata.get("state") == "FINISHED":
                    return
                row.audit_metadata = metadata | {"state": "FINISHED", "http_status": http_status}
                session.add(row)
                await session.commit()
