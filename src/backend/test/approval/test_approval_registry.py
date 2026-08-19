import pytest

from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler


async def test_invite_preset_remains_but_legacy_runtime_handler_is_removed():
    preset = ApprovalRegistry.with_default_presets().get_preset("resource_user_invite_confirmation")

    assert preset is not None
    assert preset.approver_source_types == ["invited_user"]
    with pytest.raises(KeyError, match="resource_user_invite_confirmation"):
        await build_runtime_handler("resource_user_invite_confirmation")
