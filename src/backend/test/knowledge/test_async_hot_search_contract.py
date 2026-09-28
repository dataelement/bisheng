"""慢模型调用期间共享事件循环必须继续推进。"""

import asyncio

import pytest

from bisheng.knowledge.domain.services.portal_hot_search_intent_service import PortalHotSearchIntentService
from bisheng.knowledge.domain.services.portal_hot_search_rewrite_service import PortalHotSearchRewriteService


@pytest.mark.parametrize("kind", ["group", "rewrite"])
async def test_native_async_model_yields_and_preserves_result(kind):
    entered, release = asyncio.Event(), asyncio.Event()

    async def invoke(prompt):
        entered.set()
        await release.wait()
        if kind == "group":
            return '{"groups":[{"canonical_query":"设备检修","members":["设备检修"]}]}'
        return "设备检修安全要求有哪些具体规定？"

    if kind == "group":
        service = PortalHotSearchIntentService(llm_ainvoke=invoke)
        task = asyncio.create_task(service.agroup(["设备检修"]))
    else:
        service = PortalHotSearchRewriteService(llm_ainvoke=invoke)
        task = asyncio.create_task(service.arewrite("设备检修安全要求"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not task.done()
        release.set()
        result = await task
        assert (not result.degraded) if kind == "group" else result[1] == "llm"
    finally:
        release.set()
        await task
