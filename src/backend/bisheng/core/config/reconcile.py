"""Relink configuration retained from F015 organization reconciliation.

The provider-pull Celery reconcile and its conflict reports were retired after
Gateway push became the organization-data source of truth. See
`features/v2.5.1/015-ldap-reconcile-celery/spec.md` for the protocol and
INV-T12 (v2.5.1 release-contract) for the conflict-resolution invariant.
"""

from pydantic import BaseModel, Field


class ReconcileConf(BaseModel):
    """Targeted reconcile locking and department relink settings."""

    redis_lock_ttl_seconds: int = Field(
        default=1800,
        description=(
            "Redis SETNX TTL for the per-config reconcile lock "
            "(key: org_reconcile:{config_id}). 30 min matches the Celery "
            "soft time limit so a stuck worker cannot hold the lock forever."
        ),
    )

    relink_conflict_ttl_seconds: int = Field(
        default=604800,  # 7 days
        description=(
            "Redis Hash TTL for multi-candidate relink conflicts "
            "(key: relink_conflict:{dept_id}). Admins must resolve within 7 "
            "days via POST /api/v1/internal/departments/relink/resolve-conflict."
        ),
    )
