from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

from bisheng.common.schemas.api import PageData
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import (
    KnowledgeSpaceTagLibraryDetail,
    KnowledgeSpaceTagLibraryListItem,
)


def _mount_app(fake_service) -> FastAPI:
    from bisheng.knowledge.api.endpoints import knowledge_space_tag_library as ep

    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(ep.router)
    app.include_router(api)
    app.dependency_overrides[ep.get_service] = lambda: fake_service
    return app


def _service() -> SimpleNamespace:
    return SimpleNamespace(
        list_libraries=AsyncMock(
            return_value=PageData(
                data=[
                    KnowledgeSpaceTagLibraryListItem(
                        id=1,
                        name="业务标签",
                        description="按业务线分类",
                        tag_count=2,
                        is_builtin=False,
                    )
                ],
                total=1,
            )
        ),
        get_library=AsyncMock(
            return_value=KnowledgeSpaceTagLibraryDetail(
                id=1,
                name="业务标签",
                description="按业务线分类",
                tag_count=2,
                is_builtin=False,
                tags=["合同", "制度"],
            )
        ),
        create_library=AsyncMock(
            return_value=KnowledgeSpaceTagLibraryDetail(
                id=2,
                name="新标签库",
                description="",
                tag_count=2,
                is_builtin=False,
                tags=["A", "B"],
            )
        ),
        import_text_library=AsyncMock(
            return_value=KnowledgeSpaceTagLibraryDetail(
                id=3,
                name="导入标签库",
                description="",
                tag_count=2,
                is_builtin=False,
                tags=["A", "B"],
            )
        ),
        update_library=AsyncMock(
            return_value=KnowledgeSpaceTagLibraryDetail(
                id=1,
                name="更新标签库",
                description="更新",
                tag_count=1,
                is_builtin=False,
                tags=["合同"],
            )
        ),
        delete_library=AsyncMock(return_value=None),
    )


def test_list_tag_libraries_returns_tag_count_without_tags():
    service = _service()
    app = _mount_app(service)

    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/knowledge/space/tag-libraries", params={"keyword": "业务"}
        )

    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["total"] == 1
    item = payload["data"][0]
    assert item["tag_count"] == 2
    assert "tags" not in item
    service.list_libraries.assert_awaited_once_with(
        page=1, page_size=20, keyword="业务"
    )


def test_get_tag_library_returns_tags():
    service = _service()
    app = _mount_app(service)

    with TestClient(app) as client:
        resp = client.get("/api/v1/knowledge/space/tag-libraries/1")

    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["tags"] == ["合同", "制度"]
    assert payload["tag_count"] == 2
    service.get_library.assert_awaited_once_with(1)


def test_create_import_update_and_delete_tag_library_routes_thread_payloads():
    service = _service()
    app = _mount_app(service)

    with TestClient(app) as client:
        create_resp = client.post(
            "/api/v1/knowledge/space/tag-libraries",
            json={"name": "新标签库", "description": "", "tags": ["A", "B"]},
        )
        import_resp = client.post(
            "/api/v1/knowledge/space/tag-libraries/import/text",
            json={"name": "导入标签库", "description": "", "content": "A\nB\n"},
        )
        update_resp = client.put(
            "/api/v1/knowledge/space/tag-libraries/1",
            json={"name": "更新标签库", "description": "更新", "tags": ["合同"]},
        )
        delete_resp = client.delete("/api/v1/knowledge/space/tag-libraries/1")

    assert create_resp.status_code == 200
    assert create_resp.json()["data"]["tags"] == ["A", "B"]
    service.create_library.assert_awaited_once_with("新标签库", "", ["A", "B"])

    assert import_resp.status_code == 200
    assert import_resp.json()["data"]["tag_count"] == 2
    service.import_text_library.assert_awaited_once_with("导入标签库", "", "A\nB\n")

    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["tags"] == ["合同"]
    service.update_library.assert_awaited_once_with(
        library_id=1,
        name="更新标签库",
        description="更新",
        tags=["合同"],
    )

    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"] is True
    service.delete_library.assert_awaited_once_with(1)
