"""A create whose target is proven absent may be replayed; nothing else may."""

from types import SimpleNamespace

import httpx
import pytest

from bisheng.knowledge.application import provider_provision_runtime as runtime
from bisheng.knowledge.application.provider_provisioning import (
    ProviderProvisioning,
    ProviderTargetAbsent,
)


class _Remote:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def read_library(self, _op):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _App:
    async def authorize(self, *_args):
        return True

    async def project(self, _op):
        return "confirmed"


def _op(kind="create_space", name="space"):
    return SimpleNamespace(
        tenant_id=1,
        actor_user_id=9,
        kind=kind,
        space_id=11,
        operation_id="op",
        remote_kb_id="kb",
        provider_instance_id=1,
        remote_scope_id="10000",
        capability_revision=1,
        target_manifest=[{"name": name, "department_id": None, "config": {"type": "document"}}],
    )


def _service(remote):
    return ProviderProvisioning(
        repo=SimpleNamespace(), remote=remote, authorize=_App().authorize, project_grants=_App().project
    )


async def test_absent_target_replays_a_create():
    remote = _Remote(ProviderTargetAbsent("provider target not found"))
    assert await _service(remote).reconcile(_op()) == "verified_safe_replay"
    assert remote.calls == 1


async def test_absent_target_never_replays_a_settings_write():
    remote = _Remote(ProviderTargetAbsent("provider target not found"))
    with pytest.raises(ProviderTargetAbsent):
        await _service(remote).reconcile(_op(kind="update_space_settings"))


@pytest.mark.parametrize("error", [ConnectionError("provider receipt unavailable"), TimeoutError()])
async def test_a_dropped_or_slow_read_stays_unknown(error):
    assert await _service(_Remote(error)).reconcile(_op()) == "unknown"


def test_a_404_response_is_reported_as_a_definitive_absence(monkeypatch):
    """404 must not be folded into the generic 'evidence unavailable' failure."""

    class Client:
        timeout = httpx.Timeout(5)

        async def request(self, *_args, **_kwargs):
            return httpx.Response(404, json={"success": False})

    import asyncio

    with pytest.raises(ProviderTargetAbsent):
        asyncio.run(runtime._data(Client(), "GET", "knowledge-bases/kb"))
