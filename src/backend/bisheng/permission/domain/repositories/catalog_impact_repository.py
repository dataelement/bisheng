"""Bounded reads of existing Catalog Grant/assignee impact, across tenants."""

from hashlib import sha256

from sqlalchemy import and_, or_
from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee

BATCH_SIZE = 200


def _after(columns, values):
    return or_(
        *(
            and_(
                *(column == value for column, value in zip(columns[:i], values[:i], strict=True)),
                columns[i] > values[i],
            )
            for i in range(len(columns))
        )
    )


class CatalogImpactRepository:
    def __init__(self, *, session_factory):
        self.sessions = session_factory

    async def agrant_pages(self, model_keys):
        if not model_keys:
            return
        keys = sorted(model_keys)
        columns = (
            PermissionGrant.tenant_id,
            PermissionGrant.resource_type,
            PermissionGrant.resource_id,
            PermissionGrant.model_key,
            PermissionGrant.id,
        )
        cursor = None
        with bypass_tenant_filter():
            while True:
                query = select(PermissionGrant).where(
                    PermissionGrant.state != "INACTIVE",
                    or_(
                        *(
                            col(PermissionGrant.model_key).in_(keys[i : i + BATCH_SIZE])
                            for i in range(0, len(keys), BATCH_SIZE)
                        )
                    ),
                )
                if cursor is not None:
                    query = query.where(_after(columns, cursor))
                async with self.sessions() as session:
                    rows = tuple((await session.exec(query.order_by(*columns).limit(BATCH_SIZE))).all())
                if not rows:
                    return
                last = rows[-1]
                cursor = (last.tenant_id, last.resource_type, last.resource_id, last.model_key, last.id)
                yield rows
                if len(rows) < BATCH_SIZE:
                    return

    async def asource_summaries(self, grant_ids):
        if len(grant_ids) > BATCH_SIZE:
            raise ValueError("Catalog impact source batch exceeds 200 Grants")
        summaries = {ident: [0, sha256()] for ident in grant_ids}
        cursor = None
        columns = (PermissionGrantAssignee.grant_id, PermissionGrantAssignee.id)
        with bypass_tenant_filter():
            while grant_ids:
                query = select(
                    PermissionGrantAssignee.grant_id,
                    PermissionGrantAssignee.id,
                    PermissionGrantAssignee.source_fingerprint,
                    PermissionGrantAssignee.version,
                    PermissionGrantAssignee.protected,
                ).where(col(PermissionGrantAssignee.grant_id).in_(grant_ids), PermissionGrantAssignee.state == "ACTIVE")
                if cursor is not None:
                    query = query.where(_after(columns, cursor))
                async with self.sessions() as session:
                    rows = tuple((await session.exec(query.order_by(*columns).limit(BATCH_SIZE))).all())
                if not rows:
                    break
                for grant_id, _ident, fingerprint, version, protected in rows:
                    summary = summaries[grant_id]
                    summary[0] += 1
                    summary[1].update(repr((fingerprint, version, bool(protected))).encode() + b"\n")
                cursor = rows[-1][:2]
                if len(rows) < BATCH_SIZE:
                    break
        return {ident: (count, digest.hexdigest()) for ident, (count, digest) in summaries.items()}

    async def asource_subjects(self, grant_ids):
        """按 200 行分页读取活跃授权来源主体，用于受影响用户展开与去重。"""
        if len(grant_ids) > BATCH_SIZE:
            raise ValueError("Catalog impact source batch exceeds 200 Grants")
        items: list[tuple[int, int, str, str, str | None, bool]] = []
        cursor = None
        columns = (PermissionGrantAssignee.grant_id, PermissionGrantAssignee.id)
        with bypass_tenant_filter():
            while grant_ids:
                query = select(
                    PermissionGrantAssignee.grant_id,
                    PermissionGrantAssignee.id,
                    PermissionGrantAssignee.tenant_id,
                    PermissionGrantAssignee.subject_type,
                    PermissionGrantAssignee.subject_id,
                    PermissionGrantAssignee.userset_relation,
                    PermissionGrantAssignee.include_children,
                ).where(col(PermissionGrantAssignee.grant_id).in_(grant_ids), PermissionGrantAssignee.state == "ACTIVE")
                if cursor is not None:
                    query = query.where(_after(columns, cursor))
                async with self.sessions() as session:
                    rows = tuple((await session.exec(query.order_by(*columns).limit(BATCH_SIZE))).all())
                if not rows:
                    break
                for grant_id, _ident, tenant_id, subject_type, subject_id, userset_relation, include_children in rows:
                    items.append(
                        (
                            int(grant_id),
                            int(tenant_id or 1),
                            str(subject_type),
                            str(subject_id),
                            str(userset_relation) if userset_relation is not None else None,
                            bool(include_children),
                        )
                    )
                cursor = rows[-1][:2]
                if len(rows) < BATCH_SIZE:
                    break
        return items
