from __future__ import annotations

from bisheng.common.errcode.knowledge_space import SpaceFileChangeApproverUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.domain.services.permission_service import PermissionService


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
