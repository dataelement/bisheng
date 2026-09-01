"""T010 + F058 follow-up — user-related dashboard dataset consolidation (AC-06, AC-07).

- 用户反馈统计 (mid_user_interact_dtl) drops out of the dashboard picker.
- 用户规模统计 (mid_user_increment) is now the ONE surviving, visible dataset — its
  schema_config is the union of what used to be three separate datasets' metrics and
  dimensions, and its es_index_name points at the shared ES index
  (USER_ENGAGEMENT_ES_INDEX). dataset_code/es_index_name deliberately keep the ORIGINAL
  "mid_user_increment" identity so existing components (including the preset_oss
  dashboard SQL in this file) keep working without edits.
- 活跃用户规模统计 (mid_active_user) / 全员每日参与度 (mid_user_daily_participation) are
  hidden from the picker (is_visible=False) but their es_index_name is ALSO repointed at
  the shared index, so any pre-existing component referencing them by dataset_code still
  reads live (not stale/frozen) data.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub

from bisheng.telemetry.domain.mid_table.user_engagement_shared import USER_ENGAGEMENT_ES_INDEX
from bisheng.telemetry_search.domain.init_dataset import (
    DASHBOARD_DATASET,
    DASHBOARD_DATASET_REFRESH_CODES,
)

_HIDDEN_ENGAGEMENT_CODES = ("mid_active_user", "mid_user_daily_participation")


def _dataset(code: str):
    return next(d for d in DASHBOARD_DATASET if d.dataset_code == code)


def test_feedback_dataset_marked_not_visible():
    assert _dataset("mid_user_interact_dtl").is_visible is False


def test_mid_user_increment_is_the_one_surviving_visible_entry():
    surviving = _dataset("mid_user_increment")
    assert surviving.is_visible is True
    assert surviving.es_index_name == USER_ENGAGEMENT_ES_INDEX


def test_surviving_dataset_schema_is_the_union_of_all_three_sources():
    fields = {m["field"] for m in _dataset("mid_user_increment").schema_config["dimensions"]}
    metric_fields = {m["field"] for m in _dataset("mid_user_increment").schema_config["metrics"]}
    # from mid_user_increment
    assert {"total_user_count", "new_user_count"} <= metric_fields
    # from mid_active_user
    assert "active_user_count" in metric_fields
    # from mid_user_daily_participation
    assert {"participation_rate", "logged_in_employee_count", "active_employee_count", "login_count"} <= metric_fields
    assert {"local_date", "primary_department_id", "primary_department_name", "user_id", "user_name"} <= fields


def test_non_surviving_engagement_datasets_hidden_but_index_repointed():
    """The two merged-away datasets stay is_visible=False, but their es_index_name is
    still repointed at the shared index — pre-existing components referencing them by
    dataset_code must keep reading live data, not a frozen/abandoned index."""
    for code in _HIDDEN_ENGAGEMENT_CODES:
        dataset = _dataset(code)
        assert dataset.is_visible is False
        assert dataset.es_index_name == USER_ENGAGEMENT_ES_INDEX


def test_previously_insert_once_datasets_now_refresh_on_startup():
    """Regression guard: mid_user_increment/mid_active_user/mid_user_interact_dtl used to be
    bulk_save-only (first install only) — without adding them to the refresh list, an
    already-deployed instance's rows would never pick up is_visible/dataset_group."""
    for code in ("mid_user_increment", "mid_active_user", "mid_user_interact_dtl"):
        assert code in DASHBOARD_DATASET_REFRESH_CODES


async def test_get_dataset_options_excludes_hidden_dataset(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard as module

    class _FakeDbSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *_exc):
            return False

    visible_datasets = [SimpleNamespace(dataset_code="mid_user_increment", is_visible=True)]
    repository = SimpleNamespace(find_all=AsyncMock(return_value=visible_datasets))
    monkeypatch.setattr(module, "get_async_db_session", _FakeDbSession)
    monkeypatch.setattr(module, "DashboardDatasetRepositoryImpl", lambda _session: repository)
    monkeypatch.setattr(module, "is_commercial", lambda: False)

    result = await module.DashboardService.get_dataset_options()

    assert result == visible_datasets
    repository.find_all.assert_awaited_once_with(is_commercial_only=False, is_visible=True)


async def test_get_dataset_options_commercial_still_filters_visibility(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard as module

    class _FakeDbSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *_exc):
            return False

    repository = SimpleNamespace(find_all=AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "get_async_db_session", _FakeDbSession)
    monkeypatch.setattr(module, "DashboardDatasetRepositoryImpl", lambda _session: repository)
    monkeypatch.setattr(module, "is_commercial", lambda: True)

    await module.DashboardService.get_dataset_options()

    repository.find_all.assert_awaited_once_with(is_visible=True)
