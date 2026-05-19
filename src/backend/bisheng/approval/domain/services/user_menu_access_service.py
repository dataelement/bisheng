from __future__ import annotations

from bisheng.approval.domain.models.user_menu_access import UserMenuAccess
from bisheng.approval.domain.repositories.user_menu_access_repository import (
    UserMenuAccessRepository,
)
class UserMenuAccessService:
    _PARENT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
        'home': ('workstation',),
        'apps': ('workstation',),
        'subscription': ('workstation',),
        'knowledge_space': ('workstation',),
        'build': ('admin',),
        'knowledge': ('admin',),
        'model': ('admin',),
        'evaluation': ('admin',),
        'mark_task': ('admin',),
        'board': ('admin',),
        'create_app': ('admin', 'build'),
        'create_knowledge': ('admin', 'knowledge'),
    }

    @classmethod
    def expand_menu_keys_with_dependencies(cls, menu_keys: list[str] | set[str] | tuple[str, ...]) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()

        def _visit(menu_key: str) -> None:
            normalized_key = str(menu_key or '').strip()
            if not normalized_key or normalized_key in seen:
                return
            seen.add(normalized_key)
            for parent in cls._PARENT_DEPENDENCIES.get(normalized_key, ()):
                _visit(parent)
            resolved.append(normalized_key)

        for key in menu_keys:
            _visit(key)
        return resolved

    @classmethod
    async def list_effective_menu_grants(cls, tenant_id: int, user_id: int) -> list[str]:
        active_keys = await UserMenuAccessRepository.list_active_menu_keys(tenant_id, user_id)
        return cls.expand_menu_keys_with_dependencies(active_keys)

    @classmethod
    async def grant_menu_access(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        menu_key: str,
        menu_name: str | None,
        grant_source: str,
        grant_instance_id: int | None = None,
    ) -> list[UserMenuAccess]:
        rows: list[UserMenuAccess] = []
        for key in cls.expand_menu_keys_with_dependencies([menu_key]):
            rows.append(
                await UserMenuAccessRepository.upsert_active_grant(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    menu_key=key,
                    menu_name=menu_name if key == menu_key else None,
                    grant_source=grant_source,
                    grant_instance_id=grant_instance_id,
                )
            )
        return rows

    @classmethod
    async def revoke_menu_access(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        menu_key: str,
        grant_source: str,
        revoked_by_user_id: int,
        revoked_reason: str | None = None,
    ) -> list[UserMenuAccess]:
        rows: list[UserMenuAccess] = []
        for key in reversed(cls.expand_menu_keys_with_dependencies([menu_key])):
            row = await UserMenuAccessRepository.revoke_grant(
                tenant_id=tenant_id,
                user_id=user_id,
                menu_key=key,
                grant_source=grant_source,
                revoked_by_user_id=revoked_by_user_id,
                revoked_reason=revoked_reason if key == menu_key else None,
            )
            if row:
                rows.append(row)
        return rows
