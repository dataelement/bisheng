"""Personal skill HTTP routes, beside the unchanged management routes."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.linsight.api.endpoints import personal_skill as personal_endpoints
from bisheng.linsight.api.endpoints import skill as skill_endpoints
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.services.personal_skill_service import PERSONAL_SKILL_BYTES_LIMIT, PersonalSkillService
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

BASE = "/api/v1/linsight/skill"
TENANT = 5
USER = 11
LOCALE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "packages" / "locales" / "src" / "api_errors"


def _md(name: str = "pdf", body: str = "个人正文", display: str = "个人报告") -> bytes:
    return (
        f"---\nname: {name}\ndescription: 用途说明\nmetadata:\n  display-name: {display}\n---\n\n# {body}\n"
    ).encode()


def _app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request: Request, call_next):
        set_current_tenant_id(TENANT)
        return await call_next(request)

    @app.exception_handler(BaseErrorCode)
    def handle_business_error(request: Request, exc: BaseErrorCode):
        data = {"exception": str(exc), **exc.kwargs} if exc.kwargs else {"exception": str(exc)}
        return JSONResponse(content={"status_code": exc.code, "status_message": exc.message, "data": data})

    @app.exception_handler(AuthJWTException)
    def handle_auth(request: Request, exc: AuthJWTException):
        return JSONResponse(status_code=401, content={"detail": getattr(exc, "message", str(exc))})

    # Literal paths first, matching linsight.api.router.
    app.include_router(personal_endpoints.router, prefix="/api/v1/linsight")
    app.include_router(skill_endpoints.router, prefix="/api/v1/linsight")
    return app


@pytest.fixture
def api(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter

    db_path = tmp_path / "skills.db"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    LinsightSkill.__table__.create(sync_engine)
    sync_engine.dispose()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 5})

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    monkeypatch.setattr(model_module, "get_async_db_session", _session)
    monkeypatch.setattr(PersonalSkillService, "_audit", AsyncMock())

    async def permitted(_user, *, resource_ids, **kwargs):
        return {str(skill_id): {"use"} for skill_id in resource_ids}

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", permitted)
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.user_skills.SkillAvailabilityRepository.disabled_ids",
        AsyncMock(return_value=set()),
    )

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.require_business_action",
        AsyncMock(),
    )
    monkeypatch.setattr(skill_endpoints, "_current_tenant_id", lambda: TENANT)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    set_current_tenant_id(TENANT)

    minio = FakeMinioStorage()
    store = SkillStore(root=tmp_path, minio=minio)
    projection = SimpleNamespace(authorize_created=AsyncMock())
    service = PersonalSkillService(
        store=store,
        owner_projection=projection,
        unpack_root=tmp_path / "unpack",
    )
    monkeypatch.setattr(personal_endpoints, "_service", lambda: service)
    monkeypatch.setattr(
        skill_endpoints,
        "SkillService",
        lambda: SkillService(store=store, owner_projection=projection),
    )

    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    logged_in = _app()

    async def end_user():
        return SimpleNamespace(user_id=USER, user_name="member", tenant_id=TENANT, is_global_super=False)

    async def admin_user():
        return SimpleNamespace(user_id=1, user_name="admin", tenant_id=TENANT, is_global_super=False)

    logged_in.dependency_overrides[UserPayload.get_login_user] = end_user
    logged_in.dependency_overrides[UserPayload.get_tenant_admin_user] = admin_user

    yield SimpleNamespace(
        client=TestClient(logged_in, raise_server_exceptions=False),
        anonymous=TestClient(_app(), raise_server_exceptions=False),
        minio=minio,
    )
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()


def _upload(client: TestClient, name: str, import_id: str, body: str = "个人正文") -> dict:
    resp = client.post(
        f"{BASE}/personal",
        files={"file": (f"{name}.md", _md(name, body), "text/markdown")},
        data={"import_id": import_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status_code"] == 200
    return resp.json()["data"]


class TestPersonalSkillApi:
    def test_logged_out_request_is_rejected(self, api):
        resp = api.anonymous.get(f"{BASE}/center")
        assert resp.status_code == 401

    def test_literal_paths_are_not_read_as_skill_names(self, api):
        center = api.client.get(f"{BASE}/center").json()
        assert center["status_code"] == 200
        assert set(center["data"]) == {"personal", "enterprise", "personal_count", "enterprise_count"}
        usage = api.client.get(f"{BASE}/personal/usage").json()
        assert usage["data"]["count_limit"] == 20
        assert usage["data"]["bytes_limit"] == PERSONAL_SKILL_BYTES_LIMIT
        candidates = api.client.get(f"{BASE}/candidates").json()
        assert candidates["data"] == []

    def test_management_list_stays_enterprise_only(self, api):
        created = api.client.post(
            BASE,
            data={
                "display_name": "合同审阅",
                "name": "he-tong",
                "description": "审阅合同",
                "content": "# 企业",
            },
        ).json()
        assert created["status_code"] == 200
        personal = _upload(api.client, "pdf", "imp-1")
        listed = api.client.get(BASE).json()["data"]["data"]
        assert [row["name"] for row in listed] == ["he-tong"]
        assert set(listed[0]) == {
            "id",
            "name",
            "display_name",
            "description",
            "enabled",
            "default_checked",
            "source",
            "create_time",
            "update_time",
        }
        selectable = api.client.get(f"{BASE}/selectable").json()["data"]
        assert {row["name"] for row in selectable} == {"he-tong", "pdf"}
        assert set(selectable[0]) == {"name", "display_name", "description", "default_checked"}

        center = api.client.get(f"{BASE}/center").json()["data"]
        assert [row["name"] for row in center["personal"]] == ["pdf"]
        assert [row["name"] for row in center["enterprise"]] == ["he-tong"]
        assert center["personal_count"] == 1 and center["enterprise_count"] == 1
        assert center["personal"][0]["bundle_missing"] is False
        assert center["personal"][0]["update_time"]
        assert personal["id"] == center["personal"][0]["id"]

        candidates = api.client.get(f"{BASE}/candidates").json()["data"]
        assert {row["id"] for row in candidates} == {created["data"]["id"], personal["id"]}

        toggled = api.client.patch(f"{BASE}/he-tong/status", json={"enabled": False}).json()
        assert toggled["data"] == {"ok": True}
        assert [row["name"] for row in api.client.get(f"{BASE}/selectable").json()["data"]] == ["pdf"]
        assert api.client.get(f"{BASE}/candidates").json()["data"][0]["id"] == personal["id"]
        assert api.client.delete(f"{BASE}/he-tong").json()["data"] == {"ok": True}

    def test_duplicate_does_not_write_and_uses_the_translated_code(self, api):
        saved = _upload(api.client, "pdf", "imp-1")
        puts = api.minio.put_calls
        resp = api.client.post(
            f"{BASE}/personal",
            files={"file": ("pdf.md", _md("pdf", "另一份"), "text/markdown")},
            data={"import_id": "imp-2"},
        ).json()
        assert resp["status_code"] == 11055
        assert resp["data"]["skill_id"] == saved["id"]
        assert resp["data"]["content_hash"] == saved["content_hash"]
        assert "个人报告" not in json.dumps(resp, ensure_ascii=False)
        assert api.minio.put_calls == puts
        for language in ("zh-Hans", "en", "ja"):
            copy = json.loads((LOCALE_DIR / f"{language}.json").read_text(encoding="utf-8"))
            assert "11055" in copy and "11053" in copy

    def test_overwrite_detail_file_status_and_delete(self, api):
        saved = _upload(api.client, "pdf", "imp-1", body="第一版")
        detail = api.client.get(f"{BASE}/personal/{saved['id']}").json()["data"]
        assert detail["bundle_missing"] is False
        assert "第一版" in detail["source_text"]
        opened = api.client.get(f"{BASE}/personal/{saved['id']}/file", params={"path": "SKILL.md"}).json()
        assert "第一版" in opened["data"]["content"]

        replaced = api.client.post(
            f"{BASE}/personal/{saved['id']}/overwrite",
            files={"file": ("pdf.md", _md("pdf", "第二版"), "text/markdown")},
            data={"import_id": "imp-2", "expected_content_hash": saved["content_hash"]},
        ).json()["data"]
        assert replaced["id"] == saved["id"]
        assert replaced["content_hash"] != saved["content_hash"]
        assert replaced["enabled"] is True

        found = api.client.get(f"{BASE}/personal/import/imp-2").json()
        assert found["status_code"] == 200
        assert found["data"]["id"] == saved["id"]
        missing = api.client.get(f"{BASE}/personal/import/missing").json()
        assert missing["status_code"] == 11053

        paused = api.client.patch(f"{BASE}/personal/{saved['id']}/status", json={"enabled": False}).json()["data"]
        assert paused["enabled"] is False
        assert api.client.get(f"{BASE}/candidates").json()["data"] == []
        center = api.client.get(f"{BASE}/center").json()["data"]
        assert center["personal"][0]["enabled"] is False

        assert api.client.delete(f"{BASE}/personal/{saved['id']}").json()["data"] == {}
        gone = api.client.get(f"{BASE}/personal/{saved['id']}").json()
        assert gone["status_code"] == 11053
        assert "个人报告" not in json.dumps(gone, ensure_ascii=False)
        assert api.client.delete(f"{BASE}/personal/{saved['id']}").json()["data"] == {}
