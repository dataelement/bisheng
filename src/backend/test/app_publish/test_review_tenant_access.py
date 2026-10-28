"""F113 R2: independent publish/source reads cannot bypass tenant admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
from bisheng.app_publish.domain.services.snapshot_browse_service import ReviewAccess, SnapshotBrowseService
from bisheng.app_publish.domain.services.version_diff_service import VersionDiffService
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.app_publish import AppVersionReviewForbiddenError


def caller(tenant=1, user_id=21, is_super=False):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant, is_global_super=is_super)


def target():
    return SimpleNamespace(id="f113", tenant_id=1, owner_user_id=21)


async def test_publish_status_refuses_before_assembling_private_versions(monkeypatch):
    monkeypatch.setattr(PublishStatusService, "_load", AsyncMock(return_value=target()))
    load = AsyncMock(side_effect=AssertionError("Foreign deployment details were loaded"))
    monkeypatch.setattr(PublishStatusService, "_latest_deployment", load)
    with pytest.raises(AppNotFoundError):
        await PublishStatusService.get_publish_status("f113", actor=caller(2))
    load.assert_not_awaited()


@pytest.mark.parametrize("entry", ["tree", "file", "context", "diff"])
async def test_old_version_references_refuse_before_snapshot_or_version_read(monkeypatch, entry):
    monkeypatch.setattr(ReviewAccess, "load_app", AsyncMock(return_value=target()))
    version = AsyncMock(side_effect=AssertionError("Foreign version was read"))
    storage = AsyncMock(side_effect=AssertionError("Foreign source was downloaded"))
    monkeypatch.setattr(SnapshotBrowseService, "load_version", version)
    monkeypatch.setattr(SnapshotBrowseService, "load_snapshot_bytes", storage)
    with pytest.raises((AppNotFoundError, AppVersionReviewForbiddenError)):
        if entry == "tree":
            await SnapshotBrowseService.list_tree("f113", "v1", actor=caller(2))
        elif entry == "file":
            await SnapshotBrowseService.read_file("f113", "v1", "main.py", actor=caller(2))
        elif entry == "context":
            await SnapshotBrowseService.review_context("f113", "v1", actor=caller(2))
        else:
            await VersionDiffService.diff("f113", "v1", "v2", actor=caller(2))
    version.assert_not_awaited()
    storage.assert_not_awaited()


@pytest.mark.parametrize("role", ["owner", "approver", "stranger", "super", "moved_approver"])
async def test_review_roles_do_not_gain_or_lose_same_tenant_permissions(monkeypatch, role):
    from bisheng.app_publish.domain.services import snapshot_browse_service as module

    monkeypatch.setattr(module, "check_tenant_admin", AsyncMock(return_value=False))
    holds = AsyncMock(return_value=role in {"approver", "moved_approver"})
    monkeypatch.setattr(ReviewAccess, "_holds_task", holds)
    actor = caller(
        tenant=2 if role in {"super", "moved_approver"} else 1,
        user_id=21 if role == "owner" else 22,
        is_super=role == "super",
    )
    if role in {"stranger", "moved_approver"}:
        with pytest.raises((AppNotFoundError, AppVersionReviewForbiddenError)):
            await ReviewAccess.require(target(), actor, ("v1", "v2"))
        if role == "moved_approver":
            holds.assert_not_awaited()
    else:
        actual = await ReviewAccess.require(target(), actor, ("v1", "v2"))
        assert actual == {"owner": "owner", "approver": "approver", "super": "super_admin"}[role]
