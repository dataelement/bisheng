from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from bisheng.user.application import runtime_identity
from bisheng.user.application.avatar import read_visible_user_avatar_urls
from bisheng.user.domain.services import user as user_service


def _person(user_id: int, avatar: str | None, *, deleted: int = 0) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, avatar=avatar, delete=deleted)


async def test_signs_only_active_unambiguous_users_in_requested_tenant(monkeypatch):
    rows = AsyncMock(
        return_value=[
            (_person(10, "avatar/10/current.png"), 2),
            (_person(11, "avatar/11/other.png"), 3),
            (_person(12, "avatar/12/disabled.png", deleted=1), 2),
            (_person(13, "avatar/13/ambiguous.png"), 2),
            (_person(13, "avatar/13/ambiguous.png"), 3),
            (_person(15, "  "), 2),
            (_person(16, "avatar/16/no_active_tenant.png"), None),
        ]
    )
    sign = AsyncMock(return_value="/object/bucket/avatar/10/current.png?signature=one")
    monkeypatch.setattr(runtime_identity, "current_person_rows", rows)
    monkeypatch.setattr(runtime_identity.settings.multi_tenant, "enabled", True)
    monkeypatch.setattr(user_service.UserService, "get_avatar_share_link", sign)
    pairs = [(2, 10), (2, 10), (3, 10), (2, 11), (2, 12), (2, 13), (2, 14), (2, 15), (2, 16), (2, 0)]

    assert await read_visible_user_avatar_urls(pairs) == {(2, 10): "/object/bucket/avatar/10/current.png?signature=one"}
    rows.assert_awaited_once()
    assert set(rows.await_args.args[0]) == {10, 11, 12, 13, 14, 15, 16}
    sign.assert_awaited_once_with("avatar/10/current.png")


async def test_avatar_signing_failure_preserves_other_users_in_single_tenant(monkeypatch):
    rows = AsyncMock(return_value=[(_person(10, "first.png"), None), (_person(11, "second.png"), None)])
    monkeypatch.setattr(runtime_identity, "current_person_rows", rows)
    monkeypatch.setattr(runtime_identity.settings.multi_tenant, "enabled", False)

    async def sign(avatar):
        if avatar == "first.png":
            raise OSError("storage unavailable")
        return "/object/bucket/second.png"

    monkeypatch.setattr(user_service.UserService, "get_avatar_share_link", sign)

    assert await read_visible_user_avatar_urls([(1, 10), (3, 10), (1, 11)]) == {(1, 11): "/object/bucket/second.png"}


async def test_avatar_identity_lookup_failure_does_not_sign(monkeypatch):
    rows = AsyncMock(side_effect=OperationalError("SELECT", {}, OSError("unavailable")))
    sign = AsyncMock()
    monkeypatch.setattr(runtime_identity, "current_person_rows", rows)
    monkeypatch.setattr(user_service.UserService, "get_avatar_share_link", sign)

    assert await read_visible_user_avatar_urls([(2, 10)]) == {}
    sign.assert_not_awaited()


@pytest.mark.parametrize(
    "stored_avatar",
    [
        "avatar/10/picture.png",
        "/public-bucket/avatar/10/picture.png?signature=expired",
        "/object/public-bucket/avatar/10/picture.png?signature=expired",
        "/workspace/object/public-bucket/avatar/10/picture.png?signature=expired",
    ],
)
async def test_supported_object_references_are_signed_again(monkeypatch, stored_avatar):
    signed = "/object/public-bucket/avatar/10/picture.png?signature=fresh"
    storage = SimpleNamespace(bucket="public-bucket", get_share_link=AsyncMock(return_value=signed))
    monkeypatch.setattr(user_service, "get_minio_storage", AsyncMock(return_value=storage))

    assert await user_service.UserService.get_avatar_share_link(stored_avatar) == signed
    storage.get_share_link.assert_awaited_once_with("avatar/10/picture.png")


async def test_legacy_external_avatar_keeps_its_url(monkeypatch):
    storage = SimpleNamespace(bucket="public-bucket", get_share_link=AsyncMock())
    monkeypatch.setattr(user_service, "get_minio_storage", AsyncMock(return_value=storage))
    avatar = "https://profiles.example/portrait.png?size=80"

    assert await user_service.UserService.get_avatar_share_link(avatar) == avatar
    storage.get_share_link.assert_not_awaited()
