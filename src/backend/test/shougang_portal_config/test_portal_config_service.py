from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


def _domain(
    *,
    code: str = "SAFE",
    department_ids: list[int] | None = None,
    enabled: bool = True,
) -> dict:
    return {
        "name": code or "未编码域",
        "code": code,
        "space_ids": [],
        "department_ids": department_ids if department_ids is not None else [10],
        "color": "#fff",
        "bg": "#000",
        "icon": "Shield",
        "enabled": enabled,
    }


def _payload(
    *,
    home_total_count: int = 20,
    hot_half_life_days: int = 7,
    domains: list[dict] | None = None,
) -> ShougangPortalAdminConfig:
    return ShougangPortalAdminConfig.model_validate(
        {
            "version": 999,
            "portal": {
                "domains": domains if domains is not None else [_domain()],
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


async def _stored_config(session_context) -> dict:
    async with session_context() as session:
        config_result = await session.exec(
            text('SELECT value FROM config WHERE "key" = :key').bindparams(key="shougang_portal_config")
        )
        value = config_result.scalar_one()
    return ShougangPortalAdminConfig.model_validate_json(value).model_dump(mode="json")


async def test_service_ignores_client_version_and_atomically_increments_server_version(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        first = await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
        second = await ShougangPortalConfigService.save_config(_payload(), tenant_id=1, create_user=8)
    finally:
        current_tenant_id.reset(tenant_token)

    stored = await _stored_config(portal_config_session_factory)
    assert first.version == 1
    assert second.version == 2
    assert stored["version"] == 2
    assert stored["portal"]["domains"][0]["department_ids"] == [10]
    assert "department_business_domain_bindings" not in stored["portal"]


async def test_config_post_commit_hook_receives_domain_mapping_and_heat_changes(
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


async def test_old_and_new_domain_mappings_invalidate_every_affected_department(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        await ShougangPortalConfigService.save_config(
            _payload(domains=[_domain(code="SAFE", department_ids=[10, 11])]),
            tenant_id=1,
            create_user=8,
        )
        await ShougangPortalConfigService.save_config(
            _payload(domains=[_domain(code="SAFE", department_ids=[11, 12])]),
            tenant_id=1,
            create_user=8,
        )
        await ShougangPortalConfigService.save_config(
            _payload(domains=[_domain(code="PP", department_ids=[11, 12])]),
            tenant_id=1,
            create_user=8,
        )
        await ShougangPortalConfigService.save_config(
            _payload(domains=[_domain(code="PP", department_ids=[11, 12])]),
            tenant_id=1,
            create_user=8,
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert portal_config_session_factory.post_commit_calls == [
        {"tenant_id": 1, "department_ids": [10, 11], "rebuild_pools": True},
        {"tenant_id": 1, "department_ids": [10, 11, 12], "rebuild_pools": False},
        {"tenant_id": 1, "department_ids": [11, 12], "rebuild_pools": False},
        {"tenant_id": 1, "department_ids": [], "rebuild_pools": False},
    ]


async def test_disabled_or_invalid_domains_do_not_create_user_domain_mapping(
    portal_config_session_factory,
):
    tenant_token = set_current_tenant_id(1)
    try:
        await ShougangPortalConfigService.save_config(
            _payload(
                domains=[
                    _domain(code="SAFE", department_ids=[10], enabled=False),
                    _domain(code="bad-code!", department_ids=[11]),
                ]
            ),
            tenant_id=1,
            create_user=8,
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert portal_config_session_factory.post_commit_calls == [
        {"tenant_id": 1, "department_ids": [], "rebuild_pools": True},
    ]
