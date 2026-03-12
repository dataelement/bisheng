import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.message.api.dependencies import get_message_service
from bisheng.message.domain.schemas.message_schema import (
    TabTypeEnum,
    MarkReadRequest,
    ApprovalActionRequest,
)
from bisheng.message.domain.services.message_service import MessageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='', tags=['Message'])


@router.get("/list")
async def get_message_list(
        tab: TabTypeEnum = Query(TabTypeEnum.ALL, description='Tab type: all or request'),
        only_unread: bool = Query(False, description='Show only unread messages'),
        keyword: Optional[str] = Query(None, description='Search keyword'),
        page: int = Query(1, ge=1, description='Page number'),
        page_size: int = Query(20, ge=1, le=100, description='Page size'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Get paginated message list with optional filters."""
    try:
        result = await message_service.get_message_list(
            login_user=login_user,
            tab=tab,
            only_unread=only_unread,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return resp_200(data=result.model_dump())
    except Exception as e:
        logger.error(f"Failed to get message list: {e}")
        return resp_500(message="Failed to get message list")


@router.get("/unread_count")
async def get_unread_count(
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Get unread message counts grouped by message type."""
    try:
        result = await message_service.get_unread_count(login_user)
        return resp_200(data=result.model_dump())
    except Exception as e:
        logger.error(f"Failed to get unread count: {e}")
        return resp_500(message="Failed to get unread count")


@router.post("/mark_read")
async def mark_messages_read(
        req: MarkReadRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Mark specific messages as read."""
    try:
        count = await message_service.mark_as_read(req.message_ids, login_user)
        return resp_200(data={"marked_count": count})
    except Exception as e:
        logger.error(f"Failed to mark messages as read: {e}")
        return resp_500(message="Failed to mark messages as read")


@router.post("/mark_all_read")
async def mark_all_messages_read(
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Mark all messages as read for the current user."""
    try:
        count = await message_service.mark_all_as_read(login_user)
        return resp_200(data={"marked_count": count})
    except Exception as e:
        logger.error(f"Failed to mark all messages as read: {e}")
        return resp_500(message="Failed to mark all messages as read")


@router.post("/approve")
async def approve_message(
        req: ApprovalActionRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Process approval action (agree/reject) on an approval message."""
    result = await message_service.handle_approval(
        message_id=req.message_id,
        action=req.action,
        login_user=login_user,
    )
    return resp_200(data=result.model_dump())


@router.delete("/{message_id}")
async def delete_message(
        message_id: int,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        message_service: MessageService = Depends(get_message_service),
):
    """Delete a message."""
    await message_service.delete_message(message_id, login_user)
    return resp_200(data=True)
