"""Allowlisted low-cardinality audit metrics; never original data or session identities."""

from bisheng.common.services.metric_log import emit_metric


def record_audit_metric(event, *, tenant_id=None, kind=None, value=1, duration_ms=None):
    emit_metric("dsh_model_audit", event=event, tenant_id=tenant_id, kind=kind, value=value, duration_ms=duration_ms)
