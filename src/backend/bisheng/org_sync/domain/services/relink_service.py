"""F015 :class:`DepartmentRelinkService`.

SSO system migration escape hatch. Two strategies:

- ``external_id_map``: operator-supplied ``old_ext -> new_ext`` dict.
- ``path_plus_name``: discover candidates by ``(path, name)`` match;
  one candidate auto-applies, multiple candidates land in the
  :class:`RelinkConflictStore` for manual resolution via
  ``POST /api/v1/internal/departments/relink/resolve-conflict``.

``dry_run`` returns the list of intended rewrites without touching the
database or the conflict store. Every actual rewrite writes an
``audit_log.action='dept.relink_applied'`` (auto-apply path) or
``'dept.relink_resolved'`` (manual resolve path) entry.
"""

from __future__ import annotations

from typing import List

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    SsoRelinkConflictUnresolvedError,
    SsoRelinkStrategyUnsupportedError,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao
from bisheng.org_sync.domain.schemas.relink import (
    RelinkAppliedItem,
    RelinkCandidate,
    RelinkConflictItem,
    RelinkRequest,
    RelinkResponse,
)
from bisheng.org_sync.domain.services.relink_conflict_store import (
    RelinkConflictStore,
)


class DepartmentRelinkService:
    """Stateless orchestration over DepartmentDao + RelinkConflictStore."""

    # Injectable for tests — monkeypatch the attribute rather than the module.
    store = RelinkConflictStore

    @classmethod
    async def relink(cls, req: RelinkRequest) -> RelinkResponse:
        strategy = req.matching_strategy
        if strategy == 'external_id_map':
            return await cls._relink_external_id_map(req)
        if strategy == 'path_plus_name':
            return await cls._relink_path_plus_name(req)
        raise SsoRelinkStrategyUnsupportedError.http_exception()

    @classmethod
    async def resolve_conflict(
        cls, dept_id: int, chosen_new_external_id: str,
    ) -> RelinkAppliedItem:
        candidates = await cls.store.get(dept_id)
        if not candidates:
            raise SsoRelinkConflictUnresolvedError.http_exception(
                f'no stored candidates for dept {dept_id}')
        valid = {c.get('new_external_id') for c in candidates}
        if chosen_new_external_id not in valid:
            raise SsoRelinkConflictUnresolvedError.http_exception(
                f'{chosen_new_external_id} not among {sorted(valid)}')

        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None:
            raise SsoRelinkConflictUnresolvedError.http_exception(
                f'dept {dept_id} no longer exists')
        old_external_id = dept.external_id
        await DepartmentDao.aupdate_external_id(
            dept_id, chosen_new_external_id)
        await cls._audit_rewrite(
            dept_id=dept_id, tenant_id=dept.tenant_id,
            old_ext=old_external_id or '',
            new_ext=chosen_new_external_id,
            action='dept.relink_resolved',
            strategy='manual_resolve',
        )
        await cls.store.delete(dept_id)
        return RelinkAppliedItem(
            dept_id=dept_id,
            old_external_id=old_external_id or '',
            new_external_id=chosen_new_external_id,
        )

    # ------------------------------------------------------------------
    # Strategy: external_id_map
    # ------------------------------------------------------------------

    @classmethod
    async def _relink_external_id_map(
        cls, req: RelinkRequest,
    ) -> RelinkResponse:
        mapping = req.external_id_map or {}
        response = RelinkResponse()
        for old_ext in req.old_external_ids:
            new_ext = mapping.get(old_ext)
            if not new_ext:
                continue
            dept = await DepartmentDao.aget_by_source_external_id(
                req.source, old_ext)
            if dept is None:
                continue
            item = RelinkAppliedItem(
                dept_id=dept.id,
                old_external_id=old_ext,
                new_external_id=new_ext,
            )
            if req.dry_run:
                response.would_apply.append(item)
                continue
            await DepartmentDao.aupdate_external_id(dept.id, new_ext)
            await cls._audit_rewrite(
                dept_id=dept.id, tenant_id=dept.tenant_id,
                old_ext=old_ext, new_ext=new_ext,
                action='dept.relink_applied',
                strategy='external_id_map',
            )
            response.applied.append(item)
        return response

    # ------------------------------------------------------------------
    # Strategy: path_plus_name
    # ------------------------------------------------------------------

    @classmethod
    async def _relink_path_plus_name(
        cls, req: RelinkRequest,
    ) -> RelinkResponse:
        response = RelinkResponse()
        for old_ext in req.old_external_ids:
            dept = await DepartmentDao.aget_by_source_external_id(
                req.source, old_ext)
            if dept is None:
                continue
            candidates = await cls._find_candidates(req.source, dept)
            if not candidates:
                continue
            if len(candidates) == 1:
                new_ext = candidates[0]['new_external_id']
                item = RelinkAppliedItem(
                    dept_id=dept.id,
                    old_external_id=old_ext,
                    new_external_id=new_ext,
                )
                if req.dry_run:
                    response.would_apply.append(item)
                    continue
                await DepartmentDao.aupdate_external_id(dept.id, new_ext)
                await cls._audit_rewrite(
                    dept_id=dept.id, tenant_id=dept.tenant_id,
                    old_ext=old_ext, new_ext=new_ext,
                    action='dept.relink_applied',
                    strategy='path_plus_name',
                )
                response.applied.append(item)
            else:
                # Multi-candidate: persist + surface conflict.
                if not req.dry_run:
                    await cls.store.save(dept.id, candidates)
                response.conflicts.append(RelinkConflictItem(
                    dept_id=dept.id,
                    old_external_id=old_ext,
                    candidates=[RelinkCandidate(**c) for c in candidates],
                ))
        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _find_candidates(cls, source: str, dept) -> List[dict]:
        """Active same-source depts with identical ``(path, name)``.

        The old dept is explicitly excluded so it never matches itself.
        """
        depts = await DepartmentDao.aget_active_by_source_path_name(
            source=source, path=dept.path, name=dept.name,
            exclude_id=dept.id,
        )
        return [
            {
                'new_external_id': d.external_id,
                'path': d.path or '',
                'name': d.name or '',
                'score': 1.0,
            }
            for d in depts
            if d.external_id and d.external_id != dept.external_id
        ]

    @classmethod
    async def _audit_rewrite(
        cls,
        *,
        dept_id: int,
        tenant_id: int,
        old_ext: str,
        new_ext: str,
        action: str,
        strategy: str,
    ) -> None:
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id, operator_id=0,
                operator_tenant_id=tenant_id,
                action=action,
                target_type='department',
                target_id=str(dept_id),
                metadata={
                    'old_external_id': old_ext,
                    'new_external_id': new_ext,
                    'strategy': strategy,
                },
                ip_address='internal',
            )
        except Exception as e:  # audit write must not abort the relink
            logger.exception(
                f'audit_log.{action} failed for dept {dept_id}: {e}')
