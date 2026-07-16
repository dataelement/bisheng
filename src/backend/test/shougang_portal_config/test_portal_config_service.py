from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.shougang_portal_config.domain.repositories.implementations.department_business_domain_repository_impl import (
    DepartmentBusinessDomainRepositoryImpl,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


def _payload(
    *,
    home_total_count: int = 20,
    department_id: int = 10,
    hot_half_life_days: int = 7,
) -> ShougangPortalAdminConfig:
    return ShougangPortalAdminConfig.model_validate(
        {
            "version": 999,
            "portal": {
                "domains": [
                    {
                        "name": "安全",
                        "code": "SAFE",
                        "space_ids": [],
                        "color": "#fff",
                        "bg": "#000",
                        "icon": "Shield",
                        "enabled": True,
                    }
                ],
                "sections": [],
                "document_types": [],
                "qa": {},
                "recommendation": {
                    "provider": "tag_feed",
                    "home_strategy": "latest",
                    "detail_strategy": "related",
                    "home_total_count": home_total_count,
                    "hot_half_life_days": hot_half_life_days,
                },
                "department_business_domain_bindings": [
                    {"department_id": department_id, "business_domain_codes": ["SAFE"]},
                ],
                "display": {"home": {}, "list": {}, "search": {}, "detail": {}},
                "banners": [],
                "integrations": {},
                "site": {},
            },
            "bisheng": {"base_url": "http://bisheng.example.com"},
            "unified_auth": {},
        }
    )


@pytest.fixture()
async def portal_config_session_factory(async_db_engine, monkeypatch):
    register_tenant_filter_events()
    async with async_db_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO department (id, dept_id, name, tenant_id) VALUES (10, 'D10', '安全部', 1)")
        )

    @asynccontextmanager
    async def session_context():
        async with AsyncSession(bind=async_db_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.shougang_portal_config.domain.services.portal_config_service.get_async_db_session",
        session_context,
    )
    post_commit_calls = []
    monkeypatch.setattr(
        "bisheng.shougang_portal_config.domain.services.portal_config_service."
        "_enqueue_recommendation_config_post_commit",
        lambda **kwargs: post_commit_calls.append(kwargs),
    )
    session_context.post_commit_calls = post_commit_calls
    return session_context


async def _stored_state(session_context) -> tuple[dict, list[tuple]]:
    async with session_context() as session:
        config_result = await session.exec(
            text('SELECT value FROM config WHERE "key" = :key').bindparams(key="shougang_portal_config")
        )
        value = config_result.scalar_one()
        binding_result = await session.exec(
            text(
                "SELECT tenant_id, department_id, business_domain_code "
                "FROM department_business_domain ORDER BY tenant_id, department_id, business_domain_code"
            )
        )
    return ShougangPortalAdminConfig.model_validate_json(value).model_dump(mode="json"), binding_result.all()


async def test_service_ignores_client_version_and_atomically_increments_server_version(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        first = await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
        second = await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
    finally:
        current_tenant_id.reset(tenant_token)

    stored, bindings = await _stored_state(portal_config_session_factory)
    assert first.version == 1
    assert second.version == 2
    assert stored["version"] == 2
    assert bindings == [(1, 10, "SAFE")]


async def test_binding_failure_rolls_back_config_and_binding_together(
    portal_config_session_factory,
    monkeypatch,
):
    tenant_token = set_current_tenant_id(1)
    try:
        await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)

        async def fail_replace(*args, **kwargs):
            raise RuntimeError("binding flush failed")

        monkeypatch.setattr(DepartmentBusinessDomainRepositoryImpl, "replace_all", fail_replace)
        with pytest.raises(RuntimeError, match="binding flush failed"):
            await ShougangPortalConfigService.save_config(
                _payload(home_total_count=21),
                tenant_id=1,
                create_user=8,
            )
    finally:
        current_tenant_id.reset(tenant_token)

    stored, bindings = await _stored_state(portal_config_session_factory)
    assert stored["version"] == 1
    assert stored["portal"]["recommendation"]["home_total_count"] == 20
    assert bindings == [(1, 10, "SAFE")]


async def test_missing_department_is_rejected_without_mutating_old_config_or_bindings(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
        with pytest.raises(ValueError, match="missing department"):
            await ShougangPortalConfigService.save_config(
                _payload(home_total_count=21, department_id=999),
                tenant_id=1,
                create_user=8,
            )
    finally:
        current_tenant_id.reset(tenant_token)

    stored, bindings = await _stored_state(portal_config_session_factory)
    assert stored["version"] == 1
    assert stored["portal"]["recommendation"]["home_total_count"] == 20
    assert bindings == [(1, 10, "SAFE")]


async def test_config_post_commit_hook_receives_binding_and_heat_changes(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
        await ShougangPortalConfigService.save_config(
            _payload(hot_half_life_days=14),
            tenant_id=1,
            create_user=8,
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert portal_config_session_factory.post_commit_calls == [
        {"tenant_id": 1, "department_ids": [10], "rebuild_pools": True},
        {"tenant_id": 1, "department_ids": [], "rebuild_pools": True},
    ]
