from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.services.approval_registry import SYSTEM_FILE_CHANGE_SCENARIO_CODE
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangeSetting,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    KnowledgeSpaceFileChangeConfigurationResp,
    KnowledgeSpaceFileChangePolicyResp,
    KnowledgeSpaceFileChangeSettingResp,
    KnowledgeSpaceFileChangeSettingsResp,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_policy_service import (
    KnowledgeSpaceFileChangePolicyService,
)


def _mount_app(service, *, authorized: bool = True) -> FastAPI:
    from bisheng.knowledge.api.endpoints import knowledge_space_file_change as endpoint

    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(endpoint.router)
    app.include_router(api)
    app.dependency_overrides[endpoint.get_file_change_policy_service] = lambda: service

    async def _admin_user():
        if not authorized:
            raise HTTPException(status_code=403, detail="admin required")
        return SimpleNamespace(user_id=7, tenant_id=17)

    app.dependency_overrides[UserPayload.get_tenant_admin_user] = _admin_user
    return app


def _fake_service() -> SimpleNamespace:
    setting = KnowledgeSpaceFileChangeSettingResp(
        space_id=101,
        name="研发空间",
        auth_type="public",
        space_kind="normal",
        approval_required=False,
        effective_required=False,
    )
    return SimpleNamespace(
        get_policy=AsyncMock(
            return_value=KnowledgeSpaceFileChangePolicyResp(
                enabled=True,
                scope="per_space",
            )
        ),
        save_policy=AsyncMock(
            return_value=KnowledgeSpaceFileChangePolicyResp(
                enabled=False,
                scope="all_spaces",
            )
        ),
        get_space_settings_page=AsyncMock(
            return_value=KnowledgeSpaceFileChangeSettingsResp(
                data=[
                    KnowledgeSpaceFileChangeSettingResp(
                        space_id=101,
                        name="研发空间",
                        auth_type="public",
                        space_kind="normal",
                        approval_required=True,
                        effective_required=True,
                    )
                ],
                total=1,
            )
        ),
        update_space_setting=AsyncMock(
            return_value=setting
        ),
        save_configuration=AsyncMock(
            return_value=KnowledgeSpaceFileChangeConfigurationResp(
                policy=KnowledgeSpaceFileChangePolicyResp(enabled=False, scope="all_spaces"),
                settings=[setting],
            )
        ),
    )


def test_get_and_put_policy_use_unified_response_and_admin_dependency():
    service = _fake_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        get_response = client.get("/api/v1/knowledge/space/admin/file-change-policy")
        put_response = client.put(
            "/api/v1/knowledge/space/admin/file-change-policy",
            json={"enabled": False, "scope": "all_spaces"},
        )

    assert get_response.status_code == 200
    assert get_response.json() == {
        "status_code": 200,
        "status_message": "SUCCESS",
        "data": {"enabled": True, "scope": "per_space"},
    }
    assert put_response.status_code == 200
    assert put_response.json()["data"] == {"enabled": False, "scope": "all_spaces"}
    service.get_policy.assert_awaited_once_with()
    service.save_policy.assert_awaited_once_with(enabled=False, scope="all_spaces")


def test_space_settings_are_paginated_and_setting_can_be_updated():
    service = _fake_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        list_response = client.get(
            "/api/v1/knowledge/space/admin/file-change-settings",
            params={"keyword": "研发", "page": 2, "page_size": 10},
        )
        update_response = client.put(
            "/api/v1/knowledge/space/admin/file-change-settings/101",
            json={"approval_required": False},
        )

    assert list_response.status_code == 200
    assert list_response.json()["data"] == {
        "data": [
            {
                "space_id": 101,
                "name": "研发空间",
                "auth_type": "public",
                "space_kind": "normal",
                "approval_required": True,
                "effective_required": True,
            }
        ],
        "total": 1,
    }
    assert update_response.status_code == 200
    assert update_response.json()["data"]["approval_required"] is False
    service.get_space_settings_page.assert_awaited_once_with(keyword="研发", page=2, page_size=10)
    service.update_space_setting.assert_awaited_once_with(space_id=101, approval_required=False)


def test_bulk_configuration_uses_one_admin_current_tenant_command():
    service = _fake_service()
    app = _mount_app(service)
    payload = {
        "policy": {"enabled": False, "scope": "all_spaces"},
        "settings": [{"space_id": 101, "approval_required": False}],
    }

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/knowledge/space/admin/file-change-configuration",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "policy": {"enabled": False, "scope": "all_spaces"},
        "settings": [
            {
                "space_id": 101,
                "name": "研发空间",
                "auth_type": "public",
                "space_kind": "normal",
                "approval_required": False,
                "effective_required": False,
            }
        ],
    }
    request = service.save_configuration.await_args.kwargs
    assert request["policy"].model_dump(mode="json") == payload["policy"]
    assert [item.model_dump(mode="json") for item in request["settings"]] == payload["settings"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"settings": []},
        {
            "settings": [
                {"space_id": 101, "approval_required": True},
                {"space_id": 101, "approval_required": False},
            ]
        },
        {"policy": {"enabled": True, "scope": "per_space", "tenant_id": 99}},
    ],
)
def test_bulk_configuration_rejects_empty_duplicate_or_caller_tenant_payload(payload):
    service = _fake_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/knowledge/space/admin/file-change-configuration",
            json=payload,
        )

    assert response.status_code == 422
    service.save_configuration.assert_not_awaited()


def test_missing_or_cross_tenant_space_update_returns_structured_not_found():
    service = _fake_service()
    service.update_space_setting.side_effect = LookupError("knowledge space not found")
    app = _mount_app(service)

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/knowledge/space/admin/file-change-settings/201",
            json={"approval_required": False},
        )

    assert response.status_code == 404
    assert response.json() == {
        "status_code": 18073,
        "status_message": "File change request does not exist or is not visible",
        "data": {"exception": "File change request does not exist or is not visible"},
    }
    service.update_space_setting.assert_awaited_once_with(space_id=201, approval_required=False)


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        (
            "put",
            "/api/v1/knowledge/space/admin/file-change-policy",
            {"enabled": True, "scope": "per_space", "tenant_id": 99},
        ),
        (
            "put",
            "/api/v1/knowledge/space/admin/file-change-settings/101",
            {"approval_required": True, "tenant_id": 99},
        ),
        (
            "get",
            "/api/v1/knowledge/space/admin/file-change-policy?tenant_id=99",
            None,
        ),
        (
            "get",
            "/api/v1/knowledge/space/admin/file-change-settings?tenant_id=99",
            None,
        ),
        (
            "put",
            "/api/v1/knowledge/space/admin/file-change-configuration?tenant_id=99",
            {"policy": {"enabled": True, "scope": "per_space"}, "settings": []},
        ),
    ],
)
def test_public_contract_rejects_caller_controlled_tenant(method: str, path: str, json: dict | None):
    service = _fake_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        response = client.request(method, path, json=json)

    assert response.status_code == 422
    service.get_policy.assert_not_awaited()
    service.save_policy.assert_not_awaited()
    service.get_space_settings_page.assert_not_awaited()
    service.update_space_setting.assert_not_awaited()


def test_non_admin_is_rejected_before_service_call():
    service = _fake_service()
    app = _mount_app(service, authorized=False)

    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge/space/admin/file-change-policy")

    assert response.status_code == 403
    service.get_policy.assert_not_awaited()


@pytest_asyncio.fixture
async def policy_api_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Knowledge.__table__,
        DepartmentKnowledgeSpace.__table__,
        KnowledgeSpaceFileChangePolicy.__table__,
        KnowledgeSpaceFileChangeSetting.__table__,
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)


def _real_service(engine) -> KnowledgeSpaceFileChangePolicyService:
    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return KnowledgeSpaceFileChangePolicyService(session_factory=session_factory)


async def _insert_spaces(engine) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add_all(
                [
                    Knowledge(
                        id=101,
                        tenant_id=17,
                        user_id=1,
                        name="研发空间",
                        type=KnowledgeTypeEnum.SPACE.value,
                        auth_type=AuthTypeEnum.PUBLIC,
                    ),
                    Knowledge(
                        id=102,
                        tenant_id=17,
                        user_id=1,
                        name="私密空间",
                        type=KnowledgeTypeEnum.SPACE.value,
                        auth_type=AuthTypeEnum.PRIVATE,
                    ),
                    Knowledge(
                        id=103,
                        tenant_id=17,
                        user_id=1,
                        name="部门空间",
                        type=KnowledgeTypeEnum.SPACE.value,
                        auth_type=AuthTypeEnum.PUBLIC,
                    ),
                    Knowledge(
                        id=201,
                        tenant_id=18,
                        user_id=2,
                        name="其他租户空间",
                        type=KnowledgeTypeEnum.SPACE.value,
                        auth_type=AuthTypeEnum.PUBLIC,
                    ),
                    Knowledge(
                        id=999,
                        tenant_id=17,
                        user_id=1,
                        name="普通知识库",
                        type=KnowledgeTypeEnum.NORMAL.value,
                        auth_type=AuthTypeEnum.PUBLIC,
                    ),
                ]
            )
            session.add(
                DepartmentKnowledgeSpace(
                    tenant_id=17,
                    department_id=88,
                    space_id=103,
                    created_by=1,
                )
            )


async def test_settings_page_is_tenant_isolated_paginated_and_projects_effective_value(policy_api_engine):
    await _insert_spaces(policy_api_engine)
    service = _real_service(policy_api_engine)

    set_current_tenant_id(17)
    await service.save_space_setting(space_id=101, approval_required=False)
    first_page = await service.get_space_settings_page(page=1, page_size=2, keyword=None)
    private_page = await service.get_space_settings_page(page=1, page_size=10, keyword="私密")
    department_page = await service.get_space_settings_page(page=1, page_size=10, keyword="部门")

    assert first_page.total == 3
    assert [row.space_id for row in first_page.data] == [101, 102]
    assert first_page.data[0].approval_required is False
    assert first_page.data[0].effective_required is False
    assert private_page.data[0].auth_type == "private"
    assert private_page.data[0].effective_required is False
    assert department_page.data[0].space_kind == "department"
    with pytest.raises(LookupError, match="knowledge space not found"):
        await service.update_space_setting(space_id=201, approval_required=False)

    set_current_tenant_id(18)
    other_tenant = await service.get_space_settings_page(page=1, page_size=20, keyword=None)
    assert other_tenant.total == 1
    assert [row.space_id for row in other_tenant.data] == [201]


async def test_successful_policy_save_atomically_ensures_fixed_scenario(policy_api_engine):
    set_current_tenant_id(17)
    service = _real_service(policy_api_engine)

    saved = await service.save_policy(enabled=False, scope="all_spaces")

    assert saved.enabled is False
    assert saved.scope == "all_spaces"
    async with AsyncSession(bind=policy_api_engine) as session:
        policy = (
            await session.exec(
                select(KnowledgeSpaceFileChangePolicy).where(
                    KnowledgeSpaceFileChangePolicy.tenant_id == 17,
                )
            )
        ).one()
        scenario = (
            await session.exec(
                select(ApprovalScenario).where(
                    ApprovalScenario.tenant_id == 17,
                    ApprovalScenario.scenario_code == SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                )
            )
        ).one()
    assert policy.enabled is False
    assert scenario.enabled is True


async def test_failed_policy_save_rolls_back_partial_fixed_scenario(policy_api_engine, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_space_file_change_policy_service as service_module

    async def _partial_scenario_then_fail(*, tenant_id: int, session: AsyncSession):
        session.add(
            ApprovalScenario(
                tenant_id=tenant_id,
                scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                scenario_name="partial scenario",
                enabled=True,
            )
        )
        await session.flush()
        raise RuntimeError("injected scenario failure")

    monkeypatch.setattr(service_module, "ensure_system_file_change_scenario", _partial_scenario_then_fail)
    async with AsyncSession(bind=policy_api_engine) as session:
        async with session.begin():
            session.add(
                KnowledgeSpaceFileChangePolicy(
                    tenant_id=17,
                    enabled=True,
                    scope="per_space",
                )
            )
    set_current_tenant_id(17)
    service = _real_service(policy_api_engine)

    with pytest.raises(RuntimeError, match="injected scenario failure"):
        await service.save_policy(enabled=False, scope="all_spaces")

    async with AsyncSession(bind=policy_api_engine) as session:
        policies = (await session.exec(select(KnowledgeSpaceFileChangePolicy))).all()
        scenarios = (await session.exec(select(ApprovalScenario))).all()
    assert len(policies) == 1
    assert policies[0].enabled is True
    assert policies[0].scope == "per_space"
    assert scenarios == []
