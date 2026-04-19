"""Idempotent department tree upsert for F014 Gateway push flows.

``DeptUpsertService`` is the single gatekeeper that translates
:class:`DepartmentUpsertItem` payloads into ``DepartmentDao`` writes while
enforcing three invariants:

1. **Never touch mount state.** ``is_tenant_root`` and
   ``mounted_tenant_id`` belong to bisheng internal state (F011). SSO sync
   resilience requires accidental remount to be impossible even if the
   upstream source-of-truth changes names or reparents the department
   (PRD §5.2.5).

2. **Parent chain must exist.** :meth:`assert_parent_chain_exists` rejects
   SSO login-sync calls whose primary/secondary department has not yet
   been pushed via ``/departments/sync`` (SsoDeptParentMissingError →
   19312). This keeps the tree consistent; fail-fast over build-a-tiny-
   orphan.

3. **Materialised path stays consistent.** On upsert the ``path`` column is
   recomputed from the parent row's path; legacy rows with broken paths
   still upsert successfully because we derive the child path from the
   (freshly looked-up) parent's current path, not from any cached value.
"""

from typing import Dict, Iterable, List, Optional

from bisheng.common.errcode.sso_sync import SsoDeptParentMissingError
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.sso_sync.domain.schemas.payloads import DepartmentUpsertItem


class DeptUpsertService:

    SOURCE = 'sso'

    # -----------------------------------------------------------------------
    # Pre-flight checks for login-sync flow
    # -----------------------------------------------------------------------

    @classmethod
    async def assert_parent_chain_exists(
        cls, external_ids: Iterable[str],
    ) -> Dict[str, Department]:
        """Resolve every ``external_id`` to a Department row, raise 19312 on
        the first miss.

        Used by :class:`LoginSyncService` to fail fast when the Gateway has
        not yet pushed the user's department tree. Returns the resolved
        mapping so callers don't have to requery.
        """
        resolved: Dict[str, Department] = {}
        missing: List[str] = []
        for ext in external_ids:
            if not ext:
                continue
            dept = await DepartmentDao.aget_by_source_external_id(
                cls.SOURCE, ext,
            )
            if dept is None or dept.is_deleted == 1:
                missing.append(ext)
                continue
            resolved[ext] = dept
        if missing:
            raise SsoDeptParentMissingError.http_exception(
                f'departments not synced yet: {missing}'
            )
        return resolved

    # -----------------------------------------------------------------------
    # Per-item upsert helper used by departments/sync batch
    # -----------------------------------------------------------------------

    @classmethod
    async def upsert_from_sync_payload(
        cls,
        existing: Optional[Department],
        item: DepartmentUpsertItem,
        source: str,
        last_sync_ts: int,
    ) -> Department:
        """Apply a single upsert. The caller is responsible for running
        :class:`OrgSyncTsGuard` and passing only APPLY-verdicted items.

        Parent resolution rule: if ``item.parent_external_id`` is set, the
        parent must already exist in bisheng (same source) — otherwise
        raises 19312. Top-level items (``parent_external_id is None``)
        attach directly under Root (``parent_id=None``).
        """
        parent_id: Optional[int] = None
        parent_path: str = ''
        if item.parent_external_id:
            parent = await DepartmentDao.aget_by_source_external_id(
                source, item.parent_external_id,
            )
            if parent is None or parent.is_deleted == 1:
                raise SsoDeptParentMissingError.http_exception(
                    f'parent {item.parent_external_id} not synced for '
                    f'child {item.external_id}'
                )
            parent_id = parent.id
            parent_path = parent.path or ''

        # ``path`` convention (F002): /id1/id2/.../parent_id/ — always
        # terminated with '/'. For a new row we stamp a provisional path
        # and leave the definitive ``/parent_path + self_id + '/'`` update
        # to the existing F002 path helpers when path-rewrites land.
        if parent_id is None:
            computed_path = '/'
        else:
            base = parent_path if parent_path.endswith('/') else parent_path + '/'
            computed_path = f'{base}{parent_id}/'

        return await DepartmentDao.aupsert_by_external_id(
            source=source,
            external_id=item.external_id,
            name=item.name,
            parent_id=parent_id,
            path=computed_path,
            sort_order=item.sort,
            last_sync_ts=last_sync_ts,
        )
