"""Publication orchestration: current state, permissions, shared admission and cleanup."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import (
    DshToolArgumentsInvalidError,
    DshToolExecutionTimeoutError,
    DshToolInputTooLargeError,
    DshToolPublicationNotFoundError,
)
from bisheng.dsh.domain.schemas.tool_publications import ToolPublication
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.tool_publications import ToolPublicationService


def publication(**updates):
    return ToolPublication(tool_id=7, tool_code="bs_web_search", enabled=True, revision=1).model_copy(update=updates)


@pytest.fixture
def service():
    record = SimpleNamespace(publication=publication(), created=False)

    @asynccontextmanager
    async def locked(*args, **kwargs):
        yield record

    repository = SimpleNamespace(locked=locked)
    tools = SimpleNamespace(prepare=AsyncMock(return_value=(object(), {"query": "hello"})))
    tools.execute = AsyncMock(return_value='{"results":[],"truncated":false}')
    leases = SimpleNamespace(acquire=AsyncMock(return_value="owner"), release=AsyncMock())
    instance = ToolPublicationService(repository, tools, leases)
    instance.record = record
    return instance


def principal():
    return DshPrincipal(tenant_id="2", user_id="3", seat_id="s", session_id="x", grant_version=1)


async def test_invoke_and_release(service):
    assert await service.invoke(principal(), "bs_web_search", {"query": " hello "}, 40) == {
        "tool": "bs_web_search",
        "result": {"results": [], "truncated": False},
    }
    service.leases.acquire.assert_awaited_once_with(2, "bs_web_search", 4)
    service.leases.release.assert_awaited_once_with(2, "bs_web_search", "owner")


async def test_disabled_never_admitted(service):
    service.record.publication = publication(enabled=False)
    with pytest.raises(DshToolPublicationNotFoundError):
        await service.invoke(principal(), "bs_web_search", {"query": "x"}, 40)
    service.leases.acquire.assert_not_awaited()


@pytest.mark.parametrize("arguments", [{"query": " "}, {"query": "x", "maxResults": True}, {"query": 1}])
async def test_search_business_input(service, arguments):
    with pytest.raises(DshToolArgumentsInvalidError):
        await service.invoke(principal(), "bs_web_search", arguments, 40)
    service.leases.acquire.assert_not_awaited()


async def test_cancellation_releases(service):
    started = asyncio.Event()

    async def block(*args):
        started.set()
        await asyncio.Event().wait()

    service.tools.execute.side_effect = block
    task = asyncio.create_task(service.invoke(principal(), "bs_web_search", {"query": "x"}, 40))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    service.leases.release.assert_awaited_once()


async def test_body_time_is_included_in_configured_deadline(service):
    """AC-27, AC-29: configured deadline starts before body reading, not after it."""

    async def prepare(*args):
        await asyncio.sleep(0)
        return object(), {"query": "x"}

    service.tools.prepare.side_effect = prepare
    with pytest.raises(DshToolExecutionTimeoutError):
        await service.invoke(
            principal(), "bs_web_search", {"query": "x"}, 40, started_at=asyncio.get_running_loop().time() - 31
        )
    service.leases.acquire.assert_not_awaited()


async def test_configured_input_cap(service):
    """AC-27: a publication can tighten the global input cap."""
    service.record.publication = publication(limits=publication().limits.model_copy(update={"max_input_bytes": 10}))
    with pytest.raises(DshToolInputTooLargeError):
        await service.invoke(principal(), "bs_web_search", {"query": "x"}, 40)
    service.tools.prepare.assert_not_awaited()


async def test_inherited_admin_and_bypass_are_cleared(service):
    """AC-10, AC-11: root/admin visibility cannot widen the verified tenant."""
    from bisheng.core.context import tenant

    async def prepare(*args):
        assert tenant.get_current_tenant_id() == 2
        assert not tenant.is_tenant_filter_bypassed()
        assert tenant.is_strict_tenant_filter()
        return object(), {"query": "x"}

    service.tools.prepare.side_effect = prepare
    tokens = [tenant.set_admin_scope_tenant_id(99), tenant._bypass_tenant_filter.set(True)]
    try:
        await service.invoke(principal(), "bs_web_search", {"query": "x"}, 40)
        assert tenant.get_current_tenant_id() == 99 and tenant.is_tenant_filter_bypassed()
    finally:
        for item in reversed(tokens):
            item.var.reset(item)
