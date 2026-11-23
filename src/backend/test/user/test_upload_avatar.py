from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from bisheng.user.domain.services import user as user_service


def upload() -> UploadFile:
    return UploadFile(BytesIO(b"test avatar"), headers=Headers({"content-type": "image/png"}))


@pytest.fixture
def dependencies(monkeypatch):
    user = SimpleNamespace(delete=0, avatar="avatar/8/previous.png")
    storage = SimpleNamespace(
        get_share_link=AsyncMock(return_value="/object/bisheng/avatar/8/new.png"), put_object=AsyncMock()
    )
    store_profile = AsyncMock()
    monkeypatch.setattr(user_service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(user_service.UserDao, "aget_user", AsyncMock(return_value=user))
    monkeypatch.setattr(user_service.UserDao, "aupdate_user", store_profile)
    return user, storage, store_profile


@pytest.mark.parametrize("operation", ["get_share_link", "put_object"])
async def test_storage_failure_keeps_existing_avatar(dependencies, operation):
    user, storage, store_profile = dependencies
    getattr(storage, operation).side_effect = OSError("storage unavailable")

    with pytest.raises(OSError, match="storage unavailable"):
        await user_service.UserService.update_avatar(8, upload())

    store_profile.assert_not_awaited()
    assert user.avatar == "avatar/8/previous.png"


async def test_successful_upload_persists_the_object_key_and_returns_the_url(dependencies):
    user, storage, store_profile = dependencies

    url = await user_service.UserService.update_avatar(8, upload())

    assert url == storage.get_share_link.return_value
    assert user.avatar.startswith("avatar/8/") and user.avatar.endswith(".png")
    storage.get_share_link.assert_awaited_once_with(user.avatar)
    storage.put_object.assert_awaited_once_with(object_name=user.avatar, file=b"test avatar", content_type="image/png")
    store_profile.assert_awaited_once_with(user)
