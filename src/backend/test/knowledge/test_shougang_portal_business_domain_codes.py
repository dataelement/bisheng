from types import SimpleNamespace

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceBusinessDomainCodeInvalidError,
    SpaceNotFoundError,
)
from bisheng.knowledge.api.endpoints.shougang_portal import (
    sync_shougang_portal_space_business_domain_codes,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
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
        ShougangPortalSpaceBusinessDomainCodesSyncReq(
            bindings=[{"space_id": 11, "business_domain_codes": ["PP"]}]
        ),
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
