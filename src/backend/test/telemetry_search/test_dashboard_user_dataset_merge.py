"""T010 — user-related dashboard dataset consolidation (F058, AC-06, AC-07).

- 用户反馈统计 (mid_user_interact_dtl) drops out of the dashboard picker.
- 用户规模统计 (mid_user_increment) / 活跃用户规模统计 (mid_active_user) /
  全员每日参与度 (mid_user_daily_participation) share one dataset_group so the
  frontend can render them as sub-panels of a single entry (UI-level merge only —
  each still queries its own ES index, see spec.md AD-04).
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub

from bisheng.telemetry_search.domain.init_dataset import (
    DASHBOARD_DATASET,
    DASHBOARD_DATASET_REFRESH_CODES,
)

_USER_ENGAGEMENT_CODES = ("mid_user_increment", "mid_active_user", "mid_user_daily_participation")


def _dataset(code: str):
    return next(d for d in DASHBOARD_DATASET if d.dataset_code == code)


def test_feedback_dataset_marked_not_visible():
    assert _dataset("mid_user_interact_dtl").is_visible is False


def test_engagement_datasets_share_one_group():
    groups = {_dataset(code).dataset_group for code in _USER_ENGAGEMENT_CODES}
    assert groups == {"user_engagement"}
    assert _dataset("mid_user_interact_dtl").dataset_group != "user_engagement"


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
