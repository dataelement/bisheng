"""``[Sn]`` handles in the streamed answer of a unified run, turned into citation markers.

Both run profiles publish the main agent's answer as ``text`` events. The model
writes short handles (``[S3]``); the frontend renders citation markers. This
rewriter sends the main-answer text through the F075 ``HandleStreamConverter``
before the event is written. The converter holds back a tail that may still
become a handle (``[S`` at the end of a delta); any other event ends the text
run, so the held tail is written first, as one more ``text`` event.

Used by the direct profile (``DirectTurn``) and the planned profile
(``task_exec._UnifiedRun``).
"""

from __future__ import annotations

from bisheng.citation.domain.services.daily_citation_handles import HandleStreamConverter
from bisheng.linsight.domain.schemas import run_events


class TextHandleRewriter:
    def __init__(self, handles: dict[str, str] | None = None):
        # The caller keeps adding handles to ``handles`` while tools run.
        self.converter = HandleStreamConverter(handles)
        self._template: dict | None = None
        self._pending = False

    def rewrite(self, event: dict) -> list[dict]:
        """The events to write in place of ``event`` (zero, one or two)."""
        data = event.get("data") or {}
        if event.get("type") == run_events.TEXT and not data.get("namespace"):
            self._template = event
            self._pending = True
            converted = self.converter.feed(str(data.get("text") or ""))
            return [{**event, "data": {**data, "text": converted}}] if converted else []
        return [*self.flush(), event]

    def flush(self) -> list[dict]:
        """The held tail of the current text run as a ``text`` event, if any."""
        if not self._pending or self._template is None:
            return []
        self._pending = False
        tail = self.converter.flush()
        if not tail:
            return []
        template = self._template
        return [{**template, "data": {**(template.get("data") or {}), "text": tail}}]
