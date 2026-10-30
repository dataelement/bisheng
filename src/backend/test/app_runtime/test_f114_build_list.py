"""The mixed build list preserves non-Vibe actions and exposes all Vibe management actions."""

from unittest.mock import AsyncMock


async def test_hosted_management_summary_is_or_not_edit_only(monkeypatch):
    from bisheng.api.services.workflow import WorkFlowService
    from bisheng.app_runtime.application import authorization
    from bisheng.database.models.flow import FlowType

    rows = [
        {"id": "publish-only", "flow_type": FlowType.HOSTED_APP.value},
        {"id": "use-only", "flow_type": FlowType.HOSTED_APP.value},
        {"id": "workflow", "flow_type": 10},
    ]
    monkeypatch.setattr(
        authorization, "management_actions_for_ids", AsyncMock(return_value={"publish-only": frozenset({"publish"})})
    )
    await WorkFlowService._managed_hosted_actions(object(), rows)
    assert WorkFlowService._managed_visible(rows[0], {}, "edit")
    assert not WorkFlowService._managed_visible(rows[1], {}, "edit")
    assert not WorkFlowService._managed_visible(rows[2], {"workflow": frozenset({"use"})}, "edit")
    assert WorkFlowService._managed_visible(rows[2], {"workflow": frozenset({"edit"})}, "edit")
    assert rows[0]["allowed_actions"] == ["publish"]
