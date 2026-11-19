from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.schemas.message_schema import TabTypeEnum
from bisheng.message.domain.services import message_service


def _message(message_id: int, tenant_id: int, sender: int, content: list[dict] | None = None) -> InboxMessage:
    return InboxMessage(
        id=message_id,
        tenant_id=tenant_id,
        sender=sender,
        receiver=[40],
        message_type=MessageTypeEnum.NOTIFY,
        status=MessageStatusEnum.APPROVED,
        content=content or [],
    )


async def test_notification_list_adds_current_visible_sender_avatar_without_mutating_messages(monkeypatch):
    snapshot = [
        {"type": "user", "content": "@Historical", "metadata": {"user_id": 11, "avatar": "/old-1"}},
        {"type": "user", "content": "@Legacy", "metadata": {"user_id": "11", "user_avatar": "/old-2", "keep": 1}},
        {"type": "user", "content": "@Unknown", "metadata": {"avatar": "/old-3", "user_avatar": "/old-4"}},
        {"type": "user", "content": "@Old record", "metadata": "legacy value"},
        {"type": "system_text", "content": "action"},
    ]
    messages = [
        _message(101, 2, 10, snapshot),
        _message(102, 3, 10, snapshot),
        _message(103, 2, 11),
        _message(104, 2, 0, snapshot),
    ]
    repository = SimpleNamespace(
        find_messages_by_receiver=AsyncMock(return_value=messages),
        count_messages_by_receiver=AsyncMock(return_value=len(messages)),
    )
    reads = SimpleNamespace(get_read_message_ids=AsyncMock(return_value=[101]), mark_as_read=AsyncMock())
    service = message_service.MessageService(repository, reads)
    find_senders = AsyncMock(
        return_value=[SimpleNamespace(user_id=10, user_name="Same"), SimpleNamespace(user_id=11, user_name="Same")]
    )
    group_names = AsyncMock(return_value={11: ["Readers"]})
    monkeypatch.setattr(message_service.UserDao, "aget_user_by_ids", find_senders)
    monkeypatch.setattr(service, "_build_user_group_name_map", group_names)
    first_avatar = "/object/public-bucket/avatar/10/one.png?signature=first"
    second_avatar = "/object/public-bucket/avatar/10/two.png?signature=second"
    same_name_avatar = "/object/public-bucket/avatar/11/other.png?signature=first"
    avatar_queries = []

    async def read_avatars(pairs):
        avatar_queries.append(list(pairs))
        avatar = first_avatar if len(avatar_queries) == 1 else second_avatar
        return {(2, 10): avatar, (2, 11): same_name_avatar}

    monkeypatch.setattr(message_service, "read_visible_user_avatar_urls", read_avatars)
    # The recipient's own tenant differs from the notification tenants.
    recipient = SimpleNamespace(user_id=40, tenant_id=99)

    first = (await service.get_message_list(recipient, tab=TabTypeEnum.NOTIFY)).model_dump()
    reopened = (await service.get_message_list(recipient, tab=TabTypeEnum.NOTIFY)).model_dump()

    assert avatar_queries == [[(2, 10), (3, 10), (2, 11)]] * 2
    assert [row["sender_avatar"] for row in first["data"]] == [first_avatar, None, same_name_avatar, None]
    assert [row["sender_avatar"] for row in reopened["data"]] == [second_avatar, None, same_name_avatar, None]
    assert [row["sender_name"] for row in reopened["data"]] == ["Same", "Same", "Same", None]
    assert [row["is_read"] for row in reopened["data"]] == [True, False, False, False]
    assert reopened["total"] == len(messages)
    assert repository.find_messages_by_receiver.await_args.kwargs["user_id"] == 40
    reads.mark_as_read.assert_not_awaited()
    assert snapshot[0]["metadata"]["avatar"] == "/old-1"
    for row in [reopened["data"][0], reopened["data"][1], reopened["data"][3]]:
        assert row["content"][0]["metadata"] == {"user_id": 11, "group_names": ["Readers"]}
        assert row["content"][1]["metadata"] == {"user_id": "11", "keep": 1}
        assert row["content"][2]["metadata"] == {}
        assert row["content"][3:] == snapshot[3:]
