"""F017 ResourceShareService — Root→Child resource sharing via OpenFGA tuples.

Implements the DSL v2.0.1 tuple scheme (spec §5.1 + release-contract):

- **Resource-level** ``{resource}#shared_with → tenant:{child_id}`` — one tuple
  per Child; makes the resource visible via the viewer tupleToUserset chain.
- **Tenant-level**  ``tenant:{child_id}#shared_to → tenant:{root_id}`` — one
  tuple per Child; feeds ``PermissionService._is_shared_to()`` L3 check.

These two tuples together implement the PRD §7.2 intent
``{resource}#viewer → tenant:{root}#shared_to#member`` (which OpenFGA protobuf
rejects due to the nested ``#`` restriction on ``directly_related_user_types``).
See DSL v2.0.1 redesign in ``core/openfga/authorization_model.py`` v2.0.1 notes.

Usage scenarios:

1. ``enable_sharing / disable_sharing`` — toggle share on a single Root
   resource; fan out writes/deletes over all active Children.
2. ``distribute_to_child / revoke_from_child`` — on Child mount/unmount,
   write/revoke the Tenant-level ``shared_to`` tuple so the _is_shared_to
   check short-circuits correctly.
3. ``list_sharing_children`` — introspect which Children a given resource is
   currently shared with (UI / audit / unmount cleanup).

FGA write failures surface as ``FGAWriteError`` and are expected to be
captured by the upstream compensator (``failed_tuples`` table from F013).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)

# Resource types that support group-sharing. Must stay aligned with the DSL
# (authorization_model.py) — adding a new type here without updating the model
# causes OpenFGA to reject writes with "unknown object type".
SUPPORTED_SHAREABLE_TYPES: set[str] = {
    'knowledge_space',
    'workflow',
    'assistant',
    'channel',
    'tool',
    # llm_model follows its parent llm_server and is not shared directly.
    'llm_server',
}


class ResourceShareService:
    """FGA tuple wrapper for Root→Child resource sharing (F017)."""

    # ── FGA client acquisition ───────────────────────────────────

    @staticmethod
    def _get_fga():
        """Return the singleton FGAClient or None when OpenFGA is disabled.

        Mirrors ``PermissionService._get_fga``; returning None lets higher
        layers degrade gracefully in local dev without OpenFGA configured.
        """
        from bisheng.core.openfga.manager import get_fga_client
        return get_fga_client()

    # ── Resource-level sharing (shared_with) ─────────────────────

    @classmethod
    async def enable_sharing(
        cls,
        object_type: str,
        object_id: str,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> List[int]:
        """Write ``{object_type}:{object_id}#shared_with → tenant:{child}`` for
        each active Child. Returns the list of child_ids that received the
        tuple (empty if no active Children).

        Raises ValueError for unsupported resource types.
        """
        cls._validate_type(object_type)
        fga = cls._get_fga()
        if fga is None:
            logger.info('[F017] OpenFGA disabled; skip enable_sharing %s:%s', object_type, object_id)
            return []

        child_ids = await TenantDao.aget_children_ids_active(root_tenant_id)
        if not child_ids:
            logger.info('[F017] No active children to share %s:%s', object_type, object_id)
            return []

        writes = [
            {
                'user': f'tenant:{cid}',
                'relation': 'shared_with',
                'object': f'{object_type}:{object_id}',
            }
            for cid in child_ids
        ]
        await fga.write_tuples(writes=writes)
        logger.info('[F017] Shared %s:%s with %d children', object_type, object_id, len(child_ids))
        return child_ids

    @classmethod
    async def disable_sharing(
        cls,
        object_type: str,
        object_id: str,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> List[int]:
        """Delete all ``{object_type}:{object_id}#shared_with → tenant:*`` tuples.

        Returns the list of child_ids whose tuples were revoked. Reads existing
        tuples first to produce a precise delete list (safe even if some
        Children were added mid-flight).
        """
        cls._validate_type(object_type)
        fga = cls._get_fga()
        if fga is None:
            return []

        # FGA server narrows to shared_with rows; we still filter the user
        # prefix client-side to guard against any non-tenant subject that
        # somehow got written under shared_with.
        existing = await fga.read_tuples(
            relation='shared_with',
            object=f'{object_type}:{object_id}',
        )
        deletes = [
            {
                'user': t['user'],
                'relation': 'shared_with',
                'object': f'{object_type}:{object_id}',
            }
            for t in existing
            if t.get('user', '').startswith('tenant:')
        ]
        if not deletes:
            return []

        await fga.write_tuples(deletes=deletes)
        revoked = [int(d['user'].split(':', 1)[1]) for d in deletes]
        logger.info('[F017] Unshared %s:%s from %d children', object_type, object_id, len(revoked))
        return revoked

    @classmethod
    async def list_sharing_children(
        cls,
        object_type: str,
        object_id: str,
    ) -> List[int]:
        """Return the child tenant_ids this resource is currently shared with.

        Reads the FGA side (ground truth), not the ``is_shared`` DB column —
        useful for audit/UI and for reconciling after a manual tuple edit.
        """
        cls._validate_type(object_type)
        fga = cls._get_fga()
        if fga is None:
            return []

        existing = await fga.read_tuples(
            relation='shared_with',
            object=f'{object_type}:{object_id}',
        )
        return [
            int(t['user'].split(':', 1)[1])
            for t in existing
            if t.get('user', '').startswith('tenant:')
        ]

    # ── Tenant-level distribution (shared_to) ────────────────────

    @classmethod
    async def distribute_to_child(
        cls,
        child_id: int,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> None:
        """Write ``tenant:{child_id}#shared_to → tenant:{root_tenant_id}``.

        Called on Child mount (``TenantMountService._on_child_mounted``) so
        the Child is included in the ``tenant#shared_to`` set used by
        ``PermissionService._is_shared_to()``. Idempotent at the FGA side
        (duplicate writes are no-ops).
        """
        fga = cls._get_fga()
        if fga is None:
            return
        await fga.write_tuples(writes=[
            {
                'user': f'tenant:{child_id}',
                'relation': 'shared_to',
                'object': f'tenant:{root_tenant_id}',
            },
        ])
        logger.info('[F017] distribute_to_child: tenant:%s → shared_to tenant:%s', child_id, root_tenant_id)

    @classmethod
    async def revoke_from_child(
        cls,
        child_id: int,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> None:
        """Delete ``tenant:{child_id}#shared_to → tenant:{root_tenant_id}``.

        Called on Child unmount (``TenantMountService._on_child_unmounted``)
        to prevent dangling shared_to relations after the Child is removed.
        """
        fga = cls._get_fga()
        if fga is None:
            return
        await fga.write_tuples(deletes=[
            {
                'user': f'tenant:{child_id}',
                'relation': 'shared_to',
                'object': f'tenant:{root_tenant_id}',
            },
        ])
        logger.info('[F017] revoke_from_child: tenant:%s → shared_to tenant:%s', child_id, root_tenant_id)

    # ── is_shared DB flag (mirror of FGA shared_with for list/UI speed) ─

    @classmethod
    async def set_is_shared(
        cls, object_type: str, object_id: str, is_shared: bool,
    ) -> None:
        """Flip ``{resource}.is_shared`` in the backing table for the 5 types.

        FGA ``shared_with`` is the source of truth for access decisions; this
        column is a denormalized cache so list queries / list_root_shared
        snapshots don't need an FGA scan per row. Callers that toggle sharing
        must call this so the two views stay consistent.
        """
        cls._validate_type(object_type)
        if object_type == 'knowledge_space':
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
            rows = await KnowledgeDao.aget_list_by_ids([int(object_id)])
            if rows:
                row = rows[0]
                row.is_shared = is_shared
                await KnowledgeDao.aupdate_one(row)
            return
        if object_type == 'workflow':
            from bisheng.database.models.flow import FlowDao
            row = await FlowDao.aget_flow_by_id(object_id)
            if row is not None:
                row.is_shared = is_shared
                await FlowDao.aupdate_flow(row)
            return
        if object_type == 'assistant':
            # AssistantDao exposes sync ``update_assistant``; wrap in a thread
            # so we don't block the event loop when called from async paths.
            import asyncio as _asyncio
            from bisheng.database.models.assistant import AssistantDao
            row = await AssistantDao.aget_one_assistant(object_id)
            if row is not None:
                row.is_shared = is_shared
                await _asyncio.to_thread(AssistantDao.update_assistant, row)
            return
        if object_type == 'channel':
            from bisheng.channel.domain.models.channel import Channel
            from bisheng.core.database import get_async_db_session
            from sqlmodel import select
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(Channel).where(Channel.id == object_id),
                )
                row = result.first()
                if row is not None:
                    row.is_shared = is_shared
                    session.add(row)
                    await session.commit()
            return
        if object_type == 'tool':
            from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
            await GptsToolsDao.aset_tool_type_is_shared(int(object_id), is_shared)
            return

    # ── High-level orchestrator (used by 5 resource create flows) ─

    @classmethod
    async def share_on_create(
        cls,
        object_type: str,
        object_id: str,
        creator_tenant_id: int,
        operator_id: int,
        operator_tenant_id: int,
        explicit: Optional[bool] = None,
    ) -> List[int]:
        """High-level orchestrator for F017 "share at creation" (D6).

        Called right after ``OwnerService.write_owner_tuple`` in each resource
        create flow. Applies the Root-only + default-fallback policy, writes
        shared_with tuples, flips ``{resource}.is_shared=True`` on success,
        and records audit_log ``RESOURCE_SHARE_ENABLE``.

        Returns the list of Child tenant_ids the resource was actually shared
        with (empty when creator is Child / explicit=False / default=false /
        no active children).
        """
        # Child creators never fan out — share is a Root-only concept.
        if creator_tenant_id != ROOT_TENANT_ID:
            return []

        if explicit is None:
            # Defaulting: ``Root.share_default_to_children`` from F011.
            root = await TenantDao.aget_by_id(ROOT_TENANT_ID)
            if not (root and root.share_default_to_children):
                return []
        elif not explicit:
            return []

        try:
            shared_children = await cls.enable_sharing(
                object_type, object_id, root_tenant_id=ROOT_TENANT_ID,
            )
        except FGAClientError as e:
            logger.warning(
                '[F017] share_on_create.enable_sharing failed for %s:%s: %s',
                object_type, object_id, e,
            )
            return []

        if not shared_children:
            return []

        try:
            await cls.set_is_shared(object_type, object_id, True)
        except Exception as e:
            logger.warning(
                '[F017] share_on_create.set_is_shared failed for %s:%s: %s',
                object_type, object_id, e,
            )

        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=ROOT_TENANT_ID,
                operator_id=operator_id,
                operator_tenant_id=operator_tenant_id,
                action=TenantAuditAction.RESOURCE_SHARE_ENABLE.value,
                target_type=object_type,
                target_id=object_id,
                metadata={'shared_children': shared_children, 'trigger': 'create'},
            )
        except Exception as e:
            logger.warning(
                '[F017] share_on_create.audit_log failed for %s:%s: %s',
                object_type, object_id, e,
            )

        return shared_children

    @classmethod
    def share_on_create_sync(
        cls,
        object_type: str,
        object_id: str,
        creator_tenant_id: int,
        operator_id: int,
        operator_tenant_id: int,
        explicit: Optional[bool] = None,
    ) -> List[int]:
        """Sync wrapper for ``share_on_create`` (FastAPI sync-endpoint path).

        Returns empty list + logs a warning on failure; never raises, so the
        Flow / Assistant creation endpoint does not abort when the share
        write fails — the resource itself has already been persisted.
        """
        try:
            return run_async_safe(cls.share_on_create(
                object_type, object_id,
                creator_tenant_id=creator_tenant_id,
                operator_id=operator_id,
                operator_tenant_id=operator_tenant_id,
                explicit=explicit,
            ))
        except Exception as e:
            logger.warning(
                '[F017] share_on_create_sync failed for %s:%s: %s',
                object_type, object_id, e,
            )
            return []

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _validate_type(object_type: str) -> None:
        if object_type not in SUPPORTED_SHAREABLE_TYPES:
            raise ValueError(
                f'Unsupported resource type for sharing: {object_type!r}; '
                f'supported={sorted(SUPPORTED_SHAREABLE_TYPES)}'
            )
