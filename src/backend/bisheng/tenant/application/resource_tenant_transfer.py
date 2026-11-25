"""Unmount transfers business ownership and permission SQL in one native transaction."""

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.tenant_resource_transfer import resume_transfer, verify_transfer_input
from bisheng.permission.domain.repositories.tenant_transfer_repository import TenantPermissionTransferRepository
from bisheng.permission.domain.services.tenant_transfer_policy import blocked, checksum
from bisheng.tenant.domain.repositories.resource_tenant_transfer_repository import ResourceTenantTransferRepository


class ResourceTenantTransferApplication:
    def __init__(self, *, projection, session_factory=get_async_db_session):
        self.projection = projection
        self.sessions = session_factory
        self.business = ResourceTenantTransferRepository()
        self.permissions = TenantPermissionTransferRepository()

    async def preview(self, *, source, destination=1, tables=(), filters=None, historical=False):
        filters = filters or {}
        with bypass_tenant_filter():
            async with self.sessions() as session, session.begin():
                pin = await self.permissions.pin(session)
                before = (
                    {}
                    if historical
                    else await self.business.collect(session, source=source, tables=tables, filters=filters)
                )
                resources = (
                    await self.business.historical_resources(session, source=source, destination=destination)
                    if historical
                    else self.business.resources(before)
                )
                snapshots = await self.permissions.snapshot(
                    session, source=source, destination=destination, resources=resources
                )
        return {
            "source": source,
            "destination": destination,
            "pin": pin,
            "historical": historical,
            "business": before,
            "permissions": snapshots,
            "resources": resources,
            "tables": tuple(tables),
            "filters": filters,
        }

    async def resume(self, *, source, destination=1, resources=None):
        with bypass_tenant_filter():
            async with self.sessions() as session:
                pin = await self.permissions.pin(session)
                pending = await self.permissions.pending(session, source=source, destination=destination)
        # A maintenance replay is restricted to its confirmed backup; online
        # unmount retries may resume all original journals for that exact Child.
        selected = []
        scope = None if resources is None else {f"{kind}:{ident}" for kind, ident in resources}
        for ident in pending:
            with bypass_tenant_filter():
                operation = await self.projection._repository.aget_operation(ident)
            if scope is not None and operation.scope_key not in scope:
                continue
            if (operation.store_id, operation.model_id) != (pin["store_id"], pin["model_id"]):
                blocked("pending transfer belongs to another Catalog pin")
            selected.append(ident)
        await resume_transfer(self.projection, selected, destination=destination)
        return len(selected)

    async def apply(self, preview, *, operator_id, expected_checksum, expected_graph=None):
        if checksum(preview) != expected_checksum:
            blocked("transfer preview checksum changed")
        source, destination, pin = (preview[key] for key in ("source", "destination", "pin"))
        graph = await verify_transfer_input(
            self.projection,
            preview["permissions"],
            source=source,
            destination=destination,
            pin=pin,
            operator_id=operator_id,
        )
        if expected_graph is not None and checksum({key: sorted(rows) for key, rows in graph.items()}) != checksum(
            expected_graph
        ):
            blocked("physical preview changed")
        with bypass_tenant_filter():
            async with self.sessions() as session, session.begin():
                if preview["historical"]:
                    actual = await self.business.historical_resources(
                        session, source=source, destination=destination, lock=True
                    )
                    if tuple(actual) != tuple(tuple(row) for row in preview["resources"]):
                        blocked("historical ownership scope changed")
                else:
                    await self.business.disable_source(session, source)
                    # Serialize the final native ownership re-read before changing any mirror.
                    await self.business.collect(
                        session, source=source, tables=preview["tables"], filters=preview["filters"], lock=True
                    )
                ids = await self.permissions.prepare(
                    session,
                    snapshots=preview["permissions"],
                    source=source,
                    destination=destination,
                    pin=pin,
                    operator_id=operator_id,
                )
                counts = (
                    {}
                    if preview["historical"]
                    else await self.business.move(
                        session,
                        before=preview["business"],
                        source=source,
                        destination=destination,
                        tables=preview["tables"],
                        filters=preview["filters"],
                    )
                )
        await resume_transfer(self.projection, ids, destination=destination)
        return counts

    async def unmount(self, *, source, tables, filters, operator_id):
        await self.resume(source=source)
        preview = await self.preview(source=source, tables=tables, filters=filters)
        return await self.apply(preview, operator_id=operator_id, expected_checksum=checksum(preview))


async def migrate_unmounted_resources(*, source, tables, filters, operator_id):
    from bisheng.permission.application.access import get_f048_runtime

    runtime = await get_f048_runtime()
    await runtime.current_catalog()
    from bisheng.permission.application.tenant_resource_transfer import transfer_projection

    return await ResourceTenantTransferApplication(
        projection=transfer_projection(runtime._projection, runtime._client)
    ).unmount(source=source, tables=tables, filters=filters, operator_id=operator_id)
