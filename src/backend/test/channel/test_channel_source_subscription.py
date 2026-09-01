"""F060 — channel writes desired sources without remote subscription side effects.

These cover the hot-path half of the feature (spec §7.3):
- create/update persist desired sources and refresh public display metadata best-effort;
- subscribe/unsubscribe is owned exclusively by periodic platform reconciliation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
    UpdateChannelRequest,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import (
    MembershipStatusEnum,
    UserRoleEnum,
)

_CS = "bisheng.channel.domain.services.channel_service"


@pytest.fixture(autouse=True)
def _stub_channel_quota():
    with patch(
        f"{_CS}.QuotaService.get_effective_quota",
        new=AsyncMock(return_value=-1),
    ):
        yield


class _LoginUser:
    user_id = 7
    user_name = "operator"
    tenant_id = 1

    def is_admin(self):
        return False


def _info_source_rows(ids):
    """Rows as returned by channel_info_source_repository.find_by_ids (only .id is read)."""
    return [SimpleNamespace(id=i) for i in ids]


def _info_source_meta(sid):
    """A metadata payload as returned by get_information_source_by_ids."""
    return SimpleNamespace(
        id=sid,
        name=f"name-{sid}",
        icon=None,
        business_type="rss",
        description=None,
    )


def _service(*, channel_repository, member_repository, info_source_repository):
    return ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=info_source_repository,
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )


def _permission_adapter():
    return SimpleNamespace(
        authorize_created=AsyncMock(),
        load_permission_record=AsyncMock(return_value=SimpleNamespace(tenant_id=1)),
        project_delete=AsyncMock(),
    )


# --------------------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_never_subscribes_and_refreshes_public_metadata():
    created = SimpleNamespace(
        id="channel-1",
        source_list=["A", "B"],
        tenant_id=1,
    )
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=created))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        add_member=AsyncMock(),
    )
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=_info_source_rows(["A"])),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[_info_source_meta("A"), _info_source_meta("B")]),
    )
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name="资讯频道",
                source_list=["A", "B"],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    info_client.subscribe_information_source.assert_not_awaited()
    info_client.get_information_source_by_ids.assert_awaited_once_with(["A", "B"])
    info_source_repository.upsert_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_metadata_failure_does_not_roll_back_channel():
    created = SimpleNamespace(
        id="channel-1",
        source_list=["A", "B"],
        tenant_id=1,
    )
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=created))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        add_member=AsyncMock(),
    )
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=_info_source_rows(["A", "B"])),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(side_effect=RuntimeError("metadata unavailable")),
    )
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name="资讯频道",
                source_list=["A", "B"],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    info_client.subscribe_information_source.assert_not_awaited()
    channel_repository.save.assert_awaited_once()
    member_repository.add_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_upserts_selected_source_metadata():
    created = SimpleNamespace(id="channel-1", source_list=["B"], tenant_id=1)
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=created))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        add_member=AsyncMock(),
    )
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[]),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[_info_source_meta("B")]),
    )
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name="资讯频道",
                source_list=["B"],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    info_client.get_information_source_by_ids.assert_awaited_once_with(["B"])
    info_client.subscribe_information_source.assert_not_awaited()
    info_source_repository.upsert_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_is_not_blocked_by_remote_subscription_limit():
    created = SimpleNamespace(id="channel-1", source_list=["B"], tenant_id=1)
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=created))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        add_member=AsyncMock(),
    )
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[]),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(side_effect=RuntimeError("must not be called")),
        get_information_source_by_ids=AsyncMock(side_effect=RuntimeError("metadata unavailable")),
    )
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name="资讯频道",
                source_list=["B"],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    info_client.subscribe_information_source.assert_not_awaited()
    channel_repository.save.assert_awaited_once()
    member_repository.add_member.assert_awaited_once()
    permission_adapter.authorize_created.assert_awaited_once()


# --------------------------------------------------------------------------- update


def _update_membership():
    return SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.CREATOR,
        user_id=7,
    )


@pytest.mark.asyncio
async def test_update_add_never_subscribes_and_refreshes_metadata():
    channel = SimpleNamespace(id="channel-1", name="c", source_list=["A"], visibility=ChannelVisibilityEnum.PUBLIC)
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(return_value=channel),
    )
    member_repository = SimpleNamespace(find_membership=AsyncMock(return_value=_update_membership()))

    async def _find_by_ids(ids):
        return _info_source_rows([i for i in ids if i in {"A", "B"}])

    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(side_effect=_find_by_ids),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(
            return_value=[_info_source_meta("A"), _info_source_meta("B"), _info_source_meta("C")]
        ),
    )

    with (
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.update_channel(
            "channel-1",
            UpdateChannelRequest(source_list=["A", "B", "C"]),
            _LoginUser(),
        )

    info_client.subscribe_information_source.assert_not_awaited()
    info_client.unsubscribe_information_source.assert_not_awaited()
    info_source_repository.upsert_metadata.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_remove_does_not_unsubscribe():
    """Removing a source from a channel never calls the information service. (AC-07)"""
    channel = SimpleNamespace(id="channel-1", name="c", source_list=["A", "B"], visibility=ChannelVisibilityEnum.PUBLIC)
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(return_value=channel),
    )
    member_repository = SimpleNamespace(find_membership=AsyncMock(return_value=_update_membership()))
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=_info_source_rows(["A"])),
        upsert_metadata=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service.update_channels_latest_article_time = AsyncMock()

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[]),
    )

    with (
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.update_channel(
            "channel-1",
            UpdateChannelRequest(source_list=["A"]),
            _LoginUser(),
        )

    info_client.unsubscribe_information_source.assert_not_awaited()
    info_client.subscribe_information_source.assert_not_awaited()


# --------------------------------------------------------------------------- dismiss


def _dismiss_service(channel):
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(
            return_value=SimpleNamespace(
                status=MembershipStatusEnum.ACTIVE,
                user_role=UserRoleEnum.CREATOR,
                user_id=7,
            )
        ),
        find_all=AsyncMock(return_value=[]),
        delete=AsyncMock(),
    )
    info_source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[]),
        batch_add=AsyncMock(),
        delete_by_ids=AsyncMock(),
    )
    service = _service(
        channel_repository=channel_repository,
        member_repository=member_repository,
        info_source_repository=info_source_repository,
    )
    service._authorized_channel_user_ids = AsyncMock(return_value=set())
    service._send_channel_event_notification = AsyncMock()
    return service, info_source_repository


@pytest.mark.asyncio
async def test_dismiss_does_not_unsubscribe():
    """Dismissing a channel never unsubscribes nor deletes channel_info_source rows. (AC-06)"""
    channel = SimpleNamespace(id="channel-1", name="c", source_list=["X"])
    service, info_source_repository = _dismiss_service(channel)

    info_client = SimpleNamespace(unsubscribe_information_source=AsyncMock())
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.dismiss_channel("channel-1", _LoginUser())

    info_client.unsubscribe_information_source.assert_not_awaited()
    info_source_repository.delete_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_dismiss_shared_source_stays_subscribed():
    """Source X is shared with another channel; dismissing one must not unsubscribe X. (AC-08)"""
    channel = SimpleNamespace(id="channel-A", name="A", source_list=["X"])
    service, info_source_repository = _dismiss_service(channel)

    info_client = SimpleNamespace(unsubscribe_information_source=AsyncMock())
    permission_adapter = _permission_adapter()

    with (
        patch(
            f"{_CS}.get_f048_resource_adapter",
            new=AsyncMock(return_value=permission_adapter),
        ),
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)),
    ):
        await service.dismiss_channel("channel-A", _LoginUser())

    # Dismiss no longer touches the information service at all, so a source still
    # referenced by channel B remains subscribed.
    info_client.unsubscribe_information_source.assert_not_awaited()
    info_source_repository.delete_by_ids.assert_not_awaited()


# --------------------------------------------------- channel_info_source batch_add


@pytest.mark.asyncio
async def test_batch_add_idempotent_on_integrity_error():
    """A concurrent duplicate-id insert is recovered: rollback, drop existing, retry new only."""
    from sqlalchemy.exc import IntegrityError

    from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )

    added_batches: list[list[str]] = []
    commits = {"n": 0}

    class _Result:
        def all(self):
            # On the post-conflict re-query, 'A' is reported as already present.
            return [ChannelInfoSource(id="A", source_name="a", source_type="rss")]

    async def _commit():
        commits["n"] += 1
        if commits["n"] == 1:
            raise IntegrityError("duplicate", None, Exception("duplicate"))

    session = SimpleNamespace(
        add_all=lambda rows: added_batches.append([r.id for r in rows]),
        commit=_commit,
        rollback=AsyncMock(),
        exec=AsyncMock(return_value=_Result()),
    )

    repo = ChannelInfoSourceRepositoryImpl(session)
    await repo.batch_add(
        [
            ChannelInfoSource(id="A", source_name="a", source_type="rss"),
            ChannelInfoSource(id="B", source_name="b", source_type="rss"),
        ]
    )

    assert added_batches[0] == ["A", "B"]  # first attempt: both
    assert added_batches[1] == ["B"]  # retry: only the genuinely-new one
    assert commits["n"] == 2
    session.rollback.assert_awaited_once()
