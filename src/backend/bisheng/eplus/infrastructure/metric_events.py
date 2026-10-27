"""Best-effort E+ event formatting; all counting belongs to monitoring."""

import hashlib
import json
import uuid

from loguru import logger

from bisheng.common.services.metric_log import emit_metric
from bisheng.eplus.domain.schemas.metric import TerminalMetricSnapshot


def emit_request_metric(value: TerminalMetricSnapshot) -> None:
    try:
        identity = json.dumps(
            ["eplus-user-v1", value.tenant_id, value.sender_external_id], ensure_ascii=False, separators=(",", ":")
        )
        emit_metric(
            "eplus_robot_request",
            schema_version=1,
            source="eplus_robot",
            tenant_id=value.tenant_id,
            bot_id=value.bot_id,
            bot_config_id=value.bot_config_id,
            user_id=hashlib.sha256(identity.encode()).hexdigest(),
            message_id=value.message_id,
            conversation_id=value.conversation_id,
            event_id=uuid.uuid4().hex,
            admitted=value.admitted,
            result=value.result,
            reason=value.reason,
            reply_status=value.reply_status,
            event_time_ms=int(value.event_time.timestamp() * 1000),
            elapsed_ms=max(0, (value.event_time - value.received_at).total_seconds() * 1000),
        )
    except Exception as exc:
        # Optional telemetry must not change business state or expose source values.
        logger.debug("E+ metric formatting failed error_type={}", type(exc).__name__)


class ConnectionMetricObserver:
    def __init__(self, *, tenant_id, bot_id, bot_config_id, lease, stale_after_s=90):
        self.tenant_id = tenant_id
        self.bot_id = bot_id
        self.bot_config_id = bot_config_id
        self.lease = lease
        self.stale_after_s = stale_after_s
        self._sequence = 0
        self._ended = False

    def __call__(self, event, fields):
        try:
            names = {
                "connection.opening": "opening",
                "subscription.authenticated": "authenticated",
                "heartbeat.ok": "heartbeat_ok",
                "heartbeat.failed": "heartbeat_failed",
                "connection.ended": "closed",
                "connection.auth_failed": "auth_failed",
                "connection.retrying": "retrying",
                "connection.taken_over": "taken_over",
            }
            name = names.get(event)
            if name is None:
                return
            alive = name in {"authenticated", "heartbeat_ok"}
            if name in {"closed", "taken_over"}:
                self._ended = True
            if alive:
                if self._ended:
                    return
                self.lease.ensure_owned()
            self._sequence += 1
            timestamp = int(fields["server_unix_ms"])
            emit_metric(
                "eplus_robot_connection",
                schema_version=1,
                source="eplus_robot",
                tenant_id=self.tenant_id,
                bot_id=self.bot_id,
                bot_config_id=self.bot_config_id,
                connection_id=fields["connection_id"],
                event_seq=self._sequence,
                event=name,
                event_time_ms=timestamp,
                expires_at_ms=timestamp + self.stale_after_s * 1000 if alive else None,
                reason=fields.get("reason") or fields.get("error_type"),
            )
        except Exception as exc:
            # Lease loss or telemetry failure only suppresses this observation.
            logger.debug("E+ connection metric skipped error_type={}", type(exc).__name__)
