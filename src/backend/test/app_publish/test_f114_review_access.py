"""F114 source review is edit or a current, version-bound personal task."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.app_publish import AppVersionReviewForbiddenError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context import tenant


@pytest.fixture
def review_access(monkeypatch):
    from bisheng.app_publish.domain.services import snapshot_browse_service as mod

    app = SimpleNamespace(id="target", tenant_id=3, owner_user_id=81, state="draft", current_version_id="base")
    actor = SimpleNamespace(user_id=42, tenant_id=3, is_global_super=False)
    monkeypatch.setattr(mod.VersionService, "get_app_scoped", AsyncMock(return_value=app))
    monkeypatch.setattr(mod, "authorize_app", AsyncMock(side_effect=PermissionDeniedError()), raising=False)
    monkeypatch.setattr(mod, "pending_app_reviews", AsyncMock(return_value=()), raising=False)
    monkeypatch.setattr(mod, "get_current_open_api_principal", lambda: None, raising=False)
    return mod, app, actor


async def test_editor_is_not_required_to_be_original_owner(review_access):
    mod, app, actor = review_access
    mod.authorize_app.side_effect = None
    async with mod.ReviewAccess.scope(app.id, actor, ("pending",)) as (actual, role):
        assert actual is app
        assert role == "editor"


async def test_publish_only_cannot_read_source(review_access):
    mod, app, actor = review_access
    with pytest.raises(AppVersionReviewForbiddenError):
        async with mod.ReviewAccess.scope(app.id, actor, ("pending",)):
            pytest.fail("private source became readable")


async def test_valid_personal_task_ignores_view_selection_and_restores_it(review_access):
    from bisheng.approval.application.app_review import AppReviewGrant

    mod, app, actor = review_access
    mod.pending_app_reviews.return_value = (
        AppReviewGrant(tenant_id=3, app_id=app.id, version_id="pending", instance_id=7, task_id=8),
    )
    with tenant.management_tenant_scope(2):
        async with mod.ReviewAccess.scope(app.id, actor, ("pending", "base")) as (_, role):
            assert role == "approver"
            assert tenant.get_current_tenant_id() == 3
            assert not tenant.get_is_management_api()
        assert tenant.get_current_tenant_id() == 2


async def test_task_does_not_open_unrelated_version(review_access):
    from bisheng.approval.application.app_review import AppReviewGrant

    mod, app, actor = review_access
    mod.pending_app_reviews.return_value = (AppReviewGrant(3, app.id, "pending", 7, 8),)
    with pytest.raises(AppVersionReviewForbiddenError):
        async with mod.ReviewAccess.scope(app.id, actor, ("pending", "unrelated")):
            pytest.fail("task opened an unrelated snapshot")


async def test_service_account_cannot_borrow_owners_personal_task(review_access, monkeypatch):
    mod, app, actor = review_access
    monkeypatch.setattr(mod, "get_current_open_api_principal", lambda: SimpleNamespace(actor_kind="service_account"))
    with pytest.raises(AppVersionReviewForbiddenError):
        async with mod.ReviewAccess.scope(app.id, actor, ("pending",)):
            pytest.fail("service account borrowed a personal task")
    mod.pending_app_reviews.assert_not_awaited()
