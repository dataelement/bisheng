"""Legacy list protocol labels reach the sole visibility authorization facade.

覆盖 AC: AC-37, AC-68. Keeping the wire label never restores a Catalog action.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services import workflow as workflow_service
from bisheng.common.services.config_service import settings
from bisheng.database.models.flow import FlowType
from bisheng.permission.application import business_authorization as authorization
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.catalog_policy import REGISTERED_ACTION_CODES
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def visibility_facade(monkeypatch):
    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    decisions = []

    async def resolve(*, resource_type, resource_id, actor, action):
        assert action == "visible"
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=101,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=1,
            context_version="test-business-context",
        )

    async def check(actor, targets, action):
        decisions.append((action, tuple(target.resource_type for target in targets)))
        return tuple(True for target in targets)

    runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=check))
    monkeypatch.setattr(
        authorization, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(tenant_id=101, user_id=11))
    )
    monkeypatch.setattr(
        authorization, "get_f048_resource_registry", AsyncMock(return_value=SimpleNamespace(resolve=resolve))
    )
    monkeypatch.setattr(authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    # Deliberately retain the real facade: a list-local alias must never become
    # a direct or unconditional permission grant.
    monkeypatch.setattr(workflow_service, "batch_check_business_actions", authorization.batch_check_business_actions)
    assert "use" not in REGISTERED_ACTION_CODES
    return SimpleNamespace(
        user=SimpleNamespace(user_id=11, tenant_id=101),
        decisions=decisions,
        runtime=runtime,
    )


async def test_default_legacy_use_filter_keeps_visible_resources_via_real_facade(visibility_facade):
    rows = [
        {"id": "wf", "flow_type": FlowType.WORKFLOW.value},
        {"id": "asst", "flow_type": FlowType.ASSISTANT.value},
        {"id": "app", "flow_type": FlowType.HOSTED_APP.value},
    ]
    assert await workflow_service.WorkFlowService.filter_apps_by_action(visibility_facade.user, rows) == rows
    assert len(visibility_facade.decisions) == 3
    assert all(action == "visible" for action, _ in visibility_facade.decisions)


async def test_hosted_card_legacy_use_bucket_is_checked_as_visible(visibility_facade, monkeypatch):
    row = {"id": "app", "flow_type": FlowType.HOSTED_APP.value}
    monkeypatch.setattr(workflow_service.FlowDao, "aget_all_apps", AsyncMock(return_value=([row], False)))
    monkeypatch.setattr(workflow_service.WorkFlowService, "_attach_hosted_app_entry_fields", AsyncMock())
    items, has_more, actions = await workflow_service.WorkFlowService._scan_visible_apps_cursor(
        user=visibility_facade.user, page_size=10, additional_actions=()
    )
    assert items == [row] and not has_more
    assert actions == {"app": frozenset({"use"})}
    assert visibility_facade.decisions == [("visible", ("app",))]


async def test_legacy_label_still_denies_when_visibility_facade_denies(visibility_facade):
    visibility_facade.runtime.batch_check_actions.side_effect = None
    visibility_facade.runtime.batch_check_actions.return_value = (False,)
    rows = [{"id": "wf", "flow_type": FlowType.WORKFLOW.value}]
    assert await workflow_service.WorkFlowService.filter_apps_by_action(visibility_facade.user, rows) == []
    visibility_facade.runtime.batch_check_actions.assert_awaited_once()
    assert visibility_facade.runtime.batch_check_actions.call_args.args[2] == "visible"
