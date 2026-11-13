"""Audit records for memory changes (AC-101; design decision 20).

Action names are ``memory.item.<verb>``. They are deliberately NOT added to the
admin audit page whitelist (``_UI_VISIBLE_V2_ACTIONS``): this release shows no
administrator any interface about a user's memory. Metadata never carries content.
"""

from __future__ import annotations

from loguru import logger

from bisheng.memory.domain.ports import MemoryContext

ACTIONS = {
    "remember": "memory.item.remember",
    "correct": "memory.item.correct",
    "forget": "memory.item.forget",
    "add": "memory.item.add",
    "edit": "memory.item.edit",
    "delete": "memory.item.delete",
    "clear": "memory.item.clear",
    "undo": "memory.item.undo",
}


async def _default_writer(**kwargs):
    from bisheng.database.models.audit_log import AuditLogDao

    await AuditLogDao.ainsert_v2(**kwargs)


class MemoryAudit:
    def __init__(self, writer=None):
        self._writer = writer or _default_writer

    async def record(self, ctx: MemoryContext, verb: str, item_ids: list[str], operator_id: int | None = None):
        action = ACTIONS[verb]
        try:
            await self._writer(
                tenant_id=ctx.tenant_id,
                operator_id=int(operator_id if operator_id is not None else ctx.user_id),
                operator_tenant_id=ctx.tenant_id,
                action=action,
                target_type="memory_item",
                target_id=item_ids[0] if len(item_ids) == 1 else None,
                metadata={"item_ids": list(item_ids), "scene": ctx.scene},
            )
        except Exception:
            # Audit is written after the change committed; failing it must not undo
            # the user's operation. Logged with traceback for follow-up.
            logger.exception("memory audit write failed action={} items={}", action, item_ids)
