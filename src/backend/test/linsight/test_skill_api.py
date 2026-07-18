"""F035 Track D — /api/v1/linsight/skill API integration tests (TD-5).

Minimal FastAPI app mounting only the skill router; auth dependencies are
overridden, the DAO is the in-memory fake from the service tests, disk IO is
a tmp SkillStore. Covers the C3 contract (2026-06-12 increment): display_name
fields, multi-format upload, bundle file endpoint, built-in 404 semantics.
"""

import io
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.linsight.api.endpoints import skill as skill_endpoints
from bisheng.linsight.domain.services import skill_service as service_module
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import MAX_BUNDLE_SIZE, SkillStore
from test.linsight.test_skill_service import FakeSkillDao

BASE = "/api/v1/linsight/skill"


class MockAdminUser:
    user_id = 1
    user_name = "admin"


class MockEndUser:
    user_id = 99
    user_name = "viewer"


@pytest.fixture
def client(tmp_path, monkeypatch):
    FakeSkillDao.reset()
    monkeypatch.setattr(service_module, "LinsightSkillDao", FakeSkillDao)
    monkeypatch.setattr(service_module.PermissionService, "authorize", AsyncMock())
    # Endpoint-level service factory pinned to the tmp store; tenant id pinned to 1.
    monkeypatch.setattr(skill_endpoints, "SkillService", lambda: SkillService(store=SkillStore(root=tmp_path)))
    monkeypatch.setattr(skill_endpoints, "_current_tenant_id", lambda: 1)

    app = FastAPI()
    app.include_router(skill_endpoints.router, prefix="/api/v1/linsight")

    @app.exception_handler(BaseErrorCode)
    def handle_business_error(request, exc: BaseErrorCode):
        # mirror bisheng.main.handle_http_exception shape for BaseErrorCode
        return JSONResponse(content={"status_code": exc.code, "status_message": exc.message})

    async def admin_user():
        return MockAdminUser()

    async def end_user():
        return MockEndUser()

    app.dependency_overrides[UserPayload.get_tenant_admin_user] = admin_user
    app.dependency_overrides[UserPayload.get_login_user] = end_user
    return TestClient(app, raise_server_exceptions=False)


def _md_bytes(name="demo-skill", display_name="演示技能") -> bytes:
    return (
        f"---\nname: {name}\ndescription: desc of {name}\nmetadata:\n  display-name: {display_name}\n---\n\n# body\n"
    ).encode()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _create_form(client, **overrides) -> dict:
    data = {
        "display_name": "季度财报分析",
        "name": "ji-du-cai-bao-fen-xi",
        "description": "抽取核心指标。",
        "content": "# 正文",
    }
    data.update(overrides)
    resp = client.post(BASE, data=data)
    assert resp.status_code == 200
    return resp.json()


class TestCrudFlow:
    def test_form_create_then_list_and_detail(self, client):
        body = _create_form(client)
        assert body["status_code"] == 200
        assert body["data"]["display_name"] == "季度财报分析"

        listed = client.get(BASE).json()
        assert listed["data"]["total"] == 1
        item = listed["data"]["data"][0]
        assert item["display_name"] == "季度财报分析"
        assert item["enabled"] is True

        detail = client.get(f"{BASE}/ji-du-cai-bao-fen-xi").json()
        assert detail["data"]["source_text"].startswith("---")
        assert [f["path"] for f in detail["data"]["files"]] == ["SKILL.md"]

    def test_multipart_md_upload(self, client):
        resp = client.post(BASE, files={"file": ("demo-skill.md", _md_bytes(), "text/markdown")})
        assert resp.json()["data"]["name"] == "demo-skill"

    def test_multipart_zip_bundle_and_file_endpoint(self, client):
        data = _zip_bytes({"demo-skill/SKILL.md": _md_bytes(), "demo-skill/scripts/a.py": b"print(1)"})
        resp = client.post(BASE, files={"file": ("demo-skill.skill", data, "application/zip")})
        assert {f["path"] for f in resp.json()["data"]["files"]} == {"SKILL.md", "scripts/a.py"}

        content = client.get(f"{BASE}/demo-skill/file", params={"path": "scripts/a.py"}).json()
        assert content["data"]["content"] == "print(1)"

    def test_put_form_edit(self, client):
        _create_form(client)
        resp = client.put(
            f"{BASE}/ji-du-cai-bao-fen-xi",
            data={
                "display_name": "季度财报分析v2",
                "name": "ji-du-cai-bao-fen-xi",
                "description": "新描述。",
                "content": "# 新正文",
            },
        )
        assert resp.json()["data"]["display_name"] == "季度财报分析v2"

    def test_status_toggle_affects_selectable(self, client):
        _create_form(client)
        assert len(client.get(f"{BASE}/selectable").json()["data"]) == 1
        resp = client.patch(f"{BASE}/ji-du-cai-bao-fen-xi/status", json={"enabled": False})
        assert resp.json()["data"] == {"ok": True}
        assert client.get(f"{BASE}/selectable").json()["data"] == []

    def test_delete(self, client):
        _create_form(client)
        assert client.delete(f"{BASE}/ji-du-cai-bao-fen-xi").json()["data"] == {"ok": True}
        assert client.get(f"{BASE}/ji-du-cai-bao-fen-xi").json()["status_code"] == 11053

    def test_selectable_shape(self, client):
        _create_form(client)
        item = client.get(f"{BASE}/selectable").json()["data"][0]
        assert set(item) == {"name", "display_name", "description"}


class TestErrorCodes:
    def test_builtin_or_unknown_name_is_404_code(self, client):
        # built-in skills are not addressable through /skill: plain 11053
        assert client.get(f"{BASE}/kernel-core").json()["status_code"] == 11053
        assert client.delete(f"{BASE}/kernel-core").json()["status_code"] == 11053
        assert client.patch(f"{BASE}/kernel-core/status", json={"enabled": False}).json()["status_code"] == 11053

    def test_duplicate_name_11055(self, client):
        _create_form(client)
        resp = client.post(
            BASE,
            data={
                "display_name": "另一个",
                "name": "ji-du-cai-bao-fen-xi",
                "description": "x",
                "content": "y",
            },
        )
        assert resp.json()["status_code"] == 11055

    def test_invalid_skill_id_11051(self, client):
        resp = client.post(BASE, data={"display_name": "名", "name": "Bad_Name", "description": "x", "content": "y"})
        assert resp.json()["status_code"] == 11051

    def test_zip_without_skill_md_11051(self, client):
        resp = client.post(BASE, files={"file": ("x.zip", _zip_bytes({"readme.md": b"r"}), "application/zip")})
        assert resp.json()["status_code"] == 11051

    def test_oversize_11052(self, client):
        big = b"x" * (MAX_BUNDLE_SIZE + 1)
        resp = client.post(BASE, files={"file": ("big.md", big, "text/markdown")})
        assert resp.json()["status_code"] == 11052

    def test_missing_form_fields_11051(self, client):
        resp = client.post(BASE, data={"display_name": "只有名"})
        assert resp.json()["status_code"] == 11051

    def test_file_endpoint_traversal_11051(self, client):
        client.post(BASE, files={"file": ("demo-skill.md", _md_bytes(), "text/markdown")})
        resp = client.get(f"{BASE}/demo-skill/file", params={"path": "../escape.md"})
        assert resp.json()["status_code"] == 11051


class TestSlugify:
    def test_slugify_endpoint(self, client):
        resp = client.get(f"{BASE}/slugify", params={"text": "季度财报分析"})
        assert resp.json()["data"]["slug"] == "ji-du-cai-bao-fen-xi"
