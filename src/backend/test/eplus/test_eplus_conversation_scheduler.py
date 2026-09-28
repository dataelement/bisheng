from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusBotSpace,
    EPlusChatType,
    EPlusConnectionStatus,
    EPlusConversation,
    EPlusConversationStatus,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusMessageType,
    EPlusReplyStatus,
    EPlusTurn,
    EPlusTurnStatus,
)
from bisheng.eplus.domain.services.conversation_scheduler import EPlusConversationScheduler

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
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'eplus-scheduler.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    EPlusBotConfig.__table__,
                    EPlusBotSpace.__table__,
                    EPlusInboundMessage.__table__,
                    EPlusConversation.__table__,
                    EPlusTurn.__table__,
                ],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            EPlusBotConfig(
                id=BOT_CONFIG_ID,
                tenant_id=TENANT_ID,
                assistant_id="assistant-1",
                bot_id="bot-1",
                connection_url="wss://eplus.example/im_openws?bizid=1",
                secret_ciphertext="ciphertext",
                enabled=True,
                connection_status=EPlusConnectionStatus.AUTHENTICATED.value,
                created_by=9,
                updated_by=9,
            )
        )
        await session.commit()
    yield engine
    await engine.dispose()


async def _seed_turn(
    engine,
    *,
    conversation_id: str,
    conversation_key: str,
    turn_seq: int,
    status: EPlusTurnStatus = EPlusTurnStatus.QUEUED,
    scope_version: int = 7,
    chat_type: EPlusChatType = EPlusChatType.SINGLE,
    sender_external_id: str = "u1",
    answer: str | None = None,
):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        conversation = await session.get(EPlusConversation, conversation_id)
        if conversation is None:
            conversation = EPlusConversation(
                id=conversation_id,
                tenant_id=TENANT_ID,
                bot_config_id=BOT_CONFIG_ID,
                assistant_id="assistant-1",
                chat_type=chat_type.value,
                conversation_key=conversation_key,
                scope_version=scope_version,
                next_turn_seq=turn_seq + 1,
                status=EPlusConversationStatus.ACTIVE.value,
            )
            session.add(conversation)
        inbound = EPlusInboundMessage(
            tenant_id=TENANT_ID,
            bot_config_id=BOT_CONFIG_ID,
            bot_id="bot-1",
            msgid=f"{conversation_id}-{turn_seq}",
            req_id=f"req-{conversation_id}-{turn_seq}",
            stream_id=f"stream-{conversation_id}-{turn_seq}",
            conversation_id=conversation_id,
            turn_id=f"turn-{conversation_id}-{turn_seq}",
            sender_external_id=sender_external_id,
            sender_user_id=turn_seq + 80,
            chat_type=chat_type.value,
            chat_id=conversation_key if chat_type == EPlusChatType.GROUP else None,
            msg_type=EPlusMessageType.TEXT.value,
            payload_sha256=str(turn_seq).zfill(64),
            status=(
                EPlusInboundStatus.PREPARING.value
                if status == EPlusTurnStatus.PREPARING
                else EPlusInboundStatus.QUEUED.value
                if status == EPlusTurnStatus.QUEUED
                else EPlusInboundStatus.PROCESSING.value
                if status == EPlusTurnStatus.RUNNING
                else EPlusInboundStatus.SUCCEEDED.value
            ),
            reply_status=EPlusReplyStatus.NOT_STARTED.value,
        )
        session.add(inbound)
        await session.flush()
        session.add(
            EPlusTurn(
                id=f"turn-{conversation_id}-{turn_seq}",
                tenant_id=TENANT_ID,
                conversation_id=conversation_id,
                inbound_message_id=inbound.id,
                turn_seq=turn_seq,
                sender_user_id=turn_seq + 80,
                sender_external_id=sender_external_id,
                user_text=f"q{turn_seq}",
                scope_version=scope_version,
                scope_space_ids=[11],
                answer_text=answer,
                status=status.value,
            )
        )
        await session.commit()


def _scheduler(engine):
    return EPlusConversationScheduler(
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    )


async def test_separate_single_and_group_conversations_do_not_share_turns(engine):
    await _seed_turn(engine, conversation_id="single-u1", conversation_key="u1", turn_seq=1)
    await _seed_turn(
        engine,
        conversation_id="group-g1",
        conversation_key="g1",
        turn_seq=1,
        chat_type=EPlusChatType.GROUP,
        sender_external_id="u2",
    )
    scheduler = _scheduler(engine)

    single = await scheduler.next_ready_turn(TENANT_ID, "single-u1")
    group = await scheduler.next_ready_turn(TENANT_ID, "group-g1")

    assert single.turn.conversation_id == "single-u1"
    assert group.turn.conversation_id == "group-g1"
    assert group.turn.sender_external_id == "u2"


async def test_one_conversation_claims_strictly_in_sequence_and_completion_wakes_next(engine):
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=1)
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=2)
    scheduler = _scheduler(engine)

    first = await scheduler.next_ready_turn(TENANT_ID, "c1")
    assert first.turn.turn_seq == 1
    assert await scheduler.next_ready_turn(TENANT_ID, "c1") is None

    second = await scheduler.complete_and_wake_next(
        tenant_id=TENANT_ID,
        turn_id=first.turn.id,
        succeeded=True,
        answer_text="a1",
        execution_token=first.turn.assistant_run_id,
    )
    assert second.turn.turn_seq == 2


async def test_concurrent_consumers_have_only_one_claim_owner(engine):
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=1)

    claims = await asyncio.gather(
        _scheduler(engine).next_ready_turn(TENANT_ID, "c1"),
        _scheduler(engine).next_ready_turn(TENANT_ID, "c1"),
    )

    assert sum(claim is not None for claim in claims) == 1


async def test_preparing_head_blocks_later_queued_turn(engine):
    await _seed_turn(
        engine,
        conversation_id="c1",
        conversation_key="u1",
        turn_seq=1,
        status=EPlusTurnStatus.PREPARING,
    )
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=2)
    scheduler = _scheduler(engine)

    assert await scheduler.next_ready_turn(TENANT_ID, "c1") is None

    async with AsyncSession(engine) as session, session.begin():
        await session.exec(
            update(EPlusTurn)
            .where(EPlusTurn.id == "turn-c1-1")
            .values(status=EPlusTurnStatus.QUEUED.value)
        )
        await session.exec(
            update(EPlusInboundMessage)
            .where(EPlusInboundMessage.msgid == "c1-1")
            .values(status=EPlusInboundStatus.QUEUED.value)
        )

    claimed = await scheduler.next_ready_turn(TENANT_ID, "c1")
    assert claimed.turn.turn_seq == 1


async def test_claim_refreshes_scope_and_stale_execution_token_cannot_complete(engine):
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=1, scope_version=7)
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        config = await session.get(EPlusBotConfig, BOT_CONFIG_ID)
        config.scope_version = 8
        session.add(config)
        session.add(
            EPlusBotSpace(
                tenant_id=TENANT_ID,
                bot_config_id=BOT_CONFIG_ID,
                space_id=12,
                bound_by=9,
            )
        )

    scheduler = _scheduler(engine)
    claimed = await scheduler.next_ready_turn(TENANT_ID, "c1")
    stale_token = claimed.turn.assistant_run_id
    assert claimed.turn.scope_version == 8
    assert claimed.turn.scope_space_ids == [12]
    assert stale_token

    async with AsyncSession(engine) as session, session.begin():
        await session.exec(
            update(EPlusTurn)
            .where(EPlusTurn.id == claimed.turn.id)
            .values(assistant_run_id="replacement-owner")
        )

    assert (
        await scheduler.complete_and_wake_next(
            tenant_id=TENANT_ID,
            turn_id=claimed.turn.id,
            succeeded=True,
            answer_text="stale answer",
            execution_token=stale_token,
        )
        is None
    )
    async with AsyncSession(engine) as session:
        turn = await session.get(EPlusTurn, claimed.turn.id)
    assert turn.status == EPlusTurnStatus.RUNNING.value
    assert turn.answer_text is None


async def test_history_contains_completed_turns_across_scope_versions(engine):
    await _seed_turn(
        engine,
        conversation_id="c1",
        conversation_key="u1",
        turn_seq=1,
        status=EPlusTurnStatus.SUCCEEDED,
        scope_version=6,
        answer="old answer",
    )
    await _seed_turn(
        engine,
        conversation_id="c1",
        conversation_key="u1",
        turn_seq=2,
        status=EPlusTurnStatus.SUCCEEDED,
        scope_version=7,
        answer="current answer",
    )
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=3, scope_version=7)

    claimed = await _scheduler(engine).next_ready_turn(TENANT_ID, "c1")

    assert [(item.user_text, item.answer_text) for item in claimed.history] == [
        ("q1", "old answer"),
        ("q2", "current answer"),
    ]


async def test_recovery_returns_queued_and_marks_running_failed_without_rerun(engine):
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=1, status=EPlusTurnStatus.RUNNING)
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=2)
    scheduler = _scheduler(engine)

    recovered = await scheduler.recover_queued(tenant_id=TENANT_ID, bot_config_id=BOT_CONFIG_ID)

    assert recovered == ("c1",)
    async with AsyncSession(engine) as session:
        turns = list((await session.exec(select(EPlusTurn).order_by(EPlusTurn.turn_seq))).all())
    assert [turn.status for turn in turns] == [EPlusTurnStatus.FAILED.value, EPlusTurnStatus.QUEUED.value]
    assert turns[0].error_code == "WORKER_INTERRUPTED"


async def test_failed_or_cancelled_completion_releases_conversation_for_next_turn(engine):
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=1)
    await _seed_turn(engine, conversation_id="c1", conversation_key="u1", turn_seq=2)
    scheduler = _scheduler(engine)
    first = await scheduler.next_ready_turn(TENANT_ID, "c1")

    second = await scheduler.complete_and_wake_next(
        tenant_id=TENANT_ID,
        turn_id=first.turn.id,
        succeeded=False,
        error_code="CANCELLED",
        execution_token=first.turn.assistant_run_id,
    )

    assert second.turn.turn_seq == 2
