from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import (
    DeveloperTokenAdminForbiddenError,
    DeveloperTokenInvalidFileSyncRuleError,
)
from bisheng.common.schemas.api import PageData
from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    get_visible_tenant_ids,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenFileSyncOptions,
    FileSyncOptionBusinessDomain,
    FileSyncOptionCategory,
    FileSyncOptionChild,
    FileSyncOptionKnowledgeSpace,
)
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService

ENDPOINT_MOD = "bisheng.developer_token.api.endpoints.developer_token"


def _operator():
    user = MagicMock(spec=UserPayload)
    user.user_id = 10
    user.tenant_id = 5
    return user


def _app(login_user):
    from bisheng.admin.api.router import router as admin_router

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


def test_options_route_precedes_dynamic_token_route_and_forwards_query() -> None:
    response = DeveloperTokenFileSyncOptions(
        tenant_id=5,
        categories=[
            FileSyncOptionCategory(
                code="POLICY",
                label="政策制度",
                children=[FileSyncOptionChild(code="MGMT_POLICY", label="管理政策")],
            )
        ],
        business_domains=[FileSyncOptionBusinessDomain(code="SA", name="安全")],
        knowledge_spaces=PageData(
            data=[FileSyncOptionKnowledgeSpace(id=118, name="安全库")],
            total=1,
        ),
    )
    service = AsyncMock(return_value=response)
    app = _app(_operator())

    with patch(f"{ENDPOINT_MOD}.DeveloperTokenService.get_file_sync_options", new=service):
        result = TestClient(app).get(
            "/api/v1/admin/developer-tokens/config/file-sync-options",
            params={
                "tenant_id": 5,
                "space_page": 2,
                "space_limit": 25,
                "space_keyword": "安全",
            },
        )

    assert result.status_code == 200
    assert result.json()["data"]["knowledge_spaces"] == {
        "data": [{"id": 118, "name": "安全库"}],
        "total": 1,
    }
    assert service.await_args.kwargs == {
        "tenant_id": 5,
        "space_page": 2,
        "space_limit": 25,
        "space_keyword": "安全",
    }


@pytest.mark.asyncio
async def test_options_filter_invalid_categories_disabled_domains_and_page_spaces(monkeypatch) -> None:
    config = SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[
                SimpleNamespace(
                    code=" POLICY ",
                    label="政策制度",
                    children=[
                        SimpleNamespace(code="MGMT_POLICY", label="管理政策"),
                        SimpleNamespace(code="TOO_LONG_SUBCATEGORY_CODE", label="无效"),
                    ],
                ),
                SimpleNamespace(code="bad/code", label="无效", children=[]),
            ],
            domains=[
                SimpleNamespace(code=" sa ", name="安全", enabled=True),
                SimpleNamespace(code="OFF", name="关闭", enabled=False),
                SimpleNamespace(code="bad/code", name="无效", enabled=True),
            ],
        )
    )

    class Repo:
        @staticmethod
        async def list_file_sync_spaces(*, page, limit, keyword):
            assert (page, limit, keyword) == (2, 25, "安全")
            return [SimpleNamespace(id=118, name="安全库")], 26

    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    current_token = set_current_tenant_id(99)
    visible_token = set_visible_tenant_ids(frozenset({99}))
    try:
        result = await DeveloperTokenService.get_file_sync_options(
            _operator(),
            tenant_id=5,
            space_page=2,
            space_limit=25,
            space_keyword=" 安全 ",
        )

        assert result.categories[0].model_dump() == {
            "code": "POLICY",
            "label": "政策制度",
            "children": [{"code": "MGMT_POLICY", "label": "管理政策"}],
        }
        assert [item.model_dump() for item in result.business_domains] == [{"code": "SA", "name": "安全"}]
        assert result.knowledge_spaces.total == 26
        assert get_current_tenant_id() == 99
        assert get_visible_tenant_ids() == frozenset({99})
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(current_token)


@pytest.mark.asyncio
async def test_options_requires_portal_config(monkeypatch) -> None:
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=None),
    )

    with pytest.raises(DeveloperTokenInvalidFileSyncRuleError) as exc_info:
        await DeveloperTokenService.get_file_sync_options(_operator(), tenant_id=5)

    assert exc_info.value.code == 19813


@pytest.mark.asyncio
async def test_options_rejects_cross_tenant_scope_before_loading_resources(monkeypatch) -> None:
    check_scope = AsyncMock(side_effect=DeveloperTokenAdminForbiddenError())
    load_config = AsyncMock()
    operator = _operator()
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", check_scope)
    monkeypatch.setattr(DeveloperTokenService, "_get_file_sync_portal_config", load_config)

    with pytest.raises(DeveloperTokenAdminForbiddenError):
        await DeveloperTokenService.get_file_sync_options(operator, tenant_id=8)

    check_scope.assert_awaited_once_with(operator, 8)
    load_config.assert_not_awaited()
