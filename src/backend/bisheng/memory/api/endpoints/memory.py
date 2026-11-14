"""Personal memory management API (design §4.2 HTTP table).

Every endpoint acts on the caller only, in the current tenant. There is no
parameter that names another user, and no metrics or statistics endpoint
(AC-08, AC-103). "My memory" being off does not block any of these (AC-90).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services.context import build_user_context
from bisheng.memory.domain.services.factory import get_memory_service, get_resident_service
from bisheng.memory.domain.services.turn_record import TurnRecordService
from bisheng.memory.domain.services.views import item_view, turn_view

router = APIRouter()


class ItemIn(BaseModel):
    content: str
    type: str = "fact"
    event_time: str | None = None


class SettingIn(BaseModel):
    enabled: bool


class TimezoneIn(BaseModel):
    timezone: str = Field(max_length=64)

    @field_validator("timezone")
    @classmethod
    def _valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


class UndoIn(BaseModel):
    record_id: int


@router.get("/items")
async def list_items(login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)):
    ctx = build_user_context(login_user)
    return resp_200([item_view(i) for i in await service.list(ctx)])


@router.get("/items/{item_id}/detail")
async def get_item_detail(
    item_id: str, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)
):
    """Full text of one of the caller's items (``detail`` is null when it has none)."""
    ctx = build_user_context(login_user)
    return resp_200({"detail": await service.get_detail(ctx, item_id)})


@router.post("/items")
async def add_item(data: ItemIn, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)):
    ctx = build_user_context(login_user)
    res = await service.add_manual(ctx, data.content, data.type, data.event_time)
    return resp_200({"item_id": res.item_id})


@router.put("/items/{item_id}")
async def edit_item(
    item_id: str, data: ItemIn, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)
):
    ctx = build_user_context(login_user)
    res = await service.edit(ctx, item_id, data.content, data.type, data.event_time)
    return resp_200({"item_id": res.item_id, "replaced_item_id": res.related_item_id})


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)
):
    ctx = build_user_context(login_user)
    await service.delete(ctx, item_id)
    return resp_200(None)


@router.post("/items/clear")
async def clear_items(login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)):
    ctx = build_user_context(login_user)
    await service.clear(ctx)
    return resp_200(None)


@router.post("/undo")
async def undo(data: UndoIn, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)):
    ctx = build_user_context(login_user)
    res = await service.undo(ctx, data.record_id)
    return resp_200({"item_id": res.item_id, "related_item_id": res.related_item_id})


@router.get("/setting")
async def get_setting(login_user=Depends(UserPayload.get_login_user)):
    ctx = build_user_context(login_user)
    row = await SettingRepository.get(ctx)
    return resp_200({"enabled": True if row is None else bool(row.enabled), "timezone": row.timezone if row else None})


@router.put("/setting")
async def update_setting(
    data: SettingIn, login_user=Depends(UserPayload.get_login_user), service=Depends(get_memory_service)
):
    ctx = build_user_context(login_user)
    row = await SettingRepository.set_enabled(ctx, data.enabled)
    return resp_200({"enabled": bool(row.enabled), "timezone": row.timezone})


@router.post("/timezone")
async def report_timezone(data: TimezoneIn, login_user=Depends(UserPayload.get_login_user)):
    ctx = build_user_context(login_user)
    changed = await SettingRepository.set_timezone(ctx, data.timezone)
    return resp_200({"changed": changed})


@router.get("/turn")
async def get_turn(
    turn_id: str | None = Query(default=None),
    message_id: int | None = Query(default=None),
    login_user=Depends(UserPayload.get_login_user),
    service=Depends(get_memory_service),
    resident=Depends(get_resident_service),
):
    """Operation notices and attribution of one turn, by turn_id or message id (owner only)."""
    ctx = build_user_context(login_user)
    return resp_200(await turn_view(ctx, service, turn_id=turn_id, message_id=message_id))


@router.get("/flags")
async def get_flags(chat_id: str = Query(...), login_user=Depends(UserPayload.get_login_user)):
    """Memory flags of the caller's messages in one chat, for loading history."""
    ctx = build_user_context(login_user)
    flags = await TurnRecordService.flags_for_chat(ctx, chat_id)
    return resp_200({str(k): v for k, v in flags.items()})
