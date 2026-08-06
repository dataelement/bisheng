"""F017 Root-to-Child resource sharing application service.

The service expresses sharing through the permission application's relation
protocol. Storage-model encoding and the authorization backend stay inside the
permission module.

Usage scenarios:

1. ``enable_sharing / disable_sharing`` — toggle share on a single Root
   resource; fan out writes/deletes over all active Children.
2. ``distribute_to_child / revoke_from_child`` — on Child mount/unmount,
   grant/revoke the Tenant-level ``shared_to`` identity relation.
3. ``list_sharing_children`` — introspect which Children a given resource is
   currently shared with (UI / audit / unmount cleanup).

Permission backend failures surface as ``PermissionServiceUnavailableError``.
"""

from __future__ import annotations

import logging
from typing import Protocol

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
    PermissionServiceUnavailableError,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionSubject,
    get_permission_relation_api,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.repositories.resource_share_repository import (
    SharedResourceRepository,
)
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)

# Resource types that currently support Root-to-Child sharing fan-out.
# Business resources (knowledge_space / workflow / assistant / channel / tool)
# were removed in v2.6.0-beta2: owners now grant access through ReBAC (per-user)
# instead of bulk Root→Child default-share. Only llm_server keeps the
# write path because it backs F020 platform-level LLM inheritance.
# Must stay aligned with the permission catalog.
SUPPORTED_SHAREABLE_TYPES: set[str] = {
    "llm_server",
}

# Resource types that historically wrote ``shared_with`` relations and may
# still have stale permission data. Used by the revoke-side APIs
# (disable_sharing / list_sharing_children / set_is_shared) so the cleanup
# script can purge legacy tuples without re-enabling business-resource sharing.
LEGACY_SHAREABLE_TYPES: set[str] = SUPPORTED_SHAREABLE_TYPES | {
    "knowledge_space",
    "workflow",
    "assistant",
    "channel",
    "tool",
}

F048_SHARED_ACTIONS: dict[str, frozenset[str]] = {
    "knowledge_space": frozenset({"visible", "download"}),
    "knowledge_library": frozenset({"visible", "use"}),
    "folder": frozenset({"visible", "download"}),
    "knowledge_file": frozenset({"visible", "download"}),
    "workflow": frozenset({"visible", "use"}),
    "assistant": frozenset({"visible", "use"}),
    "tool": frozenset({"visible", "use"}),
    "channel": frozenset({"visible"}),
}


class SharedSystemPermissionPort(Protocol):
    async def check_system_action(
        self,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> bool: ...


class TenantShareTopologyPort(Protocol):
    async def is_root_to_child(
        self,
        owner_tenant_id: int,
        child_tenant_id: int,
    ) -> bool: ...


class ResourceShareService:
    """Root-to-Child resource sharing through the permission application."""

    def __init__(
        self,
        *,
        repository: SharedResourceRepository | None = None,
        system_permission: SharedSystemPermissionPort | None = None,
        topology: TenantShareTopologyPort | None = None,
    ) -> None:
        self._repository = repository
        self._system_permission = system_permission
        self._topology = topology

    async def resolve_shared_target(
        self,
        *,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> VerifiedPermissionTarget:
        """Resolve only a system-authorized Root resource by its exact ID."""

        allowed_actions = F048_SHARED_ACTIONS.get(resource_type)
        if allowed_actions is None or action not in allowed_actions:
            raise InvalidCatalogActionError(msg=f"Shared {resource_type} does not support action: {action}")
        if self._repository is None or self._system_permission is None or self._topology is None:
            raise RuntimeError("F048 shared resource adapters are not configured")

        allowed = await self._system_permission.check_system_action(
            actor,
            resource_type,
            resource_id,
            action,
        )
        if not allowed:
            raise PermissionInvalidResourceError()

        rows = await self._repository.get_authorized_by_ids(
            owner_tenant_id=ROOT_TENANT_ID,
            resource_type=resource_type,
            resource_ids=(resource_id,),
        )
        if len(rows) != 1:
            raise PermissionInvalidResourceError()
        row = rows[0]
        topology_valid = await self._topology.is_root_to_child(
            row.owner_tenant_id,
            actor.current_tenant_id,
        )
        if (
            row.resource_id != resource_id
            or row.status != "ACTIVE"
            or not row.shareable
            or row.owner_tenant_id == actor.current_tenant_id
            or not topology_valid
        ):
            raise PermissionInvalidResourceError()

        return VerifiedPermissionTarget.from_business_service(
            tenant_id=row.owner_tenant_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            resource_version=row.permission_version,
            context_version=row.context_version,
        )

    # ── Resource-level sharing (shared_with) ─────────────────────

    @classmethod
    async def enable_sharing(
        cls,
        object_type: str,
        object_id: str,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> list[int]:
        """Write ``{object_type}:{object_id}#shared_with → tenant:{child}`` for
        each active Child. Returns the list of child_ids that received the
        tuple (empty if no active Children).

        Raises ValueError for unsupported resource types.
        """
        cls._validate_type(object_type)
        permissions = await get_permission_relation_api()

        child_ids = await TenantDao.aget_children_ids_active(root_tenant_id)
        if not child_ids:
            logger.info("[F017] No active children to share %s:%s", object_type, object_id)
            return []

        # Read the current set first and only write the gap. This keeps sharing idempotent
        # under retries and safe when called concurrently with a freshly-
        # mounted Child whose backfill already wrote a partial tuple set.
        resource = PermissionObject(object_type, str(object_id))
        existing = await permissions.list_subject_ids(
            resource=resource,
            relation="shared_with",
            subject_type="tenant",
        )
        already_shared_tenants = set(existing)
        grants = tuple(
            PermissionRelation(
                subject=PermissionSubject("tenant", str(child_id)),
                relation="shared_with",
                resource=resource,
            )
            for child_id in child_ids
            if str(child_id) not in already_shared_tenants
        )
        if not grants:
            logger.info(
                "[F017] %s:%s already shared with all %d children — no-op", object_type, object_id, len(child_ids)
            )
            return child_ids
        await permissions.grant(grants)
        logger.info(
            "[F017] Shared %s:%s with %d new children (total %d)", object_type, object_id, len(grants), len(child_ids)
        )
        return child_ids

    @classmethod
    async def disable_sharing(
        cls,
        object_type: str,
        object_id: str,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> list[int]:
        """Delete all ``{object_type}:{object_id}#shared_with → tenant:*`` tuples.

        Returns the list of child_ids whose tuples were revoked. Reads existing
        tuples first to produce a precise delete list (safe even if some
        Children were added mid-flight).
        """
        cls._validate_type(object_type, legacy=True)
        permissions = await get_permission_relation_api()

        resource = PermissionObject(object_type, str(object_id))
        existing = await permissions.list_subject_ids(
            resource=resource,
            relation="shared_with",
            subject_type="tenant",
        )
        revokes = tuple(
            PermissionRelation(
                subject=PermissionSubject("tenant", tenant_id),
                relation="shared_with",
                resource=resource,
            )
            for tenant_id in existing
        )
        if not revokes:
            return []

        await permissions.revoke(revokes)
        revoked = [int(tenant_id) for tenant_id in existing if tenant_id.isdigit()]
        logger.info("[F017] Unshared %s:%s from %d children", object_type, object_id, len(revoked))
        return revoked

    @classmethod
    async def list_sharing_children(
        cls,
        object_type: str,
        object_id: str,
    ) -> list[int]:
        """Return the child tenant IDs this resource is shared with.

        Reads the permission service (ground truth), not the ``is_shared`` DB
        projection used to accelerate list queries.
        """
        cls._validate_type(object_type, legacy=True)
        permissions = await get_permission_relation_api()
        existing = await permissions.list_subject_ids(
            resource=PermissionObject(object_type, str(object_id)),
            relation="shared_with",
            subject_type="tenant",
        )
        return [int(tenant_id) for tenant_id in existing if tenant_id.isdigit()]

    # ── Tenant-level distribution (shared_to) ────────────────────

    @classmethod
    async def distribute_to_child(
        cls,
        child_id: int,
        root_tenant_id: int = ROOT_TENANT_ID,
    ) -> None:
        """Write ``tenant:{child_id}#shared_to → tenant:{root_tenant_id}``.

        Called on Child mount (``TenantMountService._on_child_mounted``) to
        preserve the explicit Root-to-Child identity fact. Idempotent at the
        permission service (duplicate grants are no-ops).
        """
        permissions = await get_permission_relation_api()
        await permissions.grant(
            (
                PermissionRelation(
                    subject=PermissionSubject("tenant", str(child_id)),
                    relation="shared_to",
                    resource=PermissionObject("tenant", str(root_tenant_id)),
                ),
            )
        )
        logger.info("[F017] distribute_to_child: tenant:%s → shared_to tenant:%s", child_id, root_tenant_id)

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
        permissions = await get_permission_relation_api()
        await permissions.revoke(
            (
                PermissionRelation(
                    subject=PermissionSubject("tenant", str(child_id)),
                    relation="shared_to",
                    resource=PermissionObject("tenant", str(root_tenant_id)),
                ),
            )
        )
        logger.info("[F017] revoke_from_child: tenant:%s → shared_to tenant:%s", child_id, root_tenant_id)

    # ── is_shared DB projection for list/UI speed ─────────────────

    @classmethod
    async def set_is_shared(
        cls,
        object_type: str,
        object_id: str,
        is_shared: bool,
    ) -> None:
        """Flip ``{resource}.is_shared`` in the backing table for the 5 types.

        The permission service is the source of truth for access decisions;
        this column is a denormalized projection for list queries.
        """
        cls._validate_type(object_type, legacy=True)
        if object_type == "knowledge_space":
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

            rows = await KnowledgeDao.aget_list_by_ids([int(object_id)])
            if rows:
                row = rows[0]
                row.is_shared = is_shared
                await KnowledgeDao.aupdate_one(row)
            return
        if object_type == "workflow":
            from bisheng.database.models.flow import FlowDao

            row = await FlowDao.aget_flow_by_id(object_id)
            if row is not None:
                row.is_shared = is_shared
                await FlowDao.aupdate_flow(row)
            return
        if object_type == "assistant":
            # AssistantDao exposes sync ``update_assistant``; wrap in a thread
            # so we don't block the event loop when called from async paths.
            import asyncio as _asyncio

            from bisheng.database.models.assistant import AssistantDao

            row = await AssistantDao.aget_one_assistant(object_id)
            if row is not None:
                row.is_shared = is_shared
                await _asyncio.to_thread(AssistantDao.update_assistant, row)
            return
        if object_type == "channel":
            from sqlmodel import select

            from bisheng.channel.domain.models.channel import Channel
            from bisheng.core.database import get_async_db_session

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
        if object_type == "tool":
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
        explicit: bool | None = None,
    ) -> list[int]:
        """High-level orchestrator for F017 "share at creation" (D6).

        Called after the resource's F048 creation projection. Applies the
        Root-only + default-fallback policy, writes the independent
        ``shared_with`` system relation, flips ``{resource}.is_shared=True``
        on success, and records audit_log ``RESOURCE_SHARE_ENABLE``.

        Returns the list of Child tenant_ids the resource was actually shared
        with (empty when creator is Child / explicit=False / default=false /
        no active children / object_type not in SUPPORTED_SHAREABLE_TYPES).
        """
        # v2.6.0-beta2: business resources no longer fan out — silently noop
        # so any leftover caller in a stale plugin keeps working without
        # crashing on the now-stricter _validate_type check below.
        if object_type not in SUPPORTED_SHAREABLE_TYPES:
            return []

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
                object_type,
                object_id,
                root_tenant_id=ROOT_TENANT_ID,
            )
        except PermissionServiceUnavailableError as e:
            logger.warning(
                "[F017] share_on_create.enable_sharing failed for %s:%s: %s",
                object_type,
                object_id,
                e,
            )
            return []

        if not shared_children:
            return []

        try:
            await cls.set_is_shared(object_type, object_id, True)
        except Exception as e:
            logger.warning(
                "[F017] share_on_create.set_is_shared failed for %s:%s: %s",
                object_type,
                object_id,
                e,
            )

        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=ROOT_TENANT_ID,
                operator_id=operator_id,
                operator_tenant_id=operator_tenant_id,
                action=TenantAuditAction.RESOURCE_SHARE_ENABLE.value,
                target_type=object_type,
                target_id=object_id,
                metadata={"shared_children": shared_children, "trigger": "create"},
            )
        except Exception as e:
            logger.warning(
                "[F017] share_on_create.audit_log failed for %s:%s: %s",
                object_type,
                object_id,
                e,
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
        explicit: bool | None = None,
    ) -> list[int]:
        """Sync wrapper for ``share_on_create`` (FastAPI sync-endpoint path).

        Returns empty list + logs a warning on failure; never raises, so the
        Flow / Assistant creation endpoint does not abort when the share
        write fails — the resource itself has already been persisted.
        """
        try:
            return run_async_safe(
                cls.share_on_create(
                    object_type,
                    object_id,
                    creator_tenant_id=creator_tenant_id,
                    operator_id=operator_id,
                    operator_tenant_id=operator_tenant_id,
                    explicit=explicit,
                )
            )
        except Exception as e:
            logger.warning(
                "[F017] share_on_create_sync failed for %s:%s: %s",
                object_type,
                object_id,
                e,
            )
            return []

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _validate_type(object_type: str, *, legacy: bool = False) -> None:
        """Reject unknown object types.

        ``legacy=True`` widens the allow-list to historically shareable
        business resources so the cleanup path (disable_sharing /
        list_sharing_children / set_is_shared) can purge stale tuples
        without re-introducing the write path.
        """
        allowed = LEGACY_SHAREABLE_TYPES if legacy else SUPPORTED_SHAREABLE_TYPES
        if object_type not in allowed:
            raise ValueError(f"Unsupported resource type for sharing: {object_type!r}; supported={sorted(allowed)}")
