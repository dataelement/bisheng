"""Permission-owned SQL participant in the business owner's tenant-transfer transaction."""

from sqlalchemy import and_, select, update

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.services.projection_plan import build_projection_operation, projection_request_checksum
from bisheng.permission.domain.services.tenant_transfer_policy import (
    blocked,
    checksum,
    compile_transfer,
    operation_prefix,
)

# Core mapping queries below deliberately freeze complete rows, including provenance.
MODELS = (ResourcePermissionMode, PermissionGrant, PermissionGrantAssignee, PermissionVisibleSourceProjection)


class TenantPermissionTransferRepository:
    async def pin(self, session):
        with bypass_tenant_filter():
            rows = (
                await session.execute(
                    select(PermissionCatalogRelease, AuthorizationModelRelease)
                    .join(
                        AuthorizationModelRelease,
                        AuthorizationModelRelease.id
                        == PermissionCatalogRelease.required_authorization_model_release_id,
                    )
                    .where(PermissionCatalogRelease.status == "CURRENT")
                )
            ).all()
        if len(rows) != 1:
            blocked("CURRENT Catalog is not unique")
        catalog, authorization = rows[0]
        if catalog.write_fenced or authorization.status != "ACTIVE":
            blocked("Catalog is fenced")
        return {
            "catalog_id": catalog.id,
            "catalog_checksum": catalog.checksum,
            "store_id": authorization.store_id,
            "model_id": authorization.model_id,
            "model_checksum": authorization.model_checksum,
        }

    async def snapshot(self, session, *, source, destination, resources, lock=False):
        """Resources are exact IDs verified by their business owner, never caller strings."""
        if not resources:
            return ()
        result = []

        async def read(model, condition):
            table = model.__table__
            query = select(*table.c).where(condition).order_by(table.c.id)
            with bypass_tenant_filter():
                return [
                    dict(row) for row in (await session.execute(query.with_for_update() if lock else query)).mappings()
                ]

        for kind, ident in sorted(set(resources)):
            mode = ResourcePermissionMode.__table__
            modes = await read(
                ResourcePermissionMode,
                and_(
                    mode.c.tenant_id.in_((source, destination)),
                    mode.c.resource_type == kind,
                    mode.c.resource_id == ident,
                ),
            )
            if len(modes) != 1 or modes[0]["tenant_id"] != source:
                blocked(f"missing source mode or destination conflict: {kind}:{ident}")
            grant = PermissionGrant.__table__
            grants = await read(
                PermissionGrant,
                and_(
                    grant.c.resource_type == kind,
                    grant.c.resource_id == ident,
                    grant.c.tenant_id.in_((source, destination)),
                ),
            )
            if any(row["tenant_id"] != source for row in grants):
                blocked("destination Grant exists")
            assignee = PermissionGrantAssignee.__table__
            assignees = (
                await read(PermissionGrantAssignee, assignee.c.grant_id.in_([row["id"] for row in grants]))
                if grants
                else []
            )
            visible = PermissionVisibleSourceProjection.__table__
            sources = await read(
                PermissionVisibleSourceProjection,
                and_(
                    visible.c.resource_type == kind,
                    visible.c.resource_id == ident,
                    visible.c.tenant_id.in_((source, destination)),
                ),
            )
            if any(row["tenant_id"] != source for row in sources):
                blocked("destination visible source exists")
            operation = PermissionProjectionOperation.__table__
            pending = await read(
                PermissionProjectionOperation,
                and_(
                    operation.c.scope_type == "resource",
                    operation.c.scope_key == f"{kind}:{ident}",
                    operation.c.status != "FINALIZED",
                ),
            )
            if pending:
                blocked(f"pending permission operation: {kind}:{ident}")
            result.append({"mode": modes[0], "grants": grants, "assignees": assignees, "visible": sources})
        return tuple(result)

    async def prepare(self, session, *, snapshots, source, destination, pin, operator_id):
        if not session.in_transaction():
            blocked("native business transaction required")
        if await self.pin(session) != pin:
            blocked("Catalog changed")
        resources = tuple((row["mode"]["resource_type"], row["mode"]["resource_id"]) for row in snapshots)
        actual = await self.snapshot(session, source=source, destination=destination, resources=resources, lock=True)
        if checksum(actual) != checksum(snapshots):
            blocked("permission snapshot changed")
        operation_ids = []
        for snapshot in actual:
            plan = compile_transfer(snapshot, source=source, destination=destination, pin=pin, operator_id=operator_id)
            operation, tuples = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
            session.add(operation)
            await session.flush()
            for row in tuples:
                row.operation_id = operation.id
                session.add(row)
            await session.flush()
            for model, key in zip(MODELS, ("mode", "grants", "assignees", "visible"), strict=True):
                rows = [snapshot[key]] if key == "mode" else snapshot[key]
                ids = [row["id"] for row in rows]
                table = model.__table__
                values = {"tenant_id": destination}
                if key in {"mode", "grants"}:
                    values["projection_state"] = "PROJECTING"
                if key == "mode":
                    values["operation_id"] = operation.id
                for start in range(0, len(ids), 200):
                    changed = await session.execute(
                        update(table)
                        .where(table.c.tenant_id == source, table.c.id.in_(ids[start : start + 200]))
                        .values(**values)
                    )
                    if changed.rowcount != len(ids[start : start + 200]):
                        blocked("permission scope changed during transfer")
            operation_ids.append(int(operation.id))
        return tuple(operation_ids)

    async def pending(self, session, *, source, destination):
        table = PermissionProjectionOperation.__table__
        with bypass_tenant_filter():
            return tuple(
                (
                    await session.execute(
                        select(table.c.id)
                        .where(
                            table.c.tenant_id == destination,
                            table.c.operation_type == "RESOURCE_TENANT_TRANSFER",
                            table.c.idempotency_key.startswith(operation_prefix(source, destination)),
                            table.c.status != "FINALIZED",
                        )
                        .order_by(table.c.id)
                    )
                ).scalars()
            )
