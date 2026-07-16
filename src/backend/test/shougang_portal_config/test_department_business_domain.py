import pytest

from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    PortalDomainConfig,
)
from bisheng.shougang_portal_config.domain.services.department_business_domain_service import (
    DepartmentBusinessDomainService,
)


class _Repository:
    def __init__(self, primary_department_ids: list[int]):
        self.primary_department_ids = primary_department_ids
        self.queries: list[int] = []

    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        self.queries.append(user_id)
        return list(self.primary_department_ids)


def _domain(
    code: str,
    department_ids: list[int],
    *,
    enabled: bool = True,
) -> PortalDomainConfig:
    return PortalDomainConfig(
        name=code or "未编码域",
        code=code,
        department_ids=department_ids,
        space_ids=[],
        color="#fff",
        bg="#000",
        icon="Shield",
        enabled=enabled,
    )


async def test_unique_primary_department_returns_exact_domains_from_portal_config():
    repository = _Repository([10])
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(
        7,
        [
            _domain("SAFE", [10, 12]),
            _domain("PP", [10]),
            _domain("SAFE", [10]),
            _domain("OTHER", [11]),
        ],
    )

    assert codes == ["PP", "SAFE"]
    assert repository.queries == [7]


@pytest.mark.parametrize("primary_department_ids", [[], [10, 11]])
async def test_zero_or_multiple_primary_departments_disable_domain_feature(primary_department_ids):
    repository = _Repository(primary_department_ids)
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(7, [_domain("SAFE", [10, 11])])

    assert codes == []
    assert repository.queries == [7]


async def test_primary_department_does_not_inherit_parent_child_or_secondary_domains():
    repository = _Repository([10])
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(
        7,
        [
            _domain("PARENT", [9]),
            _domain("CHILD", [12]),
            _domain("SECONDARY", [11]),
        ],
    )

    assert codes == []


async def test_disabled_empty_or_invalid_domain_codes_are_not_recommendation_features():
    repository = _Repository([10])
    service = DepartmentBusinessDomainService(repository)

    codes = await service.get_user_business_domain_codes(
        7,
        [
            _domain("SAFE", [10], enabled=False),
            _domain("", [10]),
            _domain("bad-code!", [10]),
            _domain("PP", [10]),
        ],
    )

    assert codes == ["PP"]


def test_domain_department_pairs_uses_the_same_enabled_exact_mapping_rules():
    pairs = DepartmentBusinessDomainService.domain_department_pairs(
        [
            _domain("SAFE", [10, 11, 10]),
            _domain("PP", [10]),
            _domain("OLD", [12], enabled=False),
            _domain("bad-code!", [13]),
        ]
    )

    assert pairs == {(10, "SAFE"), (11, "SAFE"), (10, "PP")}
