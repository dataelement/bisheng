"""A cancelled model call (probe timeout, closed request) must not be recorded
as a success, and must not mark the model normal on the way out."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.constants.enums.telemetry import StatusEnum
from bisheng.llm.domain import utils as llm_utils
from bisheng.llm.domain.const import LLMModelStatus


def _fake_model():
    return SimpleNamespace(model_info=SimpleNamespace(model_type="llm"), update_model_status=AsyncMock())


@pytest.fixture
def telemetry():
    upload = MagicMock()
    with (
        patch.object(llm_utils, "bisheng_model_limit_check", AsyncMock()),
        patch.object(llm_utils, "upload_telemetry_log", upload),
    ):
        yield upload


async def test_cancelled_call_is_recorded_as_failed(telemetry):
    started = asyncio.Event()

    @llm_utils.wrapper_bisheng_model_limit_check_async
    async def hang(self):
        started.set()
        await asyncio.sleep(3600)

    model = _fake_model()
    task = asyncio.create_task(hang(model))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert telemetry.call_args.args[4] == StatusEnum.FAILED
    model.update_model_status.assert_not_awaited()


async def test_successful_call_still_marks_the_model_normal(telemetry):
    @llm_utils.wrapper_bisheng_model_limit_check_async
    async def ok(self):
        return "hi"

    model = _fake_model()
    assert await ok(model) == "hi"
    assert telemetry.call_args.args[4] == StatusEnum.SUCCESS
    model.update_model_status.assert_awaited_once_with(LLMModelStatus.NORMAL.value, "")
