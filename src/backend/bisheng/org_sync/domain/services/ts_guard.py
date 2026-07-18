"""OrgSyncTsGuard — per-external_id ts conflict decision (INV-T12).

Shared between F014 (Gateway realtime) and F015 (Celery reconcile). Pure
decision function; the caller is responsible for persisting
``last_sync_ts`` after a successful upsert/archive. Keeping the decision
and the write separated makes the 8-case matrix straightforward to unit
test without a DB round-trip.

INV-T12 rules (v2.5.1 PRD §9.5):
  - ``incoming_ts < last_sync_ts`` → ``SKIP_TS`` (stale message dropped)
  - Same ts with ``remove`` already applied (``is_deleted=1``) vs an
    incoming ``upsert`` → ``SKIP_TS`` (remove wins)
  - Otherwise → ``APPLY``
"""

from enum import Enum
from typing import Literal, Optional

from bisheng.database.models.department import Department


class GuardDecision(str, Enum):
    APPLY = 'apply'
    SKIP_TS = 'skip_ts'


Action = Literal['upsert', 'remove']


class OrgSyncTsGuard:
    """Synchronous pure-function guard. See module docstring for rules."""

    @classmethod
    async def check_and_update(
        cls,
        existing: Optional[Department],
        incoming_ts: int,
        action: Action,
    ) -> GuardDecision:
        """Decide whether to apply an incoming upsert/remove for a department.

        ``existing`` is the current DB row (including ``is_deleted=1`` rows)
        or None when the external_id has never been synced. The method does
        not perform any I/O — callers commit the change themselves on an
        APPLY verdict and then persist ``last_sync_ts = incoming_ts``.
        """
        if existing is None:
            # Never seen: only upserts make sense; removes on unknown rows
            # are silently dropped by the caller (no history to protect).
            return (
                GuardDecision.APPLY if action == 'upsert'
                else GuardDecision.SKIP_TS
            )

        last = int(existing.last_sync_ts or 0)

        # Stale message → drop.
        if incoming_ts < last:
            return GuardDecision.SKIP_TS

        # Same ts: "remove wins" when a prior remove already landed.
        # We do not have a cross-request oracle for the other side of a
        # same-ts collision; the invariant holds because the first writer
        # sets ``is_deleted=1`` and later upserts observe it here.
        if (
            incoming_ts == last
            and action == 'upsert'
            and int(getattr(existing, 'is_deleted', 0) or 0) == 1
        ):
            return GuardDecision.SKIP_TS

        return GuardDecision.APPLY
