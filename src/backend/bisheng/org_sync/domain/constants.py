"""F015 string constants used across reconcile + relink + reporter.

Centralises the ``event_type`` / ``level`` tags written into
``org_sync_log`` and the ``audit_log.action`` tags written by the
relink / reconcile flows. Kept as plain class attributes (not Enum)
so values can be passed directly into SQLModel columns and Pydantic
fields without ``.value`` indirection, while still giving IDEs a
single location to grep for usages.
"""


class EventType:
    """``org_sync_log.event_type`` values owned by F015."""

    STALE_TS = 'stale_ts'
    TS_CONFLICT = 'ts_conflict'
    CONFLICT_WEEKLY_SENT = 'conflict_weekly_sent'
    CONFLICT_DAILY_ESCALATION_SENT = 'conflict_daily_escalation_sent'


class EventLevel:
    """``org_sync_log.level`` values."""

    INFO = 'info'
    WARN = 'warn'
    ERROR = 'error'


class AuditAction:
    """``audit_log.action`` values emitted by F015 services.

    Department-scoped actions use the ``dept.*`` namespace consistent
    with F011 / F014 (see F011 §5.4.2 action catalogue).
    """

    DEPT_SYNC_CONFLICT = 'dept.sync_conflict'
    DEPT_RELINK_APPLIED = 'dept.relink_applied'
    DEPT_RELINK_RESOLVED = 'dept.relink_resolved'


class ReconcileAction:
    """String tags passed into ``OrgSyncTsGuard.check_and_update(action=...)``.

    Mirrors the F014 TsGuard protocol so we don't scatter raw 'upsert'
    / 'remove' strings in the service layer.
    """

    UPSERT = 'upsert'
    REMOVE = 'remove'
