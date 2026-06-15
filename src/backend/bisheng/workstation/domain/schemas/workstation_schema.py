import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.user.domain.models.user import UserDao


class WorkstationMessage(BaseModel):
    messageId: str
    conversationId: str
    createdAt: datetime
    isCreatedByUser: bool
    model: str | None
    parentMessageId: str | None
    user_name: str | None
    sender: str
    text: str
    updateAt: datetime
    files: list | None
    error: bool | None = False
    unfinished: bool | None = False
    flow_name: str | None = None
    source: int | None = None
    # F035 Track J: unified conversation model — task-mode turns are plain
    # ChatMessage rows in the daily conversation. `category` lets the frontend
    # branch to the rich task panel ('task'); `linsightSessionVersionId` points
    # to the execution detail for lazy-loading. Both absent on normal turns.
    category: str | None = None
    linsightSessionVersionId: str | None = None

    @field_validator("messageId", mode="before")
    @classmethod
    def convert_message_id(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)

    @field_validator("parentMessageId", mode="before")
    @classmethod
    def convert_parent_message_id(cls, value: Any) -> str:
        if value is None or isinstance(value, str):
            return value
        return str(value)

    @classmethod
    async def from_chat_message(cls, message: ChatMessage):
        files = json.loads(message.files) if message.files else []
        extra = json.loads(message.extra) if message.extra else {}
        user_model = await UserDao.aget_user(message.user_id)
        message_session_model = await MessageSessionDao.async_get_one(chat_id=message.chat_id)
        return cls(
            messageId=str(message.id),
            conversationId=message.chat_id,
            createdAt=message.create_time,
            updateAt=message.update_time,
            isCreatedByUser=not message.is_bot,
            model=None,
            parentMessageId=extra.get("parentMessageId"),
            error=extra.get("error", False),
            unfinished=extra.get("unfinished", False),
            user_name=user_model.user_name,
            sender=message.sender,
            text=message.message,
            files=files,
            flow_name=message_session_model.name if message_session_model else None,
            source=message.source,
            category=message.category,
            linsightSessionVersionId=extra.get("linsight_session_version_id"),
        )


class WorkstationConversation(BaseModel):
    conversationId: str
    user: str
    createdAt: datetime
    updateAt: datetime
    model: str | None
    title: str | None

    @classmethod
    def from_chat_session(cls, session: MessageSession):
        return cls(
            conversationId=session.chat_id,
            user=str(session.user_id),
            createdAt=session.create_time,
            updateAt=session.update_time,
            model=None,
            title=session.name,
        )

    @field_validator("user", mode="before")
    @classmethod
    def convert_user(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)
