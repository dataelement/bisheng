"""Share-link authorization for GET /workbench/session-version-list.

In 2.6 task mode a conversation holds ONE session_version per turn (the 2.0
integer-"version" re-run concept is dead — ``version`` is now a datetime sort
key). A whole-conversation (workbench_chat) share must therefore return EVERY
turn's version to a non-owner viewer; a single-version (linsight_session) share
must still narrow to just the pinned versionId.

Regression guard: a non-owner opening a workbench_chat share saw
"任务详情加载失败" because the endpoint filtered the version list by a missing
``meta_data.versionId`` and returned an empty list, so the frontend
``TaskTurnPanel`` could not find its turn's version to hydrate.

The endpoint's auth branch is exercised directly (DB/service mocked) — the unit
under test is that branch, not DB access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.linsight.api.endpoints import linsight as linsight_ep
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareLink, ShareMode

OWNER_ID = 100
VIEWER_ID = 999
SESSION_ID = "sess-share-1"


def _version(vid: str, user_id: int = OWNER_ID) -> LinsightSessionVersion:
    return LinsightSessionVersion(id=vid, session_id=SESSION_ID, user_id=user_id, question="q")


def _share(resource_id: str, meta_data: dict | None, resource_type: ResourceTypeEnum) -> ShareLink:
    return ShareLink(
        share_token="tok-1",
        resource_id=resource_id,
        resource_type=resource_type,
        share_mode=ShareMode.READ_ONLY,
        meta_data=meta_data,
        create_user_id=str(OWNER_ID),
    )


def _login(user_id: int) -> MagicMock:
    u = MagicMock()
    u.user_id = user_id
    return u


@pytest.fixture
def two_turn_session(monkeypatch: pytest.MonkeyPatch):
    """A multi-turn task-mode conversation: two session_version rows, one per turn."""
    versions = [_version("v-turn-1"), _version("v-turn-2")]
    monkeypatch.setattr(
        linsight_ep.LinsightWorkbenchImpl,
        "get_linsight_session_version_list",
        AsyncMock(return_value=versions),
    )
    return versions


async def _call(login_user, share_link):
    return await linsight_ep.get_linsight_session_version_list(
        session_id=SESSION_ID, login_user=login_user, share_link=share_link
    )


async def test_workbench_chat_share_returns_all_turns(two_turn_session):
    """Non-owner + whole-conversation (workbench_chat) share → every turn's version.

    meta_data carries NO versionId; the old code filtered by ``None`` → empty
    list → "任务详情加载失败". The fix must return all versions.
    """
    share = _share(SESSION_ID, meta_data={}, resource_type=ResourceTypeEnum.WORKBENCH_CHAT)
    resp = await _call(_login(VIEWER_ID), share)

    assert resp.status_code == 200
    assert {row["id"] for row in resp.data} == {"v-turn-1", "v-turn-2"}


async def test_workbench_chat_share_with_flowid_only_meta(two_turn_session):
    """meta_data may carry flowId but no versionId — still return all turns."""
    share = _share(SESSION_ID, meta_data={"flowId": "f1"}, resource_type=ResourceTypeEnum.WORKBENCH_CHAT)
    resp = await _call(_login(VIEWER_ID), share)

    assert resp.status_code == 200
    assert len(resp.data) == 2


async def test_workbench_chat_share_null_meta_data_returns_all(two_turn_session):
    """Defensive: meta_data is None (model default) must not 500 and returns all."""
    share = _share(SESSION_ID, meta_data=None, resource_type=ResourceTypeEnum.WORKBENCH_CHAT)
    resp = await _call(_login(VIEWER_ID), share)

    assert resp.status_code == 200
    assert len(resp.data) == 2


async def test_linsight_session_share_narrows_to_pinned_version(two_turn_session):
    """Non-owner + single-version (linsight_session) share → only the pinned version."""
    share = _share(SESSION_ID, meta_data={"versionId": "v-turn-2"}, resource_type=ResourceTypeEnum.LINSIGHT_SESSION)
    resp = await _call(_login(VIEWER_ID), share)

    assert resp.status_code == 200
    assert [row["id"] for row in resp.data] == ["v-turn-2"]


async def test_non_owner_without_share_link_unauthorized(two_turn_session):
    """Non-owner + no share token → 403 (auth stays strict)."""
    resp = await _call(_login(VIEWER_ID), None)

    assert resp.status_code == 403


async def test_non_owner_share_link_for_other_session_unauthorized(two_turn_session):
    """Non-owner + share_link pointing at a DIFFERENT session (no valid versionId) → 403."""
    share = _share("other-session", meta_data={}, resource_type=ResourceTypeEnum.WORKBENCH_CHAT)
    resp = await _call(_login(VIEWER_ID), share)

    assert resp.status_code == 403


async def test_owner_bypasses_share_link(two_turn_session):
    """Owner always gets every version regardless of share_link (no regression)."""
    resp = await _call(_login(OWNER_ID), None)

    assert resp.status_code == 200
    assert len(resp.data) == 2
