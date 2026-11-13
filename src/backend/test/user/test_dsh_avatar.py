"""DSH avatar adapter validates current membership before signing current data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.user.domain.services import dsh_avatar


@pytest.fixture
def avatar_dependencies(monkeypatch):
    # Only signing tests need the full user service; cold-import guards run in
    # a fresh subprocess and must not rely on pytest's already imported modules.
    from bisheng.user.domain.services import user as user_module

    person = AsyncMock(return_value=(SimpleNamespace(user_id=1001, avatar="avatar/first.png"), 2))
    storage = SimpleNamespace(bucket="bisheng", get_share_link=AsyncMock())
    storage.get_share_link.side_effect = lambda name: f"https://objects.example/{name}?signed=current"
    storage_factory = AsyncMock(return_value=storage)
    monkeypatch.setattr(dsh_avatar, "current_runtime_person", person)
    monkeypatch.setattr(user_module, "get_minio_storage", storage_factory)
    return person, storage, storage_factory


async def test_reads_and_signs_current_avatar_on_every_call(avatar_dependencies):
    person, storage, storage_factory = avatar_dependencies
    user = person.return_value[0]
    for avatar in ("avatar/first.png", "avatar/updated.png", "", None):
        user.avatar = avatar
        result = await dsh_avatar.read_dsh_avatar("2", "1001")
        assert result == (f"https://objects.example/{avatar}?signed=current" if avatar else None)
    assert person.await_count == 4
    person.assert_awaited_with(1001)
    assert storage_factory.await_count == storage.get_share_link.await_count == 2
    assert [call.args for call in storage.get_share_link.await_args_list] == [
        ("avatar/first.png",),
        ("avatar/updated.png",),
    ]


@pytest.mark.parametrize("avatar", [None, ""])
async def test_missing_avatar_never_constructs_storage(avatar_dependencies, avatar):
    person, storage, storage_factory = avatar_dependencies
    person.return_value[0].avatar = avatar
    assert await dsh_avatar.read_dsh_avatar("2", "1001") is None
    storage_factory.assert_not_awaited()
    storage.get_share_link.assert_not_awaited()


@pytest.mark.parametrize(
    "row",
    [
        None,  # Missing, disabled, inactive tenant, or ambiguous membership is rejected by the repository.
        (SimpleNamespace(user_id=1002, avatar="avatar/foreign.png"), 2),
        (SimpleNamespace(user_id=1001, avatar="avatar/foreign.png"), 3),
    ],
)
async def test_foreign_or_unavailable_person_never_signs(avatar_dependencies, row):
    person, storage, storage_factory = avatar_dependencies
    person.return_value = row
    with pytest.raises(DshUserDisabledError):
        await dsh_avatar.read_dsh_avatar("2", "1001")
    person.assert_awaited_once_with(1001)
    storage_factory.assert_not_awaited()
    storage.get_share_link.assert_not_awaited()


async def test_membership_change_between_reads_refuses_old_tenant(avatar_dependencies):
    person, storage, _ = avatar_dependencies
    assert await dsh_avatar.read_dsh_avatar("2", "1001")
    user = person.return_value[0]
    person.return_value = (user, 3)
    with pytest.raises(DshUserDisabledError):
        await dsh_avatar.read_dsh_avatar("2", "1001")
    storage.get_share_link.assert_awaited_once_with("avatar/first.png")
    assert await dsh_avatar.read_dsh_avatar("3", "1001")
    assert storage.get_share_link.await_count == 2


async def test_signing_failure_propagates_without_raw_path_fallback(avatar_dependencies):
    _, storage, _ = avatar_dependencies
    storage.get_share_link.side_effect = RuntimeError("object signing unavailable")
    with pytest.raises(RuntimeError, match="object signing unavailable"):
        await dsh_avatar.read_dsh_avatar("2", "1001")
    storage.get_share_link.assert_awaited_once_with("avatar/first.png")


async def test_identity_read_failure_propagates_without_storage_access(avatar_dependencies):
    person, _, storage_factory = avatar_dependencies
    person.side_effect = RuntimeError("identity unavailable")
    with pytest.raises(RuntimeError, match="identity unavailable"):
        await dsh_avatar.read_dsh_avatar("2", "1001")
    storage_factory.assert_not_awaited()


async def test_existing_signed_avatar_is_renewed_using_user_service_normalization(avatar_dependencies):
    person, storage, _ = avatar_dependencies
    person.return_value[0].avatar = "https://old.example/bisheng/avatar/photo%20one.png?expired=1"
    assert await dsh_avatar.read_dsh_avatar("2", "1001") == (
        "https://objects.example/avatar/photo one.png?signed=current"
    )
    storage.get_share_link.assert_awaited_once_with("avatar/photo one.png")
