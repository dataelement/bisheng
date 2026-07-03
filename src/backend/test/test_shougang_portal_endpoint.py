import importlib
import sys
from types import ModuleType

import pytest

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalSpaceInfoReq


class _FakeKnowledgeSpaceService:
    def __init__(self):
        self.requested_space_ids = None
        self.search_request = None
        self.share_create_request = None
        self.share_verify_request = None

    async def get_space_info(self, space_id: int):
        raise AssertionError("endpoint should use the batch service method")

    async def get_shougang_portal_space_infos(self, space_ids: list[int]):
        self.requested_space_ids = space_ids
        spaces = []
        for space_id in space_ids:
            if space_id == 2:
                spaces.append({
                    "id": space_id,
                    "data": {},
                    "error": {"code": 18000, "message": "Knowledge Space does not exist"},
                })
            elif space_id == 3:
                spaces.append({
                    "id": space_id,
                    "data": {},
                    "error": {
                        "code": 18040,
                        "message": "Permission denied: only the creator or admin can perform this operation",
                    },
                })
            else:
                spaces.append({
                    "id": space_id,
                    "data": {"id": space_id, "name": f"空间{space_id}"},
                    "error": None,
                })
        return spaces

    async def get_shougang_portal_space_levels(self):
        return [
            {"value": "public", "label": "公共空间"},
            {"value": "department", "label": "部门空间"},
            {"value": "team", "label": "团队空间"},
            {"value": "personal", "label": "个人空间"},
        ]

    async def get_shougang_portal_personal_spaces(self):
        return {
            "data": [
                {
                    "id": 200,
                    "name": "我的收藏",
                    "description": "",
                    "file_count": 0,
                    "updated_at": "",
                    "is_favorite": True,
                },
                {
                    "id": 7,
                    "name": "个人沉淀库",
                    "description": "个人知识空间",
                    "file_count": 3,
                    "updated_at": "2026-05-15T09:30:00",
                    "is_favorite": False,
                },
            ],
            "total": 2,
        }

    async def create_shougang_portal_favorite(self, req):
        return {
            "favorite_file_id": 99,
            "space_id": 200,
            "source_space_id": req.source_space_id,
            "source_file_id": req.source_file_id,
            "title": "热轧1580产线精轧机振动纹治理实践",
        }

    async def remove_shougang_portal_favorite(self, req):
        return {"removed": True}

    async def get_shougang_portal_favorite_status(self, req):
        return {
            "data": [
                {"space_id": it.space_id, "file_id": it.file_id, "favorited": True}
                for it in req.items
            ]
        }

    async def list_shougang_portal_favorites(self, page=1, page_size=20):
        return {
            "data": [
                {
                    "favorite_file_id": 9,
                    "source_space_id": 1,
                    "source_file_id": 2,
                    "title": "doc",
                    "file_name": "doc.pdf",
                    "status": "invalid",
                    "updated_at": "",
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    async def create_shougang_portal_share_link(self, req):
        self.share_create_request = req
        return {
            "share_token": "share-token-1580",
            "link": "/share/document/share-token-1580",
            "invite_code": "ABC123",
            "expire_seconds": req.expire_seconds,
        }

    async def get_shougang_portal_share_link_meta(self, share_token):
        return {
            "share_token": share_token,
            "file_name": "热轧1580产线精轧机振动纹治理实践.pdf",
            "share_type": "invite_code",
            "visibility": "public",
            "permissions": {"view": True, "download": False, "upload": False},
            "requires_password": True,
            "requires_invite_code": True,
            "expired": False,
        }

    async def verify_shougang_portal_share_link(self, share_token, req):
        self.share_verify_request = (share_token, req)
        return {
            "share_token": share_token,
            "space_id": 12,
            "file_id": 1580,
            "allow_download": False,
        }

    async def search_shougang_portal_files(self, req):
        self.search_request = req
        return {
            "data": [
                {
                    "id": 1580,
                    "space_id": 12,
                    "title": "热轧1580产线精轧机振动纹治理实践",
                    "summary": "振动纹治理实践摘要",
                    "source": "轧线技术案例库",
                    "updated_at": "2026-04-13T10:30:00",
                    "tags": ["热轧"],
                    "file_ext": "pdf",
                    "file_size": "949.33KB",
                    "file_encoding": "GF-ZD-SC-202604-01201",
                }
            ],
            "has_more": False,
            "next_cursor": None,
        }

    async def search_shougang_portal_tags(self, space_ids, space_level, business_domain_code=None):
        self.tag_search_request = (space_ids, space_level, business_domain_code)
        return ["设备"]

    async def count_shougang_portal_domain_files(self, codes):
        self.requested_codes = codes
        return {"PP": 5, "QM": 2}

    async def get_shougang_portal_home(self, req):
        return {
            "sections": {
                req.sections[0].tag: [
                    {
                        "id": 1580,
                        "space_id": 12,
                        "title": "热轧1580产线精轧机振动纹治理实践",
                        "summary": "振动纹治理实践摘要",
                        "source": "轧线技术案例库",
                        "updated_at": "2026-04-13T10:30:00",
                        "tags": ["最新精选", "热轧"],
                        "file_ext": "pdf",
                        "file_size": "949.33KB",
                        "file_encoding": "GF-ZD-SC-202604-01201",
                    }
                ],
            },
            "tags": ["最新精选", "热轧"],
        }


def _load_shougang_portal_endpoint(monkeypatch: pytest.MonkeyPatch):
    dependencies_module = ModuleType('bisheng.knowledge.api.dependencies')

    def _get_knowledge_space_service():
        return None

    dependencies_module.get_knowledge_space_service = _get_knowledge_space_service
    monkeypatch.setitem(sys.modules, 'bisheng.knowledge.api.dependencies', dependencies_module)
    return importlib.import_module('bisheng.knowledge.api.endpoints.shougang_portal')


@pytest.mark.asyncio
async def test_shougang_portal_space_infos_keeps_failed_items_in_response(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        fake_service = _FakeKnowledgeSpaceService()
        response = await endpoint.get_shougang_portal_space_infos(
            ShougangPortalSpaceInfoReq(space_ids=[1, 2, 3]),
            svc=fake_service,
        )
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert fake_service.requested_space_ids == [1, 2, 3]
    assert response.data["spaces"] == [
        {"id": 1, "data": {"id": 1, "name": "空间1"}, "error": None},
        {
            "id": 2,
            "data": {},
            "error": {"code": 18000, "message": "Knowledge Space does not exist"},
        },
        {
            "id": 3,
            "data": {},
            "error": {
                "code": 18040,
                "message": "Permission denied: only the creator or admin can perform this operation",
            },
        },
    ]


@pytest.mark.asyncio
async def test_shougang_portal_space_levels_returns_level_options(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        response = await endpoint.get_shougang_portal_space_levels(svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["levels"] == [
        {"value": "public", "label": "公共空间"},
        {"value": "department", "label": "部门空间"},
        {"value": "team", "label": "团队空间"},
        {"value": "personal", "label": "个人空间"},
    ]


@pytest.mark.asyncio
async def test_shougang_portal_personal_spaces_returns_current_user_spaces(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        response = await endpoint.get_shougang_portal_personal_spaces(svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["total"] == 2
    assert response.data["data"][0]["is_favorite"] is True
    assert response.data["data"][0]["name"] == "我的收藏"


@pytest.mark.asyncio
async def test_shougang_portal_create_favorite_delegates_to_service(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        req = endpoint.ShougangPortalFavoriteCreateReq(
            source_space_id=12,
            source_file_id=1580,
        )
        response = await endpoint.create_shougang_portal_favorite(req, svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data == {
        "favorite_file_id": 99,
        "space_id": 200,
        "source_space_id": 12,
        "source_file_id": 1580,
        "title": "热轧1580产线精轧机振动纹治理实践",
    }


@pytest.mark.asyncio
async def test_shougang_portal_remove_favorite_delegates(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        req = endpoint.ShougangPortalFavoriteRemoveReq(source_space_id=1, source_file_id=2)
        response = await endpoint.remove_shougang_portal_favorite(req, svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["removed"] is True


@pytest.mark.asyncio
async def test_shougang_portal_favorite_status_delegates(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        req = endpoint.ShougangPortalFavoriteStatusReq(items=[{"space_id": 1, "file_id": 2}])
        response = await endpoint.get_shougang_portal_favorite_status(req, svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["data"][0]["favorited"] is True


@pytest.mark.asyncio
async def test_shougang_portal_list_favorites_delegates(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        response = await endpoint.list_shougang_portal_favorites(
            page=1, page_size=20, svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["total"] == 1
    assert response.data["data"][0]["status"] == "invalid"


@pytest.mark.asyncio
async def test_shougang_portal_share_link_endpoints_delegate_to_service(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        fake_service = _FakeKnowledgeSpaceService()
        create_req = endpoint.ShougangPortalShareLinkCreateReq(
            space_id=12,
            file_id=1580,
            share_type="invite_code",
            visibility="public",
            allow_download=False,
            password="secret",
            expire_seconds=3600,
        )
        create_response = await endpoint.create_shougang_portal_share_link(create_req, svc=fake_service)
        meta_response = await endpoint.get_shougang_portal_share_link_meta(
            "share-token-1580",
            svc=fake_service,
        )
        verify_req = endpoint.ShougangPortalShareLinkVerifyReq(password="secret", invite_code="ABC123")
        verify_response = await endpoint.verify_shougang_portal_share_link(
            "share-token-1580",
            verify_req,
            svc=fake_service,
        )
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert create_response.status_code == 200
    assert fake_service.share_create_request.file_id == 1580
    assert create_response.data["invite_code"] == "ABC123"
    assert meta_response.data["requires_password"] is True
    assert meta_response.data["permissions"]["download"] is False
    assert verify_response.data == {
        "share_token": "share-token-1580",
        "space_id": 12,
        "file_id": 1580,
        "allow_download": False,
    }


@pytest.mark.asyncio
async def test_shougang_portal_file_search_accepts_space_level_filter(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        fake_service = _FakeKnowledgeSpaceService()
        req = endpoint.ShougangPortalFileSearchReq(
            q="振动纹",
            space_ids=[12, 18],
            space_level="department",
            file_ext="pdf",
            document_type="RPT",
            business_domain_code="pm",
            sort="relevance",
            limit=10,
        )
        response = await endpoint.search_shougang_portal_files(req, svc=fake_service)
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert fake_service.search_request.space_level == "department"
    assert fake_service.search_request.space_ids == [12, 18]
    assert fake_service.search_request.document_type == "RPT"
    assert fake_service.search_request.business_domain_code == "PM"
    assert fake_service.search_request.limit == 10
    assert response.data["has_more"] is False
    assert response.data["next_cursor"] is None
    assert response.data["data"][0]["space_id"] == 12


@pytest.mark.asyncio
async def test_shougang_portal_tag_search_accepts_business_domain_code(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        fake_service = _FakeKnowledgeSpaceService()
        req = endpoint.ShougangPortalTagSearchReq(
            space_ids=[12],
            business_domain_code=" pm ",
        )
        response = await endpoint.search_shougang_portal_tags(req, svc=fake_service)
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert fake_service.tag_search_request == ([12], None, "PM")
    assert response.data["tags"] == ["设备"]


@pytest.mark.asyncio
async def test_shougang_portal_domain_file_counts_delegates_to_service(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        fake_service = _FakeKnowledgeSpaceService()
        req = endpoint.ShougangPortalDomainFileCountReq(codes=["PP", "QM"])
        response = await endpoint.count_shougang_portal_domain_files(req, svc=fake_service)
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert fake_service.requested_codes == ["PP", "QM"]
    assert response.data["counts"] == {"PP": 5, "QM": 2}


@pytest.mark.asyncio
async def test_shougang_portal_home_accepts_section_batch_request(monkeypatch: pytest.MonkeyPatch):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        req = endpoint.ShougangPortalHomeReq(
            space_ids=[12, 18],
            sections=[{"tag": "最新精选", "page_size": 4}],
            hot_tags_limit=8,
        )
        response = await endpoint.get_shougang_portal_home(req, svc=_FakeKnowledgeSpaceService())
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert response.data["sections"]["最新精选"][0]["space_id"] == 12
    assert response.data["tags"] == ["最新精选", "热轧"]
