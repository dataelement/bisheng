"""请求作用域与并发隔离（AC-07 / AC-09）。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from bisheng_sdk import auth
from bisheng_sdk.errors import PlatformIdentityMissingError
from tests.helpers.platform_mock import hosted_headers


async def test_two_concurrent_requests_do_not_leak_into_each_other():
    async def handle(user_id: str) -> str:
        with auth.bind(hosted_headers(user_id=user_id)):
            await asyncio.sleep(0)  # 交出控制权：串扰就在这一刻发生
            return auth.current_user().user_id

    assert await asyncio.gather(handle("1"), handle("2")) == ["1", "2"]


def test_thread_pool_worker_has_no_identity():
    """后台线程没有访问者——这是 ContextVar 的语义，也正是我们要的行为。"""

    def work() -> str:
        try:
            auth.current_user()
        except PlatformIdentityMissingError:
            return "refused"
        return "leaked"

    with auth.bind(hosted_headers()):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(work).result() == "refused"


async def test_created_task_inherits_a_copy_of_the_request_context():
    """`asyncio.create_task` 复制父上下文——记录这条语义，不是 SDK 的兜底。

    于是请求里 `create_task` 出去的后台任务**能**拿到身份并检索。指南因此写明
    「后台任务不要假设有访问者」，SDK 不额外清空副本（清空会破坏 FastAPI 依赖
    注入的正常任务树）。
    """

    async def child() -> str:
        return auth.current_user().user_id

    with auth.bind(hosted_headers(user_id="7")):
        assert await asyncio.create_task(child()) == "7"


def test_nested_bind_restores_the_outer_identity():
    with auth.bind(hosted_headers(user_id="1")):
        with auth.bind(hosted_headers(user_id="2")):
            assert auth.current_user().user_id == "2"
        assert auth.current_user().user_id == "1"
    with pytest.raises(PlatformIdentityMissingError):
        auth.current_user()
