from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, UserDepartment
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope


class DelegateScopeRepository:
    @classmethod
    async def list_for_credential(cls, credential_id: int) -> list[ApiCredentialDelegateScope]:
        async with get_async_db_session() as session:
            statement = select(ApiCredentialDelegateScope).where(
                ApiCredentialDelegateScope.credential_id == credential_id
            )
            return list((await session.exec(statement)).all())

    @classmethod
    async def replace(
        cls,
        *,
        tenant_id: int,
        credential_id: int,
        entries: tuple[tuple[str, int], ...],
    ) -> None:
        async with get_async_db_session() as session:
            async with session.begin():
                await session.exec(
                    delete(ApiCredentialDelegateScope).where(
                        ApiCredentialDelegateScope.credential_id == credential_id
                    )
                )
                for subject_type, subject_id in entries:
                    session.add(
                        ApiCredentialDelegateScope(
                            tenant_id=tenant_id,
                            credential_id=credential_id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )

    @classmethod
    async def get_department(cls, department_id: int) -> Department | None:
        async with get_async_db_session() as session:
            return (
                await session.exec(select(Department).where(Department.id == department_id))
            ).first()

    @classmethod
    async def target_in_departments(cls, user_id: int, department_ids: tuple[int, ...]) -> bool:
        if not department_ids:
            return False
        async with get_async_db_session() as session:
            scoped = list(
                (
                    await session.exec(
                        select(Department).where(Department.id.in_(department_ids))
                    )
                ).all()
            )
            memberships = list(
                (
                    await session.exec(
                        select(Department)
                        .join(UserDepartment, UserDepartment.department_id == Department.id)
                        .where(UserDepartment.user_id == user_id)
                    )
                ).all()
            )
        return any(member.path.startswith(scope.path) for scope in scoped for member in memberships)
