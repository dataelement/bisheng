from types import SimpleNamespace

import pytest

from bisheng.shougang_portal_config.domain.services.department_business_domain_service import (
    DepartmentBusinessDomainService,
)


class _Repository:
    def __init__(self, primary_department_ids: list[int], codes_by_department: dict[int, list[str]]):
        self.primary_department_ids = primary_department_ids
        self.codes_by_department = codes_by_department
        self.binding_queries: list[int] = []

    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        assert user_id == 7
        return list(self.primary_department_ids)

    async def list_by_department_id(self, department_id: int):
        self.binding_queries.append(department_id)
        return [SimpleNamespace(business_domain_code=code) for code in self.codes_by_department.get(department_id, [])]


async def test_unique_primary_department_returns_its_exact_deduplicated_bindings():
    repository = _Repository([10], {10: ["SAFE", "PP", "SAFE"], 11: ["SHOULD_NOT_READ"]})
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(7)

    assert codes == ["PP", "SAFE"]
    assert repository.binding_queries == [10]


@pytest.mark.parametrize("primary_department_ids", [[], [10, 11]])
async def test_zero_or_multiple_primary_departments_disable_domain_feature(primary_department_ids):
    repository = _Repository(primary_department_ids, {10: ["SAFE"], 11: ["PP"]})
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(7)

    assert codes == []
    assert repository.binding_queries == []


async def test_primary_department_without_binding_does_not_fall_back_to_secondary_department():
    repository = _Repository([10], {11: ["PP"]})
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(7)

    assert codes == []
    assert repository.binding_queries == [10]
