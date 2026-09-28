from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.eplus.domain.models.eplus import (
    EPlusBotConfig,
    EPlusConnectionStatus,
    EPlusConversation,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusTurn,
)
from bisheng.eplus.domain.schemas.protocol import EPlusCallback, EPlusContentBlock, EPlusContentKind
from bisheng.eplus.domain.services.identity_service import WECOM_SOURCE, EPlusIdentity, EPlusIdentityService
from bisheng.eplus.domain.services.media_service import EPlusPreparedBlock, EPlusPreparedMessage
from bisheng.eplus.domain.services.message_service import (
    AdmissionDisposition,
    EPlusAdmissionContext,
    EPlusMessageAdmissionService,
    InvalidEPlusCallbackError,
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
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'eplus-admission.sqlite'}",
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
                media_host_allowlist=["media.example"],
                enabled=True,
                connection_status=EPlusConnectionStatus.AUTHENTICATED.value,
                scope_version=7,
                created_by=9,
                updated_by=9,
            )
        )
        await session.commit()
    yield engine
    await engine.dispose()


@dataclass
class FakeIdentityResolver:
    identity: EPlusIdentity | None = field(
        default_factory=lambda: EPlusIdentity(user_id=88, external_user_id="user-1")
    )
    calls: int = 0

    async def resolve(self, *, tenant_id: int, external_user_id: str) -> EPlusIdentity | None:
        self.calls += 1
        if self.identity is None:
            return None
        return EPlusIdentity(self.identity.user_id, external_user_id)


class FakeMediaService:
    def __init__(self, *, image_error: bool = False, delay: float = 0) -> None:
        self.image_error = image_error
        self.delay = delay
        self.calls = 0

    async def ingest_blocks(self, *, blocks, **kwargs) -> EPlusPreparedMessage:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        prepared = []
        errors = []
        for block in blocks:
            if block.kind == EPlusContentKind.TEXT:
                prepared.append(EPlusPreparedBlock(kind="text", text=block.text))
            elif self.image_error:
                prepared.append(EPlusPreparedBlock(kind="error", text="[无法读取图片]"))
                errors.append("image failed")
            else:
                prepared.append(EPlusPreparedBlock(kind="image"))
        return EPlusPreparedMessage(tuple(prepared), (), tuple(errors))


def _context() -> EPlusAdmissionContext:
    return EPlusAdmissionContext(
        tenant_id=TENANT_ID,
        bot_config_id=BOT_CONFIG_ID,
        assistant_id="assistant-1",
        bot_id="bot-1",
        scope_version=7,
        space_ids=(11, 12),
        media_hosts=("media.example",),
        ca_pem=None,
    )


def _callback(
    msg_id: str,
    *,
    bot_id: str = "bot-1",
    sender: str = "user-1",
    chat_type: str = "single",
    chat_id: str | None = None,
    blocks: tuple[EPlusContentBlock, ...] | None = None,
) -> EPlusCallback:
    return EPlusCallback(
        req_id=f"req-{msg_id or 'missing'}",
        msg_id=msg_id,
        bot_id=bot_id,
        sender_external_id=sender,
        chat_type=chat_type,
        chat_id=chat_id,
        msg_type="mixed" if blocks and len(blocks) > 1 else "text",
        blocks=blocks or (EPlusContentBlock(kind=EPlusContentKind.TEXT, text=msg_id),),
    )


def _service(engine, *, identity=None, media=None):
    return EPlusMessageAdmissionService(
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        identity_service=identity or FakeIdentityResolver(),
        media_service=media or FakeMediaService(),
    )


async def test_wrong_bot_and_missing_msgid_are_rejected_before_persistence(engine):
    service = _service(engine)
    with pytest.raises(InvalidEPlusCallbackError, match="bot identity"):
        await service.admit(_context(), _callback("m1", bot_id="other"))
    with pytest.raises(InvalidEPlusCallbackError, match="msgid"):
        await service.admit(_context(), _callback(""))

    async with AsyncSession(engine) as session:
        assert (await session.exec(select(func.count()).select_from(EPlusInboundMessage))).one() == 0


async def test_duplicate_msgid_has_one_queued_owner_and_is_not_answered_twice(engine):
    media = FakeMediaService(delay=0.03)
    service = _service(engine, media=media)

    first, second = await asyncio.gather(
        service.admit(_context(), _callback("same")),
        service.admit(_context(), _callback("same")),
    )

    assert {first.disposition, second.disposition} == {
        AdmissionDisposition.QUEUED,
        AdmissionDisposition.DUPLICATE,
    }
    assert media.calls == 1
    async with AsyncSession(engine) as session:
        assert (await session.exec(select(func.count()).select_from(EPlusTurn))).one() == 1


async def test_missing_disabled_or_cross_tenant_user_returns_fixed_no_permission_without_turn(engine):
    identity = FakeIdentityResolver(identity=None)
    service = _service(engine, identity=identity)

    result = await service.admit(_context(), _callback("denied"))

    assert result.disposition == AdmissionDisposition.NO_PERMISSION
    assert result.reply_text == "无权限使用"
    async with AsyncSession(engine) as session:
        inbound = (await session.exec(select(EPlusInboundMessage))).one()
        assert inbound.status == EPlusInboundStatus.FAILED.value
        assert inbound.error_code == "NO_PERMISSION"
        assert (await session.exec(select(func.count()).select_from(EPlusTurn))).one() == 0


async def test_each_group_message_resolves_its_actual_sender(engine):
    identity = FakeIdentityResolver()
    service = _service(engine, identity=identity)

    await service.admit(_context(), _callback("g1", sender="u1", chat_type="group", chat_id="group-7"))
    await service.admit(_context(), _callback("g2", sender="u2", chat_type="group", chat_id="group-7"))

    assert identity.calls == 2
    async with AsyncSession(engine) as session:
        turns = list((await session.exec(select(EPlusTurn).order_by(EPlusTurn.turn_seq))).all())
    assert [turn.sender_external_id for turn in turns] == ["u1", "u2"]
    assert len({turn.conversation_id for turn in turns}) == 1


async def test_first_three_messages_queue_and_fourth_is_rejected_busy_without_turn(engine):
    service = _service(engine)

    results = [await service.admit(_context(), _callback(f"m{index}")) for index in range(1, 5)]

    assert [result.disposition for result in results] == [
        AdmissionDisposition.QUEUED,
        AdmissionDisposition.QUEUED,
        AdmissionDisposition.QUEUED,
        AdmissionDisposition.BUSY,
    ]
    assert results[-1].reply_text == "消息处理中，请稍后再试"  # noqa: RUF001 - fixed reply contract
    async with AsyncSession(engine) as session:
        assert (await session.exec(select(func.count()).select_from(EPlusTurn))).one() == 3
        busy = (await session.exec(select(EPlusInboundMessage).where(EPlusInboundMessage.msgid == "m4"))).one()
    assert busy.status == EPlusInboundStatus.REJECTED_BUSY.value


async def test_images_are_persisted_before_queue_and_failed_image_keeps_text(engine):
    media = FakeMediaService(image_error=True)
    service = _service(engine, media=media)
    blocks = (
        EPlusContentBlock(kind=EPlusContentKind.TEXT, text="keep this"),
        EPlusContentBlock(kind=EPlusContentKind.IMAGE, url="https://media.example/1", aes_key="key"),
    )

    result = await service.admit(_context(), _callback("mixed", blocks=blocks))

    assert result.disposition == AdmissionDisposition.QUEUED
    assert media.calls == 1
    async with AsyncSession(engine) as session:
        turn = (await session.exec(select(EPlusTurn))).one()
    assert turn.user_text == "keep this"
    assert [item["kind"] for item in turn.content_manifest] == ["text", "error"]


async def test_identity_mapping_uses_raw_wecom_external_id_and_active_tenant():
    user = SimpleNamespace(user_id=88, external_id="RAW-923", delete=0)
    with (
        patch(
            "bisheng.eplus.domain.services.identity_service.UserDao.aget_by_source_external_id",
            AsyncMock(return_value=user),
        ) as lookup,
        patch(
            "bisheng.eplus.domain.services.identity_service.UserTenantDao.aget_active_user_tenant",
            AsyncMock(return_value=SimpleNamespace(tenant_id=TENANT_ID, status="active")),
        ),
    ):
        identity = await EPlusIdentityService().resolve(tenant_id=TENANT_ID, external_user_id="RAW-923")

    assert identity == EPlusIdentity(user_id=88, external_user_id="RAW-923")
    lookup.assert_awaited_once_with(WECOM_SOURCE, "RAW-923")


@pytest.mark.parametrize(
    ("user", "membership"),
    [
        (None, None),
        (SimpleNamespace(user_id=88, delete=1), SimpleNamespace(tenant_id=TENANT_ID, status="active")),
        (SimpleNamespace(user_id=88, delete=0), SimpleNamespace(tenant_id=999, status="active")),
    ],
)
async def test_identity_mapping_rejects_missing_disabled_or_cross_tenant_users(user, membership):
    with (
        patch(
            "bisheng.eplus.domain.services.identity_service.UserDao.aget_by_source_external_id",
            AsyncMock(return_value=user),
        ),
        patch(
            "bisheng.eplus.domain.services.identity_service.UserTenantDao.aget_active_user_tenant",
            AsyncMock(return_value=membership),
        ),
    ):
        assert await EPlusIdentityService().resolve(tenant_id=TENANT_ID, external_user_id="RAW-923") is None
