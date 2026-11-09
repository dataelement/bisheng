"""Read original permission facts in the operational caller's transaction.

Global Catalog rows deliberately bypass no policy through a runtime loader:
they are global SQL data and may still contain the retired legacy use action.
All tenant-owned pages stay strictly scoped. Nothing is written or published.
"""

from dataclasses import fields

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.tenant import Tenant
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.catalog_policy import CatalogAction
from bisheng.permission.migration.f118_plan import (
    AuthorizationPinBaseline,
    CatalogReleaseBaseline,
    PermissionAssigneeBaseline,
    PermissionCatalogBaseline,
    PermissionGrantBaseline,
    PermissionModelBaseline,
    PermissionVisibleSourceBaseline,
    ResourceModeBaseline,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity


def _blocked(reason):
    raise PermissionMigrationBlockedError(reason=f"f118_snapshot_{reason}")


def _record(cls, row, **overrides):
    return cls(
        **{
            item.name: overrides[item.name] if item.name in overrides else row[item.name]
            for item in fields(cls)
            if item.name in row or item.name in overrides
        }
    )


class PermissionMigrationSnapshotRepository:
    async def avalidate_global_integrity(self, session):
        """One run-wide raw probe per original table, never per tenant."""
        self._scope(session)
        if not session.in_transaction():
            _blocked("native_transaction_required")
        tenant = Tenant.__table__.alias("f118_permission_actual_tenant")
        queries = []
        for model in (
            ResourcePermissionMode,
            PermissionGrant,
            PermissionGrantAssignee,
            PermissionVisibleSourceProjection,
        ):
            table = model.__table__.alias("f118_original_" + model.__tablename__)
            queries.append(
                select(table.c.id)
                .outerjoin(tenant, tenant.c.id == table.c.tenant_id)
                .where(or_(table.c.tenant_id.is_(None), tenant.c.id.is_(None)))
                .limit(1)
            )
        assignee = PermissionGrantAssignee.__table__.alias("f118_global_assignee")
        grant = PermissionGrant.__table__.alias("f118_global_grant")
        queries.append(
            select(assignee.c.id)
            .outerjoin(grant, grant.c.id == assignee.c.grant_id)
            .where(or_(grant.c.id.is_(None), assignee.c.tenant_id != grant.c.tenant_id))
            .limit(1)
        )
        with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            for query in queries:
                if (await session.execute(query)).first() is not None:
                    _blocked("global_original_orphan")

    @staticmethod
    def _scope(session):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
        ):
            _blocked("concrete_native_tenant_required")
        return tenant

    @staticmethod
    def _bounds(after_id, limit):
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or (after_id is not None and (type(after_id) is not int or after_id < 0))
        ):
            raise ValueError("snapshot pages require limit 1..200 and a nonnegative integer seek ID")

    async def _read(self, session, statement):
        self._scope(session)
        with session.no_autoflush, strict_tenant_filter():
            return tuple((await session.execute(statement)).mappings().all())

    async def _catalog_rows(self, session, table, *conditions, read=None):
        """Internal <=200-ID batches plus one unconsumed EOF lookahead."""
        read = read or self._read
        after = 0
        while True:
            rows = await read(
                session, select(*table.c).where(*conditions, table.c.id > after).order_by(table.c.id).limit(201)
            )
            batch = rows[:200]
            yield batch
            if len(rows) <= 200:
                return
            after = batch[-1]["id"]

    async def aload_catalog_baseline(self, session, *, environment):
        self._scope(session)
        if not isinstance(environment, str) or not environment.strip():
            _blocked("environment_required")
        release_table = PermissionCatalogRelease.__table__
        releases = await self._read(
            session,
            select(*release_table.c).where(release_table.c.status == "CURRENT").order_by(release_table.c.id).limit(2),
        )
        if len(releases) != 1:
            _blocked("current_catalog_not_unique")
        release = releases[0]
        auth_table = AuthorizationModelRelease.__table__
        pins = await self._read(
            session,
            select(*auth_table.c).where(auth_table.c.id == release["required_authorization_model_release_id"]).limit(1),
        )
        if (
            len(pins) != 1
            or pins[0]["environment"] != environment
            or pins[0]["status"] != "ACTIVE"
            or release["write_fenced"]
        ):
            _blocked("authorization_pin_not_ready")
        return await self._catalog_content(session, release, pins[0])

    async def aload_catalog_release(self, session: AsyncSession, *, release_id: int) -> PermissionCatalogBaseline:
        """Complete raw by-ID facts, retaining actual DRAFT/STAGED status."""
        tenant = self._scope(session)
        if type(release_id) is not int or release_id <= 0 or not session.in_transaction():
            _blocked("native_release_identity_required")
        try:
            transaction = TransactionIdentity.capture(session)
        except (TypeError, ValueError) as error:
            raise PermissionMigrationBlockedError(reason="f118_snapshot_release_transaction_changed") from error

        def current():
            if self._scope(session) != tenant or session.new or session.dirty or session.deleted:
                _blocked("release_context_changed")
            try:
                transaction.assert_current(session)
            except (TypeError, ValueError) as error:
                raise PermissionMigrationBlockedError(reason="f118_snapshot_release_transaction_changed") from error

        async def read(session, query):
            current()
            result = await self._read(session, query)
            current()
            return result

        release_table, auth_table = PermissionCatalogRelease.__table__, AuthorizationModelRelease.__table__
        releases = await read(session, select(*release_table.c).where(release_table.c.id == release_id))
        if len(releases) != 1:
            _blocked("catalog_release_missing")
        pins = await read(
            session,
            select(*auth_table.c).where(auth_table.c.id == releases[0]["required_authorization_model_release_id"]),
        )
        if len(pins) != 1:
            _blocked("catalog_release_authorization_missing")
        result = await self._catalog_content(session, releases[0], pins[0], read=read)
        current()
        return result

    async def _catalog_content(self, session, release, pin, *, read=None):
        read = read or self._read
        action_table, scope_table = PermissionAction.__table__, PermissionActionResourceScope.__table__
        actions = []
        action_by_id = {}
        async for rows in self._catalog_rows(
            session, action_table, action_table.c.catalog_release_id == release["id"], read=read
        ):
            if not rows:
                continue
            ids = tuple(row["id"] for row in rows)
            action_by_id.update((row["id"], row) for row in rows)
            scopes = {ident: [] for ident in ids}
            async for links in self._catalog_rows(session, scope_table, scope_table.c.action_id.in_(ids), read=read):
                for link in links:
                    scopes[link["action_id"]].append(link["resource_type"])
            actions.extend(
                CatalogAction(
                    row["code"],
                    row["name"],
                    row["level"],
                    row["active"],
                    frozenset(scopes[row["id"]]),
                    row["sort_order"],
                )
                for row in rows
            )
        model_table, link_table = PermissionModel.__table__, PermissionModelAction.__table__
        models = []
        async for rows in self._catalog_rows(
            session, model_table, model_table.c.catalog_release_id == release["id"], read=read
        ):
            if not rows:
                continue
            ids = tuple(row["id"] for row in rows)
            selected = {ident: [] for ident in ids}
            async for links in self._catalog_rows(session, link_table, link_table.c.model_id.in_(ids), read=read):
                for link in links:
                    action = action_by_id.get(link["action_id"])
                    if action is None:
                        _blocked("model_action_parent_mismatch")
                    selected[link["model_id"]].append(action)
            for row in rows:
                original_types = row["visibility_only_resource_types"]
                if original_types is not None and (
                    not isinstance(original_types, list) or not all(isinstance(value, str) for value in original_types)
                ):
                    _blocked("model_visibility_shape")
                chosen = sorted(selected[row["id"]], key=lambda item: item["id"])
                models.append(
                    _record(
                        PermissionModelBaseline,
                        row,
                        selected_action_codes=tuple(action["code"] for action in chosen),
                        effective_action_codes=tuple(
                            action["code"] for action in chosen if action["active"] and action["level"] is not None
                        ),
                        visibility_only_resource_types=tuple(original_types or ()),
                    )
                )
        return PermissionCatalogBaseline(
            _record(CatalogReleaseBaseline, release),
            _record(AuthorizationPinBaseline, pin),
            tuple(actions),
            tuple(models),
        )

    async def aload_resource(self, session, *, mode_id, resource_keys, lock=False):
        """Exact old/new resource buckets, including every inactive source."""
        tenant = self._scope(session)
        if (
            type(mode_id) is not int
            or mode_id <= 0
            or type(resource_keys) is not tuple
            or not 1 <= len(resource_keys) <= 2
            or type(lock) is not bool
            or not session.in_transaction()
        ):
            _blocked("resource_identity_required")
        transaction = TransactionIdentity.capture(session)

        def current():
            if self._scope(session) != tenant or session.new or session.dirty or session.deleted:
                _blocked("resource_context_changed")
            try:
                transaction.assert_current(session)
            except (TypeError, ValueError) as error:
                raise PermissionMigrationBlockedError(reason="f118_snapshot_resource_transaction_changed") from error

        async def read(query):
            current()
            result = await self._read(session, query.with_for_update() if lock else query)
            current()
            return result

        mode = ResourcePermissionMode.__table__
        rows = await read(select(*mode.c).where(mode.c.id == mode_id, mode.c.tenant_id == tenant))
        if len(rows) != 1 or (rows[0]["resource_type"], rows[0]["resource_id"]) not in resource_keys:
            _blocked("resource_mode_changed")
        await self._operations(session, rows)
        current()
        buckets = []
        for model in (PermissionGrant, PermissionVisibleSourceProjection):
            table, records, after = model.__table__, [], 0
            keys = []
            for key in resource_keys:
                if type(key) is not tuple or len(key) != 2 or not all(type(value) is str and value for value in key):
                    _blocked("resource_key_invalid")
                keys.append((table.c.resource_type == key[0]) & (table.c.resource_id == key[1]))
            while True:
                page = await read(
                    select(*table.c)
                    .where(table.c.tenant_id == tenant, or_(*keys), table.c.id > after)
                    .order_by(table.c.id)
                    .limit(200)
                )
                records.extend(page)
                if len(page) < 200:
                    break
                after = page[-1]["id"]
            buckets.append(records)
        grant_rows, visible_rows = buckets
        for start in range(0, len(visible_rows), 200):
            await self._operations(session, visible_rows[start : start + 200])
            current()
        sources = []
        source = PermissionGrantAssignee.__table__.alias("f118_resource_sources")
        for offset in range(0, len(grant_rows), 200):
            ids, after = tuple(row["id"] for row in grant_rows[offset : offset + 200]), 0
            while True:
                page = await read(
                    select(*source.c)
                    .where(source.c.grant_id.in_(ids), source.c.id > after)
                    .order_by(source.c.id)
                    .limit(200)
                )
                if any(row["tenant_id"] != tenant for row in page):
                    _blocked("resource_source_owner_changed")
                sources.extend(page)
                if len(page) < 200:
                    break
                after = page[-1]["id"]
        grouped = {}
        for row in sources:
            grouped.setdefault(row["grant_id"], []).append(row)
        names = set(VisibleSourceProjectionDTO.model_fields)
        from bisheng.permission.migration.f118_plan import PermissionResourceBaseline

        result = PermissionResourceBaseline(
            tenant,
            rows[0]["resource_type"],
            rows[0]["resource_id"],
            _record(ResourceModeBaseline, rows[0]),
            tuple(_record(PermissionGrantBaseline, row) for row in grant_rows),
            tuple(
                _record(PermissionAssigneeBaseline, source)
                for grant in grant_rows
                for source in grouped.get(grant["id"], ())
            ),
            tuple(
                PermissionVisibleSourceBaseline(
                    row["id"], VisibleSourceProjectionDTO.model_validate({key: row[key] for key in names})
                )
                for row in visible_rows
            ),
        )
        current()
        return result

    async def _page(self, session, model, *, after_id, limit):
        tenant = self._scope(session)
        self._bounds(after_id, limit)
        table = model.__table__
        statement = select(*table.c).where(table.c.id > (after_id or 0)).order_by(table.c.id).limit(limit)
        rows = await self._read(session, statement)
        if any(row["tenant_id"] != tenant for row in rows):
            _blocked("page_tenant_mismatch")
        return rows

    async def _operations(self, session, rows):
        ids = tuple(sorted({row["operation_id"] for row in rows if row["operation_id"] is not None}))
        if not ids:
            return
        table = PermissionProjectionOperation.__table__
        operations = await self._read(
            session, select(table.c.id, table.c.tenant_id, table.c.status).where(table.c.id.in_(ids))
        )
        expected = {row["id"]: row for row in operations}
        tenant = self._scope(session)
        if any(
            ident not in expected or expected[ident]["tenant_id"] != tenant or expected[ident]["status"] != "FINALIZED"
            for ident in ids
        ):
            _blocked("projection_operation_incomplete")

    async def alist_resource_modes(self, session, *, after_id=None, limit=200):
        rows = await self._page(session, ResourcePermissionMode, after_id=after_id, limit=limit)
        await self._operations(session, rows)
        return tuple(_record(ResourceModeBaseline, row) for row in rows)

    async def alist_grants(self, session, *, after_id=None, limit=200):
        rows = await self._page(session, PermissionGrant, after_id=after_id, limit=limit)
        return tuple(_record(PermissionGrantBaseline, row) for row in rows)

    async def alist_assignees(self, session, *, after_id=None, limit=200):
        tenant = self._scope(session)
        self._bounds(after_id, limit)
        source = PermissionGrantAssignee.__table__
        # Keep invalid parent chains visible as NULL/cross-tenant facts. A raw
        # alias prevents automatic child filtering from hiding broken joins.
        parent = PermissionGrant.__table__.alias("f118_original_grant_parent")
        rows = await self._read(
            session,
            select(
                *(getattr(PermissionGrantAssignee, column.name) for column in source.c),
                parent.c.id.label("parent_id"),
                parent.c.tenant_id.label("parent_tenant"),
            )
            .outerjoin(parent, parent.c.id == source.c.grant_id)
            .where(source.c.id > (after_id or 0))
            .order_by(source.c.id)
            .limit(limit),
        )
        if any(
            row["tenant_id"] != tenant or row["parent_id"] is None or row["parent_tenant"] != tenant for row in rows
        ):
            _blocked("assignee_parent_mismatch")
        return tuple(_record(PermissionAssigneeBaseline, row) for row in rows)

    async def alist_visible_sources(self, session, *, after_id=None, limit=200):
        rows = await self._page(session, PermissionVisibleSourceProjection, after_id=after_id, limit=limit)
        await self._operations(session, rows)
        names = set(VisibleSourceProjectionDTO.model_fields)
        return tuple(
            PermissionVisibleSourceBaseline(
                row["id"], VisibleSourceProjectionDTO.model_validate({key: row[key] for key in names})
            )
            for row in rows
        )
