"""Exercise upload and historical notification on the real HTTP routes with isolated fixtures."""

from base64 import b64decode
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.message.api.dependencies import get_message_service
from bisheng.message.api.endpoints.message_endpoint import router as message_router
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.services.message_service import MessageService
from bisheng.user.api.user import router as user_router
from bisheng.user.application import avatar
from bisheng.user.domain.services import user as user_service
from test.e2e.helpers.api import assert_resp_200
from test.e2e.helpers.auth import auth_headers


async def test_upload_changes_the_visible_avatar_on_an_already_received_notification(monkeypatch):
    sender = SimpleNamespace(user_id=11, user_name="e2e-avatar-sender", delete=0, avatar=None)
    notice = InboxMessage(
        id=20,
        sender=sender.user_id,
        receiver=[12],
        tenant_id=3,
        content=[],
        message_type=MessageTypeEnum.NOTIFY,
        status=MessageStatusEnum.APPROVED,
    )

    async def messages(*, user_id, **kwargs):
        return [notice] if user_id in notice.receiver else []

    async def count(**kwargs):
        return len(await messages(**kwargs))

    async def sign(object_name):
        return f"/object/test-bucket/{object_name}?signature=test"

    app = FastAPI()
    app.include_router(user_router, prefix="/api/v1")
    app.include_router(message_router, prefix="/api/v1/message")
    service = MessageService(
        SimpleNamespace(find_messages_by_receiver=messages, count_messages_by_receiver=count),
        SimpleNamespace(get_read_message_ids=AsyncMock(return_value=[])),
    )

    async def identity(request: Request):
        account = request.cookies.get("access_token_cookie")
        user_id = {"e2e-avatar-sender": 11, "e2e-avatar-receiver": 12, "e2e-avatar-other": 13}.get(account)
        if user_id is None:
            raise HTTPException(401)
        return SimpleNamespace(user_id=user_id)

    app.dependency_overrides[user_service.LoginUser.get_login_user] = identity
    app.dependency_overrides[UserPayload.get_login_user] = identity
    app.dependency_overrides[get_message_service] = lambda: service
    storage = SimpleNamespace(bucket="test-bucket", get_share_link=sign, put_object=AsyncMock())
    monkeypatch.setattr(user_service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(user_service.UserDao, "aget_user", AsyncMock(return_value=sender))
    monkeypatch.setattr(user_service.UserDao, "aget_user_by_ids", AsyncMock(return_value=[sender]))
    monkeypatch.setattr(user_service.UserDao, "aupdate_user", AsyncMock())
    monkeypatch.setattr(avatar, "read_current_person_records", AsyncMock(return_value={11: (sender, "active", 3)}))

    receiver_headers = auth_headers("e2e-avatar-receiver")
    path = "/api/v1/message/list?tab=notify"
    png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://avatar.test") as client:
        before = assert_resp_200(await client.get(path, headers=receiver_headers))["data"][0]
        assert before["sender_avatar"] is None
        upload = assert_resp_200(
            await client.post(
                "/api/v1/user/avatar",
                headers=auth_headers("e2e-avatar-sender"),
                files={"file": ("avatar.png", png, "image/png")},
            )
        )
        after = assert_resp_200(await client.get(path, headers=receiver_headers))["data"][0]
        assert after["id"] == before["id"] == notice.id
        assert after["is_read"] is before["is_read"] is False
        assert after["sender_avatar"] == upload["avatar"]
        assert assert_resp_200(await client.get(path, headers=auth_headers("e2e-avatar-other")))["data"] == []
        assert (await client.get(path)).status_code == 401
