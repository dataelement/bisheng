from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bisheng.common.errcode.knowledge_space import SpaceFileChangeApproverUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.services.permission_service import PermissionService


@dataclass(frozen=True, slots=True)
class KnowledgeSpaceFileChangeApproverReconciliationTarget:
    """Knowledge-owned input for one application-level F025 reconciliation."""

    instance_id: int
    approver_user_ids: tuple[int, ...]


@runtime_checkable
class KnowledgeSpaceFileChangeApproverResolverPort(Protocol):
    """Public resolver boundary consumed by permission-event orchestration."""

    async def resolve_reconciliation_targets(
        self,
        *,
        tenant_id: int,
        space_id: int,
    ) -> list[KnowledgeSpaceFileChangeApproverReconciliationTarget]: ...


class KnowledgeSpaceFileChangeApproverResolver:
    """Strictly resolve current F046 approvers from authoritative ReBAC data."""

    _APPROVER_RELATIONS = ("owner", "manager")

    @classmethod
    async def resolve_approver_user_ids(
        cls,
        *,
        tenant_id: int,
        space_id: int,
        applicant_user_id: int | None,
    ) -> list[int]:
        try:
            current_tenant_id = get_current_tenant_id()
            if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
                raise RuntimeError("a matching tenant context is required for file change approvers")

            resolved = await PermissionService.resolve_resource_relation_user_ids_strict(
                tenant_id=int(tenant_id),
                object_type="knowledge_space",
                object_id=str(space_id),
                relations=cls._APPROVER_RELATIONS,
            )
            # Knowledge-space creators are permanent owners in the permission
            # model even while their best-effort OpenFGA owner tuple is waiting
            # for compensation. Keep the strict OpenFGA read above as the
            # availability boundary, then merge the permission service result.
            creator_ids = await PermissionService.resolve_permanent_creator_user_ids_strict(
                tenant_id=int(tenant_id),
                object_type="knowledge_space",
                object_id=str(space_id),
            )
            resolved = set(resolved).union(creator_ids)
            excluded_user_id = int(applicant_user_id) if applicant_user_id is not None else None
            return sorted(
                {int(user_id) for user_id in resolved if excluded_user_id is None or int(user_id) != excluded_user_id}
            )
        except SpaceFileChangeApproverUnavailableError:
            raise
        except Exception as exc:
            raise SpaceFileChangeApproverUnavailableError(exc) from exc

    @classmethod
    async def is_current_approver(
        cls,
        *,
        tenant_id: int,
        space_id: int,
        user_id: int,
    ) -> bool:
        approver_user_ids = await cls.resolve_approver_user_ids(
            tenant_id=tenant_id,
            space_id=space_id,
            applicant_user_id=None,
        )
        return int(user_id) in approver_user_ids

    @classmethod
    async def resolve_reconciliation_targets(
        cls,
        *,
        tenant_id: int,
        space_id: int,
    ) -> list[KnowledgeSpaceFileChangeApproverReconciliationTarget]:
        """Resolve a bounded Knowledge-owned page without exposing business rows."""

        try:
            normalized_tenant_id = int(tenant_id)
            normalized_space_id = int(space_id)
            current_tenant_id = get_current_tenant_id()
            if (
                normalized_tenant_id <= 0
                or normalized_space_id <= 0
                or current_tenant_id is None
                or int(current_tenant_id) != normalized_tenant_id
            ):
                raise RuntimeError("a matching tenant context is required for file change reconciliation")

            from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
                KnowledgeSpaceFileChangeRequestRepository,
            )

            async with get_async_db_session() as session:
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                instance_ids = await repository.list_reconcilable_instance_ids(
                    tenant_id=normalized_tenant_id,
                    space_ids=[normalized_space_id],
                    limit=KnowledgeSpaceFileChangeRequestRepository.MAX_RECONCILE_BATCH_SIZE,
                )
                requests = [
                    await repository.get_by_approval_instance_id(
                        tenant_id=normalized_tenant_id,
                        approval_instance_id=int(instance_id),
                    )
                    for instance_id in instance_ids
                ]

            targets: list[KnowledgeSpaceFileChangeApproverReconciliationTarget] = []
            for instance_id, request in zip(instance_ids, requests, strict=True):
                # A candidate may become terminal between discovery and the
                # Knowledge read. Skipping a vanished row cannot erase F025 tasks.
                if request is None:
                    continue
                approver_user_ids = await cls.resolve_approver_user_ids(
                    tenant_id=normalized_tenant_id,
                    space_id=int(request.space_id),
                    applicant_user_id=int(request.applicant_user_id),
                )
                targets.append(
                    KnowledgeSpaceFileChangeApproverReconciliationTarget(
                        instance_id=int(instance_id),
                        approver_user_ids=tuple(approver_user_ids),
                    )
                )
            return targets
        except SpaceFileChangeApproverUnavailableError:
            raise
        except Exception as exc:
            raise SpaceFileChangeApproverUnavailableError(exc) from exc


__all__ = [
    "KnowledgeSpaceFileChangeApproverReconciliationTarget",
    "KnowledgeSpaceFileChangeApproverResolver",
    "KnowledgeSpaceFileChangeApproverResolverPort",
]
