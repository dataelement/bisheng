"""Immutable, content-free observations of existing E+ business state."""

from dataclasses import dataclass
from datetime import datetime

METRIC_SNAPSHOTS_KEY = "eplus_terminal_metrics"


@dataclass(frozen=True, slots=True)
class TerminalMetricSnapshot:
    tenant_id: int
    bot_id: str
    bot_config_id: int
    message_id: str
    sender_external_id: str
    conversation_id: str | None
    admitted: bool
    result: str
    reason: str | None
    reply_status: str
    event_time: datetime
    received_at: datetime

    @classmethod
    def from_message(cls, row, *, status=None, finished_at=None, error_code=None, duplicate=False):
        state = status or row.status
        admitted = bool(row.turn_id) and not duplicate
        result = "duplicate" if duplicate else "rejected" if not admitted else "failed"
        if admitted and state == "SUCCEEDED" and row.reply_status == "FINISHED":
            result = "success"
        now = finished_at or row.finished_at or datetime.now()
        return cls(
            tenant_id=int(row.tenant_id),
            bot_id=row.bot_id,
            bot_config_id=int(row.bot_config_id),
            message_id=row.msgid,
            sender_external_id=row.sender_external_id,
            conversation_id=row.conversation_id,
            admitted=admitted,
            result=result,
            reason=error_code or row.error_code,
            reply_status=row.reply_status,
            event_time=now,
            received_at=row.received_at or now,
        )
