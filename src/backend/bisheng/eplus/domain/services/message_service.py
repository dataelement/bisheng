"""Durable admission for E+ callback messages."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.eplus.domain.models.eplus import (
    EPlusChatType,
    EPlusConversation,
    EPlusConversationStatus,
    EPlusInboundMessage,
    EPlusInboundStatus,
    EPlusMessageType,
    EPlusReplyStatus,
    EPlusTurn,
    EPlusTurnStatus,
)
from bisheng.eplus.domain.repositories.eplus_repository import (
    EPlusConversationRepository,
    EPlusMessageRepository,
)
from bisheng.eplus.domain.schemas.protocol import EPlusCallback, EPlusContentKind
from bisheng.eplus.domain.services.identity_service import EPlusIdentityService
from bisheng.eplus.domain.services.media_service import (
    EPlusMediaService,
    EPlusPreparedBlock,
    EPlusPreparedMessage,
)
from bisheng.eplus.infrastructure.protocol import stable_stream_id

NO_PERMISSION_REPLY = "无权限使用"
BUSY_REPLY = "消息处理中，请稍后再试"  # noqa: RUF001 - customer-facing fixed reply
MAX_INFLIGHT_PER_USER_BOT = 3


class InvalidEPlusCallbackError(ValueError):
    pass


class AdmissionDisposition(StrEnum):
    DUPLICATE = "duplicate"
    NO_PERMISSION = "no_permission"
    BUSY = "busy"
    QUEUED = "queued"


@dataclass(frozen=True, slots=True)
class EPlusAdmissionContext:
    tenant_id: int
    bot_config_id: int
    assistant_id: str
    bot_id: str
    scope_version: int
    space_ids: tuple[int, ...]
    media_hosts: tuple[str, ...]
    ca_pem: bytes | None


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    disposition: AdmissionDisposition
    inbound_message_id: int
    conversation_id: str | None = None
    turn_id: str | None = None
    reply_text: str | None = None
    existing_status: str | None = None


class EPlusMessageAdmissionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        identity_service: EPlusIdentityService,
        media_service: EPlusMediaService,
    ) -> None:
        self._session_factory = session_factory
        self._identity_service = identity_service
        self._media_service = media_service

    async def admit(self, context: EPlusAdmissionContext, callback: EPlusCallback) -> AdmissionResult:
        self._validate_callback(context, callback)
        inbound = self._new_inbound(context, callback)

        # Commit the idempotency owner before any user lookup or media network
        # call. A retry observes this row and never starts a second answer.
        async with self._session_factory() as session:
            repository = EPlusMessageRepository(session)
            inbound, created = await repository.create_or_get_inbound(inbound)
            await session.commit()
        if not created:
            return AdmissionResult(
                disposition=AdmissionDisposition.DUPLICATE,
                inbound_message_id=int(inbound.id),
                conversation_id=inbound.conversation_id,
                turn_id=inbound.turn_id,
                existing_status=inbound.status,
            )

        identity = await self._identity_service.resolve(
            tenant_id=context.tenant_id,
            external_user_id=callback.sender_external_id,
        )
        if identity is None:
            await self._finish_rejected(
                context,
                int(inbound.id),
                target=EPlusInboundStatus.FAILED,
                error_code="NO_PERMISSION",
            )
            return AdmissionResult(
                disposition=AdmissionDisposition.NO_PERMISSION,
                inbound_message_id=int(inbound.id),
                reply_text=NO_PERMISSION_REPLY,
            )

        prepared = await self._ingest_content(context, callback)

        async with self._session_factory() as session, session.begin():
            messages = EPlusMessageRepository(session)
            conversations = EPlusConversationRepository(session)
            current = await messages.get_inbound(tenant_id=context.tenant_id, message_id=int(inbound.id))
            if current is None:
                raise LookupError(f"E+ inbound message not found: {inbound.id}")
            if current.status != EPlusInboundStatus.RECEIVED.value:
                return AdmissionResult(
                    disposition=AdmissionDisposition.DUPLICATE,
                    inbound_message_id=int(current.id),
                    conversation_id=current.conversation_id,
                    turn_id=current.turn_id,
                    existing_status=current.status,
                )

            await messages.lock_bot_admission(
                tenant_id=context.tenant_id,
                bot_config_id=context.bot_config_id,
            )
            inflight = await messages.count_inflight(
                tenant_id=context.tenant_id,
                bot_id=context.bot_id,
                sender_external_id=callback.sender_external_id,
            )
            if inflight >= MAX_INFLIGHT_PER_USER_BOT:
                transitioned = await messages.transition(
                    tenant_id=context.tenant_id,
                    message_id=int(current.id),
                    target=EPlusInboundStatus.REJECTED_BUSY,
                    error_code="BUSY",
                )
                if not transitioned:
                    raise RuntimeError("E+ busy rejection lost its inbound state transition")
                return AdmissionResult(
                    disposition=AdmissionDisposition.BUSY,
                    inbound_message_id=int(current.id),
                    reply_text=BUSY_REPLY,
                )

            conversation = await conversations.get_or_create(
                tenant_id=context.tenant_id,
                conversation=EPlusConversation(
                    id=uuid.uuid4().hex,
                    tenant_id=context.tenant_id,
                    bot_config_id=context.bot_config_id,
                    assistant_id=context.assistant_id,
                    chat_type=_chat_type(callback),
                    conversation_key=_conversation_key(callback),
                    scope_version=context.scope_version,
                    status=EPlusConversationStatus.ACTIVE.value,
                ),
            )
            sequence = await conversations.allocate_next_sequence(
                tenant_id=context.tenant_id,
                conversation_id=conversation.id,
            )
            turn = EPlusTurn(
                id=uuid.uuid4().hex,
                tenant_id=context.tenant_id,
                conversation_id=conversation.id,
                inbound_message_id=int(current.id),
                turn_seq=sequence,
                sender_user_id=identity.user_id,
                sender_external_id=identity.external_user_id,
                user_text=_joined_user_text(callback),
                content_manifest=[asdict(block) for block in prepared.blocks],
                scope_version=context.scope_version,
                scope_space_ids=list(context.space_ids),
                status=EPlusTurnStatus.QUEUED.value,
            )
            await conversations.save_turn(tenant_id=context.tenant_id, turn=turn)
            await messages.link_to_turn(
                tenant_id=context.tenant_id,
                message=current,
                conversation_id=conversation.id,
                turn_id=turn.id,
                sender_user_id=identity.user_id,
            )
            transitioned = await messages.transition(
                tenant_id=context.tenant_id,
                message_id=int(current.id),
                target=EPlusInboundStatus.QUEUED,
            )
            if not transitioned:
                raise RuntimeError("E+ queued admission lost its inbound state transition")
            return AdmissionResult(
                disposition=AdmissionDisposition.QUEUED,
                inbound_message_id=int(current.id),
                conversation_id=conversation.id,
                turn_id=turn.id,
            )

    async def _ingest_content(
        self,
        context: EPlusAdmissionContext,
        callback: EPlusCallback,
    ) -> EPlusPreparedMessage:
        try:
            return await self._media_service.ingest_blocks(
                tenant_id=context.tenant_id,
                blocks=callback.blocks,
                allowed_hosts=context.media_hosts,
                ca_pem=context.ca_pem,
            )
        except Exception:
            # Admission must preserve usable text when media infrastructure is
            # unavailable. No URL, AES key or original text is written to logs.
            logger.opt(exception=True).warning(
                "E+ media admission failed bot_config_id={} msgid_hash={}",
                context.bot_config_id,
                hashlib.sha256(callback.msg_id.encode()).hexdigest()[:12],
            )
            blocks = []
            for block in callback.blocks:
                if block.kind == EPlusContentKind.TEXT:
                    blocks.append(EPlusPreparedBlock(kind="text", text=block.text or ""))
                else:
                    blocks.append(EPlusPreparedBlock(kind="error", text="[无法读取图片]"))
            return EPlusPreparedMessage(tuple(blocks), (), ("image admission failed",))

    async def _finish_rejected(
        self,
        context: EPlusAdmissionContext,
        message_id: int,
        *,
        target: EPlusInboundStatus,
        error_code: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            transitioned = await EPlusMessageRepository(session).transition(
                tenant_id=context.tenant_id,
                message_id=message_id,
                target=target,
                error_code=error_code,
            )
            if not transitioned:
                raise RuntimeError("E+ rejected admission lost its inbound state transition")

    @staticmethod
    def _validate_callback(context: EPlusAdmissionContext, callback: EPlusCallback) -> None:
        if callback.bot_id != context.bot_id:
            raise InvalidEPlusCallbackError("callback bot identity does not match the subscribed robot")
        if not callback.msg_id:
            raise InvalidEPlusCallbackError("callback msgid is required")
        if callback.chat_type == "group" and not callback.chat_id:
            raise InvalidEPlusCallbackError("group callback chatid is required")

    @staticmethod
    def _new_inbound(context: EPlusAdmissionContext, callback: EPlusCallback) -> EPlusInboundMessage:
        return EPlusInboundMessage(
            tenant_id=context.tenant_id,
            bot_config_id=context.bot_config_id,
            bot_id=context.bot_id,
            msgid=callback.msg_id,
            req_id=callback.req_id,
            stream_id=stable_stream_id(context.bot_id, callback.msg_id),
            sender_external_id=callback.sender_external_id,
            chat_type=_chat_type(callback),
            chat_id=callback.chat_id,
            msg_type=_message_type(callback),
            payload_sha256=_payload_sha256(callback),
            status=EPlusInboundStatus.RECEIVED.value,
            reply_status=EPlusReplyStatus.NOT_STARTED.value,
        )


def _chat_type(callback: EPlusCallback) -> str:
    return EPlusChatType.GROUP.value if callback.chat_type == "group" else EPlusChatType.SINGLE.value


def _message_type(callback: EPlusCallback) -> str:
    value = callback.msg_type.upper()
    return value if value in EPlusMessageType._value2member_map_ else EPlusMessageType.MIXED.value


def _conversation_key(callback: EPlusCallback) -> str:
    return str(callback.chat_id) if callback.chat_type == "group" else callback.sender_external_id


def _joined_user_text(callback: EPlusCallback) -> str | None:
    parts = [block.text or "" for block in callback.blocks if block.kind == EPlusContentKind.TEXT]
    text = "\n".join(part for part in parts if part)
    return text or None


def _payload_sha256(callback: EPlusCallback) -> str:
    safe_shape = {
        "req_id": callback.req_id,
        "msg_id": callback.msg_id,
        "bot_id": callback.bot_id,
        "sender": callback.sender_external_id,
        "chat_type": callback.chat_type,
        "chat_id": callback.chat_id,
        "blocks": [
            {"kind": block.kind.value, "text": block.text if block.kind == EPlusContentKind.TEXT else None}
            for block in callback.blocks
        ],
    }
    encoded = json.dumps(safe_shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
