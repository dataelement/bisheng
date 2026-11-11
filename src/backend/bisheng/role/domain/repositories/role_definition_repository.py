"""Definition-owner transactions, after RoleService has authorized the target."""

from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.errcode.role import RoleNameDuplicateError, RoleNotFoundError, RolePolicyUnavailableError
from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess


class RoleDefinitionRepository:
    @staticmethod
    async def replace_menu(session, role_id: int, menu_ids: list[str], *, owner_tenant_id: int):
        with tenant_execution_scope(owner_tenant_id), strict_tenant_filter():
            await session.exec(
                delete(RoleAccess).where(
                    RoleAccess.tenant_id == owner_tenant_id,
                    RoleAccess.role_id == role_id,
                    RoleAccess.type == AccessType.WEB_MENU.value,
                )
            )
            session.add_all(
                [
                    RoleAccess(role_id=role_id, third_id=key, type=AccessType.WEB_MENU.value, tenant_id=owner_tenant_id)
                    for key in dict.fromkeys(menu_ids)
                ]
            )

    @staticmethod
    async def _check_name(session, role: Role, changes: dict):
        statement = select(Role.id).where(
            Role.id != role.id,
            Role.role_type == role.role_type,
            Role.role_name == changes.get("role_name", role.role_name),
            Role.department_id == changes.get("department_id", role.department_id),
        )
        if (await session.exec(statement)).first() is not None:
            raise RoleNameDuplicateError()

    @classmethod
    async def create(cls, role: Role, menu_ids: list[str] | None = None) -> Role:
        with tenant_execution_scope(int(role.tenant_id)), strict_tenant_filter():
            try:
                async with get_async_db_session() as session:
                    await cls._check_name(session, role, {})
                    session.add(role)
                    await session.flush()
                    if menu_ids is not None:
                        await cls.replace_menu(session, role.id, menu_ids, owner_tenant_id=int(role.tenant_id))
                    await session.commit()
                    await session.refresh(role)
                    return role
            except IntegrityError as exc:
                raise RoleNameDuplicateError() from exc

    @classmethod
    async def update(
        cls, verified_role: Role, changes: dict, menu_ids: list[str] | None = None, *, operator_id=None
    ) -> Role:
        with tenant_execution_scope(int(verified_role.tenant_id)), strict_tenant_filter():
            try:
                async with get_async_db_session() as session:
                    role = (
                        await session.exec(select(Role).where(Role.id == verified_role.id).with_for_update())
                    ).first()
                    if role is None:
                        raise RoleNotFoundError()
                    if (role.role_type, role.department_id) != (verified_role.role_type, verified_role.department_id):
                        raise RolePolicyUnavailableError()
                    await cls._check_name(session, role, changes)
                    affected = []
                    if "department_id" in changes:
                        from bisheng.user.application.policy_bindings import (
                            affected_policy_users,
                            retire_invalid_policy_bindings,
                        )

                        affected = await affected_policy_users(session=session, role_ids=[role.id])
                        await retire_invalid_policy_bindings(
                            affected, session=session, restrict_role_ids={role.id}, operator_id=operator_id
                        )
                    for key, value in changes.items():
                        setattr(role, key, value)
                    role.update_time = func.now()
                    session.add(role)
                    if menu_ids is not None:
                        await cls.replace_menu(session, role.id, menu_ids, owner_tenant_id=int(role.tenant_id))
                    if "department_id" in changes:
                        from bisheng.user.application.policy_bindings import (
                            affected_policy_users,
                            retire_invalid_policy_bindings,
                        )

                        affected = await affected_policy_users(session=session, role_ids=[role.id])
                        await retire_invalid_policy_bindings(
                            affected, session=session, restrict_role_ids={role.id}, operator_id=operator_id
                        )
                    await session.commit()
                    await session.refresh(role)
                    return role
            except IntegrityError as exc:
                raise RoleNameDuplicateError() from exc

    @staticmethod
    async def menu(verified_role: Role) -> list[RoleAccess]:
        with tenant_execution_scope(int(verified_role.tenant_id)), strict_tenant_filter():
            async with get_async_db_session() as session:
                return list(
                    (
                        await session.exec(
                            select(RoleAccess).where(
                                RoleAccess.role_id == verified_role.id, RoleAccess.type == AccessType.WEB_MENU.value
                            )
                        )
                    ).all()
                )

    @staticmethod
    async def delete(verified_role, *, operator_id=None):
        from bisheng.user.application.policy_bindings import retire_role_bindings

        with tenant_execution_scope(int(verified_role.tenant_id)), strict_tenant_filter():
            async with get_async_db_session() as session:
                role = (
                    await session.exec(
                        select(Role)
                        .where(Role.id == verified_role.id, Role.tenant_id == verified_role.tenant_id)
                        .with_for_update()
                    )
                ).first()
                if role is None:
                    raise RoleNotFoundError()
                await retire_role_bindings(role.id, session=session, operator_id=operator_id)
                await session.execute(
                    delete(RoleAccess).where(RoleAccess.tenant_id == role.tenant_id, RoleAccess.role_id == role.id)
                )
                await session.delete(role)
                await session.commit()
