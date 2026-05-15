import importlib
import sys
from types import ModuleType

import pytest

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalSpaceInfoReq


class _FakeKnowledgeSpaceService:
    def __init__(self):
        self.requested_space_ids = None
        self.search_request = None

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
            "total": 1,
            "page": req.page,
            "page_size": req.page_size,
        }

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
            sort="relevance",
            page=1,
            page_size=10,
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
    assert response.data["total"] == 1
    assert response.data["data"][0]["space_id"] == 12


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
