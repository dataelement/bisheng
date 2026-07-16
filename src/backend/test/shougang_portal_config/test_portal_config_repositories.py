from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
    PortalRecommendationRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_repository import (
    PortalRecommendationProjectionUpsert,
)
from bisheng.shougang_portal_config.domain.models.department_business_domain import (
    DepartmentBusinessDomain,
)
from bisheng.shougang_portal_config.domain.repositories.implementations.department_business_domain_repository_impl import (
    DepartmentBusinessDomainRepositoryImpl,
)
from bisheng.shougang_portal_config.domain.repositories.implementations.portal_admin_config_repository_impl import (
    PortalAdminConfigRepositoryImpl,
)
from bisheng.shougang_portal_config.domain.repositories.interfaces.department_business_domain_repository import (
    DepartmentBusinessDomainBinding,
)
from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
    portal_admin_config_physical_key,
)


def test_portal_config_physical_key_is_backward_compatible_and_tenant_scoped():
    assert portal_admin_config_physical_key(1) == "shougang_portal_config"
    assert portal_admin_config_physical_key(5) == "shougang_portal_config:t:5"
    with pytest.raises(ValueError):
        portal_admin_config_physical_key(0)


async def test_config_repository_flushes_without_committing():
    session = MagicMock()
    session.exec = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = PortalAdminConfigRepositoryImpl(session)

    await repository.write_value(5, "{}")

    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_binding_repository_uses_strict_tenant_even_when_root_is_visible(async_db_session):
    register_tenant_filter_events()
    with bypass_tenant_filter():
        async_db_session.add_all(
            [
                DepartmentBusinessDomain(
                    tenant_id=1,
                    department_id=10,
                    business_domain_code="ROOT",
                ),
                DepartmentBusinessDomain(
                    tenant_id=5,
                    department_id=10,
                    business_domain_code="CHILD",
                ),
            ]
        )
        await async_db_session.commit()

    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({1, 5}))
    try:
        repository = DepartmentBusinessDomainRepositoryImpl(async_db_session)

        rows = await repository.list_by_department_id(10)
        await repository.replace_all(
            [DepartmentBusinessDomainBinding(department_id=10, business_domain_code="NEXT")],
            create_user=7,
        )
        await async_db_session.commit()
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)

    assert [(row.tenant_id, row.business_domain_code) for row in rows] == [(5, "CHILD")]
    with bypass_tenant_filter():
        result = await async_db_session.exec(
            text(
                "SELECT tenant_id, business_domain_code FROM department_business_domain "
                "ORDER BY tenant_id, business_domain_code"
            )
        )
    assert result.all() == [(1, "ROOT"), (5, "NEXT")]


async def test_projection_repository_is_version_idempotent_and_strict_tenant(async_db_session):
    register_tenant_filter_events()
    now = datetime(2026, 7, 15, tzinfo=timezone.utc).replace(tzinfo=None)
    with bypass_tenant_filter():
        async_db_session.add_all(
            [
                PortalRecommendationFileProjection(
                    tenant_id=1,
                    file_id=20,
                    space_id=100,
                    permission_scope="inherited",
                    recommendable=1,
                    reason_code="eligible",
                    source_update_time=now,
                    projection_version=3,
                ),
                PortalRecommendationFileProjection(
                    tenant_id=5,
                    file_id=20,
                    space_id=500,
                    permission_scope="inherited",
                    recommendable=1,
                    reason_code="eligible",
                    source_update_time=now,
                    projection_version=2,
                ),
            ]
        )
        await async_db_session.commit()

    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({1, 5}))
    try:
        repository = PortalRecommendationRepositoryImpl(async_db_session)
        before = await repository.find_by_file_ids([20])
        stale_applied = await repository.upsert(
            PortalRecommendationProjectionUpsert(
                file_id=20,
                space_id=999,
                business_domain_code="SAFE",
                permission_scope="inherited",
                recommendable=True,
                reason_code="eligible",
                source_update_time=now,
                projection_version=2,
            )
        )
        fresh_applied = await repository.upsert(
            PortalRecommendationProjectionUpsert(
                file_id=20,
                space_id=501,
                business_domain_code=" safe ",
                permission_scope="INHERITED",
                recommendable=True,
                reason_code="ELIGIBLE",
                source_update_time=now,
                projection_version=4,
            )
        )
        await async_db_session.commit()
        after = await repository.find_by_file_ids([20])
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)

    assert [(row.tenant_id, row.space_id) for row in before] == [(5, 500)]
    assert stale_applied is False
    assert fresh_applied is True
    assert [(row.tenant_id, row.space_id, row.business_domain_code, row.projection_version) for row in after] == [
        (5, 501, "SAFE", 4)
    ]
    with bypass_tenant_filter():
        root_space = await async_db_session.exec(
            text("SELECT space_id FROM portal_recommendation_file_projection WHERE tenant_id = 1 AND file_id = 20")
        )
    assert root_space.scalar_one() == 100
