"""SQLModel implementation of exact department business-domain bindings."""

from collections.abc import Sequence

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.shougang_portal_config.domain.models.department_business_domain import (
    DepartmentBusinessDomain,
)
from bisheng.shougang_portal_config.domain.repositories.interfaces.department_business_domain_repository import (
    DepartmentBusinessDomainBinding,
    DepartmentBusinessDomainRecord,
    DepartmentBusinessDomainRepository,
)


class DepartmentBusinessDomainRepositoryImpl(DepartmentBusinessDomainRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_record(model: DepartmentBusinessDomain) -> DepartmentBusinessDomainRecord:
        return DepartmentBusinessDomainRecord(
            id=int(model.id),
            tenant_id=int(model.tenant_id),
            department_id=int(model.department_id),
            business_domain_code=model.business_domain_code,
            create_user=model.create_user,
            create_time=model.create_time,
            update_time=model.update_time,
        )

    async def list_all(self) -> list[DepartmentBusinessDomainRecord]:
        with strict_tenant_filter():
            result = await self.session.exec(
                select(DepartmentBusinessDomain).order_by(
                    DepartmentBusinessDomain.department_id,
                    DepartmentBusinessDomain.business_domain_code,
                )
            )
        return [self._to_record(model) for model in result.all()]

    async def list_by_department_id(self, department_id: int) -> list[DepartmentBusinessDomainRecord]:
        return await self.list_by_department_ids([department_id])

    async def list_by_department_ids(
        self,
        department_ids: Sequence[int],
    ) -> list[DepartmentBusinessDomainRecord]:
        normalized_ids = sorted({int(value) for value in department_ids})
        if not normalized_ids:
            return []
        with strict_tenant_filter():
            result = await self.session.exec(
                select(DepartmentBusinessDomain)
                .where(col(DepartmentBusinessDomain.department_id).in_(normalized_ids))
                .order_by(
                    DepartmentBusinessDomain.department_id,
                    DepartmentBusinessDomain.business_domain_code,
                )
            )
        return [self._to_record(model) for model in result.all()]

    async def list_existing_department_ids(self, department_ids: Sequence[int]) -> set[int]:
        normalized_ids = sorted({int(value) for value in department_ids})
        if not normalized_ids:
            return set()
        # Selecting a Department column ensures the automatic tenant filter sees
        # the tenant-aware table even though this query has no ORM entity result.
        with strict_tenant_filter():
            result = await self.session.exec(select(Department.id).where(col(Department.id).in_(normalized_ids)))
        return {int(value) for value in result.all()}

    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        # Join through Department so a duplicated numeric department ID in a
        # different tenant can never become the user's recommendation feature.
        with strict_tenant_filter():
            result = await self.session.exec(
                select(Department.id)
                .join(UserDepartment, UserDepartment.department_id == Department.id)
                .where(
                    UserDepartment.user_id == int(user_id),
                    UserDepartment.is_primary == 1,
                )
                .order_by(Department.id)
            )
        return [int(value) for value in result.all()]

    async def delete_all(self) -> int:
        rows = await self._list_models_for_update()
        for row in rows:
            await self.session.delete(row)
        if rows:
            await self.session.flush()
        return len(rows)

    async def replace_all(
        self,
        bindings: Sequence[DepartmentBusinessDomainBinding],
        *,
        create_user: int | None,
    ) -> list[DepartmentBusinessDomainRecord]:
        await self.delete_all()
        models = [
            DepartmentBusinessDomain(
                department_id=int(binding.department_id),
                business_domain_code=binding.business_domain_code,
                create_user=create_user,
            )
            for binding in bindings
        ]
        if models:
            self.session.add_all(models)
            await self.session.flush()
        return [self._to_record(model) for model in models]

    async def _list_models_for_update(self) -> list[DepartmentBusinessDomain]:
        with strict_tenant_filter():
            result = await self.session.exec(select(DepartmentBusinessDomain).with_for_update())
        return list(result.all())
