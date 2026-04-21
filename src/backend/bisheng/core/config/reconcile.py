"""Reconcile configuration model (F015-ldap-reconcile-celery).

Controls the 6h forced organization reconcile beat, relink flow, and
ts_conflict weekly / daily-escalation reporting. See
`features/v2.5.1/015-ldap-reconcile-celery/spec.md` for the protocol and
INV-T12 (v2.5.1 release-contract) for the conflict-resolution invariant.
"""

from pydantic import BaseModel, Field


class ReconcileConf(BaseModel):
    """F015 reconcile + relink + conflict-report settings."""

    beat_cron_reconcile: str = Field(
        default='0 */6 * * *',
        description=(
            '6h forced reconcile beat schedule. Applies to '
            '`reconcile_all_organizations` (the fan-out Celery task).'
        ),
    )

    beat_cron_weekly_report: str = Field(
        default='0 9 * * MON',
        description=(
            'Weekly ts_conflict aggregation (Mon 09:00 local). Sends an inbox '
            'notice to every global super-admin when any external_id crosses '
            '`weekly_conflict_threshold` within the past 7 days.'
        ),
    )

    beat_cron_daily_escalation: str = Field(
        default='0 9 * * *',
        description=(
            'Daily escalation beat. Only fires an inbox notice when the last '
            'weekly report is older than `daily_escalation_days` AND the '
            'flagged external_ids still have unresolved conflicts.'
        ),
    )

    redis_lock_ttl_seconds: int = Field(
        default=1800,
        description=(
            'Redis SETNX TTL for the per-config reconcile lock '
            '(key: org_reconcile:{config_id}). 30 min matches the Celery '
            'soft time limit so a stuck worker cannot hold the lock forever.'
        ),
    )

    relink_conflict_ttl_seconds: int = Field(
        default=604800,  # 7 days
        description=(
            'Redis Hash TTL for multi-candidate relink conflicts '
            '(key: relink_conflict:{dept_id}). Admins must resolve within 7 '
            'days via POST /api/v1/internal/departments/relink/resolve-conflict.'
        ),
    )

    weekly_conflict_threshold: int = Field(
        default=3,
        description=(
            'Minimum ts_conflict count for a single external_id within 7 days '
            'to be flagged in the weekly report (AC-12).'
        ),
    )

    daily_escalation_days: int = Field(
        default=5,
        description=(
            'Grace window between weekly report and daily escalation. Once '
            'the weekly report is older than this value and conflicts remain, '
            'switch to daily notifications (AC-12).'
        ),
    )

    task_time_limit: int = Field(
        default=1800,
        description='Hard time limit (seconds) for `reconcile_single_config`.',
    )

    task_soft_time_limit: int = Field(
        default=1500,
        description='Soft time limit (seconds) for `reconcile_single_config`.',
    )
