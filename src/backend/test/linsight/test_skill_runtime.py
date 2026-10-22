"""End-user runtime transport shares Chat's tenant-enabled authorization rule."""

import io
import zipfile

from test.linsight.test_skill_api import BASE, _md_bytes, _zip_bytes

pytest_plugins = ("test.linsight.test_skill_api",)


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
