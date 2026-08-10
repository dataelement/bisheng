from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
    ResourceUserInviteScenarioHandler,
)


async def test_invite_preset_and_runtime_registered():
    preset = ApprovalRegistry.with_default_presets().get_preset("resource_user_invite_confirmation")
    handler = await build_runtime_handler("resource_user_invite_confirmation")

    assert preset is not None
    assert preset.approver_source_types == ["invited_user"]
    assert isinstance(handler, ResourceUserInviteScenarioHandler)
