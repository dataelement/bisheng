"""F004 design §7 item 17: a direct run writes the citation audit line of daily chat.

The legacy daily chat logs one ``[daily-citation-audit]`` line per turn, right
after it selected the sources the answer cites (``daily_citation.log_citation_audit``).
The direct run on the unified runtime writes the same line, with the same
fields, when its projector writes the answer row.

No database, no Redis server: the message table is in memory, Redis is fakeredis
and the graph is driven by the scripted model of ``test_direct_run``.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from loguru import logger

from bisheng.citation.domain.services.daily_citation_handles import StreamStats
from bisheng.linsight.domain.schemas import run_events
from bisheng.workstation.domain.services import chat_service, daily_citation, direct_run_turn
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector
from test.workstation.run_persist_support import MessageTable
from test.workstation.test_direct_run import CID, USER, make_env  # noqa: F401

RUN = "run-audit"
AUDIT = "[daily-citation-audit]"


class _Lines:
    """Captures loguru records as ``(level, message)``."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self._sink_id: int | None = None

    def __enter__(self) -> _Lines:
        self._sink_id = logger.add(
            lambda m: self.records.append((m.record["level"].name, m.record["message"])), level="INFO"
        )
        return self

    def __exit__(self, *exc: Any) -> None:
        logger.remove(self._sink_id)

    def audit(self) -> list[tuple[str, str]]:
        return [(level, message) for level, message in self.records if message.startswith(AUDIT)]


@pytest.fixture
def table(monkeypatch):
    async def no_citations(**_: Any) -> None:
        return None

    async def cited(items, text):
        return [item for item in items if item["id"] in text]

    monkeypatch.setattr(chat_service, "save_message_citations", no_citations)
    monkeypatch.setattr(chat_service, "select_cited_items", cited)
    return MessageTable().install(monkeypatch)


def _event(event_type: str, data: dict | None = None) -> dict:
    return run_events.make_event(event_type, data or {}, run_id=RUN)


def _turn(*, seen: set[str], unknown: list[str] | None = None, legacy: int = 0) -> direct_run_turn.DirectTurn:
    turn = direct_run_turn.open_turn(CID, RUN)
    turn.model = "101"
    turn.scope.seen_keys.update(seen)
    turn.converter.stats.unknown.extend(unknown or [])
    turn.converter.stats.legacy_markers = legacy
    return turn


def _projector(collected: list[dict]) -> DirectRunProjector:
    return DirectRunProjector(
        run_id=RUN, conversation_id=CID, user_id=USER, sender="model", citation_items=lambda: collected
    )


def _legacy_line(*, seen: set[str], cited: list, unknown: list[str], legacy: int) -> tuple[str, str]:
    """The line the legacy daily chat writes for the same turn."""
    scope = direct_run_turn.DailyCitationScope(CID)
    scope.seen_keys.update(seen)
    with _Lines() as lines:
        daily_citation.log_citation_audit(
            chat_id=CID,
            model="101",
            scope=scope,
            stats=StreamStats(unknown=list(unknown), legacy_markers=legacy),
            cited=cited,
        )
    (record,) = lines.audit()
    return record


async def test_audit_line_has_the_legacy_fields_and_format(table):
    collected = [{"id": "[citation:k1]"}, {"id": "[citation:k2]"}]
    turn = _turn(seen={"k1", "k2", "k3"}, unknown=["S9"], legacy=2)
    projector = _projector(collected)
    try:
        with _Lines() as lines:
            await projector.on_event(_event(run_events.TEXT, {"text": "见 [citation:k1]"}))
            assert lines.audit() == []
            await projector.on_event(_event(run_events.RUN_FINISHED))
    finally:
        direct_run_turn.close_turn(RUN, turn)

    assert lines.audit() == [
        ("INFO", f"{AUDIT} chat={CID} model=101 sources_seen=3 cited=1 unknown_handles=1 legacy_markers=2")
    ]
    # Byte for byte the legacy line of the same turn.
    assert lines.audit() == [_legacy_line(seen={"k1", "k2", "k3"}, cited=collected[:1], unknown=["S9"], legacy=2)]
    # Written at the legacy point: before the answer row is saved.
    saved_at = next(i for i, (_, message) in enumerate(lines.records) if message.startswith("direct run answer saved"))
    audit_at = next(i for i, (_, message) in enumerate(lines.records) if message.startswith(AUDIT))
    assert audit_at < saved_at


async def test_sources_seen_but_none_cited_is_a_warning(table):
    turn = _turn(seen={"k1"})
    projector = _projector([{"id": "[citation:k1]"}])
    try:
        with _Lines() as lines:
            await projector.on_event(_event(run_events.TEXT, {"text": "没有引用"}))
            await projector.on_event(_event(run_events.RUN_FINISHED))
    finally:
        direct_run_turn.close_turn(RUN, turn)

    assert lines.audit() == [
        ("WARNING", f"{AUDIT} chat={CID} model=101 sources_seen=1 cited=0 unknown_handles=0 legacy_markers=0")
    ]


@pytest.mark.parametrize(
    ("terminal", "data"),
    [(run_events.RUN_STOPPED, {}), (run_events.RUN_FAILED, {"detail": "boom", "reason": "error"})],
)
async def test_stopped_and_failed_runs_write_the_line_once(table, terminal, data):
    """The legacy stream writes it on its interruption path too."""
    turn = _turn(seen=set())
    projector = _projector([])
    try:
        with _Lines() as lines:
            await projector.on_event(_event(run_events.TEXT, {"text": "半句"}))
            await projector.on_event(_event(terminal, data))
            await projector.aclose()
    finally:
        direct_run_turn.close_turn(RUN, turn)

    assert len(lines.audit()) == 1


async def test_blocked_answer_writes_no_line(table):
    """The legacy stream returns before the audit when the output scanner hits."""
    turn = _turn(seen={"k1"})
    projector = _projector([{"id": "[citation:k1]"}])
    try:
        with _Lines() as lines:
            await projector.on_event(
                _event(run_events.RUN_FINISHED, {"content_safety": True, "auto_reply": "不能回答"})
            )
    finally:
        direct_run_turn.close_turn(RUN, turn)

    assert lines.audit() == []


async def test_row_written_outside_the_running_process_writes_no_line(table):
    """No turn in this process: the converter counts do not exist here, so nothing is invented."""
    projector = _projector([])
    with _Lines() as lines:
        await projector.on_event(_event(run_events.TEXT, {"text": "回答"}))
        await projector.on_event(_event(run_events.RUN_FINISHED))

    assert direct_run_turn.log_citation_audit(RUN, []) is False
    assert lines.audit() == []
    assert len(table.answers()) == 1


async def test_direct_run_writes_one_audit_line(make_env, table):  # noqa: F811
    """End to end: the real runner, the real graph, the projector as the run's hook."""
    env = make_env([AIMessage(content="你好，我没有查资料。")])
    ctx = await env.submit("你好")
    ctx.model_id = "101"
    projector = DirectRunProjector(
        run_id=ctx.run_id,
        conversation_id=CID,
        user_id=USER,
        sender="model",
        citation_items=lambda: direct_run_turn.collected_citations(ctx.run_id),
    )
    env.hook = projector.on_event

    with _Lines() as lines:
        assert (await env.run(ctx)).status == "finished"

    (record,) = lines.audit()
    assert record[0] == "INFO"
    assert re.fullmatch(
        rf"\[daily-citation-audit\] chat={CID} model=101 sources_seen=0 cited=0 unknown_handles=0 legacy_markers=0",
        record[1],
    )
    assert len(table.answers()) == 1
