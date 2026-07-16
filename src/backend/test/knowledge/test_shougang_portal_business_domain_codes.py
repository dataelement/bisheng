from types import SimpleNamespace

import pytest

import bisheng.knowledge.domain.services.knowledge_space_service as knowledge_space_service_module
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    SpaceBusinessDomainCodeInvalidError,
    SpaceNotFoundError,
)
from bisheng.knowledge.api.endpoints.shougang_portal import (
    get_shougang_portal_domain_bindable_spaces,
    sync_shougang_portal_space_business_domain_codes,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalSpaceBusinessDomainCodesSyncReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service() -> KnowledgeSpaceService:
    return object.__new__(KnowledgeSpaceService)


async def test_sync_shougang_portal_space_business_domain_codes_updates_all(monkeypatch):
    captured = {}

    async def fake_get_spaces(space_ids, order_by="update_time"):
        assert order_by == "update_time"
        return [SimpleNamespace(id=space_id) for space_id in space_ids]

    async def fake_update(bindings):
        captured["bindings"] = bindings
        return len(bindings)

    monkeypatch.setattr(KnowledgeDao, "async_get_spaces_by_ids", fake_get_spaces)
    monkeypatch.setattr(KnowledgeDao, "async_update_space_business_domain_codes", fake_update)

    result = await _service().sync_shougang_portal_space_business_domain_codes(
        ShougangPortalSpaceBusinessDomainCodesSyncReq(
            bindings=[
                {"space_id": 11, "business_domain_codes": ["pp", "QM", "PP"]},
                {"space_id": 12, "business_domain_codes": []},
            ]
        )
    )

    assert result == {"updated": 2}
    assert captured["bindings"] == {11: ["PP", "QM"], 12: []}


async def test_sync_shougang_portal_space_business_domain_codes_rejects_invalid_code(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("database should not be called")

    monkeypatch.setattr(KnowledgeDao, "async_get_spaces_by_ids", fail_if_called)

    with pytest.raises(SpaceBusinessDomainCodeInvalidError):
        await _service().sync_shougang_portal_space_business_domain_codes(
            ShougangPortalSpaceBusinessDomainCodesSyncReq(
                bindings=[{"space_id": 11, "business_domain_codes": ["UNKNOWN!"]}]
            )
        )


async def test_sync_shougang_portal_space_business_domain_codes_requires_all_spaces(monkeypatch):
    async def fake_get_spaces(space_ids, order_by="update_time"):
        return [SimpleNamespace(id=11)]

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("update should not be called")

    monkeypatch.setattr(KnowledgeDao, "async_get_spaces_by_ids", fake_get_spaces)
    monkeypatch.setattr(KnowledgeDao, "async_update_space_business_domain_codes", fail_if_called)

    with pytest.raises(SpaceNotFoundError):
        await _service().sync_shougang_portal_space_business_domain_codes(
            ShougangPortalSpaceBusinessDomainCodesSyncReq(
                bindings=[
                    {"space_id": 11, "business_domain_codes": ["PP"]},
                    {"space_id": 12, "business_domain_codes": []},
                ]
            )
        )


async def test_sync_shougang_portal_space_business_domain_codes_endpoint_returns_updated_count():
    class FakeService:
        async def sync_shougang_portal_space_business_domain_codes(self, req):
            assert req.bindings[0].space_id == 11
            return {"updated": 1}

    response = await sync_shougang_portal_space_business_domain_codes(
        ShougangPortalSpaceBusinessDomainCodesSyncReq(bindings=[{"space_id": 11, "business_domain_codes": ["PP"]}]),
        svc=FakeService(),
    )

    assert response.status_code == 200
    assert response.data == {"updated": 1}


def test_space_business_domain_allowed_check_rejects_unbound_code():
    space = SimpleNamespace(business_domain_codes=["QM"])

    with pytest.raises(SpaceBusinessDomainCodeInvalidError):
        _service()._ensure_business_domain_allowed_for_space(space, "PP")


def test_space_business_domain_allowed_check_allows_all_when_unbound():
    space = SimpleNamespace(business_domain_codes=[])

    _service()._ensure_business_domain_allowed_for_space(space, "PP")


async def test_list_shougang_portal_domain_bindable_spaces_returns_public_and_department_spaces_regardless_of_release(
    monkeypatch,
):
    service = _service()
    service.login_user = SimpleNamespace(is_admin=lambda: True)
    requested_levels = []

    async def fake_get_space_ids(level):
        requested_levels.append(level)
        return {
            KnowledgeSpaceLevelEnum.PUBLIC: [11, 12],
            KnowledgeSpaceLevelEnum.DEPARTMENT: [20, 11],
        }[level]

    async def fake_get_spaces(space_ids, order_by="update_time"):
        assert set(space_ids) == {11, 12, 20}
        assert order_by == "name"
        return [
            SimpleNamespace(
                id=11,
                name="公共空间",
                description="公共",
                is_released=True,
                business_domain_codes=["pp"],
            ),
            SimpleNamespace(
                id=12,
                name="未发布公共空间",
                description="未发布",
                is_released=False,
                business_domain_codes=[],
            ),
            SimpleNamespace(
                id=20,
                name="部门空间",
                description="部门",
                is_released=True,
                business_domain_codes=["QM"],
            ),
        ]

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("domain-bindable query must not use the generic visible-space path")

    monkeypatch.setattr(KnowledgeSpaceScopeDao, "aget_space_ids_by_level", fake_get_space_ids)
    monkeypatch.setattr(KnowledgeDao, "async_get_spaces_by_ids", fake_get_spaces)
    monkeypatch.setattr(service, "_list_accessible_spaces", fail_if_called)

    result = await service.list_shougang_portal_domain_bindable_spaces()

    assert requested_levels == [KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceLevelEnum.DEPARTMENT]
    assert [item.model_dump(mode="json") for item in result] == [
        {
            "id": 11,
            "name": "公共空间",
            "description": "公共",
            "space_level": "public",
            "business_domain_codes": ["PP"],
            "file_num": 0,
        },
        {
            "id": 12,
            "name": "未发布公共空间",
            "description": "未发布",
            "space_level": "public",
            "business_domain_codes": [],
            "file_num": 0,
        },
        {
            "id": 20,
            "name": "部门空间",
            "description": "部门",
            "space_level": "department",
            "business_domain_codes": ["QM"],
            "file_num": 0,
        },
    ]


async def test_list_shougang_portal_domain_bindable_spaces_rejects_non_admin(monkeypatch):
    service = _service()
    service.login_user = SimpleNamespace(is_admin=lambda: False)

    class UnauthorizedForTest(BaseErrorCode):
        Code = 403
        Msg = "No permission to operate"

    monkeypatch.setattr(knowledge_space_service_module, "UnAuthorizedError", UnauthorizedForTest)

    with pytest.raises(BaseErrorCode) as exc_info:
        await service.list_shougang_portal_domain_bindable_spaces()
    assert exc_info.value.Code == 403


async def test_get_shougang_portal_domain_bindable_spaces_endpoint_returns_spaces():
    class FakeService:
        async def list_shougang_portal_domain_bindable_spaces(self):
            return [
                {
                    "id": 11,
                    "name": "公共空间",
                    "description": "公共",
                    "space_level": "public",
                    "business_domain_codes": ["PP"],
                    "file_num": 0,
                }
            ]

    response = await get_shougang_portal_domain_bindable_spaces(svc=FakeService())

    assert response.status_code == 200
    assert response.data == {
        "spaces": [
            {
                "id": 11,
                "name": "公共空间",
                "description": "公共",
                "space_level": "public",
                "business_domain_codes": ["PP"],
                "file_num": 0,
            }
        ]
    }
