"""Annotation task identifiers are not read capabilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.api.v1 import mark_task as endpoint
from bisheng.common.errcode.http_error import UnAuthorizedError


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_user", {"task_id": 1}),
        ("get_record", {"task_id": 1, "chat_id": "chat"}),
        ("get_status", {"task_id": 1, "chat_id": "chat"}),
    ],
)
async def test_unassigned_user_denied_before_mark_data(monkeypatch, name, args):
    monkeypatch.setattr(
        endpoint.MarkTaskDao,
        "get_task_byid",
        lambda _: SimpleNamespace(id=1, tenant_id=7, create_id=22, process_users="22,33", app_id="app"),
    )
    effect = MagicMock()
    monkeypatch.setattr(endpoint.MarkRecordDao, "get_record", effect)
    monkeypatch.setattr(endpoint.UserDao, "get_user", effect)
    actor = SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: False)
    with pytest.raises(UnAuthorizedError):
        await getattr(endpoint, name)(login_user=actor, **args)
    effect.assert_not_called()


@pytest.mark.parametrize("path", ["/mark/get_user?task_id=1", "/mark/get_record?task_id=1&chat_id=chat"])
def test_anonymous_mark_reads_require_login(monkeypatch, path):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from bisheng.common.dependencies.user_deps import UserPayload

    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")

    def deny():
        raise HTTPException(status_code=401)

    app.dependency_overrides[UserPayload.get_login_user] = deny
    effect = MagicMock()
    monkeypatch.setattr(endpoint.MarkTaskDao, "get_task_byid", effect)
    with TestClient(app) as client:
        assert client.get("/api/v1" + path).status_code == 401
    effect.assert_not_called()


@pytest.mark.parametrize("role", ["creator", "assignee", "admin"])
def test_actual_task_readers_keep_access(monkeypatch, role):
    from bisheng.chat_session.domain.services import mark_read_authorization as policy

    monkeypatch.setattr(
        policy.MarkTaskDao,
        "get_task_byid",
        lambda _: SimpleNamespace(
            id=1,
            tenant_id=7,
            create_id=11 if role == "creator" else 22,
            process_users="11" if role == "assignee" else "22",
            app_id="app",
        ),
    )
    assert (
        policy.require_mark_task_reader(
            1, SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: role == "admin")
        ).id
        == 1
    )


@pytest.mark.parametrize("tenant,flow", [(8, "app"), (7, "other")])
def test_task_reader_cannot_select_unrelated_chat(monkeypatch, tenant, flow):
    from bisheng.chat_session.domain.services import mark_read_authorization as policy

    monkeypatch.setattr(
        policy.MarkTaskDao,
        "get_task_byid",
        lambda _: SimpleNamespace(id=1, tenant_id=7, create_id=11, process_users="11", app_id="app"),
    )
    monkeypatch.setattr(
        policy.MessageSessionDao, "get_one", lambda _: SimpleNamespace(tenant_id=tenant, flow_id=flow, is_delete=False)
    )
    with pytest.raises(UnAuthorizedError):
        policy.require_mark_task_reader(1, SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: False), "chat")
