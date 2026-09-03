"""F050 permission configuration before a business resource exists."""

from __future__ import annotations

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.ports import (
    ProspectiveGrantRuntimePort,
    ProspectiveGrantSubjectDirectoryPort,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class ProspectiveGrantApplication:
    """Read owner grant policy and tenant candidates without inventing a target."""

    def __init__(
        self,
        *,
        runtime: ProspectiveGrantRuntimePort,
        subjects: ProspectiveGrantSubjectDirectoryPort,
    ) -> None:
        self._runtime = runtime
        self._subjects = subjects

    async def get_context(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
    ) -> dict[str, object]:
        self._require_tenant_scope(actor, tenant_id)
        del resource_type
        catalog, models = await self._runtime.prospective_owner_grantable_models()
        return {
            "catalog_release_id": catalog.release_id,
            "can_configure_initial_permissions": bool(models),
            "grantable_models": [
                {
                    "key": model.snapshot.model_key,
                    "name": model.name,
                    "level": model.snapshot.derived_level,
                    "active": model.snapshot.active,
                }
                for model in models
            ],
        }

    async def list_users(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        self._require_tenant_scope(actor, tenant_id)
        return await self._subjects.list_users(
            tenant_id=tenant_id,
            resource_type=resource_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

    async def list_user_groups(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        self._require_tenant_scope(actor, tenant_id)
        return await self._subjects.list_user_groups(
            tenant_id=tenant_id,
            resource_type=resource_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

    async def list_department_children(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
        parent_id: int | None,
    ) -> list[dict[str, object]]:
        self._require_tenant_scope(actor, tenant_id)
        return await self._subjects.list_department_children(
            tenant_id=tenant_id,
            resource_type=resource_type,
            parent_id=parent_id,
        )

    async def search_departments(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        limit: int,
    ) -> dict[str, object]:
        self._require_tenant_scope(actor, tenant_id)
        return await self._subjects.search_departments(
            tenant_id=tenant_id,
            resource_type=resource_type,
            keyword=keyword,
            limit=limit,
        )

    async def get_department_path(
        self,
        *,
        actor: PermissionActor,
        tenant_id: int,
        resource_type: str,
        department_id: int,
    ) -> dict[str, object]:
        self._require_tenant_scope(actor, tenant_id)
        return await self._subjects.get_department_path(
            tenant_id=tenant_id,
            resource_type=resource_type,
            department_id=department_id,
        )

    @staticmethod
    def _require_tenant_scope(actor: PermissionActor, tenant_id: int) -> None:
        if (
            tenant_id != actor.current_tenant_id
            and not actor.super_admin
            and tenant_id not in actor.tenant_admin_tenant_ids
        ):
            raise PermissionDeniedError()
