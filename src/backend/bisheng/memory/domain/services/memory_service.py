"""MemoryService: the single business entry of long-term memory (design §4.3).

Writes follow design decisions 3, 4, 5 and 8:
- remember is an INSERT; correct/forget are conditional UPDATEs on ``status='active'``
  (rowcount 0 = the target is gone or changed, nothing else is written);
- a detail body is written to the object store before the row (immutable object);
- item change, ``rev`` bump and the turn record commit in one transaction;
- after commit: index synchronously (3 s embedding timeout; failure leaves the item
  ``pending`` for the reconcile task), audit, count.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.memory import (
    MemoryDetailUnavailableError,
    MemoryItemNotFoundError,
    MemoryUndoAlreadyDoneError,
    MemoryUndoChangedError,
    MemoryUndoClearedError,
)
from bisheng.memory.domain.models.memory_item import (
    INDEX_OK,
    INDEX_PENDING,
    ORIGIN_EXPLICIT,
    ORIGIN_MANUAL,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_SUPERSEDED,
    MemoryItem,
)
from bisheng.memory.domain.models.memory_turn_record import KIND_WRITE, MemoryTurnRecord
from bisheng.memory.domain.ports import SCENE_MANUAL, DetailStore, MemoryContext, MemoryIndex
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.cursor_repository import CursorRepository
from bisheng.memory.domain.repositories.item_repository import ItemRepository
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.audit import MemoryAudit
from bisheng.memory.domain.services.guard import validate_detail, validate_item
from bisheng.memory.domain.services.turn_record import TurnRecordService

INDEX_TIMEOUT_SECONDS = 3.0
RESIDENT_TYPES = ("fact", "preference")
ACTIONS = ("remember", "correct", "forget")


@dataclass
class WriteResult:
    ok: bool
    op: str
    item_id: str | None = None
    related_item_id: str | None = None
    record_id: int | None = None


def parse_event_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid event_time {value!r}") from exc
    return parsed.replace(tzinfo=None)


# ``edit(detail=KEEP)``: leave the item's full text as it is.
KEEP = object()


class MemoryService:
    def __init__(
        self,
        index: MemoryIndex,
        details: DetailStore,
        kv,
        audit: MemoryAudit | None = None,
        metrics: m.MemoryMetrics | None = None,
    ):
        self.index = index
        self.details = details
        self.kv = kv
        self.audit = audit or MemoryAudit()
        self.metrics = metrics or m.MemoryMetrics(kv)

    # ------------------------------------------------------------------ reads
    async def list(self, ctx: MemoryContext) -> list[MemoryItem]:
        async with _db.async_session() as s:
            return await ItemRepository.list_active(s, ctx)

    async def get_detail(self, ctx: MemoryContext, item_id: str) -> str | None:
        """Full text of one of the caller's active items; None when it has none.

        For the owner's management page: it does not count as a model read.
        """
        async with _db.async_session() as s:
            item = await ItemRepository.get_active(s, ctx, item_id)
        if item is None:
            raise MemoryItemNotFoundError()
        if not item.detail_object_key:
            return None
        try:
            return await self.details.get(item.detail_object_key)
        except Exception as exc:
            logger.exception("memory detail read failed item={}", item_id)
            raise MemoryDetailUnavailableError() from exc

    async def get_items(self, ctx: MemoryContext, item_ids: list[str], active_only: bool = True) -> list[MemoryItem]:
        async with _db.async_session() as s:
            return await ItemRepository.list_by_ids(s, ctx, item_ids, active_only=active_only)

    # ------------------------------------------------------------------ helpers
    def _new_item(
        self, ctx: MemoryContext, content: str, item_type: str, origin: str, event_time, pinned: bool
    ) -> MemoryItem:
        now = datetime.now()
        return MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            type=item_type,
            content=content,
            status=STATUS_ACTIVE,
            pinned=pinned,
            pin_order=0,
            event_time=parse_event_time(event_time),
            valid_from=now,
            recorded_at=now,
            origin=origin,
            source_scene=SCENE_MANUAL if origin == ORIGIN_MANUAL else ctx.scene,
            source_app_id=None if origin == ORIGIN_MANUAL else ctx.app_id,
            source_app_name=None if origin == ORIGIN_MANUAL else ctx.app_name,
            source_chat_id=None if origin == ORIGIN_MANUAL else ctx.chat_id,
            index_state=INDEX_PENDING,
        )

    async def _attach_detail(self, ctx: MemoryContext, item: MemoryItem, detail: str | None) -> None:
        if not detail:
            return
        validate_detail(detail)
        item.detail_object_key = await self.details.put(ctx, item.id, detail)
        item.detail_sha256 = hashlib.sha256(detail.encode("utf-8")).hexdigest()

    async def index_items(self, ctx: MemoryContext, items: list[MemoryItem]) -> None:
        """Index after commit; a failure or timeout leaves the item pending (decision 5)."""
        for item in items:
            try:
                model_id = await asyncio.wait_for(
                    self.index.upsert(ctx, item.id, item.content), timeout=INDEX_TIMEOUT_SECONDS
                )
            except Exception as exc:
                logger.warning("memory index write failed item={} err={!r}; left pending", item.id, exc)
                continue
            async with _db.async_session() as s:
                await ItemRepository.update_fields(s, ctx, [item.id], index_state=INDEX_OK, index_model_id=model_id)
                await s.commit()

    async def _unindex(self, ctx: MemoryContext, item_ids: list[str]) -> None:
        try:
            await self.index.delete(ctx, item_ids)
        except Exception as exc:
            logger.warning("memory index delete failed items={} err={!r}", item_ids, exc)

    async def _new_head_order(self, session, ctx: MemoryContext) -> int:
        return await ItemRepository.min_pin_order(session, ctx) - 1

    # ------------------------------------------------------------------ explicit write (tool)
    async def write(
        self,
        ctx: MemoryContext,
        action: str,
        content: str | None = None,
        target_id: str | None = None,
        type: str | None = None,
        event_time=None,
        detail: str | None = None,
    ) -> WriteResult:
        if action == "remember":
            return await self._create(ctx, content, type or "fact", event_time, detail, ORIGIN_EXPLICIT, "remember")
        if action == "correct":
            return await self._replace(ctx, target_id, content, type, event_time, detail, ORIGIN_EXPLICIT, "correct")
        if action == "forget":
            return await self._forget(ctx, target_id, "forget")
        raise ValueError(f"unknown memory action {action!r}")

    async def _create(self, ctx, content, item_type, event_time, detail, origin, verb) -> WriteResult:
        text = validate_item(content, item_type)
        item = self._new_item(ctx, text, item_type, origin, event_time, pinned=item_type in RESIDENT_TYPES)
        await self._attach_detail(ctx, item, detail)
        async with _db.async_session() as s:
            if item.pinned:
                item.pin_order = await self._new_head_order(s, ctx)
            await ItemRepository.insert(s, ctx, item)
            await SettingRepository.bump_rev(s, ctx)
            record = await TurnRecordService.add_write(s, ctx, "remember", item.id) if verb == "remember" else None
            record_id = record.id if record else None
            await s.commit()
        await self.index_items(ctx, [item])
        await self.audit.record(ctx, verb, [item.id])
        await self.metrics.incr(ctx, m.ADDED_MANUAL if origin == ORIGIN_MANUAL else m.ADDED_EXPLICIT)
        return WriteResult(ok=True, op=verb, item_id=item.id, record_id=record_id)

    async def _replace(self, ctx, target_id, content, item_type, event_time, detail, origin, verb) -> WriteResult:
        if not target_id:
            raise MemoryItemNotFoundError()
        async with _db.async_session() as s:
            old = await ItemRepository.get_active(s, ctx, target_id)
        if old is None:
            raise MemoryItemNotFoundError()
        new_type = item_type or old.type
        text = validate_item(content, new_type)
        if detail is KEEP:
            # The caller did not touch the detail: it carries over (objects are immutable and
            # keyed by item id, so it is copied to the new item). An empty string drops it.
            detail = None
            if old.detail_object_key:
                try:
                    detail = await self.details.get(old.detail_object_key)
                except Exception as exc:
                    logger.exception("memory detail read failed during edit item={}", target_id)
                    raise MemoryDetailUnavailableError() from exc
        item = self._new_item(ctx, text, new_type, origin, event_time, pinned=new_type in RESIDENT_TYPES)
        if origin == ORIGIN_MANUAL:
            # An edit keeps the original source mark; only the write mode becomes manual.
            item.source_scene, item.source_app_id = old.source_scene, old.source_app_id
            item.source_app_name, item.source_chat_id = old.source_app_name, old.source_chat_id
        await self._attach_detail(ctx, item, detail)
        async with _db.async_session() as s:
            if item.pinned:
                item.pin_order = old.pin_order if old.pinned else await self._new_head_order(s, ctx)
            await ItemRepository.insert(s, ctx, item)
            changed = await ItemRepository.update_status(
                s, ctx, target_id, STATUS_ACTIVE, STATUS_SUPERSEDED, superseded_by=item.id
            )
            if changed == 0:
                await s.rollback()
                raise MemoryItemNotFoundError()
            await SettingRepository.bump_rev(s, ctx)
            record = (
                await TurnRecordService.add_write(s, ctx, "correct", item.id, target_id) if verb == "correct" else None
            )
            record_id = record.id if record else None
            await s.commit()
        await self._unindex(ctx, [target_id])
        await self.index_items(ctx, [item])
        await self.audit.record(ctx, verb, [item.id, target_id])
        await self.metrics.incr(ctx, m.ADDED_MANUAL if origin == ORIGIN_MANUAL else m.ADDED_EXPLICIT)
        await self.metrics.incr(ctx, m.SUPERSEDED)
        return WriteResult(ok=True, op=verb, item_id=item.id, related_item_id=target_id, record_id=record_id)

    async def _forget(self, ctx, target_id, verb) -> WriteResult:
        if not target_id:
            raise MemoryItemNotFoundError()
        async with _db.async_session() as s:
            changed = await ItemRepository.update_status(s, ctx, target_id, STATUS_ACTIVE, STATUS_DELETED)
            if changed == 0:
                await s.rollback()
                raise MemoryItemNotFoundError()
            await SettingRepository.bump_rev(s, ctx)
            record = await TurnRecordService.add_write(s, ctx, "forget", None, target_id) if verb == "forget" else None
            record_id = record.id if record else None
            await s.commit()
        await self._unindex(ctx, [target_id])
        await self.audit.record(ctx, verb, [target_id])
        await self.metrics.incr(ctx, m.DELETED)
        return WriteResult(ok=True, op=verb, related_item_id=target_id, record_id=record_id)

    # ------------------------------------------------------------------ management (AC-88, AC-89)
    async def add_manual(
        self, ctx: MemoryContext, content: str, item_type: str = "fact", event_time=None, detail: str | None = None
    ):
        return await self._create(ctx, content, item_type, event_time, detail or None, ORIGIN_MANUAL, "add")

    async def edit(
        self,
        ctx: MemoryContext,
        item_id: str,
        content: str,
        item_type: str | None = None,
        event_time=None,
        detail=KEEP,
        verb: str = "edit",
    ):
        """Hand edit (or an AI revision the user asked for, ``verb="revise"``).

        ``detail``: ``KEEP`` copies the current full text, ``""`` drops it, text replaces it.
        """
        return await self._replace(ctx, item_id, content, item_type, event_time, detail, ORIGIN_MANUAL, verb)

    async def delete(self, ctx: MemoryContext, item_id: str) -> WriteResult:
        return await self._forget(ctx, item_id, "delete")

    async def clear(self, ctx: MemoryContext) -> None:
        """Hard delete everything of this user in this tenant (AC-93); re-entrant.

        Order: index, objects, turn records and snapshots, item rows, then push
        every registered session's watermark so cleared conversations are not
        consolidated again (decision 7).
        """
        async with _db.async_session() as s:
            keys = await ItemRepository.list_detail_keys(s, ctx)
        await self.index.delete_user(ctx)
        for key in keys:
            await self.details.delete(key)
        await self.details.delete_user(ctx)
        async with _db.async_session() as s:
            await TurnRecordService.delete_user(ctx, session=s)
            removed = await ItemRepository.delete_all(s, ctx)
            await SettingRepository.bump_rev(s, ctx)
            await s.commit()
        await CursorRepository.advance_all_for_user(ctx.tenant_id, ctx.user_id)
        try:
            from bisheng.memory.domain.services.consolidator import clear_marker_key

            # A consolidation run already in flight must not write pre-clear results back.
            await self.kv.set(clear_marker_key(ctx.tenant_id, ctx.user_id), uuid.uuid4().hex, 86400)
        except Exception:
            logger.exception("memory: setting the clear marker failed")
        await self.audit.record(ctx, "clear", [])
        await self.metrics.incr(ctx, m.DELETED, removed)

    async def undo(self, ctx: MemoryContext, record_id: int) -> WriteResult:
        """Undo one explicit write (AC-22). Fails whole, never partially."""
        async with _db.async_session() as s:
            record = await s.get(MemoryTurnRecord, record_id)
            if (
                record is None
                or record.kind != KIND_WRITE
                or record.tenant_id != ctx.tenant_id
                or record.user_id != ctx.user_id
            ):
                raise MemoryUndoClearedError()
            if record.undone:
                raise MemoryUndoAlreadyDoneError()
            op, item_id, related_id = record.op, record.item_id, record.related_item_id
            ids = [i for i in (item_id, related_id) if i]
            rows = {i.id: i for i in await ItemRepository.list_by_ids(s, ctx, ids, active_only=False)}
            if any(i not in rows for i in ids):
                raise MemoryUndoClearedError()
            reindex: list[str] = []
            unindex: list[str] = []
            if op == "remember":
                if await ItemRepository.update_status(s, ctx, item_id, STATUS_ACTIVE, STATUS_DELETED) == 0:
                    await s.rollback()
                    raise MemoryUndoChangedError()
                unindex.append(item_id)
            elif op == "correct":
                if await ItemRepository.update_status(s, ctx, item_id, STATUS_ACTIVE, STATUS_DELETED) == 0:
                    await s.rollback()
                    raise MemoryUndoChangedError()
                restored = await ItemRepository.update_status(
                    s, ctx, related_id, STATUS_SUPERSEDED, STATUS_ACTIVE, clear_superseded_by=True
                )
                if restored == 0:
                    await s.rollback()
                    raise MemoryUndoChangedError()
                unindex.append(item_id)
                reindex.append(related_id)
            elif op == "forget":
                if await ItemRepository.update_status(s, ctx, related_id, STATUS_DELETED, STATUS_ACTIVE) == 0:
                    await s.rollback()
                    raise MemoryUndoChangedError()
                reindex.append(related_id)
            else:
                raise MemoryUndoChangedError()
            record.undone = True
            s.add(record)
            await SettingRepository.bump_rev(s, ctx)
            await s.commit()
        if unindex:
            await self._unindex(ctx, unindex)
        if reindex:
            async with _db.async_session() as s:
                await ItemRepository.update_fields(s, ctx, reindex, index_state=INDEX_PENDING)
                await s.commit()
                items = await ItemRepository.list_by_ids(s, ctx, reindex)
            await self.index_items(ctx, items)
        await self.audit.record(ctx, "undo", ids)
        await self.metrics.incr(ctx, m.UNDO)
        return WriteResult(ok=True, op="undo", item_id=item_id, related_item_id=related_id, record_id=record_id)

    # ------------------------------------------------------------------ consolidation (decision 7)
    async def apply_operations(self, session, ctx: MemoryContext, ops: list[dict]) -> list[MemoryItem]:
        """Apply consolidation operations inside the caller's transaction.

        ``add`` inserts an auto item; ``supersede`` replaces an active item (the old
        row stays, AC-92); ``pin`` adjusts residency within the configured limit.
        Invalid candidates are dropped one by one without affecting the others.
        """
        from bisheng.memory.domain.config import aget_memory_config
        from bisheng.memory.domain.models.memory_item import ORIGIN_AUTO

        config = await aget_memory_config()
        new_items: list[MemoryItem] = []
        superseded: list[str] = []
        pinned_now = len(await ItemRepository.list_resident(session, ctx, RESIDENT_TYPES))
        for op in ops or []:
            kind = op.get("op")
            try:
                if kind in ("add", "supersede", "rewrite"):
                    item_type = op.get("type") or "fact"
                    old = None
                    if kind != "add":
                        old = await ItemRepository.get_active(session, ctx, op.get("target_id") or "")
                        if old is None:
                            continue
                        item_type = op.get("type") or old.type
                    text = validate_item(op.get("content"), item_type)
                    want_pin = bool(op.get("pinned", old.pinned if old else False)) and item_type in RESIDENT_TYPES
                    keeps_slot = old is not None and old.pinned
                    if want_pin and not keeps_slot and pinned_now >= config.resident_max_items:
                        want_pin = False
                    item = self._new_item(ctx, text, item_type, ORIGIN_AUTO, op.get("event_time"), pinned=want_pin)
                    if old is not None and kind == "rewrite":
                        # A tense rewrite is the same memory: keep its source mark (AC-04, AC-98).
                        item.rewritten = True
                        item.source_scene, item.source_app_id = old.source_scene, old.source_app_id
                        item.source_app_name, item.source_chat_id = old.source_app_name, old.source_chat_id
                        item.origin = old.origin
                    if want_pin:
                        item.pin_order = (
                            old.pin_order if keeps_slot else await ItemRepository.max_pin_order(session, ctx) + 1
                        )
                        pinned_now += 0 if keeps_slot else 1
                    elif keeps_slot:
                        pinned_now -= 1
                    if old is not None:
                        changed = await ItemRepository.update_status(
                            session, ctx, old.id, STATUS_ACTIVE, STATUS_SUPERSEDED, superseded_by=item.id
                        )
                        if changed == 0:
                            continue
                        superseded.append(old.id)
                    await ItemRepository.insert(session, ctx, item)
                    new_items.append(item)
                elif kind == "pin":
                    target = await ItemRepository.get_active(session, ctx, op.get("target_id") or "")
                    if target is None or target.type not in RESIDENT_TYPES or bool(op.get("pinned")) == target.pinned:
                        continue
                    if op.get("pinned"):
                        if pinned_now >= config.resident_max_items:
                            continue
                        order = await ItemRepository.max_pin_order(session, ctx) + 1
                        await ItemRepository.update_fields(session, ctx, [target.id], pinned=True, pin_order=order)
                        pinned_now += 1
                    else:
                        await ItemRepository.update_fields(session, ctx, [target.id], pinned=False)
                        pinned_now -= 1
            except BaseErrorCode as exc:
                logger.info("memory consolidation dropped a candidate: {}", exc.message)
            except ValueError as exc:
                logger.info("memory consolidation dropped a candidate: {}", exc)
        ctx.extra["superseded_ids"] = superseded
        return new_items

    async def after_auto_commit(self, ctx: MemoryContext, new_items: list[MemoryItem]) -> None:
        superseded = ctx.extra.pop("superseded_ids", [])
        if superseded:
            await self._unindex(ctx, superseded)
        await self.index_items(ctx, new_items)
        await self.metrics.incr(ctx, m.ADDED_AUTO, len(new_items))
        await self.metrics.incr(ctx, m.SUPERSEDED, len(superseded))
