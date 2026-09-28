"""Transactional repository behavior for E+ durable message processing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusChatType,
    EPlusConnectionStatus,
    EPlusConversation,
    EPlusConversationStatus,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusMessageType,
    EPlusReplyStatus,
)
from bisheng.eplus.domain.repositories.eplus_repository import (
    EPlusConversationRepository,
    EPlusMessageRepository,
)

TENANT_ID = 73
BOT_CONFIG_ID = 101


@pytest_asyncio.fixture(autouse=True)
async def tenant_context() -> AsyncIterator[None]:
    token = current_tenant_id.set(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    database_path = tmp_path / "eplus-repository.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    EPlusBotConfig.__table__,
                    EPlusInboundMessage.__table__,
                    EPlusConversation.__table__,
                ],
            )
        )
    yield engine
    await engine.dispose()


def _config() -> EPlusBotConfig:
    return EPlusBotConfig(
        id=BOT_CONFIG_ID,
        tenant_id=TENANT_ID,
        assistant_id="assistant-1",
        bot_id="bot-1",
        connection_url="wss://eplus.example.test/im_openws?bizid=1",
        secret_ciphertext="ciphertext",
        media_host_allowlist=["media.example.test"],
        enabled=True,
        connection_status=EPlusConnectionStatus.AUTHENTICATED.value,
        created_by=9,
        updated_by=9,
    )


def _inbound(
    *,
    msgid: str,
    status: str = EPlusInboundStatus.RECEIVED.value,
    sender_external_id: str = "user-1",
    bot_config_id: int = BOT_CONFIG_ID,
) -> EPlusInboundMessage:
    return EPlusInboundMessage(
        tenant_id=TENANT_ID,
        bot_config_id=bot_config_id,
        bot_id="bot-1",
        msgid=msgid,
        req_id=f"req-{msgid}",
        stream_id=f"stream-{msgid}",
        sender_external_id=sender_external_id,
        chat_type=EPlusChatType.SINGLE.value,
        msg_type=EPlusMessageType.TEXT.value,
        payload_sha256="a" * 64,
        status=status,
        reply_status=EPlusReplyStatus.NOT_STARTED.value,
    )


async def _seed_config(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(_config())
        await session.commit()


async def test_duplicate_inbound_message_has_only_one_creator(engine: AsyncEngine) -> None:
    """Removing the unique-conflict branch would create or raise instead of returning one durable owner."""

    await _seed_config(engine)

    async def attempt(number: int) -> bool:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            _, created = await EPlusMessageRepository(session).create_or_get_inbound(_inbound(msgid="same-message"))
            await session.commit()
            return created

    created_flags = await asyncio.gather(*(attempt(number) for number in range(4)))

    assert sorted(created_flags) == [False, False, False, True]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        count = (
            await session.exec(
                select(func.count())
                .select_from(EPlusInboundMessage)
                .where(
                    EPlusInboundMessage.tenant_id == TENANT_ID,
                    EPlusInboundMessage.bot_id == "bot-1",
                    EPlusInboundMessage.msgid == "same-message",
                )
            )
        ).one()
    assert count == 1


async def test_state_machine_rejects_skipped_and_terminal_transitions(engine: AsyncEngine) -> None:
    await _seed_config(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        message, _ = await EPlusMessageRepository(session).create_or_get_inbound(_inbound(msgid="stateful"))
        await session.flush()
        repository = EPlusMessageRepository(session)

        assert await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.PREPARING,
        )
        assert await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.QUEUED,
        )
        assert not await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.SUCCEEDED,
        )
        assert await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.PROCESSING,
        )
        assert await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.SUCCEEDED,
        )
        assert not await repository.transition(
            tenant_id=TENANT_ID,
            message_id=message.id,
            target=EPlusInboundStatus.FAILED,
        )
        await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        saved = await session.get(EPlusInboundMessage, message.id)
    assert saved is not None
    assert saved.status == EPlusInboundStatus.SUCCEEDED.value


async def test_inflight_count_is_scoped_to_tenant_bot_and_sender(engine: AsyncEngine) -> None:
    await _seed_config(engine)
    rows = [
        _inbound(msgid="q1", status=EPlusInboundStatus.QUEUED.value),
        _inbound(msgid="p1", status=EPlusInboundStatus.PROCESSING.value),
        _inbound(msgid="done", status=EPlusInboundStatus.SUCCEEDED.value),
        _inbound(msgid="other-user", status=EPlusInboundStatus.QUEUED.value, sender_external_id="user-2"),
    ]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(rows)
        await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        count = await EPlusMessageRepository(session).count_inflight(
            tenant_id=TENANT_ID,
            bot_id="bot-1",
            sender_external_id="user-1",
        )
    assert count == 2


async def test_recovery_returns_queued_but_never_processing_messages(engine: AsyncEngine) -> None:
    await _seed_config(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _inbound(msgid="queued", status=EPlusInboundStatus.QUEUED.value),
                _inbound(msgid="processing", status=EPlusInboundStatus.PROCESSING.value),
                _inbound(msgid="finished", status=EPlusInboundStatus.SUCCEEDED.value),
            ]
        )
        await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        recovered = await EPlusMessageRepository(session).list_recoverable_queued(
            tenant_id=TENANT_ID,
            bot_config_id=BOT_CONFIG_ID,
        )
    assert [message.msgid for message in recovered] == ["queued"]


async def test_conversation_sequence_is_allocated_transactionally(engine: AsyncEngine) -> None:
    await _seed_config(engine)
    conversation = EPlusConversation(
        id="conversation-1",
        tenant_id=TENANT_ID,
        bot_config_id=BOT_CONFIG_ID,
        assistant_id="assistant-1",
        chat_type=EPlusChatType.SINGLE.value,
        conversation_key="user-1",
        scope_version=1,
        next_turn_seq=1,
        status=EPlusConversationStatus.ACTIVE.value,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(conversation)
        await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = EPlusConversationRepository(session)
        first = await repository.allocate_next_sequence(
            tenant_id=TENANT_ID,
            conversation_id="conversation-1",
        )
        second = await repository.allocate_next_sequence(
            tenant_id=TENANT_ID,
            conversation_id="conversation-1",
        )
        await session.commit()

    assert (first, second) == (1, 2)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        saved = await session.get(EPlusConversation, "conversation-1")
    assert saved is not None
    assert saved.next_turn_seq == 3


async def test_writes_require_matching_tenant_context(engine: AsyncEngine) -> None:
    await _seed_config(engine)
    token = current_tenant_id.set(TENANT_ID + 1)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository = EPlusMessageRepository(session)
            with pytest.raises(ValueError, match="matching tenant context"):
                await repository.create_or_get_inbound(_inbound(msgid="wrong-tenant"))
    finally:
        current_tenant_id.reset(token)
