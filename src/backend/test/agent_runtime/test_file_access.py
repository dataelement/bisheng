"""F078 T32: who may download a deliverable file."""

from types import SimpleNamespace

import pytest

import bisheng.agent_runtime.domain.services.file_access as file_access
from bisheng.agent_runtime.domain.services.file_access import resolve_deliverable_url
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from test.linsight.fixtures.fake_minio import FakeMinioStorage


class _Minio(FakeMinioStorage):
    async def get_share_link(self, object_name, bucket=None, clear_host=True, expire_days=7):
        return f"/signed/{bucket or self.bucket}/{object_name}"


class _TmpSessions:
    def __init__(self, owners):
        self.owners = owners

    async def aowner_of(self, tmp_id):
        return self.owners.get(tmp_id)


@pytest.fixture
def minio():
    return _Minio()


def _user(user_id=7):
    return SimpleNamespace(user_id=user_id)


class TestFormalSession:
    async def test_owner_gets_a_signed_link(self, monkeypatch, minio):
        calls = {}

        async def _resolve(chat_id, file_id, login_user):
            calls["args"] = (chat_id, file_id, login_user.user_id)
            return "/signed/bisheng/chat/7/agent/c1/f1.docx"

        monkeypatch.setattr(file_access.ChatSessionService, "resolve_attachment_url", _resolve)
        url = await resolve_deliverable_url("c1", "f1", _user(), minio=minio, tmp_sessions=_TmpSessions({}))
        assert url == "/signed/bisheng/chat/7/agent/c1/f1.docx"
        assert calls["args"] == ("c1", "f1", 7)

    async def test_ownership_failure_propagates(self, monkeypatch, minio):
        async def _resolve(chat_id, file_id, login_user):
            raise NotFoundError.http_exception()

        monkeypatch.setattr(file_access.ChatSessionService, "resolve_attachment_url", _resolve)
        with pytest.raises(Exception) as exc_info:
            await resolve_deliverable_url("c1", "f1", _user(8), minio=minio, tmp_sessions=_TmpSessions({}))
        assert getattr(exc_info.value, "status_code", None) == NotFoundError.Code


class TestTempSession:
    def _store(self, minio, tmp_id="t1", file_id="f1"):
        minio.put_object_sync(
            bucket_name=minio.tmp_bucket, object_name=f"agent_runtime/tmp-{tmp_id}/{file_id}.docx", file=b"x"
        )

    async def test_owner_downloads_from_the_tmp_bucket(self, minio):
        self._store(minio)
        url = await resolve_deliverable_url(
            "tmp-t1", "f1", _user(7), minio=minio, tmp_sessions=_TmpSessions({"t1": {"user_id": 7, "tenant_id": 2}})
        )
        assert url == f"/signed/{minio.tmp_bucket}/agent_runtime/tmp-t1/f1.docx"

    async def test_another_user_is_refused(self, minio):
        self._store(minio)
        with pytest.raises(Exception) as exc_info:
            await resolve_deliverable_url(
                "tmp-t1", "f1", _user(8), minio=minio, tmp_sessions=_TmpSessions({"t1": {"user_id": 7}})
            )
        assert getattr(exc_info.value, "status_code", None) == UnAuthorizedError.Code

    async def test_expired_registration_is_refused(self, minio):
        self._store(minio)
        with pytest.raises(Exception) as exc_info:
            await resolve_deliverable_url("tmp-t1", "f1", _user(7), minio=minio, tmp_sessions=_TmpSessions({}))
        assert getattr(exc_info.value, "status_code", None) == UnAuthorizedError.Code

    async def test_unknown_file_id_is_not_found(self, minio):
        self._store(minio)
        with pytest.raises(Exception) as exc_info:
            await resolve_deliverable_url(
                "tmp-t1", "nope", _user(7), minio=minio, tmp_sessions=_TmpSessions({"t1": {"user_id": 7}})
            )
        assert getattr(exc_info.value, "status_code", None) == NotFoundError.Code


@pytest.mark.parametrize("session_key,file_id", [("../c1", "f1"), ("c1", "../f1"), ("tmp-", "f1"), ("c 1", "f1")])
async def test_unsafe_identifiers_are_not_found(minio, session_key, file_id):
    with pytest.raises(Exception) as exc_info:
        await resolve_deliverable_url(session_key, file_id, _user(), minio=minio, tmp_sessions=_TmpSessions({}))
    assert getattr(exc_info.value, "status_code", None) == NotFoundError.Code


class TestSessionDeletion:
    async def test_deleting_a_session_removes_its_agent_workspaces(self, monkeypatch, minio):
        import bisheng.chat_session.domain.chat as chat_module

        minio.put_object_sync(object_name="workspace/agent/c1/wf-n1/output/a.md", file=b"a")
        minio.put_object_sync(object_name="workspace/agent/c2/wf-n1/output/a.md", file=b"b")

        async def _minio():
            return minio

        monkeypatch.setattr(chat_module, "get_minio_storage", _minio)
        await chat_module.ChatSessionService._remove_agent_workspaces("c1")
        assert minio.keys("workspace/agent/") == ["workspace/agent/c2/wf-n1/output/a.md"]

    async def test_unsafe_chat_id_is_ignored(self, monkeypatch, minio):
        import bisheng.chat_session.domain.chat as chat_module

        async def _minio():
            return minio

        monkeypatch.setattr(chat_module, "get_minio_storage", _minio)
        await chat_module.ChatSessionService._remove_agent_workspaces("../etc")


def test_endpoint_redirects_to_the_signed_link(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import bisheng.agent_runtime.api.endpoints.files as files_endpoint
    from bisheng.agent_runtime.api.router import router
    from bisheng.common.dependencies.user_deps import UserPayload

    async def _resolve(session_key, file_id, login_user):
        return f"/signed/{session_key}/{file_id}"

    monkeypatch.setattr(files_endpoint, "aresolve_deliverable_url", _resolve)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7)
    response = TestClient(app).get("/api/v1/agent-runtime/files/c1/f1", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/signed/c1/f1"
