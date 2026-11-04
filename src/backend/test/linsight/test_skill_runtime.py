"""End-user runtime transport shares Chat's tenant-enabled authorization rule."""

import io
import zipfile
from unittest.mock import AsyncMock

import pytest

from test.linsight.test_skill_api import BASE, _md_bytes, _zip_bytes

pytest_plugins = ("test.linsight.test_skill_api",)


@pytest.fixture(autouse=True)
def runtime_permission_scope(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
    from bisheng.linsight.domain.services.user_skills import SkillAvailabilityRepository
    from test.linsight.test_skill_service import FakeSkillDao

    async def enabled(*, owner_user_id=0):
        return [row for row in await FakeSkillDao.list_enabled() if getattr(row, "owner_user_id", 0) == owner_user_id]

    monkeypatch.setattr(LinsightSkillDao, "list_enabled", enabled)
    monkeypatch.setattr(SkillAvailabilityRepository, "disabled_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    allowed = {"enabled": True}

    async def decisions(user, *, resource_type, resource_ids, actions):
        return {str(i): {"use"} for i in resource_ids} if allowed["enabled"] else {}

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", decisions)
    token = set_current_tenant_id(1)
    yield allowed
    current_tenant_id.reset(token)


def test_runtime_revocation_hides_catalog_and_blocks_direct_bundle(client, runtime_permission_scope):
    client.post(BASE, files={"file": ("demo.md", _md_bytes(), "text/markdown")})
    row = client.get(BASE + "/runtime/catalog").json()["data"][0]
    runtime_permission_scope["enabled"] = False
    assert client.get(BASE + "/runtime/catalog").json()["data"] == []
    response = client.get(f"{BASE}/runtime/{row['id']}/bundle", params={"version": row["content_hash"]})
    assert response.json()["status_code"] != 200
    assert response.headers["content-type"] == "application/json"


def test_runtime_bundle_preserves_assets_and_rechecks_enabled(client):
    files = {"SKILL.md": _md_bytes(), "scripts/run.py": b"print('ok')", "templates/demo.bin": bytes(range(256))}
    created = client.post(BASE, files={"file": ("demo.zip", _zip_bytes(files), "application/zip")}).json()
    assert created["status_code"] == 200
    rows = client.get(BASE + "/runtime/catalog").json()["data"]
    row = rows[0]
    response = client.get(f"{BASE}/runtime/{row['id']}/bundle", params={"version": row["content_hash"]})
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == files
    from test.linsight.test_skill_service import FakeSkillDao

    FakeSkillDao.rows[row["name"]].enabled = False
    assert client.get(BASE + "/runtime/catalog").json()["data"] == []
    assert (
        client.get(f"{BASE}/runtime/{row['id']}/bundle", params={"version": row["content_hash"]}).json()["status_code"]
        != 200
    )


def test_runtime_rejects_foreign_tenant_unknown_and_old_revision(client):
    client.post(BASE, files={"file": ("demo.md", _md_bytes(), "text/markdown")})
    row = client.get(BASE + "/runtime/catalog").json()["data"][0]
    url = f"{BASE}/runtime/{row['id']}/bundle"
    assert client.get(url, params={"version": "0" * 64}).json()["status_code"] != 200
    assert (
        client.get(f"{BASE}/runtime/9999/bundle", params={"version": row["content_hash"]}).json()["status_code"] != 200
    )
    from test.linsight.test_skill_service import FakeSkillDao

    FakeSkillDao.rows[row["name"]].tenant_id = 2
    assert client.get(url, params={"version": row["content_hash"]}).json()["status_code"] != 200


def test_runtime_requires_login(client):
    from fastapi import HTTPException

    from bisheng.common.dependencies.user_deps import UserPayload

    async def logged_out():
        raise HTTPException(status_code=401)

    client.app.dependency_overrides[UserPayload.get_login_user] = logged_out
    assert client.get(BASE + "/runtime/catalog").status_code == 401
    assert client.get(BASE + "/runtime/1/bundle", params={"version": "0" * 64}).status_code == 401
