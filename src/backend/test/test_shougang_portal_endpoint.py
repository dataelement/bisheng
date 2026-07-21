import importlib
import json
import sys
from types import ModuleType

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    PortalPdfArtifactUnavailableError,
    PortalPdfDownloadBusyError,
    PortalPdfDownloadGenerationError,
    PortalPdfDownloadServiceUnavailableError,
    PortalPdfDownloadTimeoutError,
    PortalShareDownloadGrantInvalidError,
    SpaceFileNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalSpaceInfoReq,
    ShougangPortalTelemetryEventReq,
)


class _FakeKnowledgeSpaceService:
    def __init__(self):
        self.requested_space_ids = None
        self.search_request = None
        self.share_create_request = None
        self.share_verify_request = None
        self.behavior_event = None

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

    async def count_shougang_portal_domain_files(self, domains):
        self.requested_codes = domains
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

    async def record_shougang_portal_recommendation_behavior(self, req):
        self.behavior_event = req


class _FakePreparedDownload:
    path = None
    filename = "迁移指南.pdf"
    size = 8

    def __init__(self) -> None:
        self.closed = False

    async def iter_bytes(self):
        try:
            yield b"%PDF-1."
        finally:
            self.closed = True


class _FakePortalPdfDownloadService:
    def __init__(self, *, error=None) -> None:
        self.error = error
        self.calls = []
        self.prepared = _FakePreparedDownload()

    async def prepare_download(self, request, login_user):
        self.calls.append((request, login_user))
        if self.error:
            raise self.error
        return self.prepared


def _load_shougang_portal_endpoint(monkeypatch: pytest.MonkeyPatch):
    dependencies_module = ModuleType('bisheng.knowledge.api.dependencies')

    def _get_knowledge_space_service():
        return None

    def _get_portal_pdf_download_service():
        return None

    dependencies_module.get_knowledge_space_service = _get_knowledge_space_service
    dependencies_module.get_portal_pdf_download_service = _get_portal_pdf_download_service
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
async def test_portal_search_writes_common_telemetry_then_updates_recommendation_behavior(
    monkeypatch: pytest.MonkeyPatch,
):
    endpoint_module_name = 'bisheng.knowledge.api.endpoints.shougang_portal'
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        logged = []
        monkeypatch.setattr(
            endpoint.PortalTelemetryEventService,
            "log_event_sync",
            lambda **kwargs: logged.append(kwargs),
        )
        service = _FakeKnowledgeSpaceService()
        request = ShougangPortalTelemetryEventReq(
            event_type="portal_search",
            source_app="shougang_portal",
            scene="knowledge_search",
            entry_point="search_page",
            query="  安全   STEEL ",
        )
        response = await endpoint.record_shougang_portal_telemetry_event(
            request,
            login_user=UserPayload(user_id=7, user_name="user-7"),
            svc=service,
        )
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert logged[0]["event_data"].query == "安全 STEEL"
    assert logged[0]["event_data"].normalized_query == "安全 steel"
    assert service.behavior_event is request


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
        req = endpoint.ShougangPortalDomainFileCountReq(
            domains=[
                {"code": "PP", "space_ids": [11, 12]},
                {"code": "QM", "space_ids": [13]},
            ]
        )
        response = await endpoint.count_shougang_portal_domain_files(req, svc=fake_service)
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    assert response.status_code == 200
    assert [item.model_dump() for item in fake_service.requested_codes] == [
        {"code": "PP", "space_ids": [11, 12]},
        {"code": "QM", "space_ids": [13]},
    ]
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
            sections=[{"tag": "最新精选", "recommendation": "latest_selected", "page_size": 4}],
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


@pytest.mark.asyncio
async def test_portal_pdf_download_returns_binary_safe_headers_and_chinese_filename(
    monkeypatch: pytest.MonkeyPatch,
):
    endpoint_module_name = "bisheng.knowledge.api.endpoints.shougang_portal"
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        service = _FakePortalPdfDownloadService()
        login_user = UserPayload(user_id=7, user_name="张三", tenant_id=5)
        response = await endpoint.download_shougang_portal_pdf(
            space_id=12,
            file_id=1580,
            entry_point="detail",
            share_access_grant="",
            login_user=login_user,
            svc=service,
        )
        body = b"".join([chunk async for chunk in response.body_iterator])
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    request, actual_user = service.calls[0]
    assert request.space_id == 12
    assert request.file_id == 1580
    assert request.entry_point.value == "detail"
    assert actual_user is login_user
    assert response.status_code == 200
    assert body == b"%PDF-1."
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == "8"
    assert 'filename="document.pdf"' in response.headers["content-disposition"]
    assert "filename*=UTF-8''%E8%BF%81%E7%A7%BB%E6%8C%87%E5%8D%97.pdf" in response.headers[
        "content-disposition"
    ]
    assert response.headers["cache-control"] == "private, no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert service.prepared.closed is True


@pytest.mark.asyncio
async def test_portal_pdf_download_passes_private_grant_and_normalizes_unknown_entry_point(
    monkeypatch: pytest.MonkeyPatch,
):
    endpoint_module_name = "bisheng.knowledge.api.endpoints.shougang_portal"
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        service = _FakePortalPdfDownloadService()
        response = await endpoint.download_shougang_portal_pdf(
            space_id=12,
            file_id=1580,
            entry_point="untrusted",
            share_access_grant="opaque-secret-grant",
            login_user=UserPayload(user_id=7, user_name="张三", tenant_id=5),
            svc=service,
        )
        await response.body_iterator.aclose()
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    request, _ = service.calls[0]
    assert request.entry_point.value == "other"
    assert request.share_access_grant == "opaque-secret-grant"
    assert "opaque-secret-grant" not in json.dumps(dict(response.headers))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "http_status", "business_code"),
    [
        (SpacePermissionDeniedError(), 403, 18040),
        (PortalShareDownloadGrantInvalidError(), 403, 18088),
        (SpaceFileNotFoundError(), 404, 18020),
        (PortalPdfArtifactUnavailableError(), 409, 18085),
        (PortalPdfDownloadBusyError(), 429, 18086),
        (PortalPdfDownloadServiceUnavailableError(), 503, 18090),
        (PortalPdfDownloadTimeoutError(), 504, 18087),
        (PortalPdfDownloadGenerationError(), 500, 18089),
    ],
)
async def test_portal_pdf_download_maps_domain_errors_to_real_http_status(
    monkeypatch: pytest.MonkeyPatch,
    error,
    http_status: int,
    business_code: int,
):
    endpoint_module_name = "bisheng.knowledge.api.endpoints.shougang_portal"
    previous_endpoint_module = sys.modules.get(endpoint_module_name)
    sys.modules.pop(endpoint_module_name, None)
    try:
        endpoint = _load_shougang_portal_endpoint(monkeypatch)
        response = await endpoint.download_shougang_portal_pdf(
            space_id=12,
            file_id=1580,
            entry_point="detail",
            share_access_grant="",
            login_user=UserPayload(user_id=7, user_name="张三", tenant_id=5),
            svc=_FakePortalPdfDownloadService(error=error),
        )
    finally:
        if previous_endpoint_module is None:
            sys.modules.pop(endpoint_module_name, None)
        else:
            sys.modules[endpoint_module_name] = previous_endpoint_module

    payload = json.loads(response.body)
    assert response.status_code == http_status
    assert payload["status_code"] == business_code
    assert "opaque" not in response.body.decode()
