"""The 组织同步 list must keep covering every run type it can produce.

The list query filters on ``LISTED_TRIGGER_TYPES``; adding a new writer without
adding its label would silently hide those runs from the page, so pin the set.
"""

from bisheng.org_sync.domain.models.org_sync import LISTED_TRIGGER_TYPES


def test_listing_covers_every_user_visible_run_type():
    # Gateway push, no-Gateway cron script, admin console run-now.
    assert set(LISTED_TRIGGER_TYPES) == {"sso_realtime", "scheduled", "manual"}


def test_diagnostic_rows_stay_out_of_the_list():
    # F015 event/reconcile rows are diagnostics, not runs an operator triggered.
    assert "event" not in LISTED_TRIGGER_TYPES
    assert "reconcile" not in LISTED_TRIGGER_TYPES
