"""F018 ResourceOwnershipService — batch owner transfer within a Tenant.

Implements spec AC-01~AC-10 / AC-08b/c/d:

  - ``transfer_owner``: single-transaction owner flip across MySQL (7
    resource tables) and OpenFGA (owner tuples). Enforces the visible-set
    rule (INV-T10: receiver leaf ∈ {tenant_id, Root}), supported paths
    "same tenant" and "Child → Root". Rejects Root → Child (AC-08d) with
    a hint to use F011 ``migrate-from-root``.
  - ``list_pending_transfer``: AC-10 MVP — reports users who still own
    resources in a tenant but whose active leaf tenant differs (the
    signal for "relocated away without handing off").

Dependencies outside this module are the minimum needed to land F018
without blocking on F012/F013:
  - Leaf tenant resolution → ``UserTenantDao.aget_active_user_tenant``
    (F011 shipped this; F012 will wrap it as a service).
  - Super-admin detection → ``operator.is_global_super()`` if present,
    else fall back to ``operator.is_admin()`` (F011 mount service uses
    the same guard; F013 will tighten).
  - OpenFGA owner flip → ``PermissionService.batch_write_tuples(..., crash_safe=True)``
    (F004 shipped crash-safe dual-write with ``FailedTuple`` compensation).
  - Audit log → ``AuditLogDao.ainsert_v2`` + ``TenantAuditAction.RESOURCE_TRANSFER_OWNER``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import bindparam, text

from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferBatchLimitError,
    ResourceTransferPermissionError,
    ResourceTransferReceiverOutOfTenantError,
    ResourceTransferSelfError,
    ResourceTransferTxFailedError,
    ResourceTransferUnsupportedTypeError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, UserTenantDao
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.services.resource_type_registry import (
    REGISTRY,
    ResourceTypeMeta,
    get_meta,
)

logger = logging.getLogger(__name__)

# AD-02: 500-item cap balances OpenFGA write throughput against lock time
# on per-table ``UPDATE ... WHERE id IN (...)``. 500 stays well inside
# MySQL's max_allowed_packet and OpenFGA's 100-per-request batch limit
# (PermissionService chunks internally).
MAX_BATCH: int = 500


@dataclass(frozen=True)
class ResourceRow:
    """Row returned by ``_resolve_resources`` — minimal projection used by
    the subsequent MySQL update and FGA tuple flip.
    """
    resource_type: str
    id: Union[int, str]
    user_id: int
    tenant_id: int


class ResourceOwnershipService:
    """Stateless service for spec §5 ``ResourceOwnershipService``."""

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @classmethod
    async def transfer_owner(
        cls,
        tenant_id: int,
        from_user_id: int,
        to_user_id: int,
        resource_types: List[str],
        resource_ids: Optional[List[Union[int, str]]] = None,
        reason: str = '',
        operator: Any = None,
    ) -> Dict[str, Any]:
        """Transfer owner of ``from_user_id``'s resources to ``to_user_id``
        within ``tenant_id``. Returns ``{transferred_count, transfer_log_id}``.

        Raises (spec §9 error codes):
          - 19601 non-owner + non-admin (AC-03)
          - 19602 > MAX_BATCH after resource resolution (AC-07)
          - 19603 receiver leaf out of visible set (AC-08/08c/08d)
          - 19604 unknown resource_type (AC-unsupported-type)
          - 19605 MySQL/OpenFGA transaction failure (AC-06)
          - 19606 from_user_id == to_user_id
        """
        # 1. Fast validations (before any DB I/O)
        if from_user_id == to_user_id:
            raise ResourceTransferSelfError()
        for rt in resource_types:
            get_meta(rt)  # raises 19604 if unknown

        # 2. Operator permission gate (AC-03)
        cls._check_operator(operator, from_user_id)

        # 3. Receiver visible-set check (INV-T10 / AC-08)
        await cls._check_receiver_visible(to_user_id, tenant_id)

        # 4. Resolve resources owned by from_user within tenant
        resources = await cls._resolve_resources(
            tenant_id, from_user_id, resource_types, resource_ids,
        )
        if len(resources) > MAX_BATCH:
            raise ResourceTransferBatchLimitError()
        if not resources:
            return {'transferred_count': 0, 'transfer_log_id': None}

        # 5. Transactional flip: MySQL → OpenFGA (crash_safe) → audit
        transfer_log_id = cls._make_transfer_log_id()
        try:
            await cls._bulk_update_user_ids(resources, to_user_id)
            await cls._flip_fga_owner_tuples(resources, from_user_id, to_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'transfer_owner transaction failed tenant=%s from=%s to=%s: %s',
                tenant_id, from_user_id, to_user_id, exc,
            )
            raise ResourceTransferTxFailedError() from exc

        await cls._safe_audit(
            tenant_id=tenant_id,
            operator=operator,
            transfer_log_id=transfer_log_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            resources=resources,
            reason=reason,
        )
        return {
            'transferred_count': len(resources),
            'transfer_log_id': transfer_log_id,
        }

    @classmethod
    async def list_pending_transfer(cls, tenant_id: int) -> List[Dict[str, Any]]:
        """Return users who still own resources in ``tenant_id`` but whose
        current leaf tenant differs (AC-10 MVP signal).

        Aggregates per-user resource counts across all 7 registered
        tables, then compares each user's active leaf. No resource-age
        threshold is applied — callers that want a "超期" cutoff should
        filter on the client side.
        """
        counts_by_user: Dict[int, int] = {}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for meta in REGISTRY.values():
                    sql = (
                        f'SELECT user_id, COUNT(*) FROM {meta.table} '
                        f'WHERE tenant_id = :tid AND user_id IS NOT NULL'
                    )
                    if meta.type_filter_sql:
                        sql += f' AND {meta.type_filter_sql}'
                    sql += ' GROUP BY user_id'
                    rows = (
                        await session.execute(text(sql), {'tid': tenant_id})
                    ).all()
                    for uid, count in rows:
                        if uid is None:
                            continue
                        counts_by_user[int(uid)] = (
                            counts_by_user.get(int(uid), 0) + int(count)
                        )

        pending: List[Dict[str, Any]] = []
        for uid, count in counts_by_user.items():
            leaf = await cls._resolve_leaf_tenant(uid)
            if leaf != tenant_id:
                pending.append({
                    'user_id': uid,
                    'resource_count': count,
                    'current_leaf_tenant_id': leaf,
                })
        return pending

    # -----------------------------------------------------------------------
    # Operator / receiver gates
    # -----------------------------------------------------------------------

    @classmethod
    def _check_operator(cls, operator: Any, from_user_id: int) -> None:
        """AC-03: owner / tenant admin / global super — one of the three."""
        if operator is None:
            raise ResourceTransferPermissionError()
        if getattr(operator, 'user_id', None) == from_user_id:
            return  # owner themselves
        is_super = getattr(operator, 'is_global_super', None)
        if callable(is_super) and is_super():
            return  # global super (tenant-wide)
        is_admin = getattr(operator, 'is_admin', None)
        if callable(is_admin) and is_admin():
            return  # tenant admin (F013 will narrow this into is_tenant_admin)
        raise ResourceTransferPermissionError()

    @classmethod
    async def _check_receiver_visible(cls, to_user_id: int, tenant_id: int) -> None:
        """AC-08 / INV-T10: receiver's leaf tenant must be in
        ``{tenant_id, ROOT_TENANT_ID}``.

        Two legal paths:
          - tenant_id == Root  → allowed = {Root}           (AC-08d rejects Child)
          - tenant_id == Child → allowed = {Child, Root}    (AC-08b allows Root)
        """
        leaf = await cls._resolve_leaf_tenant(to_user_id)
        allowed = {tenant_id, ROOT_TENANT_ID}
        if leaf not in allowed:
            raise ResourceTransferReceiverOutOfTenantError()

    @classmethod
    async def _resolve_leaf_tenant(cls, user_id: int) -> int:
        """F012 drop-in: fall back to Root when the user has no active
        ``UserTenant`` record (e.g. new signup before SSO sync)."""
        record = await UserTenantDao.aget_active_user_tenant(user_id)
        return record.tenant_id if record is not None else ROOT_TENANT_ID

    # -----------------------------------------------------------------------
    # Resource resolution & bulk updates
    # -----------------------------------------------------------------------

    @classmethod
    async def _resolve_resources(
        cls,
        tenant_id: int,
        from_user_id: int,
        resource_types: List[str],
        resource_ids: Optional[List[Union[int, str]]],
    ) -> List[ResourceRow]:
        """For each requested ``resource_type``, select rows owned by
        ``from_user_id`` inside ``tenant_id``. When ``resource_ids`` is
        provided, it filters the entire batch across types (ids are
        globally unique within a table; a stray id type mismatch will
        simply miss the row rather than leaking across resources).
        """
        results: List[ResourceRow] = []
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for rt in resource_types:
                    meta = get_meta(rt)
                    rows = await cls._select_resources(
                        session, meta, tenant_id, from_user_id, resource_ids,
                    )
                    for row in rows:
                        results.append(ResourceRow(
                            resource_type=rt,
                            id=row[0],
                            user_id=int(row[1]) if row[1] is not None else 0,
                            tenant_id=int(row[2]) if row[2] is not None else 0,
                        ))
        return results

    @classmethod
    async def _select_resources(
        cls,
        session: Any,
        meta: ResourceTypeMeta,
        tenant_id: int,
        from_user_id: int,
        resource_ids: Optional[List[Union[int, str]]],
    ) -> List[Tuple[Any, Any, Any]]:
        sql = (
            f'SELECT id, user_id, tenant_id FROM {meta.table} '
            f'WHERE user_id = :uid AND tenant_id = :tid'
        )
        if meta.type_filter_sql:
            sql += f' AND {meta.type_filter_sql}'

        params: Dict[str, Any] = {'uid': from_user_id, 'tid': tenant_id}

        if resource_ids:
            coerced = cls._coerce_ids(meta, resource_ids)
            if not coerced:
                return []
            sql += ' AND id IN :ids'
            stmt = text(sql).bindparams(bindparam('ids', expanding=True))
            params['ids'] = coerced
        else:
            stmt = text(sql)

        res = await session.execute(stmt, params)
        return res.all()

    @staticmethod
    def _coerce_ids(
        meta: ResourceTypeMeta, raw_ids: List[Union[int, str]],
    ) -> List[Union[int, str]]:
        """Silently drop ids whose type doesn't match the target table's
        id_type (e.g. numeric ids sent to the Flow UUID table). The
        mismatched ids simply won't match any rows — same outcome as
        coercing would give, but we avoid ValueError on non-numeric str
        inputs for numeric tables.
        """
        out: List[Union[int, str]] = []
        for rid in raw_ids:
            if meta.id_type is int:
                if isinstance(rid, int):
                    out.append(rid)
                elif isinstance(rid, str) and rid.isdigit():
                    out.append(int(rid))
                # else: drop silently (type mismatch)
            else:  # id_type is str
                if isinstance(rid, str):
                    out.append(rid)
                elif isinstance(rid, int):
                    out.append(str(rid))
        return out

    @classmethod
    async def _bulk_update_user_ids(
        cls, resources: List[ResourceRow], to_user_id: int,
    ) -> None:
        """Per-table ``UPDATE SET user_id = :uid WHERE id IN (...)``.

        Grouped by resource_type (not by table) so that the folder and
        knowledge_file cases — which share ``knowledgefile`` — each get
        their own ``type_filter_sql`` re-applied. This is slightly
        redundant (the ids already disambiguate) but keeps the update
        SQL symmetric with the select SQL and makes audits line up with
        per-type resource counts.
        """
        by_type: Dict[str, List[Union[int, str]]] = {}
        for r in resources:
            by_type.setdefault(r.resource_type, []).append(r.id)

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                try:
                    for rt, ids in by_type.items():
                        meta = get_meta(rt)
                        stmt = text(
                            f'UPDATE {meta.table} SET user_id = :uid '
                            f'WHERE id IN :ids'
                        ).bindparams(bindparam('ids', expanding=True))
                        await session.execute(stmt, {'uid': to_user_id, 'ids': ids})
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

    # -----------------------------------------------------------------------
    # OpenFGA owner flip
    # -----------------------------------------------------------------------

    @classmethod
    async def _flip_fga_owner_tuples(
        cls,
        resources: List[ResourceRow],
        from_user_id: int,
        to_user_id: int,
    ) -> None:
        """Delete ``user:{from}/owner/{type}:{id}`` and write
        ``user:{to}/owner/{type}:{id}`` for every resource.

        ``crash_safe=True`` pre-records both ops in ``failed_tuples``
        before calling FGA; on FGA success they're purged. If this
        process dies between the MySQL commit above and the FGA write,
        the compensation worker replays from ``failed_tuples``
        (INV-4).
        """
        if not resources:
            return
        ops: List[TupleOperation] = []
        for r in resources:
            obj = f'{r.resource_type}:{r.id}'
            ops.append(TupleOperation(
                action='delete', user=f'user:{from_user_id}',
                relation='owner', object=obj,
            ))
            ops.append(TupleOperation(
                action='write', user=f'user:{to_user_id}',
                relation='owner', object=obj,
            ))
        await PermissionService.batch_write_tuples(ops, crash_safe=True)

    # -----------------------------------------------------------------------
    # Audit
    # -----------------------------------------------------------------------

    @classmethod
    async def _safe_audit(
        cls,
        tenant_id: int,
        operator: Any,
        transfer_log_id: str,
        from_user_id: int,
        to_user_id: int,
        resources: List[ResourceRow],
        reason: str,
    ) -> None:
        """Best-effort audit_log insert. Mirrors F011 `_safe_audit`:
        the main transaction already committed, so an audit failure
        here is logged but never raised — callers still get the
        successful count."""
        try:
            ids_by_type: Dict[str, List[Union[int, str]]] = {}
            for r in resources:
                ids_by_type.setdefault(r.resource_type, []).append(r.id)
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=getattr(operator, 'user_id', 0) or 0,
                operator_tenant_id=cls._resolve_operator_tenant_id(
                    operator, tenant_id,
                ),
                action=TenantAuditAction.RESOURCE_TRANSFER_OWNER.value,
                target_type='resource_batch',
                target_id=transfer_log_id,
                reason=reason or None,
                metadata={
                    'from': from_user_id,
                    'to': to_user_id,
                    'count': len(resources),
                    'resource_types': sorted(ids_by_type.keys()),
                    'resource_ids_by_type': ids_by_type,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'audit_log insert failed for resource.transfer_owner '
                'tenant=%s transfer_log=%s: %s',
                tenant_id, transfer_log_id, exc,
            )

    @staticmethod
    def _resolve_operator_tenant_id(operator: Any, tenant_id: int) -> int:
        """Spec §5.4 operator_tenant_id rule.

        When F019 ``admin_scope_tenant_id`` is set (super admin switched
        management view), honor it. Otherwise: super admins default to
        ROOT, tenant admins / ordinary users default to their own leaf.
        Falls back to the resource tenant_id when the operator shape is
        unknown (test doubles, system triggers).
        """
        scope = getattr(operator, 'admin_scope_tenant_id', None)
        if scope:
            return int(scope)
        is_super = getattr(operator, 'is_global_super', None)
        if callable(is_super) and is_super():
            return ROOT_TENANT_ID
        op_tenant = getattr(operator, 'tenant_id', None)
        if op_tenant:
            return int(op_tenant)
        return tenant_id

    @staticmethod
    def _make_transfer_log_id() -> str:
        """``txn_YYYYMMDD_<8hex>`` — mirrors the PRD §5.6.3.1 sample
        response ``txn_20260420_abc123``."""
        return f'txn_{datetime.utcnow():%Y%m%d}_{uuid.uuid4().hex[:8]}'
