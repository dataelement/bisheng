"""Exact bound definition and WEB_MENU reads, separate from resource grants."""

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess


def _menu_statement(roles):
    return select(RoleAccess.third_id).where(
        RoleAccess.type == AccessType.WEB_MENU.value,
        or_(*(and_(RoleAccess.role_id == role.id, RoleAccess.tenant_id == role.tenant_id) for role in roles)),
    )


class EffectiveRoleRepository:
    @staticmethod
    async def assignable_definitions(business_tenant_ids: set[int], ancestor_ids: set[int]) -> list[Role]:
        if not business_tenant_ids:
            return []
        statement = (
            select(Role)
            .where(
                Role.id > 1,
                or_(Role.role_type == "global", Role.tenant_id.in_(business_tenant_ids)),
                or_(Role.department_id.is_(None), Role.department_id.in_(ancestor_ids)),
            )
            .order_by(Role.role_name)
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

    @staticmethod
    async def locked_definitions(session, role_ids: set[int]):
        if not role_ids:
            return []
        with bypass_tenant_filter():
            return list(
                (
                    await session.exec(select(Role).where(Role.id.in_(role_ids)).order_by(Role.id).with_for_update())
                ).all()
            )

    @staticmethod
    async def definitions(role_ids: set[int]) -> list[Role]:
        if not role_ids:
            return []
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(select(Role).where(Role.id.in_(role_ids)))).all())

    @staticmethod
    def definitions_sync(role_ids: set[int], *, session=None) -> list[Role]:
        if not role_ids:
            return []
        if session is None:
            with get_sync_db_session() as owned_session:
                return EffectiveRoleRepository.definitions_sync(role_ids, session=owned_session)
        with bypass_tenant_filter():
            return list(session.exec(select(Role).where(Role.id.in_(role_ids))).all())

    @staticmethod
    async def menu(roles) -> frozenset[str]:
        if not roles:
            return frozenset()
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return frozenset((await session.exec(_menu_statement(roles))).all())

    @staticmethod
    def menu_sync(roles, *, session=None) -> frozenset[str]:
        if not roles:
            return frozenset()
        if session is None:
            with get_sync_db_session() as owned_session:
                return EffectiveRoleRepository.menu_sync(roles, session=owned_session)
        with bypass_tenant_filter():
            return frozenset(session.exec(_menu_statement(roles)).all())
