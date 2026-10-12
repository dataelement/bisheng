"""DSH observability is best-effort and never participates in quota decisions."""

from contextlib import contextmanager

from loguru import logger

from bisheng.common.services.metric_log import emit_metric
from bisheng.core.logger import trace_id_var


@contextmanager
def request_trace(request_id: str):
    token = trace_id_var.set(request_id)
    try:
        yield
    finally:
        trace_id_var.reset(token)


def record_settlement(event):
    try:
        # Only allowlisted accounting fields, never messages, tokens or upstream errors.
        emit_metric(
            "dsh_settlement",
            app_type="dsh_desktop",
            request_id=event.request_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            model_id=event.model_id,
            status=event.status,
            used_tokens=event.total_tokens,
        )
    except Exception:
        logger.warning("DSH settlement telemetry unavailable for request {}", event.request_id)
