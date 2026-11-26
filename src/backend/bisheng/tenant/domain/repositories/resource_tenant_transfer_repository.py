"""Exact business ownership closure for unmount; permission tables have a separate owner."""

from sqlalchemy import select, update
from sqlmodel import SQLModel

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.permission.domain.services.tenant_transfer_policy import blocked, checksum

RESOURCE_TABLES = {"assistant": "assistant", "flow": "workflow", "channel": "channel", "t_gpts_tools_type": "tool"}


def resource_kind(table, row):
    if table == "flow" and row.get("flow_type", 10) != 10:
        return None
    if table == "knowledge":
        return "knowledge_space" if row["type"] == 3 else ("knowledge_library" if row["type"] in {0, 1} else None)
    if table == "knowledgefile":
        return "folder" if row["file_type"] == 0 else "knowledge_file"
    return RESOURCE_TABLES.get(table)


class ResourceTenantTransferRepository:
    async def disable_source(self, session, source):
        with bypass_tenant_filter():
            row = (
                await session.execute(select(Tenant).where(Tenant.id == source).with_for_update())
            ).scalar_one_or_none()
        if row is None or source == 1 or row.status == "archived":
            blocked("source tenant is unavailable")
        await session.execute(
            update(Tenant).where(Tenant.id == source, Tenant.status == row.status).values(status="disabled")
        )

    async def collect(self, session, *, source, tables, filters, lock=False):
        rows = {}
        for name in sorted(tables):
            table = SQLModel.metadata.tables[name]
            columns = [table.c.id, table.c.tenant_id]
            columns.extend(
                table.c[key] for key in ("type", "flow_type", "file_type", "is_delete", "is_preset") if key in table.c
            )
            query = select(*columns).where(table.c.tenant_id == source).order_by(table.c.id)
            if name in filters:
                # Only the pre-existing preset exclusion is admitted; no arbitrary SQL.
                if name not in {"t_gpts_tools", "t_gpts_tools_type"} or filters[name] != "is_preset != 1":
                    blocked("unknown unmount row filter")
                query = query.where(table.c.is_preset != 1)
            with bypass_tenant_filter():
                rows[name] = [
                    dict(row) for row in (await session.execute(query.with_for_update() if lock else query)).mappings()
                ]
        return rows

    @staticmethod
    def resources(rows):
        return tuple(
            sorted(
                {
                    (kind, str(row["id"]))
                    for table, values in rows.items()
                    for row in values
                    if not row.get("is_delete") and (kind := resource_kind(table, row))
                }
            )
        )

    async def move(self, session, *, before, source, destination, tables, filters):
        actual = await self.collect(session, source=source, tables=tables, filters=filters, lock=True)
        if checksum(actual) != checksum(before):
            blocked("business ownership closure changed")
        counts = {}
        for name, rows in actual.items():
            table = SQLModel.metadata.tables[name]
            ids = [row["id"] for row in rows]
            counts[name] = len(ids)
            for start in range(0, len(ids), 200):
                result = await session.execute(
                    update(table)
                    .where(table.c.tenant_id == source, table.c.id.in_(ids[start : start + 200]))
                    .values(tenant_id=destination)
                )
                if result.rowcount != len(ids[start : start + 200]):
                    blocked("business owner changed during tenant transfer")
        return counts

    async def historical_resources(self, session, *, source, destination, lock=False):
        from bisheng.database.models.audit_log import AuditLog
        from bisheng.permission.domain.models import ResourcePermissionMode

        with bypass_tenant_filter():
            tenant_query = select(Tenant).where(Tenant.id == source)
            tenant = (
                await session.execute(tenant_query.with_for_update() if lock else tenant_query)
            ).scalar_one_or_none()
            audit = (
                await session.execute(
                    select(AuditLog.id)
                    .where(
                        AuditLog.tenant_id == source,
                        AuditLog.action == "tenant.unmount",
                        AuditLog.target_id == str(source),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if source == 1 or destination != 1 or tenant is None or tenant.status != "archived" or audit is None:
                blocked("historical repair requires an audited unmount to Root")
            modes = (
                (
                    await session.execute(
                        select(ResourcePermissionMode).where(ResourcePermissionMode.tenant_id == source)
                    )
                )
                .scalars()
                .all()
            )
            tables = {
                **{kind: table for table, kind in RESOURCE_TABLES.items()},
                "knowledge_space": "knowledge",
                "knowledge_library": "knowledge",
                "folder": "knowledgefile",
                "knowledge_file": "knowledgefile",
            }
            resources = []
            for mode in modes:
                name = tables.get(mode.resource_type)
                if name is None or name not in SQLModel.metadata.tables:
                    continue
                table = SQLModel.metadata.tables[name]
                # IDs are typed by the owning table; only its actual destination scope is authority.
                if mode.resource_type in {"tool", "knowledge_space", "knowledge_library", "folder", "knowledge_file"}:
                    if not mode.resource_id.isdecimal() or int(mode.resource_id) <= 0:
                        blocked("invalid numeric resource identity")
                    ident = int(mode.resource_id)
                else:
                    ident = mode.resource_id
                cols = [table.c.id, table.c.tenant_id]
                cols.extend(
                    table.c[key]
                    for key in ("type", "flow_type", "file_type", "is_delete", "is_preset")
                    if key in table.c
                )
                query = select(*cols).where(table.c.id == ident)
                row = (await session.execute(query.with_for_update() if lock else query)).mappings().one_or_none()
                if row is None or row["tenant_id"] != destination or row.get("is_delete"):
                    continue
                if name == "t_gpts_tools_type" and row["is_preset"] == 1:
                    blocked("preset tool unexpectedly migrated")
                if resource_kind(name, row) != mode.resource_type:
                    blocked("historical resource kind differs")
                resources.append((mode.resource_type, mode.resource_id))
            return tuple(sorted(resources))
