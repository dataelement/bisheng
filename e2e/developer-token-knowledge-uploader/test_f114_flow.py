"""F114 Developer Token 知识上传人 · 171 接口流转 (test-cases 子集).

仅当 BISHENG_E2E=1 时连接毕昇 HTTP + config.yaml 数据库.
覆盖: TC-F114-ADM-01、API-01/02/03/04、TC-F114-SYNC-01/02 (部分需环境变量).
"""

from __future__ import annotations

import io
import json
import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1",
    reason="只在明确跑 e2e 时连接毕昇和 171 (见 e2e/README.md)",
)

PREFIX = "e2e-f114-"
ADMIN_USER_ID = 1


def _engine():
    from sqlalchemy import create_engine

    from bisheng.common.services.config_service import settings

    return create_engine(settings.database_url)


def _admin_token() -> str:
    from sqlalchemy import text

    from bisheng.user.domain.services.auth import AuthJwt

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT user_name, token_version FROM user WHERE user_id = :uid AND `delete` = 0",
            ),
            {"uid": ADMIN_USER_ID},
        ).one()
    return AuthJwt().create_access_token(
        {
            "user_id": ADMIN_USER_ID,
            "user_name": row.user_name,
            "tenant_id": 1,
            "token_version": int(row.token_version or 0),
        },
    )


def _admin_client():
    import httpx

    base = os.environ.get("BISHENG_BASE_URL", "http://127.0.0.1:7860").rstrip("/")
    token = _admin_token()
    return httpx.Client(
        base_url=base,
        timeout=120,
        cookies={"access_token_cookie": token},
    )


def _filelib_client(plaintext_token: str):
    import httpx

    base = os.environ.get("BISHENG_BASE_URL", "http://127.0.0.1:7860").rstrip("/")
    return httpx.Client(
        base_url=base,
        timeout=300,
        headers={"X-Developer-Token": plaintext_token},
    )


def _api_envelope(resp) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text[:800]
    body = resp.json()
    assert isinstance(body, dict), body
    return body


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return int(raw)


def _env_str(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    return raw or None


@pytest.fixture
def f114_prep():
    """Env for API-01 / API-03 / API-04 / SYNC (bind + uploader + dept + SPACE knowledge)."""
    kid = _env_int("E2E_F114_KNOWLEDGE_ID")
    bind = _env_int("E2E_F114_BIND_USER_ID")
    up = _env_int("E2E_F114_UPLOADER_USER_ID")
    dept = _env_int("E2E_F114_DEPARTMENT_ID")
    if not all(v is not None for v in (kid, bind, up, dept)):
        pytest.skip(
            "Set E2E_F114_KNOWLEDGE_ID, E2E_F114_BIND_USER_ID, "
            "E2E_F114_UPLOADER_USER_ID, E2E_F114_DEPARTMENT_ID for filelib tests",
        )
    return {"knowledge_id": kid, "bind": bind, "uploader": up, "department_id": dept}


@pytest.fixture
def f114_prep_denied(f114_prep: dict[str, int]) -> dict[str, int]:
    """API-02: bind user must lack upload on K1; uploader still has upload."""
    denied = _env_int("E2E_F114_DENIED_USER_ID")
    if denied is None:
        pytest.skip(
            "Set E2E_F114_DENIED_USER_ID (user with no upload on E2E_F114_KNOWLEDGE_ID) for API-02",
        )
    return {**f114_prep, "denied": denied}


@pytest.fixture
def f114_prep_external(f114_prep: dict[str, int]) -> dict[str, int | str]:
    """API-03: user resolved by Query external_id (unique in DB)."""
    ext_uid = _env_int("E2E_F114_EXTERNAL_USER_ID")
    ext_id = _env_str("E2E_F114_EXTERNAL_ID")
    if ext_uid is None or not ext_id:
        pytest.skip(
            "Set E2E_F114_EXTERNAL_USER_ID and E2E_F114_EXTERNAL_ID (user.external_id unique) for API-03",
        )
    return {**f114_prep, "external_user_id": ext_uid, "external_id": ext_id}


@pytest.fixture
def f114_sync_prep(f114_prep: dict[str, int]) -> dict[str, Any]:
    """SYNC-01/02: file_sync_rule + sync params + bind user who can upload to the sync target.

    Token ``user_id`` for file/sync must pass ``_validate_file_sync_target`` (bound user can upload).
    That can differ from ``E2E_F114_BIND_USER_ID`` used in API-01/03/04 (U_bind vs U_up).
    """
    raw_rule = _env_str("E2E_F114_FILE_SYNC_RULE_JSON")
    dept_key = _env_str("E2E_F114_SYNC_DEPARTMENT_ID")
    sync_bind = _env_int("E2E_F114_SYNC_BIND_USER_ID")
    if not raw_rule or not dept_key or sync_bind is None:
        pytest.skip(
            "Set E2E_F114_FILE_SYNC_RULE_JSON, E2E_F114_SYNC_DEPARTMENT_ID, "
            "and E2E_F114_SYNC_BIND_USER_ID (user that may upload to the sync target) for SYNC tests",
        )
    try:
        rule_obj = json.loads(raw_rule)
    except json.JSONDecodeError as exc:
        pytest.fail(f"E2E_F114_FILE_SYNC_RULE_JSON is not valid JSON: {exc}")
    if not isinstance(rule_obj, dict):
        pytest.fail("E2E_F114_FILE_SYNC_RULE_JSON must be a JSON object")
    return {
        **f114_prep,
        "sync_bind_user_id": sync_bind,
        "file_sync_rule": rule_obj,
        "sync_department_id": dept_key,
    }


def test_tc_f114_adm_01_create_token_without_uploader_rejected():
    """TC-F114-ADM-01: POST admin developer-tokens without knowledge_uploader_user_id → 校验失败。"""
    name = PREFIX + "adm01-" + uuid.uuid4().hex[:8]
    with _admin_client() as client:
        resp = client.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": name,
                "user_id": ADMIN_USER_ID,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
                # intentional: no knowledge_uploader_user_id
            },
        )
    # RequestValidationError: 全局处理器用 HTTP 200 包一层, 业务层 status_code=422 (与 main.handle_request_validation_error 一致)
    assert resp.status_code == 200, resp.text[:500]
    body = resp.json()
    assert body.get("status_code") == 422, body
    assert body.get("status_message") is not None


def test_tc_f114_api_01_upload_records_uploader_not_bind_user(f114_prep: dict[str, int]):
    """TC-F114-API-01: 无 external_id 时 KnowledgeFile.user_id / original_uploader_id = U_up。"""
    from sqlalchemy import text

    knowledge_id = f114_prep["knowledge_id"]
    bind_uid = f114_prep["bind"]
    up_uid = f114_prep["uploader"]
    department_id = f114_prep["department_id"]
    token_name = PREFIX + "api01-" + uuid.uuid4().hex[:8]
    mark = PREFIX + uuid.uuid4().hex[:8] + ".txt"

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": bind_uid,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_row = env["data"]["token"]
        token_id = int(token_row["id"])

    try:
        content = f"e2e f114 api-01 {mark}\n".encode()
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {
            "knowledge_id": str(knowledge_id),
            "metadata": "{}",
            "split_mode": "auto",
        }
        with _filelib_client(plaintext) as fl:
            resp = fl.post("/api/v2/filelib/chunks", data=data, files=files)
        env = _api_envelope(resp)
        assert env.get("status_code") == 200, env

        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, user_id, original_uploader_id, file_name
                    FROM knowledgefile
                    WHERE knowledge_id = :kid AND file_name = :fn AND deleted_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"kid": knowledge_id, "fn": mark},
            ).one_or_none()
        assert row is not None, "knowledgefile row not found"
        assert int(row.user_id) == int(up_uid)
        assert int(row.original_uploader_id or 0) == int(up_uid)
    finally:
        with _admin_client() as admin:
            admin.delete(f"/api/v1/admin/developer-tokens/{token_id}")


def test_tc_f114_api_04_dirty_token_missing_uploader_rejected(f114_prep: dict[str, int]):
    """TC-F114-API-04: DB 中 knowledge_uploader_user_id NULL 时上传拒绝 19815。"""
    from sqlalchemy import text

    knowledge_id = f114_prep["knowledge_id"]
    bind_uid = f114_prep["bind"]
    up_uid = f114_prep["uploader"]
    department_id = f114_prep["department_id"]
    token_name = PREFIX + "api04-" + uuid.uuid4().hex[:8]
    mark = PREFIX + uuid.uuid4().hex[:8] + "-dirty.txt"

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": bind_uid,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_id = int(env["data"]["token"]["id"])

    engine = _engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE developer_token SET knowledge_uploader_user_id = NULL WHERE id = :id",
                ),
                {"id": token_id},
            )

        content = b"dirty token upload\n"
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {"knowledge_id": str(knowledge_id), "metadata": "{}"}
        with _filelib_client(plaintext) as fl:
            resp = fl.post("/api/v2/filelib/chunks", data=data, files=files)
        assert resp.status_code == 422, resp.text[:800]
        body = resp.json()
        assert body.get("status_code") == 19815, body

        with engine.connect() as conn:
            cnt = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM knowledgefile
                    WHERE knowledge_id = :kid AND file_name = :fn
                    """,
                ),
                {"kid": knowledge_id, "fn": mark},
            ).scalar()
        assert int(cnt or 0) == 0
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM developer_token WHERE id = :id"), {"id": token_id})


def test_tc_f114_api_02_bind_denied_uploader_cannot_bypass(f114_prep_denied: dict[str, int]):
    """TC-F114-API-02: 绑定用户无 SPACE 上传权时拒绝; 上传人高权限不救场 (permission_user=绑定用户)."""
    from sqlalchemy import text

    knowledge_id = f114_prep_denied["knowledge_id"]
    denied_uid = f114_prep_denied["denied"]
    up_uid = f114_prep_denied["uploader"]
    department_id = f114_prep_denied["department_id"]
    token_name = PREFIX + "api02-" + uuid.uuid4().hex[:8]
    mark = PREFIX + uuid.uuid4().hex[:8] + "-api02.txt"

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": denied_uid,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_id = int(env["data"]["token"]["id"])

    try:
        content = f"e2e f114 api-02 {mark}\n".encode()
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {
            "knowledge_id": str(knowledge_id),
            "metadata": "{}",
            "split_mode": "auto",
        }
        with _filelib_client(plaintext) as fl:
            resp = fl.post("/api/v2/filelib/chunks", data=data, files=files)
        assert resp.status_code == 200, resp.text[:800]
        body = resp.json()
        assert body.get("status_code") == 18040, body

        with _engine().connect() as conn:
            cnt = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM knowledgefile
                    WHERE knowledge_id = :kid AND file_name = :fn AND deleted_at IS NULL
                    """,
                ),
                {"kid": knowledge_id, "fn": mark},
            ).scalar()
        assert int(cnt or 0) == 0
    finally:
        with _admin_client() as admin:
            admin.delete(f"/api/v1/admin/developer-tokens/{token_id}")


def test_tc_f114_api_03_external_id_record_user(f114_prep_external: dict[str, int | str]):
    """TC-F114-API-03: Query external_id 时文件归属为解析用户 U_ext, 而非配置上传人 U_up."""
    from sqlalchemy import text

    knowledge_id = int(f114_prep_external["knowledge_id"])
    bind_uid = int(f114_prep_external["bind"])
    up_uid = int(f114_prep_external["uploader"])
    department_id = int(f114_prep_external["department_id"])
    ext_uid = int(f114_prep_external["external_user_id"])
    external_id = str(f114_prep_external["external_id"])
    assert ext_uid != up_uid, "API-03 needs external user != knowledge uploader for a meaningful assertion"

    token_name = PREFIX + "api03-" + uuid.uuid4().hex[:8]
    mark = PREFIX + uuid.uuid4().hex[:8] + "-api03.txt"

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": bind_uid,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_id = int(env["data"]["token"]["id"])

    try:
        content = f"e2e f114 api-03 {mark}\n".encode()
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {
            "knowledge_id": str(knowledge_id),
            "metadata": "{}",
            "split_mode": "auto",
        }
        with _filelib_client(plaintext) as fl:
            resp = fl.post(
                "/api/v2/filelib/chunks",
                params={"external_id": external_id},
                data=data,
                files=files,
            )
        env = _api_envelope(resp)
        assert env.get("status_code") == 200, env

        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, user_id, original_uploader_id, file_name
                    FROM knowledgefile
                    WHERE knowledge_id = :kid AND file_name = :fn AND deleted_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                ),
                {"kid": knowledge_id, "fn": mark},
            ).one_or_none()
        assert row is not None, "knowledgefile row not found"
        assert int(row.user_id) == ext_uid
        assert int(row.original_uploader_id or 0) == ext_uid
    finally:
        with _admin_client() as admin:
            admin.delete(f"/api/v1/admin/developer-tokens/{token_id}")


def _user_id_for_external_id(external_id: str) -> int | None:
    from sqlalchemy import text

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT user_id FROM user WHERE external_id = :e AND `delete` = 0 LIMIT 1",
            ),
            {"e": external_id.strip()},
        ).one_or_none()
    return int(row.user_id) if row is not None else None


def test_tc_f114_sync_01_responsible_overrides_uploader(f114_sync_prep: dict[str, Any]):
    """TC-F114-SYNC-01: 请求带责任人时落库归属责任人, 不为仅凭上传人配置."""
    from sqlalchemy import text

    responsible_ext = _env_str("E2E_F114_SYNC_RESPONSIBLE_EXTERNAL_ID")
    if not responsible_ext:
        pytest.skip(
            "Set E2E_F114_SYNC_RESPONSIBLE_EXTERNAL_ID (user.external_id of responsible person) for SYNC-01",
        )
    responsible_uid = _user_id_for_external_id(responsible_ext)
    if responsible_uid is None:
        pytest.fail(f"No active user with external_id={responsible_ext!r}")

    token_user = int(f114_sync_prep["sync_bind_user_id"])
    up_uid = int(f114_sync_prep["uploader"])
    department_id = int(f114_sync_prep["department_id"])
    file_sync_rule = f114_sync_prep["file_sync_rule"]
    sync_dept_id = str(f114_sync_prep["sync_department_id"])
    assert responsible_uid != up_uid, "SYNC-01 needs responsible user != knowledge uploader"

    token_name = PREFIX + "sync01-" + uuid.uuid4().hex[:8]
    mark = f"{PREFIX}sync01-{uuid.uuid4().hex[:8]}.txt"
    external_file_id = PREFIX + uuid.uuid4().hex[:16]

    params = {
        "external_file_id": external_file_id,
        "file_name": mark,
        "department_id": sync_dept_id,
        "responsible_person_id": responsible_ext,
    }

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": token_user,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
                "file_sync_rule": file_sync_rule,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_id = int(env["data"]["token"]["id"])

    try:
        content = f"e2e f114 sync-01 {mark}\n".encode()
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {"params": json.dumps(params, ensure_ascii=False)}
        with _filelib_client(plaintext) as fl:
            resp = fl.post("/api/v2/filelib/file/sync", data=data, files=files)
        env = _api_envelope(resp)
        assert env.get("status_code") == 200, env
        file_id = int(env["data"]["file_id"])

        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT user_id, original_uploader_id, file_name
                    FROM knowledgefile
                    WHERE id = :fid AND deleted_at IS NULL
                    """,
                ),
                {"fid": file_id},
            ).one_or_none()
        assert row is not None, "knowledgefile row missing after sync"
        assert int(row.user_id) == responsible_uid
        assert int(row.original_uploader_id or 0) == responsible_uid
    finally:
        with _admin_client() as admin:
            admin.delete(f"/api/v1/admin/developer-tokens/{token_id}")


def test_tc_f114_sync_02_fallback_uploader_when_no_responsible(f114_sync_prep: dict[str, Any]):
    """TC-F114-SYNC-02: 不传责任人时回落为令牌配置的知识上传人 (见 FilelibSyncService._resolve_responsible_user)."""
    from sqlalchemy import text

    token_user = int(f114_sync_prep["sync_bind_user_id"])
    up_uid = int(f114_sync_prep["uploader"])
    department_id = int(f114_sync_prep["department_id"])
    file_sync_rule = f114_sync_prep["file_sync_rule"]
    sync_dept_id = str(f114_sync_prep["sync_department_id"])

    token_name = PREFIX + "sync02-" + uuid.uuid4().hex[:8]
    mark = f"{PREFIX}sync02-{uuid.uuid4().hex[:8]}.txt"
    external_file_id = PREFIX + uuid.uuid4().hex[:16]

    params = {
        "external_file_id": external_file_id,
        "file_name": mark,
        "department_id": sync_dept_id,
    }

    with _admin_client() as admin:
        created = admin.post(
            "/api/v1/admin/developer-tokens",
            json={
                "name": token_name,
                "user_id": token_user,
                "knowledge_uploader_user_id": up_uid,
                "department_id": department_id,
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
                "file_sync_rule": file_sync_rule,
            },
        )
        env = _api_envelope(created)
        assert env.get("status_code") == 200, env
        plaintext = env["data"]["plaintext_token"]
        token_id = int(env["data"]["token"]["id"])

    try:
        content = f"e2e f114 sync-02 {mark}\n".encode()
        files = {"file": (mark, io.BytesIO(content), "text/plain")}
        data = {"params": json.dumps(params, ensure_ascii=False)}
        with _filelib_client(plaintext) as fl:
            resp = fl.post("/api/v2/filelib/file/sync", data=data, files=files)
        env = _api_envelope(resp)
        assert env.get("status_code") == 200, env
        file_id = int(env["data"]["file_id"])

        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT user_id, original_uploader_id, file_name
                    FROM knowledgefile
                    WHERE id = :fid AND deleted_at IS NULL
                    """,
                ),
                {"fid": file_id},
            ).one_or_none()
        assert row is not None, "knowledgefile row missing after sync"
        assert int(row.user_id) == up_uid
        assert int(row.original_uploader_id or 0) == up_uid
    finally:
        with _admin_client() as admin:
            admin.delete(f"/api/v1/admin/developer-tokens/{token_id}")
