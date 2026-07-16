from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, text

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
from bisheng.shougang_portal_config.domain.repositories.implementations.portal_admin_config_repository_impl import (
    PortalAdminConfigRepositoryImpl,
)
from bisheng.shougang_portal_config.domain.repositories.implementations.portal_department_repository_impl import (
    PortalDepartmentRepositoryImpl,
    normalize_department_id_rows,
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


async def test_portal_department_repository_uses_strict_tenant_and_primary_membership(async_db_session):
    register_tenant_filter_events()
    with bypass_tenant_filter():
        await async_db_session.exec(
            text(
                "INSERT INTO department (id, dept_id, name, tenant_id) VALUES "
                "(10, 'ROOT-D10', 'root', 1), "
                "(50, 'CHILD-D50', 'child-primary', 5), "
                "(51, 'CHILD-D51', 'child-secondary', 5)"
            )
        )
        await async_db_session.exec(
            text(
                "INSERT INTO user_department (user_id, department_id, is_primary) VALUES "
                "(7, 10, 1), (7, 50, 1), (7, 51, 0)"
            )
        )
        await async_db_session.commit()

    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({1, 5}))
    try:
        repository = PortalDepartmentRepositoryImpl(async_db_session)
        department_ids = await repository.list_primary_department_ids_for_user(7)
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)

    assert department_ids == [50]


def test_portal_department_repository_normalizes_driver_result_shapes():
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT 52")).one()

    assert normalize_department_id_rows([50, (51,), row]) == [50, 51, 52]


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
