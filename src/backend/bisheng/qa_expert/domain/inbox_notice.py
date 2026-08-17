# ruff: noqa: RUF002
"""专家问答站内信：统一用用户 ID 收件，匿名触发人只写同题别名。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.qa_expert.domain.identity import IdentityService

_ANON_VIEWER = SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)
_SYSTEM_SENDER = 0


def _public_user_metadata(*, anonymous: bool, user_id: int) -> dict[str, Any]:
    """匿名不写 user_id，避免列表接口回填真名和部门。"""
    if anonymous:
        return {}
    return {"user_id": int(user_id)}


async def display_name_for_trigger(
    question,
    *,
    user_id: int,
    real_name: str,
    anonymous: bool,
    reveal_on_public: bool | int | None = None,
) -> tuple[str, bool]:
    """返回通知展示名；非管理员视角下匿名为同题稳定别名。"""
    view = await IdentityService().mask_identity(
        _ANON_VIEWER,
        question_id=int(question.id),
        user_id=int(user_id),
        real_name=real_name or "",
        anonymous=bool(anonymous),
        question_type=str(getattr(question, "question_type", "") or ""),
        reveal_on_public=reveal_on_public,
        tenant_id=int(getattr(question, "tenant_id", 1) or 1),
    )
    return view.display_name, bool(view.anonymous)


async def send_qa_inbox(
    *,
    action_code: str,
    system_text: str,
    question,
    receivers: list[int],
    sender_user_id: int,
    sender_display: str,
    sender_anonymous: bool,
    answer_id: int | None = None,
    comment_id: int | None = None,
    request_id: int | None = None,
    instance_id: int | None = None,
    task_id: int | None = None,
    tooltip: str | None = None,
    business_type: str = "qa_question",
) -> None:
    """写入 inbox_message；失败只打日志，不回滚业务。"""
    receivers = list(dict.fromkeys(int(uid) for uid in receivers if uid and int(uid) != int(sender_user_id)))
    if not receivers:
        return

    from bisheng.core.database import get_async_db_session
    from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum
    from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import (
        InboxMessageReadRepositoryImpl,
    )
    from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import (
        InboxMessageRepositoryImpl,
    )
    from bisheng.message.domain.services.message_service import MessageService

    data: dict[str, Any] = {"question_id": str(question.id)}
    if answer_id:
        data["answer_id"] = str(answer_id)
    if comment_id:
        data["comment_id"] = str(comment_id)
    if request_id:
        data["request_id"] = str(request_id)
    if instance_id:
        data["approval_instance_id"] = str(instance_id)
        data["instance_id"] = str(instance_id)
    if task_id:
        data["approval_task_id"] = str(task_id)
        data["task_id"] = str(task_id)
    if business_type == "approval_instance_id" and instance_id:
        data["approval_instance_id"] = str(instance_id)
        data["business_id"] = str(instance_id)

    content: list[dict[str, Any]] = [
        {
            "type": "user",
            "content": f"@{sender_display}",
            "metadata": _public_user_metadata(anonymous=sender_anonymous, user_id=sender_user_id),
        },
        {"type": "system_text", "content": system_text},
        {
            "type": "business_url",
            "content": f"--{question.title}",
            "metadata": {"business_type": business_type, "data": data},
        },
    ]
    if tooltip:
        content.append({"type": "tooltip_text", "content": tooltip[:50]})

    try:
        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=_SYSTEM_SENDER if sender_anonymous else int(sender_user_id),
                message_type=MessageTypeEnum.NOTIFY,
                receiver=receivers,
                status=MessageStatusEnum.APPROVED,
                action_code=action_code,
            )
    except Exception:
        logger.exception("qa.inbox.send_failed action_code={}", action_code)
