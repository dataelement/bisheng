"""Per-turn citation state for the workbench daily chat (F072).

One ``DailyCitationScope`` lives for one daily-chat turn. It mirrors the
session handle table that the task mode also writes
(``linsight:cite_handles:<conversation_id>``, F069), so one source keeps one
number across daily turns and task turns of the same conversation.

It satisfies what ``assign_handles`` needs (``enabled``, ``session_id``,
``key_to_handle``, ``register_handle``) and deliberately never pins the
task-mode contract (``pins_contract = False``): the daily chat has no switch,
and pinning here would override the task-mode kill switch for this
conversation (design §3 decision 1).

``handles`` (handle → registry key) is handed to the stream converter as-is;
tools allocating mid-turn show up in it immediately.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.citation.domain.services.citation_handle_service import _item_key, load_handle_table


class DailyCitationScope:
    enabled = True
    pins_contract = False

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.handles: dict[str, str] = {}  # handle -> registry key
        self.key_to_handle: dict[str, str] = {}
        self.entries: list[dict] = []
        # registry keys this turn's tools showed to the model (audit only)
        self.seen_keys: set[str] = set()
        # False when the table could not be read; the turn still runs
        self.loaded = False

    def register_handle(self, handle: str, key: str, entry: dict) -> None:
        # A source retrieved again this turn keeps its number but gets a fresh
        # registry key; point the handle at the fresh key so the answer binds
        # to this turn's item instead of needing a cross-turn lookup. Older
        # keys stay mapped for history replay.
        self.handles[handle] = key
        self.key_to_handle[key] = handle
        self.entries.append(dict(entry, handle=handle, key=key))

    def record_seen(self, items: list[Any] | None) -> None:
        for item in items or []:
            key = _item_key(item)
            if key:
                self.seen_keys.add(key)

    async def load(self) -> None:
        """Hydrate the mirror from Redis; never raises (the turn goes on without it)."""
        if not self.session_id:
            return
        try:
            entries, _ = await load_handle_table(self.session_id)
        except Exception:
            logger.opt(exception=True).warning(f"[daily-citation] failed to load handle table chat={self.session_id}")
            return
        for handle, entry in entries.items():
            key = entry.get("key") if isinstance(entry, dict) else None
            if handle and key:
                self.register_handle(handle, key, entry)
        self.loaded = True
