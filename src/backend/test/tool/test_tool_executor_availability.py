"""Exercise runtime guards with provider calls and telemetry isolated."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.tool.domain.services.executor import ToolExecutor


class ToolAvailabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.availability = SimpleNamespace(ensure_enabled=AsyncMock(), ensure_enabled_sync=Mock())
        self.service = patch("bisheng.tool.domain.services.executor.UserToolAvailabilityService", return_value=self.availability)
        self.service.start()
        self.addCleanup(self.service.stop)
        self.tool = SimpleNamespace(
            tool_id=7, tool_key="example", tool_is_preset=1, user_id=42,
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            tool_instance=SimpleNamespace(_run=Mock(return_value="ok"), _arun=AsyncMock(return_value="ok")),
        )

    async def test_all_tool_kinds_recheck_account_state_on_every_call(self):
        for app in (ApplicationTypeEnum.DAILY_CHAT, ApplicationTypeEnum.LINSIGHT, ApplicationTypeEnum.DSH_DESKTOP):
            for kind in (0, 1, 2):
                with self.subTest(app=app, kind=kind):
                    self.tool.app_type, self.tool.tool_is_preset = app, kind
                    self.availability.ensure_enabled.side_effect = None
                    self.availability.ensure_enabled_sync.side_effect = None
                    self.assertEqual(await ToolExecutor._arun.__wrapped__(self.tool, config={}), "ok")
                    self.assertEqual(ToolExecutor._run.__wrapped__(self.tool, config={}), "ok")
                    self.tool.tool_instance._run.reset_mock()
                    self.tool.tool_instance._arun.reset_mock()
                    self.availability.ensure_enabled.side_effect = PermissionError("disabled")
                    self.availability.ensure_enabled_sync.side_effect = PermissionError("disabled")
                    with self.assertRaises(PermissionError):
                        await ToolExecutor._arun.__wrapped__(self.tool, config={})
                    with self.assertRaises(PermissionError):
                        ToolExecutor._run.__wrapped__(self.tool, config={})
                    self.tool.tool_instance._run.assert_not_called()
                    self.tool.tool_instance._arun.assert_not_awaited()

    async def test_published_apps_keep_their_own_configuration(self):
        self.availability.ensure_enabled.side_effect = PermissionError("disabled")
        self.availability.ensure_enabled_sync.side_effect = PermissionError("disabled")
        for app in (ApplicationTypeEnum.WORKFLOW, ApplicationTypeEnum.ASSISTANT):
            self.tool.app_type = app
            self.assertEqual(await ToolExecutor._arun.__wrapped__(self.tool, config={}), "ok")
            self.assertEqual(ToolExecutor._run.__wrapped__(self.tool, config={}), "ok")
        self.availability.ensure_enabled.assert_not_awaited()
        self.availability.ensure_enabled_sync.assert_not_called()

    def test_disabled_selection_is_rejected_before_provider_initialization(self):
        self.availability.ensure_enabled_sync.side_effect = PermissionError("disabled")
        with patch.object(ToolExecutor, "_init_by_tool_and_type") as initialize:
            with self.assertRaises(PermissionError):
                ToolExecutor._init_by_tool_and_type_with_context(
                    SimpleNamespace(id=7, is_preset=2), SimpleNamespace(), app_id="test",
                    app_name="test", app_type=ApplicationTypeEnum.DSH_DESKTOP, user_id=42,
                )
            initialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
